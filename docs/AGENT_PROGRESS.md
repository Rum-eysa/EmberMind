# Agent Progress — agent/task-automation

Otonom görev yürütme günlüğü. Dal: `agent/task-automation` (main'e asla commit
yok, force push yok, PR draft olarak açılır, merge edilmez).

## Baseline (değişikliklerden önce)

- `make` Windows'ta yok → kapılar eşdeğer komutlarla çalıştırıldı:
  `black --check src/ tests/` ✅ (110 files unchanged), `mypy src/` ✅ (75 files),
  `pylint src/` ✅ 10.00/10, `pytest tests/` ✅ **463 passed**.
- main HEAD: `0c46ec5` (EM-028). Bu oturumun ilk commit'i: `6be70a4`
  `feat(EM-055)` (önceki oturumda tamamlanıp commit'lenmemiş iş; kullanıcı
  onayıyla bu dala alındı + eksik `WHATIF_RECOMPUTE_TARGET_SECONDS`
  settings/.env.example girdileri tamamlandı).

## Görev kaynağı ve eleme

`gh issue list`: 84 açık issue (EM-001..EM-154). GitHub issue'ları kodla senkron
değil: çoğu görev kodda **zaten implemente edilmiş** ama issue açık bırakılmış
(kapama kararı kullanıcıya ait — önceki oturum convention'ı). Bu yüzden görev
listesi issue başlığına değil, **kod boşluğuna** göre süzüldü:

- `src/` içinde EM-id taraması: EM-005..023, 028, 052, 055, 072, 073, 075, 090,
  103, 104, 109 izleri mevcut → bu epiklerin çekirdeği tamam.
- İnsan/altyapı gerektirenler (E10 auth, E12 cloud deploy, E13 E2E/usability,
  E14 demo videosu/pitch, E16 wont) → bu oturumun kapsamı dışı.
- Devasa ML epikleri (E4 sessiz bölge Isolation Forest, E7 sınır ötesi) → tek
  oturumda gerçekçi değil; Mock ile "bitti" göstermeme kuralı gereği girilmedi.

## Sıralı plan (bağımlılık: model → servis → route → UI → test/doküman)

| # | Görev | Epic | Durum | Gerekçe |
|---|-------|------|-------|---------|
| 1 | EM-031 Kapasite kullanılabilirlik durum yönetimi (#31) | E3 | DONE | `en_route` (yolda) durumu sözlükte yoktu; durum→kapasite bağı kısmen var |
| 2 | EM-029 Risk indeksi hesaplama (#29) | E3 | DONE | Risk(t)=yayılım talebi/kapasite ufuk bazlı hiç yoktu; eşikler yapılandırılabilir eklendi |
| 3 | EM-030 Kapasite açığı zaman çizelgesi (#30) | E3 | DONE | EM-029 verisi üzerine çizgi grafik + enterpolasyonlu ilk kritik aşım dakikası |
| 4 | EM-032 Eşik aşımı uyarısı (#32) | E3 | DONE | EM-029/030'a bağlı; histerezis (besleme peak-latch) + canlı besleme "alert" + görsel/sesli |
| 5 | EM-056 Kapasite değişimi senaryosu (#56) | E6 | DONE | EM-055'in arz-tarafı karşılığı; talep sabit, varsayıms kapasiteye karşı yeniden fiyatlama |
| 6 | EM-060 Yeniden hesaplama performans bütçesi (#60) | E6 | DONE | p95 ölçümü + aşım uyarısı + otomatik ölçek küçültme |
| 7 | EM-061 Sıcaklık ve nem what-if parametreleri (#61) | E6 | DONE | EM-055 rüzgâr senaryosunun hava-tarafı genişletmesi; kaydırıcı + delta + Sıfırla |
| 8 | EM-033 Zamana bağlı kapasite modeli (#33) | E3 | DONE | yoldaki kaynağın varış ETA'sı ile çizelge kapasitesi basamaklanır (sabit değil) |
| 9 | EM-057 Dinamik otomatik yeniden hesaplama (#57) | E6 | DONE | rüzgâr/konum/kapasite değişince plan otomatik yenilenir + "ne değişti?" özeti |
| 10 | EM-059 Senaryo kaydetme ve paylaşma (#59) | E6 | DONE | geçici what-if koşularının üzerine girdi-kaydı + token'lı paylaşım bağlantısı |
| 11 | EM-062 What-if geçmişi ve geri alma (#62) | E6 | DONE | otomatik yuvarlanan son-10 koşu listesi + tek tık geri alma |
| 12 | EM-047 Öneri kabul/ret/düzenleme (#47) | E5 | DONE | EM-052 önerisi üzerinde 3 aksiyon; kabul/düzenle kaynağı yolda'ya çeker; her karar denetim kaydı |
| 13 | EM-046 Öneri gerekçesi / açıklanabilirlik (#46) | E5 | DONE | her öneri için "neden?" + reddedilen alternatifler ve gerekçeleri; build_proposals'ı açıklar, yeniden sıralamaz |
| 14 | EM-049 Kaynak tipine göre ETA — kuş uçuşu vs yol ağı (#49) | E5 | DONE | hava kaynakları (helikopter/İHA) kuş uçuşu ETA, kara ekipleri yol ağı; öneri/rota/konuşlanmada `travel_mode` |
| 15 | EM-048 Önerinin etki karşılaştırması (#48) | E5 | DONE | "uygulanırsa" vs "uygulanmazsa" risk ufuk bazında yan yana; EM-056 re-pricing motoru + EM-052 önerileri; canlı/tavsiye, kalıcılık yok |
| 16 | EM-053 Çifte atama / kaynak çakışma önleme (#53) | E5 | DONE | kabul/düzenle artık başka olaya atanmış birimi 409 ile engeller; müsaite alma + görev bitişi otomatik müsait; atama EM-047 denetim kaydından türer (migration yok) |
| 17 | EM-051 Kabul edilen öneriden saha görev kartı (#51) | E5 | DONE | hedef (olay+koordinat) + varış (ETA/arrival_eta) + risk notu (EM-029 tepe bandı); kart EM-047 denetim anlık görüntüsünden canlı kurulur, kalıcılık yok |
| — | EM-058 Yol kapalılığı (#58) | E6 | ATLANDI | **zaten mevcut**: closure endpoint + kapama-farklı yönlendirme + `build_proposals` — gerçek boşluk değil |

## Varsayımlar ve kararlar

- **EM-055 commit'i**: önceki oturumda tamamlanıp No-Auto-Push ile bekletilen iş,
  kullanıcı onayı (soru-cevap) ile bu dala tek commit alındı.
- **make yok**: Windows PowerShell'de `make` bulunamadı; `make ci-check` yerine
  aynı kapılar (`black`, `pylint`, `mypy`, `pytest`) + repo convention'ı `bandit`
  elle çalıştırılıyor.
- **Issue kapatma yok**: tamamlanan görevlerin issue'su kapatılmaz (kullanıcı
  kararı); issue'ya yalnızca özet yorum atılır.
- **EM-029 formül yorumu:** issue'nun sözel formülü `alan(t)/kapasite(t)`
  boyutsal olarak saat verir; yerine EM-055'in yayınlanan `gap = talep −
  kapasite` semantiğiyle tutarlı **birimsiz oran** (ha/saat talep ÷ ha/saat
  etkin kapasite) seçildi — `>1` yangının kapasiteden hızlı büyümesi demek.
  Ufuklar `SPREAD_HORIZON_MINUTES`'ten (30/60/120) okunur, sabitlenmez.
- **EM-029 risk indeksi**, mevcut EM-073 panelindeki `risk_index` (şu an FWI
  aynalama) alanını **değiştirmez**; yeni bağımsız `Risk(t)` endeksi ayrı
  servis/endpoint olarak eklenir (EM-073 kabul testleri bozulmaz).
- **EM-031**: `out_of_service` korunur, `en_route` eklenir; kapasite hesabı
  yalnızca `available` saydığı için `en_route` otomatik hariç → "durum değişimi
  indeksi hemen etkiler" kriteri bu yolla sağlanır.
- **EM-030 ilk aşım tanımı:** "eşik aşımı" örnek metni ("T+47 dk'da kritik")
  kritik bandına giriş olarak yorumlandı → eşik `RISK_INDEX_CRITICAL_NEAR_MAX`
  (1.2). Motor yalnızca kesikli ufukta tahmin verdiği için aşım dakikası
  komşu iki ufuk arasındaki oranda **doğrusal enterpolasyon** ile bulunur;
  kapasite zamanla sabit alınır (anlık etkin kapasite, EM-028).
- **EM-032 histerezis:** yeni tablo/migration yerine mevcut append-only canlı
  besleme (EM-090 `alert` satırları) durum deposu olarak okundu → süreçler
  arası (Celery/API) tutarlı. **peak-latch:** yalnızca önceki en yüksek
  uyarılan bandın üstüne çıkınca uyarı; bu muhafazakâr davranış düşüş-sonrası
  aynı tepeye dönüşte tekrar uyarmaz (kabul kriteri "tekrarları bastır"
  ile tutarlı). Ses = WebAudio bip (dosya asset yok, kapsam büyütmeme).
- **EM-056 arz-tarafı what-if:** EM-055 rüzgâr (talep) what-if'inin tersi.
  Yayılım tahmini **yeniden hesaplanmaz** (talep sabit); yalnızca kapasite
  değiştirilir → EM-029 `_horizons_for` ile açık/bant yeniden fiyatlanır.
  Ek birimler `assumption_map`'daki tür başına ha/saat varsayımıyle
  değerlendirilir (canlı envantere dokunulmaz, rezervasyon yok). `resolves_gap`
  = mevcut açık >0 VE senaryo açığı ==0. Endpoint hatası `RiskIndexError`
  (bulunamayan olay) bilinçli olarak **400** (wind what-if ile tutarlı; 404
  risk-index GET'in aksine POST gövde hatası).

## Görev logları

### EM-031 — Kapasite kullanılabilirliği durum yönetimi (#31) — DONE
- **Eksik analizi:** `RESOURCE_STATUSES` dört duruma sahipti; issue'nun
  istediği "yolda" (`en_route`) yoktu. Durum→kapasite bağı zaten doğru
  kuruluymuş (`effective_capacity` yalnızca `available` sayar) ama bu
  sözlüğe eklenince otomatik çalışır hale geldi.
- **Kapsam:** `src/models/inventory.py` (durum + yorum),
  `src/services/inventory.py` (`STATUS_ALIASES`: en_route/en-route/enroute/
  yolda; `capacity_summary` `en_route` sayacı),
  `src/static/inventory.html` (filtre + form `Yolda`, `STATUS_TR`,
  `em-badge--info`), `src/static/components.css` (`.em-badge--info`),
  testler (`test_inventory.py`, `test_capacity.py` — 4 yeni test),
  CHANGELOG + docs/api.
- **Kanıt:** durum `en_route` yapılınca `GET /api/v1/capacity/effective`
  anında düşüyor (servis + endpoint testi). Migration gerekmedi (String
  kolon, CHECK yok).
- **Kapılar:** black/mypy/pylint(10.00)/bandit(0) yeşil; pytest **467**.
- **Commit:** `feat(EM-031): ...` (bu dal).

### EM-029 — Operasyonel risk indeksi Risk(t) (#29) — DONE
- **Eksik analizi:** Olay bazlı, ufuk bazlı Risk(t) hiç yoktu; EM-073 paneli
  yalnızca FWI tabanlı BÖLGE riski gösteriyordu. Kapasite (EM-028) ve talep
  tanımı (EM-055 `demand_ha_h`) mevcuttu → yeni bağımsız servis bunların
  üzerine kuruldu, hiçbiri değiştirilmedi.
- **Kapsam:** `src/config/settings.py` + `.env.example`
  (`RISK_INDEX_NORMAL_MAX/CAUTION_MAX/CRITICAL_NEAR_MAX`),
  `src/services/risk_index.py` (demand/band sınıflandırma/en güncel
  `FireForecast` seçimi/boş kapasite → `null`+`kritik`/peak+summary),
  `src/routes/risk_index.py` (`GET /api/v1/risk-index[?event_key=]` 404
  dahil, `GET /api/v1/risk-index/config`), `src/fastapi_app.py` kaydı,
  `risk_panel.html` **Olay Risk İndeksi — Risk(t)** kartı (renk kodlu
  olay×ufuk tablosu, tooltip, özet), `tests/unit/test_risk_index.py`
  (18 test), CHANGELOG + docs/api.
- **Bağlantılar:** EM-031 — meşgul/yolda kaynak kapasiteye girmediği için
  indesten otomatik düşer (testyle kilitli). EM-030 bu payload'ın
  `gap_ha_h` alanını çizecek; EM-032 `level` değişimini izleyecek.
- **Kapılar:** black/mypy(77 dosya)/pylint(10.00)/bandit(0) yeşil;
  pytest **485** (467 + 18 yeni).
- **Commit:** `feat(EM-029): ...` (bu dal).

### EM-030 — Kapasite açığı zaman çizelgesi (#30) — DONE
- **Eksik analizi:** EM-029 olay×ufuk verisini sayısal tablo olarak
  veriyordu; issue zaman ekseninde **çizgi grafik** + "ilk eşik aşım
  zamanı" istiyordu. Ayrı depolama/servis gerekmez → EM-029 servisinde
  `capacity_gap_timeline` + `_first_exceedance` eklendi (veri kaynakları
  yeniden kullanıldı).
- **Kapsam:** `src/services/risk_index.py` (`capacity_gap_timeline`,
  `_first_exceedance` enterpolasyonu), `src/routes/risk_index.py`
  (`GET /api/v1/risk-index/timeline`), `risk_panel.html` **Kapasite Açığı
  Zaman Çizelgesi** kartı (satır içi SVG talep vs kapasite çizgisi, kritik
  aşım işaretçisi, başlıkta T+dk), `tests/unit/test_risk_index.py` (+8
  timeline testi: seri/enterpolasyon T+100, aşım yok, sıfır kapasite,
  en-erken-özet, endpoint 200/404, HTML), CHANGELOG + docs/api.
- **Karar:** harici grafik kütüphanesi eklenmedi (kapsam büyütmeme);
  token tabanlı satır içi SVG. Enterpolasyon varsayımı yukarıda.
- **Kapılar:** black/mypy(77)/pylint(10.00)/bandit(0) yeşil;
  pytest **493** (485 + 8 yeni).
- **Commit:** `feat(EM-030): ...` (bu dal).

### EM-032 — Eşik aşımı uyarısı, histerezis (#32) — DONE
- **Eksik analizi:** Canlı beslemede `alert` türü ve EM-090 WebSocket/REST
  altyapısı zaten vardı; ancak risk **seviye eskalasyonunda** uyarı yazan
  bir değerlendirici ve operatörde **sesli** bildirim yoktu. Harita alert'i
  yalnızca metin olarak flash'lyordu.
- **Kapsam:** `src/config/settings.py` + `.env.example`
  (`RISK_ALERTS_ENABLED`), `src/services/risk_alert.py`
  (`evaluate_risk_alerts`, beslemeden `_last_alerted_index` peak-latch
  histerezisi; normal uyarmaz), `src/routes/risk_index.py`
  (`POST /api/v1/risk-index/alerts/evaluate` — session commit ile kalıcı),
  `operator_map.html` (`#alert-banner` görsel bant, `beepTwice` WebAudio
  sesli bildirim, `🔔 Ses` aç/kapa + ilk-jest audio prime, `navigator.vibrate`,
  30 sn'de bir evaluate yoklaması), `tests/unit/test_risk_alert.py`
  (9 test), CHANGELOG + docs/api.
- **Kanıt:** dikkat'e çıkışta 1 uyarı; aynı seviyede tekrar→0 (histerezis);
  kritik'e daha çıkış→yeni uyarı; normal/forecast-yok/kapalı→0 (test).
- **Kapılar:** black/mypy(78)/pylint(10.00)/bandit(0) yeşil;
  pytest **502** (493 + 9 yeni).
- **Commit:** `feat(EM-032): ...` (bu dal).

### EM-056 — Kapasite değişimi what-if senaryosu (#56) — DONE
- **Eksik analizi:** EM-055 rüzgâr (talep-tarafı) what-if'i mevcuttu ama
  komutanın *arz* sorusu ("ek kaynak açığı nasıl değiştirir?") karşılıksızdı.
  Yeni yayılım motoru gerekmez — EM-029 `_horizons_for`/`level_thresholds`
  yeniden kullanılarak talep sabit tutulur, yalnızca kapasite değiştirilir.
- **Kapsam:** `src/services/capacity_whatif.py`
  (`_validated_added` girdi bekçisi, `scenario_capacity` ek birimleri
  ha/saat varsayımıyla fiyatlar, `run_capacity_whatif` olay×ufuk açık/bant
  öncesi-sonrası + `resolves_gap`), `src/routes/whatif.py`
  (`WhatIfCapacityRequest` + `POST /api/v1/whatif/capacity`, config'e
  `capacity_attribution`), `risk_panel.html` **Kapasite What-If (EM-056)**
  kartı (ek kaynak girdileri + olay seçki `refreshRiskIndex`'ten beslenir,
  `runCapacityWhatIf()` POST, açık değişim tablosu + "çözüldü" rozetleri,
  `escapeHtml`), `tests/unit/test_capacity_whatif.py` (19 test), CHANGELOG +
  docs/api.
- **Kanıt:** 1 müsait ekip (2.0 ha/s) + T+30 talep 12.0 → açık 10.0 (kritik);
  +1 helikopter (→14.0) açığı kapatır, bant dikkat'e düşer, `resolved_by_addition`
  True (servis + endpoint testi). Geçersiz tür/negatif/tamsayı-dışı →
  `CapacityWhatIfError` (→400).
- **Kapılar:** black(117)/mypy(79)/pylint(10.00)/bandit(0) yeşil;
  pytest **521** (502 + 19 yeni).
- **Commit:** `feat(EM-056): ...` (bu dal).

### EM-060 — Yeniden hesaplama performans bütçesi (#60) — DONE
- **Eksik analizi:** EM-022 bir *benchmark* (`spread_perf.py`, tek seferlik
  mod kıyasi) ve EM-055 anlık `within_target` işareti sunuyordu; ancak
  **kayyan p95** gecikme ölçümü, süreğen aşım tespiti ve buna bağlı
  **otomatik çözünürlük küçültme** hiç yoktu. Görev ima ettiği bağlantıları
  da içerir: telemetri tablosu+migration, ayarlar, canlı-besleme uyarısı,
  rüzgâr ucuna entegrasyon, UI kartı.
- **Kapsam:** `src/models/perf_budget.py` (`RecomputeLatencySample`,
  V017 migration, `models/__init__` kaydı), `src/config/settings.py` +
  `.env.example` (`PERF_BUDGET_*`), `src/services/perf_budget.py`
  (`percentile` numpy-tanımı enterpolasyon, `budget_status` kayan p95,
  `_CoarseSettings` delege + `resolve_recompute_settings`,
  `record_recompute_latency` kenar-tetiklemeli `alert`),
  `src/routes/perf_budget.py` (3 uç) + `fastapi_app.py` kaydı,
  `src/routes/whatif.py` rüzgâr ucuna **ek** `perf_budget` alanı +
  gecikme örneği, `risk_panel.html` **Yeniden Hesaplama Bütçesi** kartı +
  `refreshPerfBudget()`, `tests/unit/test_perf_budget.py` (20 test),
  CHANGELOG + docs/api.
- **Varsayım:** Ölçek küçültme poligon köşesini (36→`PERF_BUDGET_COARSE_VERTICES`
  vars.12) ve ufuk setini (`PERF_BUDGET_COARSE_HORIZONS` vars.[30,120])
  kırpar; tek başına gerçek CPU süresini ölçmek testte mümkün olmadığından
  rüzgâr ucu `result["compute_ms"]` değeri telemetriye beslenir. Uyarı
  yalnızca iç→dış kenarında (`_previous_breached` histerezisi) bir kez.
- **Kanıt:** 6×2000ms → `within_budget` True; 5×20000ms → `breached`
  True + `scale_down_active` True + `recommended_resolution` coarse;
  4 örnek (<min) → karar yok (None); `PERF_BUDGET_ENABLED=False` → ihlal
  ama aktif değil; coarse sarmalayıcı yalnızca iki düğmeyi değiştirir;
  alert kenarda 1 kez, süreğende tekrar yok; POST sample negatif →400;
  rüzgâr ucu `perf_budget` + telemetri satırı yazar, `FireForecast` yazmaz.
- **Kapılar:** black(121)/mypy(82)/pylint(10.00)/bandit(0) yeşil;
  pytest **541** (521 + 20 yeni).
- **Commit:** `feat(EM-060): ...` (bu dal).

### EM-061 — Sıcaklık ve nem what-if parametreleri (#61) — DONE
- **Eksik analizi:** EM-055 what-if yalnızca **rüzgâr**ı (yön/hız) bozuyordu;
  `air_temp_c`/`relative_humidity_pct` yalnızca taban değer olarak iletiliyor,
  senaryo düğmesi yoktu. Issue panelde sıcaklık/nem kaydırıcısı ve bunun
  yayılıma/riske yansımasını istiyordu.
- **Kapsam:** `src/services/whatif.py` (`_validate_wind` +sıcaklık/nem
  bekçileri, `_clamp`, `_resolve_scenario_wind`→`_resolve_scenario`
  rüzgâr+sıcaklık+nem, `_predict_request` override, `run_whatif`
  `base_inputs`/`scenario_over` + `weather` bloğu, `WHATIF_MODEL_NAME`
  `whatif_v2`), `src/routes/whatif.py` (`WhatIfRequest` iki opsiyonel alan
  `temperature_delta_c`/`humidity_delta_pct`), `operator_map.html` **What-If —
  Hava Senaryosu** sıcaklık/nem kaydırıcıları + `runWhatif()` delta okuma +
  **Sıfırla** + özet "Sıcaklık / Nem" satırı, `tests/unit/test_whatif_weather.py`
  (13 test), CHANGELOG + docs/api.
- **Varsayım (fiziksel bağlantı):** Rothermel motoru sıcaklık/nemi **denge (ölü)
  yakıt nemi** üzerinden tüketir ve bu yalnızca `fuel_moisture_pct`
  **sabitlenmediğinde** aktiftir (spread.py). Dolayısıyla sıcaklık/nem deltaları
  yayılıma ancak çağıran `fuel_moisture` vermediğinde yansır; EM-055 testleri
  `fuel_moisture` sabitlediği için davranışı değişmez. Daha sıcak/kuru → yakıt
  kurur → yayılım hızlanır (alan/talep/açık artar); daha soğuk/nemli → yavaşlar.
- **Kanıt:** delta `0`/düğme yok → senaryo == orijinal (sıfırlama sözleşmesi);
  +15°C/-20% → air_temp≈40/rh≈20, alan+talep+açık artar; −10°C/+20% → azalır;
  senaryo nemi [1,100]'e, sıcaklığı [-30,60]'a kırpılır; ± sınır aşımı →
  `WhatIfError`(→400); uç `weather` bloğu + EM-060 `perf_budget` döndürür;
  UI `whatif-temp`/`whatif-humidity` gömülü.
- **Kapılar:** black(122)/mypy(82)/pylint(10.00)/bandit(0) yeşil;
  pytest **554** (541 + 13 yeni).
- **Commit:** `feat(EM-061): ...` (bu dal).

### EM-033 — Zamana bağlı kapasite modeli, yoldaki kaynakların varışı (#33) — DONE
- **Eksik analizi:** `effective_capacity` (EM-028) yalnızca `available` sayan
  **anlık** bir yığındı; `en_route` birimin **varış zamanı** diye bir kavramı
  yoktu (`SuppressionResource`'ta ETA kolonu yok). EM-030 çizelgesi kapasiteyi
  ufuk boyunca **sabit** tutuyordu. Issue "kapasite(t) her kaynağın tahmini
  varışından itibaren devreye girer + risk eşiği bunu yansıtır" istiyordu.
- **Kapsam:** `src/models/inventory.py` (`arrival_eta` DateTime, V018
  migration, `as_dict`), `src/services/capacity.py` (`enroute_arrival_minutes`,
  `capacity_at_minute`, `capacity_schedule`), `src/services/risk_index.py`
  (`capacity_gap_timeline` her ufku o dakikadaki kapasiteyle fiyatlar +
  `capacity_schedule` bloğu), `src/config/settings.py` + `.env.example`
  (`TIME_DEPENDENT_CAPACITY`), `src/routes/capacity.py`
  (`GET /api/v1/capacity/schedule`), `src/services/inventory.py` +
  `src/routes/inventory.py` (create/update `arrival_minutes`),
  `risk_panel.html` (**basamaklı** kapasite çizgisi) + `inventory.html`
  (**Varış ETA (dk)** alanı), `tests/unit/test_time_dependent_capacity.py`
  (13 test), CHANGELOG + docs/api.
- **Varsayım (EM-031 korunumu):** yalnızca **ETA'sı olan** `en_route` birim
  gelecekteki ufuklarda kapasiteye eklenir; ETA'sız yoldaki birim hiçbir ufka
  katkı vermez → mevcut `en_route`→0 kapasite testleri (test_capacity) ve
  `available`-only `effective_capacity`/`compute_risk_index` **değişmez**. Geçmiş
  ETA "şimdi"ye kırpılır. Çizelge haricinde anlık görünüm sabit kalır.
- **Kanıt (≥3 zaman senaryosu):** T+75 varış → T+30/60 taban, T+120 taban+12
  (basamak); ilk kritik aşım pekiştirmesiz ~T+67 iken pekiştirmeli **None**
  (ertelenir); `TIME_DEPENDENT_CAPACITY=False` → tüm ufuklar sabit +
  `capacity_schedule` yok; ETA'sız yoldaki → `[]`; CRUD `arrival_minutes=45`
  → `arrival_eta` ISO, negatif → `InventoryError`; uç 200; panel/inventory
  gömülü.
- **Kapılar:** black(123)/mypy(82)/pylint(10.00)/bandit(0) yeşil;
  pytest **567** (554 + 13 yeni).
- **Commit:** `feat(EM-033): ...` (bu dal).

### EM-057 — Gerçek zamanlı otomatik yeniden hesaplama (#57) — DONE
- **Eksik analizi:** EM-018 `spread_trigger` rüzgâr/nem/sıcaklık değişimini
  tespit edip yayılımı yeniden hesaplıyordu AMA (1) **yangın konumu** ve
  **kapasite** değişimine bakmıyordu, (2) otomatik tarama canlı beslemeye hiç
  kayıt yazmıyordu → operatör "plan güncellendi, ne değişti?" özeti görmüyordu
  (yalnızca elle `/spread/predict` ucu besleme yazıyordu). E6 Must (sp5).
- **Kapsam:** `src/services/auto_recompute.py` (`current_plan_state`,
  `changed_factors`, `evaluate_recompute`, `run_recompute`,
  `auto_recompute_sweep`, `haversine_km`), `src/config/settings.py` +
  `.env.example` (`AUTO_RECOMPUTE_ENABLED/INTERVAL_MINUTES/POSITION_MOVE_KM/
  CAPACITY_CHANGE_PCT`), `src/tasks.py` (Celery beat `auto_recompute_plans`),
  `src/routes/spread.py` (`GET /recompute-status`, `POST /recompute-sweep`),
  `operator_map.html` (`flashLive` → `plan_update` başlık + değişen faktör
  etiketleri + tepe risk bandı), `tests/unit/test_auto_recompute.py` (16 test),
  CHANGELOG + docs/api.
- **Varsayım (feed-as-state, EM-032 deseni):** son planın sürücü-durum anlık
  görüntüsü yeni tablo/migration yerine append-only canlı beslemeye
  (`kind=forecast`, `source=auto_recompute`) yazılır ve geri okunur → Celery/API
  süreçleri ayrışır. Eşikler: rüzgâr/nem/sıcaklık EM-018'den; konum haversine
  ≥1 km; kapasite bağıl ≥%10. Debounce EM-018 penceresi (anti-flap). Yeniden
  hesaplama EM-018 `run_spread_forecast` + EM-029 `compute_risk_index`'i çağırır;
  **mevcut EM-018/028/029 servisleri değişmez**.
- **Kanıt:** snapshot yok → `new_plan` (run); run sonrası anında → `debouncing`;
  debounce geçip değişim yok → `stable`; +1 ekip (2→4 ha/s, +%100) → `capacity`;
  0.05° kuzey (~5.5 km) → `position`; run → 3 `FireForecast` + 1 `forecast`
  besleme kaydı (title "Plan güncellendi", message "Değişen", payload
  `plan_update`); sweep `AUTO_RECOMPUTE_ENABLED=False` → 0; endpoint 200/404.
- **Kapılar:** black(125)/mypy(83)/pylint(10.00)/bandit(0) yeşil;
  pytest **583** (567 + 16 yeni).
- **Commit:** `feat(EM-057): ...` (bu dal).

### EM-059 — Senaryo kaydetme ve paylaşma (#59) — DONE
- **Eksik analizi:** EM-055/056/061/057 what-if yeniden hesaplamaları kasıtlı
  olarak **geçici** (`persistence: "none"`). Umut verici bir koşu adlandırılamıyor,
  vardiya devrinde geri getirilemiyor ve ekiple bağlantı üzerinden
  paylaşılamıyordu. `ScenarioRun` (models/synthetic.py) **sentetik veri üretimi**
  (EM-104) içindi, what-if kalıcılığı için değil → gerçek boşluk. E6 Should (sp3).
- **Kapsam:** `src/models/scenario.py` (`WhatIfScenario`, `whatif_scenarios`,
  V019 migration), `src/services/scenario_share.py` (CRUD + token yaşam döngüsü),
  `src/routes/scenario_share.py` (9 uç, `fastapi_app`'e kaydedildi),
  `operator_map.html` (what-if panelinde **Senaryolar — Kaydet / Paylaş** araç
  çubuğu: `saveScenario`/`loadScenario`/`shareScenario`/`refreshScenarioList`),
  `tests/unit/test_scenario_share.py` (20 test), CHANGELOG + docs/api.
- **Varsayım (yalnızca girdi):** senaryo **sonuç** değil yalnızca **girdi**
  (`kind` + `params_json`) saklar; sonuç her zaman mevcut `/whatif/wind` /
  `/whatif/capacity` ucundan **yeniden oynatılır** → fizik çoğaltılmaz, bayat
  sonuç olmaz. Paylaşım opak token (`secrets.token_urlsafe(16)`) +
  `/by-token/<token>`; yeniden-share tokenı **döndürmez** (stabil).
- **Kanıt:** wind enlem+boylam ister (yok→`ScenarioError`/400), capacity dolu
  `added_resources` ister; isim boş/>120 red; list kind/event filtresi; share →
  `share_path` biter tokenla, by-token geri getirir, disable → by-token 404;
  delete True/False; uçlar 200/400/404; UI `whatif-scen-save` +
  `/api/v1/whatif/scenarios` gömülü.
- **Kapılar:** black(129)/mypy(86)/pylint(10.00)/bandit(0) yeşil;
  pytest **603** (583 + 20 yeni; V019 migration `test_spatial` yeşil).
- **Commit:** `feat(EM-059): ...` (bu dal).

### EM-062 — What-if geçmişi ve geri alma (#62) — DONE
- **Eksik analizi:** EM-059 **adlandırılmış/kalıcı** senaryoları saklar; AMA
  operatörün **otomatik**, kendiliğinden budalanan "ne denedim?" geçmişi yoktu.
  Kabul kriterleri: son 10 koşu listelenir + tek tıkla geri dönülür + oturum
  boyunca saklanır. Geçici koşular (EM-055/061) hiçbir yerde birikmiyordu.
  E6 Could (sp3).
- **Kapsam:** `src/models/scenario.py` (`WhatIfHistory`, `whatif_history`,
  V020 migration), `src/services/whatif_history.py` (`record_history`,
  `list_history`, `get_history`, `clear_history`), `src/routes/whatif_history.py`
  (5 uç, `fastapi_app`'e kaydedildi), `src/config/settings.py` +
  `.env.example` (`WHATIF_HISTORY_ENABLED/LIMIT`), `operator_map.html`
  (**Geçmiş — son koşular** aracı: koşu sonrası otomatik `recordWhatifHistory`,
  `revertHistory` tek tık, `clearHistory`), `tests/unit/test_whatif_history.py`
  (12 test), CHANGELOG + docs/api.
- **Varsayım (EM-059'dan ayrım):** geçmiş **otomatik** + sınırlı (son N) ve
  adlandırılmamış; yalnızca **girdi** saklar, geri alma `/whatif/wind`'den
  **yeniden oynatır** (sonuç önbelleği yok). En yeniyle birebir aynı girdi
  tekrar kaydedilmez (istemci + sunucu debounce). Budama: yeni kayıt sonrası
  `id` azalan sırayla son `limit` dışındakiler silinir.
- **Kanıt:** 12 koşu limit=3 → son 3 kalır [11,10,9]; disabled → `recorded:false
  reason:disabled`; duplicate → `reason:duplicate`; get(missing) → HistoryError;
  clear event-scoped + tümü; uçlar config/list/record/get(404)/delete; UI
  `whatif-hist-revert` + `recordWhatifHistory(body` + `/api/v1/whatif/history`.
- **Kapılar:** black(132)/mypy(88)/pylint(10.00)/bandit(0) yeşil;
  pytest **615** (603 + 12 yeni; V020 migration `test_spatial` yeşil).
- **Commit:** `feat(EM-062): ...` (bu dal).

### EM-047 — Öneri kabul/ret/düzenleme (#47) — DONE
- **Eksik analizi:** EM-052 (`positioning.build_proposals`) önerileri **canlı**
  üretiyor AMA operatörün bu öneri üzerinde verdiği **karar** hiçbir yerde
  saklanmıyordu; `accept/reject/decision/feedback` için model/servis/route yoktu
  (grep boş). Kabul kriterleri: üç aksiyon + kabul kaynağı "yolda" yapar +
  ret gerekçesi isteğe bağlı + her karar denetim kaydına yazılır. E5 Must (sp5).
- **Kapsam:** `src/models/recommendation.py` (`RecommendationDecision`,
  `recommendation_decisions`, V021 migration; `models/__init__`'e kaydedildi),
  `src/services/recommendation_decision.py` (`record_decision`, `list_decisions`,
  `get_decision`), `src/routes/recommendation_decision.py` (4 uç, `fastapi_app`'e
  kaydedildi), `src/services/positioning.py` (deployment_point özelliklerine
  `resource_key`/`event_key` eklendi — UI karar verebilsin), `operator_map.html`
  (öneri satırında **Kabul/Düzenle/Reddet** + `decideProposal` + karar sonrası
  `loadLayer` yenileme), `tests/unit/test_recommendation_decision.py` (12 test),
  CHANGELOG + docs/api.
- **Varsayımlar:** (1) `edit` = kabul + operatör değişiklikleri (`arrival_minutes`
  envanter üzerinden `arrival_eta`'ya planlanır); (2) kabul/düzenle kaynağı
  `en_route`'a çeker — durum geçişi `inventory.update_resource` yeniden
  kullanılarak sözlük/ETA doğrulaması tek yerde kalır; (3) E10 auth kapsam dışı,
  `decided_by` serbest metin; denetim **kaydı** (immutable satır) burada tutulur;
  (4) öneri saklanmaz — karar anındaki girdiler denetim kaydının `detail_json`
  anlık görüntüsüne yazılır.
- **Kanıt:** accept → `en_route` + `status_changed:true`; edit(arrival=30) →
  `en_route` + `arrival_eta` dolu + detail 30; reject → durum değişmez + reason
  opsiyonel (ikisi de denetlenir); invalid action → DecisionError; unknown
  resource → DecisionError; get(missing) → DecisionError; uçlar config/record
  (200/404/400)/list/get(404); UI `db-accept`/`db-reject`/`decideProposal`.
- **Kapılar:** black(136 değişmez)/mypy(91)/pylint(10.00)/bandit(0) yeşil;
  pytest **627** (615 + 12 yeni; V021 migration `test_spatial` yeşil).
- **Commit:** `feat(EM-047): ...` (bu dal).

### EM-046 — Öneri gerekçesi / açıklanabilirlik (#46) — DONE
- **Eksik analizi:** EM-052 `build_proposals` önerileri sıralıyor AMA **neden**
  sıralandığını ve **hangi alternatiflerin elendiğini** hiçbir yerden
  açıklamıyordu; `explain`/`rationale`/`why` için servis/route yoktu. Kabul
  kriterleri: her öneri için "neden?" paneli (tahmin/eşik/alternatifler) +
  reddedilen alternatifler ve nedenleri görülebilir. E5 Must (sp5).
- **Kapsam:** `src/services/recommendation_explain.py` (`explain_proposals`),
  `src/routes/recommendation_explain.py` (2 uç, `fastapi_app`'e kaydedildi),
  `operator_map.html` (öneri satırında **Neden?** düğmesi + `explainProposal`
  satır-altı açılır panel), `tests/unit/test_recommendation_explain.py` (11 test),
  CHANGELOG + docs/api. **Migration/model/settings yok** — canlı hesaplanır.
- **Varsayımlar:** (1) yeniden sıralama yok; `build_proposals` (limit=_ALL) ile
  **tam** sıralama alınıp `POSITIONING_MAX_PROPOSALS` (veya `limit`) ile
  selected/rejected bölünür — gerekçe haritadaki sayılarla çelişmez; (2) "hangi
  tahmin" = kapanış-duyarlı rota ETA'sı; "hangi eşik" = top-N seçimi +
  `threshold_eta_minutes` (en yavaş seçilenin ETA'sı); (3) reddedilen gerekçesi:
  ulaşılamayan → "izole/kopuk", eşikten uzun ETA → "daha uzun tahmini varış".
- **Kanıt:** limit=1 → 1 öneri `rank:1` + `why` ("En kısa tahmini varış"),
  reddedilenler `slow`="Daha uzun tahmini varış" + `island`="ulaşılamıyor";
  context `alternatives_evaluated:3`, `threshold_eta`==önerilenin ETA'sı; limit=10
  → reddedilen boş; bilinmeyen olay → PositioningError; boş ağ → RoadNetworkError;
  uçlar 200/404/422/config; UI `db-why`/`explainProposal`.
- **Kapılar:** black(139 değişmez)/mypy(93)/pylint(10.00)/bandit(0) yeşil;
  pytest **638** (627 + 11 yeni).
- **Commit:** `feat(EM-046): ...` (bu dal).

### EM-049 — Kaynak tipine göre ETA — kuş uçuşu vs yol ağı (#49) — DONE
- **Eksik analizi:** EM-052 `build_proposals` **tüm** kaynakları (ekip,
helikopter, İHA) yol ağı grafiğinden routing yapıyordu; kaynak **tipine göre**
seyahat modu (hava = kuş uçuşu, kara = yol ağı) hiç yoktu (`air_speed`/`flight`/
`travel_mode` araması boş). Kabul kriterleri: ETA tipe göre hız+rota ile
hesaplanır; önerilerde görünür. E5 Must (sp5).
- **Kapsam:** `src/services/positioning.py` (hava/kara dalı + `travel_mode`),
  `src/config/settings.py` + `.env.example` (`POSITIONING_AIR_SPEED_KMH`),
  `operator_map.html` (**Hava/Kara** rozeti + açılır pencere mod etiketi + CSS),
  `tests/unit/test_positioning_travel_mode.py` (9 test), CHANGELOG + docs/api.
  **Migration/model/route yok** — mevcut `/proposals` ucu genişletilir.
- **Varsayımlar:** (1) hava kaynağı = `resource_type ∈ {helicopter, uav}`;
  crew_bases (kara ekibi) daima `road`; (2) hava ETA'sı = `haversine_km/air_speed*60`,
  kapatmalar uçuşu etkilemez → `reachable=true`, `delay=0`, iki noktalı düz rota;
  (3) boş yol ağı hâlâ `RoadNetworkError` (pilot bölgesinde ağ varsayılır);
  (4) "kaynak listesinde ETA" = envanter `arrival_eta` (EM-033) zaten mevcut.
- **Kanıt:** ekip→`travel_mode:road`; heli→`air`, `distance_km`==haversine,
  `eta==round(km/220*60,2)`, rota 2 nokta; ada helikopteri ulaşılabilir + ada
  ekibi ulaşılamaz (hava öne sıralanır); kapatma hava ETA'sını değiştmez;
  110↔440 km/sa hız-ETA ters orantısı; layer/özellik `travel_mode`; uç
  `travel_mode` döner; UI `mode-air`/`mode-road`/`travel_mode`.
- **Kapılar:** black(140 değişmez)/mypy(93)/pylint(10.00)/bandit(0) yeşil;
  pytest **647** (638 + 9 yeni).
- **Commit:** `feat(EM-049): ...` (bu dal).

### EM-048 — Önerinin etki karşılaştırması (#48) — DONE
- **Eksik analizi:** EM-046/047 öneriyi açıklıyor ve karar verdiriyor AMA
  "öneri **uygulanırsa** vs **uygulanmazsa**" riskin nasıl değiştiğini yan yana
  gösteren hiçbir şey yoktu (`impact`/`compare`/`applied` araması boş). Komutan
  kararın değerini görsün ister. E5 Must (sp3).
- **Kapsam:** `src/services/recommendation_impact.py` (`compare_impact`),
  `src/routes/recommendation_impact.py` (2 uç, `fastapi_app`'e kaydedildi),
  `operator_map.html` (Konuşlanma panelinde **Etki karşılaştırması** düğmesi +
  `loadImpactComparison`/`renderImpact` + tablo CSS),
  `tests/unit/test_recommendation_impact.py` (12 test), CHANGELOG + docs/api.
  **Migration/model/settings yok** — EM-056 + EM-029 motorları yeniden kullanılır.
- **Varsayımlar:** (1) **talip sabit**, yalnızca bu olaya ayrılan EM-028 kapasite
  değişir; uygulanırsa=tam etkin kapasite, uygulanmazsa=etkin − önerilen
  ulaşılabilir kaynakların ha/saat toplamı; (2) yalnızca `kind==
  suppression_resource` önerileri ayrılan sayılır (crew_bases zaten kapasiteye
  girmez); (3) canlı/tavsiye — hiçbir kaynak rezerve edilmez; (4) karşılaştırılacak
  yayılım tahmini yoksa `ImpactError`→409.
- **Kanıt:** 2 müsait ekip (biri ulaşılabilir, biri ada/kopuk) → applied 4.0,
  committed 2.0, not_applied 2.0; side_by_side 3 ufuk, tüm `risk_index_delta<=0`
  ve en az biri <0, `decision_has_value` True; öneri yoksa committed 0 → delta 0 →
  False; bilinmeyen olay→PositioningError; boş ağ→RoadNetworkError; tahmin yoksa
  ImpactError; uçlar 200/404/422/config; UI `loadImpactComparison`/`positioning-impact`.
- **Kapılar:** black(143 değişmez)/mypy(95)/pylint(10.00)/bandit(0) yeşil;
  pytest **659** (647 + 12 yeni).
- **Commit:** `feat(EM-048): ...` (bu dal).

### EM-053 — Çifte atama ve kaynak çakışma önleme (#53) — DONE
- **Eksik analizi:** EM-047 `record_decision` kabul/düzenle'de kaynağı koşulsuz
  `en_route`'a çekiyordu; **aynı birimin ikinci bir olaya atanmasını engelleyen**
  bir bekçi ve **görev bitişi kaynağı müsaite döndüren** bir mekanizma yoktu
  (`conflict`/`release`/`assignment` araması boş). Kabul kriterleri: tek görev
  ataması + çakışmada açıklamalı uyarı + görev bitince otomatik müsait. E5 Should (sp3).
- **Kapsam:** `src/services/recommendation_decision.py` (`ConflictError`,
  `_BUSY_STATUSES`, `_active_assignment_event`, `record_decision` içine çakışma
  bekçisi, `release_assignment`, `list_active_assignments`,
  `release_completed_assignments`), `src/routes/recommendation_decision.py`
  (4 yeni uç + `…/config` `conflict_prevention` bloğu; `DecisionRecord` 409),
  `operator_map.html` (**Atamalar** bölümü: `toggleAssignments`/`loadAssignments`/
  `releaseAssignment`/`releaseCompleted` + tablo + CSS),
  `tests/unit/test_recommendation_conflict.py` (16 test), CHANGELOG + docs/api.
  **Migration/model/settings/route-kaydı yok** — mevcut EM-047 tablosu/servisi genişletilir.
- **Varsayımlar:** (1) atama **ayrı tablo değil**, EM-047 denetim kaydından türer:
  en yeni karar `accept`/`edit` ve kaynak hâlâ meşgulse (`en_route`/`deployed`)
  o olaya bağlı; sonraki `release` bağı temizler; (2) `release` yeni bir
  `DECISION_ACTIONS` **değildir** (EM-047 `actions` üçlüsü ve config testi
  korunur) — ayrı `release_assignment` fonksiyonu `release` satırı yazar;
  (3) çakışma yalnızca `event_key` verilip mevcut atama **farklıysa** tetiklenir
  (geriye dönük uyum: `event_key`'siz kabuller eskisi gibi serbest);
  (4) "görev bitti" = olay `status != "active"` ya da satırı yok.
- **Kanıt:** RES EVT-A'ya kabul → EVT-B'ye kabul `ConflictError` (uç 409);
  aynı EVT-A tekrar → idempotent; release → `available` + ETA temiz + sonra
  EVT-B'ye kabul OK; boş kaynakta release no-op; yanlış `event_key` release →
  ConflictError; `list_active_assignments` 1 satır; sweep: aktif olay bağlı
  kalır, contained/silinen olayın birimi otomatik `available`; uçlar
  release(200/404)/assignments(200)/release-completed(200)/config; UI
  `toggleAssignments`/`db-release`/`Müsaite al`.
- **Kapılar:** black(144 değişmez)/mypy(95)/pylint(10.00)/bandit(0) yeşil;
  pytest **675** (659 + 16 yeni).
- **Commit:** `feat(EM-053): ...` (bu dal).

### EM-051 — Kabul edilen öneriden saha görev kartı (#51)

- **Kapsam:** `src/services/task_instruction.py` (`generate_task_cards`),
  `src/routes/task_instruction.py` (`task-cards` + `…/config`),
  `fastapi_app.py` route kaydı, `operator_map.html` (**Görev kartları**
  bölümü: `toggleTaskCards`/`loadTaskCards`/`renderTaskCard` +
  `refreshTaskCards` karar sonrası otomatik tazeleme),
  `tests/unit/test_task_instruction.py` (15 test), CHANGELOG + docs/api.
  **Migration/model/settings/route sayısı yok** — mevcut EM-047 denetim
  tablosu okunur, yeni kalıcılık yoktur.
- **Varsayımlar:** (1) kabul edilen birim `en_route` olup canlı EM-052
  öneri listesinden düştüğü için kart **denetim anlık görüntüsünden**
  (detail_json) yeniden kurulur; (2) aynı (kaynak, olay) için **en yeni**
  `accept`/`edit` esas alınır (`release` kart üretmez — EM-053 ile tutarlı);
  (3) hedef olay silinmişse kart atlanır, kaynak silinmişse snapshot
  alanlarına düşülür; (4) risk notu ölçülebilir talep yoksa (`peak_risk_index`
  null) taşınmaz.
- **Kanıt:** kabul → kart hedef/koordinat/ETA/risk `kritik` alanlarıyla dolu;
  ret kart yok; edit `arrival_minutes`'a düşer; bilinmeyen olay
  `TaskInstructionError` (uç 404); olay filtresi + filtresiz tüm liste;
  yeniden kabulde en yeni snapshot; `en_route`'dayken de üretilir; travel_mode
  + arrival_eta taşınır; silinen kaynak snapshot'a düşer; silinen olay kart
  üretmez; uçlar task-cards(200/404)/config; UI bağlantısı.
- **Kapılar:** black(147 değişmez)/mypy(97)/pylint(10.00)/bandit(0) yeşil;
  pytest **690** (675 + 15 yeni).
- **Commit:** `feat(EM-051): ...` (bu dal).

## Bitiş özeti

- **Tamamlanan görevler (hepsi DONE):** EM-031 (#31), EM-029 (#29),
  EM-030 (#30), EM-032 (#32), EM-056 (#56), EM-060 (#60), EM-061 (#61),
  EM-033 (#33), EM-057 (#57), EM-059 (#59), EM-062 (#62), EM-047 (#47), EM-046 (#46), EM-049 (#49), EM-048 (#48), EM-053 (#53), EM-051 (#51) — her biri kendi commit'i ile
  `agent/task-automation` dalına push edildi; ilgili issue'lara
  özet yorum bırakıldı, hiçbiri **kapatılmadı**. EM-055 önceki oturumdan
  alınıp tamamlandı (#55).
- **BLOCKED:** bu turda yok. Kapsam dışı bırakılanlar (yukarıdaki eleme):
  insan/altyapı isteyen epikler (E10 auth, E12 deploy, E13 E2E, E14 demo)
  ve tek oturuma sığmayan devasa ML epikleri (E4, E7) — Mock ile "bitti"
  göstermeme kuralı gereği girilmedi.
- **Varsayımlar:** (1) görev listesi issue başlığına değil kod boşluğuna göre
  süzüldü; (2) EM-060 ölçek küçültme poligon köşesi + ufuk setini kırpır,
  gerçek CPU süresi yerine rüzgâr ucu `compute_ms`'i telemetriye beslenir;
  (3) uyarılar kenar-tetiklemeli (histerezis); (4) `.github/workflows/ci.yml`
  ve `docs/journal/` backlog'e ait olmadığı için commitlere alınmadı.
- **Final kapılar:** black 147 değişmez · mypy Success (97) · pylint 10.00/10 ·
  bandit 0 · pytest **690 passed**.
- **PR:** main'e karşı **DRAFT** #244 açıldı (merge edilmedi).
- **Önerilen sonraki adımlar:** (a) E4/E7 ML epiklerini ayrı planla;
  (b) EM-060 kaba çözünürlüğünün gerçek PostgreSQL/Celery ürette p95 etkisini
  uçtan uca yük testiyle doğrula; (c) tamamlanan issue'ları kapatma kararını
  ver; (d) draft PR'ı inceleme sonrası merge et.
