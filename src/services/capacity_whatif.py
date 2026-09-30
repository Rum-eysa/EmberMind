"""Capacity-change what-if (EM-056, Epic E6).

The commander asks a *supply* question rather than the wind what-if's *demand*
one: "if I add two helicopters and a crew, how does the capacity gap change?"
This scenario keeps the spread forecast fixed (the demand each horizon implies,
exactly as EM-029 measures it) and re-prices it against a hypothetical capacity
— the live effective capacity (EM-028) plus the requested extra units valued at
their per-type ha/hour assumption.

For every active (or one explicitly chosen) event it reports the gap and risk
band before and after the addition per horizon, and flags the incidents the
reinforcement actually **resolves** (gap was open, now closed), which is the
evidence a support request needs. Like the wind what-if it is fully ephemeral:
no resources are booked and nothing is persisted.
"""
from typing import Any

from sqlalchemy.orm import Session

from src.models.inventory import RESOURCE_TYPES
from src.services.capacity import assumption_map, effective_capacity
from src.services.risk_index import (  # noqa: PLC2701 - reuse the EM-029 engine
    RISK_ATTRIBUTION,
    RISK_LEVELS,
    RiskIndexError,
    _active_events,
    _horizons_for,
    _latest_forecasts,
    level_thresholds,
)
from src.utils.timeutils import to_utc_iso, utc_now

CAPACITY_WHATIF_PANEL = "capacity_whatif"
CAPACITY_WHATIF_ATTRIBUTION = "What-if kapasite senaryosu: sabit EM-029 talebi / varsayıms EM-028 kapasitesi (EM-056)"
CAPACITY_WHATIF_PERSISTENCE = "none"


class CapacityWhatIfError(RuntimeError):
    """Raised for invalid capacity what-if inputs (bad type or count)."""


def _validated_added(added: dict[str, Any]) -> dict[str, int]:
    """Normalise the operator's extra units to resource_type -> whole count."""
    result: dict[str, int] = {}
    for raw_type, raw_count in (added or {}).items():
        try:
            canonical = str(raw_type).strip().lower()
        except (AttributeError, TypeError) as exc:
            raise CapacityWhatIfError("resource type must be a string") from exc
        if canonical not in RESOURCE_TYPES:
            raise CapacityWhatIfError(f"unknown resource type: {raw_type!r}")
        try:
            count = int(raw_count)
        except (TypeError, ValueError) as exc:
            raise CapacityWhatIfError(
                f"added count for '{canonical}' must be an integer"
            ) from exc
        if count < 0:
            raise CapacityWhatIfError(f"added count for '{canonical}' must be >= 0")
        if count:
            result[canonical] = result.get(canonical, 0) + count
    return result


def scenario_capacity(
    session: Session, settings: Any, added: dict[str, int]
) -> dict[str, Any]:
    """Effective capacity plus the extra units priced at their ha/hour."""
    effective = effective_capacity(session, settings)
    assumptions = assumption_map(session, settings)
    current = float(effective["total_effective_ha_per_hour"])
    added_ha_h = 0.0
    breakdown: dict[str, dict[str, Any]] = {}
    for rtype, count in added.items():
        ha_per_hour = float(assumptions.get(rtype, 0.0))
        contribution = round(count * ha_per_hour, 3)
        added_ha_h += contribution
        breakdown[rtype] = {
            "count": count,
            "ha_per_hour": ha_per_hour,
            "added_ha_per_hour": contribution,
        }
    scenario = round(max(0.0, current + added_ha_h), 3)
    return {
        "unit": effective["unit"],
        "current_ha_h": round(current, 3),
        "scenario_ha_h": scenario,
        "delta_ha_h": round(scenario - current, 3),
        "assumptions_ha_h": assumptions,
        "added_breakdown": breakdown,
    }


def run_capacity_whatif(
    session: Session,
    settings: Any,
    added: dict[str, Any],
    event_key: str | None = None,
) -> dict[str, Any]:
    """Re-price every event's spread demand against the reinforced capacity."""
    added_units = _validated_added(added)
    thresholds = level_thresholds(settings)
    horizon_minutes = [
        int(h) for h in getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
    ]
    caps = scenario_capacity(session, settings, added_units)
    current = caps["current_ha_h"]
    scenario = caps["scenario_ha_h"]

    events = _active_events(session, event_key)  # raises RiskIndexError (unknown key)
    forecasts = _latest_forecasts(session, {str(e.event_key) for e in events})

    scored: list[dict[str, Any]] = []
    resolved = 0
    for event in events:
        key = str(event.event_key)
        original = {
            row["horizon_minutes"]: row
            for row in _horizons_for(
                key, forecasts, horizon_minutes, current, thresholds
            )
        }
        scenario_rows = _horizons_for(
            key, forecasts, horizon_minutes, scenario, thresholds
        )
        horizons: list[dict[str, Any]] = []
        for srow in scenario_rows:
            minute = srow["horizon_minutes"]
            orow = original.get(minute, {})
            was_open = float(orow.get("gap_ha_h", 0.0)) > 0.0
            now_closed = float(srow["gap_ha_h"]) == 0.0
            fixes = was_open and now_closed
            horizons.append(
                {
                    "horizon_minutes": minute,
                    "demand_ha_h": srow["demand_ha_h"],
                    "current_gap_ha_h": orow.get("gap_ha_h", 0.0),
                    "scenario_gap_ha_h": srow["gap_ha_h"],
                    "gap_delta_ha_h": round(
                        float(srow["gap_ha_h"]) - float(orow.get("gap_ha_h", 0.0)), 3
                    ),
                    "current_risk_index": orow.get("risk_index"),
                    "scenario_risk_index": srow["risk_index"],
                    "current_level": orow.get("level", "normal"),
                    "scenario_level": srow["level"],
                    "resolves_gap": fixes,
                }
            )
        peak = max(horizons, key=lambda row: row["horizon_minutes"], default=None)
        event_resolved = bool(
            peak
            and float(peak["current_gap_ha_h"]) > 0.0
            and float(peak["scenario_gap_ha_h"]) == 0.0
        )
        if event_resolved:
            resolved += 1
        scored.append(
            {
                "event_key": key,
                "name": event.name,
                "latitude": float(event.latitude),
                "longitude": float(event.longitude),
                "status": str(event.status),
                "horizons": horizons,
                "peak": peak,
                "resolved_by_addition": event_resolved,
            }
        )

    return {
        "panel": CAPACITY_WHATIF_PANEL,
        "generated_at": to_utc_iso(utc_now()),
        "unit": caps["unit"],
        "horizon_minutes": sorted(horizon_minutes),
        "thresholds": thresholds,
        "levels": list(RISK_LEVELS),
        "added_resources": added_units,
        "capacity": caps,
        "attribution": CAPACITY_WHATIF_ATTRIBUTION,
        "related_attribution": RISK_ATTRIBUTION,
        "persistence": CAPACITY_WHATIF_PERSISTENCE,
        "events": scored,
        "summary": {
            "events_scored": len(scored),
            "events_with_forecast": sum(1 for e in scored if e["horizons"]),
            "events_resolved_by_addition": resolved,
        },
    }


__all__ = [
    "CAPACITY_WHATIF_ATTRIBUTION",
    "CAPACITY_WHATIF_PANEL",
    "CapacityWhatIfError",
    "RiskIndexError",
    "run_capacity_whatif",
    "scenario_capacity",
]
