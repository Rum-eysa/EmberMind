# Changelog

Tüm değişiklikleri bu dosyada dokümante ediyoruz.

## [Unreleased]

### Added
- EM-072: Operatör ana haritası ve yangın katmanları (`/ui`)
  - Leaflet tabanlı operatör arayüzü FastAPI tarafından sunulur (`src/static/operator_map.html`)
  - Altı açılıp kapanabilir GeoJSON katmanı: aktif yangınlar (uydu kümesi + olaylar),
    30/60/120 dk ufuk poligonları, yakıt sınıfı, sessiz bölgeler, müdahale kaynakları, yollar
  - Zaman kaydırıcısı ile ufuklar arasında gezinme (kümülatif gösterim seçeneği) + lejant
  - `GET /api/v1/map/layers` (katman kataloğu) ve `GET /api/v1/map/layers/{katman}`
    (GeoJSON; `horizon_minutes` ve `event_key` filtresi) endpoint'leri
  - Her katman yanıtında kaynak lisansı gereği `attribution` alanı (EM-013 ile tutarlı)
- EM-015: Rothermel tabanlı temel yangın yayılım tahmin motoru
  - Rothermel (1972) yüzey yayılım modeli + Albini (1976) düzeltmeleri, 13 standart
    USDA yakıt modeliyle (`src/services/spread.py`); girdiler: yangın konumu, rüzgâr,
    sıcaklık/nem (Van Wagner denge nemi), eğim/bakı ve yakıt sınıfı
  - Her ufuk (30/60/120 dk) için odak noktası ignition noktasında olan eliptik risk
    bölgesi poligonu (GeoJSON + WKT), yayılım hızı (m/dk) ve yayılım yönü (derece)
  - `POST /api/v1/spread/predict`, `GET /api/v1/spread/fuel-models`,
    `GET /api/v1/spread/forecasts?event_key=` endpoint'leri
  - Girdi çözümleme zinciri: açık istek > en yakın kayıtlı gözlem (hava/topo/yakıt)
    > deterministik varsayılan; sonuç sabit referans senaryoda tekrarlanabilir (birim test)
  - `SPREAD_HORIZON_MINUTES`, `SPREAD_POLYGON_VERTICES`, `SPREAD_MODEL_NAME`
    konfigürasyon değişkenleri
  - V007 migration: `fire_forecasts` tablosuna ufuk/yayılım kolonları
    (`horizon_minutes`, `rate_of_spread_m_per_min`, `spread_direction_deg`, `inputs_json`)
- EM-014: Yangın Hava İndeksi (FWI) ve kuraklık göstergesi
  - Kanonik Kanada FWI sistemi (Van Wagner & Pickett 1985) bölge bazında hesaplanır
    (FFMC/DMC/DC/ISI/BUI/FWI + günlük taşıma/zincirleme kod geçmişi)
  - `GET /api/v1/fwi/map`: bölge poligonları GeoJSON harita katmanı (risk renk lejantı)
  - `GET /api/v1/fwi/daily-summary`: yüksek FWI bölgeleri için günlük özet + kuraklık izleme
  - Kuraklık göstergesi Drought Code (DC) sınıflandırması ile üretilir
  - Hava durumu verisine yağış (`rain`) alanı eklendi (FWI girdisi)
  - `FWI_ZONE_SIZE_DEG`, `FWI_SYNC_INTERVAL_MINUTES` konfigürasyon değişkenleri
    ve günlük Celery beat görevi `compute_fire_weather_index`
  - V006 migration: `fire_weather_index` tablosu + `weather_data_points.rain`
- EM-013: Veri kaynakları lisans, atıf ve kota yönetimi
  - Her kaynak için lisans/atıf/kota tablosu (`src/services/data_governance.py` registry)
  - `GET /api/v1/data-sources`, `/attribution`, `/cache-plan` endpoint'leri
  - Tüm veri listesi yanıtlarına `attribution` alanı eklendi (arayüz atıf zorunluluğu)
  - `docs/DATA_SOURCES.md`: lisans tablosu + kota riskli kaynaklar için önbellek planı
- EM-012: VIIRS/MODIS çoklu uydu veri entegrasyonu
  - Farklı uydu ürünleri tek ortak şemada (`NormalizedFire`) birleştirilir
  - Her olayda uydu geçiş (algılama) ve yayın süresi arasındaki gecikme (`latency_minutes`) gösterilir
  - Uzamsal-zamansal örtüşen yinelenen tespitler tekilleştirilir (VIIRS > MODIS önceliği)
  - `FIRMS_SOURCES` ve `SATELLITE_DEDUP_TIME_WINDOW_MINUTES` konfigürasyon değişkenleri
  - V005 migration: tespit/gecikme/tekilleştirme alanları

### Fixed
- FWI rüzgâr birimi tutarsızlığı giderildi: hava durumu gözlemi `m/s` olarak
  saklanırken FWI denklemleri `km/h` bekliyordu; toplama (aggregation) sınırında
  `× 3.6` dönüşümü eklendi (yayılım motoru ile tutarlı, düşük rüzgârlı günlerde
  hafif düşük çıkan ISI/FWI değerleri düzeltildi)

## [1.0.0] - 2024-01-01

### Added
- İlk version yayınlandı
- NASA FIRMS veri entegrasyonu
- Hava durumu verisi entegrasyonu
- Yangın yayılımı tahmin modeli
- REST API endpoint'leri
- Web dashboard
- Operatör paneli

### Changed
- ...

### Fixed
- ...

### Security
- ...
