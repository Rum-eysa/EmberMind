# EM-006: Pilot Bölge Tanımı ve Ortak Grid/Koordinat Standardı

## 1. Pilot Bölge Tanımı (TR–GR Kıyı Hattı)
- **Bölge Adı:** Türkiye – Yunanistan Ege ve Batı Akdeniz Kıyı Hattı
- **Sınır Kutusu (Bounding Box - EPSG:4326):**
  - Minimum Enlem (`min_lat`): **36.0° N**
  - Maksimum Enlem (`max_lat`): **39.5° N**
  - Minimum Boylam (`min_lon`): **26.0° E**
  - Maksimum Boylam (`max_lon`): **30.0° E**

## 2. Gerekçe
- **İklim ve Rüzgâr:** Ege yaz aylarında güçlü ve kuru Poyraz/Meltemi rüzgârlarına maruz kalır.
- **Bitki Örtüsü:** Kızılçam (*Pinus brutia*) ve maki türleri ile yüksek yakıt yüküne ve hızlı yangın yayılım riskine sahiptir.
- **Sınır Ötesi Dinamik:** Türkiye (İzmir, Muğla, Çanakkale, Aydın) ve Yunanistan (Rodos, Sisam, Sakız adaları) kıyı şeridinde ortak uzamsal izleme ihtiyacı.

## 3. Koordinat ve Grid Standartları
- **Saklama Standardı:** `EPSG:4326` (WGS 84 Coğrafi Koordinat Sistemi)
- **Metrik Hesaplama Standardı:** `EPSG:32635` (UTM Zone 35N) / `EPSG:32636` (UTM Zone 36N)
- **Hücre Grid Çözünürlüğü:** **30 m** ortak raster piksel boyutu (~0.00027 derece).
