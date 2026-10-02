"""Single public FastAPI application for wildfire monitoring."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select

from src.config.settings import get_config
from src.database import Database
from src.models.fire import FireCluster
from src.models.land_cover import LandCoverDataPoint
from src.models.spatial import FireEvent, FireForecast, SilentRegion
from src.models.topography import TopographyDataPoint
from src.models.weather import WeatherDataPoint
from src.routes.audit_trail import register_audit_trail_routes
from src.routes.capacity import register_capacity_routes
from src.routes.crossborder import register_crossborder_routes
from src.routes.crossborder_notification import (
    register_crossborder_notification_routes,
)
from src.routes.data_governance import register_data_governance_routes
from src.routes.data_quality import register_data_quality_routes
from src.routes.design_system import register_design_system_routes
from src.routes.event_timeline import register_event_timeline_routes
from src.routes.exposure import register_exposure_routes
from src.routes.external_support import register_external_support_routes
from src.routes.fwi import register_fwi_routes
from src.routes.historical_fire import register_historical_fire_routes
from src.routes.i18n import register_i18n_routes
from src.routes.inventory import register_inventory_routes
from src.routes.live import register_live_routes
from src.routes.localization import register_localization_routes
from src.routes.map_layers import register_map_layer_routes
from src.routes.municipality_view import register_municipality_view_routes
from src.routes.multi_fire import register_multi_fire_routes
from src.routes.notification_center import register_notification_center_routes
from src.routes.perf_budget import register_perf_budget_routes
from src.routes.positioning import register_positioning_routes
from src.routes.recommendation_decision import register_recommendation_routes
from src.routes.recommendation_explain import register_recommendation_explain_routes
from src.routes.recommendation_feedback import (
    register_recommendation_feedback_routes,
)
from src.routes.recommendation_impact import register_recommendation_impact_routes
from src.routes.risk_index import register_risk_index_routes
from src.routes.risk_panel import register_risk_panel_routes
from src.routes.road_network import register_road_network_routes
from src.routes.scenario_share import register_scenario_share_routes
from src.routes.share_policy import register_share_policy_routes
from src.routes.shift_handover import register_shift_handover_routes
from src.routes.silent_detection_performance import (
    register_silent_detection_performance_routes,
)
from src.routes.silent_region_risk import register_silent_region_risk_routes
from src.routes.silent_zone_confidence import register_silent_zone_confidence_routes
from src.routes.silent_zone_panel import register_silent_zone_panel_routes
from src.routes.signal_baseline import register_signal_baseline_routes
from src.routes.sitrep_report import register_sitrep_routes
from src.routes.spread import register_spread_routes
from src.routes.support_request_draft import (
    register_support_request_draft_routes,
)
from src.routes.synthetic import register_synthetic_routes
from src.routes.task_instruction import register_task_instruction_routes
from src.routes.ui_states import register_ui_state_routes
from src.routes.user_preferences import register_user_preference_routes
from src.routes.webhook import register_webhook_routes
from src.routes.whatif import register_whatif_routes
from src.routes.whatif_history import register_whatif_history_routes
from src.services.data_governance import attribution_for
from src.services.effis import EffisSourceError, import_effis_perimeters
from src.services.fire_sync import sync_firms, sync_status
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
from src.services.live import safe_record_update
from src.services.manual_fire_event import (
    VALID_SEVERITIES,
    VALID_STATUSES,
    DuplicateFireEventError,
    ManualFireEventError,
    create_manual_fire_event,
    trigger_prediction_for_event,
)
from src.services.pipeline_tracker import PipelineTracker
from src.services.road_network import RoadNetworkError, sync_road_network
from src.services.spatial_db import (
    SpatialQueryError,
    execute_polygon_intersection_query,
)
from src.services.spread import SpreadError
from src.services.topography import (
    TopographySourceError,
    sync_topography_for_clusters,
)
from src.services.weather import WeatherSourceError, sync_weather_for_clusters
from src.services.observability import setup_logging

_LOG = logging.getLogger(__name__)


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


class ManualFireEventRequest(BaseModel):
    """Request payload for manual fire event creation."""

    name: str
    latitude: float
    longitude: float
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    geometry_wkt: str
    severity: str = "medium"
    status: str = "active"
    started_at: str | None = None
    source: str = "manual"
    notes: str | None = None
    reported_by: str | None = None
    reported_at: str | None = None
    check_duplicates: bool = True
    duplicate_threshold_km: float = 5.0
    trigger_prediction: bool = True


class ManualFireEventResponse(BaseModel):
    """Response for manual fire event creation."""

    status: str
    event: dict[str, Any]
    duplicate_warning: str | None = None
    prediction_triggered: dict[str, Any] | None = None


class ManualFireEventUpdateRequest(BaseModel):
    """Request payload for updating a manual fire event."""

    name: str | None = None
    severity: str | None = None
    status: str | None = None
    notes: str | None = None


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


def parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse an ISO datetime string (optional Z suffix) into a naive UTC datetime.

    Returns ``None`` only for an absent value; a malformed string is rejected
    with 422 instead of silently falling back to "now".
    """
    if not dt_str:
        return None
    try:
        # Handle Z suffix (UTC)
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        parsed = datetime.fromisoformat(dt_str)
        # Remove timezone info for compatibility with database
        return parsed.replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "error",
                "error": f"invalid ISO-8601 datetime: {dt_str!r}",
            },
        ) from exc


