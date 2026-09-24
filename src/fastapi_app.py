"""Single public FastAPI application for wildfire monitoring."""
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.config.settings import ProductionConfig, TestingConfig
from src.database import Database
from src.models.fire import FireCluster
from src.models.land_cover import LandCoverDataPoint
from src.models.spatial import FireEvent, SilentRegion
from src.models.topography import TopographyDataPoint
from src.models.weather import WeatherDataPoint
from src.services.fire_sync import sync_firms, sync_status
from src.services.firms import FirmsSourceError
from src.services.grid_standard import (
    GridStandardError,
    PilotRegionGridService,
)
from src.services.land_cover import (
    LandCoverSourceError,
    sync_land_cover_for_clusters,
)
from src.services.spatial_db import (
    SpatialQueryError,
    execute_polygon_intersection_query,
)
from src.services.topography import (
    TopographySourceError,
    sync_topography_for_clusters,
)
from src.services.weather import WeatherSourceError, sync_weather_for_clusters


class FireClusterResponse(BaseModel):
    """Public representation of a FIRMS fire cluster."""

    cluster_key: str
    latitude: float
    longitude: float
    observation_count: int
    max_frp: float | None
    first_seen_at: str
    last_seen_at: str


class FiresResponse(BaseModel):
    """Response envelope for fire clusters."""

    source: str
    count: int
    fires: list[FireClusterResponse]


class SyncResponse(BaseModel):
    """Response returned after an on-demand FIRMS sync."""

    status: str
    observations: int
    clusters: int
    source: str
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
    forecast_offset_hours: int
    forecast_time: str
    fetched_at: str
    source: str


class WeatherResponse(BaseModel):
    """Response envelope for weather data points."""

    source: str
    count: int
    weather_data: list[WeatherDataPointResponse]


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


class LandCoverSyncResponse(BaseModel):
    """Response returned after an on-demand land cover sync."""

    status: str
    clusters_processed: int
    land_cover_points_saved: int


