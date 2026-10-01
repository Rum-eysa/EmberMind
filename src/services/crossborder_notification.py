"""Joint cross-border early-warning notification (EM-069, Epic E7).

EM-067 answers *could this fire reach the border, and when*; EM-069 turns that
answer into the coordinated **action** the acceptance asks for: once the
crossing likelihood and lead time pass the agreed threshold, the partner
country's coordination unit is notified over a **pre-defined channel** so a
joint early warning starts instead of a surprise.

The trigger is **edge-based**: at most one *open* notification exists per
``(event, target_country)``, so a recompute never spams the neighbour, and an
open warning is auto-**resolved** when the fire is no longer projected to cross
(wind shifts, the head turns away). Every dispatch is persisted to
:mod:`src.models.crossborder_notification` as the durable record of what was
sent, over which channel, to whom. The channel recipients are the agreed
standby contacts (config), so no live network call is mocked as "sent".
"""
from __future__ import annotations

import secrets
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.crossborder_notification import CrossborderNotification
from src.services.crossborder_situation import COUNTRY_LABELS
from src.services.crossborder_spread import project_border_crossing
from src.utils.timeutils import to_utc_iso, utc_now

DEFAULT_MIN_LIKELIHOOD = 0.4
DEFAULT_NOTIFY_WINDOW_MINUTES = 120

NOTIF_OPEN = "open"
NOTIF_RESOLVED = "resolved"

# The pre-defined coordination channel per partner country (agreed standby
# contacts). This is what "önceden tanımlı kanal" resolves to - a durable
# dispatch target, not a simulated live send.
COORDINATION_CHANNELS: dict[str, dict[str, str]] = {
    "TR": {
        "channel": "tr-mobil-birim-kanali",
        "recipient": "Türkiye Sınır Ötesi Koordinasyon Birimi (MOBİL)",
    },
    "GR": {
        "channel": "gr-general-secretariat-kanali",
        "recipient": "Yunanistan Genel Sekreterliği (Γενική Γραμματεία)",
    },
}

NOTIF_ATTRIBUTION = (
    "EM-069: eşik aşımında karşı ülke koordinasyon birimine önceden tanımlı "
    "kanaldan ortak erken uyarı bildirimi; kenar-tetiklemeli (olay+hedef başına "
    "tek açık bildirim) ve artık geçiş öngörülmediğinde otomatik çözülen; her "
    "gönderim country crossborder_notification tablosunda kalıcı kayıttır."
)
NOTIF_PERSISTENCE = "crossborder_notification"


class NotificationError(ValueError):
    """Raised for an unknown notification target country or missing row."""


def _min_likelihood(settings: Any) -> float:
    raw = getattr(settings, "CROSSBORDER_NOTIFY_MIN_LIKELIHOOD", DEFAULT_MIN_LIKELIHOOD)
    try:
        return float(raw)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return DEFAULT_MIN_LIKELIHOOD


def _notify_window(settings: Any) -> int:
    raw = getattr(
        settings, "CROSSBORDER_NOTIFY_WINDOW_MINUTES", DEFAULT_NOTIFY_WINDOW_MINUTES
    )
    try:
        return int(raw)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return DEFAULT_NOTIFY_WINDOW_MINUTES


def channel_for(country: str) -> dict[str, str]:
    """The pre-defined channel + recipient for a partner country."""
    code = str(country or "").strip().upper()
    if code not in COORDINATION_CHANNELS:
        raise NotificationError(f"unknown notification target country {country!r}")
    return COORDINATION_CHANNELS[code]


def _qualifies(row: dict[str, Any], min_likelihood: float, window: int) -> bool:
    """Does one projected crossing pass the agreed likelihood + lead-time gate?"""
    minutes = row.get("crossing_minutes")
    likelihood = row.get("likelihood")
    if minutes is None or likelihood is None:
        return False
    if float(likelihood) < min_likelihood:
        return False
    return float(minutes) <= window


