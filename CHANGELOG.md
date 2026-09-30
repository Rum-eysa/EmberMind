# Changelog

Tüm değişiklikleri bu dosyada dokümante ediyoruz.

## [Unreleased]

### Added
- EM-062: What-if geçmişi ve geri alma (E6)
  - Operatör **denediği koşuları** geriye doğru görmek ve tek tıkla birine
    dönmek ister (karşılaştırmalı çalışma). EM-059'dan farklı olarak geçmiş
    **otomatik** doldurulur ve yalnızca son `WHATIF_HISTORY_LIMIT` (vars. 10)
    koşuyu tutar (kendini budar); adlandırılmış/kalıcı senaryo değildir
  - `src/models/scenario.py` (`WhatIfHistory`, `whatif_history` tablosu, `V020`
    migration) + `src/services/whatif_history.py` (`record_history`,
    `list_history`, `get_history`, `clear_history`); en yeni ile **birebir
    aynı** girdi tekrar kaydedilmez (istemci + sunucu debounce)
  - Yalnızca **girdiler** (`params_json`) saklanır; geri alma mevcut
    `/whatif/wind` ucundan **yeniden oynatır** (fizik çoğaltılmaz, bayat sonuç
    olmaz)
  - Uçlar: `POST/GET/DELETE /api/v1/whatif/history`, `GET /…/history/config`,
    `GET /…/history/{id}` (`WHATIF_HISTORY_ENABLED`, vars. `true`)
  - Operatör haritası (`/ui`): koşu başarılı olduğunda **Geçmiş — son koşular**
    otomatik güncellenir; açılır listeden bir koşu seçip **Geri dön** ile
    kaydırıcılar + ignisyon noktası eski değerlerine döner ve yeniden hesaplanır
- EM-059: What-if senaryosu kaydetme ve paylaşma (E6)
  - EM-055/056/061/057 what-if yeniden hesaplamaları kasıtlı olarak geçiciydi;
    EM-059 bunların **üzerine** ince bir kalıcılık katmanı ekler: bir komutan
    umut verici bir koşu adlandırır, vardiya devrinde geri getirir ve ekibe bir
    **bağlantıyla** paylaşır (kaydırıcıları tekrar girmeden)
  - Yalnızca senaryonun **girdileri** saklanır (`kind` + `params_json`); sonuç
    asla önbelleğe alınmaz — her zaman mevcut `/whatif/wind` veya
    `/whatif/capacity` ucundan **yeniden oynatılır** (fizik çoğaltılmaz, bayat
    sonuç olmaz)
  - `src/models/scenario.py` (`whatif_scenarios` tablosu, `V019` migration):
    `scenario_key`, `name`, `kind` (wind/capacity), `event_key`, `params_json`,
    `share_token` (opsiyonel, benzersiz), `created_by`, `notes`
  - `src/services/scenario_share.py`: CRUD + paylaşım token yaşam döngüsü
    (`create/list/get/rename/enable_share/disable_share/delete`); tür/girdi
    doğrulaması (wind → enlem+boylam, capacity → dolu `added_resources`)
  - **Paylaşım:** `enable_share` opak bir token üretir (`secrets.token_urlsafe`)
    ve `/api/v1/whatif/scenarios/by-token/<token>` yolu döner; `disable_share`
    bağlantıyı iptal eder
  - Uçlar: `POST/GET /api/v1/whatif/scenarios`, `GET /…/config`,
    `GET /…/{key}`, `PATCH /…/{key}`, `POST/DELETE /…/{key}/share`,
    `DELETE /…/{key}`, `GET /…/by-token/{token}`
  - Operatör haritası (`/ui`): what-if panelinde **Senaryolar — Kaydet / Paylaş**
    araç çubuğu (mevcut kaydırıcıları adlandırılmış senaryo olarak kaydet,
    kayıtlı bir senaryoyu seçip kaydırıcılara yükle + yeniden hesapla, seçili
    senaryonun paylaşım bağlantısını panoya kopyala)
