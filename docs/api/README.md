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

### Yangın Yayılım Tahmini (EM-015)
```
POST /api/v1/spread/predict          # 30/60/120 dk risk bölgesi poligonları
GET  /api/v1/spread/fuel-models       # 13 standart USDA yakıt modeli kataloğu
GET  /api/v1/spread/forecasts         # bir olay için saklanan tahminler (?event_key=)
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

### Operatör Haritası ve Katmanları (EM-072)
```
GET /ui                              # Leaflet tabanlı operatör ana haritası
GET /api/v1/map/layers               # açılıp kapanabilir katman kataloğu
GET /api/v1/map/layers/{katman}      # GeoJSON FeatureCollection
```
Katmanlar: `fires` (aktif yangınlar: uydu kümeleri + olaylar), `forecasts`
(30/60/120 dk risk bölgesi poligonları), `fuel` (yakıt sınıfı), `silent-regions`
(sessiz bölgeler), `resources` (müdahale kaynakları/ekip üsleri), `roads` (yol ağı).
`forecasts` katmanı `?horizon_minutes=` ve `?event_key=` ile filtrelenebilir; arayüzdeki
**zaman kaydırıcısı** ile ufuklar arasında gezilir (kümülatif gösterim seçeneği ile).
Her yanıtta kaynak lisansı gereği `attribution` alanı döner (EM-013).

### Tahmin
```
POST /api/v1/predictions
```

Body:
```json
{
  "fire_id": "12345",
  "hours": 24
}
```

## Error Codes

- `200`: Başarılı
- `400`: Hatalı istek
- `404`: Bulunamadı
- `500`: Sunucu hatası
