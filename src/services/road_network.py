"""Road network import (OpenStreetMap/Overpass), routing graph, ETA and closure recalculation."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import heapq
import math
import time
from typing import Any, Callable, Optional

import requests  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.road_network import CrewBase, RoadClosure, RoadSegment

BoundingBox = tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)


class RoadNetworkError(RuntimeError):
    """Raised when road network data cannot be fetched, parsed or routed."""


class RoadSegmentNotFoundError(RoadNetworkError):
    """Raised when a routing or closure request references an unknown road segment."""


# Default travel speed (km/h) per OSM highway classification for the pilot region.
HIGHWAY_SPEED_KMH: dict[str, float] = {
    "motorway": 130.0,
    "motorway_link": 110.0,
    "trunk": 110.0,
    "trunk_link": 90.0,
    "primary": 90.0,
    "primary_link": 70.0,
    "secondary": 80.0,
    "secondary_link": 60.0,
    "tertiary": 70.0,
    "tertiary_link": 50.0,
    "unclassified": 50.0,
    "residential": 50.0,
    "living_street": 30.0,
    "service": 30.0,
    "road": 50.0,
    "track": 30.0,
    "path": 15.0,
    "footway": 15.0,
}
DEFAULT_SPEED_KMH = 50.0


def speed_for_highway(highway: str) -> float:
    """Return the assumed travel speed for an OSM highway classification."""
    return HIGHWAY_SPEED_KMH.get((highway or "").strip().lower(), DEFAULT_SPEED_KMH)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 coordinates in kilometres."""
    radius_km = 6371.0088
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius_km * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class NormalizedSegment:
    """A single directed road link normalised from OpenStreetMap."""

    segment_key: str
    osm_way_id: int
    from_node_id: int
    to_node_id: int
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    highway: str
    name: Optional[str]
    length_km: float
    max_speed_kmh: float
    one_way: bool
    source: str = "OpenStreetMap"


@dataclass(frozen=True)
class RouteResult:
    """Result of a shortest-time routing query on the road network."""

    origin: tuple[float, float]
    destination: tuple[float, float]
    reachable: bool
    eta_minutes: float
    distance_km: float
    path_segment_keys: list[str] = field(default_factory=list)
    closures_avoided: int = 0
    delay_vs_open_minutes: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "reachable": self.reachable,
            "origin": {"latitude": self.origin[0], "longitude": self.origin[1]},
            "destination": {
                "latitude": self.destination[0],
                "longitude": self.destination[1],
            },
            "eta_minutes": round(self.eta_minutes, 2),
            "distance_km": round(self.distance_km, 3),
            "path_segment_keys": self.path_segment_keys,
            "closures_avoided": self.closures_avoided,
            "delay_vs_open_minutes": round(self.delay_vs_open_minutes, 2),
        }


class OverpassClient:
    """Client that imports a road network for a bounding box from OpenStreetMap."""

    def __init__(
        self,
        base_url: str = "https://overpass-api.de/api/interpreter",
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        timeout: int = 30,
        http_get: Optional[Callable[[str, dict[str, str], int], Any]] = None,
    ):
        self.base_url = base_url
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        self._http_get = http_get or self._default_http_get

    @staticmethod
    def _default_http_get(url: str, data: dict[str, str], timeout: int) -> Any:
        response = requests.post(url, data=data, timeout=timeout)  # type: ignore[no-untyped-call]
        response.raise_for_status()
        return response

    @staticmethod
    def build_query(bbox: BoundingBox) -> str:
        """Build an Overpass QL query selecting highway ways inside a bbox."""
        min_lat, min_lon, max_lat, max_lon = bbox
        bbox_arg = f"{min_lat},{min_lon},{max_lat},{max_lon}"
        return (
            "[out:json][timeout:25];"
            f'(way["highway"]({bbox_arg}););out body;>;out skel qt;'
        )

    def fetch_network(self, bbox: BoundingBox) -> list[NormalizedSegment]:
        """Fetch and parse the road network for a bounding box with retries."""
        query = self.build_query(bbox)
        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self._http_get(self.base_url, {"data": query}, self.timeout)
                payload = response.json()
                return parse_overpass_response(payload)
            except (requests.RequestException, ValueError, KeyError) as exc:
                last_exception = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_factor * (2**attempt))
        raise RoadNetworkError(
            f"Overpass request failed after {self.max_retries} attempts: {last_exception}"
        ) from last_exception


