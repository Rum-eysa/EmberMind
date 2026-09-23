# Güvenlik Politikası

## Desteklenen Versiyonlar

Şu versiyonlara güvenlik güncellemeleri sağlanır:

| Version | Destekleniyor |
| --- | --- |
| 1.0.x   | ✅ |
| < 1.0   | ❌ |

## Güvenlik Açığı Bildir

Güvenlik açığı bulduysanız, **herkese açık issue açmayın**.

Bunun yerine: security@example.com adresine PrivatKeyi kullanarak bildir.

Güvenlik açığını bilir bildirmez:
1. 90 gün içinde yanıt alacaksınız
2. Düzeltme 30 gün içinde yayınlanacaktır (gözü)

## Güvenlik En İyi Uygulamaları

- `.env` dosyasını asla repository'e commit etmeyin
- API anahtarlarını çevresel değişkenlerde saklayın
- Parolalar için hashing algoritması kullanın
- SQL injection'a karşı prepared statements kullanın
- HTTPS'yi production'da kullanın
