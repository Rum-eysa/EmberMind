# Ekran Wireframe'leri (EM-074)

Dört ana ekran: **ana harita**, **risk paneli**, **öneri paneli**, **what-if
akışı**. ✅ = mevcut kodda var (davranış belgelenmiştir); 🔜 = planlanan
(mimari kararlar için hedef sözleşme önerilir).

---

## 1) Ana harita `/ui` ✅ (EM-072)

```
+--------------------------------------------------------------------------------+
| EmberMind — Operatör Haritası                        [Zaman kaydırıcısı]        |
|                                        ( 30 | 60 | 120 dk )  ☐ kümülatif        |
+------------------+----------------------------------------------+--------------+
| KATMANLAR        |                                              | LEJANT       |
| ☑ Aktif yangın   |          +----------------------------+      | ● uydu kümesi|
| ☑ Olaylar        |          |                            |      | ▲ manuel olay|
| ☑ Ufuk poligon.  |          |        LEAFLET HARİTA      |      | ▨ 30 dk risk |
| ☐ Yakıt sınıfı   |          |   (OSM karolar + GeoJSON   |      | ▨ 60 dk risk |
| ☐ Sessiz bölge   |          |    katmanları; poligonlar   |      | ▨ 120 dk risk|
| ☐ Kaynaklar      |          |    ufuk rengine boyalı)     |      | ○ ekip üssü  |
| ☐ Yollar         |          |                            |      | ─ yol        |
|                  |          +----------------------------+      | → /panel     |
| [boş durum kutu] |  attribution: FIRMS/OSM/CORINE...             |              |
+------------------+----------------------------------------------+--------------+
```

**Etkileşim sözleşmesi**
- Katman anahtarı = client-side `L.LayerGroup` aç/kapa; veri yeniden
  çekilmez (katalog bir kez yüklenir).
- Zaman kaydırıcısı `forecasts?horizon_minutes=` filtresini değiştirir;
  kümülatif işaretliyse 30+60+120 üst üste çizilir.
- Boş durum: katman `count == 0` ise sol panelde "Bu katmanda kayıt yok —
  son senkron: <pipeline/status>" kutusu.

**Kabul kriteri izi:** "Katmanlar açılıp kapatılabilir; zaman kaydırıcısı ile
ufuklar arasında gezilir" → EM-072 testleri + bu yerleşim.

---

## 2) Kapasite & risk paneli `/panel` ✅ (EM-073)

```
+--------------------------------------------------------------------------------+
| Komutan Kapasite & Risk Paneli          Referans gün: 2026-07-12   [⟳ 60 sn]   |
+-----------------------------------+--------------------------------------------+
| RİSK İNDEKSİ (bölge bazlı)        | KAPASİTE KIRILIMI                          |
| +---------------+----------------+| +----------------------------------------+ |
| | bölge | FWI  | eşik rengi      ||| Üs          | tür     | müsait | toplam | |
| | MTZ-07| 41.2 | ███ very_high   ||| Muğla-1     | arazöz  | 6/8    |   8    | |
| | MTZ-08| 33.9 | ███ high        ||| Dalaman-2   | helik.  | 2/2    |   2    | |
| | MTZ-09| 12.0 | █░░ low         ||| +----------------------------------------+ |
| +---------------+----------------+|| AKTİF OLAYLAR: 3   AKTİF YOL KAPATMA: 2   | |
| eşik: FWI ≥ 30 (RISK_PANEL_... )  || +----------------------------------------+ |
+-----------------------------------+| İLK AŞIM ZAMANI (bölge bazlı)              | |
| EN SICAK BÖLGE: MTZ-07             ||| MTZ-07 → 2026-07-10  MTZ-08 → 2026-07-11 | |
| "eşik aşıldı" rozeti + renk şeridi ||| (hiç aşım yoksa: "—")                    | |
+-----------------------------------+ +----------------------------------------+ |
| attribution / veri yaşı satırı                                             /ui  |
+--------------------------------------------------------------------------------+
```

**Kabul kriteri izi:** "Risk indeksi, eşik rengi, ilk aşım zamanı ve kapasite
kırılımı **tek panelde**" — dört blok tek ekranda, tek istekle
(`GET /api/v1/panel/capacity-risk`) beslenir.

---

## 3) Öneri paneli `/advisor` 🔜 (planlanan)

