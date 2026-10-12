"""Celery tasks for the wildfire data pipeline.

Every task follows the same lifecycle, centralised in :func:`_run_tracked_task`:

* a dedicated :class:`~src.database.Database` per execution whose engine is
  **always disposed afterwards** (tasks run in long-lived workers, so leaking
  connection pools would exhaust the database over time);
* the job is tracked through :class:`~src.services.pipeline_tracker.PipelineTracker`;
* on failure the aborted transaction is rolled back **before** the failure is
  recorded, so ``fail_job`` can still persist even on PostgreSQL (where an
  error poisons the whole transaction);
* the task is retried with exponential backoff up to the configured maximum.
"""
from typing import Any, Callable, Dict

from celery import Celery

from src.config.settings import ProductionConfig
from src.database import Database
from src.services.auto_recompute import auto_recompute_sweep
from src.services.effis import import_effis_perimeters
from src.services.fire_sync import sync_firms
from src.services.fwi import compute_region_fwi
from src.services.grid_standard import PilotRegionGridService
from src.services.isolation_forest_anomaly import score_silent_zone_anomalies
from src.services.land_cover import sync_land_cover_for_clusters
from src.services.pipeline_tracker import PipelineTracker
from src.services.road_network import sync_road_network as import_road_network
from src.services.spread_trigger import auto_trigger_forecasts
from src.services.topography import sync_topography_for_clusters
from src.services.weather import sync_weather_for_clusters

celery_app = Celery("wildfire-monitoring")
config = ProductionConfig  # pylint: disable=invalid-name
celery_app.conf.update(
    broker_url=config.CELERY_BROKER_URL,
    result_backend=config.CELERY_RESULT_BACKEND,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "sync-nasa-firms": {
            "task": "src.tasks.sync_nasa_firms",
            "schedule": config.FIRMS_SYNC_INTERVAL_MINUTES * 60,
        },
        "sync-openweather": {
            "task": "src.tasks.sync_openweather",
            "schedule": config.WEATHER_SYNC_INTERVAL_MINUTES * 60,
        },
        "sync-topography": {
            "task": "src.tasks.sync_topography",
            "schedule": config.TOPOGRAPHY_SYNC_INTERVAL_MINUTES * 60,
        },
        "sync-land-cover": {
            "task": "src.tasks.sync_land_cover",
            "schedule": config.LAND_COVER_SYNC_INTERVAL_MINUTES * 60,
        },
        "sync-road-network": {
            "task": "src.tasks.sync_road_network",
            "schedule": config.ROAD_NETWORK_SYNC_INTERVAL_MINUTES * 60,
        },
        "import-historical-fire": {
            "task": "src.tasks.import_historical_fire_data",
            "schedule": config.EFFIS_HISTORICAL_SYNC_INTERVAL_MINUTES * 60,
        },
        "compute-fire-weather-index": {
            "task": "src.tasks.compute_fire_weather_index",
            "schedule": config.FWI_SYNC_INTERVAL_MINUTES * 60,
        },
        "trigger-spread-forecasts": {
            "task": "src.tasks.trigger_spread_forecasts",
            "schedule": config.SPREAD_TRIGGER_INTERVAL_MINUTES * 60,
        },
        "auto-recompute-plans": {
            "task": "src.tasks.auto_recompute_plans",
            "schedule": config.AUTO_RECOMPUTE_INTERVAL_MINUTES * 60,
        },
        "score-silent-zone-anomalies": {
            "task": "src.tasks.score_silent_zone_anomaly_scores",
            "schedule": config.ANOMALY_INTERVAL_MINUTES * 60,
        },
    },
    timezone="UTC",
)


def _run_tracked_task(
    self: Any,
    job_name: str,
    source: str,
    sync_fn: Callable[[Any, Any], Dict[str, Any]],
    records_key: str,
) -> dict[str, Any]:
    """Run one tracked pipeline job with full transaction/engine hygiene.

    ``sync_fn`` receives ``(session, config)`` and returns the result dict
    whose ``records_key`` counter is stored on the job row.
    """
    database = Database(config.DATABASE_URL)
    try:
        database.create_all()
        with database.session() as session:
            job = PipelineTracker.start_job(session, job_name, source)
            try:
                res = sync_fn(session, config)
                PipelineTracker.complete_job(
                    session,
                    job,
                    records_processed=int(res.get(records_key, 0)),
                    attempt_count=self.request.retries + 1,
                )
                return {"status": "ok", **res}
            except Exception as exc:
                # The failed work poisoned the transaction (PostgreSQL aborts
                # it); roll back so the failure record below can be committed.
                session.rollback()
                PipelineTracker.fail_job(
                    session,
                    job,
                    error_message=str(exc),
                    attempt_count=self.request.retries + 1,
                )
                countdown = int(
                    config.PIPELINE_BACKOFF_FACTOR**self.request.retries * 10
                )
                raise self.retry(exc=exc, countdown=countdown) from exc
    finally:
        database.engine.dispose()


