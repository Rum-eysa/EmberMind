"""Resource recommendation engine value metric (EM-045, Epic E5).

EM-045 asks that every ranked proposal in the positioning engine carry an
*expected risk reduction* so the commander sees, at a glance, what each single
suggestion is actually worth ("şimdi ne yapmalıyım?" -> a ranked list where each
row states how much it lowers the incident's risk).

EM-048 already compares the **whole** top-N recommendation applied vs not.
Here we isolate a **single unit**: how far the event's peak EM-029 risk index
would fall if *this* resource is dedicated to the incident versus held back in
general reserve. The metric honours the arrival time - a unit only helps the
horizons it can physically reach in time - so a fast, capable crew scores higher
than a slow or distant one for the same fire.

Nothing is booked, mutated or persisted: the value is computed live and is
purely advisory, layered on top of the EM-052 proposals without touching the
ranking contract the explain / impact / constraint consumers rely on.
"""
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.services.capacity import assumption_map, effective_capacity
from src.services.risk_index import (  # noqa: PLC2701 - reuse the EM-029 engine
    RiskIndexError,
    _active_events,
    _latest_forecasts,
    demand_ha_h,
)

ENGINE_ATTRIBUTION = (
    "Öneri başına beklenen risk düşüşü: EM-029 tepe riski üzerinde tek bir "
    "kaynağın, varış süresine duyarlı marjinal etkisi (EM-045)"
)
ENGINE_PERSISTENCE = "none"


def marginal_risk_reduction(
    area_by_horizon: dict[int, float],
    unit_ha: float,
    eta_minutes: Optional[float],
    total_capacity: float,
) -> Optional[float]:
    """Peak-risk drop attributable to dedicating a single ``unit_ha`` resource.

    ``area_by_horizon`` maps each forecast horizon (minutes) to its cumulative
    predicted area (ha) for the event; ``total_capacity`` is the event's
    effective capacity with the unit secured, so holding it back leaves
    ``total_capacity - unit_ha`` available. The unit only counts toward a horizon
    it can reach in time (``eta_minutes <= horizon``), so the reduction is
    measured at the worst *without-the-unit* horizon and can be ``0.0`` when the
    unit arrives too late to help that moment. ``None`` means the value is not
    measurable (no baseline capacity, no positive unit capacity or no forecast).
    """
    if total_capacity <= 0 or unit_ha <= 0:
        return None
    cap_without = total_capacity - unit_ha
    # A non-positive baseline makes the without-side risk unbounded, so a finite
    # marginal delta cannot be expressed; report it as not measurable.
    if cap_without <= 0:
        return None

    worst: Optional[tuple[int, float, float]] = None
    for minute in sorted(area_by_horizon):
        demand = demand_ha_h(area_by_horizon[minute], minute)
        risk_without = demand / cap_without
        on_station = eta_minutes is not None and eta_minutes <= minute
        cap_with = total_capacity if on_station else cap_without
        risk_with = demand / cap_with if cap_with > 0 else 0.0
        if worst is None:
            worst = (minute, risk_without, risk_with)
        elif risk_without > worst[1]:
            worst = (minute, risk_without, risk_with)

    if worst is None:
        return None
    reduction = worst[1] - worst[2]
    return round(max(0.0, reduction), 3)


def enrich_proposals(
    session: Session, settings: Any, event_key: str, proposals: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach an ``expected_risk_reduction`` value to every ranked proposal.

    Reachable suppression resources get a marginal peak-risk-reduction number;
    crew bases, unreachable origins and units with no configured capacity get
    ``None``. The proposals are annotated in place (the EM-052 ranking is left
    untouched) and returned for convenience.
    """
    horizon_minutes = [
        int(h) for h in getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
    ]
    assumptions = assumption_map(session, settings)
    effective = effective_capacity(session, settings)
    total_capacity = float(effective["total_effective_ha_per_hour"])

    events = _active_events(session, event_key)  # raises RiskIndexError (unknown key)
    key = str(events[0].event_key)
    forecasts = _latest_forecasts(session, {key})
    area_by_horizon = {
        minute: forecasts[(key, minute)]
        for minute in horizon_minutes
        if (key, minute) in forecasts
    }

    for proposal in proposals:
        if proposal["kind"] != "suppression_resource" or not proposal["reachable"]:
            proposal["expected_risk_reduction"] = None
            continue
        unit_ha = float(
            assumptions.get(str(proposal["resource_type"]).strip().lower(), 0.0)
        )
        proposal["expected_risk_reduction"] = marginal_risk_reduction(
            area_by_horizon,
            unit_ha,
            proposal.get("eta_minutes"),
            total_capacity,
        )
    return proposals


__all__ = [
    "ENGINE_ATTRIBUTION",
    "ENGINE_PERSISTENCE",
    "RiskIndexError",
    "enrich_proposals",
    "marginal_risk_reduction",
]
