# Changelog

Tüm değişiklikleri bu dosyada dokümante ediyoruz.

## [Unreleased]

### Added
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
