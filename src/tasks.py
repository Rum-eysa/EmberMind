"""Celery tasks for the wildfire data pipeline."""
from celery import Celery

from src.config.settings import ProductionConfig
from src.database import Database
from src.services.fire_sync import sync_firms


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
        }
    },
    timezone="UTC",
)


@celery_app.task(name="src.tasks.sync_nasa_firms")
def sync_nasa_firms() -> dict[str, int]:
    """Fetch and persist active fire data from NASA FIRMS."""
    database = Database(config.DATABASE_URL)
    with database.session() as session:
        database.create_all()
        return sync_firms(session, config)