def create_fastapi_app(config_name: str | None = None) -> FastAPI:
    """Create the FastAPI application and its database lifecycle.

    ``config_name`` defaults to the environment-derived config (APP_ENV /
    FLASK_ENV, falling back to development) so a real deployment honours its
    ``DATABASE_URL`` instead of silently booting the in-memory testing
    database; tests and the in-process demo pass an explicit name.
    """
    config_cls = get_config(config_name)
    settings = config_cls()
    database = Database(settings.DATABASE_URL)

    @asynccontextmanager
    async def lifespan(_api: FastAPI):
        setup_logging(getattr(settings, "LOG_LEVEL", None))
        database.create_all()
        yield

    api = FastAPI(
        title="Wildfire Monitoring API",
        version="1.0.0",
        description=(
            "NASA FIRMS active-fire (merged VIIRS/MODIS with detection latency "
            "and cross-satellite deduplication), weather forecast, "
            "USGS/SRTM topography, CORINE land cover, PostGIS spatial monitoring service, "
            "manual fire event creation with deduplication and prediction triggering, "
            "OpenStreetMap road-network accessibility with crew ETA and closure re-routing, "
            "data-quality/freshness monitoring with operator staleness warnings, "
            "EFFIS historical fire perimeters for model calibration/validation, "
            "per-source license/attribution/quota governance with cache plans, "
            "a daily zone Fire Weather Index (FWI) with drought indicator, "
            "map layer and high-risk daily summary, a Rothermel-based "
            "spread engine producing 30/60/120-minute risk-zone polygons, "
            "and an operator map UI (/ui) with toggleable GeoJSON layers "
            "and a horizon time slider, plus a commander capacity & risk "
            "panel (/panel) with threshold colours, first exceedance time "
            "and capacity breakdown, all built on a shared design system "
            "with light/dark themes (/styleguide), plus a coordinator resource "
            "inventory (crew/helicopter/uav CRUD with CSV bulk import) exposed "
            "as a management screen (/inventory) that feeds the panel capacity "
            "account and the map resources layer, plus a deterministic "
            "synthetic scenario generator (seeded fire/wind/outage/resource "
            "data, every record explicitly labelled) for demo use."
        ),
        lifespan=lifespan,
    )
    api.state.database = database
    api.state.settings = settings

    register_road_network_routes(api, database, settings)
    register_audit_trail_routes(api, database, settings)
    register_data_quality_routes(api, database, settings)
    register_historical_fire_routes(api, database, settings)
    register_data_governance_routes(api, database, settings)
    register_fwi_routes(api, database, settings)
    register_spread_routes(api, database, settings)
    register_exposure_routes(api, database, settings)
    register_map_layer_routes(api, database, settings)
    register_positioning_routes(api, database, settings)
    register_recommendation_routes(api, database, settings)
    register_recommendation_explain_routes(api, database, settings)
    register_recommendation_impact_routes(api, database, settings)
    register_recommendation_feedback_routes(api, database, settings)
    register_task_instruction_routes(api, database, settings)
    register_risk_panel_routes(api, database, settings)
    register_risk_index_routes(api, database, settings)
    register_external_support_routes(api, database, settings)
    register_crossborder_routes(api, database, settings)
    register_crossborder_notification_routes(api, database, settings)
    register_support_request_draft_routes(api, database, settings)
    register_design_system_routes(api, database, settings)
    register_ui_state_routes(api, database, settings)
    register_event_timeline_routes(api, database, settings)
    register_multi_fire_routes(api, database, settings)
    register_municipality_view_routes(api, database, settings)
    register_notification_center_routes(api, database, settings)
    register_sitrep_routes(api, database, settings)
    register_shift_handover_routes(api, database, settings)
    register_localization_routes(api, database, settings)
    register_i18n_routes(api, database, settings)
    register_user_preference_routes(api, database, settings)
    register_webhook_routes(api, database, settings)
    register_share_policy_routes(api, database, settings)
    register_silent_zone_panel_routes(api, database, settings)
    register_signal_baseline_routes(api, database, settings)
    register_silent_region_risk_routes(api, database, settings)
    register_silent_zone_confidence_routes(api, database, settings)
    register_silent_detection_performance_routes(api, database, settings)
    register_inventory_routes(api, database, settings)
    register_capacity_routes(api, database, settings)
    register_whatif_routes(api, database, settings)
    register_scenario_share_routes(api, database, settings)
    register_whatif_history_routes(api, database, settings)
    register_perf_budget_routes(api, database, settings)
    register_synthetic_routes(api, database, settings)
    register_live_routes(api, database, settings)

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

    @api.get("/api/v1/spatial/events", tags=["spatial"])
    def spatial_events(
        limit: int = Query(default=100, ge=1, le=1000),
        source: str | None = None,
    ) -> dict[str, Any]:
        with database.session() as session:
            query = select(FireEvent)
            if source:
                query = query.where(FireEvent.source == source)
            rows = session.scalars(
                query.order_by(FireEvent.started_at.desc()).limit(limit)
            ).all()
            return {
                "source": "PostGIS/Spatial",
                "count": len(rows),
                "events": [r.as_dict for r in rows],
            }

    @api.get("/api/v1/events/{event_key}", tags=["events"])
    def get_event(event_key: str) -> dict[str, Any]:
        """Get a single fire event by event_key."""
        with database.session() as session:
            event = session.scalar(
                select(FireEvent).where(FireEvent.event_key == event_key)
            )

            if not event:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "status": "not_found",
                        "error": f"Event {event_key} not found",
                    },
                )

            return {
                "status": "ok",
                "event": event.as_dict,
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

    @api.post(
        "/api/v1/events/manual",
        response_model=ManualFireEventResponse,
        tags=["events"],
    )
    def create_manual_event(req: ManualFireEventRequest) -> dict[str, Any]:
        """Create a manual fire event with optional deduplication and prediction triggering."""
        try:
            with database.session() as session:
                started_at = parse_datetime(req.started_at)
                reported_at = parse_datetime(req.reported_at)

                # Create the manual event
                event = create_manual_fire_event(
                    session,
                    name=req.name,
                    latitude=req.latitude,
                    longitude=req.longitude,
                    min_lat=req.min_lat,
                    max_lat=req.max_lat,
                    min_lon=req.min_lon,
                    max_lon=req.max_lon,
                    geometry_wkt=req.geometry_wkt,
                    severity=req.severity,
                    status=req.status,
                    started_at=started_at,
                    source=req.source,
                    notes=req.notes,
                    reported_by=req.reported_by,
                    reported_at=reported_at,
                    check_duplicates=req.check_duplicates,
                    duplicate_threshold_km=req.duplicate_threshold_km,
                )

                # Trigger prediction if requested (EM-018: on by default,
                # a failed forecast run must not roll back event creation)
                prediction_result = None
                if req.trigger_prediction:
                    try:
                        prediction_result = trigger_prediction_for_event(
                            session, settings, event
                        )
                    except SpreadError as exc:
                        prediction_result = {
                            "status": "error",
                            "event_key": event.event_key,
                            "error": str(exc),
                        }

                safe_record_update(
                    database,
                    settings,
                    "fire_event",
                    event_key=str(event.event_key),
                    title="Yeni manuel yangın olayı",
                    message=str(event.name),
                    payload={
                        "status": event.status,
                        "severity": event.severity,
                        "prediction_triggered": prediction_result is not None,
                    },
                    source="manual",
                )

                return {
                    "status": "created",
                    "event": event.as_dict,
                    "prediction_triggered": prediction_result,
                }
        except DuplicateFireEventError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "duplicate",
                    "error": str(exc),
                    "message": "Manual event location duplicates existing satellite detection",
                },
            ) from exc
        except ManualFireEventError as exc:
            raise HTTPException(
                status_code=400,
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

    @api.put(
        "/api/v1/events/{event_key}",
        tags=["events"],
    )
    def update_manual_event(
        event_key: str,
        req: ManualFireEventUpdateRequest,
    ) -> dict[str, Any]:
        """Update an existing fire event."""
        try:
            with database.session() as session:
                event = session.scalar(
                    select(FireEvent).where(FireEvent.event_key == event_key)
                )

                if not event:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "status": "not_found",
                            "error": f"Event {event_key} not found",
                        },
                    )

                # Update fields if provided (controlled vocabularies enforced)
                if req.name is not None:
                    event.name = req.name  # type: ignore[assignment]
                if req.severity is not None:
                    if req.severity not in VALID_SEVERITIES:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "status": "error",
                                "error": (
                                    f"invalid severity '{req.severity}'; "
                                    f"expected one of {list(VALID_SEVERITIES)}"
                                ),
                            },
                        )
                    event.severity = req.severity  # type: ignore[assignment]
                if req.status is not None:
                    if req.status not in VALID_STATUSES:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "status": "error",
                                "error": (
                                    f"invalid status '{req.status}'; "
                                    f"expected one of {list(VALID_STATUSES)}"
                                ),
                            },
                        )
                    event.status = req.status  # type: ignore[assignment]
                if req.notes is not None:
                    event.notes = req.notes  # type: ignore[assignment]

                session.flush()

                return {
                    "status": "updated",
                    "event": event.as_dict,
                }
        except HTTPException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            _LOG.exception("failed to update fire event %s", event_key)
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "error",
                    "error": "internal server error while updating event",
                },
            ) from exc

    @api.delete(
        "/api/v1/events/{event_key}",
        tags=["events"],
    )
    def delete_manual_event(event_key: str) -> dict[str, Any]:
        """Delete a fire event."""
        try:
            with database.session() as session:
                event = session.scalar(
                    select(FireEvent).where(FireEvent.event_key == event_key)
                )

                if not event:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "status": "not_found",
                            "error": f"Event {event_key} not found",
                        },
                    )

                # App-level cascade: stored forecasts belong to this event and
                # must not outlive it as orphans.
                session.execute(
                    delete(FireForecast).where(FireForecast.event_key == event_key)
                )
                session.delete(event)

                return {
                    "status": "deleted",
                    "event_key": event_key,
                }
        except HTTPException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            _LOG.exception("failed to delete fire event %s", event_key)
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "error",
                    "error": "internal server error while deleting event",
                },
            ) from exc

    return api


app = create_fastapi_app()