def _parse_maxspeed(tags: dict[str, Any], highway: str) -> float:
    """Extract a km/h speed limit from OSM tags, falling back to the class default."""
    raw = tags.get("maxspeed")
    if raw is not None:
        text = str(raw).strip().lower()
        match = ""
        for char in text:
            if char.isdigit():
                match += char
            else:
                break
        if match:
            value = float(match)
            if "mph" in text:
                value *= 1.60934
            if value > 0:
                return round(value, 1)
    return speed_for_highway(highway)


def parse_overpass_response(payload: dict[str, Any]) -> list[NormalizedSegment]:
    """Convert an Overpass JSON document into normalised directed road segments."""
    elements = payload.get("elements", [])
    node_coords: dict[int, tuple[float, float]] = {}
    for element in elements:
        if element.get("type") == "node":
            node_coords[int(element["id"])] = (
                float(element["lat"]),
                float(element["lon"]),
            )

    segments: list[NormalizedSegment] = []
    for element in elements:
        if element.get("type") != "way":
            continue
        tags = element.get("tags", {}) or {}
        highway = str(tags.get("highway", "unclassified"))
        if highway in ("footway", "path", "steps", "cycleway"):
            # Pedestrian/cycle links are not usable by response vehicles.
            continue
        way_id = int(element["id"])
        name = tags.get("name")
        speed = _parse_maxspeed(tags, highway)
        one_way = str(tags.get("oneway", "")).lower() in ("yes", "1", "true")
        node_ids = element.get("nodes", [])
        for idx in range(len(node_ids) - 1):
            from_id = int(node_ids[idx])
            to_id = int(node_ids[idx + 1])
            if from_id not in node_coords or to_id not in node_coords:
                continue
            from_lat, from_lon = node_coords[from_id]
            to_lat, to_lon = node_coords[to_id]
            length = haversine_km(from_lat, from_lon, to_lat, to_lon)
            if length <= 0:
                continue
            segments.append(
                NormalizedSegment(
                    segment_key=f"way{way_id}_link{idx}",
                    osm_way_id=way_id,
                    from_node_id=from_id,
                    to_node_id=to_id,
                    from_lat=from_lat,
                    from_lon=from_lon,
                    to_lat=to_lat,
                    to_lon=to_lon,
                    highway=highway,
                    name=str(name) if name else None,
                    length_km=round(length, 4),
                    max_speed_kmh=speed,
                    one_way=one_way,
                )
            )
    return segments


@dataclass
class RoadNetworkGraph:
    """In-memory directed graph supporting shortest-travel-time routing."""

    node_coords: dict[int, tuple[float, float]]
    adjacency: dict[int, list[tuple[int, float, float, str]]]
    access_speed_kmh: float = 40.0

    @classmethod
    def from_segments(
        cls,
        segments: list[RoadSegment],
        access_speed_kmh: float = 40.0,
        excluded_segment_keys: Optional[set[str]] = None,
    ) -> "RoadNetworkGraph":
        """Build a routing graph from persisted segments, skipping excluded links."""
        excluded = excluded_segment_keys or set()
        node_coords: dict[int, tuple[float, float]] = {}
        adjacency: dict[int, list[tuple[int, float, float, str]]] = {}
        for seg in segments:
            from_id = int(seg.from_node_id)  # type: ignore[arg-type]
            to_id = int(seg.to_node_id)  # type: ignore[arg-type]
            node_coords[from_id] = (float(seg.from_lat), float(seg.from_lon))  # type: ignore[arg-type]
            node_coords[to_id] = (float(seg.to_lat), float(seg.to_lon))  # type: ignore[arg-type]
            key = str(seg.segment_key)
            if key in excluded:
                continue
            length = float(seg.length_km)  # type: ignore[arg-type]
            speed = float(seg.max_speed_kmh) or DEFAULT_SPEED_KMH  # type: ignore[arg-type]
            minutes = (length / speed) * 60.0
            adjacency.setdefault(from_id, []).append((to_id, minutes, length, key))
            if not bool(seg.one_way):  # type: ignore[arg-type]
                adjacency.setdefault(to_id, []).append((from_id, minutes, length, key))
        return cls(node_coords, adjacency, access_speed_kmh)

    def nearest_node(self, lat: float, lon: float) -> Optional[int]:
        """Return the graph node closest to a coordinate."""
        best_id: Optional[int] = None
        best_dist = float("inf")
        for node_id, (nlat, nlon) in self.node_coords.items():
            dist = haversine_km(lat, lon, nlat, nlon)
            if dist < best_dist:
                best_dist = dist
                best_id = node_id
        return best_id

    def _access_minutes(self, coord: tuple[float, float], node_id: int) -> float:
        nlat, nlon = self.node_coords[node_id]
        return (
            haversine_km(coord[0], coord[1], nlat, nlon) / self.access_speed_kmh
        ) * 60.0

    def shortest_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> tuple[float, float, list[str]]:
        """Dijkstra shortest-travel-time route; returns (minutes, km, segment keys)."""
        start = self.nearest_node(*origin)
        end = self.nearest_node(*destination)
        if start is None or end is None:
            raise RoadSegmentNotFoundError("Road network graph is empty")

        access_start = self._access_minutes(origin, start)
        access_end = self._access_minutes(destination, end)

        dist_minutes: dict[int, float] = {start: 0.0}
        dist_km: dict[int, float] = {start: 0.0}
        prev: dict[int, tuple[int, str]] = {}
        visited: set[int] = set()
        heap: list[tuple[float, int]] = [(0.0, start)]

        while heap:
            current_min, node = heapq.heappop(heap)
            if node in visited:
                continue
            visited.add(node)
            if node == end:
                break
            for neighbor, minutes, length, key in self.adjacency.get(node, []):
                candidate = current_min + minutes
                if candidate < dist_minutes.get(neighbor, float("inf")):
                    dist_minutes[neighbor] = candidate
                    dist_km[neighbor] = dist_km[node] + length
                    prev[neighbor] = (node, key)
                    heapq.heappush(heap, (candidate, neighbor))

        if end not in visited:
            return (float("inf"), float("inf"), [])

        path: list[str] = []
        cursor = end
        while cursor != start:
            parent, key = prev[cursor]
            path.append(key)
            cursor = parent
        path.reverse()

        total_minutes = dist_minutes[end] + access_start + access_end
        total_km = (
            dist_km[end]
            + _straight_km(origin, self.node_coords[start])
            + _straight_km(self.node_coords[end], destination)
        )
        return (total_minutes, total_km, path)


