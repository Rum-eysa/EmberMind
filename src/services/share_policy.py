"""Country / role data-sharing authorization policy (EM-070, Epic E7).

An administrator decides, once and durably, **which field groups of their own
country's data are allowed to cross the border to the partner** - so sovereignty
and privacy limits are the default, not something a coordinator has to remember
to request per call (that per-request knob is EM-066). A policy is keyed by the
owner country (``TR`` / ``GR``) and a role scope (``*`` = the country default,
or a named role such as ``operator`` / ``coordinator``), and holds a subset of
the shared field groups ``fire`` / ``risk`` / ``support``.

Resolution precedence (most specific wins):

1. an explicit ``(country, role)`` policy;
2. the ``(country, "*")`` country default policy;
3. the configured ``SHARE_POLICY_DEFAULT_FIELDS`` (falls back to sharing all).

Every change is written append-only to :class:`CountrySharePolicy` with the
value it replaced, so the effective policy and its full audit trail come from
the same table (criterion: "Politika değişiklikleri denetim kaydına yazılır").
A ``preview`` renders exactly what the partner would see before it is applied.
"""
from __future__ import annotations

import secrets
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.share_policy import CountrySharePolicy
from src.services.crossborder_situation import (
    COUNTRIES,
    COUNTRY_LABELS,
    SHAREABLE_FIELD_GROUPS,
)
from src.utils.timeutils import to_utc_iso, utc_now

# ``*`` is the per-country default role every other role inherits from.
DEFAULT_ROLE = "*"
_DEFAULT_SHARED_FIELDS = "fire,risk,support"

SHARE_POLICY_ATTRIBUTION = (
    "EM-070: ülke ve rol bazlı veri paylaşım politikası (yangın/risk/destek); "
    "her değişiklik ek-yazılımlı denetim satırı olarak country_share_policy'de "
    "saklanır; en yeni satır geçerli politikadır."
)
SHARE_POLICY_PERSISTENCE = "country_share_policy"


class SharePolicyError(ValueError):
    """Raised for an invalid country, role or field-group selection."""


def _normalize_fields(raw: Any) -> list[str]:
    """Coerce a str / sequence into a canonical, validated field-group subset.

    An empty selection is legal (it means "share nothing"); an unknown token is
    rejected so a typo can never silently widen a border data grant.
    """
    if isinstance(raw, str):
        tokens = [tok.strip().lower() for tok in raw.split(",")]
    elif isinstance(raw, Sequence):
        tokens = [str(tok).strip().lower() for tok in raw]
    elif raw is None:
        tokens = []
    else:  # pragma: no cover - defensive
        tokens = [str(raw).strip().lower()]
    chosen = [tok for tok in tokens if tok]
    unknown = [tok for tok in chosen if tok not in SHAREABLE_FIELD_GROUPS]
    if unknown:
        raise SharePolicyError(
            f"unknown data-sharing field(s): {', '.join(sorted(set(unknown)))}; "
            f"valid fields are {', '.join(SHAREABLE_FIELD_GROUPS)}"
        )
    return [grp for grp in SHAREABLE_FIELD_GROUPS if grp in chosen]


def _resolve_country(country: Any) -> str:
    """Upper-case and validate an owner country code against the pilot set."""
    code = str(country or "").strip().upper()
    if code not in COUNTRIES:
        raise SharePolicyError(
            f"unknown country {country!r}; expected one of {', '.join(COUNTRIES)}"
        )
    return code


def _resolve_role(role: Any) -> str:
    """Trim a role scope to text; empty / ``None`` becomes the ``*`` default."""
    text = str(role or "").strip().lower()
    return text or DEFAULT_ROLE


def _default_fields(settings: Any) -> list[str]:
    """The configured fallback scope when no policy row exists."""
    raw = getattr(settings, "SHARE_POLICY_DEFAULT_FIELDS", _DEFAULT_SHARED_FIELDS)
    return _normalize_fields(raw)


def _latest_row(
    session: Session, country: str, role: str
) -> Optional[CountrySharePolicy]:
    """Newest stored policy for one exact ``(country, role)`` key."""
    return session.scalar(
        select(CountrySharePolicy)
        .where(
            CountrySharePolicy.viewer_country == country,
            CountrySharePolicy.role == role,
        )
        .order_by(CountrySharePolicy.id.desc())
        .limit(1)
    )


def resolve_effective(
    session: Session, settings: Any, country: str, role: str
) -> dict[str, Any]:
    """The active policy for ``(country, role)`` with its resolution source.

    Walks explicit-role -> country-default -> configured default, reporting
    which layer produced the answer so the UI can badge "inherited" vs "set".
    """
    code = _resolve_country(country)
    scope = _resolve_role(role)
    row = _latest_row(session, code, scope)
    if row is not None:
        return {
            "shared_fields": _normalize_fields(row.shared_fields),
            "source": "role_policy" if scope != DEFAULT_ROLE else "country_default",
        }
    fallback = _latest_row(session, code, DEFAULT_ROLE)
    if fallback is not None and scope != DEFAULT_ROLE:
        return {
            "shared_fields": _normalize_fields(fallback.shared_fields),
            "source": "country_default",
        }
    return {"shared_fields": _default_fields(settings), "source": "configured_default"}


