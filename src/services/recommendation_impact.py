"""Recommendation impact comparison (EM-048, Epic E5).

The commander wants to see the *value of the decision*: side-by-side, how the
event's risk profile moves **if the positioning recommendation is applied**
versus **if it is not**. This reuses the EM-029 risk engine and the EM-056
re-pricing pattern, but instead of hypothetical extra units it uses the actual
top-N reachable resources that EM-052 recommends for the incident.

The comparison keeps the spread forecast (the demand each horizon implies) fixed
and varies only the capacity *dedicated to this event*:

- **Applied** = the recommended suppression units are secured for this incident,
  so the event's response capacity is the full effective capacity (EM-028).
- **Not applied** = those units stay in general reserve and are *not* counted for
  this incident, so its response capacity is reduced by their summed ha/hour.

Nothing is booked, mutated or persisted - the answer is computed live and is
purely advisory, so the operator can weigh the decision before acting on it.
"""
from typing import Any

from sqlalchemy.orm import Session

from src.services.capacity import assumption_map, effective_capacity
from src.services.positioning import PositioningError, build_proposals
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

IMPACT_PANEL = "recommendation_impact"
IMPACT_ATTRIBUTION = (
    "Öneri etki karşılaştırması: sabit EM-029 talebi, önerilen kaynaklar "
    "için ayrılan / ayrılmayan EM-028 kapasitesi (EM-048)"
)
IMPACT_PERSISTENCE = "none"


class ImpactError(RuntimeError):
    """Raised when the event has no positioning proposals to compare."""


def _severity(level: str) -> int:
    """Rank a risk level by severity using the EM-029 band order."""
    try:
        return list(RISK_LEVELS).index(str(level))
    except ValueError:
        return 0


def compare_impact(
    session: Session, settings: Any, event_key: str | None
) -> dict[str, Any]:
    """Return the side-by-side risk profile of applying vs not applying the
    positioning recommendation for a single fire event.

    Raises :class:`PositioningError` for an unknown event, :class:`RoadNetworkError`
    (propagated from positioning) for an empty network and :class:`ImpactError`
    when the event yields no comparable horizons.
    """
    thresholds = level_thresholds(settings)
    horizon_minutes = [
        int(h) for h in getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
    ]

    proposals = build_proposals(session, settings, event_key)
    committed = [
        p for p in proposals if p["reachable"] and p["kind"] == "suppression_resource"
    ]

    assumptions = assumption_map(session, settings)
    committed_ha_h = round(
        sum(
            float(assumptions.get(str(p["resource_type"]).strip().lower(), 0.0))
            for p in committed
        ),
        3,
    )

    effective = effective_capacity(session, settings)
    current = float(effective["total_effective_ha_per_hour"])
    applied_capacity = round(current, 3)
    not_applied_capacity = round(max(0.0, current - committed_ha_h), 3)

    events = _active_events(session, event_key)  # raises RiskIndexError (unknown key)
    event = events[0]
    key = str(event.event_key)
    forecasts = _latest_forecasts(session, {key})

    applied_rows = {
        row["horizon_minutes"]: row
        for row in _horizons_for(
            key, forecasts, horizon_minutes, applied_capacity, thresholds
        )
    }
    not_rows = {
        row["horizon_minutes"]: row
        for row in _horizons_for(
            key, forecasts, horizon_minutes, not_applied_capacity, thresholds
        )
    }

    side_by_side: list[dict[str, Any]] = []
    resolved = 0
    reduced = 0
    for minute in sorted(set(applied_rows) | set(not_rows)):
        arow = applied_rows.get(minute, {})
        nrow = not_rows.get(minute, {})
        a_gap = float(arow.get("gap_ha_h", 0.0))
        n_gap = float(nrow.get("gap_ha_h", 0.0))
        a_risk = arow.get("risk_index")
        n_risk = nrow.get("risk_index")
        fixes = n_gap > 0.0 and a_gap == 0.0
        resolved += int(fixes)
        if isinstance(a_risk, (int, float)) and isinstance(n_risk, (int, float)):
            reduced += int(a_risk < n_risk)
        side_by_side.append(
            {
                "horizon_minutes": minute,
                "demand_ha_h": arow.get("demand_ha_h", nrow.get("demand_ha_h")),
                "if_not_applied": {
                    "capacity_ha_h": not_applied_capacity,
                    "gap_ha_h": nrow.get("gap_ha_h"),
                    "risk_index": n_risk,
                    "level": nrow.get("level", "normal"),
                },
                "if_applied": {
                    "capacity_ha_h": applied_capacity,
                    "gap_ha_h": arow.get("gap_ha_h"),
                    "risk_index": a_risk,
                    "level": arow.get("level", "normal"),
                },
                "risk_index_delta": (
                    round(float(a_risk) - float(n_risk), 3)
                    if isinstance(a_risk, (int, float))
                    and isinstance(n_risk, (int, float))
                    else None
                ),
                "resolves_gap": fixes,
            }
        )

    if not side_by_side:
        raise ImpactError(
            f"fire event {event_key} has no spread forecasts to compare against"
        )

    def _worst(field: str) -> str:
        return max(
            (row[field]["level"] for row in side_by_side),
            key=_severity,
            default="normal",
        )

    return {
        "panel": IMPACT_PANEL,
        "event_key": key,
        "name": event.name,
        "generated_at": to_utc_iso(utc_now()),
        "unit": effective["unit"],
        "horizon_minutes": sorted(horizon_minutes),
        "thresholds": thresholds,
        "levels": list(RISK_LEVELS),
        "committed_resources": [
            {
                "resource_key": p["resource_key"],
                "name": p["name"],
                "resource_type": p["resource_type"],
                "travel_mode": p.get("travel_mode"),
                "eta_minutes": p["eta_minutes"],
            }
            for p in committed
        ],
        "capacity": {
            "current_ha_h": current,
            "applied_ha_h": applied_capacity,
            "not_applied_ha_h": not_applied_capacity,
            "committed_ha_h": committed_ha_h,
        },
        "side_by_side": side_by_side,
        "summary": {
            "horizons_compared": len(side_by_side),
            "horizons_resolved_by_applying": resolved,
            "horizons_risk_reduced": reduced,
            "worst_level_if_not_applied": _worst("if_not_applied"),
            "worst_level_if_applied": _worst("if_applied"),
            "decision_has_value": reduced > 0 or resolved > 0,
        },
        "attribution": IMPACT_ATTRIBUTION,
        "related_attribution": RISK_ATTRIBUTION,
        "persistence": IMPACT_PERSISTENCE,
    }


__all__ = [
    "IMPACT_ATTRIBUTION",
    "IMPACT_PANEL",
    "ImpactError",
    "PositioningError",
    "RiskIndexError",
    "compare_impact",
]