def _message(row: dict[str, Any]) -> str:
    """Turkish early-warning body capped to the persisted column width."""
    source = COUNTRY_LABELS.get(row["source_country"], row["source_country"])
    target = COUNTRY_LABELS.get(row["target_country"], row["target_country"])
    minutes = row.get("crossing_minutes")
    when = "belirsiz" if minutes is None else f"~T+{int(round(float(minutes)))} dk"
    text = (
        f"ORTAK ERKEN UYARI — {source} içindeki {row['event_key']} yangını "
        f"{target} sınırını {when} sonra geçebilir "
        f"(olasılık ≈ {float(row['likelihood']):.2f}, "
        f"seviye {row['likelihood_level']})."
    )
    return text[:255]


def _open_notification(
    session: Session, event_key: str, target: str
) -> Optional[CrossborderNotification]:
    """The single open warning for an incident toward one partner (dedup)."""
    return session.scalar(
        select(CrossborderNotification)
        .where(
            CrossborderNotification.event_key == event_key,
            CrossborderNotification.target_country == target,
            CrossborderNotification.status == NOTIF_OPEN,
        )
        .order_by(CrossborderNotification.id.desc())
        .limit(1)
    )


def evaluate_thresholds(session: Session, settings: Any) -> dict[str, Any]:
    """Split the EM-067 projection into crossing that qualify vs not."""
    projection = project_border_crossing(session, settings)
    min_likelihood = _min_likelihood(settings)
    window = _notify_window(settings)
    qualifying: list[dict[str, Any]] = []
    for row in projection["events"]:
        if _qualifies(row, min_likelihood, window):
            chan = channel_for(row["target_country"])
            qualifying.append(
                {
                    "event_key": row["event_key"],
                    "source_country": row["country"],
                    "target_country": row["target_country"],
                    "likelihood": row["likelihood"],
                    "likelihood_level": row["likelihood_level"],
                    "crossing_minutes": row["crossing_minutes"],
                    "within_forecast_window": row["within_forecast_window"],
                    "channel": chan["channel"],
                    "recipient": chan["recipient"],
                    "message": _message({**row, "source_country": row["country"]}),
                }
            )
    return {
        "min_likelihood": min_likelihood,
        "window_minutes": window,
        "generated_at": projection["generated_at"],
        "border_longitude": projection["border_longitude"],
        "forecast_window_minutes": projection["forecast_window_minutes"],
        "qualifying": qualifying,
    }


def dispatch(
    session: Session, settings: Any, event_key: str, target_country: str
) -> dict[str, Any]:
    """Create (or reuse) the open early-warning for an event toward a partner."""
    code = str(target_country or "").strip().upper()
    chan = channel_for(code)
    existing = _open_notification(session, event_key, code)
    if existing is not None:
        return {"created": False, "notification": existing.as_dict, "deduped": True}
    source = "GR" if code == "TR" else "TR"
    likelihood = float(
        getattr(settings, "CROSSBORDER_NOTIFY_MIN_LIKELIHOOD", DEFAULT_MIN_LIKELIHOOD)
    )
    minutes = float(
        getattr(
            settings, "CROSSBORDER_NOTIFY_WINDOW_MINUTES", DEFAULT_NOTIFY_WINDOW_MINUTES
        )
    )
    likelihood_level = "eşik"
    row = CrossborderNotification(
        notification_key=f"cbn-{secrets.token_hex(6)}",
        event_key=str(event_key),
        source_country=source,
        target_country=code,
        likelihood=likelihood,
        likelihood_level=likelihood_level,
        crossing_minutes=minutes,
        within_forecast_window=1,
        channel=chan["channel"],
        recipient=chan["recipient"],
        message=_message(
            {
                "source_country": source,
                "target_country": code,
                "event_key": str(event_key),
                "crossing_minutes": minutes,
                "likelihood": likelihood,
                "likelihood_level": likelihood_level,
            }
        ),
        status=NOTIF_OPEN,
    )
    session.add(row)
    session.flush()
    return {"created": True, "notification": row.as_dict, "deduped": False}


