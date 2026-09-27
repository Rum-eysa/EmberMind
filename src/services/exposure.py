"""Threat/exposure analysis of settlements, roads and energy lines (EM-023).

As a commander I want to know *which* village, road and infrastructure lies in
the fire's path and *when* it will first be affected, so I can prioritise
protection and evacuation. This service intersects OpenStreetMap assets
(settlements and power lines imported here, roads read from the EM-011 road
network) with the EM-015 spread-forecast horizon polygons. For every element it
reports the earliest forecast horizon whose polygon reaches it and, using the
stored head spread rate and the distance from the ignition point, an
**interpolated** first-impact time ``T+dk`` (not just the 30/60/120 bucket).
Each element also gets a **priority score** combining impact time, asset
criticality and population, so the returned list is sorted by protection /
evacuation urgency (most urgent first). A candidate bbox pre-filter, shapely
prepared geometries and a short fingerprint-keyed TTL cache keep the analysis
responsive, and the whole set is exposed as a GeoJSON layer for the map.
"""
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests  # type: ignore[import-untyped]
from shapely.geometry import LineString, Point, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.prepared import prep
from shapely.wkt import loads as wkt_loads
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.exposure import ASSET_TYPES, SETTLEMENT_PLACE_CLASSES, ExposedAsset
from src.models.road_network import RoadSegment
from src.models.spatial import FireForecast
from src.utils.timeutils import utc_now

_LOG = logging.getLogger(__name__)

BoundingBox = tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)

EXPOSURE_ATTRIBUTION = (
    "Maruziyet: OSM yerleşim/enerji hatları + yayılım tahmin poligonları (EM-023)"
)
ASSET_ROW_LIMIT = 5000
POWER_LINE_TAGS = ("line", "cable", "minor_line")
_EARTH_RADIUS_M = 6371000.0
_DEFAULT_MAX_HORIZON = 120
# Relative criticality of an asset type for the protection/evacuation score.
CRITICALITY_WEIGHTS = {"settlement": 0.6, "power_line": 0.8, "road": 0.4}
# Weighting of the priority-score components (they sum to 1.0).
_TIME_WEIGHT = 0.5
_CRITICALITY_WEIGHT = 0.3
_POPULATION_WEIGHT = 0.2
# Fingerprint-keyed TTL cache of analysed threat lists (bounded to avoid growth).
_ANALYSIS_CACHE: dict[
    tuple[Optional[str], str], tuple[float, list[dict[str, Any]]]
] = {}
_ANALYSIS_CACHE_MAX_ENTRIES = 64


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
    asset_tags: dict[str, Any] = {"place": place, "named": bool(tags.get("name"))}
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
    # A way whose member nodes were not all returned by Overpass is truncated;
    # flag it so the commander can tell a partial line from a complete one.
    partial = len(coords) < len(element.get("nodes", []))
    way_id = int(element["id"])  # type: ignore[arg-type]
    line = LineString([(lon, lat) for lat, lon in coords])
    mid_lat, mid_lon = (
        sum(p[0] for p in coords) / len(coords),
        sum(p[1] for p in coords) / len(coords),
    )
    asset_tags: dict[str, Any] = {"power": power}
    if tags.get("voltage"):
        asset_tags["voltage"] = str(tags["voltage"])
    if partial:
        asset_tags["partial"] = True
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


def bbox_area_deg2(bbox: BoundingBox) -> float:
    """Return the area of a ``(min_lat, min_lon, max_lat, max_lon)`` bbox in deg^2."""
    min_lat, min_lon, max_lat, max_lon = bbox
    return max(0.0, max_lat - min_lat) * max(0.0, max_lon - min_lon)


def filter_assets(
    assets: list[NormalizedAsset],
    priority_classes: Optional[list[str]] = None,
    max_assets: Optional[int] = None,
) -> list[NormalizedAsset]:
    """Drop low-value settlements and cap the total so a huge bbox cannot flood.

    When ``priority_classes`` is configured, an unnamed settlement is kept only if
    its place class is listed (named settlements always survive). An empty
    ``priority_classes`` keeps every settlement (used by offline tests).
    """
    classes = {c.strip().lower() for c in (priority_classes or []) if c.strip()}
    kept: list[NormalizedAsset] = []
    for asset in assets:
        if asset.asset_type == "settlement" and classes:
            named = bool(asset.tags.get("named"))
            place = str(asset.tags.get("place", "")).strip().lower()
            if not named and place not in classes:
                continue
        kept.append(asset)
    if max_assets is not None and len(kept) > max_assets:
        return kept[:max_assets]
    return kept


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
    raw = client.fetch_assets(bbox)
    kept = filter_assets(
        raw,
        priority_classes=getattr(
            settings, "EXPOSURE_IMPORT_PRIORITY_PLACE_CLASSES", None
        ),
        max_assets=int(getattr(settings, "EXPOSURE_IMPORT_MAX_ASSETS", 2000)),
    )
    saved = upsert_assets(session, kept)
    return {
        "assets_fetched": len(raw),
        "assets_kept": len(kept),
        "assets_skipped": len(raw) - len(kept),
        "assets_saved": saved,
    }


