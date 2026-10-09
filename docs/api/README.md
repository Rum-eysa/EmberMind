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
GET  /api/v1/spread/recompute-status  # rüzgâr/konum/kapasite değişiminde yeniden hesaplama kararı (EM-057)
POST /api/v1/spread/recompute-sweep   # planı değişen olayları yeniden hesapla + "ne değişti?" özeti (EM-057)
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

**Dinamik otomatik yeniden hesaplama (EM-057).** Operatör eski plana göre
hareket etmesin diye sürücü durum — **rüzgâr**, **yangın konumu** ve **kapasite**
— anlamlı biçimde değiştiğinde plan (EM-018 yayılım taraması + EM-029 risk
pik bandı) otomatik yeniden hesaplanır. Son planın sürücü-durum anlık görüntüsü
durum deposu olarak append-only canlı beslemeye (EM-090, kaynak `auto_recompute`)
yazılır; yeni bir tablo/migration gerekmez ve Celery/API süreçleri ayrışır.
Rüzgâr/nem/sıcaklık eşikleri EM-018'den alınır; konum için
`AUTO_RECOMPUTE_POSITION_MOVE_KM` (haversine), kapasite için
`AUTO_RECOMPUTE_CAPACITY_CHANGE_PCT` (bağıl %) kullanılır; anti-flap debounce
EM-018 penceresini paylaşır. Her yeniden hesaplama beslemeye `Plan güncellendi: …`
başlıklı ve `Değişen: …` mesajlı tek bir `forecast` kaydı yazar; operatör haritası
bunu **değişen faktör etiketleriyle** gösterir. Celery beat `auto_recompute_plans`
(`AUTO_RECOMPUTE_ENABLED`, `AUTO_RECOMPUTE_INTERVAL_MINUTES`).

### Maruziyet — Tehdit Altındaki Yapılar (EM-023)
```
POST /api/v1/exposure/import   # OSM'den yerleşim + enerji hattı alımı (ops. bbox)
GET  /api/v1/exposure          # öncelik skoruna göre SIRALI tehdit listesi (?event_key=)
```
Komutan perspektifi: hangi köy, yol ve altyapı yangın yolunda ve ne zaman
etkilenecek? `import` OpenStreetMap'ten (Overpass) yerleşim (`settlement`) ve
enerji hattı (`power_line`) varlıklarını `exposed_assets` (V013) tablosuna
alır; yollar EM-011 `road_segments`'ten okunur. Analiz, her varlığı EM-015
ufuk poligonlarıyla **shapely** ile kesiştirir ve **ilk etkilenme zamanı
`T+dk`**'yı hesaplar: varlığa ulaşan en küçük ufuk bulunur, ardından kaydedilen
ufuk başına **yayılma hızı** ve ateş noktasına uzaklıkla iki ufuk arasında
**enterpolasyon** yapılır (ör. `T+47`); kovayı aşan uzaklıklar ilgili ufka
kırpılır. Her öğeye **`priority_score`** (0–100; etki zamanı + varlık kritikliği
+ nüfus log ölçek) atanır ve liste bu skora göre azalan sıralanır. Poligon
dışında kalan varlık listeye girmez. Yanıt: `earliest_impact_minutes`, `by_type`
ve `items`. Ölüçek tarafında adaylarda bbox ön-eleme + hazırlanmış geometri +
tablo parmak izine bağlı kısa ömürlü TTL önbellek kullanılır
(`EXPOSURE_CACHE_*`). `import` için bbox alanı `EXPOSURE_IMPORT_MAX_BBOX_AREA_DEG2`
aşılırsa **400**, öncelikli yerleşim sınıfları (`EXPOSURE_IMPORT_PRIORITY_PLACE_CLASSES`)
dışındaki isimsiz yerleşimler elenir, `EXPOSURE_IMPORT_MAX_ASSETS` üzerinde kesilir;
Overpass erişilemezse **502** döner. Aynı varlıklar haritada **`exposure`**
katmanı olarak da çizilir ve `?event_key=` ile filtrelenebilir (aşağıda).

### Canlı Güncelleme — WebSocket (EM-090)
```
WS   /ws/live?since=<id>             # olay/tahmin/uyarı akışını canlı iter
GET  /api/v1/live/updates?since=<id> # REST yedeği (aynı imleç semantiği)
```
Operatör, güncellemeleri sayfa yenilemeden alır. Değişiklikler `live_updates`
(V014) tablosunda **monoton bir akış** olarak tutulur (`id` = sıra numarası);
kaynak veritabanı olduğu için ayrı bir Celery sürecinin yazdığı güncelleme de
tüm bağlantılara ulaşır. Bağlantı kurulunca `since` imlecinden itibaren bir
**snapshot** çerçevesi (`{"type":"snapshot","last_id","count","updates"}`) gönderilir,
ardından kısa aralıklı yoklamayla (`LIVE_POLL_INTERVAL_SECONDS`) yeni değişiklikler
`{"type":"update", ...}` olarak itilir; boşta `{"type":"ping"}` keepalive gider
(`LIVE_HEARTBEAT_SECONDS`). Her öğe `kind` (`fire_event`/`forecast`/`alert`),
`event_key`, `title`/`message`, `payload` ve `source` taşır. **Bağlantı koparsa**
istemci son imleci koruyarak üstel geri çekilmeyle yeniden bağlanır ve
`?since=<id>` ile **kaçırılanları telafi** eder. Yayınma noktaları: manuel olay
ve FIRMS senkronu → `fire_event`, `spread/predict` → `forecast`, `fwi/compute`
(eşik üstü bölge varsa) → `alert`. Operatör haritası canlı durum rozeti, güncelleme
bildirimi ve aktif katmanların otomatik yeniden yüklenmesiyle bunu gösterir.

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
Katmanlar (10): `fires` (aktif yangınlar: uydu kümeleri + olaylar), `forecasts`
(30/60/120 dk risk bölgesi poligonları), `uncertainty` (EM-020 iyimser/kötümser
belirsizlik bandı), `barriers` (EM-021 doğal engeller: su kütleleri ve
yavaşlatıcılar), `fuel` (yakıt sınıfı), `silent-regions`
(sessiz bölgeler), `resources` (müdahale kaynakları: ekip üsleri **ve** EM-103
koordinatör envanter varlıkları — `kind` alanıyla ayrılır), `roads` (yol ağı),
`exposure` (EM-023 tehdit altındaki yerleşim/yol/altyapı; `first_impact_minutes`
mor renk kodlu ve `priority_score` ile sıralı), `positioning` (EM-052 önerilen
kaynak rotaları (LineString, `T+dk` ETA etiketli) + konuşlanma noktaları (Point)).
`forecasts`, `exposure` ve `positioning` katmanları `?event_key=` ile tek yangına filtrelenebilir;
`forecasts` ayrıca `?horizon_minutes=` destekler ve arayüzdeki **zaman kaydırıcısı**
ile ufuklar arasında gezilir (kümülatif gösterim seçeneği ile).
Her yanıtta kaynak lisansı gereği `attribution` alanı döner (EM-013).

