"""Multilingual user-interface catalogue (EM-068, Epic E7).

A Greek *or* Turkish operator should read the coordination panel in their own
language, so the interface chrome - titles, card headings, table labels, button
captions and the fixed resource / risk-band enums - is resolved here from an
in-code message catalogue instead of being hard-coded in the HTML. This is the
**text** layer; the number / clock / coordinate *formatting* it complements is
EM-063 (:mod:`src.services.localization`).

Pilot coverage per the acceptance criteria:

* ``tr`` (default) and ``en`` are **complete** - they carry an identical key set;
* ``el`` covers the **core screens** (title, every card heading, the sharing
  scope, buttons, resource enum) and intentionally leaves the less common
  labels / FWI legend bands untranslated.

A missing key falls back first to ``en`` (the bridge language) and finally to
the raw key, so the UI never renders an empty string. Nothing is persisted: the
catalogue is compiled into the app, the chosen language lives only in the
operator's browser, so ``persistence`` is reported as ``none``.
"""
from __future__ import annotations

from typing import Any, Optional

SUPPORTED_LANGUAGES = ("tr", "en", "el")
DEFAULT_LANGUAGE = "tr"
# Language used to fill keys a locale does not translate yet (partial ``el``).
FALLBACK_LANGUAGE = "en"

LANGUAGE_LABELS = {
    "tr": "Türkçe",
    "en": "English",
    "el": "Ελληνικά",
}

I18N_ATTRIBUTION = (
    "EM-068: arayüz metinleri i18n kataloğundan gelir; TR ve EN tam, EL "
    "çekirdek ekranlar; eksik anahtar önce EN'e sonra ham anahtara düşer."
)
I18N_PERSISTENCE = "none"

