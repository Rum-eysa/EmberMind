# Yangın İzleme ve Tahmini Sistemi

🔥 Uydu verisi, hava durumu ve makine öğrenmesi kullanarak yangın olaylarını izleme ve yayılımını tahmin eden kapsamlı sistem.

## 📋 Proje Özellikleri

- **Gerçek Zamanlı Veri Entegrasyonu**: NASA FIRMS, hava durumu API'leri
- **Yangın Yayılımı Tahmini**: Makine öğrenmesi modellerine dayalı
- **Harita Görselleştirmesi**: İnteraktif yangın sahaları ve uyarı sistemi
- **REST API**: Tüm işlevler için API endpoint'leri
- **Operatör Paneli**: Yönetici arayüzü ve raporlama

## 🚀 Hızlı Başlangıç

### Gereksinimler
- Python 3.9+
- Docker & Docker Compose
- PostgreSQL 13+
- Redis 6+

### Kurulum

```bash
# Repository klonla
git clone https://github.com/yourusername/wildfire-monitoring-system.git
cd wildfire-monitoring-system

# Sanal ortamı oluştur
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Bağımlılıkları yükle
pip install -r requirements.txt

# Veritabanını migrate et
python manage.py migrate

# Sunucuyu başlat
python manage.py runserver
```

### Docker ile Çalıştırma

```bash
docker-compose up -d
```

## 📁 Proje Yapısı

```
wildfire-monitoring-system/
├── src/
│   ├── api/              # REST API endpoint'leri
│   ├── models/           # ML modelleri ve veri modelleri
│   ├── data/             # Veri işleme ve ETL
│   ├── services/         # İş mantığı servisleri
│   ├── utils/            # Yardımcı fonksiyonlar
│   └── config/           # Konfigürasyon dosyaları
├── tests/                # Unit ve integration testler
├── docs/                 # Dokumentasyon
├── deployment/           # Docker, K8s, Terraform dosyaları
├── scripts/              # Yardımcı betikler
├── notebooks/            # Jupyter notebooks (analiz)
├── data/                 # Veri dosyaları
└── config/               # Konfigürasyon dosyaları
```

## 🔄 Veri Akışı

1. **Veri Kaynakları** → NASA FIRMS, OpenWeatherMap API
2. **Veri İşleme** → Normalleştirme, temizleme, özellik mühendisliği
3. **Tahmin Modeli** → Yayılım hesaplaması
4. **API Katmanı** → GraphQL/REST endpoint'leri
5. **Arayüz** → Web dashboard ve mobil uygulamalar

## 📊 Epic'ler ve Sprint Planlaması

- **E1**: Veri Entegrasyonu ve Veri Hattı
- **E2**: Yangın Yayılımı Tahmini Modeli
- **E3**: Görselleştirme ve Operatör Paneli
- **E4**: Ölçeklendirebilirlik ve İzleme

Sprint planlama [Projects](https://github.com/yourusername/wildfire-monitoring-system/projects) sekmesinde.

## 🧪 Test Çalıştırma

```bash
# Tüm testleri çalıştır
pytest

# Kodu kapsam raporuyla test et
pytest --cov=src tests/

# Belirli bir test dosyasını çalıştır
pytest tests/unit/test_models.py -v
```

## 📚 Dokumentasyon

Detaylı dokümantasyon `docs/` klasöründe bulunabilir:
- [API Dokümantasyonu](docs/api/README.md)
- [Mimari Rehberi](docs/architecture/README.md)
- [Kurulum Rehberi](docs/guides/INSTALLATION.md)

## 🔐 Güvenlik

- `.env` dosyasını `.env.example` den kopyala ve gizli anahtarları ekle
- GitHub secrets'ları CI/CD için yapılandır
- Production ortamında sadece HTTPS kullan

## 🤝 Katkı Rehberi

1. Fork et
2. Feature branch'i oluştur (`git checkout -b feature/AmazingFeature`)
3. Commit et (`git commit -m 'Add some AmazingFeature'`)
4. Push et (`git push origin feature/AmazingFeature`)
5. Pull Request aç

Detaylar için [CONTRIBUTING.md](CONTRIBUTING.md) adresine bak.

## 📝 Lisans

Bu proje MIT Lisansı altında lisanslanmıştır - [LICENSE](LICENSE) dosyasına bakın.

## 📧 İletişim

- **Email**: info@example.com
- **Issues**: GitHub Issues sekmesini kullan
- **Discussions**: GitHub Discussions sekmesini kullan

---

⭐ Projeyi beğendiysen, lütfen yıldız ver!
