"""Panel state catalogue (EM-079, Epic E8).

Operators stare at these panels all shift. When data is still arriving, empty,
or has failed, they must be able to tell the three apart at a glance - otherwise
a frozen-looking screen reads as a crashed one (EM-079 acceptance: "every panel
has a loading skeleton, an empty state and an error message; the error message
says what happened *and* what to do; if the connection drops a 'connection
lost' band appears").

This is the single, deterministic source of truth for those strings so every
panel speaks the same language instead of each one inventing its own ad-hoc
text. It renders no HTML and stores nothing - the operator surfaces fetch the
catalogue once and drive their loading/empty/error affordances from it, so
``persistence`` is ``none``.
"""
from typing import Any, Optional

# Every registered panel carries the four states the operator needs; the
# ``error`` line names the failure and ``error_action`` tells them what to do
# about it (retry / check a filter / report), never a bare stack trace.
PANEL_KEYS = (
    "map_layers",
    "exposure",
    "positioning",
    "whatif",
    "silent_zones",
    "capacity_risk",
    "external_support",
    "crossborder",
    "support_request_draft",
    "event_timeline",
    "multi_fire",
    "municipality_view",
    "notification_center",
    "sitrep",
    "shift_handover",
    "webhooks",
    "audit_trail",
    "signal_baseline",
    "signal_baseline_seasonal",
    "isolation_forest_anomaly",
    "silent_region_risk",
    "silent_zone_confidence",
    "silent_detection_performance",
    "silent_region_alert",
    "silent_zone_verification",
    "silent_zone_tuning",
    "map_interaction",
    "field_view",
    "accessibility",
    "auth",
)

