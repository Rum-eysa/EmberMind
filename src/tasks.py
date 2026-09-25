"""Celery tasks for the wildfire data pipeline."""
from typing import Any

from celery import Celery

from src.config.settings import ProductionConfig
from src.database import Database
from src.services.effis import import_effis_perimeters
from src.services.fire_sync import sync_firms
from src.services.fwi import compute_region_fwi
from src.services.grid_standard import PilotRegionGridService
from src.services.land_cover import sync_land_cover_for_clusters
from src.services.pipeline_tracker import PipelineTracker
from src.services.road_network import sync_road_network as import_road_network
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
    },
    timezone="UTC",
)


@celery_app.task(
    name="src.tasks.sync_nasa_firms",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_nasa_firms(self: Any) -> dict[str, Any]:
    """Fetch and persist active fire data from NASA FIRMS with tracking and retry."""
    database = Database(config.DATABASE_URL)
    with database.session() as session:
        database.create_all()
        job = PipelineTracker.start_job(session, "sync_nasa_firms", "FIRMS")
        try:
            res = sync_firms(session, config)
            records = res.get("observations", 0)
            PipelineTracker.complete_job(
                session,
                job,
                records_processed=records,
                attempt_count=self.request.retries + 1,
            )
            return {"status": "ok", **res}
        except Exception as exc:
            PipelineTracker.fail_job(
                session,
                job,
                error_message=str(exc),
                attempt_count=self.request.retries + 1,
            )
            countdown = int(config.PIPELINE_BACKOFF_FACTOR**self.request.retries * 10)
            raise self.retry(exc=exc, countdown=countdown) from exc


@celery_app.task(
    name="src.tasks.sync_openweather",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_openweather(self: Any) -> dict[str, Any]:
    """Fetch and persist weather forecast data for fire clusters."""
    database = Database(config.DATABASE_URL)
    with database.session() as session:
        database.create_all()
        job = PipelineTracker.start_job(session, "sync_openweather", "OpenWeather")
        try:
            res = sync_weather_for_clusters(session, config)
            records = res.get("weather_points_saved", 0)
            PipelineTracker.complete_job(
                session,
                job,
                records_processed=records,
                attempt_count=self.request.retries + 1,
            )
            return {"status": "ok", **res}
        except Exception as exc:
            PipelineTracker.fail_job(
                session,
                job,
                error_message=str(exc),
                attempt_count=self.request.retries + 1,
            )
            countdown = int(config.PIPELINE_BACKOFF_FACTOR**self.request.retries * 10)
            raise self.retry(exc=exc, countdown=countdown) from exc


@celery_app.task(
    name="src.tasks.sync_topography",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_topography(self: Any) -> dict[str, Any]:
    """Fetch and persist elevation/slope/aspect data for fire clusters."""
    database = Database(config.DATABASE_URL)
    with database.session() as session:
        database.create_all()
        job = PipelineTracker.start_job(session, "sync_topography", "USGS/SRTM")
        try:
            res = sync_topography_for_clusters(session, config)
            records = res.get("topography_points_saved", 0)
            PipelineTracker.complete_job(
                session,
                job,
                records_processed=records,
                attempt_count=self.request.retries + 1,
            )
            return {"status": "ok", **res}
        except Exception as exc:
            PipelineTracker.fail_job(
                session,
                job,
                error_message=str(exc),
                attempt_count=self.request.retries + 1,
            )
            countdown = int(config.PIPELINE_BACKOFF_FACTOR**self.request.retries * 10)
            raise self.retry(exc=exc, countdown=countdown) from exc


@celery_app.task(
    name="src.tasks.sync_land_cover",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_land_cover(self: Any) -> dict[str, Any]:
    """Fetch and persist CORINE land cover classification data for fire clusters."""
    database = Database(config.DATABASE_URL)
    with database.session() as session:
        database.create_all()
        job = PipelineTracker.start_job(session, "sync_land_cover", "Copernicus")
        try:
            res = sync_land_cover_for_clusters(session, config)
            records = res.get("land_cover_points_saved", 0)
            PipelineTracker.complete_job(
                session,
                job,
                records_processed=records,
                attempt_count=self.request.retries + 1,
            )
            return {"status": "ok", **res}
        except Exception as exc:
            PipelineTracker.fail_job(
                session,
                job,
                error_message=str(exc),
                attempt_count=self.request.retries + 1,
            )
            countdown = int(config.PIPELINE_BACKOFF_FACTOR**self.request.retries * 10)
            raise self.retry(exc=exc, countdown=countdown) from exc


@celery_app.task(
    name="src.tasks.sync_road_network",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def sync_road_network(self: Any) -> dict[str, Any]:
    """Import and persist the OpenStreetMap road network for the pilot region."""
    database = Database(config.DATABASE_URL)
    grid = PilotRegionGridService()
    bbox = (grid.min_lat, grid.min_lon, grid.max_lat, grid.max_lon)
    with database.session() as session:
        database.create_all()
        job = PipelineTracker.start_job(session, "sync_road_network", "OpenStreetMap")
        try:
            res = import_road_network(session, config, bbox)
            records = res.get("segments_saved", 0)
            PipelineTracker.complete_job(
                session,
                job,
                records_processed=records,
                attempt_count=self.request.retries + 1,
            )
            return {"status": "ok", **res}
        except Exception as exc:
            PipelineTracker.fail_job(
                session,
                job,
                error_message=str(exc),
                attempt_count=self.request.retries + 1,
            )
            countdown = int(config.PIPELINE_BACKOFF_FACTOR**self.request.retries * 10)
            raise self.retry(exc=exc, countdown=countdown) from exc


@celery_app.task(
    name="src.tasks.import_historical_fire_data",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def import_historical_fire_data(self: Any) -> dict[str, Any]:
    """Import EFFIS historical fire perimeters for the pilot region."""
    database = Database(config.DATABASE_URL)
    grid = PilotRegionGridService()
    bbox = (grid.min_lat, grid.min_lon, grid.max_lat, grid.max_lon)
    with database.session() as session:
        database.create_all()
        job = PipelineTracker.start_job(session, "import_historical_fire_data", "EFFIS")
        try:
            res = import_effis_perimeters(session, config, bbox)
            records = res.get("perimeters_saved", 0)
            PipelineTracker.complete_job(
                session,
                job,
                records_processed=records,
                attempt_count=self.request.retries + 1,
            )
            return {"status": "ok", **res}
        except Exception as exc:
            PipelineTracker.fail_job(
                session,
                job,
                error_message=str(exc),
                attempt_count=self.request.retries + 1,
            )
            countdown = int(config.PIPELINE_BACKOFF_FACTOR**self.request.retries * 10)
            raise self.retry(exc=exc, countdown=countdown) from exc


@celery_app.task(
    name="src.tasks.compute_fire_weather_index",
    bind=True,
    max_retries=config.PIPELINE_MAX_RETRIES,
)
def compute_fire_weather_index(self: Any) -> dict[str, Any]:
    """Compute the daily zone Fire Weather Index and drought indicator layer."""
    database = Database(config.DATABASE_URL)
    with database.session() as session:
        database.create_all()
        job = PipelineTracker.start_job(
            session, "compute_fire_weather_index", "FWI/OpenWeather"
        )
        try:
            res = compute_region_fwi(session, config)
            records = res.get("zones_computed", 0)
            PipelineTracker.complete_job(
                session,
                job,
                records_processed=records,
                attempt_count=self.request.retries + 1,
            )
            return {"status": "ok", **res}
        except Exception as exc:
            PipelineTracker.fail_job(
                session,
                job,
                error_message=str(exc),
                attempt_count=self.request.retries + 1,
            )
            countdown = int(config.PIPELINE_BACKOFF_FACTOR**self.request.retries * 10)
            raise self.retry(exc=exc, countdown=countdown) from exc
