"""International support-request draft generator (EM-071, Epic E7).

The cross-border coordinator (EM-065) learns *when* national capacity will run
short and *how many* reinforcement units that implies. This layer turns that
early forecast into the next concrete step: a ready-to-send **draft** of the
international support request, so raising the request is a copy-and-edit action
rather than a blank page.

The draft is composed entirely from data the system already projects - there is
no learned model and nothing is persisted (``persistence`` is ``none``):

* **need** comes from EM-065's ``estimated_support_units``;
* **time** comes from the ``first_shortfall_minute`` / ``request_by_minute``;
* **location** comes from the incident's latitude / longitude (rendered through
  the EM-063 standardised coordinate formatter).

From those three the service builds an *automatic one-line summary* and a
structured, editable text body. The whole draft is rendered in TR / EN / EL via
the EM-068 locale machinery (the same ``normalize_language`` the interface uses,
so an unsupported code is rejected the same way). Editing, copy-to-clipboard and
PDF export are operator-side actions on the returned editable text.
"""
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.services.external_support import forecast_external_support
from src.services.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_LABELS,
    SUPPORTED_LANGUAGES,
    normalize_language,
)
from src.services.localization import format_coordinates

DRAFT_ATTRIBUTION = (
    "EM-071: dış destek talebi taslağı EM-065 erken tahmininden (ihtiyaç/zaman/"
    "konum) otomatik özetle üretilir; TR/EN/EL; metin düzenlenebilir"
)
DRAFT_PERSISTENCE = "none"

# Fixed wording for the three locales. ``summary`` / ``no_shortfall`` are the
# auto one-liners; the ``label_*`` keys name each field in the text body. Every
# template carries the identical key set so the renderer never branches on
# language and a missing placeholder would surface immediately in tests.
_TEMPLATES: dict[str, dict[str, str]] = {
    "tr": {
        "header": "DIŞ DESTEK TALEBİ — TASLAK",
        "label_event": "Olay",
        "label_location": "Konum",
        "label_need": "Tahmini ihtiyaç",
        "label_shortfall": "Kapasite yetersizliği",
        "label_request_by": "Talep son tarih",
        "label_generated": "Oluşturulma zamanı",
        "need_value": "{units} birim takviye",
        "shortfall_value": "T+{minutes} dk",
        "request_by_value": "en geç T+{minutes} dk",
        "request_now_value": "hemen",
        "summary": (
            "{event} olayı ({location}) için ulusal kapasite {shortfall} "
            "sonrasında yetersiz kalacak; ≈ {units} birim dış destek "
            "gerekiyor. Talep {request_by} gönderilmelidir."
        ),
        "no_shortfall": (
            "{event} olayı ({location}) için öngörülen ufuk içinde ulusal "
            "kapasite yeterli görünüyor; şu aşamada dış destek talebi "
            "öngörülmüyor."
        ),
        "footer": (
            "Bu taslak EM-065 dış destek erken tahmininden otomatik üretilmiştir;"
            " metin düzenlenebilir."
        ),
    },
    "en": {
        "header": "EXTERNAL SUPPORT REQUEST — DRAFT",
        "label_event": "Incident",
        "label_location": "Location",
        "label_need": "Estimated need",
        "label_shortfall": "Capacity shortfall",
        "label_request_by": "Request deadline",
        "label_generated": "Generated at",
        "need_value": "{units} reinforcement units",
        "shortfall_value": "T+{minutes} min",
        "request_by_value": "by T+{minutes} min at the latest",
        "request_now_value": "immediately",
        "summary": (
            "For {event} ({location}) national capacity runs short after "
            "{shortfall}; ≈ {units} external support units are required. The "
            "request should be sent {request_by}."
        ),
        "no_shortfall": (
            "For {event} ({location}) national capacity is sufficient across "
            "the forecast horizon; no external support request is projected "
            "right now."
        ),
        "footer": (
            "This draft was generated automatically from the EM-065 external-"
            "support early forecast; the text is editable."
        ),
    },
    "el": {
        "header": "ΑΙΤΗΜΑ ΕΞΩΤΕΡΙΚΗΣ ΥΠΟΣΤΗΡΙΞΗΣ — ΣΧΕΔΙΟ",
        "label_event": "Συμβάν",
        "label_location": "Τοποθεσία",
        "label_need": "Εκτιμώμενη ανάγκη",
        "label_shortfall": "Έλλειψη χωρητικότητας",
        "label_request_by": "Προθεσμία αιτήματος",
        "label_generated": "Δημιουργήθηκε",
        "need_value": "{units} μονάδες ενίσχυσης",
        "shortfall_value": "T+{minutes} λεπτ.",
        "request_by_value": "έως T+{minutes} λεπτ. το αργότερο",
        "request_now_value": "άμεσα",
        "summary": (
            "Για το συμβάν {event} ({location}) η εθνική χωρητικότητα εξαντλείται"
            " μετά από {shortfall}; απαιτούνται ≈ {units} μονάδες εξωτερικής "
            "υποστήριξης. Το αίτημα πρέπει να σταλεί {request_by}."
        ),
        "no_shortfall": (
            "Για το συμβάν {event} ({location}) η εθνική χωρητικότητα αρκεί για "
            "το ορίζοντα πρόβλεψης· αυτή τη στιγμή δεν προβλέπεται αίτημα "
            "εξωτερικής υποστήριξης."
        ),
        "footer": (
            "Το σχέδιο δημιουργήθηκε αυτόματα από την πρόωρη πρόβλεψη "
            "υποστήριξης EM-065. Το κείμενο είναι επεξεργάσιμο."
        ),
    },
}


