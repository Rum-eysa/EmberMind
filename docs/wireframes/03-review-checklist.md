# Wireframe Gözden Geçirme Protokolü ve Kaydı (EM-074)

Kabul kriteri: *"Wireframe ekiple ve en az bir alan uzmanıyla gözden geçirilir."*
Bu kriter bir **süreç** kriteridir; doküman tarafı aşağıdaki protokol ve kayıt
formuyla karşılanır. Toplantı kayıtları bu dosyaya işlenir (tek gerçek kaynak).

## Protokol

1. **Ön inceleme (ekip, 30 dk):** Backend + frontend geliştiricileri,
   wireframe'deki her kutunun mevcut API sözleşmesine bağlanıp
   bağlanamadığını kontrol eder. Bağlanamayan her kutu ya `ÖNERİLEN API`
   olarak etiketlenir ya silinir.
2. **Alan uzmanı incelemesi (45 dk, en az 1 kişi):** Orman yangın söndürme
   operatörü / KOEM personeli veya eşdeğer uzman. Sorular senaryo bazlıdır:
   - "Kütahya benzeri bir anda ilk hangi ekrana bakardınız?"
   - "Öneri sırası mantığı sahaya uygun mu? Hangi gerekçe eksik?"
   - "What-if senaryosunda hangi girdiyi değiştirmek istersiniz?"
3. **Kapanış:** Her bulgu aşağıdaki tabloya `ID` ile yazılır; kabul edilenler
   issue'a dönüşür, reddedilenler gerekçesiyle kalır (tekrar tartışma maliyeti
   olmasın).

## Bulgu kayıt formu

| ID | Tarih | Kaynak (ekip/uzman) | Ekran/Başlık | Bulgu | Karar | Issue |
|---|---|---|---|---|---|---|
| WF-001 | (doldurulacak) | | | | | |

## Katılımcı kaydı (en az bir alan uzmanı zorunlu)

| Tarih | Ad | Rol (ekip/alan uzmanı) | İmza/onay |
|---|---|---|---|
| (doldurulacak) | | | |

## İncelenecek ekranların kontrol listesi

- [ ] Ana harita — katman anahtarları ve zaman kaydırıcısı gerçek operatör
      davranışıyla eşleşiyor mu?
- [ ] Risk paneli — eşik rengi paleti kurumsal (OGM/Söndürme) renk
      ölçeğiyle uyumlu mu? İlk aşım "zaman" mı "gün" mü olmalı?
- [ ] Öneri paneli — skorlama girdileri sahada hangi sıralamayı üretmeli?
      "Öneri karar yerine geçmez" uyarısının metni uygun mu?
- [ ] What-if — hangi girdilerin override edilebilir olması yeterli?
      Senaryonun kaydedilmemesi kararı kabul ediliyor mu?
- [ ] Saha akışı — çevrimdışı/veri yaşı rozeti saha kullanımına uygun mu?

## Durum

- v1 wireframe'ler hazır (bu doküman seti) — **gözden geçirme toplantısı
  bekliyor**. Kriterin "ekiple ve alan uzmanıyla gözden geçirilir" maddesi,
  yukarıdaki tablolar doldurulmadan KAPANDI sayılmaz; EM-074 kapanış notunda
  bu açık madde olarak belirtilmiştir.
