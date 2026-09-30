"""Proactive resource positioning proposals (EM-052, Epic E5).

For a fire event, rank the nearest available suppression resources by their
closure-aware road route to the incident and expose the recommended deployment
point plus the route geometry and ETA. The suggestion is computed live on every
request (no persistence) so it always reflects the current resource statuses and
active road closures. Routing reuses the EM-011 road-network graph.
"""
import math
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


def build_proposals(
    session: Session,
    settings: Any,
    event_key: str | None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Rank available resources by route ETA to the fire event's location.

    Returns the top ``limit`` proposals (default ``POSITIONING_MAX_PROPOSALS``),
    each carrying the recommended deployment point, the route LineString and the
    closure-aware ETA. Raises :class:`PositioningError` for an unknown event and
    :class:`RoadNetworkError` when no road network is available to route on.
    """
    destination = _resolve_destination(session, event_key)
    origins = _available_origins(session)

    segments = list(session.scalars(select(RoadSegment)).all())
    if not segments:
        raise RoadNetworkError("road network is empty; import it before positioning")

    access_speed = float(getattr(settings, "ROAD_ACCESS_SPEED_KMH", 40.0))
    excluded = active_closure_keys(session)
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
        minutes, km, path = graph.shortest_route(origin["coord"], destination)
        reachable = not math.isinf(minutes)
        delay = 0.0
        if reachable and open_graph is not None:
            open_minutes, _, _ = open_graph.shortest_route(origin["coord"], destination)
            if not math.isinf(open_minutes):
                delay = max(0.0, minutes - open_minutes)
        coords = (
            _route_coordinates(origin["coord"], destination, path, segment_geom)
            if reachable
            else []
        )
        proposal = {
            "proposal_id": f"prop-{idx}-{origin['resource_key']}",
            "kind": origin["kind"],
            "resource_key": origin["resource_key"],
            "name": origin["name"],
            "resource_type": origin["resource_type"],
            "event_key": event_key,
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
                    "eta_minutes": round(minutes, 2) if reachable else None,
                    "distance_km": round(km, 3) if reachable else None,
                },
            },
        }
        proposals.append(proposal)

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
