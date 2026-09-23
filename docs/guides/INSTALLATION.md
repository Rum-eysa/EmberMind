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
git clone https://github.com/yourusername/wildfire-monitoring-system.git
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
python -c "from src.app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"
```

### 6. Uygulamayı başlat
```bash
python src/app.py
```

Uygulama `http://localhost:5000` adresinde çalışacaktır.

## Docker Kurulumu

```bash
docker-compose up -d
```

Kontroller:
```bash
docker-compose logs -f app
```

Durdur:
```bash
docker-compose down
```
