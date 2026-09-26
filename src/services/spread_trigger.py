"""Automatic spread-forecast triggering with debounce (EM-018).

Operators should not have to kick off a spread prediction by hand: when a new
fire event appears, or when the driving inputs (wind, humidity, temperature)
change meaningfully, the forecast should refresh itself. To avoid burning
compute on flapping conditions, a per-event debounce rate-limits how often the
same event may be re-forecast.

Trigger decision (evaluated per active event):
 1. No prior forecast for the event      -> run  (reason: ``new_event``)
 2. Last run younger than the debounce    -> skip (reason: ``debouncing``)
 3. Inputs moved past a change threshold  -> run  (reason: ``inputs_changed``)
 4. Otherwise                             -> skip (reason: ``stable``)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import FireEvent, FireForecast
from src.services.spread import predict_spread, resolve_inputs
from src.utils.timeutils import utc_now

# Reasons returned by :func:`evaluate_trigger`.
REASON_NEW_EVENT = "new_event"
REASON_DEBOUNCING = "debouncing"
REASON_INPUTS_CHANGED = "inputs_changed"
REASON_STABLE = "stable"


def _as_float(value: dict[str, Any], key: str) -> float:
    """Read ``key`` from ``value`` as float, treating missing/None as 0.0."""
    raw = value.get(key)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _angular_diff_deg(a: float, b: float) -> float:
    """Smallest absolute angular difference between two bearings (degrees)."""
    diff = abs((a - b) % 360.0)
    return min(diff, 360.0 - diff)


def _latest_forecast(session: Session, event_key: str) -> FireForecast | None:
    """Return the most recently created forecast for an event, if any."""
    return session.scalars(
        select(FireForecast)
        .where(FireForecast.event_key == event_key)
        .order_by(FireForecast.created_at.desc(), FireForecast.id.desc())
        .limit(1)
    ).first()


def _current_inputs(session: Session, event: FireEvent) -> dict[str, Any]:
    """Resolve the spread inputs an auto-run would use for this event now."""
    req = {"latitude": event.latitude, "longitude": event.longitude}
    return resolve_inputs(session, req)["inputs"]


def inputs_changed_meaningfully(
    previous: dict[str, Any],
    current: dict[str, Any],
    settings: Any,
) -> bool:
    """True when any driving input moved past its configured change threshold.

    Wind speed/direction, relative humidity and air temperature are compared.
    Direction uses the wraparound-safe angular difference.
    """
    wind_speed_delta = float(
        getattr(settings, "SPREAD_TRIGGER_WIND_SPEED_KMH_THRESHOLD", 10.0)
    )
    wind_dir_delta = float(
        getattr(settings, "SPREAD_TRIGGER_WIND_DIR_DEG_THRESHOLD", 30.0)
    )
    humidity_delta = float(
        getattr(settings, "SPREAD_TRIGGER_HUMIDITY_PCT_THRESHOLD", 10.0)
    )
    temp_delta = float(getattr(settings, "SPREAD_TRIGGER_TEMP_C_THRESHOLD", 5.0))

    if (
        abs(
            _as_float(current, "wind_speed_kmh") - _as_float(previous, "wind_speed_kmh")
        )
        >= wind_speed_delta
    ):
        return True
    if (
        _angular_diff_deg(
            _as_float(current, "wind_from_deg"), _as_float(previous, "wind_from_deg")
        )
        >= wind_dir_delta
    ):
        return True
    if (
        abs(
            _as_float(current, "relative_humidity_pct")
            - _as_float(previous, "relative_humidity_pct")
        )
        >= humidity_delta
    ):
        return True
    if abs(_as_float(current, "air_temp_c") - _as_float(previous, "air_temp_c")) >= (
        temp_delta
    ):
        return True
    return False


def _previous_inputs(forecast: FireForecast | None) -> dict[str, Any]:
    """Decode the stored inputs of a forecast (empty dict when unavailable)."""
    raw = getattr(forecast, "inputs_json", None) if forecast else None
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def evaluate_trigger(
    session: Session,
    settings: Any,
    event: FireEvent,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decide whether ``event`` needs a fresh spread forecast right now.

    Returns a dict with ``should_run`` (bool), ``reason`` (one of the
    ``REASON_*`` constants) and supporting detail. This function is pure with
    respect to the database: it never writes.
    """
    clock = now or utc_now()
    last = _latest_forecast(session, str(event.event_key))
    current = _current_inputs(session, event)

    if last is None:
        return {
            "event_key": event.event_key,
            "should_run": True,
            "reason": REASON_NEW_EVENT,
            "minutes_since_last": None,
            "current_inputs": current,
        }

    last_created = last.created_at
    if last_created.tzinfo is not None:
        last_created = last_created.replace(tzinfo=None)
    elapsed_min = (clock - last_created).total_seconds() / 60.0

    debounce_min = float(getattr(settings, "SPREAD_TRIGGER_DEBOUNCE_MINUTES", 15.0))
    if elapsed_min < debounce_min:
        return {
            "event_key": event.event_key,
            "should_run": False,
            "reason": REASON_DEBOUNCING,
            "minutes_since_last": round(elapsed_min, 2),
            "current_inputs": current,
        }

    changed = inputs_changed_meaningfully(_previous_inputs(last), current, settings)
    return {
        "event_key": event.event_key,
        "should_run": changed,
        "reason": REASON_INPUTS_CHANGED if changed else REASON_STABLE,
        "minutes_since_last": round(elapsed_min, 2),
        "current_inputs": current,
    }


def run_spread_forecast(
    session: Session, settings: Any, event: FireEvent
) -> dict[str, Any]:
    """Generate and persist a spread forecast for ``event`` (all horizons)."""
    result = predict_spread(
        session,
        settings,
        {
            "latitude": event.latitude,
            "longitude": event.longitude,
            "event_key": str(event.event_key),
        },
    )
    return {
        "event_key": event.event_key,
        "model_name": result["model_name"],
        "generated_at": result["generated_at"],
        "forecast_count": len(result["forecasts"]),
        "horizons": [f["horizon_minutes"] for f in result["forecasts"]],
    }


def _active_events(session: Session) -> list[FireEvent]:
    """Return events currently worth refreshing (status == 'active')."""
    return list(
        session.scalars(select(FireEvent).where(FireEvent.status == "active")).all()
    )


def auto_trigger_forecasts(
    session: Session,
    settings: Any,
    now: datetime | None = None,
    event_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Sweep active events and refresh forecasts whose trigger says 'run'.

    ``event_keys`` optionally restricts the sweep to a specific set (used by
    the manual API endpoint). Returns a summary of what ran and what was
    skipped, grouped by reason.
    """
    clock = now or utc_now()
    events = _active_events(session)
    if event_keys is not None:
        wanted = set(event_keys)
        events = [e for e in events if str(e.event_key) in wanted]

    triggered: list[dict[str, Any]] = []
    skipped: dict[str, int] = {
        REASON_DEBOUNCING: 0,
        REASON_STABLE: 0,
    }

    for event in events:
        decision = evaluate_trigger(session, settings, event, now=clock)
        if decision["should_run"]:
            triggered.append(run_spread_forecast(session, settings, event))
        else:
            reason = decision["reason"]
            skipped[reason] = skipped.get(reason, 0) + 1

    return {
        "checked": len(events),
        "triggered_count": len(triggered),
        "triggered": triggered,
        "skipped": skipped,
    }