# ------------------------------------------------------------- analysis ---


def _load_shape(wkt: str | None) -> Optional[BaseGeometry]:
    """Parse a WKT string into a shapely geometry, or ``None`` when unusable."""
    if not wkt:
        return None
    try:
        geom = wkt_loads(wkt)
    except Exception:  # noqa: BLE001 - malformed stored WKT must not break analysis
        _LOG.warning("exposure: skipping malformed stored WKT geometry")
        return None
    if geom is None or geom.is_empty:
        return None
    return geom


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _nearest_front_distance(
    ign_lat: float, ign_lon: float, shape: BaseGeometry
) -> float:
    """Ground distance (m) from the ignition point to the nearest point on a shape."""
    try:
        _ign, near = nearest_points(Point(ign_lon, ign_lat), shape)
        return _haversine_m(ign_lat, ign_lon, near.y, near.x)
    except Exception:  # noqa: BLE001 - degenerate geometry, fall back to a sample point
        sample = shape.representative_point()
        return _haversine_m(ign_lat, ign_lon, sample.y, sample.x)


@dataclass(frozen=True)
class _HorizonPolygon:
    """A forecast horizon polygon plus the spread attributes used to interpolate."""

    horizon: int
    shape: BaseGeometry
    prepared: Any
    rate_m_min: float
    ign_lat: float
    ign_lon: float


def _latest_forecast_rows(
    session: Session, event_key: str | None
) -> dict[tuple[str, int], FireForecast]:
    """Return the newest stored forecast row per (event, horizon)."""
    query = select(FireForecast).order_by(FireForecast.id.desc()).limit(ASSET_ROW_LIMIT)
    if event_key:
        query = query.where(FireForecast.event_key == event_key)
    latest: dict[tuple[str, int], FireForecast] = {}
    for row in session.scalars(query):
        key = (str(row.event_key), int(row.horizon_minutes))
        if key not in latest:
            latest[key] = row
    return latest


def _polygons_from_rows(
    rows: dict[tuple[str, int], FireForecast],
) -> dict[str, list[_HorizonPolygon]]:
    """Build per-event prepared horizon polygons from loaded forecast rows."""
    grouped: dict[str, list[_HorizonPolygon]] = {}
    for (event, horizon), row in rows.items():
        shape = _load_shape(str(row.geometry_wkt))
        if shape is None:
            continue
        try:
            prepared: Any = prep(shape)
        except Exception:  # noqa: BLE001 - invalid geometry, use the plain object
            _LOG.debug(
                "exposure: cannot prepare polygon for event %s h=%s", event, horizon
            )
            prepared = None
        grouped.setdefault(event, []).append(
            _HorizonPolygon(
                horizon=horizon,
                shape=shape,
                prepared=prepared,
                rate_m_min=float(row.rate_of_spread_m_per_min or 0.0),
                ign_lat=float(row.latitude),
                ign_lon=float(row.longitude),
            )
        )
    for polys in grouped.values():
        polys.sort(key=lambda item: item.horizon)
    return grouped


def _forecast_polygons(
    session: Session, event_key: str | None
) -> dict[str, list[_HorizonPolygon]]:
    """Group stored forecast polygons by event, ordered by ascending horizon."""
    return _polygons_from_rows(_latest_forecast_rows(session, event_key))


def _grouped_bbox(grouped: dict[str, list[_HorizonPolygon]]) -> Optional[BoundingBox]:
    """Union bounding box ``(min_lat, min_lon, max_lat, max_lon)`` of all polygons."""
    min_lat = min_lon = math.inf
    max_lat = max_lon = -math.inf
    seen = False
    for polys in grouped.values():
        for poly in polys:
            lo_x, lo_y, hi_x, hi_y = poly.shape.bounds
            min_lon = min(min_lon, lo_x)
            max_lon = max(max_lon, hi_x)
            min_lat = min(min_lat, lo_y)
            max_lat = max(max_lat, hi_y)
            seen = True
    if not seen:
        return None
    return (min_lat, min_lon, max_lat, max_lon)


def _overlaps(
    bbox: BoundingBox, lo_lat: float, lo_lon: float, hi_lat: float, hi_lon: float
) -> bool:
    """Whether an element bounding box overlaps the forecast bounding box."""
    min_lat, min_lon, max_lat, max_lon = bbox
    return not (
        hi_lat < min_lat or lo_lat > max_lat or hi_lon < min_lon or lo_lon > max_lon
    )