def _resolve(row: CrossborderNotification) -> dict[str, Any]:
    """Mark one open warning resolved (the fire is no longer projected to cross)."""
    row.status = NOTIF_RESOLVED  # type: ignore[assignment]
    row.resolved_at = to_utc_iso(utc_now())  # type: ignore[assignment]
    return row.as_dict


def sweep(session: Session, settings: Any) -> dict[str, Any]:
    """Edge-triggered dispatch + auto-resolve for every qualifying crossing."""
    evaluation = evaluate_thresholds(session, settings)
    qualifying = evaluation["qualifying"]
    created: list[dict[str, Any]] = []
    deduped: list[dict[str, Any]] = []
    for row in qualifying:
        result = dispatch(session, settings, row["event_key"], row["target_country"])
        (created if result["created"] else deduped).append(result["notification"])

    qualifying_keys = {(r["event_key"], r["target_country"]) for r in qualifying}
    resolved: list[dict[str, Any]] = []
    open_rows = session.scalars(
        select(CrossborderNotification).where(
            CrossborderNotification.status == NOTIF_OPEN
        )
    ).all()
    for notif in open_rows:
        key = (str(notif.event_key), str(notif.target_country))
        if key not in qualifying_keys:
            resolved.append(_resolve(notif))

    return {
        "threshold": {
            "min_likelihood": evaluation["min_likelihood"],
            "window_minutes": evaluation["window_minutes"],
        },
        "created": created,
        "deduped": deduped,
        "resolved": resolved,
    }


def list_notifications(
    session: Session,
    event_key: Optional[str] = None,
    target: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Dispatched warnings (newest first), optionally filtered."""
    query = select(CrossborderNotification).order_by(CrossborderNotification.id.desc())
    if event_key:
        query = query.where(CrossborderNotification.event_key == str(event_key))
    if target:
        query = query.where(
            CrossborderNotification.target_country == str(target).strip().upper()
        )
    if status:
        query = query.where(CrossborderNotification.status == str(status))
    rows = session.scalars(query.limit(max(1, int(limit)))).all()
    return [row.as_dict for row in rows]


def notification_status(session: Session, settings: Any) -> dict[str, Any]:
    """Threshold view: crossings that warrant a partner warning + dispatch state."""
    evaluation = evaluate_thresholds(session, settings)
    qualifying: list[dict[str, Any]] = []
    for row in evaluation["qualifying"]:
        open_notif = _open_notification(
            session, row["event_key"], row["target_country"]
        )
        qualifying.append(
            {
                **row,
                "notified": open_notif is not None,
                "notification": open_notif.as_dict if open_notif else None,
            }
        )
    return {
        "panel": "crossborder_notification",
        "enabled": bool(getattr(settings, "CROSSBORDER_NOTIFY_ENABLED", True)),
        "min_likelihood": evaluation["min_likelihood"],
        "notify_window_minutes": evaluation["window_minutes"],
        "generated_at": evaluation["generated_at"],
        "border_longitude": evaluation["border_longitude"],
        "attribution": NOTIF_ATTRIBUTION,
        "persistence": NOTIF_PERSISTENCE,
        "qualifying": qualifying,
        "channels": dict(COORDINATION_CHANNELS),
        "summary": {
            "crossings_qualifying": len(qualifying),
            "already_notified": sum(1 for r in qualifying if r["notified"]),
            "message": (
                f"{len(qualifying)} olay eşikleri aştı; "
                f"{sum(1 for r in qualifying if r['notified'])} bildirim gönderildi."
            ),
        },
    }


__all__ = [
    "COORDINATION_CHANNELS",
    "NOTIF_ATTRIBUTION",
    "NOTIF_PERSISTENCE",
    "NOTIF_OPEN",
    "NOTIF_RESOLVED",
    "NotificationError",
    "channel_for",
    "dispatch",
    "evaluate_thresholds",
    "list_notifications",
    "notification_status",
    "sweep",
]
