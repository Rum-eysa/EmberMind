"""Commander capacity & risk panel aggregation (EM-073).

One payload for the command panel: per-zone risk index (daily FWI), the
threshold colour of each zone, the first moment (day) each zone breached the
configurable risk threshold, and the suppression-capacity breakdown (crew
bases by type/availability, active incidents, active road closures).
"""
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.fwi import FireWeatherIndex
from src.models.road_network import CrewBase, RoadClosure
from src.models.spatial import FireEvent
from src.services.fwi import RISK_COLORS, RISK_ORDER
from src.services.inventory import capacity_summary
from src.utils.timeutils import to_utc_iso, utc_now


def _latest_fwi_day(session: Session) -> date | None:
    """Most recent day stored in the FWI layer (panel reference day)."""
    return session.scalar(select(func.max(FireWeatherIndex.day)))


def first_exceedance_days(session: Session, threshold: float) -> dict[str, str]:
    """First day per zone whose FWI reached/exceeded the risk threshold."""
    rows = session.execute(
        select(FireWeatherIndex.zone_key, func.min(FireWeatherIndex.day))
        .where(FireWeatherIndex.fwi >= threshold)
        .group_by(FireWeatherIndex.zone_key)
    ).all()
    return {str(zone): day.isoformat() for zone, day in rows if day is not None}


def zone_risk_rows(
    session: Session, day: date | None, threshold: float
) -> list[dict[str, Any]]:
    """Panel cards for every zone on the reference day, hottest first."""
    if day is None:
        return []
    exceedance = first_exceedance_days(session, threshold)
    rows = session.scalars(
        select(FireWeatherIndex)
        .where(FireWeatherIndex.day == day)
        .order_by(FireWeatherIndex.fwi.desc())
    ).all()
    zones: list[dict[str, Any]] = []
    for row in rows:
        category = str(row.risk_category)
        zones.append(
            {
                "zone_key": str(row.zone_key),
                "region_name": str(row.region_name),
                "risk_index": round(float(row.fwi), 2),
                "risk_category": category,
                "threshold_color": RISK_COLORS.get(category, "#cccccc"),
                "over_threshold": bool(float(row.fwi) >= threshold),
                "first_exceedance_day": exceedance.get(str(row.zone_key)),
                "isi": round(float(row.isi), 2),
                "drought_category": str(row.drought_category),
            }
        )
    return zones


def capacity_breakdown(session: Session) -> dict[str, Any]:
    """Suppression capacity: crew bases by type, incidents, road closures.

    The EM-103 coordinator inventory (crew / helicopter / uav assets) rides
    along in ``inventory`` so the command panel capacity account stays
    current with what the coordinator manages.
    """
    by_type: dict[str, dict[str, int]] = {}
    total_bases = 0
    available_bases = 0
    for base in session.scalars(select(CrewBase).order_by(CrewBase.id)):
        crew_type = str(base.crew_type)
        bucket = by_type.setdefault(
            crew_type, {"total": 0, "available": 0, "unavailable": 0}
        )
        bucket["total"] += 1
        total_bases += 1
        if bool(base.available):
            bucket["available"] += 1
            available_bases += 1
        else:
            bucket["unavailable"] += 1
    active_incidents = session.scalar(
        select(func.count()).select_from(FireEvent).where(FireEvent.status == "active")
    )
    active_closures = session.scalar(
        select(func.count())
        .select_from(RoadClosure)
        .where(RoadClosure.status == "active")
    )
    return {
        "crew_bases": {
            "total": total_bases,
            "available": available_bases,
            "unavailable": total_bases - available_bases,
            "by_crew_type": by_type,
        },
        "inventory": capacity_summary(session),
        "active_incidents": int(active_incidents or 0),
        "active_road_closures": int(active_closures or 0),
    }


def build_capacity_risk_panel(
    session: Session, settings: Any, day: date | None = None
) -> dict[str, Any]:
    """Assemble the single-panel command view (EM-073 acceptance)."""
    threshold = float(getattr(settings, "RISK_PANEL_THRESHOLD", 30.0))
    reference_day = day if day is not None else _latest_fwi_day(session)
    zones = zone_risk_rows(session, reference_day, threshold)
    hottest = zones[0] if zones else None
    over_count = sum(1 for zone in zones if zone["over_threshold"])
    return {
        "panel": "capacity_risk",
        "generated_at": to_utc_iso(utc_now()),
        "day": reference_day.isoformat() if reference_day else None,
        "risk_threshold": threshold,
        "risk_order": RISK_ORDER,
        "legend": dict(RISK_COLORS),
        "summary": {
            "zones_reported": len(zones),
            "zones_over_threshold": over_count,
            "max_risk_index": hottest["risk_index"] if hottest else None,
            "max_risk_zone": hottest["zone_key"] if hottest else None,
            "max_risk_color": hottest["threshold_color"] if hottest else None,
            "first_exceedance_day": min(
                (
                    zone["first_exceedance_day"]
                    for zone in zones
                    if zone["first_exceedance_day"]
                ),
                default=None,
            ),
        },
        "zones": zones,
        "capacity": capacity_breakdown(session),
    }