- EM-057: Gerçek zamanlı otomatik yeniden hesaplama — "plan güncellendi, ne değişti?" (E6)
  - `src/services/auto_recompute.py`: rüzgâr, **yangın konumu** veya **kapasite**
    anlamlı biçimde değiştiğinde planı otomatik yeniden hesaplar. Sürücü
    durum anlık görüntüsü (çözümlenen hava + olay konumu + EM-028 etkin kapasite)
    append-only canlı beslemeye (EM-090) yazılır ve bir sonraki turda **durum
    deposu** olarak geri okunur (yeni tablo/migration yok, süreçler arası çalışır)
  - **Değişim tespiti:** rüzgâr hızı/yönü, nem ve sıcaklık için EM-018 eşikleri
    yeniden kullanılır; konum için haversine mesafe tabanı
    (`AUTO_RECOMPUTE_POSITION_MOVE_KM`, vars. 1 km), kapasite için bağıl yüzde
    değişim (`AUTO_RECOMPUTE_CAPACITY_CHANGE_PCT`, vars. %10); debounce EM-018
    `SPREAD_TRIGGER_DEBOUNCE_MINUTES` ile aynı anti-flap penceresini korur
  - Yeniden hesaplama EM-018 `run_spread_forecast` (tüm ufuklar) + EM-029
    `compute_risk_index` pik bandını çağırır; ardından beslemeye tek bir
    `forecast` kaydı yazar (başlık `Plan güncellendi: …`, mesaj `Değişen: … —
    tepe risk: …`, kaynak `auto_recompute`)
  - Celery beat `auto_recompute_plans` (`AUTO_RECOMPUTE_ENABLED`, vars. `true`;
    `AUTO_RECOMPUTE_INTERVAL_MINUTES`, vars. 5 dk)
  - `GET /api/v1/spread/recompute-status?event_key=` (debounce/yeniden hesaplama kararı) ve
    `POST /api/v1/spread/recompute-sweep[?event_key=]` (talep üzerine tarama)
  - Operatör haritası (`/ui`): `flashLive` bir `plan_update` payloadı gördüğünde
    başlık + **değişen faktör etiketleri** + yeni tepe risk bandıyla gösterir
- EM-032: Eşik aşımı uyarısı — histerezis (E3)
  - `src/services/risk_alert.py`: aktif olayların EM-029 `Risk(t)` pik
    seviyesini değerlendirir; risk **bir üst seviyeye çıktığında** canlı
    beslemeye (EM-090) tek bir `alert` kaydı yazar (kaynak `risk_alert`)
  - **Histerezis (tekrar bastırma):** durum deposu olarak append-only canlı
    besleme okunur (yeni tablo/migration yok, süreçler arası çalışır);
    bir olay için yalnızca **daha önce uyarılan en yüksek bandın üstüne**
    çıkıldığında yeni uyarı üretilir — aynı seviyede tekrar yoklamalar
    sessiz kalır; `normal` seviye hiç uyarı üretmez
  - `POST /api/v1/risk-index/alerts/evaluate` — değerlendirmeyi çalıştırır
    ve uyarıları beslemeye yazar (`RISK_ALERTS_ENABLED`, vars. `true`)
  - Operatör haritası (`/ui`): uyarı geldiğinde **görsel bant** (kırmızı,
    yanıp sönen `#alert-banner`) + **sesli bildirim** (WebAudio ile
    üretilen iki-tonlu bip — ses dosyası yok) + titreşim; `🔔 Ses`
    aç/kapa düğmesi; harita 30 sn'de bir değerlendirmeyi yoklar
    (uyarılar WebSocket/REST ile tüm istemcilere akar)
- EM-030: Kapasite açığı zaman çizelgesi (E3)
  - `capacity_gap_timeline` (EM-029 servisinde): her aktif olay için ufuk
    bazlı **zaman serisi** (dakika, talep, sabit etkin kapasite, açık,
    risk, seviye) ve **ilk eşik aşım dakikası** — kritik banda
    (`risk_index >= RISK_INDEX_CRITICAL_NEAR_MAX`) giriş, ufuklar arası
    **doğrusal enterpolasyonla** bulunur (örn. `T+47 dk`); ilk ufuk zaten
    aşmışsa o ufuk (muhafazakâr üst sınır), hiç aşılmazsa `null`
  - Özet: en erken aşım yapan olay ve dakikası (`first_exceedance_event`)
  - `GET /api/v1/risk-index/timeline[?event_key=]` (bilinmeyen olay 404)
  - Komutan paneli (`/panel`): **Kapasite Açığı Zaman Çizelgesi** kartı —
    talep vs kapasite **çizgi grafiği** (satır içi SVG, harici kütüphane
    yok) ve başlıkta "Kapasite ne zaman yetmez? T+dk'da kritik"
- EM-029: Operasyonel risk indeksi — Risk(t) (E3)
  - `src/services/risk_index.py`: **Risk(t) = yayılım talebi / etkin
    kapasite** (iki taraf da EM-028 ha/saat biriminde, oran birimsiz);
    talep en güncel `FireForecast` birikimli poligonunun ortalama alan
    büyümesi (`area_ha / horizon_dk × 60`, EM-055 ile aynı tanım)
  - Yapılandırılabilir seviye bantları: `RISK_INDEX_NORMAL_MAX` (0.6),
    `RISK_INDEX_CAUTION_MAX` (0.9), `RISK_INDEX_CRITICAL_NEAR_MAX` (1.2)
    → `normal / dikkat / kritik-yakin / kritik`; kapasite 0 ve talep > 0
    iken `risk_index: null` + `kritik`
  - Meşgul/yolda kaynaklar etkin kapasiteye girmediği için indesten
    otomatik düşer (EM-031 bağlantısı); EM-073 bölge panelinin FWI
    `risk_index` alanına dokunulmaz (bağımsız servis)
  - `src/routes/risk_index.py`: **`GET /api/v1/risk-index`** (aktif tüm
    olaylar veya `?event_key=`; bilinmeyen olay 404) ve
    **`GET /api/v1/risk-index/config`**
  - Komutan paneli (`/panel`): **Olay Risk İndeksi — Risk(t)** kartı —
    olay × ufuk (T+30/60/120) renk kodlu tablo, talep/açık tooltip'i,
    en yüksek risk özeti