def _candidate_elements(
    session: Session, bbox: Optional[BoundingBox] = None
) -> list[dict[str, Any]]:
    """Collect settlements, power lines and roads, optionally bbox pre-filtered."""
    candidates: list[dict[str, Any]] = []
    asset_query = select(ExposedAsset).order_by(ExposedAsset.id).limit(ASSET_ROW_LIMIT)
    if bbox is not None:
        min_lat, min_lon, max_lat, max_lon = bbox
        # Stored bounds let the DB skip elements far from any forecast polygon.
        asset_query = asset_query.where(
            ExposedAsset.max_lat >= min_lat,
            ExposedAsset.min_lat <= max_lat,
            ExposedAsset.max_lon >= min_lon,
            ExposedAsset.min_lon <= max_lon,
        )
    for row in session.scalars(asset_query):
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
                "source": str(row.source) if row.source else "OpenStreetMap",
            }
        )
    for row in session.scalars(
        select(RoadSegment).order_by(RoadSegment.id).limit(ASSET_ROW_LIMIT)
    ):
        from_lat = float(row.from_lat)
        from_lon = float(row.from_lon)
        to_lat = float(row.to_lat)
        to_lon = float(row.to_lon)
        # A straight segment crosses the forecast bbox iff its endpoint bbox does.
        if bbox is not None and not _overlaps(
            bbox,
            min(from_lat, to_lat),
            min(from_lon, to_lon),
            max(from_lat, to_lat),
            max(from_lon, to_lon),
        ):
            continue
        line = LineString([(from_lon, from_lat), (to_lon, to_lat)])
        candidates.append(
            {
                "asset_key": f"road-{row.segment_key}",
                "asset_type": "road",
                "name": str(row.name) if row.name else str(row.highway),
                "latitude": (from_lat + to_lat) / 2.0,
                "longitude": (from_lon + to_lon) / 2.0,
                "geometry_wkt": line.wkt,
                "population": None,
                "source": "OpenStreetMap (EM-011)",
            }
        )
    return candidates


def _interpolate_impact(
    prev_head_m: float,
    prev_h: int,
    cur_head_m: float,
    cur_h: int,
    dist_m: float,
) -> int:
    """Interpolate the arrival minute between two horizons from front distances.

    The element is outside the previous polygon and inside the current one; we
    place the arrival linearly by how far the head front has travelled toward it
    (clamped to the ``(prev_h, cur_h]`` bracket). Falls back to ``cur_h`` when the
    spread rate is missing or non-positive.
    """
    if cur_h <= prev_h or cur_head_m <= prev_head_m or cur_head_m <= 0:
        return int(cur_h)
    frac = (dist_m - prev_head_m) / (cur_head_m - prev_head_m)
    frac = max(0.0, min(1.0, frac))
    return int(round(prev_h + frac * (cur_h - prev_h)))


def _first_impact(
    shape: BaseGeometry, grouped: dict[str, list[_HorizonPolygon]]
) -> Optional[dict[str, Any]]:
    """Earliest interpolated impact for a geometry across all events."""
    best: Optional[dict[str, Any]] = None
    for event_key, polys in grouped.items():
        for idx, poly in enumerate(polys):
            try:
                hit = (
                    poly.prepared.intersects(shape)
                    if poly.prepared is not None
                    else poly.shape.intersects(shape)
                )
            except Exception:  # noqa: BLE001 - ignore a single bad geometry
                _LOG.debug(
                    "exposure: intersect failed for event %s horizon %s",
                    event_key,
                    poly.horizon,
                )
                continue
            if hit:
                prev = polys[idx - 1] if idx > 0 else None
                prev_h = prev.horizon if prev is not None else 0
                prev_head = (prev.rate_m_min * prev_h) if prev is not None else 0.0
                cur_head = poly.rate_m_min * poly.horizon
                dist = _nearest_front_distance(poly.ign_lat, poly.ign_lon, shape)
                est = _interpolate_impact(
                    prev_head, prev_h, cur_head, poly.horizon, dist
                )
                if best is None or est < best["est"]:
                    best = {
                        "est": est,
                        "horizon": poly.horizon,
                        "event_key": event_key,
                    }
                break  # earliest containing horizon for this event
    return best


