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

    # EM-057: Dynamic plan auto-recompute with operator "what changed" summary.
    # Master switch for the periodic recompute sweep (wind / position / capacity).
    AUTO_RECOMPUTE_ENABLED = os.getenv("AUTO_RECOMPUTE_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    # How often the recompute sweep runs (minutes).
    AUTO_RECOMPUTE_INTERVAL_MINUTES = int(
        os.getenv("AUTO_RECOMPUTE_INTERVAL_MINUTES", "5")
    )
    # Fire-centroid move (km) that counts as a meaningful position change.
    AUTO_RECOMPUTE_POSITION_MOVE_KM = float(
        os.getenv("AUTO_RECOMPUTE_POSITION_MOVE_KM", "1.0")
    )
    # Relative effective-capacity change (%) that counts as a meaningful change.
    AUTO_RECOMPUTE_CAPACITY_CHANGE_PCT = float(
        os.getenv("AUTO_RECOMPUTE_CAPACITY_CHANGE_PCT", "10.0")
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

    # --- EM-020: spread forecast uncertainty display ------------------------
    # Wind-ensemble perturbation used for the optimistic/pessimistic band:
    # direction +/- this many degrees and speed +/- this fraction (0.15 = 15%).
    SPREAD_UNCERTAINTY_WIND_DIR_DELTA_DEG = float(
        os.getenv("SPREAD_UNCERTAINTY_WIND_DIR_DELTA_DEG", "10.0")
    )
    SPREAD_UNCERTAINTY_WIND_SPEED_FRACTION = float(
        os.getenv("SPREAD_UNCERTAINTY_WIND_SPEED_FRACTION", "0.15")
    )

    # --- EM-021: land/sea mask and natural barriers -------------------------
    # When enabled, horizon polygons are clipped at water bodies (sea, lake,
    # wide river, non-burnable) and slowed at partial obstacles (road, river).
    SPREAD_BARRIERS_ENABLED = os.getenv("SPREAD_BARRIERS_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    # --- EM-022: model performance optimization ------------------------------
    # Cache and vectorize input-layer reads so a spread recomputation stays
    # inside the operator target below. Off switches back to the scalar path.
    SPREAD_PERF_ENABLED = os.getenv("SPREAD_PERF_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    # TTL of cached weather/topography/land-cover/barrier reads (seconds).
    SPREAD_PERF_CACHE_TTL_SECONDS = float(
        os.getenv("SPREAD_PERF_CACHE_TTL_SECONDS", "120")
    )
    # Coordinate quantization of the cache grid in degrees (0.001 ~= 111 m).
    SPREAD_PERF_CACHE_GRID_DEG = float(os.getenv("SPREAD_PERF_CACHE_GRID_DEG", "0.001"))
    # Recomputation time target the benchmark is graded against (seconds).
    SPREAD_RECOMPUTE_TARGET_SECONDS = float(
        os.getenv("SPREAD_RECOMPUTE_TARGET_SECONDS", "10.0")
    )

    # --- EM-023: exposure analysis (settlements / roads / energy) ------------
    # Guard for the OSM ingest endpoint: refuse a bbox larger than this area in
    # square degrees so an accidental whole-country bbox cannot hammer Overpass
    # or exhaust memory. The pilot region (~14 deg^2) stays well under this.
    EXPOSURE_IMPORT_MAX_BBOX_AREA_DEG2 = float(
        os.getenv("EXPOSURE_IMPORT_MAX_BBOX_AREA_DEG2", "30.0")
    )
    # Hard cap on how many elements a single import may return.
    EXPOSURE_IMPORT_MAX_ASSETS = int(os.getenv("EXPOSURE_IMPORT_MAX_ASSETS", "2000"))
    # Only settlements carrying a name, or in these priority place classes, are
    # ingested by default (drops unnamed isolated dwellings that flood the list).
    EXPOSURE_IMPORT_PRIORITY_PLACE_CLASSES = [
        klass.strip()
        for klass in os.getenv(
            "EXPOSURE_IMPORT_PRIORITY_PLACE_CLASSES", "city,town,village"
        ).split(",")
        if klass.strip()
    ]
    # The threatened-element analysis is recomputed on every map/list call; a
    # short TTL cache keyed by the (forecast, asset, road) table fingerprint
    # keeps the commander view responsive without returning stale data.
    EXPOSURE_CACHE_ENABLED = os.getenv("EXPOSURE_CACHE_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    EXPOSURE_CACHE_TTL_SECONDS = float(os.getenv("EXPOSURE_CACHE_TTL_SECONDS", "60"))
    # Population reference for the priority-score normalization (log scale).
    EXPOSURE_POPULATION_REFERENCE = float(
        os.getenv("EXPOSURE_POPULATION_REFERENCE", "100000")
    )

    # --- EM-090: WebSocket live updates -------------------------------------
    # A monotonic change feed (fire_event / forecast / alert) streamed to
    # connected operator clients so the map refreshes without a page reload.
    LIVE_UPDATES_ENABLED = os.getenv("LIVE_UPDATES_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    # How often each WebSocket polls the change feed (seconds). The DB is the
    # source of truth so updates written by a separate Celery worker process
    # still reach clients; this interval only bounds delivery latency.
    LIVE_POLL_INTERVAL_SECONDS = float(os.getenv("LIVE_POLL_INTERVAL_SECONDS", "2.0"))
    # Keepalive frame sent when the feed is idle, so a dead connection is
    # detected and the client can reconnect (0 disables the heartbeat).
    LIVE_HEARTBEAT_SECONDS = float(os.getenv("LIVE_HEARTBEAT_SECONDS", "15"))
    # Upper bound on how many missed updates a reconnecting client may catch up
    # in one request (older backlog is trimmed to keep frames small).
    LIVE_MAX_CATCHUP = int(os.getenv("LIVE_MAX_CATCHUP", "100"))

    # Commander capacity & risk panel (EM-073)
    # FWI value at which a zone is considered to have breached the risk
    # threshold; the panel reports the first day each zone crossed it.
    RISK_PANEL_THRESHOLD = float(os.getenv("RISK_PANEL_THRESHOLD", "30.0"))

    # Operational risk index (EM-029, Epic E3)
    # Risk(t) = spread demand(t) / effective suppression capacity, both kept in
    # hectare/hour so the ratio is a unitless severity the bands classify. These
    # three maxima are the configurable level boundaries; anything above the
    # last one is critical ("<0.6 normal, 0.6-0.9 dikkat, 0.9-1.2 kritik-yakin,
    # >1.2 kritik").
    RISK_INDEX_NORMAL_MAX = float(os.getenv("RISK_INDEX_NORMAL_MAX", "0.6"))
    RISK_INDEX_CAUTION_MAX = float(os.getenv("RISK_INDEX_CAUTION_MAX", "0.9"))
    RISK_INDEX_CRITICAL_NEAR_MAX = float(
        os.getenv("RISK_INDEX_CRITICAL_NEAR_MAX", "1.2")
    )

    # Threshold-crossing alert (EM-032, Epic E3)
    # When an event's risk band escalates a level up we push one "alert"
    # entry onto the live feed (visual + audio on the operator map). Repeat
    # alerts for the same event are suppressed via hysteresis: an alert only
    # fires above the highest band already alerted for that event (read back
    # from the append-only feed), so re-evaluations at the same level are quiet.
    RISK_ALERTS_ENABLED = os.getenv("RISK_ALERTS_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # Capacity unit definition & normalization (EM-028, Epic E3)
    # Default "effective suppression capacity" (hectare/hour) assumed per unit
    # of each deployable resource type. These seed the admin-editable
    # capacity_assumptions table so capacity and risk share one unit (ha/hour).
    CAPACITY_HA_PER_HOUR_CREW = float(os.getenv("CAPACITY_HA_PER_HOUR_CREW", "2.0"))
    CAPACITY_HA_PER_HOUR_HELICOPTER = float(
        os.getenv("CAPACITY_HA_PER_HOUR_HELICOPTER", "12.0")
    )
    CAPACITY_HA_PER_HOUR_UAV = float(os.getenv("CAPACITY_HA_PER_HOUR_UAV", "4.0"))

    # EM-033: time-dependent capacity (Epic E3). When on, the capacity-gap
    # timeline prices each horizon against the capacity actually on station at
    # that minute (available now + en-route units whose arrival ETA has passed)
    # instead of holding capacity flat. Off -> EM-030 flat-capacity behaviour.
    TIME_DEPENDENT_CAPACITY = os.getenv("TIME_DEPENDENT_CAPACITY", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # EM-055: wind what-if live recomputation (Epic E6)
    # Wall-clock budget the ephemeral two-run recompute is graded against.
    WHATIF_RECOMPUTE_TARGET_SECONDS = float(
        os.getenv("WHATIF_RECOMPUTE_TARGET_SECONDS", "10.0")
    )

    # EM-062: rolling what-if run history (Epic E6)
    # How many recent what-if runs are kept for scroll-back + one-click revert.
    WHATIF_HISTORY_ENABLED = os.getenv("WHATIF_HISTORY_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    # Maximum history entries retained (oldest trimmed as new runs arrive).
    WHATIF_HISTORY_LIMIT = int(os.getenv("WHATIF_HISTORY_LIMIT", "10"))

    # EM-060: recompute performance budget + auto scale-down (Epic E6)
    # p95 of recent recompute latencies must stay under the target; when it
    # does not, a warning is raised and subsequent recomputes automatically
    # drop to a coarse resolution (fewer polygon vertices, trimmed horizons).
    PERF_BUDGET_ENABLED = os.getenv("PERF_BUDGET_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    PERF_BUDGET_TARGET_SECONDS = float(os.getenv("PERF_BUDGET_TARGET_SECONDS", "10.0"))
    PERF_BUDGET_WINDOW = int(os.getenv("PERF_BUDGET_WINDOW", "50"))
    PERF_BUDGET_MIN_SAMPLES = int(os.getenv("PERF_BUDGET_MIN_SAMPLES", "5"))
    PERF_BUDGET_ALERTS_ENABLED = os.getenv(
        "PERF_BUDGET_ALERTS_ENABLED", "true"
    ).lower() in ("1", "true", "yes", "on")
    PERF_BUDGET_COARSE_VERTICES = int(os.getenv("PERF_BUDGET_COARSE_VERTICES", "12"))
    PERF_BUDGET_COARSE_HORIZONS = [
        int(minutes)
        for minutes in os.getenv("PERF_BUDGET_COARSE_HORIZONS", "30,120").split(",")
        if minutes.strip()
    ]

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

    # Proactive resource positioning (EM-052)
    # How many nearest-resource deployment proposals to surface per event.
    POSITIONING_MAX_PROPOSALS = int(os.getenv("POSITIONING_MAX_PROPOSALS", "5"))
    # Aerial assets (helicopter / uav) fly great-circle instead of road-routed
    # (EM-049); this cruise speed in km/h turns straight-line distance into ETA.
    POSITIONING_AIR_SPEED_KMH = float(os.getenv("POSITIONING_AIR_SPEED_KMH", "220"))
    # EM-050 constraint-based optimisation: when enabled, an origin without
    # night capability is rejected if its arrival would land in the night
    # window; menzil (range_km) and mesai/yakıt (shift_minutes) limits always
    # apply when declared. Resources with NULL limits are never rejected.
    POSITIONING_NIGHT_BAN_ENABLED = os.getenv(
        "POSITIONING_NIGHT_BAN_ENABLED", "1"
    ) not in ("0", "false", "no")

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
    # EM-022: keep the scalar (uncached) engine path so endpoint tests stay
    # deterministic; the benchmark overrides this per measurement mode.
    SPREAD_PERF_ENABLED = False
    # EM-090: fast feed poll so WebSocket push tests are not timing-sensitive.
    LIVE_POLL_INTERVAL_SECONDS = 0.05
    LIVE_HEARTBEAT_SECONDS = 0.0


class ProductionConfig(Config):
    """Production konfigürasyonu"""

    DEBUG = False
    TESTING = False

    @classmethod
    def ensure_production_safe(cls) -> None:
        """Refuse to boot production on the inherited development defaults.

        A missing or SQLite ``DATABASE_URL`` means the environment was never
        configured for production; continuing anyway would silently run the
        live system on a file database with no server-side guarantees.
        """
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise RuntimeError(
                "DATABASE_URL must be set explicitly when APP_ENV=production"
            )
        if url.startswith("sqlite"):
            raise RuntimeError(
                "APP_ENV=production refuses a SQLite DATABASE_URL; "
                "point it at the PostgreSQL server"
            )


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
    'development'. Selecting production additionally runs the
    :meth:`ProductionConfig.ensure_production_safe` boot guard.
    """
    key = env or os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development"
    cls = _CONFIG_MAP.get(key.lower().strip(), DevelopmentConfig)
    if cls is ProductionConfig:
        ProductionConfig.ensure_production_safe()
    return cls