- EM-031: Kapasite kullanılabilirliği durum yönetimi (E3)
  - Durum sözlüğüne **`en_route` (yolda)** eklendi — müdahaleye tahsis
    edilmiş ancak henüz istasyonda olmayan kaynak; artık beş durum:
    `available / deployed / en_route / maintenance / out_of_service`
  - Etkin kapasite (EM-028) yalnızca `available` saydığı için durum
    değişimi **indeksi anında** etkiler; `PUT /api/v1/resources/{key}`
    ile `status` (Türkçe takma ad `yolda`, `en-route` kabul edilir)
    güncellenince `GET /api/v1/capacity/effective` yeni değeri döner
  - `capacity_summary` tür bazlı yeknâya `en_route` sayacı eklendi;
    envanter ekranında (filter + kayıt formu) **Yolda** seçeneği ve
    `em-badge--info` rozeti (tokens: `--color-accent`)
- EM-055: What-If ve dinamik yeniden hesaplama — rüzgâr değişimi senaryosu
  (E6)
  - `src/services/whatif.py`: operatör "rüzgâr 45° dönse ne olur?" diye
    sorduğunda EM-015 Rothermel motorunu **aynı çözülmüş girdilerle iki kez**
    çalıştırır — biri sarsılmamış (orijinal), biri rüzgâr yön/hız
    değişikliğiyle (senaryo). `predict_spread` `event_key` verilmediğinde
    yazmadığı için what-if **tamamen geçicidir (persist yok)**; iki taraf
    eşit koşullarda karşılaştırılır. Kaydırmalar **delta/çarpan** üretir
    (`wind_rotation_delta_deg`, `wind_speed_factor`); request'teki rüzgâr
    mevcut taban koşulunu taşır
  - **Kapasite açığı** EM-028'in tek biriminde: talep = senaryonun
    birikimli poligon alan büyümesi (ha/saat), arz = `effective_capacity`,
    açık = fark; orijinal ve senaryo için `gap_delta` ile
  - **Öneriler**: EM-023 maruziyet sıralaması geçici senaryo poligonlarına
    karşı yeniden hesaplanır — rüzgâr dönünce hangi yapıların **yeni**
    tehdit altına girdiği (`newly_threatened`) görünür
  - Hız hedefi: `compute_ms` ölçülür, `WHATIF_RECOMPUTE_TARGET_SECONDS`
    (varsayılan **10 sn**) ile `within_target` yanıta yazılır
  - `src/routes/whatif.py`: **`POST /api/v1/whatif/wind`** ve
    **`GET /api/v1/whatif/config`**
  - Operatör haritası (`operator_map`): **What-If (Rüzgâr)** paneli — yön
    değişimi ve hız çarpanı kaydırıcıları + "45° döndür" kısayolu; senaryo
    poligonları orijinalin **üzerine kesik mavi katman** olarak bindirilir,
    sayısal özet (alan, talep, etkin kapasite, kapasite açığı, tehdit
    sayısı, en erken etki, hesap süresi) panelde yan yana; 400 ms debounce +
    `AbortController` ile kaydırırken bile 10 sn içinde güncellenir
- EM-056: Kapasite değişimi what-if senaryosu (E6) — arz tarafı
  - `src/services/capacity_whatif.py`: komutanın *arz* sorusunu yanıtlar —
    "iki helikopter ve bir ekip eklersem kapasite açığı nasıl değişir?".
    EM-029 yayılım **talebi sabit** tutulur, varsayıms bir **kapasiteye**
    (canlı `effective_capacity` + istenen ek birimler tür başına ha/saat
    varsayımıyla değerlendirilerek) karşı yeniden fiyatlanır. Her aktif (veya
    seçilen) olay için ufuk bazında açık/risk bandı öncesi-sonrası ve
    pekiştirmenin gerçekten **çözdüğü** olaylar (açık vardı → kapandı)
    raporlanır. EM-055 gibi tamamen **geçicidir**: kaynak atanmaz, yazılmaz
  - `run_capacity_whatif` / `scenario_capacity` EM-029 motorunu
    (`_horizons_for`, `level_thresholds`) yeniden kullanır; `added_resources`
    `{crew|helicopter|uav: adet}` doğrulanır (bilinmeyen tür/negatif/tamsayı
    dışı → `CapacityWhatIfError`)
  - `src/routes/whatif.py`: **`POST /api/v1/whatif/capacity`** + config'e
    `capacity_attribution`; komutan paneli (`risk_panel`): **Kapasite
    What-If (EM-056)** kartı — ek kaynak girdileri, olay seçki, açık
    değişim tablosu ve "çözüldü" rozetleri
