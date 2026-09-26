# Kullanıcı Akışları — Operatör ve Saha (EM-074)

Kriter gereği iki akış **ayrı ayrı** çizilmiştir. Roller:

| Rol | Kim | Birincil ekran |
|---|---|---|
| Operatör (KOEM izleme memuru) | Görsel izleme, ilk ihbar | `/ui` ana harita |
| Komutan (Müdahale merkezi amiri) | Kaynak/risk kararı | `/panel` kapasite & risk paneli |
| Saha ekibi (arama-kurtarma/ORM. müdahale şefi) | Yol, ETA, saha doğrulama | `/ui` (mobil) + saha akışı |

## A) Operatör akışı (ihbardan karar destekleme kadar)

```
 [1] /ui açılır                 [2] Anomali fark et           [3] Katmanı doğrula
+------------------+           +------------------+          +--------------------+
| Ana harita       |  tarama  | Aktif yangın     |  tıkla    | Katman paneli      |
| katmanlar kapalı | -------> | kümesi parlar    | -------> | yangın + ufuk      |
| veri varsa nokta |          | (FIRMS > 0)      |          | poligonları AÇIK   |
+------------------+           +------------------+          +---------+----------+
                                                                      |
 [6] Komutana devir          [5] Yayılımı izle            [4] Olay detayı
+---------------------+     +---------------------+      +---------------------+
| /panel linki ile    |<----| 30/60/120 dk        |<-----| popup: konum,       |
| kapasite/risk       |     | zaman kaydırıcısı;  |      | FRP, yakıt sınıfı,  |
| görünümüne geçiş    |     | risk poligonu       |      | son gözlem zamanı   |
+---------------------+     | (forecasts katmanı) |      +---------------------+
                            +---------------------+
```

Adım–API eşlemesi:

| Adım | Eylem | Uç nokta |
|---|---|---|
| 1 | Katman kataloğu + GeoJSON'ları çek | `GET /api/v1/map/layers`, `GET /api/v1/map/layers/{key}` |
| 1b | Veri yoksa "senkron hiç çalışmadı" uyarısı | `GET /api/v1/pipeline/status` |
| 2–3 | Katman anahtarlarını aç/kapat (UI içi durum) | — (istemci tarafı) |
| 4 | Olay/polin detayı popup'ı | feature `properties` (ayrı istek yok) |
| 5 | Ufuklar arası geçiş | `GET /api/v1/map/layers/forecasts?horizon_minutes=` |
| 6 | Karar için panele geç | `GET /api/v1/panel/capacity-risk` |

**Akış kuralları**
- Operatör karar **vermez**, karar paketini hazırlar: olay + risk poligonu +
  eşik aşımı durumu komutana tek bağlantıyla (`/panel`) devredilir.
- Her adımda kaynak atıfı (attribution) görünür kalır (EM-013 lisans zorunluluğu).

## B) Saha akışı (müdahale ekibinin sahadaki kullanımı)

Saha akışı operatör akışından **ayrıdır**: saha kullanıcısı "hangi yoldan,
ne kadar sürede, hangi risk altında ulaşırım?" sorusunu sorar.

```
 [S1] Görev alır            [S2] /ui mobilde açar         [S3] Rota katmanı
+-----------------+        +----------------------+       +-------------------+
| Olay anahtarı / |  URL   | Harita olay merkezine | tıkla | roads + resources |
| koordinat       | -----> | odaklanır; olay       | ----> | katmanları açık;  |
| (SMS/telsiz)    |        | pin'i seçili          |       | kapatma kırmızı   |
+-----------------+        +----------------------+       +---------+---------+
                                                                    |
 [S6] Durum güncelle     [S5] Güvenlik payı            [S4] ETA doğrula
+-----------------+      +-----------------------+     +----------------------+
| "ulaştım"/"yol  |<---- | 60 dk'lık ufuk        |<--- | CrewBase -> olay     |
| kapalı" geri    |      | poligonu rotasına    |     | segmentleri ve ETA   |
| bildirimi       |      | değiyor mu? Değiyorsa |     | (road-network API)   |
| (API: POST      |      | alternatif rotaya geç |     +----------------------+
|  /events...)    |      +-----------------------+
+-----------------+
```

Adım–API eşlemesi:

| Adım | Eylem | Uç nokta |
|---|---|---|
| S2 | Olayı haritada bul | `GET /api/v1/events/{event_key}` + `fires` katmanı |
| S3–4 | Yol ağı, kapatmalar, ekip üssü, ETA | `roads`, `resources` katmanları; EM-008 yol/ETA uçları |
| S5 | 60 dk risk poligonu–rota çakışması | `GET /api/v1/map/layers/forecasts?horizon_minutes=60` |
| S6 | Saha durumu bildirimi | manuel olay/etkinlik uçları (`POST /api/v1/events/...`) |

**Akış kuralları**
- Saha akışı **çevrimdışı kalıntıya** dayanıklı olmalı: son bilinen katman
  sürümü önbellekten gösterilir, üstünde "veri yaşı" rozeti zorunludur
  (EM-011 tazeliik izleme ile tutarlı).
- Risk poligonu rotaya değiyorsa uyarı **engellemez**, bilgilendirir —
  nihai karar şefindir (insan-in-the-loop ilkesi).

## C) İki akışın kesişim noktası

```
 OPERATÖR AKIŞI                          SAHA AKIŞI
 [5] yayılım poligonu üretir  ────────►  [S5] aynı poligonu rotada tüketir
 [6] /panel'e devreder        ────────►  komutan [S1] görevi buradan verir
```

Kesişim tek noktadır: **yayılım poligonu üretimi (EM-015) tek kaynak**,
her iki akış da aynı `fire_forecasts` satırlarını okur — tutarsız görünüm
riski bilinçli olarak sıfıra indirilmiştir.
