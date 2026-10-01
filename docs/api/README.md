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
PUT /api/v1/capacity/assumptions  # yönetici düzenlemesi: {"crew":..,"helicopter":..,"uav":..}
GET /api/v1/capacity/effective    # müsait envanterin tek birime (ha/saat) normalize hali
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

## Error Codes

- `200`: Başarılı
- `400`: Hatalı istek
- `404`: Bulunamadı
- `500`: Sunucu hatası
