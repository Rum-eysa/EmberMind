"""EFFIS historical fire perimeter import, dataset splitting and calibration export.

EFFIS (European Forest Fire Information System) publishes past fire perimeters
through an ArcGIS REST service. This module fetches and normalises those
perimeters into a dedicated store (``historical_fire_perimeters``) and provides
deterministic train/test/validation splitting so the spread model can be
calibrated and validated against at least ``MIN_TRAINING_EVENTS`` past events.
"""
from dataclasses import dataclass
from datetime import datetime
import json
import math
import time
from typing import Any, Callable, Optional, cast
from urllib.parse import urlencode

import requests  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.historical_fire import HistoricalFirePerimeter
from src.utils.timeutils import utc_now

BoundingBox = tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)

DEFAULT_EFFIS_BASE_URL = (
    "https://effis.jrc.ec.europa.eu/geoportal/arcgis/rest/services/"
    "effis_perimeters/MapServer/0"
)
DEFAULT_EFFIS_YEARS = [2007, 2008, 2012, 2017, 2021]
MIN_TRAINING_EVENTS = 20
KM_PER_DEG_LAT = 111.320
_BACKOFF_FACTOR = 0.5


class EffisSourceError(RuntimeError):
    """Raised when EFFIS cannot be reached or returns invalid perimeter data."""


