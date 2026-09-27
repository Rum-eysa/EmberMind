"""Uygulama Konfigürasyonları"""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Temel konfigürasyon"""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///wildfire.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    APP_ENV = os.getenv("APP_ENV", "development")

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

    # NASA FIRMS multi-satellite ingestion (VIIRS + MODIS, EM-012)
    FIRMS_API_KEY = os.getenv("FIRMS_API_KEY", "")
    FIRMS_SOURCES = [
        source.strip()
        for source in os.getenv(
            "FIRMS_SOURCES",
            "VIIRS_SNPP_NRT,VIIRS_NOAA20_NRT,"
            "MODIS_Terra_CorrectedAnomalies,MODIS_Aqua_CorrectedAnomalies",
        ).split(",")
        if source.strip()
    ]
    # Legacy single-source fallback kept for backward compatibility.
    FIRMS_SOURCE = os.getenv("FIRMS_SOURCE", "VIIRS_SNPP_NRT")
    FIRMS_BBOX = os.getenv("FIRMS_BBOX", "25,35,45,43")
    FIRMS_DAYS = int(os.getenv("FIRMS_DAYS", "1"))
    FIRMS_CLUSTER_RADIUS_KM = float(os.getenv("FIRMS_CLUSTER_RADIUS_KM", "2"))
    # Two detections of the same fire by different satellites are merged when
    # they fall within the cluster radius and this acquisition time window.
    SATELLITE_DEDUP_TIME_WINDOW_MINUTES = int(
        os.getenv("SATELLITE_DEDUP_TIME_WINDOW_MINUTES", "180")
    )

    # OpenWeather
    OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
    OPENWEATHER_BASE_URL = os.getenv(
        "OPENWEATHER_BASE_URL", "https://api.openweathermap.org/data/2.5"
    )
    OPENWEATHER_CACHE_TTL_SECONDS = int(
        os.getenv("OPENWEATHER_CACHE_TTL_SECONDS", "1800")
    )
    WEATHER_RETRY_COUNT = int(os.getenv("WEATHER_RETRY_COUNT", "3"))

    # Fire Weather Index & drought indicator (EM-014)
    # Coarse analysis zone edge length in degrees over the pilot bbox.
    FWI_ZONE_SIZE_DEG = float(os.getenv("FWI_ZONE_SIZE_DEG", "0.5"))
    # FWI is a daily indicator; recomputed once per day by default.
    FWI_SYNC_INTERVAL_MINUTES = int(os.getenv("FWI_SYNC_INTERVAL_MINUTES", "1440"))

    # Rothermel spread engine (EM-015)
    # Prediction horizons in minutes for a spread forecast run.
    SPREAD_HORIZON_MINUTES = [
        int(minutes.strip())
        for minutes in os.getenv("SPREAD_HORIZON_MINUTES", "30,60,120").split(",")
        if minutes.strip()
    ]
    # Vertices used for the elliptical risk-zone polygons.
    SPREAD_POLYGON_VERTICES = int(os.getenv("SPREAD_POLYGON_VERTICES", "36"))
    # Model label stored with every generated forecast.
    SPREAD_MODEL_NAME = os.getenv("SPREAD_MODEL_NAME", "rothermel_v1")
    # EM-016: Fuel-transition-sensitive spread — when enabled, the horizon
    # polygon is reshaped per-vertex based on local land cover fuel models.
    FUEL_TRANSITION_ENABLED = os.getenv("FUEL_TRANSITION_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    # EM-018: Automatic spread-forecast triggering with debounce.
    # Master switch for the periodic Celery sweep over active events.
    SPREAD_AUTO_TRIGGER_ENABLED = os.getenv(
        "SPREAD_AUTO_TRIGGER_ENABLED", "true"
    ).lower() in ("1", "true", "yes")
    # How often the sweep runs (minutes).
    SPREAD_TRIGGER_INTERVAL_MINUTES = int(
        os.getenv("SPREAD_TRIGGER_INTERVAL_MINUTES", "10")
    )
    # Hard rate limit: the same event is never re-forecast automatically
    # within this window, even if inputs changed (anti-flap debounce).
    SPREAD_TRIGGER_DEBOUNCE_MINUTES = float(
        os.getenv("SPREAD_TRIGGER_DEBOUNCE_MINUTES", "15")
    )
    # Input deltas that count as a "meaningful change" worth a re-forecast.
    SPREAD_TRIGGER_WIND_SPEED_KMH_THRESHOLD = float(
        os.getenv("SPREAD_TRIGGER_WIND_SPEED_KMH_THRESHOLD", "10.0")
    )
    SPREAD_TRIGGER_WIND_DIR_DEG_THRESHOLD = float(
        os.getenv("SPREAD_TRIGGER_WIND_DIR_DEG_THRESHOLD", "30.0")
    )
    SPREAD_TRIGGER_HUMIDITY_PCT_THRESHOLD = float(
        os.getenv("SPREAD_TRIGGER_HUMIDITY_PCT_THRESHOLD", "10.0")
    )
    SPREAD_TRIGGER_TEMP_C_THRESHOLD = float(
        os.getenv("SPREAD_TRIGGER_TEMP_C_THRESHOLD", "5.0")
    )

    # EM-019: Dead fuel moisture model (1h/10h/100h classes from T & RH).
    # When enabled, spread inputs derive fuel moisture from the per-class
    # diurnal-conditioning model instead of the plain 1-hour EMC curve.
    FUEL_MOISTURE_MODEL_ENABLED = os.getenv(
        "FUEL_MOISTURE_MODEL_ENABLED", "true"
    ).lower() in ("1", "true", "yes")
    # Overnight temperature drop of the synthetic diurnal conditioning cycle.
    FUEL_MOISTURE_DIURNAL_TEMP_AMPLITUDE_C = float(
        os.getenv("FUEL_MOISTURE_DIURNAL_TEMP_AMPLITUDE_C", "8.0")
    )
    # Overnight relative-humidity rise of the synthetic diurnal cycle.
    FUEL_MOISTURE_DIURNAL_RH_AMPLITUDE_PCT = float(
        os.getenv("FUEL_MOISTURE_DIURNAL_RH_AMPLITUDE_PCT", "25.0")
    )
    # Conditioning window in hours (default two full diurnal cycles).
    FUEL_MOISTURE_CONDITIONING_HOURS = int(
        os.getenv("FUEL_MOISTURE_CONDITIONING_HOURS", "48")
    )

    # Commander capacity & risk panel (EM-073)
    # FWI value at which a zone is considered to have breached the risk
    # threshold; the panel reports the first day each zone crossed it.
    RISK_PANEL_THRESHOLD = float(os.getenv("RISK_PANEL_THRESHOLD", "30.0"))

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


class DemoConfig(Config):
    """Demo / sunum ortamı konfigürasyonu (EM-109).

    Harici API anahtarı gerektirmez; SQLite ve sentetik veriyle çalışır.
    CI'da veya canlı sunucuda API key olmadan tam fonksiyonel demo sunar.
    """

    DEBUG = False
    TESTING = False
    DATABASE_URL = os.getenv("DEMO_DATABASE_URL", "sqlite:///instance/wildfire-demo.db")
    CACHE_TYPE = "SimpleCache"
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    FIRMS_API_KEY = ""
    OPENWEATHER_API_KEY = ""


# ---------------------------------------------------------------------------
# Ortam fabrikası — FLASK_ENV / APP_ENV değişkenine göre konfigürasyon seçer
# ---------------------------------------------------------------------------
_CONFIG_MAP = {
    "development": DevelopmentConfig,
    "dev": DevelopmentConfig,
    "testing": TestingConfig,
    "test": TestingConfig,
    "demo": DemoConfig,
    "production": ProductionConfig,
    "prod": ProductionConfig,
}


def get_config(env: str | None = None) -> type[Config]:
    """Return the config class for the given environment name.

    Falls back to APP_ENV / FLASK_ENV environment variable, defaulting to
    'development'.
    """
    key = env or os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development"
    return _CONFIG_MAP.get(key.lower().strip(), DevelopmentConfig)