- EM-060: Yeniden hesaplama performans bütçesi — p95 gecikme ve otomatik
  ölçek küçültme (E6)
  - `src/models/perf_budget.py` (`RecomputeLatencySample`, migration
    `V017__recompute_latency_samples.sql`): her yayılım/what-if yeniden
    hesabının duvar saati gecikmesi, çözünen çözünürlüğü ve o anki hedefi
    tutan **yalnızca-ekleme telemetri** günlüğü (operasyonel resmi beslemez)
  - `src/services/perf_budget.py`: kayan pencerede (vars. son 50 örnek)
    **p95** gecikmeyi 10 sn hedefe karşı değerlendirir; örnek sayısı
    `PERF_BUDGET_MIN_SAMPLES` (vars. 5) altına inince karar verilmez
    (titreşimi önler). p95 hedefi aşınca `breached` işaretlenir ve
    `PERF_BUDGET_ENABLED` ise her sonraki yeniden hesaplama otomatik olarak
    **kaba çözünürlüğe** düşürülür (`_CoarseSettings` delege sarmalayıcı —
    EM-022 `_ModeSettings` deseniyle aynı — yalnızca `SPREAD_POLYGON_VERTICES`
    ve `SPREAD_HORIZON_MINUTES` değiştirilir)
  - **Uyarı (kenar tetiklemeli):** bütçe içi → bütçe dışı geçişinde canlı
    beslemeye (EM-090) tek bir `alert` yazılır; süreğen ihlalde tekrar
    üretilmez (`_previous_breached` histerezisi, `PERF_BUDGET_ALERTS_ENABLED`)
  - `src/routes/perf_budget.py`: `GET /api/v1/perf-budget`,
    `GET /api/v1/perf-budget/config`, `POST /api/v1/perf-budget/sample`
    (negatif gecikme → 400); `src/routes/whatif.py` rüzgâr ucu **eklenerek**
    entegre edildi: yeniden hesaplama bütçeye danışır, süreyi örnek olarak
    kaydeder ve yanıtta `perf_budget` alanını döndürür (yayılım tahmini
    yazılmaz — EM-055 geçicilik sözleşmesi korunur)
  - Komutan paneli (`risk_panel`): **Yeniden Hesaplama Bütçesi** kartı —
    p95 / hedef / örnek sayısı ve durum (bütçe içi · yetersiz örnek ·
    aşıldı/kaba çözünürlük); ayarlar `PERF_BUDGET_*` (`.env.example`)
- EM-061: Sıcaklık ve nem what-if parametreleri (E6)
  - `src/services/whatif.py`: EM-055 rüzgâr senaryosu **hava** düğmelerine
    genişletildi — `temperature_delta_c` (°C) ve `humidity_delta_pct` (yüzde
    puanı). Senaryo, çözülmüş taban sıcaklık/nemini deltalarla bozar; Rothermel
    motoru bu değerleri `fuel_moisture_pct` sabitlenmediğinde denge (ölü) yakıt
    nemi üzerinden tüketir, dolayısıyla **daha sıcak/kuru** senaryo yakıtı
    kurutup yayılımı hızlandırır, **daha soğuk/nemli** yavaşlatır — değişiklik
    alan/talep, kapasite açığı ve tehdit sıralamasına **otomatik** yansır
  - **Sıfırla = orijinal:** delta `0` iken senaryo çözülmüş taban hava
    değerlerini geri verir ve orijinalle birebir aynı sonucu üretir
    (tek-düğüm kontrol sözleşmesi korunur); senaryo sıcaklığı [-30, 60] °C,
    bağıl nemi [1, 100] % aralığına kırpılır; uç değer ±40 °C / ±60 puan
    aşarsa `WhatIfError` (→400)
  - Yanıta **`weather`** bloğu eklendi (orijinal/senaryo sıcaklık-nem +
    deltalar); `POST /api/v1/whatif/wind` gövdesi iki yeni opsiyonel alan alır
    (EM-060 telemetrisiyle birlikte); operatör haritasındaki **What-If**
    paneline **Sıcaklık Δ** ve **Nem Δ** kaydırıcıları + **Sıfırla**
    davranışı eklendi, özet kartına "Sıcaklık / Nem" satırı geldi
