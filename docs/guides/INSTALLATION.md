# Kurulum Rehberi

## Sistem Gereksinimleri

- Python 3.9+
- PostgreSQL 13+
- Redis 6+
- 4GB RAM (minimum)
- 10GB Disk (minimum)

## Linux/Mac Kurulumu

### 1. Repository'yi klonla
```bash
git clone <repository-url>
cd wildfire-monitoring-system
```

### 2. Sanal ortamı oluştur
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Bağımlılıkları yükle
```bash
pip install -r requirements.txt
```

### 4. .env dosyasını oluştur
```bash
cp .env.example .env
# .env dosyasını düzenle ve API anahtarlarını ekle
```

### 5. Veritabanını hazırla
```bash
# PostgreSQL'de veritabanı oluştur
createdb wildfire_db

# Tabloları oluştur
python scripts/setup_db.py
```

### 6. Uygulamayı başlat
```bash
uvicorn src.fastapi_app:app --reload --host 127.0.0.1 --port 8000
```

Uygulama `http://localhost:8000` adresinde çalışacaktır.

OpenAPI arayüzü `http://localhost:8000/docs` adresinde çalışır.

## Docker Kurulumu

```bash
docker compose up -d --build
```

Kontroller:
```bash
docker compose logs -f app
```

Durdur:
```bash
docker compose down
```