PANEL_STATES: dict[str, dict[str, str]] = {
    "map_layers": {
        "title": "Harita katmanları",
        "loading": "Katmanlar yükleniyor…",
        "empty": "Bu katmanda gösterilecek kayıt yok.",
        "error": "Katman yüklenemedi.",
        "error_action": "Bağlantınızı kontrol edin ve yeniden deneyin.",
    },
    "map_interaction": {
        "title": "Harita altlığı, arama ve ölçüm",
        "loading": "Altlıklar ve arama hazırlandığında…",
        "empty": "Arama için bir yer adı yazın ya da 'enlem, boylam' girin; ölçüm için haritaya noktalar tıklayın.",
        "error": "Harita etkileşimi açılamadı.",
        "error_action": "Arama metnini/noktaları kontrol edip yeniden deneyin; sürerse bağlantıyı gözden geçirin.",
    },
    "field_view": {
        "title": "Saha Görünümü (mobil/tablet)",
        "loading": "Görev kartı ve yakın risk bölgeleri derleniyor…",
        "empty": "Atanmış görev yok; bir kaynak/olay seçin veya konum girin.",
        "error": "Saha görünümü alınamadı.",
        "error_action": "Kaynak/olay seçimini ve konumu kontrol edip yeniden deneyin; sürerse bağlantıyı gözden geçirin.",
    },
    "accessibility": {
        "title": "Erişilebilirlik ve kısayollar",
        "loading": "Renk körü güvenli palet, renkten-bağımsız risk kodlaması ve klavye kısayolları yükleniyor…",
        "empty": "Erişilebilirlik kataloğu döndüğünde kısayollar ve risk kodlamaları burada listelenir.",
        "error": "Erişilebilirlik kataloğu alınamadı.",
        "error_action": "Bağlantınızı kontrol edip yeniden deneyin; sürerse tema/kısayol düğmelerini kullanın.",
    },
    "auth": {
        "title": "Kimlik doğrulama",
        "loading": "Oturum politikası yükleniyor…",
        "empty": "Henüz oturum yok; e-posta ve parola ile giriş yapın.",
        "error": "Kimlik doğrulama hizmeti yanıt vermedi.",
        "error_action": "Bilgileri kontrol edip yeniden deneyin; hesap kilitlendiyse kilit süresinin dolmasını bekleyin.",
    },
    "exposure": {
        "title": "Tehdit altındaki yapılar",
        "loading": "Tehdit listesi hesaplanıyor…",
        "empty": "Seçili olayın tahmin poligonlarında tehdit altındaki yapı yok.",
        "error": "Tehdit listesi alınamadı.",
        "error_action": "Olayı yeniden seçin ya da birazdan tekrar deneyin.",
    },
    "positioning": {
        "title": "Konuşlanma önerileri",
        "loading": "Öneriler üretiliyor…",
        "empty": "Öneri yok. Bir olay seçin; seçili olay için müsait kaynak ve yol ağı olmalı.",
        "error": "Öneriler üretilemedi.",
        "error_action": "Kaynak ve yol ağı verisini kontrol edip yeniden deneyin.",
    },
    "whatif": {
        "title": "What-if senaryosu",
        "loading": "Senaryo yeniden hesaplanıyor…",
        "empty": "Kaydırıcıları hareket ettirin ya da haritadan bir ignisyon noktası seçin.",
        "error": "Senaryo yeniden hesaplanamadı.",
        "error_action": "Değerleri sıfırlayıp tekrar deneyin; sürerse bağlantıyı kontrol edin.",
    },
    "silent_zones": {
        "title": "Sessiz Bölgeler",
        "loading": "Sessiz bölgeler derecelendiriliyor…",
        "empty": "Bu filtrede sessiz bölge yok.",
        "error": "Sessiz bölge paneli açılamadı.",
        "error_action": "Filtreyi sıfırlayıp yeniden deneyin.",
    },
    "capacity_risk": {
        "title": "Kapasite ve risk paneli",
        "loading": "Kapasite ve risk hesaplanıyor…",
        "empty": "Seçili bölge için aktif olay ve kapasite verisi yok.",
        "error": "Kapasite/risk göstergeleri alınamadı.",
        "error_action": "Bölge seçimini gözden geçirin ve yeniden deneyin.",
    },
    "external_support": {
        "title": "Dış destek erken tahmini",
        "loading": "Destek ihtiyacı tahmin ediliyor…",
        "empty": "Öngörülen kapasite açığı yok; dış destek gerekmiyor.",
        "error": "Destek tahmini üretilemedi.",
        "error_action": "Hava ve yayılım verisinin güncel olduğundan emin olup tekrar deneyin.",
    },
    "crossborder": {
        "title": "Sınır ötesi durum",
        "loading": "Sınır ötesi durum derleniyor…",
        "empty": "Sınır ötesine yayılan aktif olay yok.",
        "error": "Sınır ötesi durum alınamadı.",
        "error_action": "Paylaşım politikası ve bağlantıyı kontrol edip tekrar deneyin.",
    },
    "support_request_draft": {
        "title": "Dış destek talebi taslağı",
        "loading": "Taslak oluşturuluyor…",
        "empty": "Taslak için bir olay seçin.",
        "error": "Taslak oluşturulamadı.",
        "error_action": "Olay ve dil seçimini kontrol edip yeniden deneyin.",
    },
    "event_timeline": {
        "title": "Olay zaman çizelgesi",
        "loading": "Olaylar kronolojik akışta derleniyor…",
        "empty": "Seçili filtrede olay yok; vardiya boyunca kayıt üretilmemiş.",
        "error": "Zaman çizelgesi alınamadı.",
        "error_action": "Filtreyi sıfırlayıp yeniden deneyin; sürerse bağlantıyı kontrol edin.",
    },
    "multi_fire": {
        "title": "Çoklu yangın yönetimi",
        "loading": "Aktif yangınlar ve konuşlanan kaynaklar derleniyor…",
        "empty": "Şu anda aktif yangın yok; kaynak çakışması riski yok.",
        "error": "Çoklu yangın envanteri alınamadı.",
        "error_action": "Envanter ve olay verisini kontrol edip yeniden deneyin.",
    },
    "municipality_view": {
        "title": "Belediye görünümü",
        "loading": "Bölge durumu yükleniyor…",
        "empty": "Bölgenizde aktif yangın yok; sakin izleme modunda.",
        "error": "Belediye görünümü alınamadı.",
        "error_action": "Bağlantınızı kontrol edin ve birazdan yeniden deneyin.",
    },
    "notification_center": {
        "title": "Bildirim merkezi",
        "loading": "Uyarılar yükleniyor…",
        "empty": "Bekleyen uyarı yok; canlı akış sakin.",
        "error": "Bildirim merkezi alınamadı.",
        "error_action": "Bağlantınızı kontrol edip yeniden deneyin; sürerse operatöre bildirin.",
    },
    "sitrep": {
        "title": "Durum Raporu (SITREP)",
        "loading": "Tek sayfalık durum raporu derleniyor…",
        "empty": "Bildirilecek aktif yangın yok; rapor boş durumla üretilir.",
        "error": "Durum raporu oluşturulamadı.",
        "error_action": "Bağlantınızı kontrol edip yeniden deneyin; sürerse risk/öneri verisini kontrol edin.",
    },
    "shift_handover": {
        "title": "Vardiya Devri",
        "loading": "Olay notları ve devir özeti derleniyor…",
        "empty": "Bu vardiyada not yok; devir özeti yalnızca otomatik olayları içerir.",
        "error": "Vardiya devri özeti oluşturulamadı.",
        "error_action": "Olay seçimini ve not metnini kontrol edip yeniden deneyin.",
    },
    "webhooks": {
        "title": "Olay & Uyarı Webhook'ları",
        "loading": "Webhook abonelikleri ve teslim geçmişi yükleniyor…",
        "empty": "Kayıtlı webhook aboneliği yok; bir uç nokta ve olay tipleri ekleyin.",
        "error": "Webhook durumu alınamadı.",
        "error_action": "Abonelik URL'sini ve olay tiplerini kontrol edip yeniden deneyin.",
    },
    "audit_trail": {
        "title": "Birleşik Denetim Kaydı",
        "loading": "Karar ve değişiklik geçmişi yükleniyor…",
        "empty": "Henüz denetim kaydı yok; karar/değişiklik oldukça buraya yazılır.",
        "error": "Denetim kaydı alınamadı.",
        "error_action": "Alan/aktör filtresini gözden geçirip yeniden deneyin.",
    },
    "signal_baseline": {
        "title": "Sinyal Baz Çizgisi",
        "loading": "Hücre bazında 30 günlük sinyal normali hesaplanıyor…",
        "empty": "Seçili filtrede izleme hücresi yok; ızgara aralığını gözden geçirin.",
        "error": "Sinyal baz çizgisi alınamadı.",
        "error_action": "Kaynak ve tarih seçimini kontrol edip yeniden deneyin.",
    },
    "signal_baseline_seasonal": {
        "title": "Mevsimsel Sinyal Baz Çizgisi",
        "loading": "Saat ve hafta günü mevsimselliği öğreniliyor…",
        "empty": "Seçili filtrede izleme hücresi yok; kaynak/saat seçimini gözden geçirin.",
        "error": "Mevsimsel baz çizgisi alınamadı.",
        "error_action": "Kaynak, saat ve tarih seçimini kontrol edip yeniden deneyin.",
    },
    "isolation_forest_anomaly": {
        "title": "Isolation Forest Anomali Skoru",
        "loading": "Hücre bazında çok-özellikli anomali skoru öğreniliyor…",
        "empty": "Seçili filtrede izleme hücresi yok; kaynak/tarih/sigma seçimini gözden geçirin.",
        "error": "Anomali skorları alınamadı.",
        "error_action": "Kaynak, sigma katsayısı ve tarih seçimini kontrol edip yeniden deneyin.",
    },
    "silent_region_risk": {
        "title": "Yüksek Öncelikli Sessiz Bölge",
        "loading": "Sessiz bölgeler yayılım tahmin riskiyle derecelendiriliyor…",
        "empty": "Yayılım tahmini ulaşan sessiz bölge yok; aktif yangın/tahmin var mı kontrol edin.",
        "error": "Sessiz bölge risk kesişimi alınamadı.",
        "error_action": "Eşik/filtre seçimini gözden geçirip yeniden deneyin.",
    },
    "silent_zone_confidence": {
        "title": "Yanlış Alarm Önleme: Güven Etiketi",
        "loading": "Sessiz adaylar kapsama gücüne göre güven derecesiyle etiketleniyor…",
        "empty": "Etiketlenen sessiz bölge adayı yok; EM-035 baz çizgisinde sessiz aday var mı kontrol edin.",
        "error": "Sessiz bölge güven etiketleri alınamadı.",
        "error_action": "Eşik/kaynak/tarih seçimini gözden geçirip yeniden deneyin.",
    },
    "silent_detection_performance": {
        "title": "Sessiz Bölge Performans Ölçümü",
        "loading": "Sentetik senaryoda tespit TPR/FPR ve uyarı gecikmesi hesaplanıyor…",
        "empty": "Enjekte edilmiş sessiz epizot yok; enjekte oranını/ufku artırıp yeniden deneyin.",
        "error": "Sessiz bölge performans ölçümü alınamadı.",
        "error_action": "Ufk/pencere/enjekte oranı seçimlerini gözden geçirip yeniden deneyin.",
    },
    "silent_region_alert": {
        "title": "Sessiz Bölge Uyarıları",
        "loading": "Yüksek öncelikli sessiz bölgeler için uyarılar üretiliyor…",
        "empty": "Yayılım tehdidiyle kesişen yüksek öncelikli sessiz bölge yok.",
        "error": "Sessiz bölge uyarıları alınamadı.",
        "error_action": "Sessiz bölge/yayılım verisini ve risk eşiği seçimlerini gözden geçirip yeniden deneyin.",
    },
    "silent_zone_verification": {
        "title": "Sessiz Bölge Doğrulama",
        "loading": "Operatör hükümleri (doğrulandı/yanlış alarm/inceleniyor) yükleniyor…",
        "empty": "Henüz işaretlenmiş sessiz bölge uyarısı yok; uyarı beslemesinden bir bölgeyi işaretleyin.",
        "error": "Sessiz bölge doğrulama kayıtları alınamadı.",
        "error_action": "Bölge kimliğini/hükmü gözden geçirip yeniden deneyin.",
    },
    "silent_zone_tuning": {
        "title": "Sessiz Bölge Hassasiyet ve Eşik Ayarı",
        "loading": "Bölge bazlı eşik ve minimum sessizlik süresi yükleniyor…",
        "empty": "Etkin sessiz bölge yok; ayarlanacak bölge önce sessiz bölge olarak kaydedilmeli.",
        "error": "Sessiz bölge ayarları alınamadı.",
        "error_action": "Bölge seçimini ve eşik/değer sınırlarını gözden geçirip yeniden deneyin.",
    },
}

