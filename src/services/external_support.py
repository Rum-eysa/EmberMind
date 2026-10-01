"""External support early forecast (EM-065, Epic E7).

The cross-border coordinator wants to know, *before* the numbers actually go
red, when the national suppression capacity will stop being able to hold an
incident, and roughly how many reinforcement units that implies, so an
international request can be raised in time rather than after the fact.

This is a deterministic forward projection, not a learned model: it reuses the
EM-030/EM-033 capacity-gap timeline (which already prices each forecast horizon
against the capacity that will actually be on station at that minute - the
available inventory plus any en-route reinforcements whose ETA has passed) and
reads off, per event, the first minute the projected demand outruns national
capacity ("T+X dk"), the peak shortfall in that horizon window, and the whole
reinforcement units needed to cover it ("~ Y birim"). The result is an *early
warning*: the shortfall is projected ahead of when it happens, and a request-by
deadline (``EXTERNAL_SUPPORT_LEAD_TIME_MINUTES`` before the shortfall) tells the
coordinator how late they can wait. Nothing is persisted; it is computed live
from the same forecasts and inventory the risk panels use.
"""
import math
from typing import Any

from sqlalchemy.orm import Session

from src.services.capacity import CAPACITY_UNIT
from src.services.risk_index import capacity_gap_timeline

# Slightly above the pure "demand == capacity" point so rounding noise on the
# last decimal does not raise a spurious alert; the shortfall itself is the
# positive part of (demand - capacity).
_EPSILON = 1e-9

EX_SUPPORT_ATTRIBUTION = (
    "Dış destek erken tahmini: EM-030/EM-033 açık zaman çizelgesi / "
    "EM-028 etkin kapasite"
)
# Fallbacks used only when a settings object omits the keys entirely (tests may
# pass a lightweight namespace). Real config always provides these values.
_DEFAULT_UNIT_HA_PER_HOUR = 12.0
_DEFAULT_LEAD_TIME_MINUTES = 60


def _unit_capacity(settings: Any) -> float:
    return float(
        getattr(
            settings, "EXTERNAL_SUPPORT_UNIT_HA_PER_HOUR", _DEFAULT_UNIT_HA_PER_HOUR
        )
    )


def _lead_time(settings: Any) -> int:
    return int(
        getattr(
            settings, "EXTERNAL_SUPPORT_LEAD_TIME_MINUTES", _DEFAULT_LEAD_TIME_MINUTES
        )
    )


def _signed_shortfall(series: list[dict[str, Any]]) -> list[tuple[int, float]]:
    """``(minute, demand - capacity)`` per horizon; positive means a shortfall."""
    return [
        (int(row["minute"]), float(row["demand_ha_h"]) - float(row["capacity_ha_h"]))
        for row in series
    ]


def _first_shortfall_minute(points: list[tuple[int, float]]) -> float | None:
    """Earliest minute the projected demand outruns national capacity.

    ``points`` are ``(minute, signed_shortfall)`` ascending by horizon. The
    engine only forecasts at discrete horizons, so the exact crossing minute is
    linearly interpolated between the last non-positive point and the first
    positive one. If the very first horizon is already short we cannot resolve
    an earlier minute and report that horizon (a conservative upper bound). If
    no horizon goes positive the national capacity holds for the whole window.
    """
    prev_minute: int = 0
    prev_short: float = 0.0
    seen_prev = False
    for minute, short in points:
        if short > _EPSILON:
            if not seen_prev or prev_short >= short:
                return float(minute)
            fraction = -prev_short / (short - prev_short)
            return round(prev_minute + fraction * (minute - prev_minute), 1)
        prev_minute, prev_short, seen_prev = minute, short, True
    return None


def _peak_shortfall(points: list[tuple[int, float]]) -> tuple[float, int | None]:
    """Largest ``demand - capacity`` gap in the window and the minute it peaks."""
    worst = 0.0
    worst_minute: int | None = None
    for minute, short in points:
        if short > worst:
            worst, worst_minute = short, minute
    return round(worst, 3), worst_minute


