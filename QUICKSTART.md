# 🚀 Hızlı Başlangıç Rehberi

Bu rehber, proje yapısını GitHub'a nasıl yükleyeceğini ve geliştirmeye nasıl başlayacağını gösterir.

## 📋 İçindekiler
1. [GitHub'a Yükleme](#github'a-yükleme)
2. [Yerel Kurulum](#yerel-kurulum)
3. [İlk Commit ve Push](#ilk-commit-ve-push)
4. [Geliştirmeye Başla](#geliştirmeye-başla)

---

## GitHub'a Yükleme

### 1. GitHub'da Yeni Repository Oluştur

1. [GitHub](https://github.com) oturum aç
2. `+` simgesine tıkla → "New repository"
3. Repository adını gir: `wildfire-monitoring-system`
4. Açıklama (optional): "Yangın İzleme ve Tahmini Sistemi"
5. "Create repository" tıkla
6. `.gitignore` ve `LICENSE` ekleme → **Atla** (zaten var!)

### 2. Yerel Repository'yi Hazırla

```bash
# Proje dizinine git
cd wildfire-monitoring-system

# Git repository'sini başlat
git init

# Tüm dosyaları ekle
git add .

# İlk commit'i yap
git commit -m "feat: Initial project structure for wildfire monitoring system"

# Eğer main branch değilse, main'e değiştir
git branch -M main
```

### 3. Remote Repository Bağla ve Push Et

```bash
# Uzak repository'yi bağla
# UYARI: yourusername ve wildfire-monitoring-system'i kendi verilerinle değiştir!
git remote add origin https://github.com/yourusername/wildfire-monitoring-system.git

# Tüm dosyaları GitHub'a push et
git push -u origin main
```

> **Not**: Eğer SSH key kullanıyorsan, URL'i şu şekilde değiştir:
> ```bash
> git remote add origin git@github.com:yourusername/wildfire-monitoring-system.git
> ```

---

## Yerel Kurulum

### 1. Sanal Ortamı Oluştur

```bash
# Python 3.9+ gerekli
python --version  # v3.9+ olmalı

# Sanal ortam oluştur
python -m venv venv

# Sanal ortamı etkinleştir
# macOS / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### 2. Bağımlılıkları Yükle

```bash
# Geliştirme bağımlılıklarını yükle
pip install -r requirements-dev.txt

# Kontrol et
pip list | grep Flask
```

### 3. .env Dosyasını Oluştur

```bash
# .env.example'den .env oluştur
cp .env.example .env

# Editör ile aç ve gerekli değerleri doldur
# vim, nano, VS Code, vb.
```

**.env dosyasında doldurulması gerekenler:**

```env
# Veritabanı (PostgreSQL)
DATABASE_URL=postgresql://wildfire_user:password@localhost:5432/wildfire_db

# API Keys (NASA FIRMS, OpenWeather)
FIRMS_API_KEY=your_actual_key_here
OPENWEATHER_API_KEY=your_actual_key_here

# Gizli Anahtar (min 32 karakter)
SECRET_KEY=your_super_secret_key_min_32_characters
```

### 4. Veritabanını Hazırla

```bash
# PostgreSQL'e bağlan ve veritabanı oluştur
createdb wildfire_db

# Tablo oluştur
python scripts/setup_db.py
```

---

## İlk Commit ve Push

### Feature Branch Oluştur

Yeni bir özellik başlamak için:

```bash
# Ana branch'e git
git checkout main

# Yeni feature branch'i oluştur
git checkout -b feature/initial-api-setup

# Değişiklikleri yap
# ... (kod yaz)

# Değişiklikleri ekle
git add .

# Commit et
git commit -m "feat: Add initial Flask API structure"

# Push et
git push origin feature/initial-api-setup
```

### Pull Request Aç

1. GitHub'da push mesajı sonrası "Compare & pull request" tıkla
2. Başlık ve açıklama doldur
3. "Create pull request" tıkla
4. Review et ve merge et

---

## Geliştirmeye Başla

### Sunucuyu Çalıştır

#### Option 1: Flask Geliştirme Sunucusu

```bash
# Sanal ortamı etkinleştir
source venv/bin/activate

# Sunucuyu başlat
make dev

# Veya direkt:
FLASK_ENV=development python src/app.py
```

Uygulama `http://localhost:5000` adresinde çalışacak.

#### Option 2: Docker

```bash
# Docker konteynerlerini başlat
docker-compose up -d

# Logları izle
docker-compose logs -f app

# Durdur
docker-compose down
```

### Test Çalıştır

```bash
# Tüm testleri çalıştır
make test

# Veya:
pytest tests/ -v --cov=src

# Kodu biçimlendir
make format

# Kodu analiz et
make lint
```

### Makefile Komutları

```bash
# Yardım görmek
make help

# Komutlar:
make install          # Bağımlılıkları yükle
make dev             # Geliştirme sunucusu
make test            # Testleri çalıştır
make lint            # Kodu analiz et
make format          # Kodu biçimlendirin
make clean           # Geçici dosyaları sil
make docker-build    # Docker image'ı oluştur
make docker-up       # Docker başlat
make docker-down     # Docker durdur
```

---

## 📝 Kod Yazma Standartları

### 1. Branch Adlandırması

```bash
feature/new-feature           # Yeni özellik
fix/bug-name                  # Bug düzeltmesi
docs/update-readme            # Dokumentasyon
refactor/module-name          # Kod yeniden düzenleme
```

### 2. Commit Mesajı Formatı

```
[TYPE]: Kısaca açıklama

Daha detaylı açıklama.
Multiple satır yazılabilir.

Closes #123
Related-To: #456
```

**TYPE değerleri:**
- `feat`: Yeni özellik
- `fix`: Bug düzeltmesi
- `docs`: Dokumentasyon
- `refactor`: Kod yeniden düzenleme
- `test`: Test ekleme
- `chore`: Yapı değişiklikleri

### 3. Kod Formatı

```python
# Type hints kullan
def calculate_spread(fire_id: str, hours: int) -> Dict[str, float]:
    """
    Yangın yayılımını hesapla.
    
    Args:
        fire_id: Yangın ID'si
        hours: Saat sayısı
        
    Returns:
        Hesaplanan alan bilgileri
    """
    # İmplementasyon
    pass
```

---

## 🔐 Güvenlik Notları

⚠️ **Asla aşağıdakileri commit etme:**
- `.env` dosyası
- API anahtarları
- Şifreler
- Gizli anahtarlar
- Kişisel bilgiler

✅ **Her zaman:**
- `.env.example` dosyasına dummy değerler koy
- `.gitignore`'da hassas dosyaları listele
- GitHub Secrets'ları kullan

---

## 🆘 Yaygın Sorunlar

### "fatal: not a git repository"
```bash
# Çözüm:
git init
```

### "permission denied (publickey)"
```bash
# SSH key'i ekle:
ssh-add ~/.ssh/id_rsa

# Veya HTTPS kullan:
git remote set-url origin https://github.com/yourusername/repo.git
```

### "ModuleNotFoundError: No module named 'src'"
```bash
# Sanal ortamı etkinleştir:
source venv/bin/activate
```

### PostgreSQL bağlantı hatası
```bash
# PostgreSQL servisi çalışıyor mu kontrol et
# macOS:
brew services start postgresql

# Linux:
sudo systemctl start postgresql

# Windows: 
# Services uygulamasında PostgreSQL bul ve başlat
```

---

## 📚 Faydalı Bağlantılar

- [GitHub Docs](https://docs.github.com)
- [Git Cheatsheet](https://github.github.com/training-kit/)
- [Semantic Versioning](https://semver.org)
- [Conventional Commits](https://www.conventionalcommits.org)

---

## ✨ Sonraki Adımlar

1. ✅ Repository'yi GitHub'a yükle
2. ✅ Yerel kurulumu tamamla
3. ✅ İlk commit'i yap
4. ✅ Branches ve PR workflow'unu öğren
5. ✅ CI/CD pipeline'ını yapılandır
6. ✅ Takım üyelerini davet et
7. ✅ Kod review process'ini kur

---

**Sorular mı?** GitHub Issues'da soru sor veya email gönder!

**İyi kodlamalar! 🚀**
