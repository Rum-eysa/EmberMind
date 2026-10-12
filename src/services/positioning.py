"""Proactive resource positioning proposals (EM-052, Epic E5).

For a fire event, rank the nearest available suppression resources by their
closure-aware road route to the incident and expose the recommended deployment
point plus the route geometry and ETA. The suggestion is computed live on every
request (no persistence) so it always reflects the current resource statuses and
active road closures. Routing reuses the EM-011 road-network graph.

EM-050 layers *constraint-based* filtering on top of the ranking: an origin
whose route violates its declared menzil (``range_km``), duty/endurance
(``shift_minutes``) or night-operation limit (``night_capable``), or that the
active road closures made unreachable, never becomes a proposal - it moves to
the rejected list carrying the violated constraint names and a human reason.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.inventory import SuppressionResource
from src.models.road_network import CrewBase, RoadSegment
from src.models.spatial import FireEvent
from src.services.road_network import (
    RoadNetworkError,
    RoadNetworkGraph,
    active_closure_keys,
    haversine_km,
)

POSITIONING_ATTRIBUTION = (
    "Önerilen konuşlanma ve rotalar: EmberMind yol ağı routing motoru (EM-052)"
)

# Resource kinds that fly great-circle instead of following the road graph
# (EM-049). Ground crews (and crew bases) remain closure-aware road-routed.
AIRBORNE_TYPES = frozenset({"helicopter", "uav"})

# EM-050: constraint identifiers surfaced on every rejected origin.
CONSTRAINT_NAMES = ("range", "shift", "night", "road_closure")
CONSTRAINT_ATTRIBUTION = (
    "Kısıt tabanlı öneri elenme nedenleri (menzil/mesai/gece/yol kapalılığı): EM-050"
)

# Night window in UTC used by the night-operation ban; approximates the local
# operating hours of the pilot region (TR/EL, roughly UTC+3 in summer) so the
# ban engages when crews would arrive after dusk.
_NIGHT_START_UTC = 20
_NIGHT_END_UTC = 5


def _is_airborne(resource_type: str) -> bool:
    """True when the resource type flies (helicopter / uav), else ground."""
    return str(resource_type).strip().lower() in AIRBORNE_TYPES


def _is_night_hour(arrival: datetime) -> bool:
    """True when the arrival instant falls inside the night window."""
    return arrival.hour >= _NIGHT_START_UTC or arrival.hour < _NIGHT_END_UTC


# A resource origin/destination is described as a ``(latitude, longitude)`` pair.
Coord = tuple[float, float]


class PositioningError(RuntimeError):
    """Raised when a positioning request references an unknown fire event."""


def _resolve_destination(session: Session, event_key: str | None) -> Coord:
    """Return the ``(lat, lon)`` of the fire event to defend."""
    if not event_key:
        raise PositioningError("event_key is required for resource positioning")
    event = session.scalar(select(FireEvent).where(FireEvent.event_key == event_key))
    if event is None:
        raise PositioningError(f"fire event {event_key} not found")
    return (float(event.latitude), float(event.longitude))  # type: ignore[arg-type]


def _available_origins(session: Session) -> list[dict[str, Any]]:
    """Collect available crew bases and suppression assets as routing origins."""
    origins: list[dict[str, Any]] = []
    for base in session.scalars(select(CrewBase).where(CrewBase.available.is_(True))):
        origins.append(
            {
                "kind": "crew_base",
                "resource_key": str(base.base_key),
                "name": str(base.name),
                "resource_type": str(base.crew_type),
                "coord": (float(base.latitude), float(base.longitude)),  # type: ignore[arg-type]
                "range_km": base.range_km,  # type: ignore[misc]
                "shift_minutes": base.shift_minutes,  # type: ignore[misc]
                "night_capable": base.night_capable,  # type: ignore[misc]
            }
        )
    for asset in session.scalars(
        select(SuppressionResource).where(SuppressionResource.status == "available")
    ):
        origins.append(
            {
                "kind": "suppression_resource",
                "resource_key": str(asset.resource_key),
                "name": str(asset.name),
                "resource_type": str(asset.resource_type),
                "coord": (float(asset.latitude), float(asset.longitude)),  # type: ignore[arg-type]
                # EM-050 optional limits; None columns stay None (unbounded).
                "range_km": asset.range_km,  # type: ignore[misc]
                "shift_minutes": asset.shift_minutes,  # type: ignore[misc]
                "night_capable": asset.night_capable,  # type: ignore[misc]
            }
        )
    return origins


def _route_coordinates(
    origin: Coord,
    destination: Coord,
    path_keys: list[str],
    segment_geom: dict[str, tuple[Coord, Coord]],
) -> list[list[float]]:
    """Rebuild a [lon, lat] LineString by chaining routed segments end to end."""
    coords: list[list[float]] = [[origin[1], origin[0]]]
    current = origin
    for key in path_keys:
        geom = segment_geom.get(key)
        if geom is None:
            continue
        a, b = geom
        # Pick the endpoint that connects to where we currently are.
        nxt = b if haversine_km(*current, *a) > haversine_km(*current, *b) else a
        coords.append([nxt[1], nxt[0]])
        current = nxt
    coords.append([destination[1], destination[0]])
    return coords


def _reject_summary(
    origin: dict[str, Any], event_key: str | None, travel_mode: str
) -> dict[str, Any]:
    """Common identity fields carried by every EM-050 rejection entry."""
    return {
        "resource_key": origin["resource_key"],
        "name": origin["name"],
        "resource_type": origin["resource_type"],
        "kind": origin["kind"],
        "event_key": event_key,
        "travel_mode": travel_mode,
    }


def _assess_constraints(
    origin: dict[str, Any],
    minutes: float,
    km: float,
    now_utc: datetime,
    night_ban_enabled: bool,
) -> tuple[list[str], str] | None:
    """EM-050: violated constraints for a routed origin, or ``None`` if clean.

    A ``None`` limit means "unknown / unconstrained" and never rejects, so the
    check is fully backward compatible for inventories without declared limits.
    """
    violations: list[str] = []
    reasons: list[str] = []
    range_km = origin.get("range_km")
    if range_km is not None and km > float(range_km):
        violations.append("range")
        reasons.append(f"menzil {float(range_km):.0f} km, rot {km:.1f} km")
    shift_minutes = origin.get("shift_minutes")
    if shift_minutes is not None and minutes > float(shift_minutes):
        violations.append("shift")
        reasons.append(
            f"mesai/yakıt {float(shift_minutes):.0f} dk, ETA {minutes:.0f} dk"
        )
    if (
        night_ban_enabled
        and origin.get("night_capable") is False
        and _is_night_hour(now_utc + timedelta(minutes=minutes))
    ):
        violations.append("night")
        reasons.append("gece operasyonu yasak: birim gece yetkisi yok")
    if not violations:
        return None
    return violations, "; ".join(reasons)


def build_proposals(
    session: Session,
    settings: Any,
    event_key: str | None,
    limit: int | None = None,
    now_utc: datetime | None = None,
    rejected_out: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rank available resources by route ETA to the fire event's location.

    Returns the top ``limit`` proposals (default ``POSITIONING_MAX_PROPOSALS``),
    each carrying the recommended deployment point, the route LineString and the
    closure-aware ETA. Raises :class:`PositioningError` for an unknown event and
    :class:`RoadNetworkError` when no road network is available to route on.

    EM-050: origins that violate a declared constraint (menzil / mesai / gece,
    or left unreachable by an active road closure) are excluded from the
    proposals and appended to ``rejected_out`` with their constraint names and
    a human-readable reason.
    """
    destination = _resolve_destination(session, event_key)
    origins = _available_origins(session)
    now_utc = now_utc or datetime.now(timezone.utc)

    segments = list(session.scalars(select(RoadSegment)).all())
    if not segments:
        raise RoadNetworkError("road network is empty; import it before positioning")

    access_speed = float(getattr(settings, "ROAD_ACCESS_SPEED_KMH", 40.0))
    air_speed = float(getattr(settings, "POSITIONING_AIR_SPEED_KMH", 220.0))
    excluded = active_closure_keys(session)
    night_ban = bool(getattr(settings, "POSITIONING_NIGHT_BAN_ENABLED", True))
    graph = RoadNetworkGraph.from_segments(
        segments, access_speed_kmh=access_speed, excluded_segment_keys=excluded
    )
    segment_geom = {
        str(seg.segment_key): (
            (float(seg.from_lat), float(seg.from_lon)),  # type: ignore[arg-type]
            (float(seg.to_lat), float(seg.to_lon)),  # type: ignore[arg-type]
        )
        for seg in segments
    }
    # Only pay for a second (closure-free) graph when closures actually exist.
    open_graph = (
        RoadNetworkGraph.from_segments(segments, access_speed_kmh=access_speed)
        if excluded
        else None
    )

    proposals: list[dict[str, Any]] = []
    for idx, origin in enumerate(origins):
        airborne = _is_airborne(origin["resource_type"])
        delay = 0.0
        if airborne:
            # Aerial assets fly great-circle at cruise speed; road closures never
            # block them, so they are always reachable and incur no detour delay.
            origin_lat, origin_lon = origin["coord"]
            km = haversine_km(origin_lat, origin_lon, destination[0], destination[1])
            minutes = (km / air_speed * 60.0) if air_speed > 0 else float("inf")
            reachable = air_speed > 0
            travel_mode = "air"
            coords = (
                [
                    [origin["coord"][1], origin["coord"][0]],
                    [destination[1], destination[0]],
                ]
                if reachable
                else []
            )
        else:
            minutes, km, path = graph.shortest_route(origin["coord"], destination)
            reachable = not math.isinf(minutes)
            travel_mode = "road"
            if reachable and open_graph is not None:
                open_minutes, _, _ = open_graph.shortest_route(
                    origin["coord"], destination
                )
                if not math.isinf(open_minutes):
                    delay = max(0.0, minutes - open_minutes)
            coords = (
                _route_coordinates(origin["coord"], destination, path, segment_geom)
                if reachable
                else []
            )
        # EM-050: in filtering mode (``rejected_out`` supplied) an unusable
        # origin never reaches the proposal list; it is rejected with the
        # violated constraints shown. Without the sink the EM-052 ranking
        # contract is untouched (EM-046 explain relies on it), but a violation
        # is still annotated on the proposal so no consumer can miss it.
        if not reachable:
            if rejected_out is not None:
                rejected_out.append(
                    {
                        **_reject_summary(origin, event_key, travel_mode),
                        "constraints": ["road_closure"],
                        "reason": "yol kapanmaları nedeniyle ulaşılabilir değil",
                    }
                )
                continue
        breach = (
            _assess_constraints(origin, minutes, km, now_utc, night_ban)
            if reachable
            else None
        )
        if breach is not None and rejected_out is not None:
            rejected_out.append(
                {
                    **_reject_summary(origin, event_key, travel_mode),
                    "constraints": breach[0],
                    "reason": breach[1],
                    "eta_minutes": round(minutes, 2),
                    "distance_km": round(km, 3),
                }
            )
            continue
        proposal = {
            "proposal_id": f"prop-{idx}-{origin['resource_key']}",
            "kind": origin["kind"],
            "resource_key": origin["resource_key"],
            "name": origin["name"],
            "resource_type": origin["resource_type"],
            "event_key": event_key,
            "travel_mode": travel_mode,
            "reachable": reachable,
            "eta_minutes": round(minutes, 2) if reachable else None,
            "distance_km": round(km, 3) if reachable else None,
            "delay_vs_open_minutes": round(delay, 2),
            "deployment_point": {
                "latitude": destination[0],
                "longitude": destination[1],
            },
            "route": {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "kind": "positioning_route",
                    "proposal_id": f"prop-{idx}-{origin['resource_key']}",
                    "name": origin["name"],
                    "resource_type": origin["resource_type"],
                    "travel_mode": travel_mode,
                    "eta_minutes": round(minutes, 2) if reachable else None,
                    "distance_km": round(km, 3) if reachable else None,
                },
            },
        }
        proposals.append(proposal)
        # EM-050 no-sink mode: keep the historical EM-052 ranking contract,
        # but annotate any violation so no consumer can miss it.
        if rejected_out is None:
            if not reachable:
                proposal["constraint_violations"] = ["road_closure"]
            elif breach is not None:
                proposal["constraint_violations"] = breach[0]
                proposal["constraint_reason"] = breach[1]

    proposals.sort(
        key=lambda p: (
            not p["reachable"],
            p["eta_minutes"] if p["eta_minutes"] is not None else float("inf"),
        )
    )
    cap = (
        limit
        if limit is not None
        else int(getattr(settings, "POSITIONING_MAX_PROPOSALS", 5))
    )
    return proposals[: max(0, cap)]