def _straight_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_km(a[0], a[1], b[0], b[1])


def active_closure_keys(session: Session) -> set[str]:
    """Return the set of segment keys currently marked as active closures."""
    rows = session.scalars(
        select(RoadClosure).where(RoadClosure.status == "active")
    ).all()
    return {str(row.segment_key) for row in rows}


def load_graph(
    session: Session,
    access_speed_kmh: float = 40.0,
    respect_closures: bool = True,
) -> RoadNetworkGraph:
    """Load the persisted road network into a routing graph."""
    segments = session.scalars(select(RoadSegment)).all()
    excluded = active_closure_keys(session) if respect_closures else set()
    return RoadNetworkGraph.from_segments(
        list(segments),
        access_speed_kmh=access_speed_kmh,
        excluded_segment_keys=excluded,
    )


def compute_crew_arrival(
    session: Session,
    origin: tuple[float, float],
    destination: tuple[float, float],
    access_speed_kmh: float = 40.0,
) -> RouteResult:
    """Compute a crew's estimated arrival time, re-routing around active closures."""
    graph = load_graph(
        session, access_speed_kmh=access_speed_kmh, respect_closures=True
    )
    open_graph = load_graph(
        session, access_speed_kmh=access_speed_kmh, respect_closures=False
    )

    closures = active_closure_keys(session)
    minutes, km, path = graph.shortest_route(origin, destination)
    if not math.isinf(minutes):
        open_minutes, _, open_path = open_graph.shortest_route(origin, destination)
        delay = minutes - open_minutes if not math.isinf(open_minutes) else 0.0
        # Closures that the unobstructed shortest route would have used are the
        # ones we had to actively avoid by re-routing.
        avoided = len(closures & set(open_path)) if closures else 0
        return RouteResult(
            origin=origin,
            destination=destination,
            reachable=True,
            eta_minutes=minutes,
            distance_km=km,
            path_segment_keys=path,
            closures_avoided=avoided,
            delay_vs_open_minutes=max(0.0, delay),
        )

    return RouteResult(
        origin=origin,
        destination=destination,
        reachable=False,
        eta_minutes=float("inf"),
        distance_km=float("inf"),
        path_segment_keys=[],
        closures_avoided=0,
        delay_vs_open_minutes=0.0,
    )