# The connection-lost band is separate from any panel: it is the live-feed
# (WebSocket) health indicator. ``auto_reconnect`` mirrors the client's
# exponential back-off so the copy never promises a manual refresh.
CONNECTION_LOST: dict[str, Any] = {
    "title": "Bağlantı kesildi",
    "text": "Canlı akışla bağlantı koptu; ekran donmuş değil, yeniden bağlanılıyor.",
    "hint": "Kaçırılan güncellemeler bağlantı gelince telafi edilecek.",
    "retry_label": "Şimdi yeniden dene",
    "auto_reconnect": True,
}

UI_STATE_ATTRIBUTION = (
    "EM-079: panel durumları (yükleme/boş/hata) ve bağlantı-kesildi bandı tek "
    "katalogdan gelir; hata mesajı ne olduğunu ve ne yapılacağını söyler"
)
UI_STATE_PERSISTENCE = "none"
UI_STATE_LANGUAGE = "tr"


def panel_state(panel_key: str) -> dict[str, str]:
    """Return the four-state block for one panel.

    Raises ``LookupError`` for an unregistered key so the HTTP layer can answer
    404 rather than inventing a silent default.
    """
    if panel_key not in PANEL_STATES:
        raise LookupError(f"bilinmeyen panel anahtarı: {panel_key}")
    return dict(PANEL_STATES[panel_key])


