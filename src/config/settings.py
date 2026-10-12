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

    # EM-034: capacity-assumption audit trail (Epic E3). Every applied ha/hour
    # edit is recorded (old -> new, editor, timestamp). These bound how many
    # history rows the management view reads back per request.
    CAPACITY_AUDIT_DEFAULT_LIMIT = int(os.getenv("CAPACITY_AUDIT_DEFAULT_LIMIT", "50"))
    CAPACITY_AUDIT_MAX_LIMIT = int(os.getenv("CAPACITY_AUDIT_MAX_LIMIT", "200"))

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

    # EM-065: external support early forecast (Epic E7). When the projected
    # national capacity (available now + en-route reinforcements) is forecast
    # to fall short of the spread demand at some horizon, the coordinator is
    # warned early so an international request can be raised in time. The
    # shortfall (ha/hour) is converted into whole reinforcement units using
    # this per-unit capacity, and the request must go out this many minutes
    # before the predicted shortfall so the support can actually arrive.
    EXTERNAL_SUPPORT_UNIT_HA_PER_HOUR = float(
        os.getenv("EXTERNAL_SUPPORT_UNIT_HA_PER_HOUR", "12.0")
    )
    EXTERNAL_SUPPORT_LEAD_TIME_MINUTES = int(
        os.getenv("EXTERNAL_SUPPORT_LEAD_TIME_MINUTES", "60")
    )
    # EM-071: the default locale the auto-generated external-support request
    # draft is rendered in (TR / EN / EL); an operator can still override per
    # request. Falls back to the EM-068 i18n default when unset / invalid.
    SUPPORT_REQUEST_DEFAULT_LANGUAGE = os.getenv(
        "SUPPORT_REQUEST_DEFAULT_LANGUAGE", "tr"
    )

    # EM-078: silent-zone confidence panel (Epic E8)
    # An active silent region is graded by how much live fire data contradicts
    # it: a fire inside its bbox is a hard contradiction, a nearby fire erodes
    # trust linearly up to PROXIMITY_FAR_KM. The confidence cut-offs bucket the
    # score into the high / moderate / low bands the operator filters by.
    SILENT_ZONE_HIGH_CONFIDENCE = float(
        os.getenv("SILENT_ZONE_HIGH_CONFIDENCE", "0.75")
    )
    SILENT_ZONE_MODERATE_CONFIDENCE = float(
        os.getenv("SILENT_ZONE_MODERATE_CONFIDENCE", "0.40")
    )
    SILENT_ZONE_PROXIMITY_FAR_KM = float(
        os.getenv("SILENT_ZONE_PROXIMITY_FAR_KM", "25.0")
    )

    # EM-079: panel durumu kataloğu (Epic E8)
    # Operatör panellerinin yükleme/boş/hata metinlerinin ve bağlantı-kesildi
    # bandının üretildiği dil. Kataloğun tek kaynağı deterministiktir; yalnızca
    # arayüzün çektiği etiket dilini ayarlar (hiçbir şey kalıcı değildir).
    UI_STATE_LANGUAGE = os.getenv("UI_STATE_LANGUAGE", "tr")

    # EM-081: olay zaman çizelgesi (Epic E8)
    # Vardiya devrinde operatörün kronolojik akışı kaç olayla göreceğini
    # sınırlar. Sayfa boyutu varsayılanı ve üst sınırı (birleştirme canlı
    # akış + kabul edilen öneri denetim kayıtlarından okuma zamanıdır).
    EVENT_TIMELINE_DEFAULT_LIMIT = int(os.getenv("EVENT_TIMELINE_DEFAULT_LIMIT", "50"))
    EVENT_TIMELINE_MAX_LIMIT = int(os.getenv("EVENT_TIMELINE_MAX_LIMIT", "200"))

    # EM-082: çoklu yangın yönetimi (Epic E8)
    # Eş zamanlı aktif yangın envanterinin kaç olaya kadar derleneceğini üstten
    # sınırlar (acilden eskiye sıralı). Çakışma taraması (öksüz/ortağı paylaşan
    # üs/eksik konuşlanmış acil) bu küme üzerinde okuma zamanı hesaplanır.
    MULTI_FIRE_MAX_EVENTS = int(os.getenv("MULTI_FIRE_MAX_EVENTS", "50"))

    # EM-083: salt okunur belediye görünümü (Epic E8)
    # Belediye yöneticisine gösterilecek sadeleştirilmiş, yalnızca izleme amaçlı
    # bölgenin adını ve koordinat kutusunu (varsayılan: pilot bölge) ile listedeki
    # azami aktif yangın sayısını belirler. Görünüm salt okunurdur; operatör karar
    # kontrolleri bilinçli olarak gizlenir (okuma zamanı projeksiyonu).
    MUNICIPALITY_VIEW_REGION_NAME = os.getenv(
        "MUNICIPALITY_VIEW_REGION_NAME", "TR-GR Coastal Wildfire Pilot Region"
    )
    MUNICIPALITY_VIEW_MIN_LAT = float(os.getenv("MUNICIPALITY_VIEW_MIN_LAT", "36.0"))
    MUNICIPALITY_VIEW_MAX_LAT = float(os.getenv("MUNICIPALITY_VIEW_MAX_LAT", "39.5"))
    MUNICIPALITY_VIEW_MIN_LON = float(os.getenv("MUNICIPALITY_VIEW_MIN_LON", "26.0"))
    MUNICIPALITY_VIEW_MAX_LON = float(os.getenv("MUNICIPALITY_VIEW_MAX_LON", "30.0"))
    MUNICIPALITY_VIEW_MAX_FIRES = int(os.getenv("MUNICIPALITY_VIEW_MAX_FIRES", "100"))

    # EM-086: bildirim merkezi ve sesli uyarı ayarları (Epic E8)
    # Canlı akıştaki (EM-032) uyarılar okundu/onaylandı durumuyla izlenir; kritik
    # bant onaylanana kadar panelde sabit kalır. penceredeki azami uyarı sayısı,
    # sesli alarmın varsayılan açık/kapalı durumu ve çalacağı en düşük risk bandı.
    NOTIFICATION_MAX_ALERTS = int(os.getenv("NOTIFICATION_MAX_ALERTS", "100"))
    NOTIFICATION_SOUND_ENABLED = os.getenv(
        "NOTIFICATION_SOUND_ENABLED", "true"
    ).lower() in ("1", "true", "yes")
    NOTIFICATION_SOUND_MIN_LEVEL = os.getenv("NOTIFICATION_SOUND_MIN_LEVEL", "dikkat")

    # EM-087: tek sayfalık durum raporu (SITREP) dışa aktarımı (Epic E8)
    # Rapor aktif yangın, yayılım tahmini, risk indeksi ve önerileri tek sayfada
    # derler. Bildirime giren azami yangın sayısı ve en sıcak olay için listelenecek
    # azami konuşlanma önerisi sayısı.
    SITREP_MAX_FIRES = int(os.getenv("SITREP_MAX_FIRES", "20"))
    SITREP_RECOMMENDATION_LIMIT = int(os.getenv("SITREP_RECOMMENDATION_LIMIT", "5"))

    # EM-088: kaydedilmiş operatör tercih profili (Epic E8)
    # Dil (EM-068 I18N_DEFAULT_LANGUAGE), saat dilimi / koordinat biçimi (EM-063
    # DISPLAY_*) ayarlarından miras alınır; yalnız arayüz temasının varsayılanı
    # burada belirlenir ve silinmemiş bir profil olmadığında panele yansır.
    UI_DEFAULT_THEME = os.getenv("UI_DEFAULT_THEME", "dark")

    # EM-089: vardiya devri notları ve tek tık devir özeti (Epic E8)
    # Operatör olaya serbest metin not ekler; notlar EM-081 zaman çizelgesiyle
    # birleştirilip tek tık devir özetinde gösterilir. Özet ve not listesi
    # okuma zamanıdır; yalnızca event_notes kalıcıdır. Penceredeki azami not.
    SHIFT_HANDOVER_MAX_NOTES = int(os.getenv("SHIFT_HANDOVER_MAX_NOTES", "100"))

    # EM-094: olay ve uyarı webhook'ları (Epic E9)
    # Bir bütünleştirici, olay/uyarıları canlı akışı kuyruklamak yerine anında
    # bir uç noktaya push ister. Kayıt başına URL + olay tipleri + HMAC imza
    # gizli anahtarı tutulur; başarısız teslim sınırlı üstel geri çekilme ile
    # yeniden denenir ve her deneme kalıcı geçmişe yazılır. Azami abonelik ve
    # penceredeki azami teslim sayısı, azami deneme bütçesi ve taban geri
    # çekilme saniyesi.
    WEBHOOK_MAX_SUBSCRIPTIONS = int(os.getenv("WEBHOOK_MAX_SUBSCRIPTIONS", "20"))
    WEBHOOK_MAX_DELIVERIES = int(os.getenv("WEBHOOK_MAX_DELIVERIES", "100"))
    WEBHOOK_MAX_RETRIES = int(os.getenv("WEBHOOK_MAX_RETRIES", "3"))
    WEBHOOK_BACKOFF_SECONDS = int(os.getenv("WEBHOOK_BACKOFF_SECONDS", "30"))

    # EM-096: birleşik denetim kaydı (Epic E10)
    # Yönetici, hangi alt sistemden gelirse gelsin kimin hangi kararı/ğişikliği
    # ne zaman verdiğini tek, değişmez bir defterde görmek ister. Kayıt başına
    # alan (domain) + eylem (action) + özne + aktör + eski/yeni değer anlık
    # görüntüsü tutulur. Servis yüzeyinde güncelleme/silme yoktur; defter yalnız
    # eklenendir ("kayıtlar silinemez"). Bu sınırlar bir istekte okunacak azami
    # satır sayısını belirler.
    AUDIT_DEFAULT_LIMIT = int(os.getenv("AUDIT_DEFAULT_LIMIT", "50"))
    AUDIT_MAX_LIMIT = int(os.getenv("AUDIT_MAX_LIMIT", "500"))

    # EM-035: bölge bazlı iletişim sinyali baz çizgisi (Epic E4)
    # Sessiz bölge anomalisinin anlam kazanması için önce "normal" öğrenilir:
    # her izleme hücresi için kayan baz çizgi (ortalama/yayılım/medyan) ve son
    # okumanın z-skoru okuma zamanı hesaplanır (kalıcılık: none). Pencere gün
    # sayısı, hücresel ızgara boyutu (satır x sütun, azami hücre ile sınırlı),
    # sessizlik eşiği z-skoru ve pilot varsayılan sinyal kaynağı.
    SIGNAL_BASELINE_WINDOW_DAYS = int(os.getenv("SIGNAL_BASELINE_WINDOW_DAYS", "30"))
    SIGNAL_BASELINE_CELL_ROWS = int(os.getenv("SIGNAL_BASELINE_CELL_ROWS", "4"))
    SIGNAL_BASELINE_CELL_COLS = int(os.getenv("SIGNAL_BASELINE_CELL_COLS", "5"))
    SIGNAL_BASELINE_MAX_CELLS = int(os.getenv("SIGNAL_BASELINE_MAX_CELLS", "60"))
    SIGNAL_BASELINE_SENSITIVITY_Z = float(
        os.getenv("SIGNAL_BASELINE_SENSITIVITY_Z", "1.5")
    )
    SIGNAL_BASELINE_DEFAULT_SOURCE = os.getenv(
        "SIGNAL_BASELINE_DEFAULT_SOURCE", "synthetic_communication"
    )
    # Hücre izgarasının oturtulduğu pilot kutusu (config/pilot_region.json ile
    # aynı varsayılanlar); yeniden kapsamlanan pilot için kod değişikliği gerekmez.
    SIGNAL_PILOT_MIN_LAT = float(os.getenv("SIGNAL_PILOT_MIN_LAT", "36.0"))
    SIGNAL_PILOT_MAX_LAT = float(os.getenv("SIGNAL_PILOT_MAX_LAT", "39.5"))
    SIGNAL_PILOT_MIN_LON = float(os.getenv("SIGNAL_PILOT_MIN_LON", "26.0"))
    SIGNAL_PILOT_MAX_LON = float(os.getenv("SIGNAL_PILOT_MAX_LON", "30.0"))

    # EM-043: baz çizgisi mevsimsellik + günlük yenileme (Epic E4)
    # EM-035 düz (yatay) baz çizgisi hafta sonu/gece gibi yapısal durgunlukları
    # anomali sayabilir; burada saat-in-günü ve haftanın-günü mevsimsel kat sayıları
    # öğrenilip baz çizgisi mevsimsellikten arındırılır, böylece "gece sessizliği"
    # yanlış alarm olmaz. Kat sayılar iteratif normalize ile türleştirilir; gece
    # kontrol saati ve pilot varsayılan (gündüz/gece) kaynak ayarlanabilir; azami
    # hücre EM-035 ızgarası ile aynı. Kalıcılık: none — istek zamanı yeniden hesaplanır.
    SIGNAL_SEASONAL_NIGHT_CHECK_HOUR = int(
        os.getenv("SIGNAL_SEASONAL_NIGHT_CHECK_HOUR", "3")
    )
    SIGNAL_SEASONAL_NORMALIZATION_ITERATIONS = int(
        os.getenv("SIGNAL_SEASONAL_NORMALIZATION_ITERATIONS", "3")
    )
    SIGNAL_SEASONAL_DEFAULT_SOURCE = os.getenv(
        "SIGNAL_SEASONAL_DEFAULT_SOURCE", "synthetic_diurnal"
    )
    SIGNAL_SEASONAL_MAX_CELLS = int(os.getenv("SIGNAL_SEASONAL_MAX_CELLS", "60"))

    # EM-036: Isolation Forest ile anomali skorlama (Epic E4)
    # EM-035/EM-043 tek bir z-skoru ile işaretler; burada her hücrenin baz
    # penceresinde çok-özellikli [bugünkü, dünki] sinyal vektörüyle bir
    # Isolation Forest eğitilir ve son okumun otomatik anomali skoru üretilir
    # (elle inceleme gerekmez). Sessizlik eşiği ortalama(baz) - sigma*sapma;
    # sigma varsayılan 3.0 ve yapılandırılabilir. "15 dakikalık aralıklarla
    # gerçek zamanlı" bir Celery beat tazeleme sıklığıdır; kalıcılık: none —
    # okuma zamanı yeniden hesaplanır. random_state sabitlenmiştir ki skorlar
    # çalıştırmalar arası kaymasın.
    ANOMALY_SIGMA_MULTIPLIER = float(os.getenv("ANOMALY_SIGMA_MULTIPLIER", "3.0"))
    ANOMALY_WINDOW_DAYS = int(os.getenv("ANOMALY_WINDOW_DAYS", "30"))
    ANOMALY_CONTAMINATION = float(os.getenv("ANOMALY_CONTAMINATION", "0.1"))
    ANOMALY_N_ESTIMATORS = int(os.getenv("ANOMALY_N_ESTIMATORS", "100"))
    ANOMALY_RANDOM_STATE = int(os.getenv("ANOMALY_RANDOM_STATE", "0"))
    ANOMALY_MAX_CELLS = int(os.getenv("ANOMALY_MAX_CELLS", "60"))
    ANOMALY_INTERVAL_MINUTES = int(os.getenv("ANOMALY_INTERVAL_MINUTES", "15"))
    ANOMALY_DEFAULT_SOURCE = os.getenv(
        "ANOMALY_DEFAULT_SOURCE", "synthetic_communication"
    )
    ANOMALY_SCORING_ENABLED = os.getenv("ANOMALY_SCORING_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # EM-097: karar destek uyarısı ve sorumluluk çerçevesi (Epic E10)
    # Komutan, öneri ekranında sistemin bir KARAR DESTEK aracı olduğunu ve nihai
    # kararın kendisinde (yetkili operatör) olduğunu net görmelidir; öneriyi
    # üreten veri/model sürümü de görünür olmalıdır. Pilot sentetik veriyle
    # çalıştığı için "SENARYO VERİSİ" rozeti ekranda ayrım gözetmeksizin
    # basılır. Kalıcılık: none (salt okuma zamanı yapılandırma projeksiyonu).
    DECISION_SUPPORT_MODEL_VERSION = os.getenv(
        "DECISION_SUPPORT_MODEL_VERSION", "spread-v1+recommend-v1"
    )
    DECISION_SUPPORT_DATA_VERSION = os.getenv(
        "DECISION_SUPPORT_DATA_VERSION", "pilot-synthetic-2026.08"
    )
    DECISION_SUPPORT_RESPONSIBILITY_TEXT = os.getenv(
        "DECISION_SUPPORT_RESPONSIBILITY_TEXT",
        "Nihai karar yetkili operatöre aittir; EmberMind yalnızca bir karar destek "
        "aracıdır ve önerileri otomatik uygulanmaz.",
    )
    DECISION_SUPPORT_SCENARIO_DATA = os.getenv(
        "DECISION_SUPPORT_SCENARIO_DATA", "true"
    ).lower() in ("1", "true", "yes", "on")

    # EM-092: dış istemci API anahtarı + hız sınırlama (Epic E9)
    # Sistem yöneticisi, dış entegrasyonları bir API anahtarıyla yetkilendirip
    # hızlarını sınırlamak ister ki sistem kötüye kullanılmasın. Zorlama yalnızca
    # AÇIK *ve* en az bir anahtar tanımlıyken devreye girer; aksi halde uç bilinçli
    # olarak "disabled" raporlanır (gerçekten korumayan bir güvenlik kontrolü gibi
    # davranmayız). Kalıcılık: none — pencere sayaçları yalnızca süreç belleğinde.
    API_ACCESS_ENABLED = os.getenv("API_ACCESS_ENABLED", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    API_ACCESS_KEYS = os.getenv("API_ACCESS_KEYS", "")
    API_ACCESS_RATE_LIMIT_REQUESTS = int(
        os.getenv("API_ACCESS_RATE_LIMIT_REQUESTS", "30")
    )
    API_ACCESS_RATE_LIMIT_WINDOW_SECONDS = float(
        os.getenv("API_ACCESS_RATE_LIMIT_WINDOW_SECONDS", "60")
    )

    # EM-098: kimlik doğrulama — e-posta/parola + oturum süresi (Epic E10)
    # Kullanıcı sisteme güvenli giriş yapmak ister; bugün her yüzey anonimdir
    # (kayıtlara yalnızca serbest metin "updated_by" yazılır). Parola asla
    # saklanmaz — tuzlu PBKDF2-HMAC-SHA256 özeti tutulur; oturum tokenı opak-
    # tır ve yalnızca SHA-256 parmak izi kalıcıdır. Oturum üç yolla ölür: mutlak
    # TTL, hareketsizlik (idle) zaman aşımı ve anında çıkış (revocation). Giriş
    # hataları N denemeden sonra hesabı geçici kilitler; reddi mesajları
    # birleşiktir (e-posta varlığı hiçbir zaman sızdırılmaz). Kalıcılık:
    # users + user_sessions (V034).
    AUTH_SESSION_TTL_MINUTES = int(os.getenv("AUTH_SESSION_TTL_MINUTES", "240"))
    AUTH_IDLE_TIMEOUT_MINUTES = int(os.getenv("AUTH_IDLE_TIMEOUT_MINUTES", "30"))
    AUTH_MAX_FAILED_LOGINS = int(os.getenv("AUTH_MAX_FAILED_LOGINS", "5"))
    AUTH_LOCKOUT_MINUTES = int(os.getenv("AUTH_LOCKOUT_MINUTES", "15"))
    AUTH_PBKDF2_ITERATIONS = int(os.getenv("AUTH_PBKDF2_ITERATIONS", "100000"))
    AUTH_MIN_PASSWORD_LENGTH = int(os.getenv("AUTH_MIN_PASSWORD_LENGTH", "12"))
    # Demo/bootstrap hesabi yalnizca kullanici tablosu BOS iken olusturulur.
    AUTH_DEMO_BOOTSTRAP_EMAIL = os.getenv(
        "AUTH_DEMO_BOOTSTRAP_EMAIL", "demo.operator@embermind.local"
    )
    AUTH_DEMO_BOOTSTRAP_PASSWORD = os.getenv(  # nosec B105 - demo default
        "AUTH_DEMO_BOOTSTRAP_PASSWORD", "embermind-demo"
    )

    # EM-099: Rol tabanli yetkilendirme (Epic E10)
    # EM-098 kisiyi ekledi ama rolunu HIC KULLANMADI; her yaz ucu serbest metin
    # "decided_by" etiketine guvendi. EM-099, EM-098 rollerinin (operator/
    # coordinator/field/viewer/admin) uzerinde yetki uygulamasi ekler: kabul
    # ozelligi "Izleyici oneri kabul edemez". Uygulama varsayilan KAPALIDIR —
    # kapaliyken mevcut anonim karar yuzeyi (ve tum testler) geriye donuk uyumlu
    # calisir; ACIKKEN oturumu olmayan 401, rolü yetkisiz 403 alir. Kalicilik:
    # none (rol zaten users.role'da, V034).
    AUTHZ_ENFORCEMENT_ENABLED = os.getenv(
        "AUTHZ_ENFORCEMENT_ENABLED", "false"
    ).lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # EM-101: Kullanici ve rol yonetimi (Epic E10)
    # EM-098 kisiyi, EM-099 rolu ekledi ama hesaplarin yonetilecegi bir admin
    # yuzeyi yoktu. EM-101 ekle/duzenle/devre birak + rol atama + ULKE KAPSAMI
    # (users.country, V035) ekler; her islem EM-096 defterine yazilir. Bu ayar,
    # yaratilirken acik ulke verilmezse uygulanacak varsayilan kapsamdır; bos
    # birakilirsa (varsayilan) hesap global/kapsamsiz olusturulur.
    USER_MANAGEMENT_DEFAULT_COUNTRY = (
        os.getenv("USER_MANAGEMENT_DEFAULT_COUNTRY", "").strip().upper()
    )

    # EM-100: Veri gizligi ve guvenlik temelleri (Epic E10)
    # Uygunluk denetimi kod/ayar ozelligidir; gizlilik-tasarim (bolge/hucre bazli,
    # kisi bazli degil) canli ORM metadata'sindan dogrulanir, gizli anahtarlar
    # yalnizca ortam/settings'ten okunur (deger asla raporlanmaz). TLS
    # sonlandirma bir yayinlama (E12) isidir; uygulama yalnizca ters vekilin
    # ihtiyac duydugu dugmeleri sunar. Kalicilik: none (salt okuma projeksiyonu).
    SECURITY_TRUST_PROXY_SSL_HEADER = os.getenv(
        "SECURITY_TRUST_PROXY_SSL_HEADER", "false"
    ).lower() in ("1", "true", "yes", "on")
    SECURITY_SESSION_COOKIE_SECURE = os.getenv(
        "SECURITY_SESSION_COOKIE_SECURE", "false"
    ).lower() in ("1", "true", "yes", "on")

    # EM-095: API dokümantasyonu ve örnek istemci (Epic E9)
    # Entegratör API'yi hızla denemek ister; FastAPI zaten /docs (Swagger) ve
    # /openapi.json yayınlar, ancak şemanın bir kimlik metadata'sı (iletişim/
    # lisans) ve okunur bir taban URL'si olmalıdır. Örnek istemciler bu taban
    # URL üzerinde üretilir. Kalıcılık: none (salt okuma zamanı projeksiyon).
    API_DOCS_BASE_URL = os.getenv("API_DOCS_BASE_URL", "http://localhost:8000")
    API_DOCS_CONTACT_EMAIL = os.getenv("API_DOCS_CONTACT_EMAIL", "")

    # EM-093: belediye panosu / trafik / kamu uyarı entegrasyon şablonu (Epic E9)
    # Entegratör, yeni donanım gerekmeden mevcut belediye pano / trafik mesaj
    # işareti / kamu uyarı (CAP-benzeri) sistemlerini EM-094 imzalı webhook'una
    # bağlamak ister. Bu ayarlar yalnızca örnek çıktıyı biçimlendirir (CAP
    # gönderen kimliği + uyarı dili); şablonlar EM-094 zarf sözleşmesinden türer.
    # Kalıcılık: none (salt okuma zamanı projeksiyon).
    INTEGRATION_CAP_SENDER = os.getenv(
        "INTEGRATION_CAP_SENDER", "it.embermind.wildfire"
    )
    INTEGRATION_ALERT_LANGUAGE = os.getenv("INTEGRATION_ALERT_LANGUAGE", "tr")

    # EM-105: hazır senaryo kütüphanesi (Epic E11)
    # Demo sunucusu, EM-104 üreteci üzerinde sabit (seed, config) çiftleriyle
    # hazırlanmış arketip senaryoları tek tıkla başlatmak / geri sarmak ister.
    # Kütüphane kod sabitidir (yeni tablo yok); yalnızca ``sinir-bolgesi``
    # senaryosunun yangın boylamı buradan gelir (demo bbox içine sıkıştırılır).
    SCENARIO_BORDER_LON = float(os.getenv("SCENARIO_BORDER_LON", "28.85"))

    # EM-107: senaryo oynatma (replay) kontrolü (Epic E11)
    # Sunum akışını zamanla yönetilebilir kılmak için: her kare belirli bir
    # gerçek-zaman aralığında ilerler; hız çarpanı bu aralığı böler (4x → çeyrek
    # bekleme). Kareler okuma zamanı EM-104/EM-105 verisinden türetilir; burada
    # kalıcılık yok (yeni tablo gerekmez). Duraklatma istemci tarafı bir durak.
    PLAYBACK_DEFAULT_SPEED_FACTOR = float(
        os.getenv("PLAYBACK_DEFAULT_SPEED_FACTOR", "1.0")
    )
    PLAYBACK_MAX_SPEED_FACTOR = float(os.getenv("PLAYBACK_MAX_SPEED_FACTOR", "8.0"))
    PLAYBACK_FRAME_INTERVAL_SECONDS = float(
        os.getenv("PLAYBACK_FRAME_INTERVAL_SECONDS", "2.0")
    )

    # EM-108: arayüzden yazılan özel senaryolar (Epic E11)
    # Demo sunucusu kod yazmadan yeni bir senaryo tanımlamak ve bunu kütüphaneye
    # eklemek ister. Tanım ``custom_scenarios`` tablosunda saklanır; doğrulama
    # EM-104 normalize_config üzerinden yapılır (bbox/rüzgâr/kesinti sınırları).
    # Burada yalnızca kurulum başına azami özel senaryo sayısı ayarlanır.
    SCENARIO_EDITOR_MAX_ITEMS = int(os.getenv("SCENARIO_EDITOR_MAX_ITEMS", "50"))

    # EM-037: yüksek öncelikli sessiz bölge risk kesişimi (Epic E4)
    # Sessizlik güveni (EM-078) ile aktif yangınların yayılım tahmin poligonlarının
    # (EM-015) bölge kutusunu kapsama oranı okuma zamanı çarpılır (kalıcılık:
    # none). kapsama_alti: "kesişti" sayılmak için bölge alanının en az bu oranı
    # yayılmalı; guven_alti: bölgenin "gerçekten sessiz" sayılma tabanı (altındaki
    # çelişkili bölge öncelik dışı); taramada incelenecek azami tahmin satırı ve
    # tek istekte dönecek azami bölge sayısı.
    SILENT_REGION_RISK_MIN_COVERAGE = float(
        os.getenv("SILENT_REGION_RISK_MIN_COVERAGE", "0.05")
    )
    SILENT_REGION_RISK_MIN_CONFIDENCE = float(
        os.getenv("SILENT_REGION_RISK_MIN_CONFIDENCE", "0.5")
    )
    SILENT_REGION_RISK_MAX_FORECASTS = int(
        os.getenv("SILENT_REGION_RISK_MAX_FORECASTS", "200")
    )
    SILENT_REGION_RISK_MAX_LIMIT = int(os.getenv("SILENT_REGION_RISK_MAX_LIMIT", "200"))

    # EM-038: yanlış alarm önleme - sessiz bölge güven etiketi (Epic E4)
    # EM-035 hücre baz çizgisi yeniden kullanılır; sessiz adaylar yapısal kapsama
    # gücüne ve ani düşüş derecesine göre düşük/orta/yüksek güvenle etiketlenir
    # (kalıcılık: none). coverage_signal_alti: baz ortalaması bunun altındaysa
    # kapsama "zayıf" sayılır (sessizlik büyük olasılıkla yanlış alarm -> düşük
    # güven); min_gozlem: güvenilir baz için gereken asgari gözlem sayısı;
    # ani_dusus_z: z bunun altında (-) ise düşüş "belirgin" -> yüksek güven;
    # azami_limit: tek istekte dönecek azami aday sayısı.
    FALSE_ALARM_MIN_COVERAGE_SIGNAL = float(
        os.getenv("FALSE_ALARM_MIN_COVERAGE_SIGNAL", "100.0")
    )
    FALSE_ALARM_MIN_OBSERVATIONS = int(os.getenv("FALSE_ALARM_MIN_OBSERVATIONS", "7"))
    FALSE_ALARM_STRONG_DROP_Z = float(os.getenv("FALSE_ALARM_STRONG_DROP_Z", "2.5"))
    FALSE_ALARM_MAX_LIMIT = int(os.getenv("FALSE_ALARM_MAX_LIMIT", "200"))

    # EM-042: sessiz bölge performans ölçümü - sentetik senaryoda TPR/FPR/gecikme (Epic E4)
    # Gerçek etiketli kataloq olmadığından ground-truth senaryoya deterministik enjekte
    # edilir ve EM-035 algılayıcısı gün gün yeniden çalıştırılır (kalıcılık: none).
    # ufuk_gun: değerlendirme penceresi genişliği; baz_pencere_gun: her gün için
    # öğrenilen geçmiş pencere; hassasiyet_z: sessizlik eşiği (z <= -bu); enjekte_orani:
    # hücrelerin sessiz epizot alma olasılığı; kesinti_gun: epizot uzunluğu;
    # kesinti_derinligi: sessiz günde sinyal normalin bu katına düşer;
    # azami_gecikme_gun: uyarı gecikmesi için ilk işaretleme arama ufku.
    SILENT_DETECTION_HORIZON_DAYS = int(
        os.getenv("SILENT_DETECTION_HORIZON_DAYS", "30")
    )
    SILENT_DETECTION_BASELINE_WINDOW_DAYS = int(
        os.getenv("SILENT_DETECTION_BASELINE_WINDOW_DAYS", "14")
    )
    SILENT_DETECTION_SENSITIVITY_Z = float(
        os.getenv("SILENT_DETECTION_SENSITIVITY_Z", "1.5")
    )
    SILENT_DETECTION_ONSET_RATE = float(os.getenv("SILENT_DETECTION_ONSET_RATE", "0.4"))
    SILENT_DETECTION_OUTAGE_DAYS = int(os.getenv("SILENT_DETECTION_OUTAGE_DAYS", "3"))
    SILENT_DETECTION_OUTAGE_DEPTH = float(
        os.getenv("SILENT_DETECTION_OUTAGE_DEPTH", "0.05")
    )
    SILENT_DETECTION_MAX_LATENCY_DAYS = int(
        os.getenv("SILENT_DETECTION_MAX_LATENCY_DAYS", "5")
    )

    # EM-040: yüksek öncelikli sessiz bölge uyarıları - risk seviyesi bantları (Epic E4)
    # EM-037 priority skoru (risk x sessizlik) üzerinden uyarı risk seviyesi eşikleri.
    SILENT_ALERT_CRITICAL_PRIORITY = float(
        os.getenv("SILENT_ALERT_CRITICAL_PRIORITY", "0.6")
    )
    SILENT_ALERT_HIGH_PRIORITY = float(os.getenv("SILENT_ALERT_HIGH_PRIORITY", "0.4"))
    SILENT_ALERT_MEDIUM_PRIORITY = float(
        os.getenv("SILENT_ALERT_MEDIUM_PRIORITY", "0.2")
    )
    SILENT_ALERT_MAX_LIMIT = int(os.getenv("SILENT_ALERT_MAX_LIMIT", "200"))

    # EM-041: sessiz bölge doğrulama akışı - operatör hüküm listesi üst sınırı (Epic E4)
    SILENT_VERIFICATION_MAX_LIMIT = int(
        os.getenv("SILENT_VERIFICATION_MAX_LIMIT", "200")
    )

    # EM-044: sessiz bölge hassasiyet ve eşik ayarı - bölge bazlı override (Epic E4)
    # EM-035 tek global sessizlik z-skoru, EM-040 tek global minimum öğrenir; ama
    # "ne kadar sessiz = sessiz" ve "ne kadar bekleyelim" bölgeden bölgeye değişen
    # yanlış-alarm/kaçırma takasıdır ve operatöre aittir. Bu anahtarlar global
    # varsayılanı ve override sınırlarını verir; bölge override'ı silent_zone_tuning
    # tablosunda saklanır, her değişiklik tekilleştirilmiş denetim defterine
    # (threshold alanı) yazılır. Kalıcılık: silent_zone_tuning.
    SILENT_TUNING_DEFAULT_SENSITIVITY_Z = float(
        os.getenv("SILENT_TUNING_DEFAULT_SENSITIVITY_Z", "1.5")
    )
    SILENT_TUNING_DEFAULT_MIN_SILENCE_HOURS = float(
        os.getenv("SILENT_TUNING_DEFAULT_MIN_SILENCE_HOURS", "6.0")
    )
    SILENT_TUNING_MIN_SENSITIVITY_Z = float(
        os.getenv("SILENT_TUNING_MIN_SENSITIVITY_Z", "0.5")
    )
    SILENT_TUNING_MAX_SENSITIVITY_Z = float(
        os.getenv("SILENT_TUNING_MAX_SENSITIVITY_Z", "5.0")
    )
    SILENT_TUNING_MIN_SILENCE_HOURS = float(
        os.getenv("SILENT_TUNING_MIN_SILENCE_HOURS", "0.0")
    )
    SILENT_TUNING_MAX_SILENCE_HOURS = float(
        os.getenv("SILENT_TUNING_MAX_SILENCE_HOURS", "168.0")
    )
    SILENT_TUNING_MAX_LIMIT = int(os.getenv("SILENT_TUNING_MAX_LIMIT", "200"))

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

    # Cross-border display standardization (EM-063). Times are always stored /
    # serialised in UTC; these are the presentation defaults the operator UI can
    # override per request. Turkey is Europe/Istanbul (TRT, UTC+3), Greece is
    # Europe/Athens (EET/EEST); the metric unit system (km, ha, km/h) is fixed.
    DISPLAY_TIMEZONE = os.getenv("DISPLAY_TIMEZONE", "Europe/Istanbul")
    DISPLAY_COORDINATE_FORMAT = os.getenv("DISPLAY_COORDINATE_FORMAT", "decimal")

    # EM-080: operator map interaction (Epic E8). The basemap the map opens on
    # (street/satellite/terrain), the cap on place/coordinate search results and
    # the ceiling on measurement vertices. Read-only tools: the gazetteer ships
    # with the code and measurements are ephemeral, so nothing here persists.
    MAP_DEFAULT_BASEMAP = os.getenv("MAP_DEFAULT_BASEMAP", "street")
    MAP_SEARCH_MAX_RESULTS = int(os.getenv("MAP_SEARCH_MAX_RESULTS", "8"))
    MAP_MEASURE_MAX_POINTS = int(os.getenv("MAP_MEASURE_MAX_POINTS", "100"))

    # EM-084: mobile/tablet field view (Epic E8). The proximity radius (km) within
    # which active risk zones are surfaced to the team's phone, and the cap on how
    # many nearest zones are shown. A read-only projection of EM-051 cards + EM-029
    # risk; nothing here persists.
    FIELD_VIEW_RADIUS_KM = float(os.getenv("FIELD_VIEW_RADIUS_KM", "25.0"))
    FIELD_VIEW_MAX_ITEMS = int(os.getenv("FIELD_VIEW_MAX_ITEMS", "5"))

    # EM-085: operator-surface accessibility contract (Epic E8). The default
    # theme (night-shift) and whether to honour reduced motion. The non-colour
    # risk encoding and the keyboard-shortcut registry are code constants so the
    # contract is deterministic, but these two knobs let a deployment flip the
    # defaults without a rebuild. Read-time only: persistence none.
    ACCESSIBILITY_DEFAULT_THEME = os.getenv("ACCESSIBILITY_DEFAULT_THEME", "dark")
    ACCESSIBILITY_REDUCED_MOTION = os.getenv(
        "ACCESSIBILITY_REDUCED_MOTION", "false"
    ).lower() in ("1", "true", "yes", "on")

    # EM-066: cross-border shared situation view (Epic E7). FireEvent stores
    # only a coordinate, so each incident is attributed to TR (east) or GR
    # (west) by this pilot border longitude (deg East) - a deliberate
    # simplification of the real Aegean boundary, consistent with EM-063's
    # time-zone framing. The default data-sharing scope exposes every field
    # group (fire/risk/support); a view can narrow it via ?fields=. The full
    # per-country authorization policy is EM-070, intentionally kept separate.
    CROSSBORDER_BORDER_LONGITUDE = float(
        os.getenv("CROSSBORDER_BORDER_LONGITUDE", "26.5")
    )
    CROSSBORDER_SHARED_FIELDS = os.getenv(
        "CROSSBORDER_SHARED_FIELDS", "fire,risk,support"
    )

    # EM-068: multilingual UI (Epic E7). The interface text catalogue ships with
    # TR + EN complete and EL for the core screens; this is the default locale
    # served to an operator whose browser has not chosen one yet. Supported
    # codes are tr/en/el; an unknown request is rejected (400) rather than
    # silently coerced. Per-operator choice is stored only in the browser, so
    # nothing here needs a migration (persistence: none).
    I18N_DEFAULT_LANGUAGE = os.getenv("I18N_DEFAULT_LANGUAGE", "tr")

    # EM-070: country/role data-sharing authorization policy (Epic E7). The
    # fallback field groups shared to the partner country when no explicit
    # (country, role) or country-default policy row exists. A stored policy (the
    # country_share_policy table, append-only audit) overrides this per key.
    SHARE_POLICY_DEFAULT_FIELDS = os.getenv(
        "SHARE_POLICY_DEFAULT_FIELDS", "fire,risk,support"
    )

    # EM-069: joint cross-border early-warning notification (Epic E7). When the
    # EM-067 border-crossing projection reaches these thresholds the partner
    # country's coordination unit is warned over a pre-defined channel. Edge-
    # triggered (one open warning per event/target), persisted to the
    # crossborder_notification table; ``..._ENABLED`` gates the periodic sweep.
    CROSSBORDER_NOTIFY_MIN_LIKELIHOOD = float(
        os.getenv("CROSSBORDER_NOTIFY_MIN_LIKELIHOOD", "0.4")
    )
    CROSSBORDER_NOTIFY_WINDOW_MINUTES = int(
        os.getenv("CROSSBORDER_NOTIFY_WINDOW_MINUTES", "120")
    )
    CROSSBORDER_NOTIFY_ENABLED = os.getenv(
        "CROSSBORDER_NOTIFY_ENABLED", "true"
    ).lower() in ("1", "true", "yes", "on")


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
    # EM-092: enforce external API-key + rate limiting with two fixed keys and a
    # large budget so single HTTP calls are deterministic (401/200 paths); the
    # 429 path is exercised directly against the in-memory limiter in unit tests.
    API_ACCESS_ENABLED = True
    API_ACCESS_KEYS = "test-external-key-alpha,test-external-key-beta"  # nosec B105
    API_ACCESS_RATE_LIMIT_REQUESTS = 1000
    API_ACCESS_RATE_LIMIT_WINDOW_SECONDS = 60.0
    # EM-098: fixed session policy with a cheap PBKDF2 round count so login /
    # session tests stay fast and deterministic; the demo bootstrap account is
    # seeded by an explicit endpoint call in the tests, never implicitly.
    AUTH_SESSION_TTL_MINUTES = 240
    AUTH_IDLE_TIMEOUT_MINUTES = 30
    AUTH_MAX_FAILED_LOGINS = 3
    AUTH_LOCKOUT_MINUTES = 10
    AUTH_PBKDF2_ITERATIONS = 1000
    AUTH_MIN_PASSWORD_LENGTH = 8
    AUTH_DEMO_BOOTSTRAP_EMAIL = "demo.operator@embermind.test"
    AUTH_DEMO_BOOTSTRAP_PASSWORD = "test-demo-password"  # nosec B105
    # EM-099: enforcement stays OFF so the whole existing anonymous decision
    # surface keeps passing; the EM-099 tests flip it on their own settings stub.
    AUTHZ_ENFORCEMENT_ENABLED = False
    # EM-101: no implicit country scope so created accounts are global unless a
    # test passes one explicitly; the managed surface is otherwise always on.
    USER_MANAGEMENT_DEFAULT_COUNTRY = ""
    # EM-100: transport knobs default OFF in tests too (TLS is deployment/E12);
    # the conformance tests assert posture off and flip them on a local stub.
    SECURITY_TRUST_PROXY_SSL_HEADER = False
    SECURITY_SESSION_COOKIE_SECURE = False
    # EM-095: fixed base URL so example-client snippets are deterministic in tests.
    API_DOCS_BASE_URL = "http://testserver"
    # EM-093: deterministic CAP sender + language for template tests.
    INTEGRATION_CAP_SENDER = "it.embermind.test"
    INTEGRATION_ALERT_LANGUAGE = "tr"
    # EM-105: fixed notional border longitude so the border scenario dataset is
    # byte-deterministic across activation/replay assertions.
    SCENARIO_BORDER_LON = 28.85
    # EM-107: deterministic playback knobs (fixed speed/interval) so the frame
    # timeline and wall-clock schedule are stable across tests.
    PLAYBACK_DEFAULT_SPEED_FACTOR = 1.0
    PLAYBACK_MAX_SPEED_FACTOR = 8.0
    PLAYBACK_FRAME_INTERVAL_SECONDS = 2.0
    # EM-080: fixed map-interaction knobs so basemap/search/measurement tests are
    # deterministic regardless of the ambient environment.
    MAP_DEFAULT_BASEMAP = "street"
    MAP_SEARCH_MAX_RESULTS = 8
    MAP_MEASURE_MAX_POINTS = 100
    # EM-084: fixed field-view proximity knobs so the mobile projection tests are
    # deterministic regardless of the ambient environment.
    FIELD_VIEW_RADIUS_KM = 25.0
    FIELD_VIEW_MAX_ITEMS = 5
    # EM-108: fixed authored-scenario cap so editor tests are deterministic.
    SCENARIO_EDITOR_MAX_ITEMS = 50
    # EM-085: fixed accessibility knobs so the contract tests are deterministic.
    ACCESSIBILITY_DEFAULT_THEME = "dark"
    ACCESSIBILITY_REDUCED_MOTION = False


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
