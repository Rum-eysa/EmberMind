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

## Bitiş özeti

- **Tamamlanan görevler (hepsi DONE):** EM-031 (#31), EM-029 (#29),
  EM-030 (#30), EM-032 (#32), EM-056 (#56), EM-060 (#60) — her biri kendi
  commit'i ile `agent/task-automation` dalına push edildi; ilgili issue'lara
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
- **Final kapılar:** black 121 değişmez · mypy Success (82) · pylint 10.00/10 ·
  bandit 0 · pytest **541 passed**.
- **PR:** main'e karşı **DRAFT** #244 açıldı (merge edilmedi).
- **Önerilen sonraki adımlar:** (a) E4/E7 ML epiklerini ayrı planla;
  (b) EM-060 kaba çözünürlüğünün gerçek PostgreSQL/Celery ürette p95 etkisini
  uçtan uca yük testiyle doğrula; (c) tamamlanan issue'ları kapatma kararını
  ver; (d) draft PR'ı inceleme sonrası merge et.