#### Harita Etkileşimi — Altyapı, Arama ve Ölçüm (EM-080)
```
GET  /api/v1/map/config              # altlık kataloğu + arama/ölçüm sınırları
GET  /api/v1/map/search?q=           # yer adı VEYA "enlem, boylam" koordinat araması
POST /api/v1/map/measure/distance    # polilin boyunca büyük-daire mesafesi (km)
POST /api/v1/map/measure/area        # çokgen jeodezik alanı (ha / km²)
```
Üç salt-okunur operatör aracı; hepsi deterministik ve çevrimdışıdır:
`config` sokak/uydu/arazi altlıklarını (kutu URL'si + atıf + azami yakınlaştırma)
ve varsayılan altlığı (`MAP_DEFAULT_BASEMAP`) döner. `search` kodla gelen küratörlü
Ege gazetteer'ı üzerinde vurgu/harf-duyarsız olmayan eşleşme yapar; ham koordinat
sorgusu her zaman ilk `coordinate` sonucunu üretir (canlı jeokodlayıcıya gidilmez).
`measure/*` girdisi `[enlem, boylam]` noktalarıdır; mesafe en az 2, alan en az 3
nokta ister, azami `MAP_MEASURE_MAX_POINTS` köye ve aralık doğrulamasına tabidir
(ihlalde `422`). Kalıcılık yoktur (`persistence: none`).

#### Mobil/Tablet Saha Görünümü (EM-084)
```
GET  /api/v1/field-view                 # telefondan okunur görev kartı + yakın risk bölgesi
GET  /api/v1/field-view/config          # yarıçap/öğe sınırı + veri kaynakları
```
Saha ekip liderinin telefonda tek bakışta okuyacağı kompakt, **salt-okunur**
görünüm; iki mevcut motoru birleştirir (yeni tablo yok, `persistence: none`):
ekibin **EM-051 görev kartı(ları)** ve referes noktasına göre **en yakın EM-029
aktif risk bölge(leri)**. Sorgu parametreleri: `event_key` (bilinmeyen olay →
**404**), `resource_key` (kartları tek birime indirger), `latitude`/`longitude`
(“buradan” ölçüm merkezini elle verir). Merkez verilmezse ekibin ilk görev
kartının hedefi kullanılır; kart da yoksa görünüm **meşru biçimde boş** döner
(hata değil — arayüz boş durumunu çizer). `nearby_risks` büyük-daire mesafesiyle
artan sıralı, `FIELD_VIEW_RADIUS_KM` (vars. 25) yarıçapıyla süzülür ve
`FIELD_VIEW_MAX_ITEMS` (vars. 5) ile sınırlanır; her satır `distance_km`,
`bearing_deg` (kuzeyden 0–360°, çakışan noktada `null`), `peak_level` ve
`peak_risk_index` taşır. Arayüz `operator_map.html` **Saha Görünümü** panelidir;
`@media (max-width: 640px)` ile dar ekranda tam genişliğe çıkar.

### Proaktif Kaynak Konumlandırma (EM-052)
```
GET /api/v1/positioning/proposals   # bir olaya en yakın müsait kaynakların rota+ETA önerileri
```
`event_key` (zorunlu) ve `limit` (1..50) alır. Bir yangın olayı için **müsait**
ekip üsleri (`crew_bases`) + müdahale kaynaklarını (`suppression_resources`,
EM-103) toplar; her birini EM-011 yol ağı grafiği üzerinden olay konumuna
**kapanış-duyarlı en kısa süre** rotasıyla çizer ve **ETA**'ya göre sıralar.
Her öneri `deployment_point` (önerilen konuşlanma noktası), `route` (rota
LineString), `eta_minutes`, `distance_km` ve `delay_vs_open_minutes` taşır.
Öneriler **her istekte canlı** hesaplanır (kalıcı kayıt yok); yol ağı boşsa
**409**, olay bulunamazsa **404** döner. Harita gösterimi `positioning` katmanı
ve **Konuşlanma Önerileri** paneliyle yapılır (öneri seçilince harita odaklanır).

#### Kaynak Tipine Göre ETA — Kuş Uçuşu vs Yol Ağı (EM-049)
Aynı `GET /api/v1/positioning/proposals` ucu artık **seyahat modunu** ayırt eder:
her öneri `travel_mode` (`"air"` | `"road"`) taşır. **Hava** kaynakları
(helikopter/İHA) olaya **kuş uçuşu** uçar — ETA = `haversine_km(mesafe) /
POSITIONING_AIR_SPEED_KMH * 60` (vars. 220 km/sa); yol kapatmaları uçuşu
etkilemediği için hava önerileri her zaman `reachable=true` ve
`delay_vs_open_minutes=0` döner, rota iki noktalı düz çizgidir. **Kara**
ekipleri kapanış-duyarlı yol ağı rotasında kalır. Bu alan rota/konuşlanma
GeoJSON özelliklerinde de görünür; operatör haritasında **Hava/Kara** rozeti
çizilir.

### Öneri Kabul / Ret / Düzenleme (EM-047)
```
GET  /api/v1/recommendations/decisions/config   # aksiyonlar + durum sözlüğü
POST /api/v1/recommendations/decisions          # bir öneriye karar ver
GET  /api/v1/recommendations/decisions          # karar geçmişi (event_key/resource_key/action/limit)
GET  /api/v1/recommendations/decisions/{decision_key}  # tek karar (denetim kaydı)
```
Motor **önerir**, operatör **karar verir** (nihai karar operatörde). Üç aksiyon:
**`accept`** ve **`edit`** önerilen kaynağı `en_route` ("yolda") durumuna geçirir
(EM-031); `edit` ek olarak `arrival_minutes` gibi operatör değişikliklerini
uygulanır ve detail anlık görüntüsüne yazar. **`reject`** kaynağa dokunmaz ve
**isteğe bağlı** bir `reason` kaydeder (zorunlu değil). **Her** karar
`recommendation_decisions` tablosuna değiştirilemez bir **denetim kaydı** olarak
yazılır (öneri girdileri + önceki/sonraki kaynak durumu). Durum geçişleri
envanter servisini (`update_resource`) yeniden kullanır. Kaynak bulunamazsa
**404**, geçersiz `action` ise **400** döner. Operatör haritasındaki her öneri
satırında **Kabul / Düzenle / Reddet** düğmeleri bulunur.

### Öneri Gerekçesi / Açıklanabilirlik (EM-046)
```
GET /api/v1/recommendations/explain         # bir olayın sıralaması için "neden?" paneli
GET /api/v1/recommendations/explain/config  # açıklanabilirlik tanımı
```
Komutan öneriye **güvenip güvenmeyeceğine** karar vermek için **neden**
yapıldığını görmek ister. `explain`, EM-052 `build_proposals` çıktısını
**açıklar** (yeniden sıralamaz); dolayısıyla gerekçe haritanın gösterdiği
sayılarla çelişmez ve **canlı** hesaplanır (kayıt tutulmaz). Yanıtta:
- `proposals[]`: önerilenlerin her biri `rank` ve bir `why` gerekçe listesiyle
  (örn. "En kısa tahmini varış: T+X dk", "Aktif yol kapanışları +Y dk ekliyor")
- `rejected_alternatives[]`: **değerlendirilip önerilmeyen** her alternatif bir
  `reason` ile (izole/ulaşılamayan kaynak vs. daha uzun ETA)
- `context`: `ranking_metric` (kapanış-duyarlı ETA), `alternatives_evaluated`,
  `selected_limit` (top-N eşiği) ve `threshold_eta_minutes`
`event_key` (zorunlu) ve `limit` (1..50) alır; olay bulunamazsa **404**, yol ağı
boşsa **409** döner. Operatör haritasındaki her öneri satırında **Neden?**
düğmesi bu paneli satır altında açar.

### Öneri Etki Karşılaştırması (EM-048)
```
GET /api/v1/recommendations/impact         # uygulanırsa vs uygulanmazsa risk (ufuk bazında)
GET /api/v1/recommendations/impact/config  # panel tanımı
```
Komutan **kararın değerini** görmek ister. `impact`, EM-056 re-pricing motorunu
kullanır: yayılım **talebi sabit** tutulur, yalnızca bu olaya ayrılan EM-028
**kapasite** değiştirilir. *Uygulanırsa* = EM-052'nin önerdiği ulaşılabilir
müdahale kaynakları olaya ayrılır (tam etkin kapasite); *uygulanmazsa* = bu
kaynaklar general havuzda bekletilir ve olayın kapasitesi onların ha/saat
toplamı kadar azalır. **Canlı** ve **yalnızca tavsiye**dir — hiçbir kaynak
rezerve edilmez veya değiştirilmez. Yanıt:
- `side_by_side[]`: her ufuk için `if_not_applied` ve `if_applied` (kapasite,
  `gap_ha_h`, `risk_index`, `level`) + `risk_index_delta` (negatif = uygulamak
  riske düşürür) + `resolves_gap`
- `capacity`: `applied_ha_h` / `not_applied_ha_h` / `committed_ha_h`
- `committed_resources`: karşılaştırmaya konu önerilen kaynaklar (EM-049
  `travel_mode` dahil) ve `summary.decision_has_value`
`event_key` (zorunlu) alır; olay bulunamazsa **404**, yol ağı boşsa ya da
karşılaştırılacak yayılım tahmini yoksa **409** döner. Operatör haritasındaki
Konuşlanma Önerileri panelinde **Etki karşılaştırması** düğmesi tabloyu açar.

### Çifte Atama ve Kaynak Çakışma Önleme (EM-053)
```
POST /api/v1/recommendations/decisions            # kabul/düzenle — çakışmada 409
POST /api/v1/recommendations/decisions/release    # birimi müsaite al (available)
GET  /api/v1/recommendations/assignments          # aktif atamalar (kaynak×olay)
POST /api/v1/recommendations/assignments/release-completed  # biten olayları otomatik bırak
```
Koordinatör **aynı kaynağın iki yangına** atanmasını engellemek ister (gerçek
kapasite EM-028 doğru hesaplansın). EM-047 kabul/düzenle ucuna **çakışma
bekçisi** eklendi: bir kaynak başka bir olaya `en_route`/`deployed` olarak
**zaten atanmışsa**, farklı `event_key` ile kabul **`ConflictError`** döner ve
uç **409** (`detail.status="conflict"`) verir; aynı olaya tekrar kabul
**idempotent**tir. Atama durumu **ayrı bir tablo değil** — EM-047 denetim
kayıttından türetilir: bir birimin en yeni kararı `accept`/`edit` ise ve kaynak
hâlâ meşgulse o olaya bağlıdır; sonraki bir `release` bağı temizler.
- **Müsaite alma** `release_assignment`: kaynağı `available`'a çeker, planlanan
  varış ETA'sını temizler ve `release` denetim satırı yazar. Boş kaynakta
  no-op (`released:false`). `event_key` verilirse mevcut atamayla eşleşmeli.
- **Otomatik müsaite** `release_completed_assignments`: olay artık `active`
  değilse (contained/closed) ya da satırı yoksa, o olaya bağlı birimler
  otomatik `available` olur.
`…/decisions/config` artık `conflict_prevention` bloğunu taşır (yalnızca
`release` için kullanılır; `actions` üçlüsü **kabul/ret/düzenle** olarak kalır).
Operatör haritasındaki Konuşlanma panelinde **Atamalar** bölümü aktif atama
listesini, satır başına **Müsaite al** düğmesini ve "Biten olayları otomatik
müsaite al" işlemini sunar.

### Saat Dilimi, Birim ve Koordinat Standardizasyonu (EM-063)

Sınır ötesi operatör (TR/GR) için **durumsuz görüntleme** yardımcısıdır. Zaman
her zaman UTC saklanır/sorgulanır; bu uçlar onu operatörün yerel saatine çevirir,
WGS-84 koordinatını seçili formatta gösterir, rüzgâr yönünü derece + pusula
olarak okur ve **metrik** birim sistemini bildirir. Hiçbir şey kalıcılaştırılmaz;
tercihler her istekte gövdeden gelir (`persistence: none`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/display/config` | Varsayılan saat dilimi/koordinat formatı, desteklenen IANA bölgeleri, koordinat formatları ve metrik birim tanımı |
| `POST /api/v1/display/standardize` | `time`/`timezone`, `latitude`/`longitude`/`coordinate_format`, `wind_direction_deg`, `distance_km`/`area_ha`/`speed_kmh` alanlarından istenen blokları üretir; geçersiz bölge/format/koordinat 422 |

| Blok | Anahtarlar |
| --- | --- |
| `time` | `utc`, `local_iso`, `local_display`, `timezone`, `utc_offset`, `is_dst` |
| `coordinate` | `format`, `decimal`, `dms` (her ikisi de döner) + seçili `display` |
| `wind` | `degrees`, `compass` (16 yön), `compass_full` |
| `measures` | `distance_km` / `area_ha` / `speed_kmh` — `{value, unit, display}` |

Operatör haritasında **Görüntü standardizasyonu (EM-063)** paneli saat dilimi ve
koordinat formatını seçtirir; seçili biçimde yerel saat ve harita merkezi
koordinatını canlı gösterir.

### Dış Destek Erken Tahmini (EM-065)

Sınır ötesi koordinatör için **durumsuz erken uyarı**: ulusal kapasitenin (müsait
+ ETA'sı geçen yoldaki takviyeler) yayılım talebini ne zaman karşılayamayacağı,
açık **gerçekleşmeden önce** projekte edilir. EM-030/EM-033 kapasite-açığı zaman
çizelgesinin seri noktaları üzerinden olay başına ilk açık dakikası (`T+X`), tepe
açığı (ha/saat) ve bunu kapatacak tam takviye birimi sayısı (`≈ Y birim`)
hesaplanır; `EXTERNAL_SUPPORT_LEAD_TIME_MINUTES` kadar öncesine bir **talep-gönderme
son tarihi** verilir. Yeni tablo/migration yoktur (`persistence: none`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/external-support` | Her aktif olay için `first_shortfall_minute`, `peak_shortfall_ha_h`, `estimated_support_units`, `request_by_minute`, `message` + genel `summary`; `?event_key=` ile tek olay (bilinmeyen → 404) |
| `GET /api/v1/external-support/config` | `support_unit_ha_per_hour`, `lead_time_minutes`, desteklenen ufuklar |

Komuta panelinde **Dış Destek Erken Tahmini (EM-065)** kartı her olayın ilk açık
dakikasını ve gereken takviye birimini gösterir.

### Sınır Ötesi Ortak Durum (EM-066)

İki ülkeyi izleyen koordinatör için **tek ortak ekran**: her aktif olay bir
**pilot sınır boylamına** (`CROSSBORDER_BORDER_LONGITUDE`, varsayılan 26.5) göre
TR (doğu) veya GR (batı) ülkesine atanır ve ülke ülke toplanır — ülke başına
aktif yangınlar, **tepe risk bandı** (EM-029) ve **tahmini dış destek ihtiyacı**
(EM-065). **Veri paylaşım kapsamı ayarlanabilir**dır: `fire` / `risk` /
`support` alan gruplarının yalnızca seçilen alt kümesi yayımlanır, gerisi tamamen
gizlenir. Ülke bazlı *yetki* politikası EM-070'in konusudur. Yeni
tablo/migration yoktur (`persistence: none`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/crossborder/situation` | Ülke blokları (`country`, `label`, `event_count`, `peak_level`, `total_support_units`, olay satırları) + `shared_fields` + `summary`; `?fields=fire,risk` ile kapsam daraltma (geçersiz alan → 400) |
| `GET /api/v1/crossborder/config` | `border_longitude`, ülkeler, `shareable_fields`, `default_shared_fields` |

Komuta panelinde **Sınır Ötesi Durum (EM-066)** kartı, paylaşım kapsamı
kutularıyla (Yangın/Risk/Destek) ülke ülke ortak tabloyu canlı gösterir.

### Sınır Geçiş Projeksiyonu (EM-067)

Yangının **ülke sınırını geçme olasılığı ve süresi** deterministik geometriyle
hesaplanır (öğrenilen model değil): EM-015 baş yayılım yönü ile sınırın yönü
(TR olayları için batı 270°, GR için doğu 90°) arasındaki açının kosinüsü
olasılığı verir; geçiş süresi = merkezin sınır boylamına uzaklığı (cos-enlem ×
km/derece) ÷ (baş yayılım hızı × bu pay). Durgun/yassı yangın dairesel büyüdüğü
için pay 1.0'dır; baş sınırın aksi yönünde dönükse geçiş öngörülmez. Pilot
sınır boylamı EM-066 ile **ortaktır**. Öngörü, kayıtlı yayılım tahminlerinden
canlı türetilir; yeni tablo/migration yoktur (`persistence: none`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/crossborder/spread` | Her aktif olay için `country`/`target_country`, `distance_km`, `likelihood` + `likelihood_level` (yok/düşük/orta/yüksek), `crossing_minutes`, `within_forecast_window`, `message` + en erken geçişi bildiren `summary` |

Komuta panelinde **Sınır Geçiş Projeksiyonu (EM-067)** kartı olay başına
geçiş yönünü, olasılık bandını ve `T+dk` tahmini geçiş zamanını gösterir.

### Çok Dilli Arayüz (EM-068)

Arayüz **metinleri** (başlık, kart başlıkları, tablo etiketleri, butonlar ve
sabit kaynak/risk-bandı enum'ları) koda derlenmiş bir **i18n mesaj
kataloğundan** çözülür; HTML içine gömülü değildir. Kabul kriteri gereği **TR**
ve **EN** tam anahtar kümesini taşır, **EL** çekirdek ekranları kapsar; eksik
anahtar önce **EN** köprü diline, sonra ham anahtara düşer (boş render olmaz).
`normalize_language` bölgesel etiketleri (tr-TR, el-GR) desteklenen koda
indirger ve bilinmeyen dili reddeder. Bu **metin** katmanıdır; sayı/saat/
koordinat *biçimlendirme* katmanı EM-063'tür. Katalog derlenmiş olduğundan ve
seçilen dil yalnız operatörün tarayıcısında saklandığından yeni tablo yoktur
(`persistence: none`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/i18n/messages[?lang=tr|en|el]` | İstenen dil için tam mesaj kataloğu + `language`, `fallback_language`, dil başına `coverage` (bilinmeyen dil → 400) |
| `GET /api/v1/i18n/config` | Desteklenen diller (kod + etiket + anahtar sayıları), varsayılan ve köprü dil |

Komuta panelindeki **dil seçici (TR/EN/EL)**, `data-i18n` etiketli tüm arayüz
kabuğunu, enum etiketlerini ve `son güncelleme` satırını yüklenen kataloğa göre
anında çevirir; tercih localStorage'da saklanır.

### Ülke Bazlı Yetki ve Veri Paylaşım Politikası (EM-070)

EM-066'nın ertelediği **yetki katmanı**: her sahibi ülke, kendi verisinin hangi
alan gruplarının (`fire`/`risk`/`support`) karşı ülkeye geçeceğine ülke ve rol
kapsamına göre kalıcı olarak karar verir. Çözüm önceliği **adlı rol → ülke
varsayılanı (`*`) → yapılandırılmış varsayılan** (`SHARE_POLICY_DEFAULT_FIELDS`)
şeklindedir; sonuç hangi katmandan geldiyse `source` rozetiyle döner. Her
değişiklik `country_share_policy` tablosuna **ek-yazılımlı** (append-only) yeni
bir satır olarak, önceki değeri `previous_shared_fields` ile birlikte yazılır —
en yeni satır geçerli politikadır, tüm dizi denetim kaydıdır. Boş seçim yasaldır
(hiçbir şey paylaşma); tanımsız alan veya ülke `400` ile reddedilir. EM-066'nın
istek bazlı `?fields=` düğmesi gerileme olmaması için ayrı ve dokunulmadan
kalmıştır.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/share-policy` | Her ülke için `*` + adlı rollerin geçerli politikası, `source` ve `explicit` bayrağı (matris) |
| `GET /api/v1/share-policy/preview[?country=TR&role=…]` | Karşı ülkenin tam olarak ne göreceği: `shared_fields`, `denied_fields`, `message` (yazmaz) |
| `POST /api/v1/share-policy` | Ülke/rol için paylaşılan alan gruplarını kaydet (denetim satırı ekler; geçersiz → 400) |
| `GET /api/v1/share-policy/audit[?country=&role=&limit=]` | Politika değişiklik geçmişi (en yeni önce), `previous_shared_fields` zinciriyle |

Komuta panelindeki **Veri Paylaşım Politikası (EM-070)** kartı ülke/rol matrisini
kaynak rozetiyle listeler, ülke/rol seçildikçe canlı önizleme gösterir ve
yöneticinin `fire`/`risk`/`support` seçip kaydedtiği bir form sunar.

### Ortak Sınır Ötesi Erken Uyarı Bildirimi (EM-069)

EM-067 sınır geçiş projeksiyonunu **koordinasyon eylemine** dönüştürür: bir
yangının sınır geçiş olasılığı ve süresi anlaşılan eşikleri
(`CROSSBORDER_NOTIFY_MIN_LIKELIHOOD`, `CROSSBORDER_NOTIFY_WINDOW_MINUTES`) aştığında,
karşı ülke koordinasyon birimine **önceden tanımlı kanaldan** (TR: MOBİL,
GR: Genel Sekreterlik) bildirim düzenlenir ve `crossborder_notification`
tablosuna kalıcı yazılır. Tetikleme **kenar tabanlıdır**: olay+hedef başına yalnız
bir **açık** bildirim bulunur (yeniden hesaplama spamlamaz); geçiş artık
öngörülmediğinde açık bildirim otomatik **çözülen**e geçer. Bildirim kanala
kuyruğa alınarak kaydedilir — canlı ağ çağrısı mock edilmez (salt `persistence:
crossborder_notification`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/crossborder/notifications[?event_key=&target=&status=&limit=]` | Gönderilen erken uyarı kayıtları (en yeni önce) |
| `GET /api/v1/crossborder/notification-status` | Eşiği aşan geçişler + her biri için bildirilip bildirilmediği (`notified`) |
| `POST /api/v1/crossborder/notifications/sweep` | Tüm aktif geçişlerde kenar-tetiklemeli gönderim + otomatik çözim |
| `POST /api/v1/crossborder/notifications?event_key=&target_country=` | Tek olay için bildirim düzenle (varsa yeniden kullan; bilinmeyen ülke → 400) |
| `GET /api/v1/crossborder/notifications/config` | Eşikler, yaşam döngüsü ve önceden tanımlı kanallar |

Komuta panelindeki **Ortak Erken Uyarı Bildirimi (EM-069)** kartı eşik aşan
geçişleri yön/olasılık/geçiş süresiyle listeler, bildirildi/bekliyor rozetini
gösterir ve **Tara ve bildir** eylemiyle süpürmeyi çalıştırır.

### Dış Destek Talebi Taslağı Üretme (EM-071)

EM-065 erken tahminini **somut bir talebe** dönüştürür: koordinatör, boş bir
sayfaya değil hazır bir taslağa başlar. Servis olay başına **ihtiyacı**
(`estimated_support_units`), **zamanı** (ilk açık / talep son dakika) ve
**konumu** (koordinatlar, EM-063 standart biçimleyicisi) EM-065'ten okur; bu
üçünden **otomatik tek satır özet** ve çok satırlı, **düzenlenebilir** bir metin
gövdesi besteler. Taslak **EM-068 i18n** yereliyle TR/EN/EL işlenir
(`normalize_language`; bilinmeyen dil → 400, tanımsız olay → 404). Açık
öngörülmeyen olay da "yeterli" notlu bir taslağa dönüşür. **Kopyala / PDF**
operatör tarafındadır (metin alanı + panoya kopyala + gizli iframe yazdır);
servis durumludur ve hiçbir şey yazmaz (`persistence: none`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/support-request-draft?event_key=[&lang=tr|en|el]` | Bir olay için düzenlenebilir talep taslağı: `summary` (otomatik özet) + `draft_text` + `language` |
| `GET /api/v1/support-request-draft/events` | Taslak seçici için aktif olaylar (öngörülen açık/birim) + önerilen olay |
| `GET /api/v1/support-request-draft/config` | Desteklenen diller, varsayılan dil, `editable` ve dışa aktarım biçimleri (`text`, `pdf`) |

Komuta panelindeki **Dış Destek Talebi Taslağı (EM-071)** kartı olay seçtirir,
güncel arayüz dilinde taslağı üretir, metin alanını düzenletir ve **Kopyala** /
**PDF · Yazdır** düğmeleriyle talebi dışa aktarır.

### Vardiya Devri Notları / Devir Özeti (EM-089)

Canlı akış (EM-090), kabul edilen öneriler (EM-047) ve olay zaman çizelgesi
(EM-081) makine üretimidir; operatörün vardiyayı devrederken iletmek istediği
serbest metin bilgiyi yazabileceği kalıcı bir yüzey yoktu. Bu uçlar olaya
**serbest metin not** ekler, notları listeler/siler ve **tek tıkla vardiya devri
özeti** üretir. Özet okuma zamanıdır: aktif olay kartlarını (EM-082 konuşlu
kadro + çakışma sayımı) operatör notlarıyla EM-081'in kronolojik akışında
birleştirir; notlar `operator_note` kategorisiyle akışa görünür şekilde katılır
(EM-081'in kendi kategori kümesi değişmez). Yalnızca `event_notes` kalıcıdır.
Boş not→400, tanınmayan olay→404.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/shift-handover` | Tek tık devir özeti (olay kartları + olay/not akışı + çakışma sayımı); `event_key` ile tek olaya kapsamlanır |
| `GET /api/v1/shift-handover/notes` | Notlar yeniden eskiye; `event_key` filtresi ve `limit` (`SHIFT_HANDOVER_MAX_NOTES`'a kırpık) |
| `POST /api/v1/shift-handover/notes` | Olaya serbest metin not ekler (`event_key`/`body`/`author`); boş→400, tanınmayan olay→404 |
| `GET /api/v1/shift-handover/notes/{id}` | Tek notu getirir (yoksa 404) |
| `DELETE /api/v1/shift-handover/notes/{id}` | Notu siler (yoksa 404) |
| `GET /api/v1/shift-handover/config` | Not kategorisi, kaynaklar ve sayfa sınırı |

### Kullanıcı Ayarları / Tercih Profili (EM-088)

Operatörün **dil**, **tema**, **saat dilimi** ve **koordinat biçimi**
tercihlerini tarayıcıya hapseden dağınık durum (EM-068 dili yalnız
`localStorage`'da, EM-063 gösterimi istek başına türetir; ikisi de
`persistence: none`) yerine bu tercihler **tek bir operatör profilinde**
sunucu tarafında saklanır. Sayfa yenilense ya da başka bir iş istasyonundan
açılsa da seçim korunur; değişiklik **anında uygulanır** ve tek tıkla
**varsayılana dönülür**. Kayıtlı satır yoksa okuma, ayarlardan türetilen
varsayılanı `source: settings_default` ile **yazmadan** döner; ilk `PUT` satırı
oluşturur. Her alan sistemin zaten tanıdığı değer kümesine karşı doğrulanır
(dil EM-068 katalogu, saat dilimi/koordinat EM-063, tema `dark|light`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/preferences` | Kayıtlı operatör profili; satır yoksa ayar varsayılanları (`source: settings_default`) |
| `PUT /api/v1/preferences` | Profil alanlarının herhangi bir alt kümesini doğrula ve kalıcı yaz (kısmi güncelleme); geçersiz değer→400 |
| `DELETE /api/v1/preferences` | Kayıtlı profili sil; sonraki okuma tekrar `settings_default` döner |
| `GET /api/v1/preferences/config` | İzin verilen değer kümeleri, ayarlardan türetilen varsayılanlar ve sabit anahtar |

### Durum Raporu / SITREP (EM-087)

Komutanın üst makama ve karşı ülkeye ileteceği **tek sayfalık** durum özeti.
Aktif yangınları, EM-029 yayılım tahmini + risk indeksini, en sıcak olay için
EM-052 konuşlanma önerilerini, rapor **zaman damgası**ını ve **sentetik veri
rozetini** tek yüzeyde derler (okuma zamanı projeksiyonu; model/migration yok).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/sitrep[?event_key=]` | Tüm aktif yangınların (veya tek olayın) tek sayfalık raporu; `sections`, `fires`, `forecast`, `risk_index`, `recommendations`, `synthetic`, `generated_at` |
| `GET /api/v1/sitrep/config` | Bölüm listesi, sözlükler, dışa aktarma biçimleri (`pdf`/`print`), rozet metni, limitler |

Öneri bölümü yol ağı/müsait kaynak yoksa hata vermek yerine `available:false`
+ gerekçeyle **zarifçe düşer**; rapor her durumda üretilebilir. Operatör
haritasındaki **Durum Raporu (EM-087)** paneli önizlemeyi gösterir ve **PDF /
Yazdır** düğmesiyle tek sayfalık biçimli dökümü gizli iframe üzerinden yazar.

### Bildirim Merkezi ve Sesli Uyarı (EM-086)

Operatör, canlı akışa (EM-032/EM-090) düşen risk uyarılarının hangilerini
gördüğünü/onayladığını ayırt etmek, kritik bir uyarıyı **onaylayana kadar**
elinde tutmak ve sesli alarmı **seviyeye göre** ayarlamak ister. Uyarı içeriği
`live_updates` içinde kalmaya devam eder; bu merkeziyete yalnızca elle tutma
durumu eklenir: `notification_states` (uyarı başına okundu/onaylandı) ve
`notification_sound_settings` (operatör geneli tek satır: açık/kapalı + çalacağı
en düşük bant). Kritik bandlar (`kritik-yakin`/`kritik`) yalnızca **onayla** ile
düşer; diğerleri okununca düşer. Özet sayaçları her zaman tüm pencereyi anlatır.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/notifications[?only_active=]` | Canlı akıştaki uyarılar, okundu/onaylandı durumu ve sesli ayarla birlikte (en yeniden eskiye) |
| `GET /api/v1/notifications/config` | Seviye merdiveni, onay gerektiren bandlar, varsayılan sesli ayar ve `max_alerts` |
| `GET /api/v1/notifications/sound` | Geçerli sesli alarm yaplandırması (yoksa ayarlardan tohumlanır) |
| `PUT /api/v1/notifications/sound` | Sesli alarmı aç/kapat ve/veya en düşük çalma bandını ayarla |
| `POST /api/v1/notifications/{id}/read` | Tek bir uyarıyı okundu işaretle |
| `POST /api/v1/notifications/{id}/acknowledge` | Uyarıyı onayla (kritik sabitlemeyi yalnızca bu çözer) |
| `POST /api/v1/notifications/read-all` | Penceredeki tüm uyarıları okundu işaretle (kritikler yine de onay bekler) |

Operatör haritasındaki **Bildirimler (EM-086)** paneli bu uçları kullanır:
uyarı satırlarında *Okundu işaretle* / *Onayla* düğmeleri ve üstte sesli uyarı
aç/kapa onay kutusu ile en-düşük-bant seçici.

### Salt Okunur Belediye Görünümü (EM-083)

Belediye yöneticisi, operatör konsolunun karar kontrollerinde kaybolmadan
**bölgesinin durumunu** sade, yalnızca izleme amaçlı bir ekranla izlemek ister.
Görünüm, ayarlanabilir bir bölge koordinat kutusuna (varsayılan: pilot bölge)
kapsamlanan **salt okuma zamanı projeksiyonudur** (yeni tablo/göç yok,
`persistence: none`): kutu içindeki aktif `fire_events` acilden eskiye sıralı ve
yalnızca sade çekirdek alanlarla, tek bir `headline` durumu ve **yerel vs havuz**
kaynak ayrımıyla (`suppression_resources` durumları) döner. Sınır kapalı (dahil)
aralıktır.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/municipality-view[?severity=]` | Bölge içi aktif yangınlar, şiddet histogramı, `headline` durumu ve yerel/havuz kapasite özeti |
| `GET /api/v1/municipality-view/config` | Bölge kutusu, şiddet/durum taksonomisi, kaynaklar ve bu görünümde **gizlenen** operatör kontrolleri |

Yalnızca operatöre ait affordanslar (öneriler, karar eylemleri, what-if, sevk)
**bilinçli olarak** düşürülür ve `omitted_operator_controls` listesinde adlandırılır.
`?severity=` yalnızca listeyi daraltır; `headline` ve şiddet sayıları her zaman
**bölge-geneli** kalır, tanınmayan bir şiddet kodu sessizce filtre olarak
uygulanmaz. Operatör haritasındaki **Belediye (EM-083)** paneli bu sadeleştirilmiş,
salt okunur durumu gösterir.

### Çoklu Yangın Yönetimi (EM-082)

Koordinatör **eş zamanlı birden çok yangını** izlemek ve sınırlı kaynak
havuzunu yangınlar arasında dengeli dağıtmak ister. Envanter, üç mevcut kaynağı
birleştiren **salt okuma zamanı projeksiyonudur** (yeni tablo/göç yok,
`persistence: none`): aktif `fire_events`, `suppression_resources` durumları ve
EM-047/EM-053 karar denetim kaydı. Her aktif yangına konuşlanmış birim, EM-053
çift-korumasıyla aynı kurala göre belirlenir: birim hâlâ `en_route`/`deployed`
ve en yeni denetim satırı `accept`/`edit`.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/multi-fire[?event_key=]` | Aktif yangın + kadro envanteri, havuz toplamları ve çapraz-yangın çakışma uyarıları |
| `GET /api/v1/multi-fire/config` | Şiddet/durum taksonomisi, çakışma türleri, kaynaklar ve `max_events` sınırı |

Üç deterministik **çakışma** kovası döner: `orphaned_units` (meşgul görünen ama
atandığı olay artık aktif olmayan birim → serbest bırakılmalı), `contended_bases`
(aynı üs birden çok aktif yangına kaynak veriyor → havuz paylaşımlı),
`understaffed_critical` (yüksek/kritik aktif yangına hiç kaynak konuşlanmamış →
havuzu dengele). `event_key` ile yalnızca `events` listesi kapsamlanır; çakışma
taraması her zaman **küreseldir** (paylaşılan üs / öksüz birim tüm havuzu
ilgilendirir). Operatör haritasındaki **Çoklu Yangın (EM-082)** paneli aktif
yangınları şiddet sırasıyla ve çakışma uyarılarıyla listeler.

### Olay Zaman Çizelgesi (EM-081)

Vardiya devri için operatör, olan her şeyi **tek kronolojik akışta** görmek
ister. Akış iki mevcut kaynağı birleştiren **salt okuma zamanı projeksiyonudur**
(yeni tablo/göç yok, `persistence: none`): canlı değişim beslemesi (EM-090 —
`fire_event`/`forecast`/`alert`) ve operatörün **kabul ettiği** önerilerin
_denetim kayıtları_ (EM-047 — `accept`/`edit`). `reject`/`release` kabul
sayılmadığı için akışa girmez.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/event-timeline[?event_key=&category=&limit=]` | Yeniden eskiye sıralı birleşik olay akışı; `category_counts` + filtre üst verisi |
| `GET /api/v1/event-timeline/config` | Kategoriler/etiketler, kaynaklar ve sıralama sözleşmesi |

Her girdi sabit bir `category` (+ Türkçe `category_label`), `event_key`, UTC
`at` damgası ve `ref` (kaynak tablo + id) taşır. Sıralama **yeniden eskiye**;
zaman eşitliği **kaynak-sırası + id** ile deterministik bozulur. Bilinmeyen
`category` **sessizce yutulmaz**: `filter` `null`, `requested_category` korunur,
süzülmemiş akış gelir. Operatör haritasındaki **Zaman Çizelgesi (EM-081)**
paneli kategoriyi süzer ve renk kodlu satırlarla gösterir.

### Panel Durum Kataloğu ve Bağlantı Bandı (EM-079)

Panellerde **yükleme / boş / hata** durumları ile **bağlantı-kesildi** bandı tek
bir salt okunur **katalogdan** gelir (`persistence: none`, yeni tablo/göç yok).
Her panel anahtarı için `title/loading/empty/error/error_action` Türkçe metinleri
tanımlıdır; `error_action` **her zaman yapılabilir bir fiil** içerir (deneyin /
kontrol edin / seçin / gözden geçirin / sıfırlayın) — hata mesajı hem **ne
olduğunu** hem **ne yapılacağını** söyler.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/ui-states` | Tüm panel durumları + `connection` bandı + dil/üretim üst verisi |
| `GET /api/v1/ui-states/panel/{panel_key}` | Tek panel durumu; bilinmeyen anahtar **404** |

Operatör haritasındaki **`#conn-lost` bandı**, canlı akış WebSocket `onclose`
veya REST yoklama `catch` ile görünür olur, `onopen`/`ok` ile kalkar; «Şimdi
yeniden dene» düğmesi bağlantıyı yeniler. Sessiz bölge / etki / konuşlanma
panelleri yükleme iskeleti (`.skel`), boş durum ve hata (`.panel-err`) metinlerini
katalogdan çeker.

### Sessiz Bölge Güven Paneli (EM-078)

Operatör, **sessiz bölgelerin** (kayıt dışı/görüş açıksız bölgeler) hangilerine
güvenebileceğini ayırt etmek ister. Panel mevcut `silent_regions` verisini bir
**okuma zamanı projeksiyonuyla** puanlar (yeni kolon/göç yok, `persistence:
none`): sınır kutusu içindeki her **aktif yangın** ağır bir çelişki cezası
düşürür; en yakın aktif yangının centroid'a uzaklığına göre **yakınlık cezası**
(`PROXIMITY_FAR_KM`'ye kadar doğrusal) eklenir; sonuç `[0,1]`'e kırpılıp
**yüksek/orta/düşük** bantlarına ayrılır. Liste güven azalan sıralanır.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/silent-zones[?confidence=high|moderate|low]` | Güven dereceli, sıralı sessiz bölge listesi; `band_counts` + eşikler; bant filtresi |
| `GET /api/v1/silent-zones/config` | Bantlar/kesim noktaları ve türetme kuralları |

Bilinmeyen `confidence` değeri **sessizce yutulmaz**: `filter` `null` döner,
`requested_filter` değeri korunur ve süzülmamış liste gelir. Operatör haritasındaki
**Sessiz Bölgeler (EM-078)** paneli bandı süzer, satıra tıklanınca **harita senkron**
bölgenin sınır kutusuna odaklanır ve vurgu dikdörtgenini çizer.

### Kabul/Ret Geri Bildirim Döngüsü (EM-054)

Operatörün EM-047 karar denetimi (kabul/ret/düzenleme) **salt okunur** bir
geri bildirim raporuna dönüştürülür: genel kabul/ret/düzenleme oranları, kaynak
tipi bazında kırılım, en çok reddedilen tipler, ret gerekçesi sayımları ve bu
sinyallerden damıtılan **iyileştirme fikirleri**. EM-053 `release` satırları
analizden **hariçtir** (yaşam döngüsü olayı, karar sinyali değildir). Rapor yeni
bir tablo gerektirmez; tümü mevcut denetimden canlı türetilir (`persistence: none`).

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/recommendations/feedback` | Kabul/ret analizi; isteğe bağlı `event_key` ile tek olaya daraltılır (varsayılan: tümü) |
| `GET /api/v1/recommendations/feedback/config` | Tanımlayıcı: hangi aksiyonları ölçer, `release` hariç, hangi metrikleri üretir |

Operatör haritasında **Kabul/ret geri bildirimi (EM-054)** paneli, bir öneri
kararı verildikten sonra otomatik tazelenir. Eşikler: bir tipin ret oranı
`_REJECT_RATE_ALERT` (%50) üzerine çıkarsa "uygunluk/önceliklendirmeyi gözden
geçir" fikri üretilir; genel kabul oranı `%50` altında ve yeterli örneklem varsa
"motor beklentiyi karşılamıyor" uyarısı düşer.

### Kaynak Önerisi Motoru — Beklenen Risk Düşüşü (EM-045)

Öneri motoru, sıralı konuşlanma listesinin **her satırına** bir `expected_risk_reduction`
değeri ekler: bu tek kaynak olaya tahsis edildiğinde olayın **tepe EM-029 risk
indeksi** rezervde tutulmasına göre ne kadar iner. Metrik **varış süresine
duyarlıdır** — birim yalnızca yetişebildiği ufukta (ETA ≤ ufuk) kapasiteye sayılır;
yavaş/uzak kaynak düşük, hızlı/yakın kaynak yüksek skor alır. Ulaşılamayan
kaynaklar ve ekip üssü gibi öneri olmayan satırlar `None` taşır.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/positioning/proposals` | Her öneri `expected_risk_reduction` taşır; yanıtta `value_metric` (alan adı + atıf + `persistence: none`) bildirilir |

`build_proposals` **saf bırakılır**; zenginleştirme yalnızca bu uçta ek bir katman
olarak uygulanır (`src/services/recommendation_engine.py`), böylece EM-046/EM-048/
EM-050/EM-052 sıralama sözleşmesi bozulmaz. Hesap canlı ve salt danışmanlıktır;
hiçbir kaynak tutulmaz/değiştirilmez/kaydedilmez.

### Kısıt Tabanlı Optimizasyon (EM-050)

Öneriler, komutana ulaşmadan önce **kayıtlı işletme limitlerine** göre
elenir: `range_km` (menzil, tek yön km), `shift_minutes` (mesai/yakıt dk),
`night_capable` (gece yetkisi — varış UTC 20-05 penceresine denk gelir ve
yetki yoksa elenir) ve aktif **yol kapanmaları** nedeniyle ulaşılamayan
kaynaklar. Limitler `suppression_resources` ve `crew_bases` üzerinde
**opsiyoneldir** (V022, yalnızca ADD); `NULL` = bilinmiyor/sınırsız, yani
limit bildirmemiş envanter tam eskisi gibi önerilir.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/positioning/proposals` | Kısıt modunda çalışır: ihlal eden kaynak öneri listesinde **yer almaz**; yanıtta `rejected` (kısıt adları + gerekçe + ETA/mesafe) ve `rejected_count` taşır |
| `GET /api/v1/positioning/constraints` | Kısıt tanımlayıcısı: alan anlamları, kaynak sayısı limiti (`POSITIONING_MAX_PROPOSALS`), gece yasağı durumu |
| `POST/PUT /api/v1/resources` | Yeni limit alanlarını doğrular (pozitif sayı, üç durumlu gece bayrağı: belirtilmemiş/var/yok) |

Geriye dönük sözleşme: EM-046 açıklama ve harita katmanı çağrıları elenen
toplayıcısı vermediği için eski sıralama sözleşmesi **birebir korunur**; bu
modda ihlaller önerinin `constraint_violations` / `constraint_reason`
alanlarında işaretlenir. Gece yasağı `POSITIONING_NIGHT_BAN_ENABLED=0` ile
kapatılabilir. Operatör haritasında Konuşlanma paneli **"Kısıt nedeniyle
elenen öneriler"** bloğunu, envanter formu Menzil/Mesai/Gece alanlarını gösterir.

### Saha Görev Kartları (EM-051)

Kabul edilen bir öneri saha ekibi için kısa bir **görev kartına** dönüştürülür:
**hedef** (olay adı + enlem/boylam), **varış** (`eta_minutes`, planlanan
`arrival_eta`, yol kipi ve mesafe) ve **risk notu** (EM-029 tepe bandı: seviye,
indeks, ufuk). Kabul edilen birimler `en_route` olduğu için canlı öneri
listesinden düşer; kart bu yüzden **EM-047 denetim kaydındaki anlık
görüntüden** yeniden kurulur — yeni kalıcılık yoktur.

| Uç | Açıklama |
| --- | --- |
| `GET /api/v1/recommendations/task-cards` | `?event_key=` opsiyonel; verilirse yalnızca o olayın kartları (bilinmeyen olay **404**), verilmezse tüm olayların kartları — olay + ETA sıralı `{count, event_key, cards, attribution}` | 
| `GET /api/v1/recommendations/task-cards/config` | Panel tanımlayıcısı: kaynak, alanlar, kalıcılık yok |

Aynı (kaynak, olay) için **en yeni** `accept`/`edit` kararı esas alınır;
hedef olayı silinmiş kararlar kart üretmez, silinmiş kaynak snapshot
alanlarına düşer. Operatör haritasındaki Konuşlanma panelinde **Görev
kartları** bölümü panel açıkken karar sonrası otomatik tazelenir.

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

### Kapasite Birimi Tanımı ve Normalizasyonu (EM-028)
```
GET /api/v1/capacity/assumptions  # kaynak tipi başına etkin müdahale kapasitesi (ha/saat)
PUT /api/v1/capacity/assumptions  # yönetici düzenlemesi: {"crew":..,"helicopter":..,"uav":..,"updated_by":..}
GET /api/v1/capacity/assumptions/audit[?resource_type=crew&limit=50]  # değişiklik denetim geçmişi (EM-034)
GET /api/v1/capacity/effective    # müsait envanterin tek birime (ha/saat) normalize hali
GET /api/v1/capacity/by-country   # ülke bazlı ayrış kapasite hesabı (EM-064)
GET /api/v1/capacity/schedule[?minutes=30&minutes=60]  # zamana bağlı kapasite (EM-033)
```
Kapasite ile riskin **aynı birimde** ölçülebilmesi için her kaynak tipi
(ekip / helikopter / İHA) bir **etkin müdahale kapasitesi (ha/saat)**
varsayımına sahiptir. Varsayımlar `CAPACITY_HA_PER_HOUR_*` config
default'larından tohumlanır, `capacity_assumptions` tablosunda kalıcıdır ve
paneldeki **Kapasite Varsayımları (ha/saat)** kartından yönetici tarafından
düzenlenebilir. `effective_capacity` = Σ (müsait kaynak sayısı × tip
varsayımı) ile envanter ha/saat cinsinden tek bir rakama indirgenir; panel
beslemesi `capacity.assumptions` ve `capacity.effective` alanlarını taşır.
Geçersiz/negatif tip düzenlemesi **400** döner.

### Kapasite Varsayımı Denetim Kaydı (EM-034)
EM-028 varsayımları düzenlenebilir yaptı ama yalnızca **son düzenleyeni** tek
bir `updated_by` kolonunda tuttu — eski değer, kim ve ne zaman geçmişi yoktu.
EM-034 bunu **kalıcı, salt-additive bir denetim iziyle** kapatır: `PUT` her
**gerçek** değişimde (değer gerçekten farklıysa; aynı değeri tekrar kaydetme
üretmez) `capacity_assumption_audit` tablosuna bir satır yazar — `resource_type
/ old_value / new_value / updated_by` + zaman damgası. Denetim tablosu
asla **tohumlanmaz**; okuma (`GET .../assumptions/audit`) hiçbir şey
yazmaz. Yanıt yeniden eskiye sıralıdır, `resource_type` ile filtrelenir ve
`limit` `CAPACITY_AUDIT_MAX_LIMIT`'e kırpılır. `PUT` yanıtı artık
`applied_count` ve güncel `audit` satırlarını da taşır; panel kartı **Düzenleyen**
alanı ve **Değişiklik geçmişi (denetim)** tablosuyla bunu gösterir.

### Ülke Bazında Ayrış Kapasite (EM-064)
```
GET /api/v1/capacity/by-country
```
Her söndürme kaynağı bir ülkeye (`SuppressionResource.country`) aittir ve
kapasite **ülke ayrı ayrı** toplanır. Sınır ötesi operasyonda **iki ülkenin
kaynağı hiçbir ekranda sessizce birleştirilmez**: yanıt `merged_by_default:
False` taşır, `countries` listesi her ülke için ayrı `by_type` kırılımı ve
`total_effective_ha_per_hour` verir. Ülkesi boş kaynak hiçbir ülkeye
katılmaz, açıkça `atanmamış` kovasında görünür. Yalnızca `available` durumu
ve bilinen tipler (ekip/helikopter/İHA) sayılır; ülke toplamlarının toplamı
küresel `effective_capacity` değerine eşittir. `country` kolonu zaten mevcut
olduğundan yeni tablo/migration yoktur.

### Operasyonel Risk İndeksi (EM-029)
```
GET /api/v1/risk-index          # aktif her olay için ufukluk Risk(t) (?event_key=... ile tek olay)
GET /api/v1/risk-index/config   # eşik bantları, seviye sırası, ufuk dk
```
Komutanın "bu olay T+30/60/120 dk'da ne kadar zor?" sorusu. **Risk(t) =
yayılım talebi / etkin kapasite**; her iki taraf da EM-028'in tek birimine
(ha/saat) normalize edildiği için oran birimsizdir. Talep, en güncel
`FireForecast` birikimli poligonunun ortalama alan büyümesidir
(`area_ha / horizon_dk × 60`, EM-055 ile aynı tanım) — `risk_index > 1`
yangının mevcut müdahale kapasitesinden hızlı büyüdüğü anlamına gelir.
Seviye bantları yapılandırılabilir: `RISK_INDEX_NORMAL_MAX` (vars. 0.6) →
`normal`, `RISK_INDEX_CAUTION_MAX` (0.9) → `dikkat`,
`RISK_INDEX_CRITICAL_NEAR_MAX` (1.2) → `kritik-yakin`, üzeri → `kritik`.
Etkin kapasite yalnızca `available` kaynakları saydığı için meşgul/yolda
kaynaklar indesten **otomatik** düşer (EM-031). Kapasite sıfır ve talep
varsa oran ölçülemez: `risk_index: null`, seviye `kritik`. Bilinmeyen
`event_key` **404** döner. Panelde (`/panel`) **Olay Risk İndeksi — Risk(t)**
kartı olay × ufuk tablosunu renk kodlu gösterir. EM-073 bölge panelinin
FWI tabanlı `risk_index` alanından **bağımsızdır**, onu değiştirmez.

### Kapasite Açığı Zaman Çizelgesi (EM-030)
```
GET /api/v1/risk-index/timeline  # olay bazlı talep/kapasite zaman serisi + ilk kritik aşım
```
Komutanın "kapasitem ne zaman yetmez?" sorusu. Aynı talep/kapasite verisini
ufuk boyunca **zaman serisine** dökür (`series[*] = {minute, demand_ha_h,
capacity_ha_h, gap_ha_h, risk_index, level}`). Motor yalnızca kesikli
ufuklarda (30/60/120) birikimli tahmin ürettiği için, kritik banda giriş
(`risk_index >= RISK_INDEX_CRITICAL_NEAR_MAX`) **ufuklar arası doğrusal
enterpolasyonla** bir dakikaya indirgenir (`first_exceedance_minute`,
örn. `T+47`); ilk ufuk zaten aşmışsa o ufuk (muhafazakâr üst sınır),
ufuk penceresi içinde hiç aşılmazsa `null` döner. `summary` en erken
aşım yapan olayı işaret eder. Panelde **Kapasite Açığı Zaman Çizelgesi**
kartı talep (ha/saat) eğrisini **basamaklı** etkin kapasite çizgisi üzerine çizer
(satır içi SVG — harici grafik kütüphanesi yok) ve ilk kritik dakikasını
başlıkta gösterir.

### Zamana Bağlı Kapasite Modeli (EM-033)
```
GET /api/v1/capacity/schedule[?minutes=30&minutes=60&minutes=120]
PUT /api/v1/resources/{key}   # {"status":"yolda", "arrival_minutes": 45}
```
EM-028/EM-031 **anlık** kapasiteyi yalnızca `available` kaynaklardan sayar;
`en_route` (yolda) birim o an **istasyonda değildir**. EM-033 bu gerçeği
**zaman eksenine** taşır: her yoldaki birimin `arrival_eta` (naive-UTC tahmini
varış anı) alanı vardır ve kapasite(t), o dakikaya kadar **varmış** birimleri
tür başına ha/saat varsayımıyla ekler. `capacity_schedule` `base_ha_h` (anlık),
ufuk dakikalarında `schedule` ve `arrivals` (dakika + birim ha/saat) döndürür.

`capacity_gap_timeline` artık sabit kapasite yerine **her ufku o dakikadaki
kapasiteyle** fiyatlar; böylece risk eşiği ve `first_exceedance_minute`
pekiştirmenin varışını yansıtır (açık kapanır / ilk kritik aşım ertelenir).
ETA'sı **olmayan** yoldaki birim hiçbir ufka katkı vermez (EM-031 korunur);
`TIME_DEPENDENT_CAPACITY=false` iken çizelge EM-030 **sabit** kapasite
davranışına döner. `effective_capacity` ve `compute_risk_index` (anlık
 görünüm) kasten **sabit** kalır. Envanter create/update `arrival_minutes`
(dakika-şimdiden) kabul eder; negatif **400** döner.

### Eşik Aşımı Uyarısı ve Histerezis (EM-032)
```
POST /api/v1/risk-index/alerts/evaluate  # aktif olayların risk seviyesini değerlendirir
```
Operatör ekranı sürekli izlemeden kritik anı yakalamak ister. Uç nokta EM-029
`Risk(t)` pik seviyesini her olay için yeniden hesaplar; risk **bir üst seviye**
çıktığında canlı beslemeye (EM-090 `alert`) tek bir kayıt yazar — WebSocket/REST
ile bağlı tüm operatör haritalarına anında akar. **Histerezis** tekrar eden
uyarıları bastırır: durum deposu olarak append-only besleme okunur (yeni
migration yok, Celery/API süreçleri arası tutarlı); bir olay için yalnızca
daha önce uyarılan en yüksek bandın **üstüne** çıkıldığında uyarı üretilir,
aynı seviyedeki tekrar yoklamalar sessizdir; `normal` hiç uyarı üretmez.
Özellik `RISK_ALERTS_ENABLED` (vars. `true`) ile kapatılabilir. Harita
canvas'ında uyarı **görsel bant** (kırmızı, yanıp sönen) + **sesli bip**
(WebAudio — dosya yok) + titreşim olarak görünür; `🔔 Ses` düğmesi sesi aç/kapa
yapar (tarayıcı otomatik-oynatma kilidi ilk kullanıcı hareketiyle açılır).

### What-If Rüzgâr + Hava Senaryosu ve Dinamik Yeniden Hesaplama (EM-055 / EM-061)
```
GET  /api/v1/whatif/config  # yeniden hesaplama hedef süresi (sn) ve kalıcılık bilgisi
POST /api/v1/whatif/wind    # rüzgâr ve/veya sıcaklık/nem değişikliği için canlı what-if
```
Operatör "rüzgâr 45° dönse ne olur?" sorusunu sorar. Uç nokta EM-015
Rothermel motorunu **aynı çözülmüş girdilerle iki kez** çalıştırır: biri
sarsılmamış (**orijinal**), biri kaydırıcı değişiklikleriyle (**senaryo**).
Gövde `latitude`/`longitude` (zorunlu) ve isteğe bağlı rüzgâr düğmeleri
alır: `wind_rotation_delta_deg` (yön değişimi, -360..360) ve
`wind_speed_factor` (hız çarpanı, 0..5); `wind_from_deg`/`wind_speed_kmh`
mevcut **taban** rüzgârı taşır. Diğer girdi alanları (`air_temp_c`,
`relative_humidity_pct`, `fuel_moisture_pct`, `slope_deg`, `aspect_deg`,
`fuel_model`, `horizon_minutes`) opsiyoneldir.

**EM-061 — sıcaklık ve nem kaydırıcıları:** aynı uç `temperature_delta_c`
(°C, ±40) ve `humidity_delta_pct` (yüzde puanı, ±60) **delta** düğmelerini
alır. Çözülmüş taban sıcaklık/nemi deltalarla bozulur; Rothermel motoru bu
değerleri `fuel_moisture_pct` **sabitlenmediğinde** denge (ölü) yakıt nemi
üzerinden tükettiği için daha sıcak/kuru senaryo yakıtı kurutup yayılımı
hızlandırır, daha soğuk/nemli yavaşlatır — sonuç alan/talep, kapasite açığı
ve tehdit sıralamasına yansır. Delta `0` ("Sıfırla") senaryoyu orijinalle
birebir aynı değeri döndürür; senaryo sıcaklığı [-30, 60] °C ve bağıl nemi
[1, 100] % aralığına kırpılır. Yanıta `weather` bloğu (orijinal/senaryo
sıcaklık-nem + deltalar) eklenir. Uç `POST /api/v1/whatif/wind` EM-060
kayyan p95 bütçesine danışır ve `perf_budget` alanını döndürür.

Yanıt orijinal ve senaryo risk bölgesi poligonlarını (`forecasts[*]
.polygon_geojson`, `area_ha`), **kapasite açığını** EM-028 biriminde
(talep = ha/saat alan büyümesi, arz = `effective_capacity`, `gap_ha_h`,
`gap_delta_ha_h`, `coverage_pct`) ve **önerileri** (EM-023 maruziyet
sıralamasının iki hali + `delta.newly_threatened`) döndürür. `compute_ms`
ölçülür ve `WHATIF_RECOMPUTE_TARGET_SECONDS` (vars. **10 sn**) hedefiyle
`within_target` işaretlenir. What-if **kalıcı değildir** (`persistence:
"none"`; `FireForecast` satırı yazılmaz). Geçersiz koordinat/rüzgâr **400**
döner. Harita tarafında **What-If (Rüzgâr)** paneli senaryo poligonlarını
orijinalin üzerine kesik mavi katman olarak bindirir.

### Kapasite Değişimi What-If Senaryosu (EM-056)
```
POST /api/v1/whatif/capacity  # ek kaynak varsayımıyla açık değişimi (arz tarafı)
```
EM-055 *talep*tarafı (rüzgâr) iken EM-056 **arz** tarafını sorar: "ek
helikopter/ekip eklersem kapasite açığı nasıl değişir?". Gövde
`added_resources` (`{crew|helicopter|uav: adet}`) ve opsiyonel `event_key`
alır. Servis EM-029 yayılım **talebi sabit** tutar ve onu varsayıms bir
**kapasiteye** karşı yeniden fiyatlar: canlı `effective_capacity` (EM-028) +
ek birimler tür başına ha/saat varsayımıyla (ekip 2.0 / helikopter 12.0 /
İHA 4.0). Yanıt her olay için ufuk bazında `current_gap_ha_h` /
`scenario_gap_ha_h` / `gap_delta_ha_h` ile `current_level` → `scenario_level`
bant geçişini ve pekiştirmenin **çözdüğü** olayları (`resolves_gap`,
`resolved_by_addition`) `capacity` (current→scenario, `delta_ha_h`) özetiyle
döndürür. Senaryo **kalıcı değildir** (`persistence: "none"`; kaynak atanmaz,
satır yazılmaz). Bilinmeyen tür / negatif / tamsayı-dışı adet veya
bulunamayan `event_key` **400** döner. Komutan panelinde (`/panel`)
**Kapasite What-If (EM-056)** kartı girdileri, olay seçkisini ve açık değişim
tablosunu gösterir.

### Senaryo Kaydetme ve Paylaşma (EM-059)
```
GET    /api/v1/whatif/scenarios/config     # panel özellik tanımlayıcısı
POST   /api/v1/whatif/scenarios            # adlandırılmış senaryo (girdiler) kaydet
GET    /api/v1/whatif/scenarios            # kayıtlı senaryolar (kind/event_key/limit)
GET    /api/v1/whatif/scenarios/{key}      # tek senaryo
PATCH  /api/v1/whatif/scenarios/{key}      # yeniden adlandır
POST   /api/v1/whatif/scenarios/{key}/share    # paylaşım bağlantısı (token) üret
DELETE /api/v1/whatif/scenarios/{key}/share    # bağlantıyı iptal et
DELETE /api/v1/whatif/scenarios/{key}          # senaryoyu sil
GET    /api/v1/whatif/scenarios/by-token/{token}  # token ile paylaşılan senaryoyu getir
```
EM-055/056/061/057 what-if hesapları **geçicidir**; EM-059 bunların üzerine
yalnızca **girdileri** (`kind` + `params_json`) saklayan ince bir kalıcılık
katmanı ekler — sonuç **asla önbelleğe alınmaz**, her zaman mevcut
`/whatif/wind` veya `/whatif/capacity` ucundan **yeniden oynatılır** (fizik
çoğaltılmaz, bayat sonuç olmaz). `kind=wind` enlem+boylam, `kind=capacity` dolu
bir `added_resources` ister; aksi **400** döner. `share` opak bir token
(`secrets.token_urlsafe`) üretir ve `/by-token/<token>` yolunu döner; `unshare`
tokenı temizler (bayat bağlantı **404**). Bulunamayan anahtar/token **404**.
Operatör haritasındaki (`/ui`) **Senaryolar — Kaydet / Paylaş** araç çubuğu
mevcut kaydırıcıları adlandırılmış senaryo olarak kaydeder, kayıtlı bir
senaryoyu kaydırıcılara yükleyip yeniden hesaplar ve paylaşım bağlantısını
panoya kopyalar.

### What-If Koşu Geçmişi ve Geri Alma (EM-062)
```
GET    /api/v1/whatif/history/config  # etkin + tutulan koşu sayısı (limit)
POST   /api/v1/whatif/history         # bir koşuyu (girdileri) geçmişe ekle
GET    /api/v1/whatif/history         # son N koşu (event_key/kind/limit)
GET    /api/v1/whatif/history/{id}    # geri alma için tek koşu
DELETE /api/v1/whatif/history         # geçmişi temizle (tümü veya bir olay)
```
EM-059'dan farklı olarak geçmiş **otomatik** doldurulur: her başarılı what-if
koşusu yuvarlanan bir listeye eklenir ve yalnızca son `WHATIF_HISTORY_LIMIT`
(vars. **10**) koşu tutulur — yaşlılar yeni geldikçe budanır. En yeni ile
**birebir aynı** girdi tekrar kaydedilmez (debounce). `record` özeti
`recorded` (`true`/`false` + `reason`: `disabled`/`duplicate`), `count` ve
`dropped` döner. Yalnızca **girdiler** saklanır; **Geri dön** mevcut
`/whatif/wind` ucundan koşuyu **yeniden oynatır** (sonuç önbelleği yok).
Bulunamayan `{id}` **404**. `WHATIF_HISTORY_ENABLED` (vars. `true`) kapalıyken
kayıt yapılmaz. Operatör haritasındaki (`/ui`) **Geçmiş — son koşular** aracı
koşu sonrası otomatik güncellenir ve seçili koşuya tek tıkla dönülür.

### Yeniden Hesaplama Performans Bütçesi (EM-060)
```
GET  /api/v1/perf-budget          # kayan p95 gecikme okuması (durum paneli)
GET  /api/v1/perf-budget/config   # hedef/pencere + kaba çözünürlük ayarları
POST /api/v1/perf-budget/sample   # elle gecikme örneği (yük testi/operasyon)
```
Pilot bölge sözü: bir yayılım/what-if yeniden hesabı **10 sn** içinde
bitmelidir. Tek hızlı çalış bir şey kanıtlamaz; önemli olan **kuyruktur**.
Servis son `PERF_BUDGET_WINDOW` (vars. 50) örneğin **p95** gecikmesini
`PERF_BUDGET_TARGET_SECONDS` (vars. 10 sn) hedefine karşı değerlendirir;
örnek sayısı `PERF_BUDGET_MIN_SAMPLES` (vars. 5) altına inince karar
verilmez (`within_budget: null`, titreşim önlenir). p95 hedefi aşınca
`breached` işaretlenir ve `PERF_BUDGET_ENABLED` (vars. `true`) ise sonraki
her yeniden hesaplama otomatik **kaba çözünürlüğe** düşer
(`recommended_resolution: "coarse"`, `scale_down_active: true`) — yalnızca
poligon köşe sayısı (`PERF_BUDGET_COARSE_VERTICES`) ve ufuk seti
(`PERF_BUDGET_COARSE_HORIZONS`) kırpılır. Bütçe içi → dışı **geçişinde**
canlı beslemeye (EM-090) tek bir `alert` yazılır (süreğen ihlalde tekrar
yok). `POST /sample` gövdesi `{latency_ms, source, resolution}`; negatif
`latency_ms` **400** döner. EM-055 rüzgâr ucu (`POST /api/v1/whatif/wind`)
**ek olarak** `perf_budget` alanı döndürür ve ölçülen süreyi telemetri
örneği olarak kaydeder (yayılım tahmini hâlâ yazılmaz). Tablo
`recompute_latency_samples` (V017) yalnızca-ekleme telemetridir.
Komutan panelinde (`/panel`) **Yeniden Hesaplama Bütçesi** kartı
p95 / hedef / örnek sayısı ve renk kodlu durumu gösterir.

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
durum (`available` / `deployed` / `en_route` / `maintenance` /
`out_of_service`) ve sayısal
kapasite ile yönetir; böylece komutan panelindeki kapasite hesabı güncel kalır.
Türkçe eşanlamlılar kabul edilir (ekip→crew, helikopter→helicopter, iha→uav,
müsait→available, görevde→deployed, yolda→en_route…). Bu envanter, yol ağı
`crew_bases`
(rotalama başlangıçları) kayıtlarından **ayrı** bir koordinatör kaynağıdır.

**Kullanılabilirlik durumu (EM-031):** Etkin müdahale kapasitesi (EM-028)
yalnızca `available` kaynakları sayar; dolayısıyla bir kaynağın durumu
`PUT /api/v1/resources/{key}` ile örn. `en_route` (yolda) ya da `deployed`
olarak değiştirildiği anda `GET /api/v1/capacity/effective` yeni değeri
döner — **durum değişimi indeksi anında etkiler**. `en_route`, müdahaleye
tahsis edilmiş ancak henüz istasyonda olmayan kaynağı ifade eder ve
tür bazlı yeknâda (`capacity_summary`) ayrı sayaç olarak izlenir.
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

### Hazır Senaryo Kütüphanesi (EM-105)
```
GET    /api/v1/scenarios/library                # kürasyonlu senaryo kataloğu + garantiler
GET    /api/v1/scenarios/library/runs           # kütüphane etkinleştirme denetim kayıtları
GET    /api/v1/scenarios/library/{key}          # tek senaryo önizlemesi (dataset kurulur, yazılmaz)
POST   /api/v1/scenarios/library/{key}/activate # tek tıkla başlat (EM-104 satırlarını yaz)
POST   /api/v1/scenarios/library/{key}/replay   # geri sar: etiketi sil + aynı veriyi yeniden tohumla
```
EM-104 üretecinin üzerine **adlı, arketip** demo senaryoları koyar; kütüphane
katalogu kod sabitidir (yeni tablo gerekmez). Üç arketip: `kiyi-ruzgar-donusu`
(kıyı + geniş açılı rüzgâr dönüşü), `kirsal-sessiz-bolge` (çoklu sessiz bölge,
kıt kaynak), `sinir-bolgesi` (notional sınır hattına sabitlenmiş hızlı yangın —
boylam `SCENARIO_BORDER_LON`'dan gelir ve demo bbox içine sıkıştırılır). Her
senaryo sabit `(seed, config)` aldığı için **deterministik**tir: daima aynı
`scenario_tag` ve `result_hash`. `activate` EM-104 operasyonel satırlarını yazar
ve `preset=library:<anahtar>` damgalı bir `ScenarioRun` denetim kaydı bırakır;
`replay` etiketi temizleyip aynı veriyi yeniden tohumladığından sunum aynı başlangıç
durumuna döner (tek yineleme, çift kayıt yok). Tüm çıktı `SENTETİK VERİ` etiketi
ve atıf şeridiyle işaretlidir; `preview` hiçbir şey kalıcılaştırmaz.

### Senaryo Oynatma Kontrolü (EM-107)
```
GET    /api/v1/scenarios/playback/config              # hız aralığı, kare aralığı, kontroller
GET    /api/v1/scenarios/playback/{key}/frames        # senaryonun sıralı kare zaman çizelgesi
GET    /api/v1/scenarios/playback/{key}/plan          # seçilen hız çarpanıyla duvar-saati çizelgesi
GET    /api/v1/scenarios/playback/{key}/cursor        # geçen duvar süresinden mevcut kare + ilerleme
```
EM-105'in `replay`'i (geri sar = sil + yeniden tohumla) ile **karıştırılmamalıdır**:
EM-107, başlatılmış bir senaryonun ekran zamanını sürer — **oynat / duraklat / hız
çarpanı**. Kareler senaryonun kendi rüzgâr geçmişi adımlarından **okuma zamanı**
türetilir (kalıcılık/yeni tablo yok; aynı `(seed, config)` → aynı kare sırası). İki
saat ayrılır: **senaryo saati** (karenin `offset_hours`'ı) ve **duvar saati** (kareler
arası gerçek bekleme = `PLAYBACK_FRAME_INTERVAL_SECONDS`); hız çarpanı duvar aralığını
böler (`4x` → çeyrek bekleme), duraklatma istemcide geçen süreyi dondurur. `plan`
hızlı-duvar çizelgesini, `cursor` geçen süreden `(current_index, finished, progress)`
çözümünü döndürür. Hız çarpanı `(0, PLAYBACK_MAX_SPEED_FACTOR]` penceresine sıkıştırılır.
Tüm çıktı `SENTETİK VERİ` etiketi ve atıf şeridiyle işaretlidir.

### Senaryo Düzenleyici (EM-108)
```
GET    /api/v1/scenarios/custom/config          # anahtar kalıbı, seed aralığı, ayrık anahtarlar, sınırlar
GET    /api/v1/scenarios/custom                 # arayüzden yazılmış senaryo tanımları (yeni önce)
POST   /api/v1/scenarios/custom                 # yeni senaryo tanımı oluştur (doğrulama EM-104'ten)
GET    /api/v1/scenarios/custom/{key}           # tek tanım + normalize edilmiş config
PATCH  /api/v1/scenarios/custom/{key}           # başlık/açıklama/seed/config kısmi düzenleme
DELETE /api/v1/scenarios/custom/{key}           # tanımı sil (yalnız tanım; üretime dokunmaz)
GET    /api/v1/scenarios/custom/{key}/preview   # dataset kurulur, yazılmaz (hızlı geri-bildirim)
POST   /api/v1/scenarios/custom/{key}/activate  # tek tıkla başlat (EM-104 satırları + ScenarioRun)
```
EM-105 kütüphanesi arketipleri **kod sabiti** olarak sabitler; EM-108 ise operatörün
arayüzden **kendi** senaryosunu yazıp kalıcı olarak sakladığı yüzeydir (tablo
`custom_scenarios`, `V033`). Yangın konumu, rüzgâr geçmişi ve kesinti bölgeleri girdisi
**yeniden icat edilen** bir doğrulamayla değil, EM-104 `normalize_config`'e **delege
edilerek** doğrulanır — aralık dışı değer `ScenarioEditorError` (HTTP 400) üretir.
`config` **normalize-halinde** saklandığı için `activate` bit-bit yeniden üretilebilir
(`build_dataset` + `persist_dataset` + `record_run(preset=custom:<key>)`). Anahtar
alanı `custom:` ayrığıdır; kod-kütüphanesi anahtarıyla çakışma reddedilir ve toplam
tanım `SCENARIO_EDITOR_MAX_ITEMS` ile sınırlıdır. UI (`inventory.html`) kaydedilen
tanımı EM-105 kütüphane listesiyle birleştirip gösterir. Tüm çıktı `SENTETİK VERİ`
etiketi ve atıf şeridiyle işaretlidir.

### Olay & Uyarı Webhook'ları (EM-094)
```
GET    /api/v1/webhooks/config                         # geçerli olay tipleri, imza şeması, sınırlar
GET    /api/v1/webhooks                                # panel beslemesi: abonelikler + teslim özeti + son geçmiş
GET    /api/v1/webhooks/subscriptions                  # abonelikler (teslim sayılarıyla)
POST   /api/v1/webhooks/subscriptions                  # yeni uç nokta kaydet (URL + olay tipleri + gizli anahtar)
PUT    /api/v1/webhooks/subscriptions/{key}            # kısmi düzenleme (duraklat/sürdür dahil)
DELETE /api/v1/webhooks/subscriptions/{key}            # aboneliği sil (teslim geçmişi denetim izi olarak kalır)
POST   /api/v1/webhooks/dispatch                       # en son canlı-akış olaylarını ilgili abonelere imzalı dağıt
POST   /api/v1/webhooks/preview?key=&event_type=       # gönderilecek imzalı zarfı kayıtsız önizle
POST   /api/v1/webhooks/deliveries/{key}/attempt       # bir denemenin taşıyıcı sonucunu kaydet
POST   /api/v1/webhooks/retry                           # zamanlanmış başarısız teslimleri yeniden dene
GET    /api/v1/webhooks/deliveries                     # teslim defteri (yeniden eskiye; abonelik/durum filtresi)
```
Bütünleştirici, olay ve uyarıları kuyruklamak yerine bunların bir alt sistem
servisine anında **itilmesini** ister. Bir abonelik bir uç nokta (yalnızca
`http(s)`), ilgilendiği canlı-akış türleri (`fire_event` / `forecast` / `alert`)
ve her isteği HMAC-SHA256 ile imzalamak için kullanılan paylaşılan bir **gizli
anahtar** tanımlar; imza GitHub/GitLab tarzı `X-EmberMind-Signature: t=<timestamp>,v1=<hex>`
başlığıyla `"<timestamp>.<body>"` üzerinden hesaplanır. API yanıtı gizli anahtarı
asla geri vermez (yalnızca `has_secret`). Başarısız bir deneme, sınırlı bir üstel
geri çekilme bütçesiyle (`WEBHOOK_MAX_RETRIES` / `WEBHOOK_BACKOFF_SECONDS`) sonraki
deneme anını planlar; `retry_due` bütçeyi tek kapı olarak uygular (bütçe dolan
satır yeniden-deneme kuyruğundan düşer). Her deneme, imzalanan gövdeyi, imzayı,
sonucu ve deneme sayısını **yalnızca-eklenen** `webhook_deliveries` defterine
yazar; böylece "ne, kime gönderildi, tuttu mu, ne zaman yeniden denenecek"
incelenebilir kalır. **Gerçek HTTPS taşıyıcısı bu katmanda bilinerek yapılmaz**
(EM-069 emsali: canlı ağ gönderimi asla "teslim edildi" diye sahtelenmez);
defter imzalı isteğin kalıcı kaydıdır ve `record_attempt` / `dispatch_event` `simulate_fail_for`
/ `retry` uçları başarısızlık + yeniden-deneme yolunu belirlenimci biçimde çalıştırır.
UI: `/ui` haritasındaki **Webhook'lar** paneli.

### Birleşik Denetim Kaydı (EM-096)
```
GET    /api/v1/audit/config                            # kontrollü sözlükler (alan/eylem) + değişmezlik politikası + sınırlar
GET    /api/v1/audit                                   # panel beslemesi: değişmez kayıtlar (öksüzden eskiye) + alan bazlı sayım
POST   /api/v1/audit                                    # tek bir değişmez hesap verebilirlik kaydı ekle (kim/ne zaman/ne)
```
Yönetici, hangi alt sistemden gelirse gelsin **kimin hangi kararı/değişikliği ne
zaman verdiğini** tek bir yerde görmek ve kayıtların sonradan değiştirilemez/
silinemez olmasını ister. Bugüne dek denetim **parça parça**ydı (kapasite
`capacity_assumption_audit` EM-034, kararlar `recommendation_decisions` EM-047,
webhook/abonelik kendi tabloları); tek, birleşik ve değişmez bir defter yoktu.
Her kayıt bir **alan** (`recommendation` / `capacity_assumption` / `threshold` /
`scenario` / `share_policy` / `webhook` / `general`), bir **eylem** (`create` /
`update` / `delete` / `accept` / `reject` / `edit` / `enable` / `disable` /
`publish`), zorunlu bir **aktör**, opsiyonel bir özne anahtarı ve `old_value` →
`new_value` JSON anlık görüntüleri taşır; bilinmeyen alan/eylem veya boş aktör
`400` ile reddedilir. Servis yüzeyinde ve rota katmanında **güncelleme/silme/
temizleme UÇLARI BİLİNÇLİ OLARAK YOKTUR** — "kayıtlar silinemez" garantisi budur;
okuma hiçbir şey yazmaz ve mevcut alt-özellik denetim tablolarına dokunulmaz
(yalnızca-eklenen `audit_trail`, **V030**). UI: `/ui` haritasındaki **Birleşik
Denetim Kaydı** paneli (alan/aktör filtresi + alan sayımlı değişmez geçmiş).

### Belediye / Trafik / Kamu Uyarı Entegrasyon Şablonu (EM-093)
```
GET    /api/v1/integration-templates                     # birleşik paket: config + kanal bazlı örnekler + örnek alıcı
GET    /api/v1/integration-templates/config              # kanal kataloğu + olay tipleri + imza sözleşmesi (canlı EM-094)
GET    /api/v1/integration-templates/consumer            # imza doğrulama parçacığı + dağıtım notu (gizli anahtar gömmez)
GET    /api/v1/integration-templates/{event_type}        # bir olay tipi için tüm kanal biçimleri (temsili zarf)
GET    /api/v1/integration-templates/{event_type}/{channel}  # tek kanal biçimi
```
Entegratör, **yeni donanım gerekmeden** mevcut belediye bilgi panosu / trafik
değişken mesaj işareti (VMS) / kamu uyarı (CAP-benzeri) head-end'ini EM-094'ün
**imzalı webhook'una** bağlamak ister. EM-093 gönderim mekanizmasını yeniden
icra etmez; onun **alıcı tarafı bağlantı şablonudur**: gerçek bir EM-094 zarfını
her kanalın yerel biçimine nasıl dönüştüreceğini, paylaşılır gizli anahtarla
`X-EmberMind-Signature` imzasını nasıl doğrulayacağını ve kopyala-yapıştır küçük
bir alıcı iskeletini gösterir. Kanal kataloğu, imza başlığı ve olay tipleri
**canlı EM-094 sözleşmesinden** türer (asla sapmaz). Güvenlik notu: örnekler
gerçek bir gizli anahtar **gömmez** — yalnızca `$EMBERMIND_WEBHOOK_SECRET` ortam
yer tutucusu kullanılır. Kalıcılık `none` (salt okuma zamanı projeksiyon; tablo/
migration/operatör paneli yok — bu bir geliştirici/entegratör yeteneğidir).

### API Dokümantasyonu ve Örnek İstemci (EM-095)
```
GET    /api/v1/api-docs                                  # birleşik paket: openapi + errors + rate_limits + examples
GET    /api/v1/api-docs/config                           # OpenAPI kimlik metadata'sı (başlık/sürüm/taban URL/iletişim/lisans/etiketler)
GET    /api/v1/api-docs/errors                           # birleşik HTTP hata sözleşmesi (400/401/404/409/422/429/500/503)
GET    /api/v1/api-docs/rate-limits                      # EM-092 hız sözleşmesi (canlı ayardan; anahtar ifşa etmez)
GET    /api/v1/api-docs/examples                         # kopyala-yapıştır cURL + Python örnek istemcileri
```
Entegratör API'yi hızla denemek ister. FastAPI zaten etkileşimli dokümanları
yayarlar: **Swagger UI** `/docs`, **ReDoc** `/redoc`, ham şema `/openapi.json`.
EM-095 bunları tamamlar: yayımlanan OpenAPI şeması artık bir **kimlik
metadata'sı** (iletişim/lisans/servis şartları + etiket açıklamaları) taşır;
ayrıca tek, dürüst bir **hata kodu** kataloğu, **EM-092 hız sınırı sözleşmesi**
ve gerçek uçlara işaret eden **cURL/Python örnek istemcileri** sunulur. Güvenlik
notu: örnekler **gerçek bir API anahtarı gömmez** — yalnızca `x-api-key` başlığı
ve ortam yer tutucusu (`$WILDFIRE_API_KEY`) kullanılır. Kalıcılık `none` (salt
okuma zamanı projeksiyon; tablo/migration/operatör paneli yok).

### Dış İstemci Erişim Kontrolü (EM-092)
```
GET    /api/v1/external/status                          # API anahtarıyla korumalı örnek uç (401 / 429 / 200 + X-RateLimit-*)
GET    /api/v1/api-access/config                        # etkin/zorunlu, başlık adı, anahtar sayısı ve hız kesesi (anahtarları ifşa etmez)
```
Sistem yöneticisi, dış entegrasyonları bir **API anahtarıyla** yetkilendirip
**hızlarını sınırlamak** ister ki sistem kötüye kullanılmasın. Anahtar
`x-api-key` başlığıyla gönderilir; eksik/yanlış anahtar `401`, anahtarı geçerli
olup pencere bütçesini aşan istemci `429` (+ `Retry-After`) alır; izinli çağrı
`200` ve kalan bütçeyi `X-RateLimit-*` başlıklarında döner. Hız sınırı
**sabit-pencere** sayacıdır ve her istemci-anahtarının **kendi bağımsız** kovası
vardır. Zorlama yalnızca açık *ve* en az bir anahtar tanımlıyken devreye girer;
aksi halde uç bilinçli olarak `disabled` döner — korumayan bir güvenlik kontrolü
varmış gibi davranmayız. Yapılandırma `API_ACCESS_*` ayarlarındadır; kabul
edilen anahtarlar yanıtta/`config` ucunda **asla** geri yansımaz (yalnızca sayısı
ve sha256 parmak izi). Kalıcılık `none` (sayaçlar süreç-içi; tablo/migration yok).

### Karar Destek Çerçevesi (EM-097)
```
GET    /api/v1/decision-support                         # sorumluluk ifadesi + veri/model sürümü + senaryo (sentetik) rozeti
GET    /api/v1/decision-support/config                  # varsayılanlar + ayar düğmeleri + etiket kataloğu
```
Komutan, öneri ekranında sistemin bir **karar destek aracı** olduğunu ve nihai
kararın kendisinde (**yetkili operatör**) olduğunu net görmeli; öneriyi üreten
**veri/model sürümü** de görünür olmalıdır. Pilot sentetik veriyle çalıştığı için
bu gerçek ekranda **SENARYO VERİSİ** rozeti olarak ayrım gözetmeksizin basılır;
gerçek bir dağıtımda bayrak kapatılınca rozet gizlenir. `advisory_only` her zaman
`true`dur — sistem asla kararı otomatik uygulamaz. Boş/whitespace ayar
override'ları varsayılana düşer. Salt okuma zamanıdır: **hiçbir şey yazılmaz**
(`persistence: none`). UI: `/ui` haritasındaki **Konuşlanma Önerileri** panelinin
altında kalıcı sorumluluk/model/veri şeridi + başlıkta senaryo rozeti. Ayarlar:
`DECISION_SUPPORT_MODEL_VERSION`, `_DATA_VERSION`, `_RESPONSIBILITY_TEXT`,
`_SCENARIO_DATA`.

### Bölge Sinyal Baz Çizgisi (EM-035)
```
GET    /api/v1/signal-baseline/config                  # kullanılabilir+planlanan kaynaklar, pencere sınırları, ızgara, duyarlılık
GET    /api/v1/signal-baseline                         # hücre bazında baz çizgi + son okumanın z-skoru (en sessiz önce)
GET    /api/v1/signal-baseline/cells/{region_key}      # tek hücre baz çizgisi (bilinmeyen anahtar → 404)
```
Sessiz bölge **anomalisi**nin anlam kazanması için önce "normal" öğrenilir:
her izleme hücresi için `as_of` gününden önceki kayan pencerede (varsayılan
**30 gün**, `SIGNAL_BASELINE_WINDOW_DAYS`, 7–120 arası kırpılır) sinyal
seviyesinin ortalaması/yayılımı/medyanı/aralığı hesaplanır; son okumanın
z-skoru ve sessizlik oranı üretilir, `candidate_silent = z ≤ -eşik`
(`SIGNAL_BASELINE_SENSITIVITY_Z`) sessizlik **ön göstergesidir** — çok
özellikli anomali sınıflandırıcısı EM-036'nın kapsamıdır, burada öğrenilmez.
Sinyal, takılabilir bir `SignalSource` arayüzünden gelir: pilot için tek
uygulanan kaynak **deterministik sentetik** iletişim/rapor akışıdır
(hücre bazlı taban + hafta sonu ritmi + günlük titreme; tüm yanıtlar
`synthetic: true` + SENTETİK etiketiyle döner, asla gerçek gibi sunulmaz).
Gerçek beslemeler (trafik yoğunluğu, sosyal medya, sensör) `planned` olarak
listelenir ama bilinçli olarak uygulanmaz (ağ entegrasyonu bu görevin kapsamı
dışı). Izgara `SIGNAL_BASELINE_CELL_ROWS`×`_CELL_COLS` (azami `_MAX_CELLS`),
kutu pilot sınırlarından (`SIGNAL_PILOT_MIN/MAX_LAT/LON`) türetilir.
Bilinmeyen kaynak/geçersiz `as_of` → `400`; **hiçbir şey yazılmaz**
(`persistence: none`, okuma zamanı hesaplanır). UI: `/ui` haritasındaki
**Sinyal Baz Çizgisi** paneli (kaynak seçici + referans tarih + yalnızca
sessiz adayı süzmesi + harita senkron hücre seçimi).

### Mevsimsel Sinyal Baz Çizgisi (EM-043)
```
GET    /api/v1/signal-baseline-seasonal/config     # kaynaklar, mevsimsellik boyutları, saat/hafta kataloğu, sınırlar, yenileme
GET    /api/v1/signal-baseline-seasonal            # hücre bazında düz(önce) vs mevsimsel(sonra) puan + yanlış-alarm özeti
                 ?source&as_of&window_days&hour(0-23)&region_key&limit
GET    /api/v1/signal-baseline-seasonal/refresh    # istenen tarih için her hücrenin mevsimsel bazını yeniden hesapla (günlük)
```
EM-035 **düz** bir normal öğrendiği için yapısal olarak sessiz bir bölge (gecenin
kör saati, hafta sonu) düz ortalamanın çok altında kalıp **yanlış** sessiz adayı
olur. Bu servis **saat-in-günü** ve **haftanın-günü** çarpan-temelli mevsimsel
kat sayılarını yinelemeli iki-yönlü normalizasyonla öğrenir, sinyali
mevsimsellikten arındırır ve **artığı** mevsimsel normale göre puanlar — gece/hafta
sonu sessizliği artık anomali değil, beklenen. `hour` kontrol saati,
`window_days` penceresi (7–120) ve `source` seçilir. `seasonal_cell` her hücrede
`z_flat`/`z_seasonal`, `candidate_flat`/`candidate_seasonal` ve
`false_alarm_removed` üretir; rapor `flat_candidate_count → seasonal_candidate_count`
ve `false_alarms_removed` ile yenileme **öncesi/sonrası** yanlış-alarm
karşılaştırmasını özetler. `SyntheticDiurnalSource` gerçek **saatlik** bir sentetik
akıştır (sessiz gece/yoğun gündüz/hafif hafta sonu, `synthetic: true` + SENTETİK);
günlük-only bir kaynak dürüstçe yalnızca-hafta-günü mevsimselliğine düşer (saat
çarpanları 1.0). Öğrenilen anomali sınıflandırıcısı EM-036 **değildir** — bu
istatistiksel bir düzeltmedir. `refresh` "günlük yeniden hesaplama"yı modeller ama
okuma-zamanlıdır: **hiçbir şey yazılmaz** (`persistence: none`). Bilinmeyen
kaynak/`as_of`/saat → `400`/`422`. Ayarlar:
`SIGNAL_SEASONAL_NIGHT_CHECK_HOUR`, `_NORMALIZATION_ITERATIONS`,
`_DEFAULT_SOURCE`, `_MAX_CELLS`. UI: `/ui` haritasındaki **Mevsimsel Baz Çizgisi**
paneli (kaynak/kontrol-saati/referans-tarih + yalnızca-mevsimsel-aday süzmesi +
düz→mevsimsel aday geçişini gösteren özet + tek tık Günlük Yenile + harita
senkron hücre seçimi).

### Isolation Forest Anomali Skorlaması (EM-036)
```
GET    /api/v1/isolation-forest-anomaly/config   # kaynaklar, sigma/pencere sınırları, model düğmeleri, gerçek zamanlı aralık
GET    /api/v1/isolation-forest-anomaly          # hücre bazında öğrenilmiş anomali skoru + ortalama-sigma·sapma sessizlik testi
                 ?source&as_of&window_days&sigma_multiplier(1.0-5.0)&region_key&limit
GET    /api/v1/isolation-forest-anomaly/latest   # 15 dakikalık beat'in sürdüğü anlık anormallik taraması
```
EM-035/EM-043 sessiz bölgeyi **tek bir elle seçilmiş** z-eşiğiyle işaretler. Bu
servis veri bilimcisinin isteğini karşılar: her hücre için baz penceresinde bir
`IsolationForest` **eğitilir** ve son okumun **çok-özellikli** anomali skoru
otomatik üretilir — elle inceleme gerekmez. Özellik vektörü `[bugünkü sinyal,
dünki sinyal]` (düzey + gündüz momentumu); `as_of` eğitime girmez, yalnızca
puanlanır. İstatistiksel taraf kabul kriterindeki **`ortalama(baz) − sigma·sapma`**
sessizlik eşiğini verir (sigma varsayılan `3.0`, `1.0–5.0` yapılandırılabilir);
`detection_basis` `istatistikî`/`isolation_forest`/`ikisi`/`yok` olarak model ile
eşiğin **uzlaşıp uzlaşmadığını** gösterir. `random_state` sabittir, skorlar
yeniden üretilebilir. "15 dakikalık aralıklarla gerçek zamanlı" isteği
`ANOMALY_INTERVAL_MINUTES` ile bir Celery beat'i olarak modellendi; kalıcılık
`none` (okuma-zamanı yeniden hesaplama). Bilinmeyen kaynak/`as_of` → `400`/`422`.
Ayarlar: `ANOMALY_SIGMA_MULTIPLIER`, `_WINDOW_DAYS`, `_CONTAMINATION`,
`_N_ESTIMATORS`, `_RANDOM_STATE`, `_MAX_CELLS`, `_INTERVAL_MINUTES`,
`_DEFAULT_SOURCE`, `_SCORING_ENABLED`. UI: `/ui` haritasındaki **Isolation Forest
Anomali** paneli (sigma + pencere + kaynak + referans-tarih kontrolleri +
yalnızca-anomali süzmesi + hücre bazlı skor/eşik/temel rozetleri + "Anlık Tara" +
harita senkron hücre seçimi).

### Yüksek Öncelikli Sessiz Bölge Kesişimi (EM-037)
```
GET    /api/v1/silent-region-risk/config      # formül, eşikler, yüksek-öncelik kuralı, kalıcılık
GET    /api/v1/silent-region-risk[?flagged_only=true&limit=N]  # risk × sessizlik sıralı kesişim raporu
```
"Riskli ama sessiz" senaryosu: EM-078 paneli sessizlik **güven bandını**, EM-015
yayılım **poligonlarını** ayrı ayrı üretiyordu; bu servis ikisini **birleştirir**.
Her aktif sessiz bölgenin sessizlik güveni `silent_zone_report` **yeniden
kullanılarak** alınır; yalnızca **aktif** `FireEvent`'lere bağlanmış
`FireForecast` poligonları Shapely ile bölge kutusuyla kesiştirilir ve
**kapsama oranı** risk derecesini verir (`risk_degree = kesişim/alana`).
`priority = risk_degree × silence_degree` ile azalan sıralanır;
`is_high_priority` **hem** risk (`SILENT_REGION_RISK_MIN_COVERAGE`) **hem**
sessizlik (`SILENT_REGION_RISK_MIN_CONFIDENCE`) eşiklerini geçmelidir — bölge
içinde canlı yangın varsa sessizlik çöker ve bölge öncelik dışı kalır.
Çözülemeyen/poligon olmayan tahmin geometrisi **atlanır**. Tehdit başına
`worst_threat` ve `threatening_event_keys` listelenir. `flagged_only=true`
yalnızca yüksek önceliklileri tutar; `limit` (<1 → `400`/`422`) listeyi kırparsa
da `summary` **genel** kalır. Azami tahmin `SILENT_REGION_RISK_MAX_FORECASTS`.
**Hiçbir şey yazılmaz** (`persistence: none`, okuma zamanı hesaplanır). UI:
`/ui` haritasındaki **Yüksek Öncelikli Sessiz Bölge** paneli (yalnız-öncelikli
süzmesi istemci tarafında + harita senkron bölge seçimi, risk/sessizlik/öncelik
rozetleri).

### Yanlış Alarm Önleme: Sessiz Bölge Güven Etiketi (EM-038)
```
GET    /api/v1/silent-zone-confidence/config                 # güven merdiveni, eşikler, kalıcılık
GET    /api/v1/silent-zone-confidence[?confidence=high&limit=N&as_of=YYYY-MM-DD]  # güven dereceli sessiz aday raporu
```
EM-035 baz çizgisi hangi hücrenin **sessiz aday** olduğunu üretir; bu servis her
adayı **neden** sessiz olduğunu ayırt ederek **güven derecesiyle** etiketler.
`baseline_report` **yeniden kullanılır**; kapsama gücü `_coverage_strength` ile
ölçülür: gözlem sayısı `FALSE_ALARM_MIN_OBSERVATIONS` altındaysa
`insufficient_data`, baz ortalaması `FALSE_ALARM_MIN_COVERAGE_SIGNAL` altındaysa
`weak` → **düşük güven** (yapısal zayıf kapsama, bölge zaten az raporluyor →
**yanlış alarm** olasılığı). Sağlam kapsama üzerine okuma baz çizgisinin belirgin
altındaysa (`z ≤ -FALSE_ALARM_STRONG_DROP_Z`) → **yüksek güven** (ani kesinti →
**gerçek acil durum** işareti). Sağlam ama belirgin olmayan düşüş → **orta güven**
(izlemeye değer). Zayıf kapsama, ani düşüşten **önceliklidir** (düşük güven kazanır).
Her hücreye `confidence_code`/`confidence_label`/`confidence_reasons` eklenir.
`confidence` süzgeci yalnız o dereceyi tutar (bilinmeyen değer `filter: null` +
`requested_filter` olarak yankılanır); `limit` (<1 → `422`) listeyi kırparsa da
`summary` **genel** kalır (yüksek/orta/düşük sayıları + zayıf-kapsama aday sayısı).
Sıralama `(derece, z-skoru, bölge)`. Geçersiz `as_of` → `400`; **hiçbir şey
yazılmaz** (`persistence: none`, okuma zamanı hesaplanır). UI: `/ui` haritasındaki
**Yanlış Alarm Önleme** paneli (güven derecesi süzgeci istemci tarafında + harita
senkron hücre seçimi, yüksek/orta/düşük renk rozetleri, SENTETİK etiketi).

### Sessiz Bölge Performans Ölçümü (EM-042)
```
GET    /api/v1/silent-detection-performance/config           # senaryo düğmeleri, sınırlar, metrekataloğu
GET    /api/v1/silent-detection-performance[?source=&as_of=YYYY-MM-DD&horizon_days=N&window_days=N&onset_rate=F&sensitivity_z=F]  # sentetik senaryoda TPR/FPR/uyarı gecikmesi
```
Tespit doğruluğunu kanıtlamak için **gerçek EM-035 dedektörü** deterministik bir
sentetik senaryo üzerinde gün gün yeniden oynatılır. Senaryo, her izleme hücresine
`onset_rate` oranında enjekte edilen sessiz bölümler (`SilentEpisode`, kök-hakikat)
içerir; `OutageInjectedSource` bölüm günlerinde okumayı `depth` seviyesine çökertir.
`compute_cell_baseline` tahmini ile enjekte kök-hakikat karşılaştırılıp kafa karışıklık
matrisi (TP/FP/FN/TN) çıkarılır; TPR/FPR/precision/recall/F1/accuracy + uyarı gecikmesi
özeti (yakalanan/bulunamayan bölüm, ortalama/dk/maks gün) + bölüm bazında satırlar
üretilir. **Tanımsız oranlar `None`** döner (yanıltıcı `0.0` değil). Çıktı daima
`synthetic: true` + `scenario_label` ile **sentetik senaryo** olarak etiketlenir.
Geçersiz `as_of` → `400`; doğrulama hatası → `400`; **hiçbir şey yazılmaz**
(`persistence: none`). UI: `/ui` haritasındaki **Sessiz Bölge Performans** paneli
(ana metrikler + bölüm satırları + SENTETİK etiketi).

### Sessiz Bölge Uyarıları (EM-040)
```
GET    /api/v1/silent-region-alerts/config                    # risk merdiveni, bantlar, bastırma kuralı, kalıcılık
GET    /api/v1/silent-region-alerts[?level=kritik&limit=N]    # yüksek öncelikli bölge uyarı beslemesi
```
Operatör, riskli bir bölge sessizliğe düştüğü anda haberdar olur. Bu servis EM-037
`silent_region_risk_report(flagged_only=True)` **yeniden kullanılarak** her yüksek
öncelikli bölge için **tek uyarı** üretir. Sessizlik süresi sessiz bölge kaydının
`created_at`'ından şimdiye kadar **saat** olarak ölçülür (`silence_duration_hours`).
Öncelik skoru Türkçe **risk merdivenine** eşlenir: `SILENT_ALERT_CRITICAL_PRIORITY`
(0.6) → **kritik**, `_HIGH_PRIORITY` (0.4) → **yüksek**, `_MEDIUM_PRIORITY` (0.2) →
**orta**, altı → **düşük**. Aynı bölgeyi tehdit eden fazla aktif yangın
`suppressed_duplicate_alerts` ile tek uyarıya **katlanır** (kabul: "aynı bölge için
tekrar uyarı bastırılır"); `summary` `by_level` + ham aday/bastırılan sayılarını taşır.
Uyarı `bölge/süre/risk seviyesi` taşır. `level` yalnız o bandı tutar (bilinmeyen →
`400`); `limit` (<1 → `422`) listeyi kırparsa da `summary` **genel** kalır. Azami
uyarı `SILENT_ALERT_MAX_LIMIT`. Sıralama `(öncelik azalan, bölge artan)`.
**Hiçbir şey yazılmaz** (`persistence: none`, okuma zamanı hesaplanır). UI:
`/ui` haritasındaki **Sessiz Bölge Uyarıları** paneli (risk seviyesi rozetleri,
bölge/süre/tehdit eden yangın sayısı, bastırılan tekrar sayısı, harita senkron seçim).

### Sessiz Bölge Doğrulama (EM-041)
```
GET   /api/v1/silent-zone-verifications/config                    # hüküm kataloğu, eklenen-değişmez kural, geri bildirim sinyali
POST  /api/v1/silent-zone-verifications                           # bir bölgeye operatör hükmü ekle (beden: region_id, status[, region_name, reason, verified_by, detail])
GET   /api/v1/silent-zone-verifications[?status=verified&region_id=N&limit=N]   # kaydedilen hükümler (yeniden eskiye)
GET   /api/v1/silent-zone-verifications/current[?region_id=N]     # tek bölgenin güncel hükmü ya da tüm bölgelerin
GET   /api/v1/silent-zone-verifications/feedback                  # durum bazında sayım + yanlış-alarm oranı
```
EM-040 uyarısını operatörün yargısıyla kapatır: bir bölge **doğrulandı** /
**yanlış alarm** / **inceleniyor** olarak işaretlenir. Her işaretleme **eklenen-değişmez**
(append-only) bir denetim satırıdır — önceki hüküm **üzerine yazılmaz**, güncel hüküm
**en yeni satırdır**. Bölge adı satıra anlık görüntü olarak yazılır. Geçersiz `status`
→ `400`; bulunamayan `region_id` → `404`; `limit` (<1 ya da >200 → `422`, üstte
`SILENT_VERIFICATION_MAX_LIMIT`'e kırpılır). **Geri bildirim sinyali** yalnızca
**kesin** hükümler üzerinden `yanlış-alarm oranı = false_alarm / (verified + false_alarm)`
verir; `under_review` sayılır ama **kesin sayılmaz** (karara bağlanmış bölge sayısına
dahil edilmez). Bu panel okuma-zamanlı E4 panellerinden farklı olarak **yazar**
(`persistence: silent_zone_verifications`). UI: **Sessiz Bölge Uyarıları** panelinde
hüküm rozeti + satır içi Doğrulandı/Yanlış alarm/İnceleniyor düğmeleri, operatör adı
girişi ve yanlış-alarm oranı şeridi.

### Sessiz Bölge Hassasiyet ve Eşik Ayarı (EM-044)
```
GET   /api/v1/silent-zone-tuning/config                    # varsayılanlar, sınırlar, devralma kuralı, denetim alanı
GET   /api/v1/silent-zone-tuning/effective[?region_id=N]   # tek bölgenin ya da tüm etkin bölgelerin birleşik (varsayılan+override) ayarı
POST  /api/v1/silent-zone-tuning                           # bir bölgenin override'ını kaydet (beden: region_id[, sensitivity_z, min_silence_hours, actor])
POST  /api/v1/silent-zone-tuning/reset                     # override'ı sil, bölge varsayılana döner (beden: region_id[, actor])
```
EM-035 tek bir **küresel** sessizlik z-eşiği, EM-040 tek bir **küresel** minimum
sessizlik süresi kullanır; oysa "ne kadar sessiz = sessiz" ve "ne kadar bekleyelim"
bölgeden bölgeye değişen bir yanlış-alarm/kaçırma takasıdır ve **operatöre** aittir.
Bu servis bölge başına iki düğmeyi (`sensitivity_z`, `min_silence_hours`) **kalıcı**
bir override satırıyla (NULL → varsayılanı devralır) etkin değere birleştirir.
`effective_for_region`/`list_effective` ayarlanmamış bölgeyi varsayılana, ayarlanmış
olanı override'a çözer (listede ayarlanmışlar önde). `set_tuning` **en az bir** düğme
ister (yoksa `400`); verilen düğmeleri sınıra göre doğrular (`sensitivity_z`
`0.5–5.0`, `min_silence_hours` `0–168`, dışındakiler `400`), yoksa satırı oluşturur
varsa günceller ve **tekilleştirilmiş denetim defterine** `threshold` alanında
(EM-096) kim/ne-zaman/eski→yeni satırı **yazar**. `reset_tuning` satırı siler ve
`delete` denetim satırı yazar; zaten varsayılan olan bölge için **idempotenttir**
(denetim satırı yazmaz). Bulunamayan `region_id` → `404`. Bu panel E4'ün okuma-zamanlı
panellerinden farklı olarak **yazar** (`persistence: silent_zone_tuning`). Ayarlar:
`SILENT_TUNING_DEFAULT_SENSITIVITY_Z`, `_DEFAULT_MIN_SILENCE_HOURS`,
`_MIN/_MAX_SENSITIVITY_Z`, `_MIN/_MAX_SILENCE_HOURS`, `_MAX_LIMIT`. UI: **Sessiz Bölge
Ayarı** paneli (bölge başına eşik + minimum-sessizlik editörleri, varsayılan/sınır
şeridi, "Kaydet" ve "Varsayılana dön" düğmeleri, operatör adı girişi, ayarlanmış
bölge rozeti).

## Error Codes

- `200`: Başarılı
- `400`: Hatalı istek
- `404`: Bulunamadı
- `500`: Sunucu hatası
