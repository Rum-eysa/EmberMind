# Changelog

Tüm değişiklikleri bu dosyada dokümante ediyoruz.

## [Unreleased]

### Added
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