def _priority_score(
    item: dict[str, Any], max_horizon: int, population_reference: float
) -> float:
    """Blend impact time, asset criticality and population into a 0-100 score."""
    est = float(item["first_impact_minutes"])
    time_score = (
        1.0 if max_horizon <= 0 else 1.0 - max(0.0, min(1.0, est / float(max_horizon)))
    )
    criticality = CRITICALITY_WEIGHTS.get(item["asset_type"], 0.5)
    raw_pop = item.get("population")
    pop_val = raw_pop if isinstance(raw_pop, (int, float)) else _int_or_none(raw_pop)
    pop_norm = 0.0
    if pop_val and pop_val > 0 and population_reference > 0:
        pop_norm = min(
            1.0, math.log10(pop_val + 1) / math.log10(population_reference + 1)
        )
    score = 100.0 * (
        _TIME_WEIGHT * time_score
        + _CRITICALITY_WEIGHT * criticality
        + _POPULATION_WEIGHT * pop_norm
    )
    return round(score, 1)


def _table_signature(session: Session, model: Any) -> str:
    """Cheap ``(count, max_id)`` fingerprint of a table for cache invalidation."""
    count, max_id = session.execute(
        select(func.count(model.id), func.max(model.id))
    ).one()
    return f"{int(count or 0)}:{int(max_id or 0)}"


def _analysis_fingerprint(
    session: Session, rows: dict[tuple[str, int], FireForecast]
) -> str:
    """Content hash of the forecasts plus the (asset, road) table fingerprints."""
    parts = [
        f"{event}|{horizon}|{row.rate_of_spread_m_per_min}|{row.geometry_wkt}"
        for (event, horizon), row in sorted(rows.items())
    ]
    blob = "#".join(
        [
            hashlib.blake2s("|".join(parts).encode("utf-8")).hexdigest(),
            _table_signature(session, ExposedAsset),
            _table_signature(session, RoadSegment),
        ]
    )
    return hashlib.blake2s(blob.encode("utf-8")).hexdigest()


def _cache_get(
    key: tuple[Optional[str], str], ttl: float
) -> Optional[list[dict[str, Any]]]:
    hit = _ANALYSIS_CACHE.get(key)
    if hit is not None and hit[0] > time.time():
        return list(hit[1])
    return None


def _cache_set(
    key: tuple[Optional[str], str], value: list[dict[str, Any]], ttl: float
) -> None:
    if len(_ANALYSIS_CACHE) >= _ANALYSIS_CACHE_MAX_ENTRIES:
        _ANALYSIS_CACHE.clear()
    _ANALYSIS_CACHE[key] = (time.time() + ttl, value)


def analyze_exposure(
    session: Session, settings: Any, event_key: str | None = None
) -> list[dict[str, Any]]:
    """Return threatened assets sorted by protection/evacuation priority."""
    rows = _latest_forecast_rows(session, event_key)
    if not rows:
        return []
    cache_enabled = bool(getattr(settings, "EXPOSURE_CACHE_ENABLED", True))
    ttl = (
        float(getattr(settings, "EXPOSURE_CACHE_TTL_SECONDS", 60))
        if cache_enabled
        else 0.0
    )
    cache_key: Optional[tuple[Optional[str], str]] = None
    if ttl > 0:
        cache_key = (event_key, _analysis_fingerprint(session, rows))
        cached = _cache_get(cache_key, ttl)
        if cached is not None:
            return cached
    grouped = _polygons_from_rows(rows)
    if not grouped:
        result: list[dict[str, Any]] = []
    else:
        bbox = _grouped_bbox(grouped)
        max_horizon = max(
            (poly.horizon for polys in grouped.values() for poly in polys),
            default=_DEFAULT_MAX_HORIZON,
        )
        pop_ref = float(getattr(settings, "EXPOSURE_POPULATION_REFERENCE", 100000))
        threatened: list[dict[str, Any]] = []
        for candidate in _candidate_elements(session, bbox):
            shape = _load_shape(candidate["geometry_wkt"])
            if shape is None:
                continue
            impact = _first_impact(shape, grouped)
            if impact is None:
                continue
            item: dict[str, Any] = {
                "asset_key": candidate["asset_key"],
                "asset_type": candidate["asset_type"],
                "name": candidate["name"],
                "latitude": candidate["latitude"],
                "longitude": candidate["longitude"],
                "population": candidate["population"],
                "source": candidate["source"],
                "event_key": impact["event_key"],
                "first_impact_minutes": impact["est"],
                "impact_horizon_minutes": impact["horizon"],
                "geometry": mapping(shape),
            }
            item["priority_score"] = _priority_score(item, max_horizon, pop_ref)
            threatened.append(item)
        threatened.sort(
            key=lambda item: (
                -item["priority_score"],
                item["first_impact_minutes"],
                item["asset_type"],
                item["name"] or "",
            )
        )
        result = threatened
    if cache_key is not None:
        _cache_set(cache_key, result, ttl)
    return list(result)


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
