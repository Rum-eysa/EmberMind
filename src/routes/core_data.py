"""Core data-source endpoints (fire clusters, weather, topography, land cover).

Extracted from the create_fastapi_app monolith (code-quality audit A-6) into the
project's standard ``register_*_routes`` module. Behaviour-preserving: the model
declarations and route bodies are moved verbatim; the same routes are registered
in the same order via the single ``register_core_data_routes`` call.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.database import Database
from src.models.fire import FireCluster
from src.models.land_cover import LandCoverDataPoint
from src.models.topography import TopographyDataPoint
from src.models.weather import WeatherDataPoint
from src.services.data_governance import attribution_for
from src.services.fire_sync import sync_firms, sync_status
from src.services.firms import FirmsSourceError
from src.services.land_cover import (
    LandCoverSourceError,
    sync_land_cover_for_clusters,
)
from src.services.live import safe_record_update
from src.services.topography import (
    TopographySourceError,
    sync_topography_for_clusters,
)
from src.services.weather import WeatherSourceError, sync_weather_for_clusters


class FireClusterResponse(BaseModel):
    """Public representation of a merged VIIRS/MODIS fire cluster."""

    cluster_key: str
    latitude: float
    longitude: float
    observation_count: int
    max_frp: float | None
    first_seen_at: str
    last_seen_at: str
    sources: str | None = None
    latency_minutes: float | None = None
    deduplicated_count: int = 0


class FiresResponse(BaseModel):
    """Response envelope for fire clusters."""

    source: str
    count: int
    fires: list[FireClusterResponse]
    attribution: str | None = None


class SyncResponse(BaseModel):
    """Response returned after an on-demand multi-satellite FIRMS sync."""

    status: str
    observations: int
    clusters: int
    source: str
    duplicates_removed: int = 0
    sources: list[str] | None = None
    coverage: dict[str, Any] | None = None
    last_success_at: str | None
    last_success_age_minutes: float | None = None
    last_observation_count: int | None = None
    last_error: str | None = None
    stale: bool


class WeatherDataPointResponse(BaseModel):
    """Public representation of a weather forecast data point."""

    id: int
    cluster_key: str | None = None
    latitude: float
    longitude: float
    temperature: float
    humidity: float
    wind_speed: float
    wind_deg: float
    rain: float = 0.0
    forecast_offset_hours: int
    forecast_time: str
    fetched_at: str
    source: str


class WeatherResponse(BaseModel):
    """Response envelope for weather data points."""

    source: str
    count: int
    weather_data: list[WeatherDataPointResponse]
    attribution: str | None = None


class WeatherSyncResponse(BaseModel):
    """Response returned after an on-demand weather sync."""

    status: str
    clusters_processed: int
    weather_points_saved: int


class TopographyDataPointResponse(BaseModel):
    """Public representation of a topography data point."""

    id: int
    cluster_key: str | None = None
    latitude: float
    longitude: float
    elevation: float
    slope: float
    aspect: float
    resolution_meters: int
    fetched_at: str
    source: str


class TopographyResponse(BaseModel):
    """Response envelope for topography data points."""

    source: str
    count: int
    topography_data: list[TopographyDataPointResponse]
    attribution: str | None = None


class TopographySyncResponse(BaseModel):
    """Response returned after an on-demand topography sync."""

    status: str
    clusters_processed: int
    topography_points_saved: int


class LandCoverDataPointResponse(BaseModel):
    """Public representation of a land cover data point."""

    id: int
    cluster_key: str | None = None
    latitude: float
    longitude: float
    corine_code: int | None = None
    land_cover_class: str
    fuel_model: str
    spread_factor: float
    fetched_at: str
    source: str


class LandCoverResponse(BaseModel):
    """Response envelope for land cover data points."""

    source: str
    count: int
    land_cover_data: list[LandCoverDataPointResponse]
    attribution: str | None = None


class LandCoverSyncResponse(BaseModel):
    """Response returned after an on-demand land cover sync."""

    status: str
    clusters_processed: int
    land_cover_points_saved: int


def register_core_data_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the fire/weather/topography/land-cover read+sync endpoints."""

    @api.get("/api/v1/fires", response_model=FiresResponse, tags=["fires"])
    def fires(limit: int = Query(default=500, ge=1, le=1000)) -> dict[str, Any]:
        with database.session() as session:
            rows = session.scalars(
                select(FireCluster)
                .order_by(FireCluster.last_seen_at.desc())
                .limit(limit)
            ).all()
            fire_rows = [row.as_dict for row in rows]
        return {
            "source": "NASA FIRMS",
            "count": len(fire_rows),
            "fires": fire_rows,
            "attribution": attribution_for(settings, "firms"),
        }

    @api.get("/api/v1/fires/status", tags=["fires"])
    def fires_status() -> dict[str, Any]:
        with database.session() as session:
            return sync_status(session)

    @api.post("/api/v1/fires/sync", response_model=SyncResponse, tags=["fires"])
    def sync_fires() -> dict[str, Any]:
        try:
            with database.session() as session:
                result = sync_firms(session, settings)
                status = sync_status(session)
                safe_record_update(
                    database,
                    settings,
                    "fire_event",
                    title="Uydu tespiti güncellendi",
                    message=(
                        f"{result.get('clusters', 0)} küme / "
                        f"{result.get('observations', 0)} gözlem senkronize edildi"
                    ),
                    payload={
                        "clusters": result.get("clusters"),
                        "observations": result.get("observations"),
                    },
                    source="NASA FIRMS",
                )
                return {"status": "ok", **result, **status}
        except FirmsSourceError as exc:
            with database.session() as session:
                status = sync_status(session)
            raise HTTPException(
                status_code=503,
                detail={"status": "stale", "error": str(exc), **status},
            ) from exc

    @api.get("/api/v1/weather", response_model=WeatherResponse, tags=["weather"])
    def weather(
        cluster_key: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        with database.session() as session:
            query = select(WeatherDataPoint)
            if cluster_key:
                query = query.where(WeatherDataPoint.cluster_key == cluster_key)
            rows = session.scalars(
                query.order_by(WeatherDataPoint.forecast_time.asc()).limit(limit)
            ).all()
            weather_rows = [row.as_dict for row in rows]
        return {
            "source": "OpenWeatherMap",
            "count": len(weather_rows),
            "weather_data": weather_rows,
            "attribution": attribution_for(settings, "weather"),
        }

    @api.post(
        "/api/v1/weather/sync", response_model=WeatherSyncResponse, tags=["weather"]
    )
    def sync_weather() -> dict[str, Any]:
        try:
            with database.session() as session:
                result = sync_weather_for_clusters(session, settings)
                return {"status": "ok", **result}
        except WeatherSourceError as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get(
        "/api/v1/topography",
        response_model=TopographyResponse,
        tags=["topography"],
    )
    def topography(
        cluster_key: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        with database.session() as session:
            query = select(TopographyDataPoint)
            if cluster_key:
                query = query.where(TopographyDataPoint.cluster_key == cluster_key)
            rows = session.scalars(
                query.order_by(TopographyDataPoint.fetched_at.desc()).limit(limit)
            ).all()
            topo_rows = [row.as_dict for row in rows]
        return {
            "source": "USGS/SRTM",
            "count": len(topo_rows),
            "topography_data": topo_rows,
            "attribution": attribution_for(settings, "topography"),
        }

    @api.post(
        "/api/v1/topography/sync",
        response_model=TopographySyncResponse,
        tags=["topography"],
    )
    def sync_topography() -> dict[str, Any]:
        try:
            with database.session() as session:
                result = sync_topography_for_clusters(session, settings)
                return {"status": "ok", **result}
        except TopographySourceError as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get(
        "/api/v1/land-cover",
        response_model=LandCoverResponse,
        tags=["land-cover"],
    )
    def land_cover(
        cluster_key: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        with database.session() as session:
            query = select(LandCoverDataPoint)
            if cluster_key:
                query = query.where(LandCoverDataPoint.cluster_key == cluster_key)
            rows = session.scalars(
                query.order_by(LandCoverDataPoint.fetched_at.desc()).limit(limit)
            ).all()
            lc_rows = [row.as_dict for row in rows]
        return {
            "source": "CORINE/LandCover",
            "count": len(lc_rows),
            "land_cover_data": lc_rows,
            "attribution": attribution_for(settings, "land_cover"),
        }

    @api.post(
        "/api/v1/land-cover/sync",
        response_model=LandCoverSyncResponse,
        tags=["land-cover"],
    )
    def sync_land_cover() -> dict[str, Any]:
        try:
            with database.session() as session:
                result = sync_land_cover_for_clusters(session, settings)
                return {"status": "ok", **result}
        except LandCoverSourceError as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "error", "error": str(exc)},
            ) from exc
