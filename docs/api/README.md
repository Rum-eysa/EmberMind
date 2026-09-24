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