# Reference (full) key set is TR; EN mirrors it exactly, EL is a subset.
_MESSAGES: dict[str, dict[str, str]] = {
    "tr": {
        "app.title": "Komutan Paneli — Kapasite ve Risk",
        "meta.threshold": "eşik",
        "meta.last_update": "son güncelleme: {time}",
        "card.threshold": "Eşik & Aşım",
        "card.legend": "Eşik Renkleri",
        "card.risk_index": "Olay Risk İndeksi — Risk(t)",
        "card.timeline": "Kapasite Açığı Zaman Çizelgesi",
        "card.budget": "Yeniden Hesaplama Bütçesi",
        "card.zones": "Bölgeler — Risk İndeksi ve İlk Aşım",
        "card.capacity": "Müdahale Kapasitesi",
        "card.assumptions": "Kapasite Varsayımları (ha/saat)",
        "card.breakdown": "Kapasite Kırılımı (ekip türü)",
        "card.by_country": "Kapasite — Ülke Bazında (EM-064)",
        "card.ext_support": "Dış Destek Erken Tahmini (EM-065)",
        "card.crossborder": "Sınır Ötesi Durum (EM-066)",
        "card.spread": "Sınır Geçiş Projeksiyonu (EM-067)",
        "card.inventory": "Kaynak Envanteri (EM-103)",
        "card.whatif": "Kapasite What-If (EM-056)",
        "card.source": "Kaynak",
        "label.threshold_value": "Eşik değeri",
        "label.zones_over": "Eşiği aşan bölge",
        "label.first_exceedance": "İlk aşım zamanı",
        "scope.share": "Paylaşım kapsamı",
        "scope.fire": "Yangın",
        "scope.risk": "Risk",
        "scope.support": "Destek",
        "btn.save": "Kaydet",
        "btn.run": "Senaryoyu çalıştır",
        "btn.theme": "Tema",
        "enum.resource.crew": "Ekip",
        "enum.resource.helicopter": "Helikopter",
        "enum.resource.uav": "İHA",
        "enum.category.very_low": "Çok Düşük",
        "enum.category.low": "Düşük",
        "enum.category.moderate": "Orta",
        "enum.category.high": "Yüksek",
        "enum.category.very_high": "Çok Yüksek",
        "enum.category.extreme": "Aşırı",
    },
    "en": {
        "app.title": "Commander Panel — Capacity & Risk",
        "meta.threshold": "threshold",
        "meta.last_update": "last updated: {time}",
        "card.threshold": "Threshold & Exceedance",
        "card.legend": "Threshold Colours",
        "card.risk_index": "Incident Risk Index — Risk(t)",
        "card.timeline": "Capacity-Gap Timeline",
        "card.budget": "Recompute Budget",
        "card.zones": "Zones — Risk Index & First Exceedance",
        "card.capacity": "Response Capacity",
        "card.assumptions": "Capacity Assumptions (ha/h)",
        "card.breakdown": "Capacity Breakdown (crew type)",
        "card.by_country": "Capacity — By Country (EM-064)",
        "card.ext_support": "External Support Early Forecast (EM-065)",
        "card.crossborder": "Cross-Border Situation (EM-066)",
        "card.spread": "Border-Crossing Projection (EM-067)",
        "card.inventory": "Resource Inventory (EM-103)",
        "card.whatif": "Capacity What-If (EM-056)",
        "card.source": "Source",
        "label.threshold_value": "Threshold value",
        "label.zones_over": "Zones over threshold",
        "label.first_exceedance": "First exceedance time",
        "scope.share": "Sharing scope",
        "scope.fire": "Fire",
        "scope.risk": "Risk",
        "scope.support": "Support",
        "btn.save": "Save",
        "btn.run": "Run scenario",
        "btn.theme": "Theme",
        "enum.resource.crew": "Crew",
        "enum.resource.helicopter": "Helicopter",
        "enum.resource.uav": "UAV",
        "enum.category.very_low": "Very Low",
        "enum.category.low": "Low",
        "enum.category.moderate": "Moderate",
        "enum.category.high": "High",
        "enum.category.very_high": "Very High",
        "enum.category.extreme": "Extreme",
    },
    # Core screens only (acceptance criterion); the rest resolves via ``en``.
    "el": {
        "app.title": "Πίνακας Διοικητή — Χωρητικότητα και Κίνδυνος",
        "meta.threshold": "όριο",
        "meta.last_update": "τελευταία ενημέρωση: {time}",
        "card.threshold": "Όριο & Υπέρβαση",
        "card.legend": "Χρώματα ορίου",
        "card.risk_index": "Δείκτης κινδύνου συμβάντος — Risk(t)",
        "card.timeline": "Χρονοδιάγραμμα ελλείψεως χωρητικότητας",
        "card.zones": "Ζώνες — Δείκτης κινδύνου & πρώτη υπέρβαση",
        "card.capacity": "Χωρητικότητα επέμβασης",
        "card.assumptions": "Παραδοχές χωρητικότητας (στρ/ώρα)",
        "card.breakdown": "Ανάδειξη χωρητικότητας (είδος πλήρωμα)",
        "card.by_country": "Χωρητικότητα — Ανά χώρα (EM-064)",
        "card.ext_support": "Πρόωρη πρόβλεψη εξωτερικής υποστήριξης (EM-065)",
        "card.crossborder": "Διασύνορη κατάσταση (EM-066)",
        "card.spread": "Πρόβλεψη διέλευσης συνόρων (EM-067)",
        "card.inventory": "Αποθετικό πόρων (EM-103)",
        "card.whatif": "Τι-αν χωρητικότητας (EM-056)",
        "card.source": "Πηγή",
        "scope.share": "Εύρος κοινοποίησης",
        "scope.fire": "Πυρκαγιά",
        "scope.risk": "Κίνδυνος",
        "scope.support": "Υποστήριξη",
        "btn.save": "Αποθήκευση",
        "btn.run": "Εκτέλεση σεναρίου",
        "btn.theme": "Θέμα",
        "enum.resource.crew": "Πλήρωμα",
        "enum.resource.helicopter": "Ελικόπτερο",
        "enum.resource.uav": "ΜΤΠ",
    },
}


class I18nError(ValueError):
    """Raised for an unsupported interface language code."""


