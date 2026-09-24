# Mimari Rehberi

## Sistem Bileşenleri

### 1. Veri Katmanı
- NASA FIRMS API
- OpenWeather API
- PostgreSQL Veritabanı

### 2. İşleme Katmanı
- ETL Pipeline (Celery)
- Veri Normalizasyonu
- Özellik Mühendisliği

### 3. Model Katmanı
- Yangın Yayılımı Modeli
- İmage Segmentasyonu
- Kümele Analizi

### 4. API Katmanı
- REST API (FastAPI)
- Framework bağımsız FIRMS use-case servisleri (`src/services/fire_sync.py`)
- GraphQL (Optional)
- WebSocket (Real-time)

### 5. Arayüz Katmanı
- Web Dashboard
- Mobil Uygulama
- Operatör Paneli

## Veri Akışı

```
Veri Kaynakları
    ↓
Veri Toplama (Celery Tasks)
    ↓
Veri Normalizasyonu
    ↓
Depolama (PostgreSQL)
    ↓
ML Model (Tahmin)
    ↓
Cache (Redis)
    ↓
Service Layer
    ↓
FastAPI API
    ↓
Kullanıcı Arayüzü
```

FIRMS senkronizasyonu ve kaynak durum mantığı HTTP katmanından bağımsız servislerde tutulur.