- EM-033: Zamana bağlı kapasite modeli — yoldaki kaynakların varışı (E3)
  - `src/models/inventory.py` (`SuppressionResource.arrival_eta`, migration
    `V018__resource_arrival_eta.sql`): `en_route` (yolda) birimin istasyona
    **tahmini varış anı** (naive-UTC); `None` → sabit varış yok, EM-031
    davranışı korunur (müsait olmayan hiçbir ufka katkı vermez)
  - `src/services/capacity.py`: `enroute_arrival_minutes` (yalnızca ETA'sı olan
    yoldaki birimler, geçmiş ETA "şimdi"ye kırpılır), `capacity_at_minute`
    (taban kapasite + o dakikaya kadar varmış birimlerin tür başına ha/saat
    varsayımı) ve `capacity_schedule` (her ufuk dakikasında kapasite + adım
    adımlı `arrivals` listesi) — **anlık** etkin kapasite (EM-028) değişmedi,
    yalnızca **zaman ekseninde** tamamlanır
  - `src/services/risk_index.py`: `capacity_gap_timeline` artık **sabit**
    kapasite yerine her ufku o dakikadaki kapasiteyle fiyatlar (`time_dependent`
    vars. `TIME_DEPENDENT_CAPACITY`); risk eşiği ve ilk kritik aşım dakikası
    pekiştirmenin varışını yansıtır (açık kapanır / aşım ertelenir); yanıta
    `capacity_schedule` bloğu eklenir. `effective_capacity`/`compute_risk_index`
    (anlık görünüm) bilinçli olarak **sabit** kalır
  - `GET /api/v1/capacity/schedule[?minutes=]` (yeni uç); envanter
    create/update `arrival_minutes` (dakika-şimdiden) kabul eder (negatif →
    400); `src/config/settings.py` + `.env.example` (`TIME_DEPENDENT_CAPACITY`)
  - UI: komutan paneli çizelgesinde kapasite **yatay çizgi** yerine
    **basamaklı** çizgi (yoldaki kaynak varış ETA'sında yukarı adım atar);
    envanter ekranına **Varış ETA (dk)** alanı; `tests/unit/test_time_dependent_capacity.py`
    (13 test: varış bucket'ı, adım fiyatlaması, ilk aşımın ertelenmesi, sabit
    geri dönüş, CRUD, uç)
- EM-028: Kapasite biriminin tanımı ve normalizasyonu — kapasite açığı ve risk
  indeksi (E3)
  - `src/models/capacity.py` → `CapacityAssumption` (V016 migration): her
    müdahale kaynak tipi (ekip / helikopter / İHA) için yöneticinin
    düzenleyebildiği **etkin müdahale kapasitesi (ha/saat)** varsayımı; tek
    satır/tek tip, `resource_type` benzersiz
  - `src/services/capacity.py`: varsayımları config default'larından
    tohumlar (`ensure_defaults`), listeler/günceller (Türkçe tip takma
    adlarını `inventory.normalize_type` ile çözer, negatif/bilinmeyen tip
    reddedilir) ve envanteri **tek birime (ha/saat) normalize eder** —
    `effective_capacity` = Σ (müsait kaynak sayısı × tip varsayımı)
  - `src/routes/capacity.py`: **`GET/PUT /api/v1/capacity/assumptions`**
    (yönetici düzenlemesi; geçersiz tip 400) ve
    **`GET /api/v1/capacity/effective`**
  - Komutan paneli (`risk_panel`): kapasite hesabına `assumptions` ve
    `effective` (ha/saat) blokları eklendi; panelde **Kapasite Varsayımları
    (ha/saat)** kartı — tür başına düzenlenebilir input + Kaydet — ve
    "Etkin kapasite (ha/saat)" satırı; böylece kapasite ile risk aynı
    birimde okunur
  - Yapılandırma: `CAPACITY_HA_PER_HOUR_CREW/HELICOPTER/UAV`
- EM-052: Proaktif kaynak konumlandırma — öneri konumları ve rotalar (E5)
  - `src/services/positioning.py`: bir yangın olayı için **müsait** ekip
    üsleri (`crew_bases`) + müdahale kaynaklarını (`suppression_resources`,
    EM-103) toparlar; her birini EM-011 yol ağı grafiği üzerinden olay
    konumuna **kapanış-duyarlı en kısa süre** rotasıyla çizer ve **ETA**'ya
    göre sıralar (en yakın/ulaşılabilir önce). Rota geometrisi,
    `path_segment_keys` uç uca zincirlenerek LineString olarak geri kurulur;
    kapanış varsa gecikme (`delay_vs_open_minutes`) için ikinci (açık) grafik
    yalnızca gerektiğinde kurulur. Öneriler **her istekte canlı** hesaplanır
    (kalıcı kayıt yok); `positioning_layer` harita için konuşlanma noktası
    (Point) + rota (LineString) üretir, olay yoksa/ağ boşsa hata yerine boş
    koleksiyon döner
  - `src/routes/positioning.py`: **`GET /api/v1/positioning/proposals`**
    (`event_key` zorunlu, `limit` 1..50) → sıralı öneriler; bilinmeyen olay
    404, yol ağı yok 409
  - Operatör haritası: `positioning` katmanı (varsayılan kapalı/tembel) —
    rota üzerinde sabit **`T+dk` ETA etiketi**, **Konuşlanma Önerileri**
    paneli; bir öneri seçilince harita rotaya **otomatik odaklanır** ve popup
    açılır; olay filtresi değişince rota/öneriler yeniden hesaplanır
  - Yapılandırma: `POSITIONING_MAX_PROPOSALS` (varsayılan 5); erişim hızı
    `ROAD_ACCESS_SPEED_KMH` yeniden kullanılır
- EM-090: WebSocket ile canlı güncelleme — Entegrasyon API (E9)
  - `src/models/live.py` → `LiveUpdate` (V014 migration): olay/tahmin/uyarı
    değişikliklerinin **monoton akışı** (id = sıra numarası); `kind`,
    `event_key`, `title`/`message`, `payload_json`, `source`
  - `src/services/live.py`: `record_update` (kind doğrular; kapalıyken no-op),
    `recent_updates`/`feed` (`since` imleciyle telafi), `latest_id` ve
    best-effort `safe_record_update` (akış hatası tetikleyiciyi asla düşürmez)
  - `src/routes/live.py`: **`WS /ws/live`** — bağlantıda `?since=<id>` ile
    yakalanan **snapshot** çerçevesi, ardından kısa aralıklı yoklama ile yeni
    değişiklikleri `update` olarak iter; boşta `ping` keepalive. REST yedeği
    **`GET /api/v1/live/updates?since=<id>`**. Tek kaynak veritabanı olduğu
    için ayrı Celery sürecinin yazdığı güncellemeler de istemciye ulaşır
  - Yayınma noktaları: `POST /api/v1/events/manual` ve fires/sync → `fire_event`,
    `POST /api/v1/spread/predict` → `forecast`, `POST /api/v1/fwi/compute`
    (eşik üstü bölge varsa) → `alert`
  - Operatör haritası (`operator_map.html`): sayfa yenilemeden canlı akış —
    WebSocket istemcisi, **otomatik yeniden bağlanma** (üstel geri çekilme,
    son imleci koruyarak kaçırılanları telafi), canlı durum rozeti, güncelleme
    bildirimi (flash) ve aktif katmanların debounce'lu yeniden yüklenmesi;
    WebSocket yoksa REST yoklamasına düşer
  - Yapılandırma: `LIVE_UPDATES_ENABLED`, `LIVE_POLL_INTERVAL_SECONDS`,
    `LIVE_HEARTBEAT_SECONDS`, `LIVE_MAX_CATCHUP` (testte hızlı yoklama)
- EM-023: Tehdit altındaki yerleşim, yol ve altyapı analizi — maruziyet (E2)
  - `src/models/exposure.py` → `ExposedAsset` (V013 migration): OSM'den alınan
    yerleşim (`settlement`) ve enerji hattı (`power_line`) varlıkları; örnek
    nokta + tam WKT geometri (POINT/LINESTRING) ve `population`/`voltage` gibi
    etiketler. Yollar EM-011 `road_segments` üzerinden okunur (çoğaltılmaz)
  - `src/services/exposure.py`: (1) Overpass ile yerleşim/enerji hattı alımı
    (`ExposureOverpassClient`/`sync_exposed_assets`, testte enjekte edilebilir
    `http_get`), (2) her varlığı EM-015 ufuk poligonlarıyla **shapely**
    kesiştirip **ilk etkilenme zamanı T+dk**'yı hesaplar — artık yalnızca
    {30/60/120} kovası değil, kaydedilen ufuk başına **yayılma hızı** ve
    ateş noktasına uzaklıkla iki ufuk arasında **enterpolasyon** (ör. T+47);
    (3) her varlığa **öncelik skoru** (etki zamanı + varlık kritikliği + nüfus,
    log ölçek) atar ve listeyi bu skora göre sıralar (koruma/tahliye önceliği)
  - Ölçek & dayanıklılık: adaylarda **bbox ön-eleme**, **shapely hazırlanmış
    (prepared) geometri** ve tablo parmak izine (girdi içeriği + varlık/yol
    sayıları) bağlı kısa ömürlü **TTL önbellek**; bozuk geometri loglanır
  - İçe alma korumaları: bbox alan sınırı (`EXPOSURE_IMPORT_MAX_BBOX_AREA_DEG2`,
    aşan istek → **400**), öğe sayısı üst sınırı (`EXPOSURE_IMPORT_MAX_ASSETS`),
    öncelikli yerleşim sınıfları filtresi, kısmi enerji hattı işareti
  - Uç noktalar: `POST /api/v1/exposure/import` (bbox doğrulama → 400, Overpass
    hatası → 502), `GET /api/v1/exposure[?event_key=]` (öncelik sıralı liste,
    `earliest_impact_minutes` + `by_type` özetleri, `priority_score`)
  - Operatör haritasına 9. katman **`exposure`** eklendi; mor renk ailesi (≤30
    koyu mor / ≤60 mor / ≤120 açık mor) risk bölgesi renklerinden ayrışır; sol
    üstteki "Tehdit Altındaki Yapılar" panelinde **olay filtresi**, canlı sayaç,
    öncelik skoru ve insanîleştirilmiş popup; `demo_seed.py` etiketli demo
    maruziyet verisi üretir ve sahte demo tahminleri `demo_forecast` ile işaretler

### Fixed
- Docker/uygulama konfigürasyon tutarsızlıkları (operatör haritası boş kalıyordu)
  - `create_fastapi_app()` varsayılanı `"testing"` yerine ortamdan türetilen
    config'e (`APP_ENV`/`FLASK_ENV`, yoksa `development`) bırakıldı: uvicorn
    artık `DATABASE_URL`'i yok sayıp boş **in-memory SQLite** okumuyor; Docker
    ve demo profilleri gerçek veritabanını görüyor (harita boş kalmıyor)
  - `docker-compose.yml` ortak ortamına açık `APP_ENV=${APP_ENV:-production}`
    eklendi (demo override'ı `APP_ENV=demo` kazanır)
  - Kalıcı Postgres volume'ünde `create_all()` mevcut tabloyu değiştirmediği ve
    SQL migration çalıştırıcısı hiç çağrılmadığı için EM-012 kolonları
    (`fire_clusters.sources/latency_minutes/deduplicated_count` ve
    `fire_observations.product/published_at/latency_minutes`) eksik kalıyordu;
    bu kolonlar modele uygun şekilde eklendi — `/api/v1/fires` ve `fires`
    katmanı 500 yerine gerçek uydu kümelerini döndürüyor

### Added
- EM-104: Deterministik sentetik veri üreteci (E11)
  - `src/services/synthetic.py`: tohumdan (`seed` → sha256 → deterministik akış)
    yapılandırılabilir senaryo üretir: yangın konumu, rüzgâr geçmişi
    (rastgele yürüyüş: hız/yön/sıcaklık/nem), iletişim kesinti bölgeleri ve
    kaynak dağılımı (üs + ekip/helikopter/İHA, durum ağırlıklı atama);
    `standart` / `firtina` / `kaynak-dagitik` ön ayarları (`PRESETS`)
  - **Aynı tohum aynı sonucu verir**: konfigürasyon kanonik JSON + sha256 ile
    `config_hash`/`result_hash` olarak `ScenarioRun` denetim kaydına yazılır
    (V009 migration); aynı (seed, config) tekrarında tek denetim kaydı kalır
  - **Açık etiketleme**: her sentetik kayıt `synthetic: true`,
    `synthetic_label` ("SENTETİK VERİ — demo amaçlı üretildi…") ve `SYN-`
    anahtar ön eki taşır; kalıcı yazımda `source="synthetic"`, not/reason
    alanlarında etiket tekrarlanır; `DELETE /api/v1/scenarios/synthetic/{tag}`
    etiket bazlı temizlik sağlar (tekrar tohumlama idempotent)
  - Uç noktalar: `POST /api/v1/scenarios/synthetic/generate` (ops.
    `persist`), `GET /api/v1/scenarios/presets`,
    `GET /api/v1/scenarios/synthetic/runs[/{run_key}]`
  - `scripts/demo_api.py --seed N --preset X`: demo sunucusu sentetik senaryoyu
    açılışta üretir (`--no-synthetic` ile atlanabilir)
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
  - Koordinatör ekranı `GET /inventory` (EM-075 bileşenleriyle): filtreli
    tablo, ekle/düzenle/sil formu, kapasite kartı ve CSV yapıştırma kutusu;
    `/ui` lejantı ve `/panel`'den karşılıklı bağlantı
  - Kapasite döngüsü kapatıldı: envanter varlıkları `/ui` "Müdahale
    Kaynakları" katmanına (`kind=suppression_resource`, türe göre renk) ve
    `/panel` kapasite kartına (`capacity.inventory`) bağlandı
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
- EM-022: Yayılım modeli performans optimizasyonu (vektörleştirme + önbellek)
  - cProfile ile referans senaryoda sıcak nokta ölçüldü: tahmin başına ~216
    köşe-bazlı kara örtüsü sorgusu (`fuel_transition_polygon`) süre
    baskınlığındaydı (~54 ms); `GET /api/v1/spread/performance/profile`
    en sıcak fonksiyonları canlı raporlar
  - `src/services/layer_cache.py`: oturum bazlı, zayıf referanslı (sızıntısız)
    TTL önbelleği — hava/topo/yakıt girdi okumaları ve engel yüklemeleri
    karelenir (koordinat kuantumu `SPREAD_PERF_CACHE_GRID_DEG`), engel
    yazmalarında otomatik geçersiz kılınır; `SPREAD_PERF_ENABLED` kapalıysa
    birebir eski skaler yol çalışır (geri alınabilir)
  - Vektörleştirme: tek bounding-box sorgusu + numpy `argmax` ile toplu yakıt
    sınıfı örneklemesi — skaler yolla **bitbir aynı** poligon üretir (birim
    testle kilitli)
  - `POST /api/v1/spread/performance/benchmark`: optimizasyon öncesi/sonrası
    süreleri ölçer, `SpreadPerformanceRun` olarak kalıcılar (V012 migration),
    10 sn operatör hedefine göre `target_met` işaretler; ölçülen ~9-18x hızlanma
  - `GET /api/v1/spread/performance` saklanan koşular + canlı önbellek istatistikleri
- EM-021: Kara/deniz maskesi ve doğal engeller
  - `natural_barriers` tablosu (V011 migration): deniz/göl/geniş nehir su
    kütleleri tam engel, yol/ırmak yavaşlatma katsayılı kısmi engel olarak
    operatör tarafından kaydedilir (`POST/GET/DELETE /api/v1/spread/barriers`)
  - Ufuk poligonları kıyı hattında kırpılır — su kütlelerine taşmaz; tam
    engeller yayılımdan tamamen hariç, kısmi engeller katsayıyla yavaşlatır
    (`SPREAD_BARRIERS_ENABLED`)
  - EM-020 belirsizlik zarfı da engel kırpmasından geçer; haritaya 8. katman
    olarak `barriers` eklendi
- EM-020: Rüzgâr ansambli ile yayılım belirsizliği gösterimi
  - Her ufuk için iyimser/beklenen/kötümser üçgen poligon: rüzgâr yönü
    ±`SPREAD_UNCERTAINTY_WIND_DIR_DELTA_DEG`, hızı ±`SPREAD_UNCERTAINTY_WIND_SPEED_FRACTION`
    bozumlu çoklu çalıştırma (`POST /api/v1/spread/uncertainty`)
  - Güven bandı genişliğinden türeyen **model güven göstergesi**; operatör
    haritasında `uncertainty` katmanı (kümülatif 8 katman)
- EM-019: Ölü yakıt nemi modeli (1h/10h/100h sınıfları)
  - Hava sıcaklığı + bağıl nemden sentetik günlük döngüyle denge nemi
    sınıfları üretilir (`src/services/fuel_moisture.py`); yakıt modeline göre
    etkin nem hesaplanıp yayılım motoruna beslenir
    (`FUEL_MOISTURE_MODEL_ENABLED`, koşullandırma penceresi ve genlikler
    konfigürasyonla)
  - `GET /api/v1/spread/fuel-moisture` uç noktası sınıf nemlerini ve etkin nemi döner
- EM-018: Yeni olaylarda ve anlamlı girdi değişiminde otomatik tahmin tetikleme
  - `src/services/spread_trigger.py`: periyodik Celery taraması aktif olayları
    denetler; rüzgâr hızı/yön, sıcaklık ve nem için "anlamlı değişim"
    eşikleri, olay başına debounce penceresi (`SPREAD_TRIGGER_DEBOUNCE_MINUTES`)
  - Manuel olay yazımı da tetiklemeyi çağırır; `GET /api/v1/spread/trigger-status`
    ve `POST /api/v1/spread/trigger-sweep` operasyon uçları
- EM-017: Yayılım değerlendirme metrikleri (IoU, alan ve varış zamanı hatası)
  - Gerçek çevre WKT'si ile saklanan tahmin kıyaslaması: `POST /api/v1/spread/evaluate`,
    `GET /api/v1/spread/metrics[?event_key=&model_version=]` ve sürüm bazlı
    ortalama özet `GET /api/v1/spread/metrics/summary` (V010 migration)
- EM-016: Yakıt geçişine duyarlı yayılım poligonu
  - Ufuk poligonu köşe-bazlı yeniden şekillendirilir: her köşenin düştüğü
    arazi örtüsü yakıt modeliyle yerel hız hesaplanır, geçiş zonaları
    raporlanır (`FUEL_TRANSITION_ENABLED`; kapalıysa saf eliptik EM-015 yolu)
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
- EM-011: EFFIS tarihsel yangın çevresi içe aktarımı
  - `HistoricalFirePerimeter` modeli ve `src/services/effis.py` içe aktarıcısı
    (yıl bazlı sorgu, alan/kenar uzunluğu doğrulama; V004 migration)
  - Kalibrasyon/validation ayrımı: historical year'ın yangın mevsimine göre
    `split` etiketiyle saklanması; spread motoru validasyonunda kullanılabilir
  - `GET /api/v1/historical-fires[/dataset]`, `POST /api/v1/historical-fires/import`
    ve `POST /api/v1/historical-fires/splits` uç noktaları; Celery beat ile
    dönemsel senkronizasyon

### Fixed
- Demo verisi tamamlandı (`scripts/demo_api.py`): FWI bölge günleri, aktif
  yol kapatması, aktif olay ve EM-103 envanter kayıtları eklenmediği için
  `/panel` ve envanter ekranları demo modunda boş kalıyordu (import edilen
  seed modelleri hiç kullanılmıyordu)
- `docs/api/README.md`: kodda var olmayan bayat `POST /api/v1/predictions`
  bölümü kaldırıldı (yayılım tahmini EM-015 bölümündeki gerçek uçla belgeli)
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