def default_language(settings: Any = None) -> str:
    """The configured default locale (falls back to ``tr``)."""
    raw = getattr(settings, "I18N_DEFAULT_LANGUAGE", DEFAULT_LANGUAGE)
    try:
        return normalize_language(str(raw), default=DEFAULT_LANGUAGE)
    except I18nError:
        return DEFAULT_LANGUAGE


def normalize_language(raw: Optional[str], default: str = DEFAULT_LANGUAGE) -> str:
    """Reduce a BCP-47-ish tag (``tr-TR``, ``el-GR``) to a supported code.

    Empty / ``None`` resolves to ``default``. An unknown base language raises
    :class:`I18nError` so the endpoint can reject a bad preference instead of
    silently rendering the wrong locale.
    """
    text = (raw or "").strip().lower()
    if not text:
        return default
    base = text.split("-")[0].split("_")[0]
    if base in SUPPORTED_LANGUAGES:
        return base
    raise I18nError(f"unsupported language {raw!r}")


def _format(text: str, params: Optional[dict[str, Any]]) -> str:
    """Substitute ``{name}`` placeholders, leaving unknown ones untouched."""
    if not params:
        return text
    rendered = text
    for key, value in params.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def translate(
    key: str,
    lang: str = DEFAULT_LANGUAGE,
    params: Optional[dict[str, Any]] = None,
) -> str:
    """Resolve one message: locale -> ``en`` bridge -> raw key (never empty)."""
    catalog = _MESSAGES.get(lang, {})
    text = catalog.get(key)
    if text is None:
        text = _MESSAGES.get(FALLBACK_LANGUAGE, {}).get(key, key)
    return _format(text, params)


def get_messages(lang: str) -> dict[str, str]:
    """A complete flat catalogue for ``lang`` with ``en`` fallback applied."""
    merged = dict(_MESSAGES.get(FALLBACK_LANGUAGE, {}))
    merged.update(_MESSAGES.get(lang, {}))
    return merged


def coverage() -> dict[str, dict[str, int]]:
    """Per-language native key count against the full (TR) reference set."""
    total = len(_MESSAGES[DEFAULT_LANGUAGE])
    result: dict[str, dict[str, int]] = {}
    for code in SUPPORTED_LANGUAGES:
        native = len(_MESSAGES.get(code, {}))
        result[code] = {
            "native": native,
            "total": total,
            "missing": total - native,
        }
    return result


def messages_payload(lang: Optional[str], settings: Any = None) -> dict[str, Any]:
    """Build the ``/i18n/messages`` response for a requested locale."""
    resolved = normalize_language(lang, default=default_language(settings))
    return {
        "panel": "i18n_messages",
        "language": resolved,
        "language_label": LANGUAGE_LABELS.get(resolved, resolved),
        "default_language": default_language(settings),
        "fallback_language": FALLBACK_LANGUAGE,
        "supported_languages": list(SUPPORTED_LANGUAGES),
        "coverage": coverage(),
        "messages": get_messages(resolved),
        "attribution": I18N_ATTRIBUTION,
        "persistence": I18N_PERSISTENCE,
    }


def config_payload(settings: Any = None) -> dict[str, Any]:
    """The supported locales, their labels and coverage (for the switcher)."""
    cov = coverage()
    return {
        "supported_languages": [
            {
                "code": code,
                "label": LANGUAGE_LABELS.get(code, code),
                "native_keys": cov[code]["native"],
                "total_keys": cov[code]["total"],
            }
            for code in SUPPORTED_LANGUAGES
        ],
        "default_language": default_language(settings),
        "fallback_language": FALLBACK_LANGUAGE,
        "attribution": I18N_ATTRIBUTION,
        "persistence": I18N_PERSISTENCE,
    }


__all__ = [
    "DEFAULT_LANGUAGE",
    "FALLBACK_LANGUAGE",
    "I18N_ATTRIBUTION",
    "I18N_PERSISTENCE",
    "LANGUAGE_LABELS",
    "SUPPORTED_LANGUAGES",
    "I18nError",
    "config_payload",
    "coverage",
    "default_language",
    "get_messages",
    "messages_payload",
    "normalize_language",
    "translate",
]
