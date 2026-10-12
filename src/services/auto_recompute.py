"""Dynamic plan auto-recompute with an operator change summary (EM-057, E6).

The operator must never act on a stale plan. When a live driving input moves —
wind, the fire's own position, or the suppression capacity on station — the
spread plan and the risk headline are refreshed automatically, and a single
"plan güncellendi, ne değişti?" entry is pushed onto the live change feed
(EM-090) so the operator map flashes what changed and the new peak risk band.

The engine reuses the EM-018 spread recompute (:func:`run_spread_forecast`) for
the fire-growth side and the EM-029 risk index for the capacity-aware headline.
Change detection compares the *current* driving state against the snapshot
recorded on the last recompute. The append-only live feed is the state store
(the same cross-process trick EM-032 uses), so the Celery worker and the API
agree on the last-known plan without a new table.

Reasons returned by :func:`evaluate_recompute`:
 1. No prior plan snapshot for the event -> run  (``new_plan``)
 2. Last recompute younger than debounce -> skip (``debouncing``)
 3. A driving factor moved past threshold -> run  (``changed``)
 4. Otherwise                             -> skip (``stable``)
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.live import LiveUpdate
from src.models.spatial import FireEvent
from src.services.capacity import effective_capacity
from src.services.live import record_update
from src.services.risk_index import compute_risk_index
from src.services.spread import resolve_inputs
from src.services.spread_trigger import run_spread_forecast
from src.utils.timeutils import utc_now

# Reasons returned by :func:`evaluate_recompute`.
REASON_NEW_PLAN = "new_plan"
REASON_DEBOUNCING = "debouncing"
REASON_CHANGED = "changed"
REASON_STABLE = "stable"

# Feed attribution constants (kept in one place so callers/tests agree).
RECOMPUTE_SOURCE = "auto_recompute"
RECOMPUTE_ATTRIBUTION = (
    "Plan güncellendi: EM-057 dinamik yeniden hesaplama "
    "(rüzgâr / yangın konumu / kapasite değişimi)"
)

# Turkish factor labels for the operator-facing "ne değişti?" summary.
FACTOR_LABELS = {
    "wind_speed": "rüzgâr hızı",
    "wind_dir": "rüzgâr yönü",
    "humidity": "nem",
    "temp": "sıcaklık",
    "position": "yangın konumu",
    "capacity": "kapasite",
}


def _as_float(value: Any) -> float:
    """Coerce a possibly-missing/None driving-state value to float (else 0.0)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _angular_diff_deg(a: float, b: float) -> float:
    """Smallest absolute angular difference between two bearings (degrees)."""
    diff = abs((a - b) % 360.0)
    return min(diff, 360.0 - diff)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates in kilometres."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    chord = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(math.sqrt(chord))


def current_plan_state(
    session: Session, settings: Any, event: FireEvent
) -> dict[str, float]:
    """Snapshot the driving inputs the operator's plan is computed from now.

    Combines the resolved spread weather (EM-015 inputs), the event's own
    position and the current effective suppression capacity (EM-028) into one
    flat dict so change detection and the recorded baseline stay comparable.
    """
    req = {"latitude": event.latitude, "longitude": event.longitude}
    inputs = resolve_inputs(session, req, settings)["inputs"]
    capacity = float(
        effective_capacity(session, settings)["total_effective_ha_per_hour"]
    )
    return {
        "wind_speed_kmh": _as_float(inputs.get("wind_speed_kmh")),
        "wind_from_deg": _as_float(inputs.get("wind_from_deg")),
        "relative_humidity_pct": _as_float(inputs.get("relative_humidity_pct")),
        "air_temp_c": _as_float(inputs.get("air_temp_c")),
        "latitude": _as_float(event.latitude),
        "longitude": _as_float(event.longitude),
        "capacity_ha_h": capacity,
    }


