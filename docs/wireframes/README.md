# EM-074 — Wireframe ve Kullanıcı Akışları

Bu doküman seti, operatör arayüzü (E8) ekranlarının ve kullanıcı akışlarının
wireframe'lerini içerir. Amaç: öneri paneli ve what-if senaryosu gibi
henüz kodlanmamış ekranlar için geliştirmeye **net bir hedef** koymak.

## Doküman haritası

| Dosya | İçerik |
|---|---|
| [01-operator-flows.md](01-operator-flows.md) | Operatör akışı ve saha (müdahale) akışı — ayrı ayrı |
| [02-screens.md](02-screens.md) | Ana harita, risk paneli, öneri paneli, what-if akışı wireframe'leri |
| [03-review-checklist.md](03-review-checklist.md) | Ekip + alan uzmanı gözden geçirme protokolü ve kayıt formu |

## Ekran envanteri ve mevcut API'ye bağlamı

Bir kısım ekran **zaten canlıdır** ve aşağıdaki uç noktaları kullanır; bu
nedenle wireframe'leri "mevcut davranışın belgelenmesi" olarak okuyun.
Öneri paneli ve what-if ekranı ise **planlanan** ekranlardır; önerilen
sözleşmeler 02-screens.md içinde `ÖNERİLEN API` etiketiyle verilir.

| Ekren | Durum | Beslediği uç noktalar |
|---|---|---|
| Ana harita `/ui` | ✅ Canlı (EM-072) | `GET /api/v1/map/layers`, `GET /api/v1/map/layers/{katman}` |
| Kapasite & risk paneli `/panel` | ✅ Canlı (EM-073) | `GET /api/v1/panel/capacity-risk?day=` |
| Öneri paneli `/advisor` | 🔜 Planlı | `GET /api/v1/spread/forecasts?event_key=`, `GET /api/v1/fwi`, kaynak/yol katmanları + yeni öneri ucu |
| What-if senaryosu | 🔜 Planlı | `POST /api/v1/spread/predict` (girdileri override ederek) |

## Veri yokluğu notu (operatör beklentisi)

Canlı ekranlar veritabanı doldurulana kadar boş görünür — bu tasarım gereği
her wireframe'de **"boş durum" (empty state)** kutusuyla ele alınmıştır:
katman verisi yoksa harita/panel bunun yerine "veri kaynağı hiç çalışmadı /
son senkron" bilgisini gösterir (`GET /api/v1/pipeline/status`).

## Okuma sırası

1. Önce [01-operator-flows.md](01-operator-flows.md) — roller ve akışlar,
2. Sonra [02-screens.md](02-screens.md) — ekranların kaba yerleşimleri,
3. Gözden geçirme yapılacaksa [03-review-checklist.md](03-review-checklist.md).

Tüm wireframe'ler ASCII tabanlıdır; araç bağımlılığı yoktur, PR üzerinde
diff'lenebilir ve kod incelemesiyle birlikte güncel kalabilir.
