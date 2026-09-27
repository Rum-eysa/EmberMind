"""Threat/exposure analysis of settlements, roads and energy lines (EM-023).

As a commander I want to know *which* village, road and infrastructure lies in
the fire's path and *when* it will first be affected, so I can prioritise
protection and evacuation. This service intersects OpenStreetMap assets
(settlements and power lines imported here, roads read from the EM-011 road
network) with the EM-015 spread-forecast horizon polygons and reports, for
every element, the earliest forecast horizon whose polygon reaches it — the
first-impact time ``T+dk``. The affected elements are returned as a list
sorted by impact time (soonest first) and as a GeoJSON layer for the map.
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests  # type: ignore[import-untyped]
from shapely.geometry import LineString, mapping
from shapely.geometry.base import BaseGeometry
from shapely.wkt import loads as wkt_loads
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.exposure import ASSET_TYPES, SETTLEMENT_PLACE_CLASSES, ExposedAsset
from src.models.road_network import RoadSegment
from src.models.spatial import FireForecast
from src.utils.timeutils import utc_now

BoundingBox = tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)

EXPOSURE_ATTRIBUTION = (
    "Maruziyet: OSM yerleşim/enerji hatları + yayılım tahmin poligonları (EM-023)"
)
ASSET_ROW_LIMIT = 5000
POWER_LINE_TAGS = ("line", "cable", "minor_line")


class ExposureError(RuntimeError):
    """Raised when exposure assets cannot be fetched, parsed or analysed."""


@dataclass(frozen=True)
class NormalizedAsset:
    """A settlement or power line normalised from OpenStreetMap."""

    asset_key: str
    asset_type: str
    name: Optional[str]
    osm_id: int
    latitude: float
    longitude: float
    geometry_wkt: str
    tags: dict[str, Any] = field(default_factory=dict)
    source: str = "OpenStreetMap"


# ------------------------------------------------------- Overpass import ---


class ExposureOverpassClient:
    """Fetches settlements and energy lines for a bbox from OpenStreetMap."""

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
        """Overpass QL selecting place nodes and power-line ways inside a bbox."""
        min_lat, min_lon, max_lat, max_lon = bbox
        bbox_arg = f"{min_lat},{min_lon},{max_lat},{max_lon}"
        return (
            "[out:json][timeout:25];"
            f"('node[\"place\"]({bbox_arg});'"
            f'\'way["power"~"^(line|cable|minor_line)$"]({bbox_arg});\');'
            "out body;>;out skel qt;"
        )

    def fetch_assets(self, bbox: BoundingBox) -> list[NormalizedAsset]:
        """Fetch and parse settlements and power lines for a bbox with retries."""
        query = self.build_query(bbox)
        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self._http_get(self.base_url, {"data": query}, self.timeout)
                payload = response.json()
                return parse_asset_response(payload)
            except (requests.RequestException, ValueError, KeyError) as exc:
                last_exception = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_factor * (2**attempt))
        raise ExposureError(
            f"Overpass asset request failed after {self.max_retries} attempts: "
            f"{last_exception}"
        ) from last_exception


def _settlement_from_node(element: dict[str, Any]) -> Optional[NormalizedAsset]:
    """Build a settlement point asset from an Overpass node, if it is a place."""
    tags = element.get("tags", {}) or {}
    place = str(tags.get("place", "")).strip().lower()
    if not place:
        return None
    lat = float(element["lat"])  # type: ignore[arg-type]
    lon = float(element["lon"])  # type: ignore[arg-type]
    node_id = int(element["id"])  # type: ignore[arg-type]
    name = tags.get("name") or f"{place} yerleşimi"
    population = _int_or_none(tags.get("population"))
    asset_tags: dict[str, Any] = {"place": place}
    if population is not None:
        asset_tags["population"] = population
    return NormalizedAsset(
        asset_key=f"osm-node-{node_id}",
        asset_type="settlement",
        name=str(name),
        osm_id=node_id,
        latitude=lat,
        longitude=lon,
        geometry_wkt=f"POINT({lon:.6f} {lat:.6f})",
        tags=asset_tags,
    )


def _power_line_from_way(
    element: dict[str, Any], node_coords: dict[int, tuple[float, float]]
) -> Optional[NormalizedAsset]:
    """Build a power-line asset from an Overpass way using its node coordinates."""
    tags = element.get("tags", {}) or {}
    power = str(tags.get("power", "")).strip().lower()
    if power not in POWER_LINE_TAGS:
        return None
    coords = [
        node_coords[int(node_id)]
        for node_id in element.get("nodes", [])
        if int(node_id) in node_coords
    ]
    if len(coords) < 2:
        return None
    way_id = int(element["id"])  # type: ignore[arg-type]
    line = LineString([(lon, lat) for lat, lon in coords])
    mid_lat, mid_lon = (
        sum(p[0] for p in coords) / len(coords),
        sum(p[1] for p in coords) / len(coords),
    )
    asset_tags: dict[str, Any] = {"power": power}
    if tags.get("voltage"):
        asset_tags["voltage"] = str(tags["voltage"])
    return NormalizedAsset(
        asset_key=f"osm-way-{way_id}",
        asset_type="power_line",
        name=str(tags.get("name") or f"enerji hattı {way_id}"),
        osm_id=way_id,
        latitude=round(mid_lat, 6),
        longitude=round(mid_lon, 6),
        geometry_wkt=line.wkt,
        tags=asset_tags,
    )


def parse_asset_response(payload: dict[str, Any]) -> list[NormalizedAsset]:
    """Convert an Overpass JSON document into normalised settlement/power assets."""
    elements = payload.get("elements", [])
    node_coords: dict[int, tuple[float, float]] = {}
    for element in elements:
        if element.get("type") == "node":
            node_coords[int(element["id"])] = (
                float(element["lat"]),
                float(element["lon"]),
            )

    assets: list[NormalizedAsset] = []
    for element in elements:
        kind = element.get("type")
        if kind == "node":
            settlement = _settlement_from_node(element)
            if settlement is not None:
                assets.append(settlement)
        elif kind == "way":
            line = _power_line_from_way(element, node_coords)
            if line is not None:
                assets.append(line)
    return assets


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def upsert_assets(
    session: Session, assets: list[NormalizedAsset], source: str = "OpenStreetMap"
) -> int:
    """Insert or update normalised assets, returning the number written."""
    now = utc_now()
    count = 0
    for asset in assets:
        geom = _load_shape(asset.geometry_wkt)
        if geom is None:
            continue
        min_lon, min_lat, max_lon, max_lat = geom.bounds
        row: Any = session.scalar(
            select(ExposedAsset).where(ExposedAsset.asset_key == asset.asset_key)
        )
        if row is None:
            row = ExposedAsset(asset_key=asset.asset_key)
            session.add(row)
        row.asset_type = asset.asset_type
        row.name = asset.name
        row.osm_id = asset.osm_id
        row.latitude = asset.latitude
        row.longitude = asset.longitude
        row.min_lat = min_lat
        row.max_lat = max_lat
        row.min_lon = min_lon
        row.max_lon = max_lon
        row.geometry_wkt = asset.geometry_wkt
        row.tags_json = json.dumps(asset.tags, ensure_ascii=False)
        row.source = source
        row.fetched_at = now
        count += 1
    session.flush()
    return count


def sync_exposed_assets(
    session: Session,
    settings: Any,
    bbox: BoundingBox,
    client: Optional[ExposureOverpassClient] = None,
) -> dict[str, int]:
    """Import settlements and energy lines for a bbox from OpenStreetMap."""
    if client is None:
        client = ExposureOverpassClient(
            base_url=getattr(
                settings, "OVERPASS_BASE_URL", "https://overpass-api.de/api/interpreter"
            )
        )
    assets = client.fetch_assets(bbox)
    saved = upsert_assets(session, assets)
    return {"assets_fetched": len(assets), "assets_saved": saved}


# ------------------------------------------------------------- analysis ---


def _load_shape(wkt: str | None) -> Optional[BaseGeometry]:
    """Parse a WKT string into a shapely geometry, or ``None`` when unusable."""
    if not wkt:
        return None
    try:
        geom = wkt_loads(wkt)
    except Exception:  # noqa: BLE001 - malformed stored WKT must not break analysis
        return None
    if geom is None or geom.is_empty:
        return None
    return geom


def _forecast_polygons(
    session: Session, event_key: str | None
) -> dict[str, list[tuple[int, BaseGeometry]]]:
    """Group stored forecast polygons by event, ordered by ascending horizon."""
    query = select(FireForecast).order_by(FireForecast.id.desc()).limit(ASSET_ROW_LIMIT)
    if event_key:
        query = query.where(FireForecast.event_key == event_key)
    latest: dict[tuple[str, int], FireForecast] = {}
    for row in session.scalars(query):
        key = (str(row.event_key), int(row.horizon_minutes))
        if key not in latest:
            latest[key] = row
    grouped: dict[str, list[tuple[int, BaseGeometry]]] = {}
    for (event, horizon), row in latest.items():
        shape = _load_shape(str(row.geometry_wkt))
        if shape is None:
            continue
        grouped.setdefault(event, []).append((horizon, shape))
    for horizons in grouped.values():
        horizons.sort(key=lambda item: item[0])
    return grouped


def _candidate_elements(session: Session) -> list[dict[str, Any]]:
    """Collect settlements, power lines and roads as analysis candidates."""
    candidates: list[dict[str, Any]] = []
    for row in session.scalars(
        select(ExposedAsset).order_by(ExposedAsset.id).limit(ASSET_ROW_LIMIT)
    ):
        if row.asset_type not in ASSET_TYPES:
            continue
        try:
            tags = json.loads(str(row.tags_json or "{}"))
        except ValueError:
            tags = {}
        candidates.append(
            {
                "asset_key": str(row.asset_key),
                "asset_type": str(row.asset_type),
                "name": str(row.name) if row.name else None,
                "latitude": float(row.latitude),
                "longitude": float(row.longitude),
                "geometry_wkt": str(row.geometry_wkt),
                "population": tags.get("population")
                if isinstance(tags, dict)
                else None,
            }
        )
    for row in session.scalars(
        select(RoadSegment).order_by(RoadSegment.id).limit(ASSET_ROW_LIMIT)
    ):
        line = LineString(
            [
                (float(row.from_lon), float(row.from_lat)),
                (float(row.to_lon), float(row.to_lat)),
            ]
        )
        candidates.append(
            {
                "asset_key": f"road-{row.segment_key}",
                "asset_type": "road",
                "name": str(row.name) if row.name else str(row.highway),
                "latitude": (float(row.from_lat) + float(row.to_lat)) / 2.0,
                "longitude": (float(row.from_lon) + float(row.to_lon)) / 2.0,
                "geometry_wkt": line.wkt,
                "population": None,
            }
        )
    return candidates


def _first_impact(
    shape: BaseGeometry, grouped: dict[str, list[tuple[int, BaseGeometry]]]
) -> Optional[tuple[str, int]]:
    """Earliest (event_key, horizon) whose forecast polygon reaches a geometry."""
    best: Optional[tuple[str, int]] = None
    for event_key, horizons in grouped.items():
        for horizon, polygon in horizons:
            if best is not None and horizon >= best[1]:
                break  # this event cannot beat the current earliest impact
            try:
                hit = polygon.intersects(shape) or polygon.contains(shape)
            except Exception:  # noqa: BLE001 - ignore a single bad geometry
                continue
            if hit:
                if best is None or horizon < best[1]:
                    best = (event_key, horizon)
                break
    return best


def analyze_exposure(
    session: Session, settings: Any, event_key: str | None = None
) -> list[dict[str, Any]]:
    """Return threatened assets sorted by first-impact time (soonest first)."""
    grouped = _forecast_polygons(session, event_key)
    if not grouped:
        return []
    threatened: list[dict[str, Any]] = []
    for candidate in _candidate_elements(session):
        shape = _load_shape(candidate["geometry_wkt"])
        if shape is None:
            continue
        impact = _first_impact(shape, grouped)
        if impact is None:
            continue
        matched_event, horizon = impact
        threatened.append(
            {
                "asset_key": candidate["asset_key"],
                "asset_type": candidate["asset_type"],
                "name": candidate["name"],
                "latitude": candidate["latitude"],
                "longitude": candidate["longitude"],
                "population": candidate["population"],
                "event_key": matched_event,
                "first_impact_minutes": horizon,
                "geometry": mapping(shape),
            }
        )
    threatened.sort(
        key=lambda item: (
            item["first_impact_minutes"],
            item["asset_type"],
            item["name"] or "",
        )
    )
    return threatened


def exposure_summary(
    session: Session, settings: Any, event_key: str | None = None
) -> dict[str, Any]:
    """Commander-facing sorted exposure list with per-type and earliest stats."""
    threatened = analyze_exposure(session, settings, event_key)
    by_type: dict[str, int] = {}
    for item in threatened:
        by_type[item["asset_type"]] = by_type.get(item["asset_type"], 0) + 1
    horizons = [item["first_impact_minutes"] for item in threatened]
    items = [{k: v for k, v in item.items() if k != "geometry"} for item in threatened]
    return {
        "type": "exposure",
        "attribution": EXPOSURE_ATTRIBUTION,
        "event_key": event_key,
        "count": len(threatened),
        "earliest_impact_minutes": min(horizons) if horizons else None,
        "by_type": by_type,
        "items": items,
    }


def exposure_layer(
    session: Session, settings: Any, event_key: str | None = None
) -> dict[str, Any]:
    """GeoJSON FeatureCollection of threatened assets for the operator map."""
    threatened = analyze_exposure(session, settings, event_key)
    features: list[dict[str, Any]] = []
    for item in threatened:
        properties = {k: v for k, v in item.items() if k != "geometry"}
        features.append(
            {"type": "Feature", "geometry": item["geometry"], "properties": properties}
        )
    return {
        "type": "FeatureCollection",
        "layer": "exposure",
        "title": "Tehdit Altındaki Yapılar",
        "count": len(features),
        "attribution": EXPOSURE_ATTRIBUTION,
        "features": features,
    }


def settlement_place_classes() -> tuple[str, ...]:
    """Expose the recognised OSM place classes (used by importer docs/tests)."""
    return SETTLEMENT_PLACE_CLASSES
