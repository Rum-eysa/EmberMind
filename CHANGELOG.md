# Changelog

Tüm değişiklikleri bu dosyada dokümante ediyoruz.

## [Unreleased]

### Added
- EM-103: Kaynak envanteri CRUD ve CSV toplu içe aktarma (E11)
  - `SuppressionResource` modeli (`src/models/inventory.py`): ekip / helikopter /
    İHA varlıkları konum, üs, ülke, durum (`available`, `deployed`, `maintenance`,
    `out_of_service`) ve sayısal kapasite ile tutulur (V008 migration);
    yol ağı `crew_bases` (rotalama başlangıcı)ndan ayrı, koordinatör kaynağıdır
  - `GET/POST /api/v1/resources`, `GET/PUT/DELETE /api/v1/resources/{key}`:
    tür/durum/üs/ülke filtreli listeleme, doğrulamalı ekleme (yinelen key → 409),
    kısmi güncelleme ve silme; Türkçe eşanlamlılar kabul edilir
    (ekip→crew, helikopter→helicopter, iha→uav, müsait→available, görevde→deployed…)
  - `GET /api/v1/resources/capacity`: tür bazında toplam/müsait/görevde/
    kapasite toplamı — komutan panelindeki kapasite hesabı güncel kalır
  - `POST /api/v1/resources/import/csv`: ham CSV metni ile toplu içe aktarma;
    `resource_key` üzerinden upsert, satır bazlı hata toleransı (bozuk satır
    `errors` listesinde raporlanır, import devam eder), başlık eşanlamlıları
    (tur/tür, enlem, boylam, üs, ülke, durum, kapasite…)
- EM-075: Tasarım sistemi ve UI bileşen kütüphanesi (`/styleguide`)
  - Renk (risk eşik paleti dahil), tipografi ve boşluk belirteçleri
    `src/static/tokens.css` içinde CSS custom property olarak tanımlandı;
    risk renkleri `src/services/fwi.py · RISK_COLORS` ile birim testine bağlandı
  - Buton, kart, panel, rozet, tablo ve form bileşenleri
    `src/static/components.css` (`em-*` sınıfları); risk rozetleri her FWI
    sınıfı için ayrı varyant üretir
  - Açık/koyu tema: `data-theme` niteliği + `prefers-color-scheme` medya sorgusu;
    operatör haritası ve komutan paneli token'lara bağlandı, panele tema anahtarı eklendi
  - `GET /styleguide` (bileşen vitrini) ve beyaz-listeli `GET /static/{css}` sunumu
- EM-074: Operatör arayüzü wireframe ve kullanıcı akışları doküman seti
  - `docs/wireframes/`: ekran envanteri + API eşlemesi, ana harita / risk
    paneli / öneri paneli / what-if akışı wireframe'leri
  - Operatör ve saha akışları ayrı ayrı çizildi; her adımda hangi uç noktanın
    çağrıldığı tablolandı; canlı ekranlar mevcut API'ye, planlanan ekranlar
    `ÖNERİLEN API` sözleşmesine bağlandı
  - Ekip + en az bir alan uzmanı gözden geçirme protokolü ve bulgu/katılımcı
    kayıt formu (`03-review-checklist.md`)
- EM-073: Komutan kapasite ve risk paneli (`/panel`)
  - Tek panelde bölge **risk indeksi** (günlük FWI), **eşik rengi** (CFS risk
    sınıfı renkleri), bölge bazında **ilk aşım zamanı** ve **kapasite kırılımı**
    (ekip türü/müsaitlik bazlı üsler, aktif olaylar, aktif yol kapatmaları)
  - `GET /api/v1/panel/capacity-risk` (?day=YYYY-MM-DD) tek bakışta komuta
    görünümü; 60 sn'de bir kendini yenileyen koyu temalı komutan arayüzü
  - Operatör haritasından (`/ui`) paneline bağlantı; `RISK_PANEL_THRESHOLD`
    konfigürasyon değişkeni (vars. FWI 30)
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
