"""Operator verification workflow for silent-region alerts (EM-041, Epic E4).

EM-040 emits one alert per high-priority silent region. EM-041 closes that loop
with the one input a derived score can never supply: the operator's judgement of
whether the alert was real. A region is marked **verified** / **false alarm** /
**under review**, and that verdict is *persisted* as an append-only audit row so
the detector can be tuned against real outcomes over time (EM-041 acceptance:
"operatör bir sessiz bölgeyi doğrulandı / yanlış alarm / inceleniyor olarak
işaretebilir; bu geri bildirim modelin iyileştirilmesi için kaydedilir").

The previous verdict is never overwritten - re-marking a region simply appends a
newer row, and the *current* verdict is that newest row. Because this service
writes, ``persistence`` names the table rather than being ``none`` (unlike the
read-time E4 panels it sits beside).

A lightweight **feedback summary** turns the recorded verdicts into a
model-improvement signal: per-status counts plus a false-alarm rate over the
regions an operator has actually adjudicated (a decisive verdict is
``verified`` or ``false_alarm``; ``under_review`` is parked and never counted as
either).
"""
from __future__ import annotations

import json
import secrets
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.silent_zone_verification import (
    VERIFICATION_LABELS,
    VERIFICATION_STATUSES,
    SilentZoneVerification,
)
from src.models.spatial import SilentRegion

# Verdicts that count as a decisive outcome for the false-alarm signal.
_DECISIVE_STATUSES = ("verified", "false_alarm")

DEFAULT_MAX_LIMIT = 200

SILENT_ZONE_VERIFICATION_ATTRIBUTION = (
    "EM-041: operatör sessiz bölge uyarısını doğrulandı/yanlış alarm/inceleniyor "
    "olarak işaretler; her işaretleme eklenen değişmez bir denetim satırıdır "
    "(önceki hüküm üzerine yazılmaz), güncel hüküm en yeni satırdır ve geri "
    "bildirim modelin iyileştirilmesi için kalıcıdır"
)
SILENT_ZONE_VERIFICATION_PERSISTENCE = "silent_zone_verifications"


class SilentZoneVerificationError(ValueError):
    """Raised for an invalid verification request (bad status, missing region)."""


def _max_limit(settings: Any) -> int:
    return int(getattr(settings, "SILENT_VERIFICATION_MAX_LIMIT", DEFAULT_MAX_LIMIT))


def _new_key() -> str:
    """A short, URL-safe unique verification key (collision negligible)."""
    return f"szv-{secrets.token_hex(6)}"


def _clean(value: Any, maximum: int) -> Optional[str]:
    """Trim an optional free-text field to ``None`` or a bounded string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:maximum]


def _validate_status(status: str) -> str:
    """Return a normalised status or raise for an unknown verdict."""
    normalised = str(status).strip().lower()
    if normalised not in VERIFICATION_STATUSES:
        raise SilentZoneVerificationError(
            f"invalid status {status!r}; expected one of "
            f"{list(VERIFICATION_STATUSES)}"
        )
    return normalised


def _resolve_region(session: Session, region_id: int) -> SilentRegion:
    """Fetch the silent region a verdict targets or raise a not-found error."""
    region = session.scalar(select(SilentRegion).where(SilentRegion.id == region_id))
    if region is None:
        raise SilentZoneVerificationError(f"silent region '{region_id}' not found")
    return region


def record_verification(
    session: Session,
    *,
    region_id: int,
    status: str,
    region_name: Optional[str] = None,
    reason: Optional[str] = None,
    verified_by: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one operator verdict on a silent-region alert.

    The verdict never replaces the previous one; it is added as a newer audit
    row so history is preserved. Raises :class:`SilentZoneVerificationError` for
    an unknown ``status`` or a missing ``region_id``. ``region_name`` defaults to
    the region's own name and is snapshotted so the audit stays readable even if
    the region is later renamed.
    """
    normalised = _validate_status(status)
    wanted = int(region_id)
    region = _resolve_region(session, wanted)

    snapshot: dict[str, Any] = dict(detail or {})
    snapshot["status"] = normalised

    row = SilentZoneVerification(
        verification_key=_new_key(),
        region_id=wanted,
        region_name=_clean(region_name or region.region_name, 128),
        status=normalised,
        reason=_clean(reason, 255),
        verified_by=_clean(verified_by, 64),
        detail_json=json.dumps(snapshot, default=str),
    )
    session.add(row)
    session.flush()
    return {
        "verification": row.as_dict,
        "is_new_current": True,
        "prior_verifications": _count_for_region(session, wanted) - 1,
    }