Komutan "hangi olaya, ne göndermeliyim?" sorusunu sorar; panel EM-008
(ETA/kapasite), EM-015 (yayılım) ve EM-073 (risk) verilerini **kural tabanlı**
birleştirir. Öneri asla otomatik karar değildir — gerekçesiyle sunulur.

```
+--------------------------------------------------------------------------------+
| Öneri Paneli — olay seç: [event_015 ▾]                          [what-if aç →] |
+-------------------------------------+------------------------------------------+
| ÖNERİ SIRASI (skorlanmış)           | GEREKÇE PENCERESİ                        |
| +---------------------------------+ | +--------------------------------------+ |
| | 1. Muğla-1 arazöz x4  ETA 12 dk | | | • Olay 60 dk poligonunda: YOK         | |
| | 2. Dalaman-2 helik.   ETA 19 dk | | | • Rüzgâr 25 km/h → yayılım K-KD      | |
| | 3. Yatağan tim        ETA 31 dk | | | • En yakın üs 8.4 km, yol açık        | |
| +---------------------------------+ | | • Kaynak müsaitlik: 6/8 (MTZ-07)      | |
|                                     | | • Güvenlik: 120 dk poligonu 2. üssü   | |
| [alternatif rota önerisi]           | |   kesiyor → yedek üs gösteriliyor     | |
|                                     | +--------------------------------------+ |
+-------------------------------------+------------------------------------------+
| uyarı şeridi: "Öneriler karar yerine geçmez; komut onayı gereklidir."          |
+--------------------------------------------------------------------------------+
```

**ÖNERİLEN API** (yeni görev: EM-075+ aday):
```
GET /api/v1/advisor/recommendations?event_key=&horizon_minutes=60
→ { recommendations: [{resource, eta_min, score, rationale[]}], safety_flags[] }
```
İstemci yalnızca mevcut uçları okur; skorlama sunucuda, deterministik kurallarla.

---

## 4) What-if akışı 🔜 (planlanan)

Operatör/komutan, girdileri değiştirip "rüzgâr 10 km/h daha hızlı olsaydı?"
senaryosunu **canlı yayılım motoru üzerinde** görür. Motor değişikliği
gerektirmez — `POST /api/v1/spread/predict` girdi override'larını zaten kabul
eder; fark, sonuçların **karşılaştırmalı** çizilmesidir.

```
 Adım akışı:
 [W1] olay/polin seç ──► [W2] girdi override formu ──► [W3] A/B harita ──► [W4] kaydet/karar
                          (mevcut değerler dolu gelir)   (gerçek vs senaryo)

 [W2] Senaryo girdileri          [W3] A/B görünümü
+--------------------------+     +----------------+----------------+
| rüzgâr km/h   [ 35.0 ]* |     |  GERÇEK (30dk) |  SENARYO (30dk)|
| yön   °       [225  ]*   |     |   ▨ poligon    |   ▨▨ poligon   |
| nem    %      [ 18  ]*   |     |  6.9 ha        |  11.2 ha (+63%)|
| yakıt  sınıfı [FM10 ]*   |     |                |   Δ alan rozeti|
| [TEMİZLE]   [HESAPLA →] |     +----------------+----------------+
| * = sistemde okunan değer|      not: senaryo satırı KAYDEDİLMEZ
+--------------------------+      (fire_forecasts'a yalnızca gerçek yazılır)
```

**Sözleşme:** her "HESAPLA", `POST /api/v1/spread/predict` çağrısıdır
(girdiler override). `event_key` **gönderilmez** → senaryo satırı üretilmez,
kirlilik olmaz. Karar verici onaylarsa ayrı bir görevde gerçek tahmine
dönüştürülür.

---

## Ekranlar arası navigasyon haritası

```
        ┌──────────┐   lejant linki   ┌──────────┐   "senaryo aç"   ┌──────────┐
        │  /ui     │ ─--------------► │  /panel  │ ─--------------► │ what-if  │
        │ ana harita│ ◄--------------- │ risk+kapa│                  │  [W1-W4] │
        └──────────┘   olay detayı     └──────────┘                  └────┬─────┘
             ▲          (pin click)           │ "öneri gör"               │
             │                                ▼                           │
             └─────────── (poligon karşılaştırma) ──┬──► ┌──────────┐ ◄──┘
                                                   │    │ /advisor │
                                                   └────└──────────
```