def _support_units(shortfall_ha_h: float, unit_capacity: float) -> int:
    """Whole reinforcement units needed to cover ``shortfall_ha_h`` (ha/hour)."""
    if shortfall_ha_h <= _EPSILON or unit_capacity <= 0:
        return 0
    return int(math.ceil(shortfall_ha_h / unit_capacity))


def _message(first_minute: float | None, units: int, request_by: float | None) -> str:
    """Human-readable early-warning suggestion (Turkish, matches the panels)."""
    if first_minute is None:
        return (
            "Öngörülen ufuk içinde ulusal kapasite yeterli; "
            "dış destek ihtiyacı öngörülmüyor."
        )
    base = (
        f"Ulusal kapasite T+{int(round(first_minute))} dk sonra yetersiz "
        f"kalacak, dış destek ihtiyacı ≈ {units} birim."
    )
    if request_by is not None and request_by > 0:
        return (
            base + f" Talep en geç T+{int(round(request_by))} dk'ye kadar gönderilmeli."
        )
    return base + " Talep hemen gönderilmeli (varış süresi riski aşıyor)."


def _assess_event(
    event: dict[str, Any], unit_capacity: float, lead_time: int
) -> dict[str, Any]:
    """Turn one timeline event's series into an external-support assessment."""
    points = _signed_shortfall(list(event.get("series", [])))
    first_minute = _first_shortfall_minute(points)
    peak_ha_h, peak_minute = _peak_shortfall(points)
    units = _support_units(peak_ha_h, unit_capacity) if first_minute is not None else 0
    request_by = (
        None if first_minute is None else max(0.0, round(first_minute - lead_time, 1))
    )
    return {
        "event_key": event["event_key"],
        "name": event.get("name"),
        "latitude": event.get("latitude"),
        "longitude": event.get("longitude"),
        "predicted_shortfall": first_minute is not None,
        "first_shortfall_minute": first_minute,
        "peak_shortfall_ha_h": peak_ha_h if first_minute is not None else 0.0,
        "peak_shortfall_minute": peak_minute if first_minute is not None else None,
        "estimated_support_units": units,
        "request_by_minute": request_by,
        "lead_time_minutes": lead_time,
        "message": _message(first_minute, units, request_by),
    }


def forecast_external_support(
    session: Session, settings: Any, event_key: str | None = None
) -> dict[str, Any]:
    """Early external-support forecast for active events (or one event)."""
    timeline = capacity_gap_timeline(session, settings, event_key)
    unit_capacity = _unit_capacity(settings)
    lead_time = _lead_time(settings)

    assessments = [
        _assess_event(event, unit_capacity, lead_time)
        for event in timeline.get("events", [])
    ]
    warning = [a for a in assessments if a["predicted_shortfall"]]
    soonest = min(warning, key=lambda a: a["first_shortfall_minute"], default=None)

    return {
        "panel": "external_support",
        "generated_at": timeline["generated_at"],
        "unit": CAPACITY_UNIT,
        "support_unit_ha_per_hour": unit_capacity,
        "capacity_effective_ha_h": timeline["capacity_effective_ha_h"],
        "lead_time_minutes": lead_time,
        "attribution": EX_SUPPORT_ATTRIBUTION,
        "persistence": "none",
        "events": assessments,
        "summary": {
            "events_scored": len(assessments),
            "events_with_warning": len(warning),
            "earliest_shortfall_event": soonest["event_key"] if soonest else None,
            "earliest_shortfall_minute": soonest["first_shortfall_minute"]
            if soonest
            else None,
            "earliest_support_units": soonest["estimated_support_units"]
            if soonest
            else 0,
            "message": soonest["message"] if soonest else _message(None, 0, None),
        },
    }