def _pilot_bbox() -> tuple[float, float, float, float]:
    """Pilot-region bounding box (min_lat, min_lon, max_lat, max_lon)."""
    grid = PilotRegionGridService()
    return (grid.min_lat, grid.min_lon, grid.max_lat, grid.max_lon)


def _score_anomalies(session: Any, settings: Any) -> dict[str, Any]:
    """EM-036 read-time scorer adapter: needs only settings, so the session is unused."""
    del session
    return score_silent_zone_anomalies(settings)


@celery_app.task(
    name="src.tasks.sync_nasa_firms",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_nasa_firms(self: Any) -> dict[str, Any]:
    """Fetch and persist active fire data from NASA FIRMS with tracking and retry."""
    return _run_tracked_task(
        self,
        "sync_nasa_firms",
        "FIRMS",
        sync_firms,
        "observations",
    )


@celery_app.task(
    name="src.tasks.sync_openweather",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_openweather(self: Any) -> dict[str, Any]:
    """Fetch and persist weather forecast data for fire clusters."""
    return _run_tracked_task(
        self,
        "sync_openweather",
        "OpenWeather",
        sync_weather_for_clusters,
        "weather_points_saved",
    )


@celery_app.task(
    name="src.tasks.sync_topography",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_topography(self: Any) -> dict[str, Any]:
    """Fetch and persist elevation/slope/aspect data for fire clusters."""
    return _run_tracked_task(
        self,
        "sync_topography",
        "USGS/SRTM",
        sync_topography_for_clusters,
        "topography_points_saved",
    )


@celery_app.task(
    name="src.tasks.sync_land_cover",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_land_cover(self: Any) -> dict[str, Any]:
    """Fetch and persist CORINE land cover classification data for fire clusters."""
    return _run_tracked_task(
        self,
        "sync_land_cover",
        "Copernicus",
        sync_land_cover_for_clusters,
        "land_cover_points_saved",
    )


@celery_app.task(
    name="src.tasks.sync_road_network",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_road_network(self: Any) -> dict[str, Any]:
    """Import and persist the OpenStreetMap road network for the pilot region."""
    bbox = _pilot_bbox()
    return _run_tracked_task(
        self,
        "sync_road_network",
        "OpenStreetMap",
        lambda session, settings: import_road_network(session, settings, bbox),
        "segments_saved",
    )


@celery_app.task(
    name="src.tasks.import_historical_fire_data",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def import_historical_fire_data(self: Any) -> dict[str, Any]:
    """Import EFFIS historical fire perimeters for the pilot region."""
    bbox = _pilot_bbox()
    return _run_tracked_task(
        self,
        "import_historical_fire_data",
        "EFFIS",
        lambda session, settings: import_effis_perimeters(session, settings, bbox),
        "perimeters_saved",
    )


@celery_app.task(
    name="src.tasks.trigger_spread_forecasts",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def trigger_spread_forecasts(self: Any) -> dict[str, Any]:
    """EM-018: refresh spread forecasts for active events (debounced sweep)."""
    if not config.SPREAD_AUTO_TRIGGER_ENABLED:
        return {"status": "disabled"}
    return _run_tracked_task(
        self,
        "trigger_spread_forecasts",
        "Rothermel/EM-018",
        auto_trigger_forecasts,
        "triggered_count",
    )


@celery_app.task(
    name="src.tasks.compute_fire_weather_index",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def compute_fire_weather_index(self: Any) -> dict[str, Any]:
    """Compute the daily zone Fire Weather Index and drought indicator layer."""
    return _run_tracked_task(
        self,
        "compute_fire_weather_index",
        "FWI/OpenWeather",
        compute_region_fwi,
        "zones_computed",
    )


@celery_app.task(
    name="src.tasks.auto_recompute_plans",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def auto_recompute_plans(self: Any) -> dict[str, Any]:
    """EM-057: refresh plans whose wind/position/capacity changed and notify."""
    if not config.AUTO_RECOMPUTE_ENABLED:
        return {"status": "disabled"}
    return _run_tracked_task(
        self,
        "auto_recompute_plans",
        "EM-057/auto-recompute",
        auto_recompute_sweep,
        "recomputed_count",
    )


@celery_app.task(
    name="src.tasks.score_silent_zone_anomaly_scores",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def score_silent_zone_anomaly_scores(self: Any) -> dict[str, Any]:
    """EM-036: recompute every cell's Isolation-Forest anomaly score (15-min)."""
    if not config.ANOMALY_SCORING_ENABLED:
        return {"status": "disabled"}
    return _run_tracked_task(
        self,
        "score_silent_zone_anomaly_scores",
        "EM-036/isolation-forest",
        _score_anomalies,
        "anomaly_count",
    )
