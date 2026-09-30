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
| 4 | EM-032 Eşik aşımı uyarısı (#32) | E3 | TODO | EM-029/030'a bağlı; histerezis + canlı besleme (LIVE "alert") |
| 5 | EM-056 Kapasite değişimi senaryosu (#56) | E6 | TODO | EM-055 what-if'ine kapasite delta'sı eklenir (bu dalda yeni) |
| 6 | EM-060 Yeniden hesaplama performans bütçesi (#60) | E6 | TODO | p95 ölçümü + aşım uyarısı + otomatik ölçek küçültme |

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
