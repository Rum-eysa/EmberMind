"""Risk threshold-crossing alert evaluation (EM-032, Epic E3).

The operator does not want to stare at the screen waiting for a fire to get
out of hand: when an incident's risk band escalates a level up we push a single
``alert`` entry onto the live change feed (EM-090), which the WebSocket/
polling stream turns into a visual **and** audible notification on the operator
map.

Hysteresis suppresses repeat alerts. The append-only feed is the state store
(so it works across the separate Celery/API processes without a new table):
for each event we read back the highest band already alerted, and only fire
when the freshly computed band climbs *above* that high-water mark. Re-
evaluations at the same or a lower band stay quiet — the classic "don't spam
the operator" requirement — and a drop-then-rise back to the previous peak
must exceed it again to re-arm, which is a deliberately conservative latch.
"""
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.live import LiveUpdate
from src.services.live import record_update
from src.services.risk_index import RISK_LEVELS, compute_risk_index
from src.utils.timeutils import to_utc_iso, utc_now

# normal < dikkat < kritik-yakin < kritik; index 0 (normal) never alerts.
LEVEL_ORDER = {level: index for index, level in enumerate(RISK_LEVELS)}
_MIN_ALERT_INDEX = LEVEL_ORDER["dikkat"]
ALERT_SOURCE = "risk_alert"
ALERT_ATTRIBUTION = "Eşik aşımı uyarısı: EM-029 Risk(t) seviye eskalasyonu (EM-032)"


def _last_alerted_index(session: Session, event_key: str) -> int:
    """Highest band already alerted for an event, read back from the feed.

    The newest risk alert for the event carries the band it escalated *to*
    (the high-water mark, since alerts are only written on escalation). With
    no prior alert the baseline is ``normal`` (index 0), so the first climb to
    ``dikkat`` or above fires.
    """
    row = session.scalars(
        select(LiveUpdate)
        .where(
            LiveUpdate.kind == "alert",
            LiveUpdate.event_key == event_key,
            LiveUpdate.source == ALERT_SOURCE,
        )
        .order_by(LiveUpdate.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return LEVEL_ORDER["normal"]
    try:
        payload = json.loads(str(row.payload_json)) if row.payload_json else {}
    except (ValueError, TypeError):
        payload = {}
    index = payload.get("to_index")
    if index is None:
        index = LEVEL_ORDER.get(payload.get("to_level"), LEVEL_ORDER["normal"])
    return int(index)


def _level_name(index: int) -> str:
    for level, position in LEVEL_ORDER.items():
        if position == index:
            return level
    return "normal"


def evaluate_risk_alerts(session: Session, settings: Any) -> dict[str, Any]:
    """Score every active event and push an ``alert`` on a band escalation."""
    enabled = bool(getattr(settings, "RISK_ALERTS_ENABLED", True))
    panel = compute_risk_index(session, settings)
    fired: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for event in panel["events"]:
        event_key = str(event["event_key"])
        to_level = str(event["peak_level"])
        to_index = LEVEL_ORDER.get(to_level, 0)
        last_index = _last_alerted_index(session, event_key)
        escalated = enabled and to_index > last_index and to_index >= _MIN_ALERT_INDEX
        state = {
            "event_key": event_key,
            "name": event["name"],
            "peak_level": to_level,
            "peak_index": to_index,
            "peak_risk_index": event["peak_risk_index"],
            "peak_horizon_minutes": event["peak_horizon_minutes"],
            "last_alerted_level": _level_name(last_index),
            "last_alerted_index": last_index,
            "escalated": escalated,
        }
        states.append(state)
        if not escalated:
            continue
        entry = record_update(
            session,
            settings,
            "alert",
            event_key=event_key,
            title=f"Risk yükseldi: {event['name'] or event_key}",
            message=(
                f"{event_key}: risk {_level_name(last_index)} → {to_level}"
                f" (Risk(t) {event['peak_risk_index']})"
            ),
            payload={
                "from_level": _level_name(last_index),
                "from_index": last_index,
                "to_level": to_level,
                "to_index": to_index,
                "risk_index": event["peak_risk_index"],
                "horizon_minutes": event["peak_horizon_minutes"],
            },
            source=ALERT_SOURCE,
        )
        if entry is not None:
            fired.append(entry)
    return {
        "panel": "risk_alerts",
        "evaluated_at": to_utc_iso(utc_now()),
        "enabled": enabled,
        "levels": list(RISK_LEVELS),
        "hysteresis": (
            "peak-latch: bir olay için yalnızca daha önce uyarılan en yüksek "
            "bandın üstüne çıkıldığında tek bir uyarı üretilir"
        ),
        "attribution": ALERT_ATTRIBUTION,
        "alerts": fired,
        "events": states,
        "summary": {
            "events_evaluated": len(states),
            "alerts_raised": len(fired),
        },
    }
