# Veri Kaynakları: Lisans, Atıf ve Kota Yönetimi (EM-013)

Bu belge, sistemde kullanılan tüm harici açık veri kaynaklarının hukuki
(lisans/atıf) ve operasyonel (kota) koşullarını tek tabloda toplar. Aynı
bilgiler makine okunabilir olarak API üzerinden de sunulur:

| Endpoint | Amaç |
|---|---|
| `GET /api/v1/data-sources` | Lisans, atıf ve kota tablosu |
| `GET /api/v1/data-sources/attribution` | Arayüzde gösterilecek atıf metinleri |
| `GET /api/v1/data-sources/cache-plan` | Kota riski taşıyan kaynakların önbellek planı |

> Kota değerleri 2026 itibarıyla kamuya açık servis dokümanlarındaki
> sınırlardır; değişirse `src/services/data_governance.py` güncellenir.

## Lisans, Atıf ve Kota Tablosu

| Kaynak | Lisans | Atıf Metni | Kota Limiti | Tahmini Günlük İstek | Kota Riski |
|---|---|---|---|---|---|
| NASA FIRMS (VIIRS/MODIS) | NASA Open Data (kamusal alan; kaynak gösterilmesi istenir) — [şartlar](https://firms.modaps.eosdis.nasa.gov/using-firms-data/) | "Fire detections are courtesy of NASA/LANCE/FIRMS." | MAP_KEY başına 5000 işlem / 10 dk | ~576 (4 ürün × 10 dk) | Düşük |
| OpenWeather Forecast | CC BY 4.0 — [telif](https://openweathermap.org/copyright) | "Weather data by OpenWeatherMap, licensed under CC BY 4.0." | 60 çağrı/dk, ~1M/ay (~33.000/gün) | ~2.880 (20 küme varsayımı) | Düşük–Orta* |
| USGS SRTM (Open-Elevation) | NASA SRTM kamusal alan; servis topluluk barındırmalı — [site](https://open-elevation.com/) | "Elevation data: NASA SRTM via the Open-Elevation project." | Yayınlanmış kota YOK; kötüye kullanım bazlı throttling | ~144 (1 toplu sorgu/senkron) | **Yüksek** |
| OpenStreetMap (Overpass) | ODbL 1.0 — [telif](https://www.openstreetmap.org/copyright) | "© OpenStreetMap contributors" (ekranda görünmek zorunda) | ~10.000 sorgu/gün + indirme hacmi sınırı (kamuya açık örnekler) | ~2 (720 dk aralık) | Düşük |
| CORINE Land Cover (Copernicus) | Copernicus lisansı (ücretsiz kullanım, atıf zorunlu) — [site](https://land.copernicus.eu/corine/land-cover) | "Land cover: Copernicus Land Monitoring Service / EEA CORINE." | Çalışma zamanı API çağrısı yok (yerel eşleme dosyası) | 0 | Düşük |
| EFFIS Tarihsel Perimetrler | EFFIS/JRC kullanım şartları — [şartlar](https://effis.jrc.ec.europa.eu/about-effis/term-of-use/) | "Historical fire perimeters: EFFIS, European Commission / JRC." | Yayınlanmış kota yok; fair-use (yıllık sorgu başına 1 istek) | ~5/hafta | Düşük |

\* OpenWeather riski aktif küme sayısıyla doğrusal büyür; ~100 kümenin
üzerinde orta/yüksek riske geçer (senkron aralığı genişletilmelidir).

## Arayüz ve Doküman Atıfları

- Her veri listesinin API yanıtı `attribution` alanı içerir
  (`/api/v1/fires`, `/api/v1/weather`, `/api/v1/topography`,
  `/api/v1/land-cover`, `/api/v1/roads`, `/api/v1/historical-fires`).
- Dashboard/footer katmanı `GET /api/v1/data-sources/attribution`
  yanıtındaki `combined_footer` metnini olduğu gibi göstermelidir.
- ODbL gereği "© OpenStreetMap contributors" atfının **kullanıcıya görünür**
  olmasından UI sorumludur (harita üzerinde zorunlu).

## Önbellek Planı (Kota Aşımı Riski Olan Kaynaklar)

Risk sıralamasında **yüksek** tek kaynak Open-Elevation (topoğrafya),
**büyümeye duyarlı** kaynaklar FIRMS ve OpenWeather'tir. Plan:

1. **Topoğrafya (risk: yüksek) — "kalıcı-sakla-ve-atla"**
   - Rakım statik veridir: ilk çekimde `topography_data_points` tablosuna
     yazılır, sonraki senkronlarda yalnızca **hiç görülmemiş 30 m grid
     hücreleri** için API çağrısı yapılır (EM-005 standart grid anahtarı).
   - TTL: 86400 sn (günlük yeniden kontrol yalnız yeni kümeler için).
   - Throttle edilirse: kendi Open-Elevation instance'ımıza veya doğrudan
     SRTM tile sunucusuna geçiş (`USGS_SRTM_BASE_URL` değişkeni yeterli).

2. **FIRMS (risk: düşük, hacim ürün sayısıyla artar) — "kısa TTL + birleşik çekim"**
   - Redis'te ürün+bbox+algılama günü anahtarlı 300 sn yanıt önbelleği.
   - EM-012 çoklu-ürün birleştirme nedeniyle mükerrer istek atılmaz.
   - Anahtar kullanım oranı yükselirse: ürün listesi daraltılır
     (`FIRMS_SOURCES`) veya `FIRMS_SYNC_INTERVAL_MINUTES` genişletilir.

3. **OpenWeather (risk: küme sayısına bağlı) — "mevcut TTL + eşikleme"**
   - İstemci içinde 1800 sn önbellek (`OPENWEATHER_CACHE_TTL_SECONDS`)
     yuvarlanmış lat/lon anahtarıyla çalışıyor.
   - İzleme eşiği: aktif küme > 100 → senkron aralığı 10 → 20 dk'ya çıkarılır.

4. **Yol ağı / EFFIS — "nadir yenileme"**
   - Veri statik/yıllıktır; DB'ye bir kez yazılır, aylık (yol) ve haftalık
     artımlı (EFFIS) yenileme yapılır. Kota aşımında Geofabrik extract veya
     kendi Overpass instance'ı kullanılır.

## Sorumluluklar

- Kaynak eklendiğinde/çıkarıldığında `src/services/data_governance.py`
  kayıt listesi güncellenmeli ve bu tabloya yansıtılmalıdır.
- Kota sayaçları ve tazelik uyarıları EM-010 veri kalitesi izleme
  (`/api/v1/data-quality`) ile birlikte izlenir.