def effective_shared_fields(
    session: Session, settings: Any, country: str, role: str = DEFAULT_ROLE
) -> list[str]:
    """Just the active field groups for one country / role (convenience)."""
    return resolve_effective(session, settings, country, role)["shared_fields"]


def preview_sharing(
    session: Session, settings: Any, country: str, role: str = DEFAULT_ROLE
) -> dict[str, Any]:
    """Show exactly what the partner would see for this scope (no writes)."""
    code = _resolve_country(country)
    scope = _resolve_role(role)
    resolved = resolve_effective(session, settings, code, scope)
    shared = resolved["shared_fields"]
    denied = [grp for grp in SHAREABLE_FIELD_GROUPS if grp not in shared]
    label = COUNTRY_LABELS.get(code, code)
    message = (
        f"{label} ({scope}) verilerinden karşı ülke yalnız "
        f"{', '.join(shared) if shared else 'hiçbir alan grubu'} gruplarını görür."
    )
    return {
        "viewer_country": code,
        "country_label": label,
        "role": scope,
        "shared_fields": shared,
        "denied_fields": denied,
        "source": resolved["source"],
        "message": message,
    }


def set_policy(
    session: Session,
    settings: Any,
    country: str,
    role: str,
    shared_fields: Any,
    changed_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Append one policy change (audit row) and return its effect.

    The value this change replaces is the *current effective* scope for the key
    (walking stored rows then the configured default), captured before the
    insert, so the audit series reads as a chain of ``before -> after``
    transitions even across role inheritance.
    """
    code = _resolve_country(country)
    scope = _resolve_role(role)
    fields = _normalize_fields(shared_fields)
    before = effective_shared_fields(session, settings, code, scope)

    row = CountrySharePolicy(
        policy_key=f"sp-{secrets.token_hex(6)}",
        viewer_country=code,
        role=scope,
        shared_fields=",".join(fields),
        previous_shared_fields=",".join(before),
        changed_by=_clean(changed_by, 64),
        reason=_clean(reason, 255),
    )
    session.add(row)
    session.flush()
    return {
        "policy": row.as_dict,
        "changed": before != fields,
        "shared_fields_before": before,
        "shared_fields_after": fields,
    }


def audit_trail(
    session: Session,
    country: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Policy change history (newest first), optionally filtered."""
    query = select(CountrySharePolicy).order_by(CountrySharePolicy.id.desc())
    if country:
        query = query.where(
            CountrySharePolicy.viewer_country == _resolve_country(country)
        )
    if role:
        query = query.where(CountrySharePolicy.role == _resolve_role(role))
    rows = session.scalars(query.limit(max(1, int(limit)))).all()
    return [row.as_dict for row in rows]


def policy_matrix(session: Session, settings: Any) -> dict[str, Any]:
    """Every country's default + named-role effective policies (for the UI)."""
    countries: list[dict[str, Any]] = []
    for code in COUNTRIES:
        role_rows = session.scalars(
            select(CountrySharePolicy.role)
            .where(CountrySharePolicy.viewer_country == code)
            .distinct()
        ).all()
        roles = {DEFAULT_ROLE, *(str(r) for r in role_rows)}
        entries = []
        for role in sorted(roles):
            resolved = resolve_effective(session, settings, code, role)
            entries.append(
                {
                    "role": role,
                    "shared_fields": resolved["shared_fields"],
                    "source": resolved["source"],
                    "explicit": _latest_row(session, code, role) is not None,
                }
            )
        countries.append(
            {
                "country": code,
                "label": COUNTRY_LABELS.get(code, code),
                "roles": entries,
            }
        )
    return {
        "panel": "share_policy",
        "generated_at": to_utc_iso(utc_now()),
        "field_groups": list(SHAREABLE_FIELD_GROUPS),
        "default_role": DEFAULT_ROLE,
        "attribution": SHARE_POLICY_ATTRIBUTION,
        "persistence": SHARE_POLICY_PERSISTENCE,
        "countries": countries,
    }


def _clean(value: Any, maximum: int) -> Optional[str]:
    """Trim an optional free-text field to ``None`` or a bounded string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:maximum]


__all__ = [
    "DEFAULT_ROLE",
    "SHARE_POLICY_ATTRIBUTION",
    "SHARE_POLICY_PERSISTENCE",
    "SharePolicyError",
    "audit_trail",
    "effective_shared_fields",
    "policy_matrix",
    "preview_sharing",
    "resolve_effective",
    "set_policy",
]
