"""Operational risk index computation (EM-029, Epic E3).

The commander asks, for every prediction horizon (30/60/120 dk), how hard an
active incident is to hold given the suppression capacity that is actually
available *right now*. ``Risk(t)`` compares the spread demand a horizon implies
against that capacity. Both sides are normalised to hectare/hour (the single
EM-028 unit), so the ratio is a unitless severity the configurable bands
classify: ``<0.6`` normal, ``0.6-0.9`` dikkat, ``0.9-1.2`` kritik-yakin and
``>1.2`` kritik. Busy / en-route / broken resources are already excluded from
the effective capacity (EM-031), so they drop straight out of the index.

Demand for a horizon is the average growth of that horizon's cumulative
forecast polygon expressed in ha/hour (``area_ha / horizon_minutes * 60``),
the same definition EM-055 uses for its capacity gap, so a risk ratio above 1
means the fire is outgrowing everything currently able to suppress it.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import FireEvent, FireForecast
from src.services.capacity import effective_capacity
from src.utils.timeutils import to_utc_iso, utc_now

# Ordered severity bands; the boundary values come from settings so an
# operator can retune the index without a code change (EM-029 acceptance).
RISK_LEVELS = ("normal", "dikkat", "kritik-yakin", "kritik")
RISK_ATTRIBUTION = "Risk indeksi: EM-015 yayılım talebi / EM-028 etkin kapasite"
# Fallbacks used only when a settings object omits the keys entirely (tests may
# pass a lightweight namespace). Real config always provides these values.
_DEFAULT_NORMAL_MAX = 0.6
_DEFAULT_CAUTION_MAX = 0.9
_DEFAULT_CRITICAL_NEAR_MAX = 1.2
# Reading window for stored forecasts; newest rows win per (event, horizon).
_FORECAST_ROW_LIMIT = 2000


class RiskIndexError(RuntimeError):
    """Raised when a risk index cannot be computed for the given request."""


def level_thresholds(settings: Any) -> dict[str, float]:
    """Configurable band boundaries for the risk index."""
    return {
        "normal_max": float(
            getattr(settings, "RISK_INDEX_NORMAL_MAX", _DEFAULT_NORMAL_MAX)
        ),
        "caution_max": float(
            getattr(settings, "RISK_INDEX_CAUTION_MAX", _DEFAULT_CAUTION_MAX)
        ),
        "critical_near_max": float(
            getattr(
                settings, "RISK_INDEX_CRITICAL_NEAR_MAX", _DEFAULT_CRITICAL_NEAR_MAX
            )
        ),
    }


def classify_risk(value: float | None, thresholds: dict[str, float]) -> str:
    """Map a risk ratio to its severity band. ``None`` (no capacity to even
    measure against) is treated as the worst band when a value exists."""
    if value is None:
        return "kritik"
    if value < thresholds["normal_max"]:
        return "normal"
    if value < thresholds["caution_max"]:
        return "dikkat"
    if value < thresholds["critical_near_max"]:
        return "kritik-yakin"
    return "kritik"


def demand_ha_h(area_ha: float, horizon_minutes: int) -> float:
    """Average area growth of the cumulative polygon, normalised to ha/hour."""
    if horizon_minutes <= 0:
        return 0.0
    return round(float(area_ha) / float(horizon_minutes) * 60.0, 3)


def _latest_forecasts(
    session: Session, event_keys: set[str]
) -> dict[tuple[str, int], float]:
    """Newest stored predicted area (ha) per ``(event_key, horizon_minutes)``.

    Rows are read newest-id-first so the first sighting of a key is the current
    model run; a later (older) duplicate for the same horizon is ignored.
    """
    if not event_keys:
        return {}
    latest: dict[tuple[str, int], float] = {}
    rows = session.scalars(
        select(FireForecast)
        .where(FireForecast.event_key.in_(event_keys))
        .order_by(FireForecast.id.desc())
        .limit(_FORECAST_ROW_LIMIT)
    )
    for row in rows:
        key = (str(row.event_key), int(row.horizon_minutes))
        if key not in latest:
            latest[key] = float(row.predicted_area_ha)
    return latest


def _active_events(session: Session, event_key: str | None) -> list[FireEvent]:
    """Events to score: one explicit event, else every active incident."""
    if event_key:
        event = session.scalar(
            select(FireEvent).where(FireEvent.event_key == event_key)
        )
        if event is None:
            raise RiskIndexError(f"fire event {event_key} not found")
        return [event]
    return list(
        session.scalars(
            select(FireEvent).where(FireEvent.status == "active").order_by(FireEvent.id)
        )
    )


def _horizons_for(
    event_key: str,
    forecasts: dict[tuple[str, int], float],
    horizon_minutes: list[int],
    capacity: float,
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    """Per-horizon risk rows for one event, ascending by horizon."""
    horizons: list[dict[str, Any]] = []
    for horizon in sorted(horizon_minutes):
        area_ha = forecasts.get((event_key, horizon))
        if area_ha is None:
            continue
        demand = demand_ha_h(area_ha, horizon)
        if capacity > 0:
            ratio = round(demand / capacity, 3)
            risk: float | None = ratio
        else:
            risk = None if demand > 0 else 0.0
        horizons.append(
            {
                "horizon_minutes": horizon,
                "area_ha": round(area_ha, 3),
                "demand_ha_h": demand,
                "gap_ha_h": round(max(0.0, demand - capacity), 3),
                "risk_index": risk,
                "level": classify_risk(risk, thresholds),
            }
        )
    return horizons


def compute_risk_index(
    session: Session, settings: Any, event_key: str | None = None
) -> dict[str, Any]:
    """Score every active event (or one) across the configured horizons."""
    thresholds = level_thresholds(settings)
    horizon_minutes = [
        int(h) for h in getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
    ]
    capacity = effective_capacity(session, settings)
    total_capacity = float(capacity["total_effective_ha_per_hour"])
    events = _active_events(session, event_key)
    forecasts = _latest_forecasts(session, {str(e.event_key) for e in events})

    scored: list[dict[str, Any]] = []
    level_counts = {level: 0 for level in RISK_LEVELS}
    for event in events:
        horizons = _horizons_for(
            str(event.event_key), forecasts, horizon_minutes, total_capacity, thresholds
        )
        peak = max(
            horizons,
            key=lambda row: (row["risk_index"] is None, row["risk_index"] or 0.0),
            default=None,
        )
        peak_level = peak["level"] if peak else "normal"
        level_counts[peak_level] = level_counts.get(peak_level, 0) + 1
        scored.append(
            {
                "event_key": str(event.event_key),
                "name": event.name,
                "latitude": float(event.latitude),
                "longitude": float(event.longitude),
                "status": str(event.status),
                "horizons": horizons,
                "peak_risk_index": peak["risk_index"] if peak else None,
                "peak_level": peak_level,
                "peak_horizon_minutes": peak["horizon_minutes"] if peak else None,
            }
        )

    hottest = max(
        scored,
        key=lambda row: (
            row["peak_risk_index"] is None,
            row["peak_risk_index"] or 0.0,
        ),
        default=None,
    )
    return {
        "panel": "risk_index",
        "generated_at": to_utc_iso(utc_now()),
        "unit": capacity["unit"],
        "horizon_minutes": sorted(horizon_minutes),
        "thresholds": thresholds,
        "levels": list(RISK_LEVELS),
        "capacity_effective_ha_h": total_capacity,
        "attribution": RISK_ATTRIBUTION,
        "events": scored,
        "summary": {
            "events_scored": len(scored),
            "events_with_forecast": sum(1 for e in scored if e["horizons"]),
            "max_risk_event": hottest["event_key"] if hottest else None,
            "max_risk_index": hottest["peak_risk_index"] if hottest else None,
            "max_risk_level": hottest["peak_level"] if hottest else None,
            "level_counts": level_counts,
        },
    }


def _first_exceedance(
    points: list[tuple[int, float | None]], threshold: float
) -> float | None:
    """Earliest minute the risk ratio reaches ``threshold`` (entering kritik).

    ``points`` are ``(horizon_minute, risk_ratio)`` ascending by horizon, where
    ``risk_ratio`` may be ``None`` (no capacity to measure against). Because the
    engine only produces a cumulative forecast at discrete horizons, the exact
    crossing minute is linearly interpolated between the last below-threshold
    horizon and the first at/above one (e.g. ``T+47``). If the very first
    horizon already exceeds the threshold we cannot resolve an earlier minute,
    so that horizon is reported (a conservative upper bound); if no horizon
    reaches the threshold the gap never opens within the forecast window.
    """
    prev_minute: int = 0
    prev_ratio: float | None = None
    for minute, ratio in points:
        if ratio is None:
            return float(minute)  # no capacity -> unmeasurable, worst-case now
        if ratio >= threshold:
            if prev_ratio is None or prev_ratio >= threshold or ratio == prev_ratio:
                return float(minute)
            fraction = (threshold - prev_ratio) / (ratio - prev_ratio)
            return round(prev_minute + fraction * (minute - prev_minute), 1)
        prev_minute, prev_ratio = minute, ratio
    return None


def capacity_gap_timeline(
    session: Session, settings: Any, event_key: str | None = None
) -> dict[str, Any]:
    """Per-event capacity-gap timeline and the first ``kritik`` exceedance.

    EM-030 answers "when does my capacity run out?": for every scored event it
    exposes the same horizon rows as :func:`compute_risk_index` as a time
    series (demand, constant effective capacity, the gap and the risk band per
    minute) plus the interpolated minute at which the ratio first enters the
    ``kritik`` band (``>= RISK_INDEX_CRITICAL_NEAR_MAX``).
    """
    thresholds = level_thresholds(settings)
    horizon_minutes = [
        int(h) for h in getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
    ]
    capacity = effective_capacity(session, settings)
    total_capacity = float(capacity["total_effective_ha_per_hour"])
    events = _active_events(session, event_key)
    forecasts = _latest_forecasts(session, {str(e.event_key) for e in events})
    kritik = thresholds["critical_near_max"]

    scored: list[dict[str, Any]] = []
    for event in events:
        rows = _horizons_for(
            str(event.event_key), forecasts, horizon_minutes, total_capacity, thresholds
        )
        series = [
            {
                "minute": row["horizon_minutes"],
                "area_ha": row["area_ha"],
                "demand_ha_h": row["demand_ha_h"],
                "capacity_ha_h": round(total_capacity, 3),
                "gap_ha_h": row["gap_ha_h"],
                "risk_index": row["risk_index"],
                "level": row["level"],
            }
            for row in rows
        ]
        first = _first_exceedance(
            [(row["horizon_minutes"], row["risk_index"]) for row in rows], kritik
        )
        scored.append(
            {
                "event_key": str(event.event_key),
                "name": event.name,
                "latitude": float(event.latitude),
                "longitude": float(event.longitude),
                "status": str(event.status),
                "series": series,
                "first_exceedance_minute": first,
                "first_exceedance_level": "kritik" if first is not None else None,
                "exceedance_threshold": kritik,
            }
        )

    over = [e for e in scored if e["first_exceedance_minute"] is not None]
    soonest = min(over, key=lambda e: e["first_exceedance_minute"], default=None)
    return {
        "panel": "capacity_gap_timeline",
        "generated_at": to_utc_iso(utc_now()),
        "unit": capacity["unit"],
        "capacity_effective_ha_h": total_capacity,
        "thresholds": thresholds,
        "levels": list(RISK_LEVELS),
        "exceedance_level": "kritik",
        "attribution": RISK_ATTRIBUTION,
        "events": scored,
        "summary": {
            "events_scored": len(scored),
            "events_over_threshold": len(over),
            "first_exceedance_event": soonest["event_key"] if soonest else None,
            "first_exceedance_minute": soonest["first_exceedance_minute"]
            if soonest
            else None,
        },
    }