@dataclass(frozen=True)
class NormalizedPerimeter:
    """A single historical fire perimeter normalised from EFFIS."""

    perimeter_key: str
    effis_objectid: int
    fire_year: int
    country_code: Optional[str]
    country: Optional[str]
    national_code: Optional[str]
    date_start: Optional[datetime]
    date_end: Optional[datetime]
    area_km2: float
    mmi_level: str
    latitude: float
    longitude: float
    geometry: dict[str, Any]
    source: str = "EFFIS"


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any) -> Optional[datetime]:
    """Parse an EFFIS date string (ISO or DD/MM/YYYY) into a naive UTC datetime."""
    text = _as_str(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _ring_area_km2(ring: list[list[float]], ref_lat: float) -> float:
    km_per_lon = KM_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    points = [(lon * km_per_lon, lat * KM_PER_DEG_LAT) for lon, lat in ring]
    total = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _polygon_metrics(rings: list[Any]) -> Optional[tuple[float, float, float]]:
    """Return (centroid_lon, centroid_lat, area_km2) for the largest valid ring."""
    best_ring: Optional[list[list[float]]] = None
    best_area = -1.0
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 3:
            continue
        ref_lat = sum(float(point[1]) for point in ring) / len(ring)
        area = _ring_area_km2(ring, ref_lat)
        if area > best_area:
            best_area = area
            best_ring = ring
    if best_ring is None:
        return None
    centroid_lon = sum(float(point[0]) for point in best_ring) / len(best_ring)
    centroid_lat = sum(float(point[1]) for point in best_ring) / len(best_ring)
    return round(centroid_lon, 6), round(centroid_lat, 6), round(best_area, 4)


def _to_geojson(rings: list[Any]) -> dict[str, Any]:
    """Convert ArcGIS polygon rings into a GeoJSON Polygon (EPSG:4326)."""
    coordinates = [
        [[round(float(pt[0]), 6), round(float(pt[1]), 6)] for pt in ring]
        for ring in rings
        if isinstance(ring, list) and len(ring) >= 3
    ]
    return {"type": "Polygon", "coordinates": coordinates}


def parse_effis_response(
    payload: dict[str, Any], default_year: int
) -> list[NormalizedPerimeter]:
    """Convert an EFFIS ArcGIS JSON document into normalised perimeters."""
    features = payload.get("features", []) or []
    perimeters: list[NormalizedPerimeter] = []
    for index, feature in enumerate(features):
        attributes = feature.get("attributes", {}) or {}
        geometry = feature.get("geometry") or {}
        rings = geometry.get("rings") or []
        metrics = _polygon_metrics(rings)
        if metrics is None:
            continue
        lon, lat, area = metrics
        objectid = _coerce_int(attributes.get("OBJECTID", feature.get("fid")))
        if objectid is None:
            objectid = index
        year = _coerce_int(attributes.get("FIRE_YEAR")) or default_year
        perimeters.append(
            NormalizedPerimeter(
                perimeter_key=f"effis_{year}_{objectid}",
                effis_objectid=objectid,
                fire_year=year,
                country_code=_as_str(
                    attributes.get("ISO_CODE") or attributes.get("COUNTRY_CODE")
                ),
                country=_as_str(attributes.get("COUNTRY")),
                national_code=_as_str(attributes.get("NATIONAL_CODE")),
                date_start=_parse_date(attributes.get("DATE_START")),
                date_end=_parse_date(attributes.get("DATE_END")),
                area_km2=area,
                mmi_level=_as_str(attributes.get("MMI_LEVEL")) or "unknown",
                latitude=lat,
                longitude=lon,
                geometry=_to_geojson(rings),
            )
        )
    return perimeters


class EffisClient:
    """Client for the EFFIS historical fire perimeter ArcGIS REST service."""

    def __init__(
        self,
        base_url: str = DEFAULT_EFFIS_BASE_URL,
        years: Optional[list[int]] = None,
        timeout: int = 30,
        max_retries: int = 3,
        http_get: Optional[Callable[[str, int], Any]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.years = list(years) if years else list(DEFAULT_EFFIS_YEARS)
        self.timeout = timeout
        self.max_retries = max_retries
        self._http_get = http_get or self._default_http_get

    @staticmethod
    def _default_http_get(url: str, timeout: int) -> Any:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response

    def build_query_url(self, bbox: BoundingBox, year: int) -> str:
        """Build an ArcGIS REST query URL for one fire year inside a bbox."""
        min_lat, min_lon, max_lat, max_lon = bbox
        params = {
            "where": f"FIRE_YEAR={year}",
            "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "f": "json",
            "returnGeometry": "true",
            "outFields": "*",
        }
        return f"{self.base_url}/query?{urlencode(params)}"

    def _fetch_json(self, url: str) -> dict[str, Any]:
        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self._http_get(url, self.timeout)
                return cast(dict[str, Any], response.json())
            except (requests.RequestException, ValueError, KeyError) as exc:
                last_exception = exc
                if attempt < self.max_retries - 1:
                    time.sleep(_BACKOFF_FACTOR * (2**attempt))
        raise EffisSourceError(
            f"EFFIS request failed after {self.max_retries} attempts: {last_exception}"
        ) from last_exception

    def fetch_perimeters(self, bbox: BoundingBox) -> list[NormalizedPerimeter]:
        """Fetch and parse historical perimeters for every configured year."""
        perimeters: list[NormalizedPerimeter] = []
        for year in self.years:
            payload = self._fetch_json(self.build_query_url(bbox, year))
            perimeters.extend(parse_effis_response(payload, year))
        return perimeters


def upsert_perimeters(session: Session, perimeters: list[NormalizedPerimeter]) -> int:
    """Insert or update normalised perimeters keyed by perimeter_key."""
    now = utc_now()
    count = 0
    for item in perimeters:
        existing = session.scalar(
            select(HistoricalFirePerimeter).where(
                HistoricalFirePerimeter.perimeter_key == item.perimeter_key
            )
        )
        geometry_json = json.dumps(item.geometry)
        if existing:
            existing.effis_objectid = item.effis_objectid  # type: ignore[assignment]
            existing.fire_year = item.fire_year  # type: ignore[assignment]
            existing.country_code = item.country_code  # type: ignore[assignment]
            existing.country = item.country  # type: ignore[assignment]
            existing.national_code = item.national_code  # type: ignore[assignment]
            existing.date_start = item.date_start  # type: ignore[assignment]
            existing.date_end = item.date_end  # type: ignore[assignment]
            existing.area_km2 = item.area_km2  # type: ignore[assignment]
            existing.mmi_level = item.mmi_level  # type: ignore[assignment]
            existing.latitude = item.latitude  # type: ignore[assignment]
            existing.longitude = item.longitude  # type: ignore[assignment]
            existing.geometry_json = geometry_json  # type: ignore[assignment]
            existing.fetched_at = now  # type: ignore[assignment]
            count += 1
            continue
        session.add(
            HistoricalFirePerimeter(
                perimeter_key=item.perimeter_key,
                effis_objectid=item.effis_objectid,
                fire_year=item.fire_year,
                country_code=item.country_code,
                country=item.country,
                national_code=item.national_code,
                date_start=item.date_start,
                date_end=item.date_end,
                area_km2=item.area_km2,
                mmi_level=item.mmi_level,
                latitude=item.latitude,
                longitude=item.longitude,
                geometry_json=geometry_json,
                source=item.source,
                fetched_at=now,
            )
        )
        count += 1
    session.flush()
    return count


def import_effis_perimeters(
    session: Session,
    settings: Any,
    bbox: BoundingBox,
    client: Optional[EffisClient] = None,
) -> dict[str, int]:
    """Import EFFIS historical perimeters for a bbox and persist them."""
    if client is None:
        client = EffisClient(
            base_url=getattr(settings, "EFFIS_BASE_URL", DEFAULT_EFFIS_BASE_URL),
            years=getattr(settings, "EFFIS_HISTORICAL_YEARS", DEFAULT_EFFIS_YEARS),
        )
    perimeters = client.fetch_perimeters(bbox)
    saved = upsert_perimeters(session, perimeters)
    return {"perimeters_fetched": len(perimeters), "perimeters_saved": saved}


def assign_dataset_splits(
    session: Session,
    test_fraction: float = 0.2,
    validation_fraction: float = 0.2,
) -> dict[str, Any]:
    """Deterministically assign train/test/validation splits to stored perimeters."""
    if not 0 <= test_fraction <= 1 or not 0 <= validation_fraction <= 1:
        raise ValueError("split fractions must be between 0 and 1")
    if test_fraction + validation_fraction >= 1:
        raise ValueError("test_fraction + validation_fraction must be < 1")

    rows = session.scalars(
        select(HistoricalFirePerimeter).order_by(HistoricalFirePerimeter.perimeter_key)
    ).all()
    total = len(rows)
    test_count = int(total * test_fraction)
    validation_count = int(total * validation_fraction)
    counts = {"train": 0, "validation": 0, "test": 0}
    for index, row in enumerate(rows):
        if index < test_count:
            split = "test"
        elif index < test_count + validation_count:
            split = "validation"
        else:
            split = "train"
        row.split = split  # type: ignore[assignment]
        counts[split] += 1
    session.flush()
    counts["total"] = total
    counts["ready_for_training"] = total >= MIN_TRAINING_EVENTS
    return counts


def _feature_from_row(
    row: HistoricalFirePerimeter, include_geometry: bool
) -> dict[str, Any]:
    geometry = json.loads(str(row.geometry_json or "{}")) if include_geometry else None
    return {
        "perimeter_key": str(row.perimeter_key),
        "fire_year": int(row.fire_year),  # type: ignore[arg-type]
        "country_code": _as_str(row.country_code),
        "area_km2": float(row.area_km2),  # type: ignore[arg-type]
        "mmi_level": _as_str(row.mmi_level),
        "latitude": float(row.latitude),  # type: ignore[arg-type]
        "longitude": float(row.longitude),  # type: ignore[arg-type]
        "split": _as_str(row.split),
        "geometry": geometry,
    }


def build_calibration_dataset(
    session: Session, include_geometry: bool = True
) -> dict[str, Any]:
    """Return train/test/validation feature sets ready for model calibration."""
    rows = session.scalars(
        select(HistoricalFirePerimeter).order_by(HistoricalFirePerimeter.fire_year)
    ).all()
    buckets: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "test": [],
        "validation": [],
        "unassigned": [],
    }
    for row in rows:
        split = _as_str(row.split)
        bucket = split if split in ("train", "test", "validation") else "unassigned"
        buckets[bucket].append(_feature_from_row(row, include_geometry))
    total = len(rows)
    return {
        "total": total,
        "min_required": MIN_TRAINING_EVENTS,
        "ready_for_training": total >= MIN_TRAINING_EVENTS,
        "counts": {name: len(items) for name, items in buckets.items()},
        "splits": buckets,
    }


def sample_effis_payload(bbox: BoundingBox, count: int = 24) -> dict[str, Any]:
    """Build a deterministic EFFIS-style payload of ``count`` perimeters in a bbox."""
    min_lat, min_lon, max_lat, max_lon = bbox
    columns = 6
    rows_n = max(1, (count + columns - 1) // columns)
    size = min(0.03, (max_lat - min_lat) / rows_n * 0.3)
    features: list[dict[str, Any]] = []
    for index in range(count):
        row, col = divmod(index, columns)
        lat = min_lat + (max_lat - min_lat) * (row + 0.5) / rows_n
        lon = min_lon + (max_lon - min_lon) * (col + 0.5) / columns
        ring = [
            [lon, lat],
            [lon + size, lat],
            [lon + size, lat + size],
            [lon, lat + size],
            [lon, lat],
        ]
        year = 2007 + (index % 12)
        is_turkey = index % 2 == 0
        features.append(
            {
                "attributes": {
                    "OBJECTID": 100000 + index,
                    "FIRE_YEAR": year,
                    "COUNTRY": "Turkey" if is_turkey else "Greece",
                    "ISO_CODE": "TR" if is_turkey else "GR",
                    "NATIONAL_CODE": f"nat{year}_{index}",
                    "MMI_LEVEL": ["high", "medium", "low"][index % 3],
                    "DATE_START": f"{year}-07-{(index % 28) + 1:02d}",
                    "DATE_END": f"{year}-08-{(index % 28) + 1:02d}",
                },
                "geometry": {"rings": [ring]},
            }
        )
    return {"features": features}


def bootstrap_sample_dataset(
    session: Session, bbox: BoundingBox, count: int = 24
) -> dict[str, int]:
    """Load a deterministic offline EFFIS-style dataset (for demo/tests without network)."""
    payload = sample_effis_payload(bbox, count)
    perimeters = parse_effis_response(payload, default_year=0)
    saved = upsert_perimeters(session, perimeters)
    return {"perimeters_fetched": len(perimeters), "perimeters_saved": saved}