def _minutes(value: Optional[float]) -> Optional[int]:
    """Round a projected minute offset to a whole minute (``None`` passes)."""
    if value is None:
        return None
    return int(round(float(value)))


def _location_text(latitude: Any, longitude: Any) -> str:
    """Standardised coordinate string (EM-063), ``—`` when the point is absent."""
    if latitude is None or longitude is None:
        return "\u2014"
    try:
        return str(format_coordinates(latitude, longitude)["decimal"]["string"])
    except Exception:  # noqa: BLE001 - a bad point should not break the draft
        return "\u2014"


def _auto_summary(
    tpl: dict[str, str],
    event_name: str,
    location: str,
    assessment: dict[str, Any],
) -> str:
    """One-line summary built from need + time + location (acceptance #1)."""
    fmt = {
        "event": event_name,
        "location": location,
        "units": assessment["estimated_support_units"],
    }
    if not assessment["predicted_shortfall"]:
        return tpl["no_shortfall"].format(**fmt)
    first = _minutes(assessment["first_shortfall_minute"])
    request_by = _minutes(assessment["request_by_minute"])
    fmt["shortfall"] = tpl["shortfall_value"].format(minutes=first)
    fmt["request_by"] = (
        tpl["request_now_value"]
        if request_by is None or request_by <= 0
        else tpl["request_by_value"].format(minutes=request_by)
    )
    return tpl["summary"].format(**fmt)


def _draft_text(
    tpl: dict[str, str],
    event_name: str,
    event_key: str,
    location: str,
    assessment: dict[str, Any],
    generated_at: Any,
    summary: str,
) -> str:
    """Assemble the editable, copyable / printable multi-line draft body."""
    units = assessment["estimated_support_units"]
    need = tpl["need_value"].format(units=units)
    if assessment["predicted_shortfall"]:
        shortfall = tpl["shortfall_value"].format(
            minutes=_minutes(assessment["first_shortfall_minute"])
        )
        request_by = _minutes(assessment["request_by_minute"])
        deadline = (
            tpl["request_now_value"]
            if request_by is None or request_by <= 0
            else tpl["request_by_value"].format(minutes=request_by)
        )
    else:
        shortfall = "\u2014"
        deadline = "\u2014"
    lines = [
        tpl["header"],
        "=" * len(tpl["header"]),
        f"{tpl['label_event']}: {event_name} ({event_key})",
        f"{tpl['label_location']}: {location}",
        f"{tpl['label_need']}: {need}",
        f"{tpl['label_shortfall']}: {shortfall}",
        f"{tpl['label_request_by']}: {deadline}",
        f"{tpl['label_generated']}: {generated_at}",
        "",
        summary,
        "",
        tpl["footer"],
    ]
    return "\n".join(lines)


