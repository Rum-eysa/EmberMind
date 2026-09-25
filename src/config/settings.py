"""Uygulama Konfigürasyonları"""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Temel konfigürasyon"""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///wildfire.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Cache
    CACHE_TYPE = "redis"
    CACHE_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_DEFAULT_TIMEOUT = 300

    # Celery
    CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Pipeline Scheduler (5-10 min intervals & retry parameters)
    FIRMS_SYNC_INTERVAL_MINUTES = int(os.getenv("FIRMS_SYNC_INTERVAL_MINUTES", "10"))
    WEATHER_SYNC_INTERVAL_MINUTES = int(
        os.getenv("WEATHER_SYNC_INTERVAL_MINUTES", "10")
    )
    TOPOGRAPHY_SYNC_INTERVAL_MINUTES = int(
        os.getenv("TOPOGRAPHY_SYNC_INTERVAL_MINUTES", "10")
    )
    LAND_COVER_SYNC_INTERVAL_MINUTES = int(
        os.getenv("LAND_COVER_SYNC_INTERVAL_MINUTES", "10")
    )
    PIPELINE_MAX_RETRIES = int(os.getenv("PIPELINE_MAX_RETRIES", "3"))
    PIPELINE_BACKOFF_FACTOR = float(os.getenv("PIPELINE_BACKOFF_FACTOR", "2.0"))

    # OpenWeather
    OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
    OPENWEATHER_BASE_URL = os.getenv(
        "OPENWEATHER_BASE_URL", "https://api.openweathermap.org/data/2.5"
    )
    OPENWEATHER_CACHE_TTL_SECONDS = int(
        os.getenv("OPENWEATHER_CACHE_TTL_SECONDS", "1800")
    )
    WEATHER_RETRY_COUNT = int(os.getenv("WEATHER_RETRY_COUNT", "3"))

    # USGS / SRTM Topography
    USGS_SRTM_BASE_URL = os.getenv(
        "USGS_SRTM_BASE_URL", "https://api.open-elevation.com/api/v1"
    )
    TOPOGRAPHY_RESOLUTION_METERS = int(os.getenv("TOPOGRAPHY_RESOLUTION_METERS", "30"))
    TOPOGRAPHY_CACHE_TTL_SECONDS = int(
        os.getenv("TOPOGRAPHY_CACHE_TTL_SECONDS", "86400")
    )

    # OpenStreetMap / Overpass road network (EM-009)
    OVERPASS_BASE_URL = os.getenv(
        "OVERPASS_BASE_URL", "https://overpass-api.de/api/interpreter"
    )
    ROAD_NETWORK_SYNC_INTERVAL_MINUTES = int(
        os.getenv("ROAD_NETWORK_SYNC_INTERVAL_MINUTES", "720")
    )
    ROAD_ACCESS_SPEED_KMH = float(os.getenv("ROAD_ACCESS_SPEED_KMH", "40"))

    # EFFIS historical fire perimeters (EM-011)
    EFFIS_BASE_URL = os.getenv(
        "EFFIS_BASE_URL",
        "https://effis.jrc.ec.europa.eu/geoportal/arcgis/rest/services/"
        "effis_perimeters/MapServer/0",
    )
    EFFIS_HISTORICAL_YEARS = [
        int(year)
        for year in os.getenv(
            "EFFIS_HISTORICAL_YEARS", "2007,2008,2012,2017,2021"
        ).split(",")
    ]
    EFFIS_HISTORICAL_SYNC_INTERVAL_MINUTES = int(
        os.getenv("EFFIS_HISTORICAL_SYNC_INTERVAL_MINUTES", "10080")
    )

    # Data quality & freshness monitoring (EM-010)
    # A source is "stale" once its last successful pull is older than
    # sync_interval * DATA_QUALITY_STALE_MULTIPLIER minutes.
    DATA_QUALITY_STALE_MULTIPLIER = float(
        os.getenv("DATA_QUALITY_STALE_MULTIPLIER", "2")
    )
    # Consecutive failed pulls after which a source is reported as "down".
    DATA_QUALITY_FAILURE_WARNING_THRESHOLD = int(
        os.getenv("DATA_QUALITY_FAILURE_WARNING_THRESHOLD", "3")
    )


class DevelopmentConfig(Config):
    """Geliştirme konfigürasyonu"""

    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Test konfigürasyonu"""

    TESTING = True
    DATABASE_URL = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    """Production konfigürasyonu"""

    DEBUG = False
    TESTING = False
