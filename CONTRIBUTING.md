# Katkı Rehberi

Yangın İzleme Sistemine katkı yapmak için teşekkürler! 🎉

## Başlamadan Önce

1. Bu repository'yi fork edin
2. Klonlayın: `git clone https://github.com/yourusername/wildfire-monitoring-system.git`
3. Main branch'ten yeni bir branch oluşturun: `git checkout -b feature/your-feature`

## Geliştirme İş Akışı

### 1. Geliştirme Ortamını Kurma

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

### 2. Kod Yazma

- PEP 8 standardını takip edin
- Type hints ekleyin
- Docstring'ler yazın
- Test yazın

### 3. Testleri Çalıştırma

```bash
pytest tests/ -v --cov=src
pylint src/
black --check src/
mypy src/
```

### 4. Commit Mesajları

Format:
```
[TYPE]: Kısaca açıklama

Daha detaylı açıklama varsa burada yazılır.
Related-To: #123
```

Tipleri:
- `feat`: Yeni özellik
- `fix`: Bug düzeltmesi
- `docs`: Dokumentasyon
- `refactor`: Kod yeniden düzenleme
- `test`: Test ekleme

### 5. Pull Request

Pull request açarken:
- Başlığında `[TYPE]` ekleyin
- Neler değiştirildiğini açıklayın
- İlgili issue'ları referans verin (#123)
- Testlerin geçtiğinden emin olun

## Kodlama Standartları

- **Python 3.9+** kullanın
- **Black** ile biçimlendirin: `black src/ tests/`
- **Pylint** ile kontrol edin: `pylint src/`
- **Type hints** kullanın: `def process_data(data: List[Dict]) -> DataFrame:`

## Test Yazma

Her yeni özellik için test yazın:

```python
# tests/unit/test_example.py
def test_example_functionality():
    """Fonksiyonun temel işlevini test eder."""
    result = my_function(input_data)
    assert result == expected_output
```

## Özellik Talebi

Yeni bir özellik önermek için:
1. GitHub Issues'da açın
2. Başlığı açıklayıcı yapın
3. Neden ihtiyaç duyulduğunu açıklayın
4. Olası çözümleri önerini

## Bug Raporlama

Bug bulduğunuzda:
1. GitHub Issues'da açın
2. Başlık: `[BUG] Kısaca hata açıklaması`
3. Detaylar:
   - Hatayı tekrar sağlayabilir misiniz?
   - Beklenen davranış nedir?
   - Gerçek davranış nedir?
   - Python/OS versiyonu?

## Sorular ve Tartışmalar

- Sorularınız için GitHub Discussions kullanın
- Veya E-posta gönderin

Teşekkürler! 🙏