def _panel_payload(panel_key: str) -> dict[str, str]:
    state = PANEL_STATES[panel_key]
    return {"key": panel_key, **state}


def ui_state_catalog(settings: Any = None) -> dict[str, Any]:
    """The full loading/empty/error + connection catalogue the surfaces consume."""
    language = UI_STATE_LANGUAGE
    if settings is not None:
        language = getattr(settings, "UI_STATE_LANGUAGE", UI_STATE_LANGUAGE)
    return {
        "catalog": "ui_states",
        "language": language,
        "panel_keys": list(PANEL_KEYS),
        "panels": [_panel_payload(key) for key in PANEL_KEYS],
        "connection": dict(CONNECTION_LOST),
        "attribution": UI_STATE_ATTRIBUTION,
        "persistence": UI_STATE_PERSISTENCE,
    }


def panel_states_by_key() -> dict[str, dict[str, str]]:
    """Panel key -> state block (a defensive copy for callers/tests)."""
    return {key: dict(value) for key, value in PANEL_STATES.items()}


def connection_state(lost: bool, detail: Optional[str] = None) -> dict[str, Any]:
    """Shape the connection band payload for the current live-feed health.

    ``lost=True`` surfaces the 'connection lost' copy plus the retry affordance;
    ``lost=False`` clears the band but keeps a short 'restored' note so the
    operator knows the feed recovered (and ``detail`` can carry the reason).
    """
    payload: dict[str, Any] = {
        "lost": bool(lost),
        "detail": detail,
    }
    if lost:
        payload["band"] = dict(CONNECTION_LOST)
        payload["text"] = CONNECTION_LOST["text"]
    else:
        payload["band"] = None
        payload["text"] = "Bağlantı geri geldi."
    return payload


__all__ = [
    "CONNECTION_LOST",
    "PANEL_KEYS",
    "PANEL_STATES",
    "UI_STATE_ATTRIBUTION",
    "UI_STATE_PERSISTENCE",
    "connection_state",
    "panel_state",
    "panel_states_by_key",
    "ui_state_catalog",
]