def _latest_plan_snapshot(
    session: Session, event_key: str
) -> tuple[dict[str, Any], datetime | None]:
    """Return the last recorded plan snapshot + its timestamp for an event."""
    row = session.scalars(
        select(LiveUpdate)
        .where(
            LiveUpdate.kind == "forecast",
            LiveUpdate.event_key == event_key,
            LiveUpdate.source == RECOMPUTE_SOURCE,
        )
        .order_by(LiveUpdate.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return {}, None
    payload: Any = {}
    if row.payload_json:
        try:
            payload = json.loads(str(row.payload_json))
        except (ValueError, TypeError):
            payload = {}
    state = payload.get("state") if isinstance(payload, dict) else None
    snapshot: dict[str, Any] = state if isinstance(state, dict) else {}
    return snapshot, cast(datetime, row.created_at)


def changed_factors(
    previous: dict[str, Any], current: dict[str, Any], settings: Any
) -> list[str]:
    """Which plan-driving factors moved past their threshold since last plan.

    Wind speed/direction/humidity/temperature reuse the EM-018 deltas; the fire
    position uses a haversine distance floor; capacity uses a relative percent
    change. Returns an empty list for the very first (no-baseline) snapshot.
    """
    if not previous:
        return []
    changed: list[str] = []
    if abs(
        _as_float(current.get("wind_speed_kmh"))
        - _as_float(previous.get("wind_speed_kmh"))
    ) >= float(getattr(settings, "SPREAD_TRIGGER_WIND_SPEED_KMH_THRESHOLD", 10.0)):
        changed.append("wind_speed")
    if _angular_diff_deg(
        _as_float(current.get("wind_from_deg")),
        _as_float(previous.get("wind_from_deg")),
    ) >= float(getattr(settings, "SPREAD_TRIGGER_WIND_DIR_DEG_THRESHOLD", 30.0)):
        changed.append("wind_dir")
    if abs(
        _as_float(current.get("relative_humidity_pct"))
        - _as_float(previous.get("relative_humidity_pct"))
    ) >= float(getattr(settings, "SPREAD_TRIGGER_HUMIDITY_PCT_THRESHOLD", 10.0)):
        changed.append("humidity")
    if abs(
        _as_float(current.get("air_temp_c")) - _as_float(previous.get("air_temp_c"))
    ) >= (float(getattr(settings, "SPREAD_TRIGGER_TEMP_C_THRESHOLD", 5.0))):
        changed.append("temp")
    moved = haversine_km(
        _as_float(previous.get("latitude")),
        _as_float(previous.get("longitude")),
        _as_float(current.get("latitude")),
        _as_float(current.get("longitude")),
    )
    if moved >= float(getattr(settings, "AUTO_RECOMPUTE_POSITION_MOVE_KM", 1.0)):
        changed.append("position")
    prev_cap = _as_float(previous.get("capacity_ha_h"))
    cur_cap = _as_float(current.get("capacity_ha_h"))
    cap_pct = float(getattr(settings, "AUTO_RECOMPUTE_CAPACITY_CHANGE_PCT", 10.0))
    if prev_cap > 0 and abs(cur_cap - prev_cap) / prev_cap * 100.0 >= cap_pct:
        changed.append("capacity")
    return changed


def evaluate_recompute(
    session: Session,
    settings: Any,
    event: FireEvent,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decide whether ``event`` needs a fresh plan right now.

    Pure with respect to writes: it reads the last plan snapshot and the current
    driving state and returns ``should_recompute`` + the reasons/factors.
    """
    clock = now or utc_now()
    event_key = str(event.event_key)
    previous, last_at = _latest_plan_snapshot(session, event_key)
    current = current_plan_state(session, settings, event)

    if not previous:
        return {
            "event_key": event_key,
            "should_recompute": True,
            "reason": REASON_NEW_PLAN,
            "changed": [],
            "minutes_since_last": None,
            "current_state": current,
            "previous_state": {},
        }

    elapsed_min = None
    if last_at is not None:
        baseline = last_at.replace(tzinfo=None) if last_at.tzinfo else last_at
        elapsed_min = (clock - baseline).total_seconds() / 60.0

    changed = changed_factors(previous, current, settings)
    debounce = float(getattr(settings, "SPREAD_TRIGGER_DEBOUNCE_MINUTES", 15.0))
    if elapsed_min is not None and elapsed_min < debounce:
        return {
            "event_key": event_key,
            "should_recompute": False,
            "reason": REASON_DEBOUNCING,
            "changed": changed,
            "minutes_since_last": round(elapsed_min, 2),
            "current_state": current,
            "previous_state": previous,
        }

    should = bool(changed)
    return {
        "event_key": event_key,
        "should_recompute": should,
        "reason": REASON_CHANGED if should else REASON_STABLE,
        "changed": changed,
        "minutes_since_last": round(elapsed_min, 2)
        if elapsed_min is not None
        else None,
        "current_state": current,
        "previous_state": previous,
    }


def _plan_headline(session: Session, settings: Any, event_key: str) -> dict[str, Any]:
    """Recompute the risk index and pull the fresh headline band for one event."""
    panel = compute_risk_index(session, settings, event_key=event_key)
    for scored in panel["events"]:
        if str(scored["event_key"]) == event_key:
            return {
                "peak_level": scored["peak_level"],
                "peak_risk_index": scored["peak_risk_index"],
                "peak_horizon_minutes": scored["peak_horizon_minutes"],
            }
    return {
        "peak_level": "normal",
        "peak_risk_index": None,
        "peak_horizon_minutes": None,
    }


def run_recompute(
    session: Session,
    settings: Any,
    event: FireEvent,
    now: datetime | None = None,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh the spread plan + risk headline and notify the operator.

    Re-runs the EM-018 forecast sweep for the event (all horizons), re-scores
    the risk index against the current capacity, then records a single
    "plan güncellendi, ne değişti?" ``forecast`` entry on the live feed whose
    payload doubles as the next baseline snapshot.
    """
    clock = now or utc_now()
    event_key = str(event.event_key)
    decision = decision or evaluate_recompute(session, settings, event, clock)
    state = decision["current_state"]
    changed = decision["changed"]

    spread = run_spread_forecast(session, settings, event)
    headline = _plan_headline(session, settings, event_key)

    factors = [FACTOR_LABELS.get(factor, factor) for factor in changed] or ["yeni plan"]
    summary = (
        "Değişen: "
        + ", ".join(factors)
        + f" — tepe risk: {headline['peak_level']}"
        + f" (Risk(t) {headline['peak_risk_index']})"
    )
    entry = record_update(
        session,
        settings,
        "forecast",
        event_key=event_key,
        title=f"Plan güncellendi: {event.name or event_key}",
        message=summary,
        payload={
            "plan_update": True,
            "changed": changed,
            "changed_labels": factors,
            "state": state,
            "headline": headline,
            "reason": decision["reason"],
            "attribution": RECOMPUTE_ATTRIBUTION,
        },
        source=RECOMPUTE_SOURCE,
    )
    return {
        "event_key": event_key,
        "reason": decision["reason"],
        "changed": changed,
        "summary": summary,
        "spread": spread,
        "headline": headline,
        "entry": entry,
    }


def auto_recompute_sweep(
    session: Session,
    settings: Any,
    now: datetime | None = None,
    event_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Sweep active events and refresh the plan of every one that changed.

    ``event_keys`` optionally restricts the sweep (used by the manual API
    endpoint). Returns a summary of what was recomputed and what was skipped.
    """
    clock = now or utc_now()
    events = list(
        session.scalars(select(FireEvent).where(FireEvent.status == "active")).all()
    )
    if event_keys is not None:
        wanted = set(event_keys)
        events = [e for e in events if str(e.event_key) in wanted]

    enabled = bool(getattr(settings, "AUTO_RECOMPUTE_ENABLED", True))
    recomputed: list[dict[str, Any]] = []
    skipped: dict[str, int] = {REASON_DEBOUNCING: 0, REASON_STABLE: 0}

    if enabled:
        for event in events:
            decision = evaluate_recompute(session, settings, event, clock)
            if decision["should_recompute"]:
                recomputed.append(
                    run_recompute(session, settings, event, clock, decision)
                )
            else:
                reason = decision["reason"]
                skipped[reason] = skipped.get(reason, 0) + 1

    return {
        "enabled": enabled,
        "checked": len(events),
        "recomputed_count": len(recomputed),
        "recomputed": recomputed,
        "skipped": skipped,
    }
