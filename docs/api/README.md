# REST API Dokümantasyonu

## Base URL
```
http://localhost:8000/api/v1
```

## Endpoints

### Sağlık Kontrolü
```
GET /health
```

Response:
```json
{
  "status": "healthy"
}
```

### Yangın Sahaları
```
GET /api/v1/fires
```

Query Parameters:
- `radius`: Arama yarıçapı (km)
- `confidence`: Güven seviyesi (0-100)
- `limit`: Sonuç sayısı

Her veri listesi yanıtında kaynak lisansı gereği `attribution` alanı döner.

### Veri Kaynakları Lisans / Atıf / Kota (EM-013)
```
GET /api/v1/data-sources              # lisans, atıf ve kota tablosu
GET /api/v1/data-sources/attribution  # arayüzde gösterilecek atıf metinleri
GET /api/v1/data-sources/cache-plan   # kota riskli kaynaklar için önbellek planı
```

Ayrıntılı tablo ve önbellek planı: [docs/DATA_SOURCES.md](../DATA_SOURCES.md)

### Yangın Hava İndeksi ve Kuraklık Göstergesi (EM-014)
```
GET  /api/v1/fwi                    # bölge bazlı FWI profilleri (?day=YYYY-MM-DD)
GET  /api/v1/fwi/map                # GeoJSON harita katmanı (risk renkleri + lejant)
GET  /api/v1/fwi/daily-summary      # yüksek FWI bölgeleri için günlük özet
POST /api/v1/fwi/compute            # belirtilen/güncel gün için FWI hesabı
```
Pilot bölge `FWI_ZONE_SIZE_DEG` (vars. 0.5°) karelerine bölünür; her bölge için
günlük FFMC/DMC/DC/ISI/BUI/FWI bileşenleri, risk sınıfı (`risk_category`) ve
kuraklık göstergesi (`drought_category`, Drought Code tabanlı) üretilir.
Hesap, bir önceki günün yakıt-nem kodlarını taşımalı (carry-over) zincirle yürür
ve Celery beat ile günde bir kez (`FWI_SYNC_INTERVAL_MINUTES`, vars. 1440 dk)
otomatik çalışır. Kaynak: OpenWeather (attribution yanıtlarda döner).

### Yangın Yayılım Tahmini (EM-015 + EM-016..EM-022)
```
POST /api/v1/spread/predict          # 30/60/120 dk risk bölgesi poligonları
GET  /api/v1/spread/fuel-models       # 13 standart USDA yakıt modeli kataloğu
GET  /api/v1/spread/forecasts         # bir olay için saklanan tahminler (?event_key=)
GET  /api/v1/spread/fuel-moisture     # 1h/10h/100h ölü yakıt nemi sınıfları (EM-019)
POST /api/v1/spread/uncertainty       # iyimser/beklenen/kötümser belirsizlik zarfı (EM-020)
POST /api/v1/spread/barriers          # doğal engel kaydı: su tam, yol/ırmak kısmi (EM-021)
GET  /api/v1/spread/barriers          # kayıtlı engeller listesi (EM-021)
DELETE /api/v1/spread/barriers/{key}  # engel kaldırma (EM-021)
POST /api/v1/spread/evaluate          # tahmin vs gerçek çevre: IoU/alan/varış hatası (EM-017)
GET  /api/v1/spread/metrics           # saklanan değerlendirme metrikleri (EM-017)
GET  /api/v1/spread/metrics/summary   # sürüm bazlı ortalama özet (EM-017)
GET  /api/v1/spread/trigger-status    # olay için debounce'lu tetikleme kararı (EM-018)
POST /api/v1/spread/trigger-sweep     # otomatik tetikleme taramasını elle çalıştır (EM-018)
POST /api/v1/spread/performance/benchmark  # optimizasyon öncesi/sonrası ölçüm + kalıcı kayıt (EM-022)
GET  /api/v1/spread/performance            # saklanan benchmark koşuları + önbellek istatistikleri (EM-022)
GET  /api/v1/spread/performance/profile    # cProfile sıcak fonksiyon raporu (EM-022)
```
Rothermel (1972) yüzey yayılım motoru; girdiler: `latitude`, `longitude`,
`wind_speed_kmh`, `wind_from_deg`, `air_temp_c`, `relative_humidity_pct`,
`fuel_moisture_pct`, `slope_deg`, `aspect_deg`, `fuel_model`. Girdi verilmezse
en yakın kayıtlı hava/topografya/yakıt gözlemi, o da yoksa deterministik
varsayılan kullanılır (`input_provenance` alanında kaynak belirtilir). Her ufuk
için odak noktası ignition noktasında olan eliptik risk bölgesi (GeoJSON + WKT),
yayılım hızı (`rate_of_spread_m_min`, m/dk) ve yönü (`spread_direction_deg`, °)
üretilir. `event_key` verilirse `FireForecast` satırlarına kalıcı yazılır.
Sabit bir referans senaryoda sonuç birim testlerle tekrarlanabilir.