def _count_for_region(session: Session, region_id: int) -> int:
    """How many verdicts (including the just-added one) exist for a region."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(SilentZoneVerification)
            .where(SilentZoneVerification.region_id == region_id)
        )
        or 0
    )


def get_current_verification(
    session: Session, region_id: int
) -> Optional[dict[str, Any]]:
    """The newest verdict for one region, or ``None`` when never marked."""
    row = session.scalar(
        select(SilentZoneVerification)
        .where(SilentZoneVerification.region_id == int(region_id))
        .order_by(SilentZoneVerification.id.desc())
        .limit(1)
    )
    return row.as_dict if row is not None else None


def list_verifications(
    session: Session,
    *,
    status: Optional[str] = None,
    region_id: Optional[int] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Recorded verdicts (newest first), optionally filtered.

    A ``status`` filter accepts a raw code (``verified`` / ``false_alarm`` /
    ``under_review``); an unknown value is reported via the raised error so a
    typo never silently returns everything.
    """
    query = select(SilentZoneVerification).order_by(SilentZoneVerification.id.desc())
    if status is not None:
        query = query.where(SilentZoneVerification.status == _validate_status(status))
    if region_id is not None:
        query = query.where(SilentZoneVerification.region_id == int(region_id))
    bounded = max(1, min(int(limit), _max_limit(None)))
    rows = session.scalars(query.limit(bounded)).all()
    return [row.as_dict for row in rows]


def current_verdicts(session: Session) -> dict[int, dict[str, Any]]:
    """Every region's newest verdict, keyed by ``region_id``.

    One pass over the audit rows (oldest to newest) so a later marking simply
    overwrites the earlier entry for the same region - the append-only history
    collapses to the current state the operator sees.
    """
    current: dict[int, dict[str, Any]] = {}
    rows = session.scalars(
        select(SilentZoneVerification).order_by(SilentZoneVerification.id.asc())
    ).all()
    for row in rows:
        current[int(row.region_id)] = {
            "region_id": int(row.region_id),
            "region_name": row.region_name,
            "status": row.status,
            "status_label": VERIFICATION_LABELS.get(str(row.status), str(row.status)),
            "verified_by": row.verified_by,
            "verification_key": row.verification_key,
            "created_at": row.as_dict["created_at"],
        }
    return current


def feedback_summary(session: Session) -> dict[str, Any]:
    """Model-improvement signal over the recorded operator verdicts.

    Counts every verdict row, the per-status split, how many regions have been
    adjudicated decisively, and the **false-alarm rate** across those decisive
    verdicts (``false_alarm / (verified + false_alarm)``). Regions still parked
    in ``under_review`` are counted but never treated as a real outcome, so the
    rate only reflects confirmed truth.
    """
    by_status = {code: 0 for code in VERIFICATION_STATUSES}
    # Aggregate in SQL: this ledger only ever grows, so the summary must not read
    # every verdict row into Python to compute four numbers.
    counts = session.execute(
        select(SilentZoneVerification.status, func.count()).group_by(
            SilentZoneVerification.status
        )
    ).all()
    total_verifications = 0
    for code, count in counts:
        key = str(code)
        by_status[key] = by_status.get(key, 0) + int(count)
        total_verifications += int(count)

    decisive = by_status["verified"] + by_status["false_alarm"]
    false_alarm_rate = (
        round(by_status["false_alarm"] / decisive, 4) if decisive else None
    )
    adjudicated_region_count = int(
        session.scalar(
            select(func.count(func.distinct(SilentZoneVerification.region_id))).where(
                SilentZoneVerification.status.in_(_DECISIVE_STATUSES)
            )
        )
        or 0
    )

    return {
        "total_verifications": total_verifications,
        "by_status": by_status,
        "status_labels": dict(VERIFICATION_LABELS),
        "decisive_verifications": decisive,
        "under_review_verifications": by_status["under_review"],
        "adjudicated_region_count": adjudicated_region_count,
        "false_alarm_rate": false_alarm_rate,
    }


def verification_config(settings: Any = None) -> dict[str, Any]:
    """Descriptor: the verdicts, the append-only rule and the feedback signal."""
    return {
        "statuses": [
            {"code": code, "label": VERIFICATION_LABELS[code]}
            for code in VERIFICATION_STATUSES
        ],
        "current_verdict_rule": "en yeni satır güncel hükümdür (üzerine yazılmaz)",
        "feedback_signal": "yanlış alarm oranı = false_alarm / (verified + "
        "false_alarm); inceleniyor sayılmaz",
        "max_limit": _max_limit(settings),
        "attribution": SILENT_ZONE_VERIFICATION_ATTRIBUTION,
        "persistence": SILENT_ZONE_VERIFICATION_PERSISTENCE,
    }


__all__ = [
    "SILENT_ZONE_VERIFICATION_ATTRIBUTION",
    "SILENT_ZONE_VERIFICATION_PERSISTENCE",
    "VERIFICATION_LABELS",
    "VERIFICATION_STATUSES",
    "SilentZoneVerificationError",
    "current_verdicts",
    "feedback_summary",
    "get_current_verification",
    "list_verifications",
    "record_verification",
    "verification_config",
]
