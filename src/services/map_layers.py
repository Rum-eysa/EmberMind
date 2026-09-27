"""GeoJSON map layers for the operator main map (EM-072).

One endpoint per map layer so the operator UI can toggle each layer
independently: active fires, spread-forecast horizon polygons, fuel class,
silent regions, suppression resources and the road network. Every response is
a GeoJSON FeatureCollection enriched with the source attribution required by
the data-governance licenses (EM-013).
"""
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FireCluster
from src.models.inventory import SuppressionResource
from src.models.land_cover import LandCoverDataPoint
from src.models.road_network import CrewBase, RoadSegment
from src.models.spatial import (
    FireEvent,
    FireForecast,
    NaturalBarrier,
    SilentRegion,
)
from src.services.barriers import (
    BARRIER_GEOMETRY,
    BarrierError,
    parse_line_string,
    parse_polygon_ring,
)
from src.services.data_governance import attribution_for
from src.services.spread import resolve_fuel_model_number
from src.services.spread_uncertainty import (
    ENSEMBLE_MODEL_NAME,
    envelope_from_inputs,
    model_confidence,
    perturbation_settings,
)
from src.utils.timeutils import to_utc_iso

# Upper bound on features returned per layer request (keeps the map payload
# light; the pilot region is small enough for this cap).
LAYER_ROW_LIMIT = 2000

FORECASTS_ATTRIBUTION = "Yayılım tahmini: EmberMind Rothermel motoru (EM-015)"
UNCERTAINTY_ATTRIBUTION = (
    "Belirsizlik bandı: EmberMind rüzgâr ansambli, yön/hız bozumları (EM-020)"
)
SILENT_REGIONS_ATTRIBUTION = "Sessiz bölgeler: operatör kayıtları (EmberMind)"
BARRIERS_ATTRIBUTION = (
    "Doğal engeller: operatör kaydı + OSM/CORINE yüzey sınıfları (EM-021)"
)
RESOURCES_ATTRIBUTION = (
    "Müdahale kaynakları: EmberMind crew_bases + koordinatör envanteri (EM-103)"
)


class MapLayerError(RuntimeError):
    """Raised when an unknown map layer is requested."""


def parse_polygon_wkt(wkt: str | None) -> list[list[float]]:
    """Parse a simple ``POLYGON((lon lat, ...))`` WKT into a [lon, lat] ring.

    Returns an empty list for ``POLYGON(EMPTY)``, empty or malformed input so
    that callers can skip unusable geometries.
    """
    if not wkt:
        return []
    text = wkt.strip()
    if not text.upper().startswith("POLYGON((") or not text.endswith("))"):
        return []
    ring: list[list[float]] = []
    for pair in text[len("POLYGON((") : -2].split(","):
        parts = pair.strip().split()
        if len(parts) != 2:
            return []
        try:
            ring.append([float(parts[0]), float(parts[1])])
        except ValueError:
            return []
    return ring