def build_request_draft(
    session: Session,
    settings: Any,
    event_key: str,
    lang: Optional[str] = None,
) -> dict[str, Any]:
    """Compose an editable external-support request draft for one incident.

    The need / time / location are read from the EM-065 early forecast, so an
    incident with no projected shortfall still yields a (clearly labelled) draft
    stating that no support is currently required. An unknown ``event_key``
    propagates the underlying :class:`RiskIndexError` (mapped to ``404``); an
    unsupported ``lang`` raises :class:`I18nError` (mapped to ``400``).
    """
    resolved = normalize_language(lang, default=default_draft_language(settings))
    forecast = forecast_external_support(session, settings, event_key)
    events = forecast.get("events", [])
    if not events:
        raise LookupError(f"no capacity timeline for event {event_key!r}")
    assessment = events[0]
    tpl = _TEMPLATES[resolved]

    event_name = assessment.get("name") or assessment["event_key"]
    location = _location_text(assessment.get("latitude"), assessment.get("longitude"))
    generated_at = forecast["generated_at"]
    summary = _auto_summary(tpl, event_name, location, assessment)
    draft_text = _draft_text(
        tpl,
        event_name,
        assessment["event_key"],
        location,
        assessment,
        generated_at,
        summary,
    )

    return {
        "panel": "support_request_draft",
        "language": resolved,
        "language_label": LANGUAGE_LABELS.get(resolved, resolved),
        "supported_languages": list(SUPPORTED_LANGUAGES),
        "event_key": assessment["event_key"],
        "event_name": event_name,
        "location": location,
        "estimated_support_units": assessment["estimated_support_units"],
        "first_shortfall_minute": assessment["first_shortfall_minute"],
        "request_by_minute": assessment["request_by_minute"],
        "predicted_shortfall": assessment["predicted_shortfall"],
        "generated_at": generated_at,
        "summary": summary,
        "draft_text": draft_text,
        "editable": True,
        "attribution": DRAFT_ATTRIBUTION,
        "persistence": DRAFT_PERSISTENCE,
    }


def requestable_events(session: Session, settings: Any) -> dict[str, Any]:
    """Active incidents that could need support, for the draft's event picker."""
    forecast = forecast_external_support(session, settings)
    items = [
        {
            "event_key": a["event_key"],
            "name": a.get("name") or a["event_key"],
            "predicted_shortfall": a["predicted_shortfall"],
            "estimated_support_units": a["estimated_support_units"],
            "first_shortfall_minute": a["first_shortfall_minute"],
            "request_by_minute": a["request_by_minute"],
        }
        for a in forecast.get("events", [])
    ]
    warning = [a for a in forecast.get("events", []) if a["predicted_shortfall"]]
    soonest = min(warning, key=lambda a: a["first_shortfall_minute"], default=None)
    return {
        "panel": "support_request_draft_events",
        "generated_at": forecast["generated_at"],
        "suggested_event_key": soonest["event_key"] if soonest else None,
        "events": items,
        "attribution": DRAFT_ATTRIBUTION,
        "persistence": DRAFT_PERSISTENCE,
    }


def config_payload(settings: Any = None) -> dict[str, Any]:
    """Supported draft locales + defaults (for the UI selector)."""
    resolved = default_draft_language(settings)
    return {
        "supported_languages": [
            {"code": code, "label": LANGUAGE_LABELS.get(code, code)}
            for code in SUPPORTED_LANGUAGES
        ],
        "default_language": resolved,
        "editable": True,
        "export_formats": ["text", "pdf"],
        "attribution": DRAFT_ATTRIBUTION,
        "persistence": DRAFT_PERSISTENCE,
    }


def default_draft_language(settings: Any = None) -> str:
    """The configured default draft locale (falls back to the i18n default)."""
    raw = getattr(settings, "SUPPORT_REQUEST_DEFAULT_LANGUAGE", None)
    if raw:
        try:
            return normalize_language(str(raw), default=DEFAULT_LANGUAGE)
        except Exception:  # noqa: BLE001 - a bad default must not break config
            return DEFAULT_LANGUAGE
    return DEFAULT_LANGUAGE


__all__ = [
    "DRAFT_ATTRIBUTION",
    "DRAFT_PERSISTENCE",
    "build_request_draft",
    "config_payload",
    "default_draft_language",
    "requestable_events",
]
