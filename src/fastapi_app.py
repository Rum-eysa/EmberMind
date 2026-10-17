"""Single public FastAPI application for wildfire monitoring."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config.settings import get_config
from src.database import Database
from src.routes.accessibility import register_accessibility_routes
from src.routes.api_access import register_api_access_routes
from src.routes.api_docs import register_api_docs_routes
from src.routes.audit_trail import register_audit_trail_routes
from src.routes.auth import register_auth_routes
from src.routes.authorization import register_authorization_routes
from src.routes.capacity import register_capacity_routes
from src.routes.core_data import register_core_data_routes
from src.routes.crossborder import register_crossborder_routes
from src.routes.crossborder_notification import (
    register_crossborder_notification_routes,
)
from src.routes.data_governance import register_data_governance_routes
from src.routes.data_quality import register_data_quality_routes
from src.routes.decision_support import register_decision_support_routes
from src.routes.design_system import register_design_system_routes
from src.routes.event_lifecycle import register_event_lifecycle_routes
from src.routes.event_timeline import register_event_timeline_routes
from src.routes.exposure import register_exposure_routes
from src.routes.external_support import register_external_support_routes
from src.routes.field_view import register_field_view_routes
from src.routes.fwi import register_fwi_routes
from src.routes.grid_pipeline import register_grid_pipeline_routes
from src.routes.historical_fire import register_historical_fire_routes
from src.routes.i18n import register_i18n_routes
from src.routes.integration_templates import (
    register_integration_template_routes,
)
from src.routes.inventory import register_inventory_routes
from src.routes.isolation_forest_anomaly import (
    register_isolation_forest_anomaly_routes,
)
from src.routes.live import register_live_routes
from src.routes.localization import register_localization_routes
from src.routes.map_interaction import register_map_interaction_routes
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
from src.routes.scenario_editor import register_scenario_editor_routes
from src.routes.scenario_library import register_scenario_library_routes
from src.routes.scenario_playback import register_scenario_playback_routes
from src.routes.scenario_share import register_scenario_share_routes
from src.routes.security_privacy import register_security_privacy_routes
from src.routes.share_policy import register_share_policy_routes
from src.routes.shift_handover import register_shift_handover_routes
from src.routes.silent_detection_performance import (
    register_silent_detection_performance_routes,
)
from src.routes.silent_region_alert import register_silent_region_alert_routes
from src.routes.silent_region_risk import register_silent_region_risk_routes
from src.routes.silent_zone_confidence import register_silent_zone_confidence_routes
from src.routes.silent_zone_panel import register_silent_zone_panel_routes
from src.routes.silent_zone_tuning import register_silent_zone_tuning_routes
from src.routes.silent_zone_verification import (
    register_silent_zone_verification_routes,
)
from src.routes.signal_baseline import register_signal_baseline_routes
from src.routes.signal_baseline_seasonal import (
    register_signal_baseline_seasonal_routes,
)
from src.routes.sitrep_report import register_sitrep_routes
from src.routes.spatial_events import register_spatial_event_routes
from src.routes.spread import register_spread_routes
from src.routes.support_request_draft import (
    register_support_request_draft_routes,
)
from src.routes.synthetic import register_synthetic_routes
from src.routes.task_instruction import register_task_instruction_routes
from src.routes.ui_states import register_ui_state_routes
from src.routes.user_management import register_user_management_routes
from src.routes.user_preferences import register_user_preference_routes
from src.routes.webhook import register_webhook_routes
from src.routes.whatif import register_whatif_routes
from src.routes.whatif_history import register_whatif_history_routes
from src.services.api_docs import (
    OPENAPI_CONTACT,
    OPENAPI_LICENSE,
    OPENAPI_TAGS,
    OPENAPI_TERMS,
)
from src.services.observability import setup_logging


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
        # EM-095: publish a documented, self-describing OpenAPI surface. The
        # interactive docs (Swagger UI / ReDoc / raw schema) are enabled
        # explicitly and the schema carries maintainer + license identity.
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=OPENAPI_TAGS,
        contact=dict(OPENAPI_CONTACT),
        license_info=dict(OPENAPI_LICENSE),
        terms_of_service=OPENAPI_TERMS,
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
    register_map_interaction_routes(api, database, settings)
    register_field_view_routes(api, database, settings)
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
    register_decision_support_routes(api, database, settings)
    register_accessibility_routes(api, database, settings)
    register_api_access_routes(api, database, settings)
    register_api_docs_routes(api, database, settings)
    register_auth_routes(api, database, settings)
    register_authorization_routes(api, database, settings)
    register_user_management_routes(api, database, settings)
    register_security_privacy_routes(api, database, settings)
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
    register_integration_template_routes(api, database, settings)
    register_share_policy_routes(api, database, settings)
    register_silent_zone_panel_routes(api, database, settings)
    register_signal_baseline_routes(api, database, settings)
    register_signal_baseline_seasonal_routes(api, database, settings)
    register_isolation_forest_anomaly_routes(api, database, settings)
    register_silent_region_risk_routes(api, database, settings)
    register_silent_zone_confidence_routes(api, database, settings)
    register_silent_detection_performance_routes(api, database, settings)
    register_silent_region_alert_routes(api, database, settings)
    register_silent_zone_verification_routes(api, database, settings)
    register_silent_zone_tuning_routes(api, database, settings)
    register_inventory_routes(api, database, settings)
    register_capacity_routes(api, database, settings)
    register_whatif_routes(api, database, settings)
    register_scenario_share_routes(api, database, settings)
    register_whatif_history_routes(api, database, settings)
    register_perf_budget_routes(api, database, settings)
    register_synthetic_routes(api, database, settings)
    register_scenario_library_routes(api, database, settings)
    register_scenario_playback_routes(api, database, settings)
    register_scenario_editor_routes(api, database, settings)
    register_live_routes(api, database, settings)

    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @api.get("/api/v1", tags=["system"])
    def api_root() -> dict[str, str]:
        return {"version": "1.0.0", "project": "Yangın İzleme Sistemi"}

    register_core_data_routes(api, database, settings)

    register_spatial_event_routes(api, database, settings)

    register_grid_pipeline_routes(api, database, settings)

    register_event_lifecycle_routes(api, database, settings)

    return api


app = create_fastapi_app()