def bbox_ring(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[list[float]]:
    """Closed counter-clockwise [lon, lat] ring for a bounding box."""
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def _point_feature(lat: Any, lon: Any, properties: dict[str, Any]) -> dict[str, Any]:
    """GeoJSON Point feature from stored latitude/longitude columns."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
        "properties": properties,
    }


def _collection(
    layer: str, title: str, features: list[dict[str, Any]], attribution: str | None
) -> dict[str, Any]:
    """Wrap features into the common GeoJSON envelope used by the map UI."""
    return {
        "type": "FeatureCollection",
        "layer": layer,
        "title": title,
        "count": len(features),
        "attribution": attribution,
        "features": features,
    }


def fires_layer(session: Session, settings: Any) -> dict[str, Any]:
    """Active fires: merged satellite clusters plus manual/satellite events."""
    features: list[dict[str, Any]] = []
    clusters = session.scalars(
        select(FireCluster)
        .order_by(FireCluster.last_seen_at.desc())
        .limit(LAYER_ROW_LIMIT)
    ).all()
    for row in clusters:
        features.append(
            _point_feature(
                row.latitude,
                row.longitude,
                {
                    "kind": "satellite_cluster",
                    "cluster_key": str(row.cluster_key),
                    "observation_count": int(row.observation_count),
                    "max_frp": row.max_frp,
                    "sources": row.sources,
                    "last_seen_at": to_utc_iso(row.last_seen_at),
                },
            )
        )
    events = session.scalars(
        select(FireEvent).order_by(FireEvent.started_at.desc()).limit(LAYER_ROW_LIMIT)
    ).all()
    for row in events:
        features.append(
            _point_feature(
                row.latitude,
                row.longitude,
                {
                    "kind": "fire_event",
                    "event_key": str(row.event_key),
                    "name": str(row.name),
                    "severity": str(row.severity),
                    "status": str(row.status),
                    "source": str(row.source),
                    "started_at": to_utc_iso(row.started_at),
                },
            )
        )
    return _collection(
        "fires", "Aktif Yangınlar", features, attribution_for(settings, "firms")
    )


def forecasts_layer(
    session: Session,
    horizon_minutes: int | None = None,
    event_key: str | None = None,
) -> dict[str, Any]:
    """EM-015 spread risk-zone polygons, filterable by horizon and event."""
    query = select(FireForecast).order_by(FireForecast.id.desc()).limit(LAYER_ROW_LIMIT)
    if horizon_minutes is not None:
        query = query.where(FireForecast.horizon_minutes == int(horizon_minutes))
    if event_key:
        query = query.where(FireForecast.event_key == event_key)
    features: list[dict[str, Any]] = []
    for row in session.scalars(query):
        ring = parse_polygon_wkt(str(row.geometry_wkt))
        if not ring:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "event_key": str(row.event_key),
                    "model_name": str(row.model_name),
                    "horizon_minutes": int(row.horizon_minutes),
                    "rate_of_spread_m_per_min": float(row.rate_of_spread_m_per_min),
                    "spread_direction_deg": float(row.spread_direction_deg),
                    "area_ha": float(row.predicted_area_ha),
                    "forecast_for": to_utc_iso(row.forecast_for),
                },
            }
        )
    return _collection(
        "forecasts", "Risk Bölgeleri (30/60/120 dk)", features, FORECASTS_ATTRIBUTION
    )


def uncertainty_layer(session: Session, settings: Any) -> dict[str, Any]:
    """EM-020 optimistic/pessimistic confidence band around the latest runs.

    Replays the stored resolved inputs (``inputs_json`` including the
    per-field provenance) of the most recent forecast per event and horizon
    through the deterministic wind ensemble, so the operator map can draw
    the band and the model-confidence badge without re-resolving layers.
    """
    latest: dict[tuple[str, int], FireForecast] = {}
    for row in session.scalars(
        select(FireForecast).order_by(FireForecast.id.desc()).limit(LAYER_ROW_LIMIT)
    ):
        key = (str(row.event_key), int(row.horizon_minutes))
        if key not in latest:
            latest[key] = row
    by_event: dict[str, dict[int, FireForecast]] = {}
    for (event_key, horizon), row in latest.items():
        by_event.setdefault(event_key, {})[horizon] = row

    dir_delta, speed_fraction = perturbation_settings(settings)
    features: list[dict[str, Any]] = []
    confidence_per_event: dict[str, Any] = {}
    for event_key, rows in sorted(by_event.items()):
        sample = max(rows.values(), key=lambda row: int(row.id))
        try:
            stored = json.loads(str(sample.inputs_json or "{}"))
        except ValueError:
            stored = {}
        if not isinstance(stored, dict) or "fuel_moisture_pct" not in stored:
            continue
        inputs = {
            **stored,
            "fuel_model_number": resolve_fuel_model_number(stored.get("fuel_model")),
        }
        envelope = envelope_from_inputs(session, settings, inputs, sorted(rows))
        confidence = model_confidence(stored.get("provenance"))
        confidence_per_event[event_key] = confidence
        for band in envelope["horizons"]:
            for extreme in ("optimistic", "pessimistic"):
                member = band[extreme]
                coordinates = member["polygon_geojson"]["coordinates"]
                if not coordinates:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": coordinates},
                        "properties": {
                            "event_key": event_key,
                            "model_name": ENSEMBLE_MODEL_NAME,
                            "horizon_minutes": band["horizon_minutes"],
                            "band": extreme,
                            "head_distance_m": member["head_distance_m"],
                            "area_ha": member["area_ha"],
                            "model_confidence_band": confidence["band"],
                            "model_confidence_score": confidence["score"],
                        },
                    }
                )
    scored = [c for c in confidence_per_event.values() if c["score"] is not None]
    worst = min(scored, key=lambda c: c["score"]) if scored else model_confidence(None)
    collection = _collection(
        "uncertainty",
        "Belirsizlik Bandı",
        features,
        UNCERTAINTY_ATTRIBUTION,
    )
    collection["perturbation"] = {
        "wind_dir_delta_deg": dir_delta,
        "wind_speed_fraction": speed_fraction,
        "model": ENSEMBLE_MODEL_NAME,
    }
    collection["model_confidence"] = worst
    collection["confidence_per_event"] = confidence_per_event
    return collection


def barriers_layer(session: Session) -> dict[str, Any]:
    """EM-021 natural barriers: water polygons and road/stream lines.

    Mixed geometry layer: full barriers (sea/lake/wide river/non-burnable)
    arrive as Polygons, partial obstacles (road/river) as LineStrings; the
    catalog advertises Polygon as the dominant shape.
    """
    features: list[dict[str, Any]] = []
    rows = session.scalars(
        select(NaturalBarrier).order_by(NaturalBarrier.id).limit(LAYER_ROW_LIMIT)
    ).all()
    for row in rows:
        kind = BARRIER_GEOMETRY.get(str(row.barrier_type))
        if kind is None:
            continue
        geometry: dict[str, Any]
        try:
            if kind == "polygon":
                ring = parse_polygon_ring(str(row.geometry_wkt))
                if ring[0] != ring[-1]:
                    ring.append(list(ring[0]))
                geometry = {"type": "Polygon", "coordinates": [ring]}
            else:
                line = parse_line_string(str(row.geometry_wkt))
                geometry = {"type": "LineString", "coordinates": line}
        except BarrierError:  # malformed stored WKT must not break the map
            continue
        properties = {
            "barrier_key": str(row.barrier_key),
            "name": str(row.name),
            "barrier_type": str(row.barrier_type),
            "slowdown_factor": float(row.slowdown_factor),
            "blocks_spread": float(row.slowdown_factor) <= 0.0,
            "is_active": bool(row.is_active),
        }
        features.append(
            {"type": "Feature", "geometry": geometry, "properties": properties}
        )
    return _collection("barriers", "Doğal Engeller", features, BARRIERS_ATTRIBUTION)


def fuel_layer(session: Session, settings: Any) -> dict[str, Any]:
    """CORINE-derived fuel class sampling points around monitored clusters."""
    features: list[dict[str, Any]] = []
    rows = session.scalars(
        select(LandCoverDataPoint)
        .order_by(LandCoverDataPoint.fetched_at.desc())
        .limit(LAYER_ROW_LIMIT)
    ).all()
    for row in rows:
        features.append(
            _point_feature(
                row.latitude,
                row.longitude,
                {
                    "fuel_model": str(row.fuel_model),
                    "land_cover_class": str(row.land_cover_class),
                    "corine_code": row.corine_code,
                    "spread_factor": float(row.spread_factor),
                },
            )
        )
    return _collection(
        "fuel", "Yakıt Sınıfı", features, attribution_for(settings, "land_cover")
    )


def silent_regions_layer(session: Session) -> dict[str, Any]:
    """Active silent (detection blackout) zones as risk-map polygons."""
    features: list[dict[str, Any]] = []
    rows = session.scalars(
        select(SilentRegion).where(SilentRegion.is_active.is_(True))
    ).all()
    for row in rows:
        ring = parse_polygon_wkt(str(row.geometry_wkt)) or bbox_ring(
            float(row.min_lat),
            float(row.max_lat),
            float(row.min_lon),
            float(row.max_lon),
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "region_name": str(row.region_name),
                    "reason": str(row.reason),
                },
            }
        )
    return _collection(
        "silent-regions", "Sessiz Bölgeler", features, SILENT_REGIONS_ATTRIBUTION
    )


def resources_layer(session: Session) -> dict[str, Any]:
    """Suppression resources: crew bases plus the EM-103 coordinator
    inventory (crew / helicopter / uav assets), distinguished by ``kind``."""
    features: list[dict[str, Any]] = []
    rows = session.scalars(select(CrewBase).order_by(CrewBase.id)).all()
    for row in rows:
        features.append(
            _point_feature(
                row.latitude,
                row.longitude,
                {
                    "kind": "crew_base",
                    "base_key": str(row.base_key),
                    "name": str(row.name),
                    "crew_type": str(row.crew_type),
                    "available": bool(row.available),
                },
            )
        )
    assets = session.scalars(
        select(SuppressionResource).order_by(SuppressionResource.resource_key)
    ).all()
    for row in assets:
        features.append(
            _point_feature(
                row.latitude,
                row.longitude,
                {
                    "kind": "suppression_resource",
                    "resource_key": str(row.resource_key),
                    "name": str(row.name),
                    "resource_type": str(row.resource_type),
                    "status": str(row.status),
                    "capacity": float(row.capacity),
                    "capacity_unit": row.capacity_unit,
                    "available": str(row.status) == "available",
                },
            )
        )
    return _collection(
        "resources", "Müdahale Kaynakları", features, RESOURCES_ATTRIBUTION
    )


def roads_layer(session: Session, settings: Any) -> dict[str, Any]:
    """OSM road segments used by crew routing (EM-011)."""
    features: list[dict[str, Any]] = []
    rows = session.scalars(
        select(RoadSegment).order_by(RoadSegment.id).limit(LAYER_ROW_LIMIT)
    ).all()
    for row in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [float(row.from_lon), float(row.from_lat)],
                        [float(row.to_lon), float(row.to_lat)],
                    ],
                },
                "properties": {
                    "segment_key": str(row.segment_key),
                    "name": row.name,
                    "highway": str(row.highway),
                    "length_km": float(row.length_km),
                    "one_way": bool(row.one_way),
                },
            }
        )
    return _collection(
        "roads", "Yol Ağı", features, attribution_for(settings, "road_network")
    )


LAYER_KEYS = (
    "fires",
    "forecasts",
    "uncertainty",
    "barriers",
    "fuel",
    "silent-regions",
    "resources",
    "roads",
)

LAYER_GEOMETRIES = {
    "fires": "Point",
    "forecasts": "Polygon",
    "uncertainty": "Polygon",
    "barriers": "Polygon",  # mixed: partial obstacles are LineStrings
    "fuel": "Point",
    "silent-regions": "Polygon",
    "resources": "Point",
    "roads": "LineString",
}


def layer_catalog() -> list[dict[str, Any]]:
    """Operator-facing list of toggleable map layers."""
    return [
        {
            "key": key,
            "title": LAYER_TITLES[key],
            "geometry": LAYER_GEOMETRIES[key],
            "url": f"/api/v1/map/layers/{key}",
        }
        for key in LAYER_KEYS
    ]


LAYER_TITLES = {
    "fires": "Aktif Yangınlar",
    "forecasts": "Risk Bölgeleri (30/60/120 dk)",
    "uncertainty": "Belirsizlik Bandı",
    "barriers": "Doğal Engeller",
    "fuel": "Yakıt Sınıfı",
    "silent-regions": "Sessiz Bölgeler",
    "resources": "Müdahale Kaynakları",
    "roads": "Yol Ağı",
}


def build_layer(
    session: Session,
    settings: Any,
    name: str,
    horizon_minutes: int | None = None,
    event_key: str | None = None,
) -> dict[str, Any]:
    """Dispatch one layer request; only forecasts accepts horizon/event filters."""
    if name == "fires":
        return fires_layer(session, settings)
    if name == "forecasts":
        return forecasts_layer(session, horizon_minutes, event_key)
    if name == "uncertainty":
        return uncertainty_layer(session, settings)
    if name == "barriers":
        return barriers_layer(session)
    if name == "fuel":
        return fuel_layer(session, settings)
    if name == "silent-regions":
        return silent_regions_layer(session)
    if name == "resources":
        return resources_layer(session)
    if name == "roads":
        return roads_layer(session, settings)
    raise MapLayerError(
        f"unknown map layer '{name}'; expected one of {sorted(LAYER_KEYS)}"
    )
