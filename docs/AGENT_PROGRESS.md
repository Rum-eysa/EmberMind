# Agent Progress — agent/task-automation

Otonom görev yürütme günlüğü. Dal: `agent/task-automation` (main'e asla commit
yok, force push yok, PR draft olarak açılır, merge edilmez).

## Baseline (değişikliklerden önce)

- `make` Windows'ta yok → kapılar eşdeğer komutlarla çalıştırıldı:
  `black --check src/ tests/` ✅ (110 files unchanged), `mypy src/` ✅ (75 files),
  `pylint src/` ✅ 10.00/10, `pytest tests/` ✅ **463 passed**.
- main HEAD: `0c46ec5` (EM-028). Bu oturumun ilk commit'i: `6be70a4`
  `feat(EM-055)` (önceki oturumda tamamlanıp commit'lenmemiş iş; kullanıcı
  onayıyla bu dala alındı + eksik `WHATIF_RECOMPUTE_TARGET_SECONDS`
  settings/.env.example girdileri tamamlandı).

## Görev kaynağı ve eleme

`gh issue list`: 84 açık issue (EM-001..EM-154). GitHub issue'ları kodla senkron
değil: çoğu görev kodda **zaten implemente edilmiş** ama issue açık bırakılmış
(kapama kararı kullanıcıya ait — önceki oturum convention'ı). Bu yüzden görev
listesi issue başlığına değil, **kod boşluğuna** göre süzüldü:

- `src/` içinde EM-id taraması: EM-005..023, 028, 052, 055, 072, 073, 075, 090,
  103, 104, 109 izleri mevcut → bu epiklerin çekirdeği tamam.
- İnsan/altyapı gerektirenler (E10 auth, E12 cloud deploy, E13 E2E/usability,
  E14 demo videosu/pitch, E16 wont) → bu oturumun kapsamı dışı.
- Devasa ML epikleri (E4 sessiz bölge Isolation Forest, E7 sınır ötesi) → tek
  oturumda gerçekçi değil; Mock ile "bitti" göstermeme kuralı gereği girilmedi.

## Sıralı plan (bağımlılık: model → servis → route → UI → test/doküman)

| # | Görev | Epic | Durum | Gerekçe |
|---|-------|------|-------|---------|
| 1 | EM-031 Kapasite kullanılabilirlik durum yönetimi (#31) | E3 | DONE | `en_route` (yolda) durumu sözlükte yoktu; durum→kapasite bağı kısmen var |
| 2 | EM-029 Risk indeksi hesaplama (#29) | E3 | DONE | Risk(t)=yayılım talebi/kapasite ufuk bazlı hiç yoktu; eşikler yapılandırılabilir eklendi |
| 3 | EM-030 Kapasite açığı zaman çizelgesi (#30) | E3 | DONE | EM-029 verisi üzerine çizgi grafik + enterpolasyonlu ilk kritik aşım dakikası |
| 4 | EM-032 Eşik aşımı uyarısı (#32) | E3 | DONE | EM-029/030'a bağlı; histerezis (besleme peak-latch) + canlı besleme "alert" + görsel/sesli |
| 5 | EM-056 Kapasite değişimi senaryosu (#56) | E6 | DONE | EM-055'in arz-tarafı karşılığı; talep sabit, varsayıms kapasiteye karşı yeniden fiyatlama |
| 6 | EM-060 Yeniden hesaplama performans bütçesi (#60) | E6 | DONE | p95 ölçümü + aşım uyarısı + otomatik ölçek küçültme |
| 7 | EM-061 Sıcaklık ve nem what-if parametreleri (#61) | E6 | DONE | EM-055 rüzgâr senaryosunun hava-tarafı genişletmesi; kaydırıcı + delta + Sıfırla |
| 8 | EM-033 Zamana bağlı kapasite modeli (#33) | E3 | DONE | yoldaki kaynağın varış ETA'sı ile çizelge kapasitesi basamaklanır (sabit değil) |
| 9 | EM-057 Dinamik otomatik yeniden hesaplama (#57) | E6 | DONE | rüzgâr/konum/kapasite değişince plan otomatik yenilenir + "ne değişti?" özeti |
| 10 | EM-059 Senaryo kaydetme ve paylaşma (#59) | E6 | DONE | geçici what-if koşularının üzerine girdi-kaydı + token'lı paylaşım bağlantısı |
| 11 | EM-062 What-if geçmişi ve geri alma (#62) | E6 | DONE | otomatik yuvarlanan son-10 koşu listesi + tek tık geri alma |
| 12 | EM-047 Öneri kabul/ret/düzenleme (#47) | E5 | DONE | EM-052 önerisi üzerinde 3 aksiyon; kabul/düzenle kaynağı yolda'ya çeker; her karar denetim kaydı |
| 13 | EM-046 Öneri gerekçesi / açıklanabilirlik (#46) | E5 | DONE | her öneri için "neden?" + reddedilen alternatifler ve gerekçeleri; build_proposals'ı açıklar, yeniden sıralamaz |
| 14 | EM-049 Kaynak tipine göre ETA — kuş uçuşu vs yol ağı (#49) | E5 | DONE | hava kaynakları (helikopter/İHA) kuş uçuşu ETA, kara ekipleri yol ağı; öneri/rota/konuşlanmada `travel_mode` |
| 15 | EM-048 Önerinin etki karşılaştırması (#48) | E5 | DONE | "uygulanırsa" vs "uygulanmazsa" risk ufuk bazında yan yana; EM-056 re-pricing motoru + EM-052 önerileri; canlı/tavsiye, kalıcılık yok |
| 16 | EM-053 Çifte atama / kaynak çakışma önleme (#53) | E5 | DONE | kabul/düzenle artık başka olaya atanmış birimi 409 ile engeller; müsaite alma + görev bitişi otomatik müsait; atama EM-047 denetim kaydından türer (migration yok) |
| 17 | EM-051 Kabul edilen öneriden saha görev kartı (#51) | E5 | DONE | hedef (olay+koordinat) + varış (ETA/arrival_eta) + risk notu (EM-029 tepe bandı); kart EM-047 denetim anlık görüntüsünden canlı kurulur, kalıcılık yok |
| 18 | EM-050 Kısıt tabanlı optimizasyon (#50) | E5 | DONE | menzil/mesai/gece/yol kapalılığı ihlali olan öneri üretilmez + nedeni gösterilir; opsiyonel limit kolonları (V022 ADD-only, NULL=sınırsız); EM-046/katman sıralama sözleşmesi korunur |
| 19 | EM-045 Kaynak önerisi motoru — öneri başına beklenen risk düşüşü (#45) | E5 | DONE | sıralı öneri listesinde her satır `expected_risk_reduction` taşır (tek birimin tepe EM-029 riskine varış-duyarlı marjinal etkisi); `build_proposals` saf kalır, zenginleştirme uçta katman |
| 20 | EM-054 Öneri kabul/ret geri bildirim döngüsü — analiz (#54) | E5 | DONE | EM-047 karar denetimi üzerinde salt okunur toplulaştırma: kabul/ret oranları, tip bazında kırılım, en çok reddedilen tipler, ret gerekçeleri + iyileştirme fikirleri; `release` hariç, tablo/migration yok |
| 21 | EM-063 Saat dilimi, birim ve koordinat standardizasyonu (#63) | E7 | DONE | sunum katmanı: UTC→yerel (IANA, TR/GR varsayılanı) + 16 yön pusula + ayarlanabilir koordinat formatı (decimal/DMS) + metrik birim tanımı; durumsuz uçlar, tablo/migration yok |
| 22 | EM-064 Ülke bazlı ayrış envanter (#64) | E7 | DONE | kapasite **ülke ayrı ayrı** toplanır/gösterilir; `merged_by_default:False` + açık `atanmamış` kovası → iki ülke sessizce birleştirilmez; `country` kolonu zaten mevcut, tablo/migration yok |
| 23 | EM-065 Dış destek ihtiyacının erken tahmini (#65) | E7 | DONE | EM-030/033 açık çizelgesi üzerinde deterministik ileri projeksiyon: "ulusal kapasite T+X dk yetersiz, ≈ Y birim dış destek" + talep-gönderme son tarihi; açığın gerçekleşmesinden önce uyarı, tablo/migration yok |
| 24 | EM-066 Sınır ötesi ortak durum görünümü (#66) | E7 | DONE | coord→ülke atfı (pilot sınır boylamı TR/GR) ile ülke ülke yangın+risk+dış destek tek ortak ekranda; **ayarlanabilir veri paylaşım kapsamı** (fire/risk/support alt kümesi); tablo/migration yok, yetki politikası EM-070'e bırakıldı |
| 25 | EM-067 Sınır bölgesi yangın yayılımı (#67) | E7 | DONE | sınır geçiş olasılığı + süresi deterministik geometriyle: cos(EM-015 baş yönü ↔ sınır yönü) olasılık, uzaklık/(ROS×pay) dakika; EM-066 pilot sınır boylamı ortak; pencere içi/dışı bayrağı; tablo/migration yok |
| 26 | EM-068 Çok dilli arayüz (TR/EL/EN) (#68) | E7 | DONE | arayüz metinleri koda derlenmiş **i18n mesaj kataloğundan** çözülür (TR+EN tam, EL çekirdek; eksik→EN→ham anahtar fallback); `normalize_language`/`translate`/`get_messages`/`coverage`; `I18N_DEFAULT_LANGUAGE`; `GET /api/v1/i18n/messages`+`/config`; panel dil seçici + `data-i18n`; tablo/migration yok (persistence none) |
| 27 | EM-070 Ülke bazlı yetki ve veri paylaşım politikası (#70) | E7 | DONE | EM-066'nın ertelediği **yetki katmanı**: ülke+rol kapsamına göre paylaşılan alan grupları (fire/risk/support); öncelik **adlı rol→ülke varsayılanı(`*`)→yapılandırılmış varsayılan** (`SHARE_POLICY_DEFAULT_FIELDS`); **ek-yazılımlı** `country_share_policy` (en yeni=geçerli, dizi=denetim); `preview`; matris/preview/POST/audit uçları; panel politika kartı; EM-066 `?fields=` korundu |
| 28 | EM-069 Ortak sınır ötesi erken uyarı bildirimi (#69) | E7 | DONE | EM-067 geçiş projeksiyonunu **eşik kapısından** geçirip (olasılık + geçiş süresi) karşı ülke koordinasyon birimine **önceden tanımlı kanaldan** bildirim düzenler/kaydedeeder; **kenar-tetiklemeli** (olay+hedef başına tek açık) + geçiş öngörülmezse otomatik **çözülen**; `crossborder_notification` (V024); status/sweep/dispatch/list/config uçları; panel "Tara ve bildir" kartı |
| 29 | EM-071 Dış destek talebi taslağı üretme (#71) | E7 | DONE | EM-065 erken tahmininden olay başına **ihtiyaç/zaman/konum**la **otomatik tek satır özet** + çok satırlı **düzenlenebilir** metin gövdesi besteler; **TR/EN/EL** (EM-068 `normalize_language`; bilinmeyen dil→400); açık öngörülmeyen olay "yeterli" notlu taslak; panel kartı: olay seç + metin alanı + **Kopyala** + **PDF/Yazdır** (gizli iframe); tablo/migration yok (persistence none) |
| 30 | EM-078 Sessiz bölge güven paneli (#78) | E8 | DONE | Mevcut `silent_regions` üzerinde **okuma zamanı** deterministik güven puanı: bbox içi aktif yangın=ağır çelişki cezası + en yakın yangın **yakınlık cezası** (PROXIMITY_FAR_KM'ye kadar doğrusal); `[0,1]` kırp + **yüksek/orta/düşük** bant; güven azalan **sıralı liste**; `?confidence=` bant filtresi; operatör haritası **Sessiz Bölgeler** paneli satır→**harita senkron seçim** (fitBounds + vurgu dikdörtgeni); model/migration yok (persistence none) |
| 31 | EM-079 Panel durum kataloğu + bağlantı bandı (#79) | E8 | DONE | 9 panel için tek **salt okunur durum kataloğu** (`PANEL_STATES`: title/loading/empty/error/error_action, Türkçe); `error_action` her zaman **yapılabilir fiil** içerir (hata ne olduğunu + ne yapılacağını söyler); `CONNECTION_LOST` bandı + `connection_state()`; `/api/v1/ui-states` + `/ui-states/panel/{key}` (bilinmeyen→404); operatör haritası `#conn-lost` bandı WebSocket `onclose`/REST `catch` ile görünür, `onopen`/`ok` ile kalkar; `.skel`/`.panel-err` yardımcıları sessiz/etki/konuşlanma panellerinde; `UI_STATE_LANGUAGE`; model/migration yok (persistence none) |
| 32 | EM-081 Olay zaman çizelgesi (#81) | E8 | DONE | Canlı değişim beslemesi (EM-090: `fire_event`/`forecast`/`alert`) + operatörün **kabul ettiği** öneri denetim kayıtlarını (EM-047 `accept`/`edit`) tek **kronolojik (yeniden eskiye)** akışta birleştiren salt okuma zamanı projeksiyonu; sabit `category` + Türkçe `category_label` + `event_key` + UTC `at` + `ref`; `reject`/`release` hariç; zaman eşitliğinde **kaynak-sırası + id** deterministik; `?event_key=`/`?category=`/`?limit=` (bilinmeyen kategori yutulmaz; limit `[1,MAX]` kırp); `/api/v1/event-timeline` + `/config`; UI Zaman Çizelgesi düğmesi + kategori filtresi + renk kodlu liste; `ui_states`'e `event_timeline` anahtarı; `EVENT_TIMELINE_DEFAULT/MAX_LIMIT`; model/migration yok (persistence none) |
| 33 | EM-082 Çoklu yangın yönetimi (#82) | E8 | DONE | Aktif `fire_events` + `suppression_resources` durumları + EM-047/053 karar denetim kaydını birleştiren **salt okuma zamanı** çoklu-yangın envanteri; her aktif yangına konuşlanmış birim EM-053 kuralıyla (hâlâ `en_route`/`deployed` + en yeni satır `accept`/`edit`); üç deterministik **çapraz-yangın çakışma** kovası: `orphaned_units` (meşgul ama olayı artık aktif değil) / `contended_bases` (üs birden çok aktif yangına veriyor) / `understaffed_critical` (acil yangın boş); `event_key` olayları kapsar ama çakışma taraması **küresel**; şiddet sıralı envanter; `/api/v1/multi-fire` + `/config`; UI Çoklu Yangın paneli (listesi + çakışma uyarıları); `ui_states`'e `multi_fire` anahtarı; `MULTI_FIRE_MAX_EVENTS`; model/migration yok (persistence none) |
| 34 | EM-083 Salt okunur belediye görünümü (#83) | E8 | DONE | Ayarlanabilir bölge koordinat kutusuna (varsayılan: pilot bölge) kapsamlanan **salt okuma zamanı** projeksiyonu; kutu içi aktif `fire_events` acilden eskiye sıralı + yalnızca sade çekirdek alanlar (anahtar/ad/şiddet/başlangıç/konum); şiddet histogramı + tek `headline` durumu + **yerel vs havuz** `suppression_resources` kapasite ayrımı; sınır kapalı (dahil); yalnızca-operatör kontrolleri (öneri/karar/what-if/sevk) bilinçli **gizlenir** ve `omitted_operator_controls` ile adlandırılır; `?severity=` listeyi daraltır ama `headline`/sayılar bölge-geneli kalır, tanınmayan kod sessiz filtre edilmez; `/api/v1/municipality-view` + `/config`; UI Belediye paneli; `ui_states`'e `municipality_view` anahtarı; `MUNICIPALITY_VIEW_*`; model/migration yok (persistence none) |
| 35 | EM-086 Bildirim merkezi ve sesli uyarı ayarları (#86) | E8 | DONE | Canlı akıştaki (`live_updates` kind=`alert`, EM-032/090) uyarıları en yeniden eskiye **okundu/onaylandı** durumuyla projekte eden bildirim merkezi; kritik bandlar (`kritik-yakin`/`kritik`) yalnızca **onaylanınca** düşer (okumak çözmez), diğerleri okununca düşer; tekil operatör-geneli **sesli alarm** (aç/kapa + en-düşük-bant) ilk okumada ayarlardan tohumlanır, güncellemede kalıcıdır (geçersiz bant→400); `should_sound` seviye kapısı; özet sayaçları (okunmamış/bekleyen-onay/sesli) her zaman tüm pencereyi anlatır; `mark_read`/`acknowledge`/`mark_all_read`; `notification_states` + `notification_sound_settings` (V025); `/api/v1/notifications` + `/config` + `/sound` GET/PUT + `/{id}/read` + `/{id}/acknowledge` + `/read-all` (bilinmeyen uyarı→404); UI Bildirimler paneli (satır eylemleri + sesli kontrol); `ui_states`'e `notification_center` anahtarı; `NOTIFICATION_MAX_ALERTS/SOUND_ENABLED/SOUND_MIN_LEVEL` |
| 36 | EM-087 Durum raporu (SITREP) PDF dışa aktarımı (#87) | E8 | DONE | Komutanın üst makama/karşı ülkeye ileteceği **tek sayfalık** durum özetini **okuma zamanı** derleyen projeksiyon; EM-029 `compute_risk_index` ile aktif yangınların yayılım tahmini (ufuk başına alan) + risk bandını çeker, `fire_events`'ten şiddet/başlangıç/sentetik notla zenginleştirir, en sıcak olay için EM-052 `build_proposals` önerilerini ekler (yol ağı yoksa `available:false`+gerekçeyle **zarifçe düşer**); `generated_at` zaman damgası + **sentetik veri rozeti** (EM-104 not işaretinden); şiddet-sonra-en-sıcak sıra, `max_fires` kırpma ama küresel toplam kalır; `?event_key=` tek-olay kapsamı (bilinmeyen→404); `sections` sabit (yangın/tahmin/risk/öneri/zaman); `/api/v1/sitrep` + `/config`; UI Durum Raporu paneli + **PDF/Yazdır** (gizli iframe tek sayfa döküm); `ui_states`'e `sitrep` anahtarı; `SITREP_MAX_FIRES/RECOMMENDATION_LIMIT`; model/migration yok (persistence none) |
| 37 | EM-088 Kullanıcı ayarları (dil, birim, tema) kalıcı profil (#88) | E8 | DONE | EM-068 dili yalnız tarayıcı `localStorage`'ında, EM-063 saat dilimi/koordinat biçimi istek başına türetilir (ikisi de `persistence=none`), tema da yerelde kalır — sunucu tarafında **kayıtlı tercih profili** hiç yoktu; **tek operatör-wide satır** (sabit anahtar `default`: `language/theme/timezone/coordinate_format`, EM-086 tek-satır deseni); satır yoksa okuma ayarlardan türetilen varsayılanı `settings_default` ile **yazmadan** döner, ilk `PUT` satırı oluşturur; **kısmi güncelleme** her alanı sistemin zaten tanıdığı kümesine karşı doğrular (dil EM-068, saat/koordinat EM-063, tema `dark|light`; geçersiz→400); `reset` satırı siler → sonraki okuma `settings_default`; `GET/PUT/DELETE /api/v1/preferences` + `/config`; UI `risk_panel`: açılışta kayıtlı profil yüklenir (tema+birim+dil **anında uygulanır**), saat/koordinat açılır listeleri + **Varsayılana dön** düğmesi eklenir, `localStorage` çevrimdışı aynaya iner; `UI_DEFAULT_THEME` (dil/saat/koordinat EM-068/063'ten miras); `i18n` `btn.pref_reset` (TR/EN/EL); `user_preferences` (V026) |
| 38 | EM-089 Vardiya devri notları ve olay notu ekleme (#89) | E8 | DONE | Canlı akış (EM-090), kabul edilen öneriler (EM-047) ve zaman çizelgesi (EM-081) makine üretimidir — operatörün serbest metin yazabileceği **kalıcı bir not yüzeyi** ve insan yorumunu makine görünümüyle birleştiren **devir özeti** hiç yoktu; `event_notes` modeli + **V027** (olay başına `event_key/body/author`, salt-additive); `shift_handover.py`: `add_note` (boş not/tanınmayan olay yükseltir), `list_notes` (yeniden eskiye + olay filtresi + `MAX_NOTES` kırpma), `get/delete_note`, `handover_summary` — aktif olay kartları (EM-082 kadro+çakışma) ile notları EM-081 kronolojik akışında **okuma zamanında** birleştirir, notlar `operator_note` kategorisiyle akışa katılır (**EM-081'in 4-kategori kümesi/testlerine dokunulmadı** — bu yüzden ayrı servis); `GET /api/v1/shift-handover` + `/notes` GET/POST, `/notes/{id}` GET/DELETE, `/config` (tanınmayan olay→404, boş→400); `ui_states`'e `shift_handover` anahtarı; UI Vardiya Devri paneli (form + Ekle/Yenile/Sil + Devir Özetini Oluştur, haritadan olay önceden doldurulur); `SHIFT_HANDOVER_MAX_NOTES`; 27 test |
| 39 | EM-034 Kapasite varsayımları yönetim ekranı — denetim kaydı (#34) | E3 | DONE | EM-028 düzenleme yüzeyini (tip başına `ha/saat` + doğrulama + panel) zaten vermişti; ama yalnızca **tek `updated_by` kolonu** tutulur, eski değer/kim/ne zaman geçmişi hiç olmaz — "değişiklik denetim kaydına yazılır" (kabul #2) gerçek boşluk; `capacity_assumption_audit` modeli + **V028** (her gerçek değişim için `resource_type/old/new/updated_by` + damga, salt-additive, kapasite matematiğini beslemez); `update_assumptions` değer gerçekten değişince denetim yazar (aynı değeri tekrar kaydetme üretmez) + `applied_count` döner, yeni `list_audit` (yeniden eskiye + tip filtresi + `[1,MAX]` kırpma); `PUT` gövdesine `updated_by`, `GET /api/v1/capacity/assumptions/audit`; `risk_panel` kartına **Düzenleyen** + Değişiklik geçmişi tablosu (açılışta + kayıt sonrası yenilenir); `CAPACITY_AUDIT_DEFAULT/MAX_LIMIT`; 17 test |
| 40 | EM-094 Olay ve uyarı webhook'ları (#94) | E9 | DONE | Bütünleştirici olay/uyarıların alt sistem servisine anında **itilmesini** ister (kabul: URL+olay tipleri yapılandırılabilir / imzalı istek + yeniden deneme / teslim geçmişi görüntülenebilir) — canlı akış (EM-090) + bildirim merkezi (EM-086) yalnızca **çekme**; dışa dönük imzalı itme kanadı hiç yoktu (`webhook` kod tabanında tamamen yok); `webhook_subscriptions` + salt-eklenen `webhook_deliveries` defteri (**V029**; `as_dict` gizli anahtarı maskele→`has_secret`); `signature_for` `"<ts>.<body>"` HMAC-SHA256 (`X-EmberMind-Signature: t=…,v1=…`); CRUD (URL http(s) + olay tipleri `LIVE_KINDS` kataloğuna karşı + azami); `dispatch_event` en son feed olaylarını imzalar (`dry_run`/`simulate_fail_for`), `retry_due` sınırlı üstel geri çekilme bütçesini tek kapı olarak uygular, `record_attempt` taşıyıcı düğümü; **gerçek HTTPS taşıyıcısı bilerek çağrılmaz** (EM-069 emsali: canlı ağ gönderimi "teslim edildi" diye sahtelenmez — defter imzalı isteğin kalıcı kaydı); `/api/v1/webhooks/*` + config/overview/subscriptions/dispatch/preview/attempt/retry/deliveries; `WEBHOOK_MAX_SUBSCRIPTIONS/DELIVERIES/RETRIES/BACKOFF_SECONDS`; `ui_states`'e `webhooks`; `operator_map` Webhook'lar paneli (abonelik formu + Dağıt/Yeniden Dene + imzalı teslim geçmişi); 32 test |
| 41 | EM-096 Birleşik denetim kaydı (#96) | E10 | DONE | Yönetici hangi alt sistemden gelirse gelsin **kimin hangi kararı/değişikliği ne zaman verdiğini** tek yerde görmek ve kayıtların **değiştirilemez/silinemez** olmasını ister (kabul: "kabul/ret, senaryo, eşik/kapasite varsayımı değişiklikleri kim/ne zaman/ne ile kaydedilir. Kayıtlar silinemez") — bugüne dek denetim **parça parça**ydı (kapasite `capacity_assumption_audit` EM-034, kararlar `recommendation_decisions` EM-047, paylaşım/webhook kendi tabloları); tek, birleşik ve değişmez bir defter yoktu (`audit_trail`/birleşik uç kod tabanında tamamen yok); `AuditTrailEntry` + yalnızca-eklenen **V030** (alan+eylem+özne anahtarı+**aktör**+`summary`+`old_value`/`new_value` JSON anlık görüntüsü); `record_audit` kontrollü sözlükleri doğrular (bilinmeyen alan/eylem + boş aktör/özet→`AuditError`), `list_audit` öksüzden eskiye + alan/aktör/özne filtresi + `AUDIT_MAX_LIMIT` kırpma, `audit_config` sözlükler + değişmezlik politikası, `count_by_domain` panel sayacı; **uygulama dikişinde güncelleme/silme/temizleme fonksiyonu YOKTUR** ("kayıtlar silinemez" garantisi budur; okuma hiçbir şey yazmaz); `/api/v1/audit` config + özet beslemesi + tek POST (güncelle/sil UÇLARI BİLİNÇLİ YOK); `AUDIT_DEFAULT/MAX_LIMIT`; `ui_states`'e `audit_trail`; `operator_map` Birleşik Denetim Kaydı paneli (alan/aktör filtresi + yeni kayıt + alan sayımlı değişmez geçmiş); 21 test |
| 42 | EM-035 Bölge bazlı sinyal baz çizgisi (#35) | E4 | DONE | Sessiz bölge **anomalisi**nin anlam kazanması için önce "normal" öğrenilir (kabul: yangın öncesi sinyal seviyesinin hücre bazlı normal değeri + 30 günlük baz çizgi hücre bazında + sentetik iletişim/rapor akışı, gerçek kaynak arayüzü soyutlanır) — EM-078 yalnızca operatör kayıtlarının güven bandını canlı yangınlarla derecelendiriyordu; sinyal baz çizgisi/`SignalSource` soyutlaması hiç yoktu; `signal_baseline.py` (persistence none): `SignalSource` ABC + deterministik `SyntheticCommunicationSource` (sha256; SENTETİK etiketli, asla gerçek gibi sunulmaz; trafik/sosyal medya/sensör `planned` — uygulanmaz/hapsedilmez, ağ yok), `monitoring_cells` satır×sütun ızgarası, `compute_cell_baseline` kayan 30 günde ortalama/yayılım/medyan/aralık + son okumanın z-skoru (`candidate_silent = z ≤ -eşik`; anomali sınıflandırıcısı EM-036'ya bırakıldı), en-sessiz-önce rapor; `/api/v1/signal-baseline` + `/config` + `/cells/{key}` (kötü kaynak/tarih→400, bilinmeyen hücre→404); `SIGNAL_BASELINE_*` + `SIGNAL_PILOT_*`; `ui_states`'e `signal_baseline`; `operator_map` paneli (kaynak seçici + referans tarih + yalnızca-sessiz-adayı + harita senkron hücre seçimi); 28 test |
| — | EM-058 Yol kapalılığı (#58) | E6 | ATLANDI | **zaten mevcut**: closure endpoint + kapama-farklı yönlendirme + `build_proposals` — gerçek boşluk değil |

## Varsayımlar ve kararlar

- **EM-055 commit'i**: önceki oturumda tamamlanıp No-Auto-Push ile bekletilen iş,
  kullanıcı onayı (soru-cevap) ile bu dala tek commit alındı.
- **make yok**: Windows PowerShell'de `make` bulunamadı; `make ci-check` yerine
  aynı kapılar (`black`, `pylint`, `mypy`, `pytest`) + repo convention'ı `bandit`
  elle çalıştırılıyor.
- **Issue kapatma yok**: tamamlanan görevlerin issue'su kapatılmaz (kullanıcı
  kararı); issue'ya yalnızca özet yorum atılır.
- **EM-029 formül yorumu:** issue'nun sözel formülü `alan(t)/kapasite(t)`
  boyutsal olarak saat verir; yerine EM-055'in yayınlanan `gap = talep −
  kapasite` semantiğiyle tutarlı **birimsiz oran** (ha/saat talep ÷ ha/saat
  etkin kapasite) seçildi — `>1` yangının kapasiteden hızlı büyümesi demek.
  Ufuklar `SPREAD_HORIZON_MINUTES`'ten (30/60/120) okunur, sabitlenmez.
- **EM-029 risk indeksi**, mevcut EM-073 panelindeki `risk_index` (şu an FWI
  aynalama) alanını **değiştirmez**; yeni bağımsız `Risk(t)` endeksi ayrı
  servis/endpoint olarak eklenir (EM-073 kabul testleri bozulmaz).
- **EM-031**: `out_of_service` korunur, `en_route` eklenir; kapasite hesabı
  yalnızca `available` saydığı için `en_route` otomatik hariç → "durum değişimi
  indeksi hemen etkiler" kriteri bu yolla sağlanır.
- **EM-030 ilk aşım tanımı:** "eşik aşımı" örnek metni ("T+47 dk'da kritik")
  kritik bandına giriş olarak yorumlandı → eşik `RISK_INDEX_CRITICAL_NEAR_MAX`
  (1.2). Motor yalnızca kesikli ufukta tahmin verdiği için aşım dakikası
  komşu iki ufuk arasındaki oranda **doğrusal enterpolasyon** ile bulunur;
  kapasite zamanla sabit alınır (anlık etkin kapasite, EM-028).
- **EM-032 histerezis:** yeni tablo/migration yerine mevcut append-only canlı
  besleme (EM-090 `alert` satırları) durum deposu olarak okundu → süreçler
  arası (Celery/API) tutarlı. **peak-latch:** yalnızca önceki en yüksek
  uyarılan bandın üstüne çıkınca uyarı; bu muhafazakâr davranış düşüş-sonrası
  aynı tepeye dönüşte tekrar uyarmaz (kabul kriteri "tekrarları bastır"
  ile tutarlı). Ses = WebAudio bip (dosya asset yok, kapsam büyütmeme).
- **EM-056 arz-tarafı what-if:** EM-055 rüzgâr (talep) what-if'inin tersi.
  Yayılım tahmini **yeniden hesaplanmaz** (talep sabit); yalnızca kapasite
  değiştirilir → EM-029 `_horizons_for` ile açık/bant yeniden fiyatlanır.
  Ek birimler `assumption_map`'daki tür başına ha/saat varsayımıyle
  değerlendirilir (canlı envantere dokunulmaz, rezervasyon yok). `resolves_gap`
  = mevcut açık >0 VE senaryo açığı ==0. Endpoint hatası `RiskIndexError`
  (bulunamayan olay) bilinçli olarak **400** (wind what-if ile tutarlı; 404
  risk-index GET'in aksine POST gövde hatası).

## Görev logları

### EM-031 — Kapasite kullanılabilirliği durum yönetimi (#31) — DONE
- **Eksik analizi:** `RESOURCE_STATUSES` dört duruma sahipti; issue'nun
  istediği "yolda" (`en_route`) yoktu. Durum→kapasite bağı zaten doğru
  kuruluymuş (`effective_capacity` yalnızca `available` sayar) ama bu
  sözlüğe eklenince otomatik çalışır hale geldi.
- **Kapsam:** `src/models/inventory.py` (durum + yorum),
  `src/services/inventory.py` (`STATUS_ALIASES`: en_route/en-route/enroute/
  yolda; `capacity_summary` `en_route` sayacı),
  `src/static/inventory.html` (filtre + form `Yolda`, `STATUS_TR`,
  `em-badge--info`), `src/static/components.css` (`.em-badge--info`),
  testler (`test_inventory.py`, `test_capacity.py` — 4 yeni test),
  CHANGELOG + docs/api.
- **Kanıt:** durum `en_route` yapılınca `GET /api/v1/capacity/effective`
  anında düşüyor (servis + endpoint testi). Migration gerekmedi (String
  kolon, CHECK yok).
- **Kapılar:** black/mypy/pylint(10.00)/bandit(0) yeşil; pytest **467**.
- **Commit:** `feat(EM-031): ...` (bu dal).

### EM-029 — Operasyonel risk indeksi Risk(t) (#29) — DONE
- **Eksik analizi:** Olay bazlı, ufuk bazlı Risk(t) hiç yoktu; EM-073 paneli
  yalnızca FWI tabanlı BÖLGE riski gösteriyordu. Kapasite (EM-028) ve talep
  tanımı (EM-055 `demand_ha_h`) mevcuttu → yeni bağımsız servis bunların
  üzerine kuruldu, hiçbiri değiştirilmedi.
- **Kapsam:** `src/config/settings.py` + `.env.example`
  (`RISK_INDEX_NORMAL_MAX/CAUTION_MAX/CRITICAL_NEAR_MAX`),
  `src/services/risk_index.py` (demand/band sınıflandırma/en güncel
  `FireForecast` seçimi/boş kapasite → `null`+`kritik`/peak+summary),
  `src/routes/risk_index.py` (`GET /api/v1/risk-index[?event_key=]` 404
  dahil, `GET /api/v1/risk-index/config`), `src/fastapi_app.py` kaydı,
  `risk_panel.html` **Olay Risk İndeksi — Risk(t)** kartı (renk kodlu
  olay×ufuk tablosu, tooltip, özet), `tests/unit/test_risk_index.py`
  (18 test), CHANGELOG + docs/api.
- **Bağlantılar:** EM-031 — meşgul/yolda kaynak kapasiteye girmediği için
  indesten otomatik düşer (testyle kilitli). EM-030 bu payload'ın
  `gap_ha_h` alanını çizecek; EM-032 `level` değişimini izleyecek.
- **Kapılar:** black/mypy(77 dosya)/pylint(10.00)/bandit(0) yeşil;
  pytest **485** (467 + 18 yeni).
- **Commit:** `feat(EM-029): ...` (bu dal).

### EM-030 — Kapasite açığı zaman çizelgesi (#30) — DONE
- **Eksik analizi:** EM-029 olay×ufuk verisini sayısal tablo olarak
  veriyordu; issue zaman ekseninde **çizgi grafik** + "ilk eşik aşım
  zamanı" istiyordu. Ayrı depolama/servis gerekmez → EM-029 servisinde
  `capacity_gap_timeline` + `_first_exceedance` eklendi (veri kaynakları
  yeniden kullanıldı).
- **Kapsam:** `src/services/risk_index.py` (`capacity_gap_timeline`,
  `_first_exceedance` enterpolasyonu), `src/routes/risk_index.py`
  (`GET /api/v1/risk-index/timeline`), `risk_panel.html` **Kapasite Açığı
  Zaman Çizelgesi** kartı (satır içi SVG talep vs kapasite çizgisi, kritik
  aşım işaretçisi, başlıkta T+dk), `tests/unit/test_risk_index.py` (+8
  timeline testi: seri/enterpolasyon T+100, aşım yok, sıfır kapasite,
  en-erken-özet, endpoint 200/404, HTML), CHANGELOG + docs/api.
- **Karar:** harici grafik kütüphanesi eklenmedi (kapsam büyütmeme);
  token tabanlı satır içi SVG. Enterpolasyon varsayımı yukarıda.
- **Kapılar:** black/mypy(77)/pylint(10.00)/bandit(0) yeşil;
  pytest **493** (485 + 8 yeni).
- **Commit:** `feat(EM-030): ...` (bu dal).

### EM-032 — Eşik aşımı uyarısı, histerezis (#32) — DONE
- **Eksik analizi:** Canlı beslemede `alert` türü ve EM-090 WebSocket/REST
  altyapısı zaten vardı; ancak risk **seviye eskalasyonunda** uyarı yazan
  bir değerlendirici ve operatörde **sesli** bildirim yoktu. Harita alert'i
  yalnızca metin olarak flash'lyordu.
- **Kapsam:** `src/config/settings.py` + `.env.example`
  (`RISK_ALERTS_ENABLED`), `src/services/risk_alert.py`
  (`evaluate_risk_alerts`, beslemeden `_last_alerted_index` peak-latch
  histerezisi; normal uyarmaz), `src/routes/risk_index.py`
  (`POST /api/v1/risk-index/alerts/evaluate` — session commit ile kalıcı),
  `operator_map.html` (`#alert-banner` görsel bant, `beepTwice` WebAudio
  sesli bildirim, `🔔 Ses` aç/kapa + ilk-jest audio prime, `navigator.vibrate`,
  30 sn'de bir evaluate yoklaması), `tests/unit/test_risk_alert.py`
  (9 test), CHANGELOG + docs/api.
- **Kanıt:** dikkat'e çıkışta 1 uyarı; aynı seviyede tekrar→0 (histerezis);
  kritik'e daha çıkış→yeni uyarı; normal/forecast-yok/kapalı→0 (test).
- **Kapılar:** black/mypy(78)/pylint(10.00)/bandit(0) yeşil;
  pytest **502** (493 + 9 yeni).
- **Commit:** `feat(EM-032): ...` (bu dal).

### EM-056 — Kapasite değişimi what-if senaryosu (#56) — DONE
- **Eksik analizi:** EM-055 rüzgâr (talep-tarafı) what-if'i mevcuttu ama
  komutanın *arz* sorusu ("ek kaynak açığı nasıl değiştirir?") karşılıksızdı.
  Yeni yayılım motoru gerekmez — EM-029 `_horizons_for`/`level_thresholds`
  yeniden kullanılarak talep sabit tutulur, yalnızca kapasite değiştirilir.
- **Kapsam:** `src/services/capacity_whatif.py`
  (`_validated_added` girdi bekçisi, `scenario_capacity` ek birimleri
  ha/saat varsayımıyla fiyatlar, `run_capacity_whatif` olay×ufuk açık/bant
  öncesi-sonrası + `resolves_gap`), `src/routes/whatif.py`
  (`WhatIfCapacityRequest` + `POST /api/v1/whatif/capacity`, config'e
  `capacity_attribution`), `risk_panel.html` **Kapasite What-If (EM-056)**
  kartı (ek kaynak girdileri + olay seçki `refreshRiskIndex`'ten beslenir,
  `runCapacityWhatIf()` POST, açık değişim tablosu + "çözüldü" rozetleri,
  `escapeHtml`), `tests/unit/test_capacity_whatif.py` (19 test), CHANGELOG +
  docs/api.
- **Kanıt:** 1 müsait ekip (2.0 ha/s) + T+30 talep 12.0 → açık 10.0 (kritik);
  +1 helikopter (→14.0) açığı kapatır, bant dikkat'e düşer, `resolved_by_addition`
  True (servis + endpoint testi). Geçersiz tür/negatif/tamsayı-dışı →
  `CapacityWhatIfError` (→400).
- **Kapılar:** black(117)/mypy(79)/pylint(10.00)/bandit(0) yeşil;
  pytest **521** (502 + 19 yeni).
- **Commit:** `feat(EM-056): ...` (bu dal).

### EM-060 — Yeniden hesaplama performans bütçesi (#60) — DONE
- **Eksik analizi:** EM-022 bir *benchmark* (`spread_perf.py`, tek seferlik
  mod kıyasi) ve EM-055 anlık `within_target` işareti sunuyordu; ancak
  **kayyan p95** gecikme ölçümü, süreğen aşım tespiti ve buna bağlı
  **otomatik çözünürlük küçültme** hiç yoktu. Görev ima ettiği bağlantıları
  da içerir: telemetri tablosu+migration, ayarlar, canlı-besleme uyarısı,
  rüzgâr ucuna entegrasyon, UI kartı.
- **Kapsam:** `src/models/perf_budget.py` (`RecomputeLatencySample`,
  V017 migration, `models/__init__` kaydı), `src/config/settings.py` +
  `.env.example` (`PERF_BUDGET_*`), `src/services/perf_budget.py`
  (`percentile` numpy-tanımı enterpolasyon, `budget_status` kayan p95,
  `_CoarseSettings` delege + `resolve_recompute_settings`,
  `record_recompute_latency` kenar-tetiklemeli `alert`),
  `src/routes/perf_budget.py` (3 uç) + `fastapi_app.py` kaydı,
  `src/routes/whatif.py` rüzgâr ucuna **ek** `perf_budget` alanı +
  gecikme örneği, `risk_panel.html` **Yeniden Hesaplama Bütçesi** kartı +
  `refreshPerfBudget()`, `tests/unit/test_perf_budget.py` (20 test),
  CHANGELOG + docs/api.
- **Varsayım:** Ölçek küçültme poligon köşesini (36→`PERF_BUDGET_COARSE_VERTICES`
  vars.12) ve ufuk setini (`PERF_BUDGET_COARSE_HORIZONS` vars.[30,120])
  kırpar; tek başına gerçek CPU süresini ölçmek testte mümkün olmadığından
  rüzgâr ucu `result["compute_ms"]` değeri telemetriye beslenir. Uyarı
  yalnızca iç→dış kenarında (`_previous_breached` histerezisi) bir kez.
- **Kanıt:** 6×2000ms → `within_budget` True; 5×20000ms → `breached`
  True + `scale_down_active` True + `recommended_resolution` coarse;
  4 örnek (<min) → karar yok (None); `PERF_BUDGET_ENABLED=False` → ihlal
  ama aktif değil; coarse sarmalayıcı yalnızca iki düğmeyi değiştirir;
  alert kenarda 1 kez, süreğende tekrar yok; POST sample negatif →400;
  rüzgâr ucu `perf_budget` + telemetri satırı yazar, `FireForecast` yazmaz.
- **Kapılar:** black(121)/mypy(82)/pylint(10.00)/bandit(0) yeşil;
  pytest **541** (521 + 20 yeni).
- **Commit:** `feat(EM-060): ...` (bu dal).

### EM-061 — Sıcaklık ve nem what-if parametreleri (#61) — DONE
- **Eksik analizi:** EM-055 what-if yalnızca **rüzgâr**ı (yön/hız) bozuyordu;
  `air_temp_c`/`relative_humidity_pct` yalnızca taban değer olarak iletiliyor,
  senaryo düğmesi yoktu. Issue panelde sıcaklık/nem kaydırıcısı ve bunun
  yayılıma/riske yansımasını istiyordu.
- **Kapsam:** `src/services/whatif.py` (`_validate_wind` +sıcaklık/nem
  bekçileri, `_clamp`, `_resolve_scenario_wind`→`_resolve_scenario`
  rüzgâr+sıcaklık+nem, `_predict_request` override, `run_whatif`
  `base_inputs`/`scenario_over` + `weather` bloğu, `WHATIF_MODEL_NAME`
  `whatif_v2`), `src/routes/whatif.py` (`WhatIfRequest` iki opsiyonel alan
  `temperature_delta_c`/`humidity_delta_pct`), `operator_map.html` **What-If —
  Hava Senaryosu** sıcaklık/nem kaydırıcıları + `runWhatif()` delta okuma +
  **Sıfırla** + özet "Sıcaklık / Nem" satırı, `tests/unit/test_whatif_weather.py`
  (13 test), CHANGELOG + docs/api.
- **Varsayım (fiziksel bağlantı):** Rothermel motoru sıcaklık/nemi **denge (ölü)
  yakıt nemi** üzerinden tüketir ve bu yalnızca `fuel_moisture_pct`
  **sabitlenmediğinde** aktiftir (spread.py). Dolayısıyla sıcaklık/nem deltaları
  yayılıma ancak çağıran `fuel_moisture` vermediğinde yansır; EM-055 testleri
  `fuel_moisture` sabitlediği için davranışı değişmez. Daha sıcak/kuru → yakıt
  kurur → yayılım hızlanır (alan/talep/açık artar); daha soğuk/nemli → yavaşlar.
- **Kanıt:** delta `0`/düğme yok → senaryo == orijinal (sıfırlama sözleşmesi);
  +15°C/-20% → air_temp≈40/rh≈20, alan+talep+açık artar; −10°C/+20% → azalır;
  senaryo nemi [1,100]'e, sıcaklığı [-30,60]'a kırpılır; ± sınır aşımı →
  `WhatIfError`(→400); uç `weather` bloğu + EM-060 `perf_budget` döndürür;
  UI `whatif-temp`/`whatif-humidity` gömülü.
- **Kapılar:** black(122)/mypy(82)/pylint(10.00)/bandit(0) yeşil;
  pytest **554** (541 + 13 yeni).
- **Commit:** `feat(EM-061): ...` (bu dal).

### EM-033 — Zamana bağlı kapasite modeli, yoldaki kaynakların varışı (#33) — DONE
- **Eksik analizi:** `effective_capacity` (EM-028) yalnızca `available` sayan
  **anlık** bir yığındı; `en_route` birimin **varış zamanı** diye bir kavramı
  yoktu (`SuppressionResource`'ta ETA kolonu yok). EM-030 çizelgesi kapasiteyi
  ufuk boyunca **sabit** tutuyordu. Issue "kapasite(t) her kaynağın tahmini
  varışından itibaren devreye girer + risk eşiği bunu yansıtır" istiyordu.
- **Kapsam:** `src/models/inventory.py` (`arrival_eta` DateTime, V018
  migration, `as_dict`), `src/services/capacity.py` (`enroute_arrival_minutes`,
  `capacity_at_minute`, `capacity_schedule`), `src/services/risk_index.py`
  (`capacity_gap_timeline` her ufku o dakikadaki kapasiteyle fiyatlar +
  `capacity_schedule` bloğu), `src/config/settings.py` + `.env.example`
  (`TIME_DEPENDENT_CAPACITY`), `src/routes/capacity.py`
  (`GET /api/v1/capacity/schedule`), `src/services/inventory.py` +
  `src/routes/inventory.py` (create/update `arrival_minutes`),
  `risk_panel.html` (**basamaklı** kapasite çizgisi) + `inventory.html`
  (**Varış ETA (dk)** alanı), `tests/unit/test_time_dependent_capacity.py`
  (13 test), CHANGELOG + docs/api.
- **Varsayım (EM-031 korunumu):** yalnızca **ETA'sı olan** `en_route` birim
  gelecekteki ufuklarda kapasiteye eklenir; ETA'sız yoldaki birim hiçbir ufka
  katkı vermez → mevcut `en_route`→0 kapasite testleri (test_capacity) ve
  `available`-only `effective_capacity`/`compute_risk_index` **değişmez**. Geçmiş
  ETA "şimdi"ye kırpılır. Çizelge haricinde anlık görünüm sabit kalır.
- **Kanıt (≥3 zaman senaryosu):** T+75 varış → T+30/60 taban, T+120 taban+12
  (basamak); ilk kritik aşım pekiştirmesiz ~T+67 iken pekiştirmeli **None**
  (ertelenir); `TIME_DEPENDENT_CAPACITY=False` → tüm ufuklar sabit +
  `capacity_schedule` yok; ETA'sız yoldaki → `[]`; CRUD `arrival_minutes=45`
  → `arrival_eta` ISO, negatif → `InventoryError`; uç 200; panel/inventory
  gömülü.
- **Kapılar:** black(123)/mypy(82)/pylint(10.00)/bandit(0) yeşil;
  pytest **567** (554 + 13 yeni).
- **Commit:** `feat(EM-033): ...` (bu dal).

### EM-057 — Gerçek zamanlı otomatik yeniden hesaplama (#57) — DONE
- **Eksik analizi:** EM-018 `spread_trigger` rüzgâr/nem/sıcaklık değişimini
  tespit edip yayılımı yeniden hesaplıyordu AMA (1) **yangın konumu** ve
  **kapasite** değişimine bakmıyordu, (2) otomatik tarama canlı beslemeye hiç
  kayıt yazmıyordu → operatör "plan güncellendi, ne değişti?" özeti görmüyordu
  (yalnızca elle `/spread/predict` ucu besleme yazıyordu). E6 Must (sp5).
- **Kapsam:** `src/services/auto_recompute.py` (`current_plan_state`,
  `changed_factors`, `evaluate_recompute`, `run_recompute`,
  `auto_recompute_sweep`, `haversine_km`), `src/config/settings.py` +
  `.env.example` (`AUTO_RECOMPUTE_ENABLED/INTERVAL_MINUTES/POSITION_MOVE_KM/
  CAPACITY_CHANGE_PCT`), `src/tasks.py` (Celery beat `auto_recompute_plans`),
  `src/routes/spread.py` (`GET /recompute-status`, `POST /recompute-sweep`),
  `operator_map.html` (`flashLive` → `plan_update` başlık + değişen faktör
  etiketleri + tepe risk bandı), `tests/unit/test_auto_recompute.py` (16 test),
  CHANGELOG + docs/api.
- **Varsayım (feed-as-state, EM-032 deseni):** son planın sürücü-durum anlık
  görüntüsü yeni tablo/migration yerine append-only canlı beslemeye
  (`kind=forecast`, `source=auto_recompute`) yazılır ve geri okunur → Celery/API
  süreçleri ayrışır. Eşikler: rüzgâr/nem/sıcaklık EM-018'den; konum haversine
  ≥1 km; kapasite bağıl ≥%10. Debounce EM-018 penceresi (anti-flap). Yeniden
  hesaplama EM-018 `run_spread_forecast` + EM-029 `compute_risk_index`'i çağırır;
  **mevcut EM-018/028/029 servisleri değişmez**.
- **Kanıt:** snapshot yok → `new_plan` (run); run sonrası anında → `debouncing`;
  debounce geçip değişim yok → `stable`; +1 ekip (2→4 ha/s, +%100) → `capacity`;
  0.05° kuzey (~5.5 km) → `position`; run → 3 `FireForecast` + 1 `forecast`
  besleme kaydı (title "Plan güncellendi", message "Değişen", payload
  `plan_update`); sweep `AUTO_RECOMPUTE_ENABLED=False` → 0; endpoint 200/404.
- **Kapılar:** black(125)/mypy(83)/pylint(10.00)/bandit(0) yeşil;
  pytest **583** (567 + 16 yeni).
- **Commit:** `feat(EM-057): ...` (bu dal).

### EM-059 — Senaryo kaydetme ve paylaşma (#59) — DONE
- **Eksik analizi:** EM-055/056/061/057 what-if yeniden hesaplamaları kasıtlı
  olarak **geçici** (`persistence: "none"`). Umut verici bir koşu adlandırılamıyor,
  vardiya devrinde geri getirilemiyor ve ekiple bağlantı üzerinden
  paylaşılamıyordu. `ScenarioRun` (models/synthetic.py) **sentetik veri üretimi**
  (EM-104) içindi, what-if kalıcılığı için değil → gerçek boşluk. E6 Should (sp3).
- **Kapsam:** `src/models/scenario.py` (`WhatIfScenario`, `whatif_scenarios`,
  V019 migration), `src/services/scenario_share.py` (CRUD + token yaşam döngüsü),
  `src/routes/scenario_share.py` (9 uç, `fastapi_app`'e kaydedildi),
  `operator_map.html` (what-if panelinde **Senaryolar — Kaydet / Paylaş** araç
  çubuğu: `saveScenario`/`loadScenario`/`shareScenario`/`refreshScenarioList`),
  `tests/unit/test_scenario_share.py` (20 test), CHANGELOG + docs/api.
- **Varsayım (yalnızca girdi):** senaryo **sonuç** değil yalnızca **girdi**
  (`kind` + `params_json`) saklar; sonuç her zaman mevcut `/whatif/wind` /
  `/whatif/capacity` ucundan **yeniden oynatılır** → fizik çoğaltılmaz, bayat
  sonuç olmaz. Paylaşım opak token (`secrets.token_urlsafe(16)`) +
  `/by-token/<token>`; yeniden-share tokenı **döndürmez** (stabil).
- **Kanıt:** wind enlem+boylam ister (yok→`ScenarioError`/400), capacity dolu
  `added_resources` ister; isim boş/>120 red; list kind/event filtresi; share →
  `share_path` biter tokenla, by-token geri getirir, disable → by-token 404;
  delete True/False; uçlar 200/400/404; UI `whatif-scen-save` +
  `/api/v1/whatif/scenarios` gömülü.
- **Kapılar:** black(129)/mypy(86)/pylint(10.00)/bandit(0) yeşil;
  pytest **603** (583 + 20 yeni; V019 migration `test_spatial` yeşil).
- **Commit:** `feat(EM-059): ...` (bu dal).

### EM-062 — What-if geçmişi ve geri alma (#62) — DONE
- **Eksik analizi:** EM-059 **adlandırılmış/kalıcı** senaryoları saklar; AMA
  operatörün **otomatik**, kendiliğinden budalanan "ne denedim?" geçmişi yoktu.
  Kabul kriterleri: son 10 koşu listelenir + tek tıkla geri dönülür + oturum
  boyunca saklanır. Geçici koşular (EM-055/061) hiçbir yerde birikmiyordu.
  E6 Could (sp3).
- **Kapsam:** `src/models/scenario.py` (`WhatIfHistory`, `whatif_history`,
  V020 migration), `src/services/whatif_history.py` (`record_history`,
  `list_history`, `get_history`, `clear_history`), `src/routes/whatif_history.py`
  (5 uç, `fastapi_app`'e kaydedildi), `src/config/settings.py` +
  `.env.example` (`WHATIF_HISTORY_ENABLED/LIMIT`), `operator_map.html`
  (**Geçmiş — son koşular** aracı: koşu sonrası otomatik `recordWhatifHistory`,
  `revertHistory` tek tık, `clearHistory`), `tests/unit/test_whatif_history.py`
  (12 test), CHANGELOG + docs/api.
- **Varsayım (EM-059'dan ayrım):** geçmiş **otomatik** + sınırlı (son N) ve
  adlandırılmamış; yalnızca **girdi** saklar, geri alma `/whatif/wind`'den
  **yeniden oynatır** (sonuç önbelleği yok). En yeniyle birebir aynı girdi
  tekrar kaydedilmez (istemci + sunucu debounce). Budama: yeni kayıt sonrası
  `id` azalan sırayla son `limit` dışındakiler silinir.
- **Kanıt:** 12 koşu limit=3 → son 3 kalır [11,10,9]; disabled → `recorded:false
  reason:disabled`; duplicate → `reason:duplicate`; get(missing) → HistoryError;
  clear event-scoped + tümü; uçlar config/list/record/get(404)/delete; UI
  `whatif-hist-revert` + `recordWhatifHistory(body` + `/api/v1/whatif/history`.
- **Kapılar:** black(132)/mypy(88)/pylint(10.00)/bandit(0) yeşil;
  pytest **615** (603 + 12 yeni; V020 migration `test_spatial` yeşil).
- **Commit:** `feat(EM-062): ...` (bu dal).

### EM-047 — Öneri kabul/ret/düzenleme (#47) — DONE
- **Eksik analizi:** EM-052 (`positioning.build_proposals`) önerileri **canlı**
  üretiyor AMA operatörün bu öneri üzerinde verdiği **karar** hiçbir yerde
  saklanmıyordu; `accept/reject/decision/feedback` için model/servis/route yoktu
  (grep boş). Kabul kriterleri: üç aksiyon + kabul kaynağı "yolda" yapar +
  ret gerekçesi isteğe bağlı + her karar denetim kaydına yazılır. E5 Must (sp5).
- **Kapsam:** `src/models/recommendation.py` (`RecommendationDecision`,
  `recommendation_decisions`, V021 migration; `models/__init__`'e kaydedildi),
  `src/services/recommendation_decision.py` (`record_decision`, `list_decisions`,
  `get_decision`), `src/routes/recommendation_decision.py` (4 uç, `fastapi_app`'e
  kaydedildi), `src/services/positioning.py` (deployment_point özelliklerine
  `resource_key`/`event_key` eklendi — UI karar verebilsin), `operator_map.html`
  (öneri satırında **Kabul/Düzenle/Reddet** + `decideProposal` + karar sonrası
  `loadLayer` yenileme), `tests/unit/test_recommendation_decision.py` (12 test),
  CHANGELOG + docs/api.
- **Varsayımlar:** (1) `edit` = kabul + operatör değişiklikleri (`arrival_minutes`
  envanter üzerinden `arrival_eta`'ya planlanır); (2) kabul/düzenle kaynağı
  `en_route`'a çeker — durum geçişi `inventory.update_resource` yeniden
  kullanılarak sözlük/ETA doğrulaması tek yerde kalır; (3) E10 auth kapsam dışı,
  `decided_by` serbest metin; denetim **kaydı** (immutable satır) burada tutulur;
  (4) öneri saklanmaz — karar anındaki girdiler denetim kaydının `detail_json`
  anlık görüntüsüne yazılır.
- **Kanıt:** accept → `en_route` + `status_changed:true`; edit(arrival=30) →
  `en_route` + `arrival_eta` dolu + detail 30; reject → durum değişmez + reason
  opsiyonel (ikisi de denetlenir); invalid action → DecisionError; unknown
  resource → DecisionError; get(missing) → DecisionError; uçlar config/record
  (200/404/400)/list/get(404); UI `db-accept`/`db-reject`/`decideProposal`.
- **Kapılar:** black(136 değişmez)/mypy(91)/pylint(10.00)/bandit(0) yeşil;
  pytest **627** (615 + 12 yeni; V021 migration `test_spatial` yeşil).
- **Commit:** `feat(EM-047): ...` (bu dal).

### EM-046 — Öneri gerekçesi / açıklanabilirlik (#46) — DONE
- **Eksik analizi:** EM-052 `build_proposals` önerileri sıralıyor AMA **neden**
  sıralandığını ve **hangi alternatiflerin elendiğini** hiçbir yerden
  açıklamıyordu; `explain`/`rationale`/`why` için servis/route yoktu. Kabul
  kriterleri: her öneri için "neden?" paneli (tahmin/eşik/alternatifler) +
  reddedilen alternatifler ve nedenleri görülebilir. E5 Must (sp5).
- **Kapsam:** `src/services/recommendation_explain.py` (`explain_proposals`),
  `src/routes/recommendation_explain.py` (2 uç, `fastapi_app`'e kaydedildi),
  `operator_map.html` (öneri satırında **Neden?** düğmesi + `explainProposal`
  satır-altı açılır panel), `tests/unit/test_recommendation_explain.py` (11 test),
  CHANGELOG + docs/api. **Migration/model/settings yok** — canlı hesaplanır.
- **Varsayımlar:** (1) yeniden sıralama yok; `build_proposals` (limit=_ALL) ile
  **tam** sıralama alınıp `POSITIONING_MAX_PROPOSALS` (veya `limit`) ile
  selected/rejected bölünür — gerekçe haritadaki sayılarla çelişmez; (2) "hangi
  tahmin" = kapanış-duyarlı rota ETA'sı; "hangi eşik" = top-N seçimi +
  `threshold_eta_minutes` (en yavaş seçilenin ETA'sı); (3) reddedilen gerekçesi:
  ulaşılamayan → "izole/kopuk", eşikten uzun ETA → "daha uzun tahmini varış".
- **Kanıt:** limit=1 → 1 öneri `rank:1` + `why` ("En kısa tahmini varış"),
  reddedilenler `slow`="Daha uzun tahmini varış" + `island`="ulaşılamıyor";
  context `alternatives_evaluated:3`, `threshold_eta`==önerilenin ETA'sı; limit=10
  → reddedilen boş; bilinmeyen olay → PositioningError; boş ağ → RoadNetworkError;
  uçlar 200/404/422/config; UI `db-why`/`explainProposal`.
- **Kapılar:** black(139 değişmez)/mypy(93)/pylint(10.00)/bandit(0) yeşil;
  pytest **638** (627 + 11 yeni).
- **Commit:** `feat(EM-046): ...` (bu dal).

### EM-049 — Kaynak tipine göre ETA — kuş uçuşu vs yol ağı (#49) — DONE
- **Eksik analizi:** EM-052 `build_proposals` **tüm** kaynakları (ekip,
helikopter, İHA) yol ağı grafiğinden routing yapıyordu; kaynak **tipine göre**
seyahat modu (hava = kuş uçuşu, kara = yol ağı) hiç yoktu (`air_speed`/`flight`/
`travel_mode` araması boş). Kabul kriterleri: ETA tipe göre hız+rota ile
hesaplanır; önerilerde görünür. E5 Must (sp5).
- **Kapsam:** `src/services/positioning.py` (hava/kara dalı + `travel_mode`),
  `src/config/settings.py` + `.env.example` (`POSITIONING_AIR_SPEED_KMH`),
  `operator_map.html` (**Hava/Kara** rozeti + açılır pencere mod etiketi + CSS),
  `tests/unit/test_positioning_travel_mode.py` (9 test), CHANGELOG + docs/api.
  **Migration/model/route yok** — mevcut `/proposals` ucu genişletilir.
- **Varsayımlar:** (1) hava kaynağı = `resource_type ∈ {helicopter, uav}`;
  crew_bases (kara ekibi) daima `road`; (2) hava ETA'sı = `haversine_km/air_speed*60`,
  kapatmalar uçuşu etkilemez → `reachable=true`, `delay=0`, iki noktalı düz rota;
  (3) boş yol ağı hâlâ `RoadNetworkError` (pilot bölgesinde ağ varsayılır);
  (4) "kaynak listesinde ETA" = envanter `arrival_eta` (EM-033) zaten mevcut.
- **Kanıt:** ekip→`travel_mode:road`; heli→`air`, `distance_km`==haversine,
  `eta==round(km/220*60,2)`, rota 2 nokta; ada helikopteri ulaşılabilir + ada
  ekibi ulaşılamaz (hava öne sıralanır); kapatma hava ETA'sını değiştmez;
  110↔440 km/sa hız-ETA ters orantısı; layer/özellik `travel_mode`; uç
  `travel_mode` döner; UI `mode-air`/`mode-road`/`travel_mode`.
- **Kapılar:** black(140 değişmez)/mypy(93)/pylint(10.00)/bandit(0) yeşil;
  pytest **647** (638 + 9 yeni).
- **Commit:** `feat(EM-049): ...` (bu dal).

### EM-048 — Önerinin etki karşılaştırması (#48) — DONE
- **Eksik analizi:** EM-046/047 öneriyi açıklıyor ve karar verdiriyor AMA
  "öneri **uygulanırsa** vs **uygulanmazsa**" riskin nasıl değiştiğini yan yana
  gösteren hiçbir şey yoktu (`impact`/`compare`/`applied` araması boş). Komutan
  kararın değerini görsün ister. E5 Must (sp3).
- **Kapsam:** `src/services/recommendation_impact.py` (`compare_impact`),
  `src/routes/recommendation_impact.py` (2 uç, `fastapi_app`'e kaydedildi),
  `operator_map.html` (Konuşlanma panelinde **Etki karşılaştırması** düğmesi +
  `loadImpactComparison`/`renderImpact` + tablo CSS),
  `tests/unit/test_recommendation_impact.py` (12 test), CHANGELOG + docs/api.
  **Migration/model/settings yok** — EM-056 + EM-029 motorları yeniden kullanılır.
- **Varsayımlar:** (1) **talip sabit**, yalnızca bu olaya ayrılan EM-028 kapasite
  değişir; uygulanırsa=tam etkin kapasite, uygulanmazsa=etkin − önerilen
  ulaşılabilir kaynakların ha/saat toplamı; (2) yalnızca `kind==
  suppression_resource` önerileri ayrılan sayılır (crew_bases zaten kapasiteye
  girmez); (3) canlı/tavsiye — hiçbir kaynak rezerve edilmez; (4) karşılaştırılacak
  yayılım tahmini yoksa `ImpactError`→409.
- **Kanıt:** 2 müsait ekip (biri ulaşılabilir, biri ada/kopuk) → applied 4.0,
  committed 2.0, not_applied 2.0; side_by_side 3 ufuk, tüm `risk_index_delta<=0`
  ve en az biri <0, `decision_has_value` True; öneri yoksa committed 0 → delta 0 →
  False; bilinmeyen olay→PositioningError; boş ağ→RoadNetworkError; tahmin yoksa
  ImpactError; uçlar 200/404/422/config; UI `loadImpactComparison`/`positioning-impact`.
- **Kapılar:** black(143 değişmez)/mypy(95)/pylint(10.00)/bandit(0) yeşil;
  pytest **659** (647 + 12 yeni).
- **Commit:** `feat(EM-048): ...` (bu dal).

### EM-053 — Çifte atama ve kaynak çakışma önleme (#53) — DONE
- **Eksik analizi:** EM-047 `record_decision` kabul/düzenle'de kaynağı koşulsuz
  `en_route`'a çekiyordu; **aynı birimin ikinci bir olaya atanmasını engelleyen**
  bir bekçi ve **görev bitişi kaynağı müsaite döndüren** bir mekanizma yoktu
  (`conflict`/`release`/`assignment` araması boş). Kabul kriterleri: tek görev
  ataması + çakışmada açıklamalı uyarı + görev bitince otomatik müsait. E5 Should (sp3).
- **Kapsam:** `src/services/recommendation_decision.py` (`ConflictError`,
  `_BUSY_STATUSES`, `_active_assignment_event`, `record_decision` içine çakışma
  bekçisi, `release_assignment`, `list_active_assignments`,
  `release_completed_assignments`), `src/routes/recommendation_decision.py`
  (4 yeni uç + `…/config` `conflict_prevention` bloğu; `DecisionRecord` 409),
  `operator_map.html` (**Atamalar** bölümü: `toggleAssignments`/`loadAssignments`/
  `releaseAssignment`/`releaseCompleted` + tablo + CSS),
  `tests/unit/test_recommendation_conflict.py` (16 test), CHANGELOG + docs/api.
  **Migration/model/settings/route-kaydı yok** — mevcut EM-047 tablosu/servisi genişletilir.
- **Varsayımlar:** (1) atama **ayrı tablo değil**, EM-047 denetim kaydından türer:
  en yeni karar `accept`/`edit` ve kaynak hâlâ meşgulse (`en_route`/`deployed`)
  o olaya bağlı; sonraki `release` bağı temizler; (2) `release` yeni bir
  `DECISION_ACTIONS` **değildir** (EM-047 `actions` üçlüsü ve config testi
  korunur) — ayrı `release_assignment` fonksiyonu `release` satırı yazar;
  (3) çakışma yalnızca `event_key` verilip mevcut atama **farklıysa** tetiklenir
  (geriye dönük uyum: `event_key`'siz kabuller eskisi gibi serbest);
  (4) "görev bitti" = olay `status != "active"` ya da satırı yok.
- **Kanıt:** RES EVT-A'ya kabul → EVT-B'ye kabul `ConflictError` (uç 409);
  aynı EVT-A tekrar → idempotent; release → `available` + ETA temiz + sonra
  EVT-B'ye kabul OK; boş kaynakta release no-op; yanlış `event_key` release →
  ConflictError; `list_active_assignments` 1 satır; sweep: aktif olay bağlı
  kalır, contained/silinen olayın birimi otomatik `available`; uçlar
  release(200/404)/assignments(200)/release-completed(200)/config; UI
  `toggleAssignments`/`db-release`/`Müsaite al`.
- **Kapılar:** black(144 değişmez)/mypy(95)/pylint(10.00)/bandit(0) yeşil;
  pytest **675** (659 + 16 yeni).
- **Commit:** `feat(EM-053): ...` (bu dal).

### EM-051 — Kabul edilen öneriden saha görev kartı (#51)

- **Kapsam:** `src/services/task_instruction.py` (`generate_task_cards`),
  `src/routes/task_instruction.py` (`task-cards` + `…/config`),
  `fastapi_app.py` route kaydı, `operator_map.html` (**Görev kartları**
  bölümü: `toggleTaskCards`/`loadTaskCards`/`renderTaskCard` +
  `refreshTaskCards` karar sonrası otomatik tazeleme),
  `tests/unit/test_task_instruction.py` (15 test), CHANGELOG + docs/api.
  **Migration/model/settings/route sayısı yok** — mevcut EM-047 denetim
  tablosu okunur, yeni kalıcılık yoktur.
- **Varsayımlar:** (1) kabul edilen birim `en_route` olup canlı EM-052
  öneri listesinden düştüğü için kart **denetim anlık görüntüsünden**
  (detail_json) yeniden kurulur; (2) aynı (kaynak, olay) için **en yeni**
  `accept`/`edit` esas alınır (`release` kart üretmez — EM-053 ile tutarlı);
  (3) hedef olay silinmişse kart atlanır, kaynak silinmişse snapshot
  alanlarına düşülür; (4) risk notu ölçülebilir talep yoksa (`peak_risk_index`
  null) taşınmaz.
- **Kanıt:** kabul → kart hedef/koordinat/ETA/risk `kritik` alanlarıyla dolu;
  ret kart yok; edit `arrival_minutes`'a düşer; bilinmeyen olay
  `TaskInstructionError` (uç 404); olay filtresi + filtresiz tüm liste;
  yeniden kabulde en yeni snapshot; `en_route`'dayken de üretilir; travel_mode
  + arrival_eta taşınır; silinen kaynak snapshot'a düşer; silinen olay kart
  üretmez; uçlar task-cards(200/404)/config; UI bağlantısı.
- **Kapılar:** black(147 değişmez)/mypy(97)/pylint(10.00)/bandit(0) yeşil;
  pytest **690** (675 + 15 yeni).
- **Commit:** `feat(EM-051): ...` (bu dal).

### EM-050 — Kısıt tabanlı optimizasyon (#50)

- **Kapsam:** `scripts/migration/V022__resource_constraint_limits.sql`
  (suppression_resources + crew_bases: `range_km`/`shift_minutes`/
  `night_capable`, yalnızca ADD), `src/models/inventory.py` +
  `src/models/road_network.py` (opsiyonel kolonlar + as_dict),
  `src/services/positioning.py` (`_assess_constraints`, `_reject_summary`,
  `build_proposals` yeni `now_utc`/`rejected_out` parametreleri — ek parametre,
  mevcut imzalar bozulmadı), `src/routes/positioning.py` (`rejected` alanları +
  `…/constraints` ucu), `src/routes/inventory.py` + `src/services/inventory.py`
  (CRUD doğrulama), `operator_map.html` (**Kısıt nedeniyle elenen öneriler**:
  `loadRejectedProposals`), `inventory.html` (Menzil/Mesai/Gece alanları),
  `settings.py` + `.env.example` (`POSITIONING_NIGHT_BAN_ENABLED`),
  `tests/unit/test_constraint_positioning.py` (12 test), CHANGELOG + docs/api.
- **Varsayımlar:** (1) NULL limit = "bilinmiyor/sınırsız" → hiç elenme yok
  (geriye dönük uyum); (2) **elenen toplayıcısı verilmeyen çağrılar EM-046/
  katman sözleşmesini bozmaz**: sıralama aynı kalır, ihlal
  `constraint_violations`/`constraint_reason` ile işaretlenir; (3) gece
  penceresi UTC 20-05 (pilot bölge yerel saatine yakın yaklaşık), varış anı
  `now_utc + ETA` ile test edilir ve `now_utc` test için enjekte edilebilir;
  (4) kaynak sayısı kısıtı = mevcut `POSITIONING_MAX_PROPOSALS`; yol
  kapalılığı rotada zaten uygulanıyordu, artık ayrıca `road_closure` olarak
  raporlanır; (5) `test_positioning.py` yardımcıları yeniden kullanılır.
- **Kanıt:** saf değerlendirme: menzil+mesai+gece birlikte, NULLsuz hiç
  elenmez, yasak kapalı/gündüz geçer; filtre modu: `far`(menzil) ve
  `island`(yol kapalılığı) öneri listesine girmez, elenenlerde kısıt
  adları+gerekçe; mesai ve gece (varış bazlı, gündüz aynı limit geçer) +
  toplayıcısız mod: ada en sonda kalır, `constraint_violations` işaretli,
  `fast` tertemiz; uç: proposals `rejected`/`rejected_count` 2, constraints
  config, 404 korundu; envanter: create 40/90/False → kalıcı, update, negatif
  menzil 400; UI + envanter formu bağlantıları.
- **Kapılar:** black(148 değişmez)/mypy(97)/pylint(10.00)/bandit(0) yeşil;
  pytest **702** (690 + 12 yeni).
- **Commit:** `feat(EM-050): ...` (bu dal).

### EM-045 — Kaynak önerisi motoru: öneri başına beklenen risk düşüşü (#45)

- **Kapsam:** `src/services/recommendation_engine.py` (`marginal_risk_reduction`
  saf marjinal matematik + `enrich_proposals` yerinde etiketleme),
  `src/routes/positioning.py` (proposals ucu `enrich_proposals` çağrısı +
  `value_metric` alanı), `tests/unit/test_recommendation_engine.py` (8 test),
  CHANGELOG + docs/api. Yeni tablo/migration/settings yok.
- **Varsayımlar:** (1) metrik = bu tek birimin olaya tahsis edilmesi ile
  rezervde tutulması arasındaki **tepe risk indeksi** farkı (talep sabit,
  kapasite tek birim kadar artar); (2) **varış-duyarlı**: birim yalnızca
  `ETA ≤ ufuk` olan ufkta kapasiteye sayılır, o an yetişemiyorsa o tepe
  dakikada katkı 0; (3) `build_proposals` **saf** kalır — zenginleştirme
  yalnızca proposals ucunda ek katman, EM-046/048/050/052 sıralama
  sözleşmesine dokunmaz; (4) ölçülemez durumlar (taban kapasite ≤ 0, birim
  kapasitesi ≤ 0, tahmin yok, ekip üssü, ulaşılamayan) `None`; (5) kayıt
  yok/canlı/danışmanlık; (6) `test_recommendation_impact.py` yardımcıları
  yeniden kullanılır (crew 2.0 ha/s → bilinen 1.0 düşüş).
- **Kanıt:** saf: hızlı birim 0.75, tepe-ufuk seçimi 1.0, yavaş birim 0.0,
  ölçülemez 4 durum `None`; zenginleştirme: `crew_near` 1.0, ulaşılamayan
  `crew_island` `None`, ekip üssü `None`, bilinmeyen olay `RiskIndexError`;
  uç: `value_metric.field=expected_risk_reduction` + atıf, `crew_near` 1.0,
  eleme modunda ada listeden düşer.
- **Kapılar:** black(150 değişmez)/mypy(98)/pylint(10.00)/bandit(0) yeşil;
  pytest **710** (702 + 8 yeni).
- **Commit:** `feat(EM-045): ...` (bu dal).

### EM-054 — Öneri kabul/ret geri bildirim döngüsü — analiz (#54) — DONE
- **Eksik analizi:** EM-047 kararları (kabul/ret/düzenleme) denetim tablosuna
  yazılıyor ama **hiçbir yerden toplulaştırılmıyordu**; operatörün ret
  sinyali motoru iyileştirecek bir rapora/fikre dönüşmüyordu (`feedback`/
  `accept_rate`/`reject_rate` araması boş). Kabul kriterleri: kabul/ret
  oranları + tip bazında kırılım + en çok reddedilenler + gerekçeler +
  iyileştirme fikirleri. E5 Could (sp3).
- **Kapsam:** `src/services/recommendation_feedback.py` (`feedback_summary`
  + sezgi/sabitler), `src/routes/recommendation_feedback.py` (2 uç,
  `fastapi_app`'e kaydedildi), `operator_map.html` (**Kabul/ret geri bildirimi**
  düğmesi + `toggleFeedback`/`refreshFeedback`/`renderFeedback`, karar sonrası
  otomatik tazeleme), `tests/unit/test_recommendation_feedback.py` (10 test),
  CHANGELOG + docs/api. **Migration/model/settings yok** — EM-047 denetiminden
  salt okunur türetilir.
- **Varsayımlar:** (1) `release` satırları (EM-053 yaşam döngüsü) karardan
  sayılmaz (`DECISION_ACTIONS` filtresi); (2) kaynak tipi önce karar anlık
  görüntüsünden, yoksa envanterden çözülür (fallback `bilinmeyen`); (3) oran
  paydası ilgili tipin **toplam kararı**; (4) fikirler eşik sezgileriyle
  (ret oranı ≥ %50, genel kabul < %50) + gerekçe anahtar kelimelerinden üretilir.
- **Kanıt:** karar yok → oranlar `None` + "operatör kararı yok" fikri; 2 kabul/3
  ret/1 düzen → `accept_rate 0.333`/`reject 0.5`/`edit 0.167`; `release` hariç
  (2 sayılıyor); crew 3/3 → `reject_rate 1.0` + `most_rejected_types[0]=crew`;
  gerekçeler `yavaş`=2/`uzak`=1 → ETA+Mesafe fikirleri; tipi eksik karar →
  envanter `helicopter`; `event_key` kapsam filtresi; uç 200 totals + config
  (`excludes:['release']`).
- **Kapılar:** black(153 değişmez)/mypy(100)/pylint(10.00)/bandit(0) yeşil;
  pytest **720** (710 + 10 yeni).
- **Commit:** `feat(EM-054): ...` (bu dal).

### EM-063 — Saat dilimi, birim ve koordinat standardizasyonu (#63) — DONE
- **Eksik analizi:** `timeutils` yalnızca UTC saklama/serileştirme sağlıyordu;
  **sunum katmanı** hiç yoktu — UTC→yerel saat (TRT/EET), rüzgâr yönünü pusula
  etiketine çevirme, koordinatı ayarlanabilir formatta (decimal/DMS) gösterme ve
  tek bir metrik birim tanımı (`compass`/`DMS`/`Europe/Istanbul`/`resolve_zone`
  aramaları boş; `spread.py`'deki `_compass_vector` iç matematikti, sunum değil).
  E7 Should/Must (sp2).
- **Kapsam:** `src/services/localization.py` (`to_local_time`, `format_wind_direction`,
  `format_coordinates`, `format_metric`, `standardize`, `resolve_zone`,
  `LocalizationError`), `src/routes/localization.py` (GET /display/config + POST
  /display/standardize, `fastapi_app`'e kaydedildi), `src/config/settings.py` +
  `.env.example` (`DISPLAY_TIMEZONE` / `DISPLAY_COORDINATE_FORMAT`),
  `operator_map.html` (**Görüntü standardizasyonu** paneli: saat dilimi/koordinat
  seçici + canlı çıktı), `tests/unit/test_localization.py` (19), CHANGELOG + docs/api.
  **Migration/model/tablo yok** — durum dönüşümü, kalıcılık yok.
- **Varsayımlar:** (1) zaman daima UTC; `Europe/Istanbul`/`Europe/Athens`/`UTC`
  varsayılan, herhangi geçerli IANA bölgesi kabul (geçersiz → `LocalizationError`
  → 422); (2) birimler **sabit metrik** (km/ha/km-sa); (3) koordinat hem decimal
  hem DMS döner, `display` seçileni taşır; (4) her blok yalnız girdisi verilmişse
  üretilir (tek istek saat+koordinat+rüzgâr+birimi birlikte).
- **Kanıt:** `2026-07-01T12:00:00Z` +3 → `15:00:00+03:00`/`+0300`; 90°→E, 0/360→N,
  225→SW; 38.42/27.14 decimal `38.420000, 27.140000` + DMS `38°25'...N`; geçersiz
  bölge/çift-eksik/format/menzil-dışı → 422; uç config + standardize + UI wiring.
- **Kapılar:** black(156 değişmez)/mypy(102)/pylint(10.00)/bandit(0) yeşil;
  pytest **739** (720 + 19 yeni).
- **Commit:** `feat(EM-063): ...` (bu dal).

### EM-064 — Ülke bazlı ayrış envanter / kapasite (#64) — DONE
- **Eksik analizi:** `SuppressionResource.country` kolonu **zaten mevcut**
  (model + `as_dict` + envanter listeleme filtresi). Gerçek boşluk: kapasite
  hesabı (`effective_capacity`) yalnızca **tip bazında** toplayıp ülkeyi
  yok sayıyordu; ülke ayrı bir hesap yoktu → sınır ötesi operasyonda iki
  ülke sessizce birleştirilebilirdi. Kabul kriterleri: her kaynak bir ülkeye
  ait + kapasite ülke ayrı toplanır/gösterilir; hiçbir ekran iki ülkeyi
  sessizce birleştirmez. E7 Must (sp5).
- **Kapsam:** `src/services/capacity.py` (`UNASSIGNED_COUNTRY`,
  `_counts_by_country_type`, `capacity_by_country` — `(country, tip)` kovalar,
  `merged_by_default:False`, ülke toplamları küresel etkinden farklı değil),
  `src/routes/capacity.py` (`GET /api/v1/capacity/by-country`),
  `risk_panel.html` (**Kapasite — Ülke Bazında** kartı + `refreshCapacityByCountry`),
  `tests/unit/test_capacity_by_country.py` (9 test), CHANGELOG + docs/api.
  **Yeni tablo/migration yok** — `country` zaten var.
- **Kanıt:** TR/GR ayrı kalır (birbirine karışmaz); `country=None` → `atanmamış`
  kovası; sadece `available` sayılır (deployed/en_route/maintenance hariç);
  bilinmeyen tip yok sayılır; ülke toplamları `effective_capacity` toplamına
  eşit; listesi sıralı; uç 200 + `merged_by_default:False`.
- **Kapılar:** black(157 değişmez)/mypy(102)/pylint(10.00)/bandit(0) yeşil;
  pytest **748** (739 + 9 yeni).
- **Commit:** `feat(EM-064): ...` (bu dal).

### EM-065 — Dış destek ihtiyacının erken tahmini (#65) — DONE
- **Eksik analizi:** sistemde **dış destek / yardım talebi** diye hiçbir
  servis/uc yoktu (`external`/`destek`/`support_need` araması sadece veri
  kaynağı lisans metinlerini donuyordu). EM-030/033 açık zaman çizelgesi
  **ne zaman** açığın olacağını zaten veriyor ama **ulusal kapasite
  yetersiz kalacak + ≈ Y birim dış destek** önerisini ve **gecikmeden talep**
  son tarihini ureten bir katman yoktu. Kabul kriterleri: "Ulusal kapasite
  T+X dk sonra yetersiz kalacak, dış destek ≈ Y birim" önerisi; açık
  gerçekleşmeden once görünür. E7 Must (sp8).
- **Kapsam:** `src/services/external_support.py` (`forecast_external_support`
  — `capacity_gap_timeline` serisinden ilk açık dakikası/tepe açığı/tam
  takviye birimi + talep-gönderme son tarihi), `src/config/settings.py` +
  `.env.example` (`EXTERNAL_SUPPORT_UNIT_HA_PER_HOUR`, `EXTERNAL_SUPPORT_LEAD_TIME_MINUTES`),
  `src/routes/external_support.py` (2 uç) + `fastapi_app.py` kaydı,
  `risk_panel.html` (**Dış Destek Erken Tahmini** kartı + `refreshExternalSupport`),
  `tests/unit/test_external_support.py` (12 test), CHANGELOG + docs/api.
  **Yeni tablo/migration yok** — mevcut yayılım tahminlerinden canlı.
- **Varsayım (deterministik projeksiyon):** "öğrenilen model" değil; açık
  eşiği = talep > ulusal kapasite (ratio 1.0, kritik-yakin 1.2 değil);
  ulusal kapasite = müsat + ETA'sı geçen yoldaki takviye (EM-033 zaman
  çizelgesi), dolayısıyla takviyeler gelse bile açik öngörülür. Birim
  sayısı = tepe açığı / `unit_ha_per_hour` yukarı yuvarlanır.
- **Kanıt:** 2 ekip(4 ha/s) + talep 3/6/8 → ilk açık T+40 (enterpolasyon),
  tepe 4 ha/s → unit 2 ile 2 birim; yeterli kapasitede uyarı yok ("yetersiz
  yeterli"); sifır kapasite → ilk ufuk T+30; lead 10 → talep en geç T+30,
  lead 60 → "hemen"; olay/özet/mesaj; `persistence:none`; uçlar 200/404/config.
- **Kapılar:** black(160 değişmez)/mypy(104)/pylint(10.00)/bandit(0) yeşil;
  pytest **760** (748 + 12 yeni).
- **Commit:** `feat(EM-065): ...` (bu dal).

### EM-066 — Sınır ötesi ortak durum görünümü (#66) — DONE
- **Eksik analizi:** `FireEvent` ülkesiz (yalnız lat/lon); sınır ötesi **ortak
  durum ekranı** yoktu (`crossborder`/`border`/`shared_field`/`situation`
  araması sadece EM-063 saat dilimi/EM-065 docstring metinlerini donuyordu).
  Kabul kriterleri: TR+GR yetkilileri için paylaşımlı özet (yangın, risk
  seviyesi, tahmini dış destek ihtiyacı) + ülke bazlı veri paylaşım kapsamı
  ayarlanabilir. E7 Must (sp5).
- **Kapsam:** `src/services/crossborder_situation.py`
  (`crossborder_situation` — koordinat→ülke atfı + ülke bazında EM-029 risk /
  EM-065 dış destek toplama + `fire`/`risk`/`support` paylaşım kapsamı filtresi),
  `src/config/settings.py` + `.env.example` (`CROSSBORDER_BORDER_LONGITUDE`,
  `CROSSBORDER_SHARED_FIELDS`), `src/routes/crossborder.py` (2 uç) +
  `fastapi_app.py` kaydı, `risk_panel.html` (**Sınır Ötesi Durum** kartı +
  `refreshCrossborder` + kapsam kutuları), `tests/unit/test_crossborder_situation.py`
  (16 test), CHANGELOG + docs/api. **Yeni tablo/migration yok** — EM-029/EM-065
  çıktısından canlı (`persistence: none`).
- **Varsayım (pilot basitleştirme):** gerçek Ege kara/deniz sınırı yerine tek
  boylam bölünmesi (boylam ≥ sınır → TR, değilse GR; EM-063 TR-doğu/GR-batı
  çerçevesiyle tutarlı, `CROSSBORDER_BORDER_LONGITUDE` ile ayarlanır). Ülke
  bazlı **yetki** politikası (kim neyi görebilir) kapsam sürünmesini önlemek
  için EM-070'e bırakıldı; EM-066 yalnızca görünen **alan grubu kapsamını**
  ayarlar.
- **Kanıt:** 27.5→TR / 26.2→GR atfı; boylam sınırda (26.5)→TR; sınır 28.0
  yapınca 27.5 GR'ye geçer; varsayılan kapsam fire+risk+support; `fields=risk`
  sadece risk bloğu (country tepe bandı var, destek None); `fields=support`
  support bloğu (tepe None, birim int); ülke toplamı olay toplamına eşit; ülke
  tepe bandı = en kötü olay; geçersiz alan → CrossborderError; olay yok → boş;
  uçlar 200/400/config.
- **Kapılar:** black(163 değişmez)/mypy(106)/pylint(10.00)/bandit(0) yeşil;
  pytest **776** (760 + 16 yeni).
- **Commit:** `feat(EM-066): ...` (bu dal).

### EM-067 — Sınır bölgesi yangın yayılımı / sınır geçiş projeksiyonu (#67) — DONE
- **Eksik analizi:** `crossing`/`geçiş` araması sadece EM-021 engel ışın
  kesmeleri ve EM-032 eşik-aşım metinlerini donuyordu; yangının **ülke
  sınırını geçme olasılığı ve süresi**ni hesaplayan hiçbir katman yoktu.
  Kabul kriteri: "Yangının ülke sınırını geçme olasılığı ve süresi
  hesaplanır." E7 Should (sp5).
- **Kapsam:** `src/services/crossborder_spread.py` (`project_border_crossing`
  — her aktif olayın en yeni EM-015 tahmininin baş yönü/hızı ile pilota sınır
  boylamına uzaklığından olasılık + geçiş dakikası), EM-066'daki atıf
  mekanizması `border_longitude`/`country_for` **public edilerek ortakıldı**,
  `src/routes/crossborder.py` içine `GET /api/v1/crossborder/spread`,
  `risk_panel.html` (**Sınır Geçiş Projeksiyonu** kartı +
  `refreshXborderSpread`), `tests/unit/test_crossborder_spread.py` (14 test),
  CHANGELOG + docs/api. **Yeni tablo/migration/ayar yok** (`persistence: none`).
- **Varsayım (deterministik geometri):** olasılık = cos(EM-015 baş yayılım
  yönü ile sınırın yönü arasındaki açı) ∈ [0,1] (TR için 270°, GR için 90°);
  yön yoksa dairesel büyüme → pay 1.0; süresi = cos(enlem)·km/derece uzaklık /
  (ROS×pay) — mevcut ROS'un doğrusal projeksiyonu, rüzgâr değişebilir, öngörü
  penceresi içi/dışı bayraklanır. 90°'lik dik yönde kayan-nokta gürültüsü
  yuvarlanmış olasılık kapısıyla bastırılır. Merkez nokta atfı pilot
  basitleştirmesidir (poligon kenarı değil).
- **Kanıt:** 270° baş → olasılık 1.0 "yüksek" + T+ formülü elle doğrulandı;
  aksi yön (90°) → 0.0/None "aksi yönünde"; dik (0°) → gürültü payı yok;
  45°'den sapma → 0.71 "orta", süre pay ile ölçeklenir; yakın+hızlı olay
  pencere içinde; GR tarafı → hedef TR; öngörüsüz olay "belirsiz"; sınır 28.0
  → yön ters döner; özet en erken geçişi söyler; `persistence:none`; uç 200.
- **Kapılar:** black(165 değişmez)/mypy(107)/pylint(10.00)/bandit(0) yeşil;
  pytest **790** (776 + 14 yeni).
- **Commit:** `feat(EM-067): ...` (bu dal).

### EM-068 — Çok dilli arayüz (TR/EL/EN) (#68) — DONE

- **Eksik analizi:** `src/services/localization.py` (EM-063) yalnız saat/birim/
  koordinat **biçimlendirme**dir; arayüz **metni** için hiçbir i18n katmanı yok
  (`grep i18n|locale|SUPPORTED_LANGUAGES` boş), `risk_panel.html` metinleri
  HTML'e gömülü Türkçe — gerçek boşluk doğrulandı.
- **Kapsam:** `src/services/i18n.py` (mesaj kataloğu: `normalize_language`,
  `translate`, `get_messages`, `coverage`, `messages_payload`, `config_payload`),
  `src/routes/i18n.py` (`GET /api/v1/i18n/messages[?lang=]` + `/config`),
  `settings.py` + `.env.example` (`I18N_DEFAULT_LANGUAGE`), `fastapi_app.py`
  kaydı, `risk_panel.html` (dil seçici + `data-i18n` kabuk + kataloq-güdümlü
  enum'lar + `t()`/`applyLocale`/`loadLocale`), `tests/unit/test_i18n.py`
  (26 test), CHANGELOG + docs/api. **Yeni tablo/migration yok** (`persistence:
  none`).
- **Varsayımlar:** (1) kabul kriteri gereği **TR + EN tam**, **EL çekirdek
  ekranlar**; eksik EL anahtarı önce **EN** köprüsüne, sonra ham anahtara düşer;
  (2) sayı/saat/koordinat biçimlendirme EM-063'te kalır — bu görev yalnız metin
  katmanıdır; (3) operatör dili yalnız tarayıcıda (localStorage) tutulur;
  (4) backend'in ürettiği veri mesajları (Türkçe) bu oturumda kapsam dışı —
  katalog arayüz kabuğudur.
- **Kanıt:** tr-TR/el-GR/en-US indirgeme; bilinmeyen dil → I18nError; EL çekirdek
  `app.title` Yunanca, EL-olmayan `card.budget` → EN fallback; `{time}` yer
  tutucusu; TR/EN anahtar kümeleri eşit; `get_messages("el")` tam küme;
  coverage EL `native<total`, TR/EN `missing 0`; `messages_payload` varsayılanı
  ayardan okur, geçersiz varsayılan çökmez; uçlar 200/400/config.
- **Kapılar:** black(168 değişmez)/mypy(109)/pylint(10.00)/bandit(0) yeşil;
  pytest **816** (790 + 26 yeni).
- **Commit:** `feat(EM-068): ...` (bu dal).

### EM-070 — Ülke bazlı yetki ve veri paylaşım politikası (#70) — DONE

- **Eksik analizi:** EM-066 `crossborder_situation.py` + `settings.py` açıkça
  "ülke bazlı yetki politikası EM-070'e bırakıldı" diyor; `grep share_policy|SHARE_POLICY`
  boş — kalıcı/yetkili paylaşım katmanı hiç yok (yalnız istek bazlı `?fields=`
  düğmesi var). Gerçek boşluk doğrulandı (`gh issue view #70`: ülke+rol bazlı
  paylaşım alanları, önizleme, denetim kaydı).
- **Kapsam:** `src/models/share_policy.py` (`CountrySharePolicy`) +
  `scripts/migration/V023__country_share_policy.sql` (yalnızca ekleme),
  `src/services/share_policy.py` (`resolve_effective`/`effective_shared_fields`/
  `preview_sharing`/`set_policy`/`audit_trail`/`policy_matrix`),
  `src/routes/share_policy.py` (matris/preview/POST/audit), `settings.py` +
  `.env.example` (`SHARE_POLICY_DEFAULT_FIELDS`), `fastapi_app.py` kaydı,
  `risk_panel.html` (Veri Paylaşım Politikası kartı + `refreshSharePolicy`/
  `refreshSharePreview`/`saveSharePolicy`), `tests/unit/test_share_policy.py`
  (22 test), CHANGELOG + docs/api.
- **Varsayımlar:** (1) tek **ek-yazılımlı** tablo hem geçerli politikayı (en yeni
  satır) hem denetim kaydını (tüm dizi) taşır — ikinci bir tabloya gerek yok;
  (2) çözüm önceliği adlı rol → ülke varsayılanı (`*`) → `SHARE_POLICY_DEFAULT_FIELDS`;
  (3) EM-066'nın `?fields=` istek düğmesi 16 testini kırmamak için **ayrı ve
  dokunulmadan** kaldı — EM-070 kalıcı politikadır; (4) boş seçim "hiçbir şey
  paylaşma" demektir ve yasaldır.
- **Kanıt:** satır yokken geçerli = yapılandırılmış varsayılan; `set_policy`
  satır ekler + geçerli güncellenir; adlı rol > ülke varsayılanı > yapılandırılmış;
  adlı rol ülke varsayılanından devralır; boş seçim desteklenir; tanımsız alan/ülke
  → SharePolicyError; denetim en yeni önce + `previous_shared_fields` before→after
  zinciri; noop değişiklik `changed=false` ama yine de denetlenir; matris iki ülkeyi
  listeler; uçlar matrix/preview 200, POST 200 (commit sonrası geçerli yansır),
  geçersiz → 400, audit 200.
- **Kapılar:** black(172 değişmez)/mypy(112)/pylint(10.00)/bandit(0) yeşil;
  pytest **838** (816 + 22 yeni).
- **Commit:** `feat(EM-070): ...` (bu dal).

### EM-069 — Ortak sınır ötesi erken uyarı bildirimi (#69) — DONE

- **Eksik analizi:** `grep crossborder_notify|partner_notif` boş; mevcut
  "notification" eşleşmeleri yalnız yurt içi EM-063 risk eşiği uyarısı
  (`risk_alert.py`) — sınır ötesi **bildirim eylemi** (kabul kriteri: eşik
  aşımında karşı ülkeye önceden tanımlı kanaldan bildirim) hiç yok. EM-067
  projeksiyonu salt okunur üretiyor, bildirime dönmüyor. Gerçek boşluk doğrulandı.
- **Kapsam:** `src/models/crossborder_notification.py` (`CrossborderNotification`,
  `status` open/resolved) + `scripts/migration/V024__crossborder_notification.sql`
  (yalnızca ekleme), `src/services/crossborder_notification.py`
  (`evaluate_thresholds`/`dispatch`/`sweep`/`list_notifications`/
  `notification_status`/`channel_for`), `src/routes/crossborder_notification.py`
  (status/sweep/dispatch/list/config), `settings.py` + `.env.example`
  (`CROSSBORDER_NOTIFY_MIN_LIKELIHOOD`/`_WINDOW_MINUTES`/`_ENABLED`),
  `fastapi_app.py` kaydı, `risk_panel.html` (Ortak Erken Uyarı kartı +
  `refreshXborderNotify`/`runXborderNotifySweep`), `tests/unit/test_crossborder_notification.py`
  (18 test), CHANGELOG + docs/api.
- **Varsayımlar:** (1) bildirim **kanala kuyruğa alınarak** kalıcı kaydedilir —
  canlı ağ çağrısı mock edilmez ("bitti" göstermeme kuralı); (2) kanal
  alıcıları (`COORDINATION_CHANNELS`: TR MOBİL / GR Genel Sekreterlik) config'tir;
  (3) **kenar-tetiklemeli**: olay+hedef başına tek açık bildirim, yeniden
  süpürme spam yapmaz; (4) geçiş artık öngörülmediğinde açık bildirim otomatik
  çözülenre döner (yaşam döngüsü denetimi); (5) eşik olasılık + geçiş süresi
  pencercesinden geçer.
- **Kanıt:** düz-batı TR olayı → GR'ye eşik aşar (likelihood 1.0); 0.71 kayık
  geçit 0.4 kapıdan geçer 0.95'te kalır; uzak geçiş varsayılan pencerede dışarı,
  geniş pencerede içeride; uzaklaşan yön projeksiyon dışı; `dispatch` GR hedef
  TR kaynakla tek kayıt; ikinci `dispatch` dedup; `sweep` yaratır/yineler/çözer;
  GR tarafı TR'yi hedefler; `notification_status` notified False→True; uçlar
  config/status/sweep/list 200, bilinmeyen hedef → 400.
- **Kapılar:** black(176 değişmez)/mypy(115)/pylint(10.00)/bandit(0) yeşil;
  pytest **856** (838 + 18 yeni). Migration testi: V024 açıklama satırındaki `;`
  naive bölmede sahte ifademe yol açtı — açıklamadan kaldırıldı.
- **Commit:** `feat(EM-069): ...` (bu dal).

### EM-071 — Dış destek talebi taslağı üretme (#71) — DONE

- **Eksik analizi:** `grep support_request|request_draft|_draft` src/ içinde boş;
  EM-065 (`external_support.py`) yalnızca **erken tahmin** üretir (ihtiyaç/zaman/
  konum) ama bunlardan **düzenlenebilir bir talep taslağı** bestelenmiyordu. Gerçek
  boşluk doğrulandı (issue #71 kabul: otomatik özet + düzenle/kopyala/PDF + TR/EN/EL).
- **Kapsam:** `src/services/support_request_draft.py` (`build_request_draft`/
  `requestable_events`/`config_payload`/`default_draft_language`; EM-065 tahmininden
  **ihtiyaç + zaman + konum**la otomatik özet + çok satırlı metin; TR/EN/EL
  `_TEMPLATES`; EM-063 `format_coordinates`; EM-068 `normalize_language`),
  `src/routes/support_request_draft.py` (draft/events/config), `fastapi_app.py`
  kaydı, `settings.py` + `.env.example` (`SUPPORT_REQUEST_DEFAULT_LANGUAGE`),
  `risk_panel.html` (EM-071 kartı: olay seç + `sd-text` metin alanı + Kopyala +
  PDF/Yazdır), `tests/unit/test_support_request_draft.py` (19 test), CHANGELOG + docs/api.
- **Varsayımlar:** (1) taslak **durumsuzdur** — EM-065 tahmininden canlı bestelenir,
  hiçbir şey yazılmaz (persistence none); (2) düzenle/kopyala/PDF **operatör
  tarafıdır** (servis `editable` + `draft_text` döner); (3) dil EM-068 yerel
  makinesinden çözülür, bilinmeyen dil → 400; (4) açık öngörülmeyen olay da
  "yeterli" notlu taslak üretir (birim 0).
- **Kanıt:** ihtiyacı/zamanı/konumu ("38.000000, 27.000000", "2 birim", "T+40",
  "en geç T+30") TR özette; `draft_text` çok satırlı + etiketler; lead>açık →
  "hemen"; açık olmayan → "yeterli"; TR/EN/EL taslakları ayrı (EN başlık,
  EL "ΕΞΩΤΕΡΙΚΗΣ ΥΠΟΣΤΗΡΙΞΗΣ", "2 reinforcement units"); en-GB → en; "de" →
  I18nError; `SUPPORT_REQUEST_DEFAULT_LANGUAGE=en` varsayılanı; bilinmeyen olay →
  RiskIndexError; config `pdf`+`editable`; events suggested_event_key; uçlar
  draft/events/config 200, lang=en 200, NOPE→404, de→400.
- **Kapılar:** black(179 değişmez)/mypy(117)/pylint(10.00)/bandit(0) yeşil;
  pytest **875** (856 + 19 yeni).
- **Commit:** `feat(EM-071): ...` (bu dal).

### EM-078 — Sessiz bölge güven paneli (#78) — DONE

- **Eksik analizi:** `SilentRegion` modeli + ham `GET /api/v1/spatial/silent-regions`
  ucu (yalnızca aktifleri listeler) + `operator_map.html`'de `silent-regions`
  katmanı **zaten var**; ama **güven alanı / yüksek-düşük filtresi / sıralı liste /
  harita ile senkron seçim yoktu**. Modelde `confidence` kolonu yok. Gerçek boşluk
  doğrulandı (issue #78 kabul: "yüksek/düşük güven filtreleri, sıralı liste, harita
  ile senkron seçim").
- **Kapsam:** `src/services/silent_zone_panel.py` (`silent_zone_report`/
  `zone_config`; bbox içi aktif yangın → `OVERLAP_PENALTY`; en yakın yangın
  uzaklığı → `PROXIMITY_MAX_PENALTY * (1 - nearest/PROXIMITY_FAR_KM)`; `[0,1]`
  kırp; `high`/`moderate`/`low` bant; güven azalan + ad artan sıralama; `haversine_km`
  EM-057'den), `src/routes/silent_zone_panel.py` (`/api/v1/silent-zones` + `/config`),
  `fastapi_app.py` kaydı, `settings.py` + `.env.example` (`SILENT_ZONE_*`),
  `operator_map.html` (Sessiz Bölgeler düğmesi + bandı filtresi + tıklanabilir
  sıralı liste + `focusSilentRegion` `fitBounds`/vurgu),
  `tests/unit/test_silent_zone_panel.py` (17 test), CHANGELOG + docs/api.
- **Varsayımlar:** (1) panel **salt okuma zamanı projeksiyonudur** — yeni
  model/göç yok, mevcut `SilentRegion` tablosu kullanılır (persistence none);
  (2) güven **canlı mekânsal veriden deterministik** türer (öğrenilen model yok);
  (3) yalnızca `status == "active"` yangınlar çelişki sayılır; (4) bilinmeyen
  `confidence` değeri yutulmaz — `filter` null + `requested_filter` korunur.
- **Kanıt:** yangın yok → tümü `high` (güven 1.0); bbox içinde aktif yangın →
  `low` (≤0.05); ~5 km yakındaki yangın → `moderate`; >25 km → `high`; `contained`
  yangın çelişki saymaz; sıralama `Remote→Near→OnFire` güven azalan; `band_counts`
  `{high:1,moderate:1,low:1}`; `?confidence=high`→1 satır; `" HIGH "`→high; `bogus`
  →tümü+filter null; pasif bölge hariç; `/silent-zones` 200 (3), `?confidence=high`
  200 (1), `/config` 200 (3 bant).
- **Kapılar:** black(182 değişmez)/mypy(119)/pylint(10.00)/bandit(0) yeşil;
  pytest **892** (875 + 17 yeni).
- **Commit:** `feat(EM-078): ...` (bu dal).

### EM-079 — Panel durum kataloğu + bağlantı bandı (#79) — DONE

- **Eksik analizi:** panellerde **yükleme iskeleti / boş durum / hata mesajı**
  tek tip katalog yerine dağınık `.empty` div'leri ve `setStatus("Hata ...")`
  metinleriyle veriliyordu; `live-chip` "yeniden bağlanıyor" **rozet** gösteriyor
  ama **bağlantı-kesildi bandı** yoktu. `git grep` skeleton/ui-state/boş durum/
  connection-lost → 0 eşleşme. Gerçek boşluk doğrulandı (issue #79 kabul: "tüm
  panellerde yükleme iskeleti, boş durum ve hata mesajı; hata ne olduğunu ve ne
  yapılacağını söyler; bağlantı koparsa 'bağlantı kesildi' bandı görünür").
- **Kapsam:** `src/services/ui_states.py` (`PANEL_KEYS` 9 panel, `PANEL_STATES`
  title/loading/empty/error/error_action Türkçe, `CONNECTION_LOST`,
  `ui_state_catalog`/`panel_state`/`panel_states_by_key`/`connection_state`),
  `src/routes/ui_states.py` (`/api/v1/ui-states` + `/api/v1/ui-states/panel/{key}`,
  LookupError→404), `fastapi_app.py` kaydı, `settings.py` + `.env.example`
  (`UI_STATE_LANGUAGE`), `operator_map.html` (`#conn-lost` bandı + `.skel` +
  `.panel-err`; `loadUiStates`/`uiPanel`/`statusLayerError`/`panelLoading`/
  `panelEmpty`/`panelErrorHtml`/`showConnLost`; sessiz/etki/konuşlanma boş
  durumları + 5 `setStatus(Hata)` → `statusLayerError`; WebSocket `onopen`/`onclose`
  ve REST `ok`/`catch` → `showConnLost`; `#conn-lost-retry` → `startLive`),
  `tests/unit/test_ui_states.py` (14 test), CHANGELOG + docs/api.
- **Varsayımlar:** (1) katalog **salt okunur**, hiçbir şey yazılmaz
  (persistence none, model/göç yok); (2) EM-075 `design_system` kalıbı —
  test edilebilir UI arka ucu + Python testi; (3) `error_action` her zaman
  yapılabilir fiil içerir; (4) katalog gelmezse paneller yerel metinlerine düşer.
- **Kanıt:** her panel 4 durumu dolu; `error_action`'da etken fiil; `connection`
  title "Bağlantı kesildi" + `auto_reconnect`; katalog metadata (catalog=ui_states,
  language=tr, persistence=none); `_Settings.UI_STATE_LANGUAGE="en"` honore;
  `panel_state` kopya döner; bilinmeyen→LookupError; `connection_state(lost)`
  bandı taşır, recovered "geldi"; `/ui-states` 200 (9 panel), `/panel/map_layers`
  200, `/panel/nope` 404.
- **Kapılar:** black(185 değişmez)/mypy(121)/pylint(10.00)/bandit(0) yeşil;
  pytest **906** (892 + 14 yeni).
- **Commit:** `feat(EM-079): ...` (bu dal).

### EM-081 — Olay zaman çizelgesi (#81) — DONE

- **Eksik analizi:** olaylar iki ayrı yerdeydi — canlı değişim beslemesi
  (`live_updates`, EM-090: `fire_event`/`forecast`/`alert`) ve kabul edilen
  öneriler (`recommendation_decisions`, EM-047) — ve hiçbiri diğerini
  göstermiyordu; **tek zaman-sıralı akış** yoktu. `git grep` kronolojik/timeline/
  olay akış/vardiya → yalnızca EM-030 kapasite-açığı çizelgesi (farklı şey).
  Gerçek boşluk doğrulandı (issue #81 kabul: "tüm olaylar (tahmin güncellemesi,
  kabul edilen öneri, uyarı) kronolojik akışta görünür").
- **Kapsam:** `src/services/event_timeline.py` (`event_timeline`/`timeline_config`;
  `_live_entries` + `_decision_entries` birleştirme, `_sort_key` yeniden eskiye +
  kaynak-sırası/id deterministik eşitlik bozucu, `_opt_str` ORM-normalizasyon;
  `accepted_recommendation` yalnızca `accept`/`edit`), `src/routes/event_timeline.py`
  (`/api/v1/event-timeline` + `/config`), `fastapi_app.py` kaydı, `settings.py` +
  `.env.example` (`EVENT_TIMELINE_DEFAULT/MAX_LIMIT`), `ui_states.py`
  (`event_timeline` panel anahtarı), `operator_map.html` (Zaman Çizelgesi düğmesi +
  `#timeline-panel` + kategori filtresi + `toggleTimelinePanel`/`loadEventTimeline`/
  `renderTimelineList`/`timelineClock`; EM-079 `panelLoading`/`panelEmpty`/
  `panelErrorHtml` ile durumlar), `tests/unit/test_event_timeline.py` (18 test),
  CHANGELOG + docs/api.
- **Varsayımlar:** (1) **okuma zamanı projeksiyonu** — yeni model/göç yok
  (persistence none); (2) `reject`/`release` **kabul olmadığı için** çizelgeye
  girmez; (3) sıralama salt `created_at` (UTC) + deterministik eşitlik bozucu;
  (4) küçük sayfa boyutu/bir filtre tam yakın pencereyi görebilsin diye her
  kaynak `MAX_LIMIT`'e kadar çekilir.
- **Kanıt:** dört kategori de eşleşir; `edit`→"düzenlenerek kabul edildi";
  `reject` hariç (0 girdi); yeniden eskiye sıralı (alert en yeni); `event_key`
  ve `category` filtresi; ` FORECAST ` küçük/karışık; `bogus`→filtre null +
  `requested_category` + süzülmemiş 4; `category_counts` 1/1/1/1; `limit=2`→2
  sayfa `total_matching=4`; `limit=999`→MAX'a kırp; settingsiz varsayılan
  50/200; `/event-timeline` 200 (4), `?category=alert` 200, `/config` 200 (4).
- **Kapılar:** black(temiz)/mypy(123)/pylint(10.00)/bandit(0) yeşil;
  pytest **924** (906 + 18 yeni).
- **Commit:** `feat(EM-081): ...` (bu dal).

### EM-082 — Çoklu yangın yönetimi (#82) — DONE

- **Eksik analizi:** koordinatörün eş zamanlı yangınları tek görünümde görüp
  kaynak paylaşım çakışmasını uyarması yoktu — `recommendation_decision.py`
  yalnızca **yazma zamanı** çift-koruması (EM-053) yapar, olay-içi; `git grep`
  multi/cross-event/çoklu → çapraz-yangın envanteri/çakışma görünümü yok.
  Gerçek boşluk doğrulandı (issue #82 kabul: "aynı anda birden çok yangın
  izlenir; kaynaklar yangınlar arasında paylaşılırken çakışmalar uyarılır").
- **Kapsam:** `src/services/multi_fire.py` (`multi_fire_overview`/
  `multi_fire_config`; `_active_events` şiddet+başlangıç sıralı, `_busy_resources`
  `en_route`/`deployed`, `_newest_assignment_rows` id-desc en-yeni-satır, `_rank`
  şiddet; EM-053'le aynı "en yeni satır accept/edit" kadro kuralı),
  `src/routes/multi_fire.py` (`/api/v1/multi-fire` + `/config`), `fastapi_app.py`
  kaydı, `settings.py` + `.env.example` (`MULTI_FIRE_MAX_EVENTS`), `ui_states.py`
  (`multi_fire` panel anahtarı), `operator_map.html` (Çoklu Yangın düğmesi +
  `#multifire-panel` + `toggleMultifirePanel`/`loadMultifire`/`renderMultifire`;
  EM-079 durum yardımcıları), `tests/unit/test_multi_fire.py` (18 test),
  CHANGELOG + docs/api.
- **Varsayımlar:** (1) **okuma zamanı projeksiyonu** — yeni model/göç yok
  (persistence none); (2) kadro EM-053 kuralıyla (hâlâ meşgul + en yeni satır
  `accept`/`edit`) — later `release` kazanır, konuşlanmaz; (3) provens-blindsiz
  meşgul birim ne kadroya ne öksüz kovasına girir (görünmeyen provenans
  iddia edilmez); (4) `event_key` yalnızca `events` listesini kapsar, çakışma
  taraması küresel kalır.
- **Kanıt:** yalnızca-aktif (2 aktif + 1 contained→2); şiddet sırası
  critical>medium>low; `max_events=1`→1 (critical); accept→kadroda; release
  sonrası boş+kadro+öksüz yok; edit→kadroda; contained olaya atanan→öksüz; aynı
  üs iki aktif yangına→contended (1); tek yangına aynı üs→contended yok; kritik
  boş→understaffed; düşük boş→flag yok; dengeli→has_conflicts false; toplamlar
  1/2/1; `event_key` kapsamı events=1 total=2 + contended korunur; persistence
  none; config 4/3/3; `/multi-fire` 200 (1), `/config` 200 (3).
- **Kapılar:** black(191 temiz)/mypy(125)/pylint(10.00)/bandit(0) yeşil;
  pytest **942** (924 + 18 yeni).
- **Commit:** `feat(EM-082): ...` (bu dal).

### EM-083 — Salt okunur belediye görünümü (#83) — DONE

- **Eksik analizi:** belediye yöneticisi için **sadeleştirilmiş, yalnızca izleme
  amaçlı** bir ekran yoktu — ham veri (`fire_events`, `suppression_resources`)
  mevcut ama operatör konsolunun karar kontrollerinden (öneri/kabul/what-if/sevk)
  arındırılmış, bir bölge kutusuna indirgenmiş salt okunur projeksiyon
  yoktu. `git grep` belediye/municipal/salt okunur/read_only/simplified → eşleşme
  yok. Gerçek boşluk doğrulandı (issue #83 kabul: "P5 için sadeleştirilmiş,
  yalnızca izleme amaçlı ekran").
- **Kapsam:** `src/services/municipality_view.py` (`municipality_view`/
  `municipality_view_config`; `_region_box` ayarlanabilir kutu, `_in_box` dahil
  sınır, `_active_fires` acilden eskiye sıralı, `_unit_counts` yerel/havuz ayrımı,
  `_rank` şiddet), `src/routes/municipality_view.py` (`/api/v1/municipality-view`
  + `/config`), `fastapi_app.py` kaydı, `settings.py` + `.env.example`
  (`MUNICIPALITY_VIEW_REGION_NAME/MIN_LAT/MAX_LAT/MIN_LON/MAX_LON/MAX_FIRES`),
  `ui_states.py` (`municipality_view` panel anahtarı), `operator_map.html`
  (Belediye düğmesi + `#belediye-panel` + `toggleBelediyePanel`/`loadBelediye`/
  `renderBelediye`; EM-079 `panelLoading`/`panelEmpty`/`panelErrorHtml`),
  `tests/unit/test_municipality_view.py` (16 test), CHANGELOG + docs/api.
- **Varsayımlar:** (1) **okuma zamanı projeksiyonu** — yeni model/göç yok
  (persistence none); (2) kutu varsayılanı pilot bölge (config/pilot_region.json),
  ayarlanabilir; (3) sınır **kapalı (dahil)**; (4) yalnızca-operatör kontrolleri
  bilinçli gizlenir ve `omitted_operator_controls` ile adlandırılır; (5)
  `?severity=` yalnızca listeyi kapsar, `headline`/şiddet sayıları bölge-geneli
  kalır; tanınmayan şiddet kodu sessizce filtre olarak uygulanmaz.
- **Kanıt:** yalnızca-aktif+kutu içi (in-1; contained/out elenir); dahil sınır
  (köşe 39.5/30.0 girer); şiddet sırası crit>med>low + most_severe; histogram
  high2/med1; yerel/havuz kapasite (local 1/1, pool 2/1, maintenance hariç);
  boş bölge→calm + "bölgede aktif yangın yok"; `severity=low`→liste 1 ama
  total=2 + most_severe=high korunur; ` HIGH ` küçük/karışık; `bogus`→filtre
  uygulanmaz + `severity_recognised false` + 2 yangın; `max_fires=2`→2 liste
  total=5; kutu örtme→dar kutu 1 yangın; read_only/persistence none/attribution;
  config severities 4 + omitted_operator_controls + region kutu; `/municipality-view`
  200 (1), `?severity=low` 200, `/config` 200.
- **Kapılar:** black(temiz)/mypy(127)/pylint(10.00)/bandit(0) yeşil;
  pytest **958** (942 + 16 yeni).
- **Commit:** `feat(EM-083): ...` (bu dal).

### EM-086 — Bildirim merkezi ve sesli uyarı ayarları (#86) — DONE
- **Eksik analizi:** EM-032 risk uyarılarını `live_updates` (kind=`alert`)
  beslemesine yazıyor, EM-090 operatör haritasına akıtıyor AMA uyarıların
  **okundu/onaylandı** durumu tutulmuyor (ham beslemede ilgili kolon yok),
  kritik uyarı ekrandan kayboluyor ve sesli alarm EM-090'da **ya tam açık ya tam
  kapalı** (seviyeye göre ayarlanamıyor, kalıcı değil). Kabul kriterleri: tüm
  uyarılar okundu/okunmadı ile listelenir; sesli uyarı aç/kapa + seviyeye göre;
  kritik uyarı onaylanana kadar görünür kalır. E8 Should (sp3). `git grep`
  bildirim/notification/read_state/acknowledge ile gerçek boşluk doğrulandı.
- **Kapsam:** `src/models/notification_center.py` (`NotificationState` +
  `NotificationSoundSetting`), `scripts/migration/V025__notification_center.sql`
  (yalnızca eklenen iki tablo), `src/services/notification_center.py`
  (`list_notifications`/`mark_read`/`acknowledge`/`mark_all_read`/
  `get_sound_setting`/`update_sound_setting`/`should_sound`/config),
  `src/routes/notification_center.py` (7 uç, `fastapi_app`'e kaydedildi),
  `settings.py` + `.env.example` (`NOTIFICATION_MAX_ALERTS/SOUND_ENABLED/SOUND_MIN_LEVEL`),
  `ui_states.py` (`notification_center` anahtarı), `operator_map.html` (Bildirimler
  düğmesi + okundu/onaylandı satırları + sesli aç/kapa ve seviye seçici),
  `tests/unit/test_notification_center.py` (23 test), CHANGELOG + docs/api.
- **Varsayımlar:** (1) uyarı içeriği `live_updates`'ta kalır, bu tablo yalnızca
  elle tutma durumunu (`live_update_id` ile) tutar — taze uyarı dokunulana kadar
  okunmamış/onaylanmamış varsayılır; (2) kritik bandlar (`ACK_REQUIRED_LEVELS`)
  yalnızca `acknowledge` ile düşer, okumak çözmez; (3) sesli ayar tekil satır,
  yoksa ayarlardan tohumlanır (yazmadan), `update` kalıcılaştırır; (4) özet
  sayaçları `only_active` filtresinden bağımsız tüm pencereyi anlatır.
- **Kanıt:** boş→0; iki uyarı yeni-eski sıra; `kritik` okundu→hâlâ `still_showing`,
  onaylandı→düşer; `dikkat` okundu→düşer; `mark_all_read` unread=0 ama
  pending_ack=1; sesli varsayılan→`settings_default`, update→`stored`, geçersiz
  bant→`bilinmeyen`; `should_sound` sınır-dahil; `sounding` mutes→0; uçlar 200,
  bilinmeyen uyarı→404.
- **Kapılar:** black(temiz)/mypy(130)/pylint(10.00)/bandit(0) yeşil;
  pytest **981** (958 + 23 yeni; V025 migration `test_spatial` yeşil).
- **Commit:** `feat(EM-086): ...` (bu dal).

### EM-087 — Durum raporu (SITREP) PDF dışa aktarımı (#87) — DONE
- **Eksik analizi:** Yangın, yayılım tahmini, risk indeksi ve öneriler ayrı
  panolarda (EM-029/052) mevcut AMA hiçbir yüzey bunları **tek sayfada** komutanın
  üst makama/karşı ülkeye ileteceği bir rapor olarak derlemiyor; raporda zaman
  damgası ve sentetik veri rozeti yok. `git grep` sitrep/status_report/durum raporu
  ile gerçek boşluk doğrulandı (yalnızca test dosyasında geçiyor). Kabul kriterleri:
  rapor yangın+tahmin+risk+öneri+zaman damgası içerir; sentetik rozet görünür; PDF
  tek tıkla indirilir. E8 Should (sp5).
- **Kapsam:** `src/services/sitrep_report.py` (`build_sitrep`/`sitrep_config`),
  `src/routes/sitrep_report.py` (2 uç, `fastapi_app`'e kaydedildi), `settings.py` +
  `.env.example` (`SITREP_MAX_FIRES`/`SITREP_RECOMMENDATION_LIMIT`), `ui_states.py`
  (`sitrep` anahtarı), `operator_map.html` (Durum Raporu düğmesi + önizleme paneli +
  PDF/Yazdır gizli iframe), `tests/unit/test_sitrep_report.py` (20 test), CHANGELOG +
  docs/api. **Migration/model/settings kalıcılığı yok** — okuma zamanı projeksiyonu.
- **Varsayımlar:** (1) risk+tahmin tek kaynaktan: `compute_risk_index` ufuk satırları
  `area_ha` (yayılım) + `risk_index`/`level` taşır, ayrı forecast sorgusu gerekmez;
  (2) öneriler en sıcak olay (`summary.max_risk_event`) ya da kapsanan olay için;
  yol ağı/kaynak yoksa `build_proposals` fırlatmak yerine `available:false`+gerekçe;
  (3) sentetik rozet `fire_events.notes` içindeki EM-104 işaretinden (`_SYNTHETIC_MARKER`);
  (4) `max_fires` listeyi kırpar ama `active_fire_total`/özet küresel kalır.
- **Kanıt:** boş→0 yangın ama 5 bölüm + zaman damgası; tek olay→peak `kritik-yakin`,
  forecast 3 ufuk (6/9/10.8 ha); critical>low sıralama; `max_fires=1`→1 liste total=2;
  not=`SYNTHETIC_LABEL`→rozet true, gerçek→false; öneri yok-ağı→`available:false`+gerekçe;
  kurgu üretici→`available:true` rank1 + hedef=`max_risk_event`; `?event_key` kapsam;
  bilinmeyen→`RiskIndexError`; uçlar 200, bilinmeyen→404.
- **Kapılar:** black(temiz)/mypy(132)/pylint(10.00)/bandit(0) yeşil;
  pytest **1001** (981 + 20 yeni).
- **Commit:** `feat(EM-087): ...` (bu dal).

### EM-088 — Kullanıcı ayarları (dil, birim, tema) kalıcı profil (#88) — DONE
- **Eksik analizi:** Operatör dil/tema/gösterim tercihlerinin profil altında
  saklanmasını, anında uygulanmasını ve varsayılana dönmeyi ister. AMA EM-068 dili
  yalnızca tarayıcı `localStorage`'ında tutar (`persistence=none`), EM-063 saat
  dilimi/koordinat biçimini istek başına yeniden türetir (`persistence=none`), tema
  da yerelde kalır — sunucu tarafında **kayıtlı bir tercih profili** hiç yoktu.
  `git grep` preference/user_profile ile gerçek boşluk doğrulandı (yalnız
  `notification_center` sesli-ayar satırı çakışıyor). E8 Should (sp2).
- **Kapsam:** `src/models/user_preferences.py` + `scripts/migration/V026__user_preferences.sql`
  (tek satır, sabit anahtar `default`), `src/services/user_preferences.py`
  (`get_preferences`/`update_preferences`/`reset_preferences`/`preference_config`),
  `src/routes/user_preferences.py` (GET/PUT/DELETE + `/config`, `fastapi_app`'e
  kaydedildi), `settings.py` + `.env.example` (`UI_DEFAULT_THEME`), `i18n.py`
  (`btn.pref_reset` TR/EN/EL), `risk_panel.html` (`bootPreferences` + dil/tema
  kalıcılığı + saat/koordinat açılır listeleri + Varsayılana dön),
  `tests/unit/test_user_preferences.py` (16 test), CHANGELOG + docs/api + models/__init__.
- **Varsayımlar:** (1) EM-086 `NotificationSoundSetting` tek-satır deseni yeniden
  kullanılır; satır yoksa okuma **yazmadan** `settings_default` döner, ilk `PUT`
  oluşturur; (2) "birim" = sistem metrikte sabit (EM-063 `UNITS`), yüzden kayıtlı
  gösterim knobs'ları saat dilimi + koordinat biçimi; (3) dil/saat/koordinat
  EM-068/EM-063 değer kümeleriyle, tema `dark|light` ile doğrulanır; (4) UI
  `localStorage`'ı korur ama artık çevrimdışı ayna; sunucu profili autorite.
- **Kanıt:** boş okuma→`settings_default` + yazmama; `language=en`→`stored`
  + diğerleri varsayılan; kısmi yığılan güncelleme; dört alan geçersiz→`UserPreferenceError`;
  reset→satır siler→`settings_default`; config izin-kümeleri; uçlar GET/PUT/DELETE 200,
  geçersiz tema→400, config 200.
- **Kapılar:** black(temiz)/mypy(135)/pylint(10.00)/bandit(0) yeşil;
  pytest **1017** (1001 + 16 yeni).
- **Commit:** `feat(EM-088): ...` (bu dal).

### EM-089 — Vardiya devri notları ve olay notu ekleme (#89) — DONE
- **Eksik analizi:** Operatör olaya serbest metin not ekleyip vardiya
  devrinde iletmek ister. AMA canlı akış (EM-090), kabul edilen öneriler
  (EM-047) ve zaman çizelgesi (EM-081) salt makine üretimidir; `git grep`
  handover/event_note/vardiya ile **kalıcı bir not yüzeyi** ve **devir özeti**
  üreteci hiç olmadığı doğrulandı (yalnız EM-081'de geçen "devir" sözü bir
  okuma-zamanı projeksiyon). E8 Could (sp3), son açık E8 ögesi.
- **Kapsam:** `src/models/event_notes.py` + `scripts/migration/V027__event_notes.sql`,
  `src/services/shift_handover.py` (`add_note`/`list_notes`/`get_note`/`delete_note`/
  `handover_summary`/`handover_config`), `src/routes/shift_handover.py`
  (`/api/v1/shift-handover` + `/notes` GET/POST, `/notes/{id}` GET/DELETE, `/config`;
  `fastapi_app`'e SITREP sonrası kaydedildi), `settings.py` + `.env.example`
  (`SHIFT_HANDOVER_MAX_NOTES`), `ui_states.py` (`shift_handover` anahtarı),
  `operator_map.html` (Vardiya Devri paneli: olay/not/yazan formu + Ekle/Yenile/Sil
  + Devir Özetini Oluştur), `tests/unit/test_shift_handover.py` (27 test),
  CHANGELOG + docs/api + models/__init__.
- **Varsayımlar:** (1) **EM-081'e dokunulmaz** — `event_timeline` testleri
  `total_matching==4`/`len(categories)==4` sabit kodlu; not `operator_note`
  kategorisi yalnızca bu servisin kronolojisinde yaşar; (2) özet okuma zamanıdır,
  yalnızca `event_notes` kalıcıdır; (3) EM-082 `multi_fire_overview` + EM-081
  `event_timeline` yeniden kullanılır (kadro + çakışma + akış); (4) tanınmayan
  olay `add_note`ta reddedilir (öksüz not olmaz); (5) UI seçili olay anahtarını
  haritadan (`exposureEventKey`) önceden doldurur.
- **Kanıt:** not ekleme/şekil + gövde/yazan kırpma; boş not/boş anahtar/tanınmayan
  olay doğrulamaları; yeniden-eskiye + olay filtresi + `MAX_NOTES` kırpma;
  get/delete + yoksa `bulunamadı`; özette yalnızca aktif olaylar; **notun
  kronolojide `operator_note` olarak görünmesi** (kabul #2); tek olay kapsam;
  kart not sayısı/son not; çakışma bloğu; uçlar 200 + tanınmayan olay→404 + boş→400.
- **Kapılar:** black(temiz)/mypy(138)/pylint(10.00)/bandit(0) yeşil;
  pytest **1044** (1017 + 27 yeni).
- **Commit:** `feat(EM-089): ...` (bu dal).

### EM-034 — Kapasite varsayımları yönetim ekranı / denetim kaydı (#34) — DONE
- **Eksik analizi:** Yönetici ekip/helikopter/İHA ha/saat değerlerini arayüzden
  düzenlemek ve her değişikliğin denetim kaydının tutulmasını ister. AMA EM-028'in
  düzenleme yüzeyini (uçlar + `capacity_assumptions` tablosu + doğrulama +
  `risk_panel` kartı) **zaten** sağlamıştı; issue'nun üç kabul kriterinden ikisi
  (#1 düzenleme, #3 doğrulama) mevcuttu. `git grep` ile gerçek boşluk doğrulandı:
  modelde yalnızca **tek `updated_by` kolonu** var — eski değer / kim / ne zaman
  geçmişi tutulmuyor, yani **#2 "değişiklik denetim kaydına yazılır"** eksik.
  E3 Should (sp3).
- **Kapsam:** `src/models/capacity_audit.py` + `scripts/migration/
  V028__capacity_assumption_audit.sql`, `src/services/capacity.py`
  (`update_assumptions` denetim yazar + `applied_count`; yeni `list_audit`),
  `src/routes/capacity.py` (`PUT` gövdesine `updated_by`; yeni
  `GET /api/v1/capacity/assumptions/audit`), `settings.py` + `.env.example`
  (`CAPACITY_AUDIT_DEFAULT/MAX_LIMIT`), `risk_panel.html` (**Düzenleyen** alanı +
  Değişiklik geçmişi tablosu + `loadAssumeAudit`),
  `tests/unit/test_capacity_audit.py` (17 test), CHANGELOG + docs/api + models/__init__.
- **Varsayımlar:** (1) salt **gerçek** değişimler denetlenir (aynı değeri tekrar
  kaydetme satır üretmez); (2) denetim tablosu tohumlanmaz — okuma hiçbir şey
  yazmaz; (3) kapasite/risk matematiği `capacity_assumptions`'dan okumaya devam
  eder, denetim salt-geçmiş (fork yok); (4) `fastapi_app` değişmedi (kapasite
  uçları EM-028'de zaten kayıtlı); (5) `updated_by` opsiyonel, auth yok (E10).
- **Kanıt:** ilk düzenleme tek satır (eski 2.0→yeni 3.0, düzenleyen, `Z` damgası);
  aynı değer→`applied_count==0`+satır yok; çoklu tip ayrı satır; kısmi değişim
  yalnız değişeni denetler; yeniden-eskiye sıralama; tip filtresi; `MAX` kırpma;
  menfi/sayısal-olmayan/boş→`CapacityError` ve denetim yazmaz; uçlar PUT/GET 200 +
  boş geçmiş + geçersiz→400.
- **Kapılar:** black(temiz)/mypy(139)/pylint(10.00)/bandit(0) yeşil;
  pytest **1061** (1044 + 17 yeni).
- **Commit:** `feat(EM-034): ...` (bu dal).

### EM-094 — Olay ve uyarı webhook'ları (#94) — DONE
- **Eksik analizi:** Bütünleştirici, olay ve uyarıları kuyruklamak yerine bir alt
  sistem servisine anında **itilmesini** ister (kabul kriterleri: webhook URL'i +
  olay tipleri yapılandırılabilir / imzalı istek + yeniden deneme desteği / teslim
  geçmişi görüntülenebilir). Canlı akış (EM-090) ve bildirim merkezi (EM-086) yalnızca
  **çekme** (pull) modelidir. `git grep webhook` kod tabanında **hiçbir şey**
  döndürmedi → dışa dönük, imzalı, tekrar denemeli bir **itme** (push) kanadı gerçek
  bir boşluk. E9 Should (sp3).
- **Kapsam:** `src/models/webhook.py` (`WebhookSubscription` + salt-eklenen
  `WebhookDelivery` defteri; `as_dict` gizli anahtarı maskeler) + `scripts/migration/
  V029__event_alert_webhooks.sql`, `src/services/webhook_delivery.py` (CRUD +
  HMAC-SHA256 imza + `dispatch_event` + `retry_due` + `record_attempt` +
  `build_envelope[_preview]` + `webhook_overview`/`webhook_config`),
  `src/routes/webhook.py` (`/api/v1/webhooks/*`), `fastapi_app.py` kaydı,
  `settings.py` + `.env.example` (`WEBHOOK_MAX_SUBSCRIPTIONS/DELIVERIES/RETRIES/
  BACKOFF_SECONDS`), `ui_states.py` (`webhooks`), `operator_map.html` (Webhook'lar
  paneli), `tests/unit/test_webhook_delivery.py` (32 test), CHANGELOG + docs/api +
  models/__init__.
- **Varsayımlar:** (1) olay kataloğu `LIVE_KINDS` (`fire_event`/`forecast`/`alert`)
  ile birebir — yeni tür yok; (2) **gerçek HTTPS taşıyıcısı bilinerek yapılmaz**
  (EM-069 emsali), teslim defteri imzalı isteğin kalıcı/auditable kaydıdır, başarısızlık
  + yeniden-deneme `simulate_fail_for`/`record_attempt`/`retry_due` ile belirlenimci
  çalıştırılır; (3) `retry_due` tek bütçe kapısıdır — `_apply_failure` her zaman bir
  sonraki-deneme anı planlar, bütçe dolan satır kuyruktan düşer; (4) `as_dict` gizli
  anahtarı asla geri vermez (yalnızca `has_secret`); (5) auth yok (E10), `dispatch`
  `dry_run` dışında commit eder.
- **Kanıt:** gizli anahtar maskeleme; URL/olay-tipi/ad/azami doğrulama; imza
  determinizmi (aynı üçlü → aynı hex); zarf başlığı; dağıtım teslim/atlama/dry-run/
  bilinmeyen-tip/simüle-hata; yeniden-deneme başarı/genişleyen geri çekilme/bütçe-
  tükenme (`exhausted`); `record_attempt` başarı/bilinmeyen; geçmiş sıralama+durum+
  filtre; düzenle/duraklat; sil-geçmişi-korur; HTTP create/list/dispatch/history + 400/404.
- **Kapılar:** black(temiz)/mypy(142 dosya, temiz)/pylint(10.00)/bandit(0) yeşil;
  pytest **1093** (1061 + 32 yeni).
- **Commit:** `feat(EM-094): ...` (bu dal).

### EM-096 — Birleşik denetim kaydı (#96) — DONE
- **Eksik analizi:** Yönetici, hangi alt sistemden gelirse gelsin **kimin hangi
  kararı/değişikliği ne zaman verdiğini** tek bir yerde görmek ve kayıtların
  sonradan değiştirilemez/silinemez olmasını ister (kabul kriteri: "kabul/ret,
  senaryo, eşik/kapasite varsayımı değişiklikleri kim/ne zaman/ne ile kaydedilir.
  Kayıtlar silinemez"). Bugüne dek denetim **parça parça**ydı: kapasite
  `capacity_assumption_audit` (EM-034), kararlar `recommendation_decisions`
  (EM-047), paylaşım/webhook kendi tabloları. `git grep audit_trail` ve birleşik
  uç **hiçbir şey** döndürmedi → tek, birleşik, değişmez bir hesap verebilirlik
  defteri gerçek bir boşluk. E10 (auth/identity KISMI kapsam dışı; buradaki gerçek
  kod boşluğu **değişmezlik + birleşik okuma modeli**). E10 Must.
- **Kapsam:** `src/models/audit_trail.py` (`AuditTrailEntry`; `as_dict` JSON
  anlık görüntülerini çözümler) + `scripts/migration/V030__unified_audit_trail.sql`,
  `src/services/audit_trail.py` (`record_audit`/`list_audit`/`audit_config`/
  `count_by_domain` + `AUDIT_DOMAINS`/`AUDIT_ACTIONS` kontrollü sözlükleri),
  `src/routes/audit_trail.py` (`/api/v1/audit` config + özet + tek POST),
  `fastapi_app.py` kaydı, `settings.py` + `.env.example`
  (`AUDIT_DEFAULT_LIMIT`/`AUDIT_MAX_LIMIT`), `ui_states.py` (`audit_trail`),
  `operator_map.html` (Birleşik Denetim Kaydı paneli),
  `tests/unit/test_audit_trail.py` (21 test), CHANGELOG + docs/api + models/__init__.
- **Varsayımlar:** (1) birleşik defter **yalnızca-eklenen**dir — mevcut alt-özellik
  denetim tablolarına (EM-034/EM-047) dokunulmaz, onları beslemez/fork etmez; (2)
  "kayıtlar silinemez" garantisi servis ve rota yüzeyinde **güncelleme/silme/
  temizleme fonksiyonlarının yokluğu** ile verilir (pozitif bir kilit değil);
  (3) okuma hiçbir şey yazmaz, defter tohumlanmaz → dokunulmamış sistem boş liste;
  (4) `actor` zorunlu — sistemi kendi başına çıkaramayacağı "kim" alanıdır;
  (5) auth/identity yok (E10), `subject_key`/`summary` opsiyonel ve kolon genişliğine kırpılır.
- **Kanıt:** geçersiz alan/eylem + boş aktör/özet→`AuditError`; tek kayıt alan/
  eylem/aktör/JSON anlık görüntüsüyle döner; öksüzden-eskiye sıralama; alan/aktör/
  özne filtresi; `AUDIT_MAX_LIMIT` kırpma; `count_by_domain` alan sayımları;
  `audit_config` sözlükler + `immutable`/`persistence=append_only`; yüzeyde
  güncelle/sil fonksiyonu **yok**; uçlar POST→200 + GET özet/config + geçersiz→400.
- **Kapılar:** black(temiz, 219)/mypy(Success, 145 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1114** (1093 + 21 yeni).
- **Commit:** `feat(EM-096): ...` (bu dal).

### EM-035 — Bölge bazlı sinyal baz çizgisi (#35) — DONE
- **Eksik analizi:** Sessiz bölge **anomalisi**nin anlam kazanması için önce
  bölgenin "normal"inin öğrenilmesi gerekir (kabul: "yangın öncesi sinyal
  seviyesinin bölge (hücre) bazlı normal değeri öğrenilir; 30 günlük baz çizgi
  hücre bazında hesaplanır; sinyal kaynağı pilot için sentetik
  iletişim/rapor akışı, gerçek kaynak arayüzü (trafik/sosyal medya/sensör)
  soyutlanır"). EM-078 paneli yalnızca operatör kayıtlarının **güven bandını**
  canlı yangınlarla derecelendiriyordu; sinyal/iletişim baz çizgisi ve kaynak
  soyutlaması hiç yoktu (`signal_baseline`/`SignalSource` kod tabanında yok).
- **Kapsam kararları:** anomali sınıflandırıcısı (EM-036 Isolation Forest,
  ağır ML → kapsam dışı) burada **öğrenilmez**; `z_score`/`candidate_silent`
  yalnızca istatistiksel ön göstergedir. Gerçek beslemeler `planned` olarak
  listelenir ama **uygulanmaz/hapsedilmez** (ağ yok). Deterministik sentetik
  akış `sha256` ile süreçler arası yeniden üretilebilir ve her yanıtta
  SENTETİK etiketi taşır. `persistence: none` — model/migration yok.
- **Uygulama:** `signal_baseline.py` servisi: `SignalSource` ABC (tek
  `daily_signal(region_key, day)` — gerçek beslemeler buraya takılır),
  `SyntheticCommunicationSource` (hücre tabanı + hafta sonu ritmi + titreme),
  `monitoring_cells` pilot kutusunda satır×sütun ızgarası (`SB-RrCc`),
  `compute_cell_baseline` as_of'tan önceki kayan 30 günde
  ortalama/yayılım/medyan/aralık + son okumanın z-skoru/sessizlik oranı
  (`candidate_silent = z ≤ -eşik`), `baseline_report` en-sessiz-önce +
  kaynak/tarih/bölge/limit süzgeçleri, `baseline_config` kataloglar.
  `/api/v1/signal-baseline` + `/config` + `/cells/{region_key}`
  (bilinmeyen kaynak/tarih→400, bilinmeyen hücre→404); `settings.py` +
  `.env.example` (`SIGNAL_BASELINE_*` + `SIGNAL_PILOT_*` kutusu);
  `ui_states`'e `signal_baseline`; `operator_map` Sinyal Baz Çizgisi paneli
  (kaynak seçici + referans tarih + yalnızca-sessiz-adayı süzmesi + harita
  senkron hücre seçimi + SENTETİK rozeti); 28 test
- **Kapılar:** black(temiz, 222)/mypy(Success, 147 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1142** (1114 + 28 yeni).
- **Commit:** `feat(EM-035): ...` (bu dal).

### EM-037 — Yüksek öncelikli sessiz bölge kesişimi (#37) — DONE
- **Eksik analizi:** "Riskli ama sessiz" senaryosu — bir bölgeye yayılım tahmin
  poligonu **ulaşıyor** olmasına rağmen oradan SOS/yardım sinyali **gelmiyor**
  olabilir (kabul: "yayılım tahmin poligonu ile sessiz bölge birleştirilir;
  kesişen bölgeler 'yüksek öncelikli sessiz bölge' olarak işaretlenir; liste,
  risk × sessizlik derecesine göre sıralanır"). EM-078 paneli sessizlik **güven
  bandını**, EM-015 yayılım **poligonlarını** ayrı ayrı üretiyordu; ikisi
  hiçbir yerde birleştirilmemişti (`silent_region_risk` kod tabanında yok).
- **Kapsam kararları:** EM-078 `silent_zone_report` **yeniden kullanılır**
  (sessizlik yeniden hesaplanmaz); risk = Shapely bbox∩tahmin-kapsama oranı.
  Yalnızca **aktif** yangınlara bağlı `FireForecast` poligonları tehdit sayılır;
  çözülemeyen geometri atlanır. `persistence: none` — model/migration yok.
- **Uygulama:** `silent_region_risk.py` servisi: `_threat_polygons` (aktif
  `FireEvent`'e join, `created_at` azalan, `max_forecasts` kırpma),
  `_score_region` (kapsama oranı → `risk_degree`, EM-078 güveni →
  `silence_degree`, `priority = risk × sessizlik`, `worst_threat`+
  `threatening_event_keys`), `_flag_row` (`is_high_priority` hem risk hem
  sessizlik eşiği), `silent_region_risk_report` (risk-azalan sıralama,
  `flagged_only`/`limit` süzgeçleri, global `summary`), `silent_region_risk_config`.
  `/api/v1/silent-region-risk` + `/config` (`limit<1`→400; sorgu `ge=1`→422);
  `settings.py` + `.env.example` (`SILENT_REGION_RISK_*`); `ui_states`'e
  `silent_region_risk`; `operator_map` Yüksek Öncelikli Sessiz Bölge paneli
  (yalnız-öncelikli süzmesi istemci tarafında + harita senkron bölge seçimi);
  20 test
- **Kapılar:** black(temiz, 225)/mypy(Success, 149 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1162** (1142 + 20 yeni).
- **Commit:** `feat(EM-037): ...` (bu dal).

### EM-038 — Yanlış alarm önleme: sessiz bölge güven etiketi (#38) — DONE
- **Eksik analizi:** "Sessiz bölge" okumasının **gerçek acil durum** mu yoksa
  **yanlış alarm** mı olduğu ayrıştırılmalı (kabul: "sessiz bölge tespiti, yapısal
  olarak zayıf kapsama nedeniyle mi yoksa gerçekten ani kesinti nedeniyle mi sessiz
  olduğunu ayırt eder; güven etiketi operatöre gösterilir"). EM-035 baz çizgisi
  hangi hücrenin **sessiz aday** olduğunu üretiyor, EM-037 sessizliği riskle
  çarpıyor; ama zayıf kapsama (yapısal/yanlış alarm) ile sağlam kapsama üzerine ani
  düşüş (gerçek acil durum) ayrımı hiçbir yerde **güven derecesi** olarak
  etiketlenmiyordu (`silent_zone_confidence` kod tabanında yok). E4 Must (sp5).
- **Kapsam kararları:** EM-035 `baseline_report` **yeniden kullanılır** (baz
  çizgisi yeniden hesaplanmaz); sınıf **okuma zamanı** bileşimi, `persistence:
  none` — model/migration yok. Zayıf kapsama, ani düşüşten **önceliklidir** (düşük
  güven kazanır).
- **Uygulama:** `silent_zone_confidence.py` servisi: `_coverage_strength`
  (gözlem sayısı/ortalaması → `insufficient_data`/`weak`/`sound`), `classify_cell`
  (sağlam+`z ≤ -eşik`→**yüksek**, sağlam+belirgin değil→**orta**, zayıf/yetersiz→
  **düşük**; `confidence_code`/`_label`/`_reasons`), `silent_zone_confidence_report`
  ((derece,z,bölge) sıralama, `confidence`/`limit` süzgeçleri, global `summary`),
  `silent_zone_confidence_config`. `/api/v1/silent-zone-confidence` + `/config`
  (`limit<1`→422; bozuk `as_of`→400); `settings.py` + `.env.example`
  (`FALSE_ALARM_*`); `ui_states`'e `silent_zone_confidence`; `operator_map` Yanlış
  Alarm Önleme paneli (güven derecesi süzgeci istemci tarafında + harita senkron
  hücre seçimi, yüksek/orta/düşük renk rozetleri, SENTETİK etiketi); 24 test
- **Kapılar:** black(temiz, 228)/mypy(Success, 151 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1186** (1162 + 24 yeni).
- **Commit:** `feat(EM-038): ...` (bu dal).

### EM-042 — Sessiz bölge performans ölçümü (#42) — DONE
- **Eksik analizi:** Veri bilimcisi, sessiz bölge tespitinin gerçek doğruluğunu
  kanıtlamak için ölçmek istiyor (kabul: "sentetik senaryo kümesi üzerinde TPR, FPR
  ve uyarı gecikmesi hesaplanır; rapor 'sentetik senaryo' etiketiyle sunulur").
  EM-035 sessiz adayı üretiyor, EM-037/EM-038 sıralıyor/etiketliyor; ama dedektörün
  isabeti (kaç gerçek sessizliği yakalar, kaç yanlış alarm, ne kadar gecikir)
  hiçbir yerde **ölçülmüyordu** (`silent_detection_performance` kod tabanında yok).
  E4 Must (sp3).
- **Kapsam kararları:** **Gerçek EM-035 dedektörü** (`compute_cell_baseline`)
  deterministik sentetik senaryoda gün gün yeniden oynatılır; kök-hakikat senaryoya
  enjekte edilir (canlı veri/model yok). Ağır ML **değil** — okuma zamanı bileşimi,
  `persistence: none` — model/migration yok. Tanımsız oranlar `None` (0.0 değil).
- **Uygulama:** `silent_detection_performance.py` servisi: `SilentEpisode`
  (yarı-açık `covers`), `ScenarioSpec.truth`, `OutageInjectedSource` (bölümde
  okumayı `depth`'e çökertir), `build_scenario` (deterministik onset/slot),
  `confusion_metrics` (TP/FP/FN/TN → TPR/FPR/precision/recall/F1/accuracy),
  `evaluate_detection` (kafa karışıklığı + uyarı gecikmesi özeti + bölüm satırları,
  daima `synthetic: true`/`scenario_label`), `performance_config`.
  `/api/v1/silent-detection-performance` + `/config` (bozuk `as_of`→400;
  `SilentDetectionPerformanceError`→400); `settings.py` + `.env.example`
  (`SILENT_DETECTION_*`); `ui_states`'e `silent_detection_performance`; `operator_map`
  Sessiz Bölge Performans paneli (ana metrikler + bölüm satırları + SENTETİK etiketi);
  27 test
- **Kapılar:** black(temiz, 231)/mypy(Success, 153 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1213** (1186 + 27 yeni).
- **Commit:** `feat(EM-042): ...` (bu dal).

### EM-040 — Sessiz bölge uyarıları (#40) — DONE
- **Eksik analizi:** Operatör, riskli bir bölge sessizliğe düştüğü anda haberdar
  olmak istiyor (kabul: "riskli bir bölge sessizliğe düştüğünde uyarı üretilir; uyarı
  bölgeyi, süreyi ve risk seviyesini taşır; aynı bölge için tekrar uyarı bastırılır").
  EM-037 yüksek öncelikli sessiz bölgeleri risk × sessizlik ile sıralıyor; ama bu
  işaretli bölgelerden operatöre bölge/süre/risk seviyesi taşıyan, tekrarları
  bastırılmış tek bir **uyarı beslemesi** üreten katman **yoktu**
  (`silent_region_alert` kod tabanında yok). E4 Should (sp2).
- **Kapsam kararları:** EM-037 `silent_region_risk_report(flagged_only=True)`
  **yeniden kullanılır** — yeniden türetme yok. Sessizlik süresi `created_at`'tan
  şimdiye saat; öncelik skoru Türkçe risk merdivenine eşlenir; aynı bölgenin fazla
  tehditleri tek uyarıya katlanır. Ağır ML/altyapı **değil** — okuma zamanı bileşimi,
  `persistence: none` — model/migration yok.
- **Uygulama:** `silent_region_alert.py` servisi: `_risk_level` (kritik/yüksek/orta/
  düşük bandı), `_silence_created_map`/`_silence_duration` (created_at→saat),
  `_build_alert` (bölge başına tek uyarı + `suppressed_duplicate_alerts`),
  `silent_region_alert_report` (öncelik azalan sıralama, `by_level` özeti, `level`
  süzmesi + `limit` kırpma), `silent_region_alert_config`.
  `/api/v1/silent-region-alerts` + `/config` (`SilentRegionAlertError`→400;
  `limit<1`→422); `settings.py` + `.env.example` (`SILENT_ALERT_*_PRIORITY`,
  `SILENT_ALERT_MAX_LIMIT`); `ui_states`'e `silent_region_alert`; `operator_map`
  Sessiz Bölge Uyarıları paneli (risk rozetleri + harita senkron seçim); 19 test
- **Kapılar:** black(temiz, 234)/mypy(Success, 155 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1232** (1213 + 19 yeni).
- **Commit:** `feat(EM-040): ...` (bu dal).

### EM-041 — Sessiz bölge doğrulama akışı (#41) — DONE
- **Eksik analizi:** Operatör, sessiz bölge uyarısını **doğrulandı/yanlış alarm/
  inceleniyor** olarak işaretlemek istiyor ki sistem zamanla daha az yanlış yapsın
  (kabul: "operatör bir sessiz bölgeyi doğrulandı/yanlış alarm/inceleniyor olarak
  işaretleyebilir; bu geri bildirim modelin iyileştirilmesi için kaydedilir"). EM-040
  uyarıyı üretiyor; ama operatör hükmünü **kalıcı** tutan, önceki hükmü ezmeden
  eklenen-değişmez bir denetim zinciri kuran ve bunu yanlış-alarm oranına çeviren
  katman **yoktu** (`silent_zone_verification` kod tabanında yok). E4 Should (sp3).
- **Kapsam kararları:** Bu panel okuma-zamanlı E4 panellerinden farklı olarak
  **yazar** — EM-047 `recommendation_decisions` append-only desenini izler
  (model + V031 migration). Güncel hüküm = en yeni satır (üzerine yazılmaz);
  bölge adı anlık görüntülenir. Ağır ML/değil; geri bildirim **türetilmiş** bir
  sinyaldir (canlı model eğitimi yok).
- **Uygulama:** `silent_zone_verification.py` modeli (`VERIFICATION_STATUSES`/
  `VERIFICATION_LABELS`, `verification_key` unique, `detail_json`). Servis:
  `record_verification` (durum doğrulama + `_resolve_region` + anlık görüntü +
  `prior_verifications`), `get_current_verification`, `current_verdicts` (tek
  geçiş), `list_verifications` (durum/bölge süzme + limit kırpma),
  `feedback_summary` (by_status + kesin-only `false_alarm_rate`), `verification_config`.
  `/api/v1/silent-zone-verifications` (POST + liste + `/current` + `/feedback` +
  `/config`; geçersiz durum→400, bölge yok→404, `limit`→422); `settings.py` +
  `.env.example` (`SILENT_VERIFICATION_MAX_LIMIT`); `models/__init__`, `fastapi_app`
  kaydı, `ui_states` `silent_zone_verification`; `operator_map` Sessiz Bölge
  Uyarıları paneline hüküm rozeti + satır içi düğmeler + operatör girişi + geri
  bildirim şeridi; 23 test.
- **Kapılar:** black(temiz, 238)/mypy(Success, 158 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1258** (1235 + 23 yeni).
- **Commit:** `feat(EM-041): ...` (bu dal).

### EM-043 — Mevsimsel sinyal baz çizgisi (#43) — DONE
- **Eksik analizi:** EM-035 **düz** 30 günlük normal öğreniyor; yapısal olarak
  sessiz bir bölge (gecenin kör saati, hafta sonu) düz ortalamanın çok altında
  kalıp **yanlış** sessiz adayı oluyor (kabul: "saat ve haftanın günü etkisi modele
  eklenir; baz çizgisi günlük yeniden hesaplanır; yanlış alarm oranı yenileme
  öncesi/sonrası karşılaştırılır"). Mevsimselliği öğrenip arındıran, günlük
  yeniden hesaplayan ve önce/sonra yanlış-alarmı karşılaştıran katman **yoktu**
  (`signal_baseline_seasonal` kod tabanında yok). E4 Should (sp5).
- **Kapsam kararları:** EM-035 üzerine **okuma-zamanlı** bileşim
  (`persistence: none`); öğrenilen anomali sınıflandırıcısı EM-036 **değil** —
  çarpan-temelli iki-yönlü mevsimsel ayrıştırma (yinelemeli normalizasyon), bilinçli
  olarak istatistiksel bir düzeltme. Saat boyutunu gerçek/sınanabilir kılmak için
  deterministik **saatlik** `SyntheticDiurnalSource`; günlük-only kaynak dürüstçe
  yalnızca-hafta-günü mevsimselliğine düşer.
- **Uygulama:** Servis `signal_baseline_seasonal.py`:
  `learn_seasonal_factors` (hour/weekday çarpanları + artık/düz düzey+yayılım),
  `seasonal_cell` (`z_flat`/`z_seasonal`, `candidate_flat`/`candidate_seasonal`,
  `false_alarm_removed`), `seasonal_report` (düz→mevsimsel aday + elenen
  yanlış-alarm özeti), `refresh_daily_baselines` (günlük yeniden hesaplama),
  `seasonal_baseline_config`. `src/services/signal_baseline.py` taban
  `SignalSource`'a `has_hourly` + varsayılan `hourly_signal` eklendi (geriye
  dönük). `/api/v1/signal-baseline-seasonal` (+`/config`, `/refresh`; geçersiz
  kaynak/as_of→400, saat 0-23 dışı→422); `settings.py` + `.env.example`
  (`SIGNAL_SEASONAL_*`); `fastapi_app` kaydı, `ui_states`
  `signal_baseline_seasonal`; `operator_map` **Mevsimsel Baz Çizgisi** paneli
  (kaynak/kontrol-saati/referans-tarih + düz→mevsimsel özet + yalnızca-mevsimsel-aday
  süzmesi + harita senkron + Günlük Yenile); 29 test.
- **Kapılar:** black(temiz, 240)/mypy(Success, 160 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1287** (1258 + 29 yeni).
- **Commit:** `feat(EM-043): ...` (bu dal).

### EM-044 — Sessiz bölge hassasiyet ve eşik ayarı (#44) — DONE
- **Eksik analizi:** EM-035 tek bir **küresel** sessizlik z-eşiği, EM-040 tek bir
  **küresel** minimum sessizlik süresi kullanıyor; oysa "ne kadar sessiz = sessiz"
  ve "ne kadar bekleyelim" bölgeden bölgeye değişen bir yanlış-alarm/kaçırma
  takasıdır ve operatöre aittir (kabul: "eşik ve minimum sessizlik süresi arayüzden
  ayarlanır; değişiklik denetim kaydına yazılır; varsayılana dönme seçeneği
  vardır"). Bölge bazında bu düğmeleri ayarlayıp denetleyen katman **yoktu**
  (`silent_zone_tuning` kod tabanında yok). E4 Should.
- **Kapsam kararları:** bölge başına **tek kalıcı override satırı** (NULL →
  varsayılanı devralır); her gerçek değişiklik **tekilleştirilmiş denetim
  defterine** (`threshold` alanı, EM-096 `record_audit`) yazılır — **ikinci bir
  denetim tablosu açılmaz**; `reset` satırı düşürür, zaten varsayılan için
  idempotenttir. Legacy `Column` mutasyonu mypy için `setattr` ile (envanter
  deyimi).
- **Uygulama:** Model `silent_zone_tuning.py` + `V032__silent_zone_tuning.sql`;
  servis `silent_zone_tuning.py`: `effective_for_region`/`list_effective`
  (varsayılan⊕override, ayarlanmışlar önde), `set_tuning` (en az bir düğme,
  sınır doğrulama, upsert + `create`/`update` denetim), `reset_tuning` (`delete`
  denetim), `tuning_config`. `/api/v1/silent-zone-tuning` (+`/config`, `/effective`,
  POST, `/reset`; geçersiz→400, bölge yok→404); `settings.py` + `.env.example`
  (`SILENT_TUNING_*`); `fastapi_app` kaydı, `ui_states` `silent_zone_tuning`;
  `operator_map` **Sessiz Bölge Ayarı** paneli (bölge başına eşik+min-sessizlik
  editörleri, varsayılan/sınır şeridi, Kaydet/Varsayılana dön, operatör girişi);
  23 test.
- **Kapılar:** black(temiz, 245)/mypy(Success, 163 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1310** (1287 + 23 yeni).
- **Commit:** `feat(EM-044): ...` (bu dal).

### EM-036 — Isolation Forest ile anomali skorlama (#36) — DONE
- **Eksik analizi:** EM-035 **elle seçilmiş** tek bir z-eşiğiyle, EM-043 ise
  mevsimselliği arındırarak sessiz bölgeyi işaretliyor; hiçbiri istatistiği
  **öğrenen** çok-özellikli bir sınıflandırıcı değil (kabul: "15 dakikalık
  aralıklarla gerçek zamanlı anomali skoru üretilir; eşik: ortalama(baz çizgi) −
  3σ; yapılandırılabilir"). `isolation_forest_anomaly` kod tabanında **yoktu**.
  E4 Must (sp8). `scikit-learn==1.3.0` zaten `requirements.txt`'te sabitliydi;
  venv'e kuruldu.
- **Kapsam kararları:** EM-035 baz çizgisi **yeniden kullanılır**
  (`compute_cell_baseline`) — istatistiksel eşik kabul kriterindeki `ortalama −
  sigma·sapma` (sigma varsayılan 3.0, `1.0–5.0`); yanı sıra hücre başına
  `[bugünkü, dünki sinyal]` iki-özellikli vektör üzerinde baz penceresinde
  `IsolationForest` eğitilir, `as_of` yalnızca puanlanır (eğitime girmez);
  `random_state` sabit → yeniden üretilebilir skorlar; kalıcılık `none`
  ("gerçek zamanlı 15 dk" = `ANOMALY_INTERVAL_MINUTES` Celery beat'i okuma-zamanı
  taramasını tazeler). `detection_basis` model ile eşiğin uzlaşısını gösterir.
- **Uygulama:** Servis `isolation_forest_anomaly.py`: `build_feature_matrix`,
  `score_cell_anomaly` (öğrenilmiş `anomaly_score` + `learned_anomalous` +
  `quiet_threshold`/`silent_anomaly` + `detection_basis`), `anomaly_report`,
  `score_silent_zone_anomalies` (beat hedefi), `interval_minutes`,
  `anomaly_config`. `/api/v1/isolation-forest-anomaly` (+`/config`, `/latest`;
  geçersiz kaynak/as_of→400, sigma 1.0–5.0 dışı→422); `settings.py` +
  `.env.example` (`ANOMALY_*`); `fastapi_app` kaydı, `ui_states`
  `isolation_forest_anomaly`; `tasks.py` 15 dk beat (`score_silent_zone_anomaly_scores`,
  `ANOMALY_SCORING_ENABLED` kapılı); `operator_map` **Isolation Forest Anomali**
  paneli (sigma/pencere/kaynak/tarih + yalnızca-anomali süzmesi + skor/eşik/temel
  rozetleri + Anlık Tara + harita senkron); 21 test.
- **Kapılar:** black(temiz, 248)/mypy(Success, 165 dosya)/pylint(10.00)/bandit(0)
  yeşil; pytest **1331** (1310 + 21 yeni).
- **Commit:** `feat(EM-036): ...` (bu dal).


## Bitiş özeti

- **Tamamlanan görevler (hepsi DONE):** EM-031 (#31), EM-029 (#29),
  EM-030 (#30), EM-032 (#32), EM-056 (#56), EM-060 (#60), EM-061 (#61),
  EM-033 (#33), EM-057 (#57), EM-059 (#59), EM-062 (#62), EM-047 (#47), EM-046 (#46), EM-049 (#49), EM-048 (#48), EM-053 (#53), EM-051 (#51), EM-050 (#50), EM-045 (#45), EM-054 (#54), EM-063 (#63), EM-064 (#64), EM-065 (#65), EM-066 (#66), EM-067 (#67), EM-068 (#68), EM-070 (#70), EM-069 (#69), EM-071 (#71), EM-078 (#78), EM-079 (#79), EM-081 (#81), EM-082 (#82), EM-083 (#83), EM-086 (#86), EM-087 (#87), EM-088 (#88), EM-089 (#89), EM-034 (#34), EM-094 (#94), EM-096 (#96), EM-035 (#35), EM-037 (#37), EM-038 (#38), EM-042 (#42), EM-040 (#40), EM-041 (#41), EM-043 (#43), EM-044 (#44), EM-036 (#36) — her biri kendi commit'i ile
  `agent/task-automation` dalına push edildi; ilgili issue'lara
  özet yorum bırakıldı, hiçbiri **kapatılmadı**. EM-055 önceki oturumdan
  alınıp tamamlandı (#55).
- **BLOCKED:** bu turda yok. Kapsam dışı bırakılanlar (yukarıdaki eleme):
  insan/altyapı isteyen epikler (E10 auth, E12 deploy, E13 E2E, E14 demo)
  ve tek oturuma sığmayan devasa ML epikleri (E4, E7) — Mock ile "bitti"
  göstermeme kuralı gereği girilmedi.
- **Varsayımlar:** (1) görev listesi issue başlığına değil kod boşluğuna göre
  süzüldü; (2) EM-060 ölçek küçültme poligon köşesi + ufuk setini kırpır,
  gerçek CPU süresi yerine rüzgâr ucu `compute_ms`'i telemetriye beslenir;
  (3) uyarılar kenar-tetiklemeli (histerezis); (4) `.github/workflows/ci.yml`
  ve `docs/journal/` backlog'e ait olmadığı için commitlere alınmadı.
- **Final kapılar:** black 234 değişmez · mypy Success (155 dosya) · pylint 10.00/10 ·
  bandit 0 · pytest **1232 passed**.
- **PR:** main'e karşı **DRAFT** #244 açıldı (merge edilmedi).
- **Önerilen sonraki adımlar:** (a) E4/E7 ML epiklerini ayrı planla;
  (b) EM-060 kaba çözünürlüğünün gerçek PostgreSQL/Celery ürette p95 etkisini
  uçtan uca yük testiyle doğrula; (c) tamamlanan issue'ları kapatma kararını
  ver; (d) draft PR'ı inceleme sonrası merge et.