Motor EM-016..EM-022 ile derinleşti: poligon köşe-bazlı **yakıt geçişine**
duyarlı (`FUEL_TRANSITION_ENABLED`), nem **ölü yakıt nemi** sınıflarından
koşullandırılır (EM-019), yeni olay/anlamlı girdi değişiminde **otomatik
tetiklenir** (EM-018, debounce'lu Celery taraması), **belirsizlik zarfı**
(rüzgâr ansambli) ve **doğal engel kırpması** (kara/deniz maskesi, EM-020/021)
uygulanır; girdi katmanı okumaları **önbellek + vektörleştirmeyle**
hızlandırılır (EM-022, `SPREAD_PERF_ENABLED`; 10 sn yeniden hesaplama hedefi
benchmark uçlarıyla kanıtlanır). Değerlendirme metrikleri (EM-017) sürüm
karşılaştırması için `spread_evaluation_metrics` tablosunda birikir (V010).

### Tarihsel Yangın Çevreleri (EM-011)
```
GET  /api/v1/historical-fires         # EFFIS içe aktarılan çevreler (yıl/ülke filtresi)
GET  /api/v1/historical-fires/dataset # kalibrasyon/validation bölünmüş dataset
POST /api/v1/historical-fires/import  # EFFIS'ten yıl bazlı içe aktarma
POST /api/v1/historical-fires/splits  # kalibrasyon/validation etiketlerini yenileme
```
Yayılım motorunun kalibrasyon ve validasyonunda kullanılan tarihsel
EFFIS çevreleri (`historical_fire_perimeters`, V004); her kayıt `split`
etiketiyle kalibrasyon veya validation tarafına ayrılır.

### Operatör Haritası ve Katmanları (EM-072)
```
GET /ui                              # Leaflet tabanlı operatör ana haritası
GET /api/v1/map/layers               # açılıp kapanabilir katman kataloğu
GET /api/v1/map/layers/{katman}      # GeoJSON FeatureCollection
```
Katmanlar (8): `fires` (aktif yangınlar: uydu kümeleri + olaylar), `forecasts`
(30/60/120 dk risk bölgesi poligonları), `uncertainty` (EM-020 iyimser/kötümser
belirsizlik bandı), `barriers` (EM-021 doğal engeller: su kütleleri ve
yavaşlatıcılar), `fuel` (yakıt sınıfı), `silent-regions`
(sessiz bölgeler), `resources` (müdahale kaynakları: ekip üsleri **ve** EM-103
koordinatör envanter varlıkları — `kind` alanıyla ayrılır), `roads` (yol ağı).
`forecasts` katmanı `?horizon_minutes=` ve `?event_key=` ile filtrelenebilir; arayüzdeki
**zaman kaydırıcısı** ile ufuklar arasında gezilir (kümülatif gösterim seçeneği ile).
Her yanıtta kaynak lisansı gereği `attribution` alanı döner (EM-013).

### Komutan Kapasite ve Risk Paneli (EM-073)
```
GET /panel                       # tek panel komuta arayüzü (koyu tema, 60 sn otomatik yenileme)
GET /api/v1/panel/capacity-risk  # panel beslemesi (?day=YYYY-MM-DD, vars. son FWI günü)
```
Panel tek ekranda: bölge **risk indeksi** (FWI) ve **eşik rengi** (CFS risk
sınıfı paleti), `RISK_PANEL_THRESHOLD` (vars. 30) değerine ulaşan ilk gün olarak
**ilk aşım zamanı** (bölge ve bölge geneli), **kapasite kırılımı** (ekip
türü ve müsaitlik bazlı müdahale üsleri, aktif yangın olayları, aktif yol
kapatmaları) ve **EM-103 kaynak envanteri** toplamı (`capacity.inventory`).
Operatör haritasındaki lejanttan `/panel`'e geçilir.

### Tasarım Sistemi ve Bileşen Kütüphanesi (EM-075)
```
GET /styleguide        # bileşen vitrini (renk/tipografi/boşluk + buton, kart, panel, rozet, tablo, form)
GET /static/tokens.css # tasarım belirteçleri (risk eşik paleti dahil)
GET /static/components.css # paylaşılan bileşen sınıfları (em-*)
```
Tüm arayüzler tek belirteç setini kullanır: `tokens.css` renk, tipografi ve
boşluk ölçeklerini tanımlar; **risk eşik renkleri** `fwi.py · RISK_COLORS` ile
birebir eşleşir (birim testiyle kilitli). **Açık/koyu tema** `data-theme`
niteliği ve `prefers-color-scheme` ile desteklenir; `/ui` ve `/panel` bu
sisteme bağlıdır, `/panel`'de tema anahtarı bulunur. `/static` yalnızca
beyaz-listedeki CSS dosyalarını sunar (keyfi dosya okuma yok).

### Kaynak Envanteri (EM-103)
```
GET    /inventory                       # koordinatör envanter ekranı (CRUD + CSV)
GET    /api/v1/resources                # envanter listesi (tür/durum/üs/ülke filtresi + kapasite toplamı)
POST   /api/v1/resources              # yeni ekip / helikopter / İHA kaydı
GET    /api/v1/resources/capacity     # tür bazında kapasite kırılımı
GET    /api/v1/resources/{key}        # tek kayıt
PUT    /api/v1/resources/{key}        # kısmi güncelleme
DELETE /api/v1/resources/{key}        # silme
POST   /api/v1/resources/import/csv   # ham CSV gövdesiyle toplu içe aktarma (upsert)
```
Koordinatör, müdahale varlıklarını (ekip, helikopter, İHA) konum, üs, ülke,
durum (`available` / `deployed` / `maintenance` / `out_of_service`) ve sayısal
kapasite ile yönetir; böylece komutan panelindeki kapasite hesabı güncel kalır.
Türkçe eşanlamlılar kabul edilir (ekip→crew, helikopter→helicopter, iha→uav,
müsait→available, görevde→deployed…). Bu envanter, yol ağı `crew_bases`
(rotalama başlangıçları) kayıtlarından **ayrı** bir koordinatör kaynağıdır.
CSV içe aktarma `resource_key` üzerinden upsert yapar; doğrulamadan geçen
satırlar işlenir, bozuk satırlar `errors` listesinde satır numarasıyla
raporlanır ve içe aktarma kesintisiz sürer. `python-multipart` bağımlılığı
olmadığından CSV, `UploadFile` yerine **ham istek gövdesi** (`text/csv`, UTF-8)
olarak okunur. Envanter varlıkları ayrıca `/ui` "Müdahale Kaynakları"
katmanında ve `/panel` kapasite kartında gösterilir (kapasite hesabı güncel kalır).

### Sentetik Veri Üreteci (EM-104)
```
GET    /api/v1/scenarios/presets                 # hazır senaryo ön ayarları
POST   /api/v1/scenarios/synthetic/generate      # tohumlu deterministik üretim (ops. kalıcı yazma)
GET    /api/v1/scenarios/synthetic/runs          # üretim denetim kayıtları (hash'li)
GET    /api/v1/scenarios/synthetic/runs/{key}    # tek kayıt + sentetik örnek satırlar
DELETE /api/v1/scenarios/synthetic/{tag}         # senaryo etiketine göre temizlik
```
Demo sunucusu, erişilemeyen verileri (iletişim kesintisi bölgeleri, rüzgâr
geçmişi, kapasite/kaynak dağılımı, yangın konumu) gerçekçi senaryolarla
üretir. Senaryo `seed` + yapılandırılabilir `config`/`preset` ile belirlenir;
**aynı tohum aynı sonucu** verir (dataset sha256 `result_hash` olarak denetim
kaydına yazılır). **Tüm sentetik kayıtlar** `synthetic: true`,
`synthetic_label` ("SENTETİK VERİ…") ve `SYN-` anahtar ön eki ile açıkça
etiketlenir; kalıcı yazımda `source="synthetic"`, not/reason alanlarında etiket
tekrarlanır. `persist=true` veriyi operasyonel tablolara yazar (olay, sessiz
bölge, hava noktası, üs + envanter varlığı) ve aynı tohumda tekrar çalışma
idempotent'tir; `DELETE` ile etiket bazlı geri alınabilir. Demo:
`python scripts/demo_api.py --seed 42 --preset firtina`.

## Error Codes

- `200`: Başarılı
- `400`: Hatalı istek
- `404`: Bulunamadı
- `500`: Sunucu hatası
