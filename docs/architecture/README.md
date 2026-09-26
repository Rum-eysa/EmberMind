# Mimari Rehberi

## Depo Yapısı (Mono-Repo)

Bu proje **mono-repo** olarak yapılandırılmıştır — API, servisler, modeller,
veritabanı göçleri, testler, CI/CD hattı ve dokümantasyon tek depoda yaşar.

**Gerekçe:**
- Ekip küçük (< 10 kişi); ayrı repo yönetim yükü getirir.
- Servisler arası bağımlılık yüksek (model → service → route → test aynı PR’da değişir).
- CI/CD tek pipeline ile tüm katmanları doğrular (lint, type, test, security, docker).
- Ortamlar (dev, test, demo, prod) aynı kod tabanından config ile ayrışır.

### Dizin Düzeni

```
wildfire-monitoring-system/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml              # Lint + test + security + docker build
│   │   └── deploy-demo.yml     # CD: main → demo ortamına otomatik dağıtım
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
├── src/
│   ├── config/settings.py      # Config, DevelopmentConfig, TestingConfig, DemoConfig, ProductionConfig
│   ├── models/                 # SQLAlchemy ORM modelleri
│   ├── routes/                 # FastAPI endpoint kaydedicileri
│   ├── services/               # İş mantığı (FIRMS, FWI, sentetik, envanter, gözlemlenebilirlik…)
│   ├── utils/                  # Yardımcı fonksiyonlar (timeutils)
│   ├── static/                 # Statik HTML arayüzler
│   ├── fastapi_app.py          # Uygulama fabrikası
│   ├── database.py             # Database sınıfı
│   └── tasks.py                # Celery görevleri
├── scripts/
│   ├── migration/              # SQL göç dosyaları (V001..V009)
│   ├── setup_db.py             # Veritabanı kurulum betiği
│   ├── demo_api.py             # In-memory demo sunucusu
│   └── demo_seed.py            # Demo ortamı veri tohumlama
├── tests/
│   └── unit/                   # Pytest birim testleri
├── config/                     # JSON yapılandırma (bölge, yakıt haritası)
├── docs/                       # Ayrıntılı dokümantasyon
├── docker-compose.yml          # Production stack (Postgres, Redis, Celery, API)
├── docker-compose.demo.yml     # Demo profili (SQLite, harici bağımlılık yok)
├── Dockerfile                  # Uygulama imajı
├── Makefile                    # Geliştirici komutları
├── .env.example                # Şablon ortam değişkenleri
├── .env.dev.example            # Development ortamı
└── .env.demo.example           # Demo ortamı
```

## Ortamlar

| Ortam | Config | Veritabanı | Harici API | Başlatma |
|-------|--------|-----------|-----------|----------|
| **dev** | `DevelopmentConfig` | PostgreSQL (Docker) | Evet (FIRMS, OW) | `make dev` |
| **test** | `TestingConfig` | SQLite in-memory | Mock | `make test` |
| **demo** | `DemoConfig` | SQLite dosya | Hayır (sentetik EM-104) | `make demo-up` |
| **prod** | `ProductionConfig` | PostgreSQL | Evet | `docker compose up` |

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
