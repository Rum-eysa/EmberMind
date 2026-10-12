"""Grid-standard and pipeline job-control endpoints.

Extracted from the create_fastapi_app monolith (code-quality audit A-6, step 3)
into the project's standard ``register_*_routes`` module. Behaviour-preserving:
the model declarations and the route bodies are moved verbatim; grid routes are
registered first, then pipeline routes, via the single
``register_grid_pipeline_routes`` call placed exactly where the inline block
used to sit, so route registration order (and thus the OpenAPI surface) is
unchanged. Keeping grid and pipeline in one function (rather than two) is
intentional: the grid endpoints use neither ``database`` nor ``settings`` while
the pipeline endpoints use both, so the shared signature has no unused argument.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.effis import EffisSourceError, import_effis_perimeters
from src.services.fire_sync import sync_firms
from src.services.firms import FirmsSourceError
from src.services.fwi import FwiError, compute_region_fwi
from src.services.grid_standard import (
    GridStandardError,
    PilotRegionGridService,
)
from src.services.land_cover import (
    LandCoverSourceError,
    sync_land_cover_for_clusters,
)
from src.services.pipeline_tracker import PipelineTracker
from src.services.road_network import RoadNetworkError, sync_road_network
from src.services.topography import (
    TopographySourceError,
    sync_topography_for_clusters,
)
from src.services.weather import WeatherSourceError, sync_weather_for_clusters


class PipelineJobResponse(BaseModel):
    """Public representation of a pipeline job run log."""

    id: int
    job_name: str
    source: str
    status: str
    start_time: str | None = None
    end_time: str | None = None
    duration_seconds: float | None = None
    attempt_count: int
    records_processed: int
    error_message: str | None = None
    created_at: str | None = None


class PipelineJobsResponse(BaseModel):
    """Response envelope for pipeline job history."""

    count: int
    jobs: list[PipelineJobResponse]


class PipelineTriggerRequest(BaseModel):
    """Request payload to trigger data source sync jobs."""

    source: str


class TransformCoordinateRequest(BaseModel):
    """Request payload for EPSG:4326 to UTM 35N conversion and 30m grid snapping."""

    latitude: float
    longitude: float


class ResampleGridRequest(BaseModel):
    """Request payload for resampling spatial raster data to uniform 30m grid."""

    points: list[dict[str, Any]]


def register_grid_pipeline_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the grid-standard and pipeline job-control endpoints."""

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

    @api.get("/api/v1/pipeline/status", tags=["pipeline"])
    def pipeline_status() -> dict[str, Any]:
        with database.session() as session:
            summary = PipelineTracker.get_pipeline_summary(session)
            summary["schedules"] = {
                "FIRMS": f"{settings.FIRMS_SYNC_INTERVAL_MINUTES}m",
                "OpenWeather": f"{settings.WEATHER_SYNC_INTERVAL_MINUTES}m",
                "USGS/SRTM": f"{settings.TOPOGRAPHY_SYNC_INTERVAL_MINUTES}m",
                "Copernicus": f"{settings.LAND_COVER_SYNC_INTERVAL_MINUTES}m",
                "OpenStreetMap": f"{settings.ROAD_NETWORK_SYNC_INTERVAL_MINUTES}m",
                "EFFIS": f"{settings.EFFIS_HISTORICAL_SYNC_INTERVAL_MINUTES}m",
                "FWI": f"{settings.FWI_SYNC_INTERVAL_MINUTES}m",
            }
            return summary

    @api.get(
        "/api/v1/pipeline/jobs",
        response_model=PipelineJobsResponse,
        tags=["pipeline"],
    )
    def pipeline_jobs(
        job_name: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        with database.session() as session:
            jobs_list = PipelineTracker.get_job_history(
                session, job_name=job_name, limit=limit
            )
            return {"count": len(jobs_list), "jobs": jobs_list}

    @api.post("/api/v1/pipeline/trigger", tags=["pipeline"])
    def pipeline_trigger(req: PipelineTriggerRequest) -> dict[str, Any]:
        valid_sources = [
            "firms",
            "weather",
            "topography",
            "land_cover",
            "road_network",
            "historical_fire",
            "fwi",
            "all",
        ]
        target = req.source.lower().strip()
        if target not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid target source '{req.source}'. Must be one of {valid_sources}",
            )

        results: dict[str, Any] = {}
        with database.session() as session:
            grid_service = PilotRegionGridService()
            bbox = (
                grid_service.min_lat,
                grid_service.min_lon,
                grid_service.max_lat,
                grid_service.max_lon,
            )
            specs = [
                (
                    "firms",
                    "sync_nasa_firms",
                    "FIRMS",
                    "observations",
                    FirmsSourceError,
                    lambda: sync_firms(session, settings),
                ),
                (
                    "weather",
                    "sync_openweather",
                    "OpenWeather",
                    "weather_points_saved",
                    WeatherSourceError,
                    lambda: sync_weather_for_clusters(session, settings),
                ),
                (
                    "topography",
                    "sync_topography",
                    "USGS/SRTM",
                    "topography_points_saved",
                    TopographySourceError,
                    lambda: sync_topography_for_clusters(session, settings),
                ),
                (
                    "land_cover",
                    "sync_land_cover",
                    "Copernicus",
                    "land_cover_points_saved",
                    LandCoverSourceError,
                    lambda: sync_land_cover_for_clusters(session, settings),
                ),
                (
                    "road_network",
                    "sync_road_network",
                    "OpenStreetMap",
                    "segments_saved",
                    RoadNetworkError,
                    lambda: sync_road_network(session, settings, bbox),
                ),
                (
                    "historical_fire",
                    "import_historical_fire_data",
                    "EFFIS",
                    "perimeters_saved",
                    EffisSourceError,
                    lambda: import_effis_perimeters(session, settings, bbox),
                ),
                (
                    "fwi",
                    "compute_fire_weather_index",
                    "FWI/OpenWeather",
                    "zones_computed",
                    FwiError,
                    lambda: compute_region_fwi(session, settings),
                ),
            ]
            for key, job_name, job_source, records_key, error_cls, sync_fn in specs:
                if target not in (key, "all"):
                    continue
                job = PipelineTracker.start_job(session, job_name, job_source)
                try:
                    res = sync_fn()
                    PipelineTracker.complete_job(
                        session, job, records_processed=res.get(records_key, 0)
                    )
                    results[key] = res
                except error_cls as exc:
                    PipelineTracker.fail_job(session, job, error_message=str(exc))
                    results[key] = {"error": str(exc)}

        return {"status": "triggered", "results": results}