def compute_arrival_for_event(
    session: Session,
    destination: tuple[float, float],
    access_speed_kmh: float = 40.0,
) -> list[dict[str, Any]]:
    """Rank available crew bases by estimated arrival time at a fire location."""
    bases = session.scalars(select(CrewBase).where(CrewBase.available.is_(True))).all()
    results: list[dict[str, Any]] = []
    for base in bases:
        origin = (float(base.latitude), float(base.longitude))  # type: ignore[arg-type]
        route = compute_crew_arrival(session, origin, destination, access_speed_kmh)
        results.append(
            {
                "base_key": str(base.base_key),
                "name": str(base.name),
                "crew_type": str(base.crew_type),
                "reachable": route.reachable,
                "eta_minutes": round(route.eta_minutes, 2) if route.reachable else None,
                "distance_km": round(route.distance_km, 3) if route.reachable else None,
                "delay_vs_open_minutes": round(route.delay_vs_open_minutes, 2),
            }
        )
    results.sort(
        key=lambda item: (not item["reachable"], item["eta_minutes"] or float("inf"))
    )
    return results


def upsert_segments(session: Session, segments: list[NormalizedSegment]) -> int:
    """Insert or update normalised segments keyed by segment_key; return affected count."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    count = 0
    for seg in segments:
        existing = session.scalar(
            select(RoadSegment).where(RoadSegment.segment_key == seg.segment_key)
        )
        if existing:
            existing.from_lat = seg.from_lat  # type: ignore[assignment]
            existing.from_lon = seg.from_lon  # type: ignore[assignment]
            existing.to_lat = seg.to_lat  # type: ignore[assignment]
            existing.to_lon = seg.to_lon  # type: ignore[assignment]
            existing.highway = seg.highway  # type: ignore[assignment]
            existing.name = seg.name  # type: ignore[assignment]
            existing.length_km = seg.length_km  # type: ignore[assignment]
            existing.max_speed_kmh = seg.max_speed_kmh  # type: ignore[assignment]
            existing.one_way = seg.one_way  # type: ignore[assignment]
            existing.fetched_at = now  # type: ignore[assignment]
            count += 1
            continue
        session.add(
            RoadSegment(
                segment_key=seg.segment_key,
                osm_way_id=seg.osm_way_id,
                from_node_id=seg.from_node_id,
                to_node_id=seg.to_node_id,
                from_lat=seg.from_lat,
                from_lon=seg.from_lon,
                to_lat=seg.to_lat,
                to_lon=seg.to_lon,
                highway=seg.highway,
                name=seg.name,
                length_km=seg.length_km,
                max_speed_kmh=seg.max_speed_kmh,
                one_way=seg.one_way,
                fetched_at=now,
                source=seg.source,
            )
        )
        count += 1
    session.flush()
    return count


def sync_road_network(
    session: Session,
    settings: Any,
    bbox: BoundingBox,
    client: Optional[OverpassClient] = None,
) -> dict[str, int]:
    """Import the OpenStreetMap road network for a bbox and persist it."""
    if client is None:
        client = OverpassClient(
            base_url=getattr(
                settings, "OVERPASS_BASE_URL", "https://overpass-api.de/api/interpreter"
            )
        )
    segments = client.fetch_network(bbox)
    saved = upsert_segments(session, segments)
    return {"segments_fetched": len(segments), "segments_saved": saved}


def mark_road_closure(
    session: Session,
    segment_key: str,
    reason: str = "unspecified",
    reported_by: Optional[str] = None,
) -> RoadClosure:
    """Mark a road segment as closed so subsequent routes avoid it."""
    segment = session.scalar(
        select(RoadSegment).where(RoadSegment.segment_key == segment_key)
    )
    if not segment:
        raise RoadSegmentNotFoundError(f"Road segment {segment_key} not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    existing = session.scalar(
        select(RoadClosure).where(
            RoadClosure.segment_key == segment_key, RoadClosure.status == "active"
        )
    )
    if existing:
        existing.reason = reason  # type: ignore[assignment]
        existing.reported_by = reported_by  # type: ignore[assignment]
        existing.reported_at = now  # type: ignore[assignment]
        session.flush()
        return existing

    closure = RoadClosure(
        segment_key=segment_key,
        osm_way_id=segment.osm_way_id,
        reason=reason,
        status="active",
        reported_by=reported_by,
        reported_at=now,
    )
    session.add(closure)
    session.flush()
    return closure


def resolve_road_closure(session: Session, segment_key: str) -> int:
    """Resolve all active closures on a segment; return the number resolved."""
    rows = session.scalars(
        select(RoadClosure).where(
            RoadClosure.segment_key == segment_key, RoadClosure.status == "active"
        )
    ).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for closure in rows:
        closure.status = "resolved"  # type: ignore[assignment]
        closure.resolved_at = now  # type: ignore[assignment]
    session.flush()
    return len(rows)