def positioning_layer(
    session: Session, settings: Any, event_key: str | None = None
) -> dict[str, Any]:
    """GeoJSON FeatureCollection of deployment points and routes for the map.

    Emits one Point (recommended deployment) and one LineString (route) per
    reachable proposal. An unknown event or an empty network yields an empty
    collection so the map layer never errors on toggle.
    """
    features: list[dict[str, Any]] = []
    try:
        proposals = build_proposals(session, settings, event_key)
    except (PositioningError, RoadNetworkError):
        proposals = []
    for proposal in proposals:
        if not proposal["reachable"]:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        proposal["deployment_point"]["longitude"],
                        proposal["deployment_point"]["latitude"],
                    ],
                },
                "properties": {
                    "kind": "deployment_point",
                    "proposal_id": proposal["proposal_id"],
                    "resource_key": proposal["resource_key"],
                    "event_key": proposal["event_key"],
                    "name": proposal["name"],
                    "resource_type": proposal["resource_type"],
                    "travel_mode": proposal["travel_mode"],
                    "eta_minutes": proposal["eta_minutes"],
                    "distance_km": proposal["distance_km"],
                },
            }
        )
        features.append(proposal["route"])
    return {
        "type": "FeatureCollection",
        "layer": "positioning",
        "title": "Önerilen Konuşlanma ve Rotalar",
        "count": len(features),
        "attribution": POSITIONING_ATTRIBUTION,
        "event_key": event_key,
        "features": features,
    }
