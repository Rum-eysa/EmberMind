"""Unified, immutable audit ledger service (EM-096, Epic E10).

Managers need a single, accountable trail of who decided or changed what, when -
across every subsystem - and that trail must not be editable or deletable after
the fact (EM-096 acceptance: "kabul/ret, senaryo, eşik/kapasite varsayımı
değişiklikleri kim/ne zaman/ne ile kaydedilir. Kayıtlar silinemez").

The surface here is intentionally tiny and *append-mostly*:

* ``record_audit`` validates the controlled vocabularies and writes exactly one
  immutable row (the "how" is the old -> new value snapshot plus a summary).
* ``list_audit`` reads the trail back newest-first with optional filters.
* ``audit_config`` exposes the domain / action catalog and the immutability
  policy so the UI and integrators speak the same vocabulary.

There is **no** ``update`` / ``delete`` / ``purge`` function anywhere in this
module - that absence *is* the "kayıtlar silinemez" guarantee at the application
seam. Recording is additive and never rewrites the per-feature histories from
earlier epics.
"""
import json
import secrets
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.audit_trail import AuditTrailEntry

# The accountability domains the ledger knows about (EM-096 names decisions,
# scenarios and threshold/capacity assumptions; we add the other governance
# surfaces that already produce accountable edits so nothing is orphaned).
AUDIT_DOMAINS: tuple[str, ...] = (
    "recommendation",  # accept / reject / edit (EM-047 lineage)
    "capacity_assumption",  # ha/hour edits (EM-034 lineage)
    "threshold",  # risk / silent-zone threshold changes (EM-032/EM-044)
    "scenario",  # what-if / synthetic scenario governance
    "share_policy",  # country data-sharing policy edits (EM-070)
    "webhook",  # outbound integration subscription changes (EM-094)
    "user_management",  # account add / edit / role / deactivate (EM-101)
    "general",  # any other governance-relevant action
)

# Controlled verbs. A domain may use any of them; the value semantics are
# carried in the old/new snapshots, not the verb.
AUDIT_ACTIONS: tuple[str, ...] = (
    "create",
    "update",
    "delete",
    "accept",
    "reject",
    "edit",
    "enable",
    "disable",
    "publish",
)

AUDIT_IMMUTABLE = True
AUDIT_ATTRIBUTION = (
    "EM-096: birleşik denetim kaydı — kim / ne zaman / hangi karar / hangi "
    "değişim; kayıtlar değişmez ve silinemez (servis yüzeyinde güncel/sil yok)"
)

# A subject and a summary are bounded to the model's column widths.
_MAX_SUMMARY = 255
_MAX_SUBJECT = 96


class AuditError(ValueError):
    """Raised for an invalid audit entry (bad vocabulary, missing fields)."""


def _dump(value: Any) -> str:
    """Serialise a value snapshot to JSON text; never raises on odd types."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return json.dumps(str(value))


def _clean_text(value: Any, field: str, max_len: int) -> str:
    text = str(value).strip()
    if not text:
        raise AuditError(f"{field} boş olamaz")
    return text[:max_len]


def record_audit(
    session: Session,
    settings: Any,
    domain: str,
    action: str,
    actor: str,
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one immutable accountability row and return its ``as_dict``.

    ``detail`` may carry ``subject_key``, ``summary``, ``old_value`` and
    ``new_value``. The domain and action must belong to the controlled
    vocabularies and the actor is mandatory - that is the "kim" the ledger can
    never infer on its own.
    """
    domain = str(domain).strip()
    action = str(action).strip()
    if domain not in AUDIT_DOMAINS:
        raise AuditError(f"bilinmeyen denetim alanı: {domain}")
    if action not in AUDIT_ACTIONS:
        raise AuditError(f"bilinmeyen denetim eylemi: {action}")
    payload = detail or {}
    actor_clean = _clean_text(actor, "actor", 64)
    subject_key = payload.get("subject_key")
    subject_clean = (
        _clean_text(subject_key, "subject_key", _MAX_SUBJECT) if subject_key else None
    )
    summary = _clean_text(
        payload.get("summary") or f"{domain}.{action}", "summary", _MAX_SUMMARY
    )

    entry = AuditTrailEntry(
        audit_key=f"aud-{secrets.token_hex(8)}",
        domain=domain,
        action=action,
        subject_key=subject_clean,
        actor=actor_clean,
        summary=summary,
        old_value_json=_dump(payload.get("old_value")),
        new_value_json=_dump(payload.get("new_value")),
    )
    session.add(entry)
    session.flush()
    return dict(entry.as_dict)


def list_audit(
    session: Session,
    settings: Any,
    *,
    domain: Optional[str] = None,
    actor: Optional[str] = None,
    subject_key: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Read the unified trail newest-first, optionally scoped by a filter.

    Reading never writes: the ledger is not seeded, so an untouched system
    returns an empty list. ``limit`` is clamped between 1 and the configured
    ``AUDIT_MAX_LIMIT``.
    """
    max_limit = int(getattr(settings, "AUDIT_MAX_LIMIT", 500))
    default_limit = int(getattr(settings, "AUDIT_DEFAULT_LIMIT", 50))
    page_limit = default_limit if limit is None else max(1, min(int(limit), max_limit))

    filters = []
    if domain:
        filters.append(AuditTrailEntry.domain == str(domain))
    if actor:
        filters.append(AuditTrailEntry.actor == str(actor))
    if subject_key:
        filters.append(AuditTrailEntry.subject_key == str(subject_key))

    stmt = select(AuditTrailEntry).order_by(AuditTrailEntry.id.desc())
    count_stmt = select(func.count()).select_from(AuditTrailEntry)
    for condition in filters:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(session.scalar(count_stmt) or 0)
    rows = session.scalars(stmt.limit(page_limit)).all()
    return {
        "limit": page_limit,
        "filters": {
            "domain": domain,
            "actor": actor,
            "subject_key": subject_key,
        },
        "total_matching": total,
        "immutable": AUDIT_IMMUTABLE,
        "entries": [row.as_dict for row in rows],
        "attribution": AUDIT_ATTRIBUTION,
    }


def audit_config(settings: Any = None) -> dict[str, Any]:
    """The controlled vocabularies and immutability policy the surfaces share."""
    return {
        "domains": list(AUDIT_DOMAINS),
        "actions": list(AUDIT_ACTIONS),
        "immutable": AUDIT_IMMUTABLE,
        "default_limit": int(getattr(settings, "AUDIT_DEFAULT_LIMIT", 50)),
        "max_limit": int(getattr(settings, "AUDIT_MAX_LIMIT", 500)),
        "attribution": AUDIT_ATTRIBUTION,
        "persistence": "append_only",
    }


def count_by_domain(session: Session) -> dict[str, int]:
    """Entry count per domain, for the panel's at-a-glance summary."""
    rows = session.execute(
        select(AuditTrailEntry.domain, func.count())
        .group_by(AuditTrailEntry.domain)
        .order_by(AuditTrailEntry.domain)
    ).all()
    return {str(domain): int(count) for domain, count in rows}


__all__ = [
    "AUDIT_ACTIONS",
    "AUDIT_DOMAINS",
    "AUDIT_ATTRIBUTION",
    "AUDIT_IMMUTABLE",
    "AuditError",
    "audit_config",
    "count_by_domain",
    "list_audit",
    "record_audit",
]
