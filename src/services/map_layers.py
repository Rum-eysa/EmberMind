"""GeoJSON map layers for the operator main map (EM-072).

One endpoint per map layer so the operator UI can toggle each layer
independently: active fires, spread-forecast horizon polygons, fuel class,
silent regions, suppression resources and the road network. Every response is
a GeoJSON FeatureCollection enriched with the source attribution required by
the data-governance licenses (EM-013).
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FireCluster
from src.models.land_cover import LandCoverDataPoint
from src.models.road_network import CrewBase, RoadSegment
from src.models.spatial import FireEvent, FireForecast, SilentRegion
from src.services.data_governance import attribution_for
from src.utils.timeutils import to_utc_iso

# Upper bound on features returned per layer request (keeps the map payload
# light; the pilot region is small enough for this cap).
LAYER_ROW_LIMIT = 2000

FORECASTS_ATTRIBUTION = "Yayılım tahmini: EmberMind Rothermel motoru (EM-015)"
SILENT_REGIONS_ATTRIBUTION = "Sessiz bölgeler: operatör kayıtları (EmberMind)"
RESOURCES_ATTRIBUTION = "Müdahale kaynakları: EmberMind crew_bases"


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
    """Suppression resources: firefighting crew bases."""
    features: list[dict[str, Any]] = []
    rows = session.scalars(select(CrewBase).order_by(CrewBase.id)).all()
    for row in rows:
        features.append(
            _point_feature(
                row.latitude,
                row.longitude,
                {
                    "base_key": str(row.base_key),
                    "name": str(row.name),
                    "crew_type": str(row.crew_type),
                    "available": bool(row.available),
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


LAYER_KEYS = ("fires", "forecasts", "fuel", "silent-regions", "resources", "roads")

LAYER_GEOMETRIES = {
    "fires": "Point",
    "forecasts": "Polygon",
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