class PolygonIntersectionRequest(BaseModel):
    """Request payload for spatial polygon intersection queries."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


class TransformCoordinateRequest(BaseModel):
    """Request payload for EPSG:4326 to UTM 35N conversion and 30m grid snapping."""

    latitude: float
    longitude: float


class ResampleGridRequest(BaseModel):
    """Request payload for resampling spatial raster data to uniform 30m grid."""

    points: list[dict[str, Any]]


def create_fastapi_app(config_name: str = "testing") -> FastAPI:
    """Create the FastAPI application and its database lifecycle."""
    settings = TestingConfig if config_name == "testing" else ProductionConfig
    database = Database(settings.DATABASE_URL)

    @asynccontextmanager
    async def lifespan(_api: FastAPI):
        database.create_all()
        yield

    api = FastAPI(
        title="Wildfire Monitoring API",
        version="1.0.0",
        description=(
            "NASA FIRMS active-fire, weather forecast, "
            "USGS/SRTM topography, CORINE land cover, and PostGIS spatial monitoring service."
        ),
        lifespan=lifespan,
    )
    api.state.database = database
    api.state.settings = settings

    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @api.get("/api/v1", tags=["system"])
    def api_root() -> dict[str, str]:
        return {"version": "1.0.0", "project": "Yangın İzleme Sistemi"}

    @api.get("/api/v1/fires", response_model=FiresResponse, tags=["fires"])
    def fires(limit: int = Query(default=500, ge=1, le=1000)) -> dict[str, Any]:
        with database.session() as session:
            rows = session.scalars(
                select(FireCluster)
                .order_by(FireCluster.last_seen_at.desc())
                .limit(limit)
            ).all()
            fire_rows = [row.as_dict for row in rows]
        return {"source": "NASA FIRMS", "count": len(fire_rows), "fires": fire_rows}

    @api.get("/api/v1/fires/status", tags=["fires"])
    def fires_status() -> dict[str, Any]:
        with database.session() as session:
            return sync_status(session)

    @api.post("/api/v1/fires/sync", response_model=SyncResponse, tags=["fires"])
    def sync_fires() -> dict[str, Any]:
        try:
            with database.session() as session:
                result = sync_firms(session, settings)
                return {"status": "ok", **result, **sync_status(session)}
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

    @api.get("/api/v1/spatial/events", tags=["spatial"])
    def spatial_events(
        limit: int = Query(default=100, ge=1, le=1000)
    ) -> dict[str, Any]:
        with database.session() as session:
            rows = session.scalars(
                select(FireEvent).order_by(FireEvent.started_at.desc()).limit(limit)
            ).all()
            return {
                "source": "PostGIS/Spatial",
                "count": len(rows),
                "events": [r.as_dict for r in rows],
            }

    @api.get("/api/v1/spatial/silent-regions", tags=["spatial"])
    def spatial_silent_regions() -> dict[str, Any]:
        with database.session() as session:
            rows = session.scalars(
                select(SilentRegion).where(SilentRegion.is_active.is_(True))
            ).all()
            return {
                "source": "PostGIS/Spatial",
                "count": len(rows),
                "silent_regions": [r.as_dict for r in rows],
            }

    @api.post("/api/v1/spatial/polygon-intersection", tags=["spatial"])
    def spatial_polygon_intersection(
        req: PolygonIntersectionRequest,
    ) -> dict[str, Any]:
        try:
            with database.session() as session:
                return execute_polygon_intersection_query(
                    session, req.min_lat, req.max_lat, req.min_lon, req.max_lon
                )
        except SpatialQueryError as exc:
            raise HTTPException(
                status_code=500,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/grid/pilot-region", tags=["grid"])
    def get_pilot_region() -> dict[str, Any]:
        grid_service = PilotRegionGridService()
        return {
            "region_name": "TR-GR Coasline Wildfire Pilot Region",
            "justification": grid_service.justification,
            "bounding_box": {
                "min_latitude": grid_service.min_lat,
                "max_latitude": grid_service.max_lat,
                "min_longitude": grid_service.min_lon,
                "max_longitude": grid_service.max_lon,
            },
            "coordinate_standards": {
                "storage_crs": grid_service.storage_crs,
                "metric_crs": grid_service.metric_crs,
            },
            "grid_specification": {
                "resolution_meters": grid_service.resolution_meters,
            },
        }

    @api.post("/api/v1/grid/transform-coordinate", tags=["grid"])
    def transform_coordinate(req: TransformCoordinateRequest) -> dict[str, Any]:
        try:
            grid_service = PilotRegionGridService()
            in_region = grid_service.is_within_pilot_region(req.latitude, req.longitude)
            easting, northing, utm_crs = grid_service.wgs84_to_utm_35n(
                req.latitude, req.longitude
            )
            grid_cell = grid_service.align_to_30m_grid(req.latitude, req.longitude)
            return {
                "input": {"latitude": req.latitude, "longitude": req.longitude},
                "within_pilot_region": in_region,
                "metric_projection": {
                    "easting_m": easting,
                    "northing_m": northing,
                    "crs": utm_crs,
                },
                "grid_30m": {
                    "cell_id": grid_cell.cell_id,
                    "grid_lat": grid_cell.grid_lat,
                    "grid_lon": grid_cell.grid_lon,
                    "resolution_meters": grid_cell.resolution_meters,
                },
            }
        except GridStandardError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.post("/api/v1/grid/resample-30m", tags=["grid"])
    def resample_grid_30m(req: ResampleGridRequest) -> dict[str, Any]:
        grid_service = PilotRegionGridService()
        resampled = grid_service.resample_raster_layer_to_30m(req.points)
        return {
            "source_points_count": len(req.points),
            "resampled_grid_cells_count": len(resampled),
            "resolution_meters": 30,
            "resampled_data": resampled,
        }

    return api


app = create_fastapi_app()
