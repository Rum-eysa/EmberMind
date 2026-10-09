"""Municipality / traffic / public-alert integration templates (EM-093, Epic E9).

An integrator wants to connect the system to *existing* downstream equipment -
a municipality information board, a traffic variable-message sign (VMS), or a
public-alert head-end - without buying new hardware. EM-093 acceptance is that
connection template: *"an example webhook integration and documentation are
provided; no new hardware is required."*

EM-094 already *sends* a signed webhook (HMAC-SHA256 over ``<timestamp>.<body>``
in the ``X-EmberMind-Signature`` header) to a configured endpoint. This module
does not re-invent that transport; it is the companion **consumer-side
template**: given the real EM-094 envelope, it shows exactly how to reshape one
notification into each channel's native rendering, how to verify the signature
with the shared secret, and a small copy-paste receiver. The channel catalog,
the signature header and the event kinds are imported from the live EM-094
contract so the templates can never drift from what is actually delivered.

It is a pure read-time projection (``persistence: none``): no table, no
migration, no operator panel - this is a developer/integrator surface. Nothing
is ever claimed as "delivered" here either; the templates only *format* an
envelope the integrator already received.

Security note: the snippets reference the shared webhook secret through an
environment placeholder (``$EMBERMIND_WEBHOOK_SECRET``); a real secret is never
embedded, so a copy of these templates is not a credential leak.
"""

from typing import Any

from src.services.webhook_delivery import SIGNATURE_HEADER, VALID_EVENT_TYPES

TEMPLATES_PERSISTENCE = "none"

# Sample shared-secret placeholder used in every example - never a real value.
SECRET_PLACEHOLDER = "$EMBERMIND_WEBHOOK_SECRET"

# Traffic variable-message signs are severely character-limited per line.
VMS_MAX_CHARS_PER_LINE = 64

# Maps the three EM-094 live-feed kinds onto an operator-facing severity that
# downstream boards / alert head-ends understand.
_SEVERITY_BY_KIND = {
    "fire_event": "warning",
    "forecast": "advisory",
    "alert": "emergency",
}

# The three consumer channels this template covers. Each entry is factual: it
# names the real EM-094 kinds that channel is expected to render.
CHANNEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "municipality_board",
        "name": "Belediye bilgi panosu",
        "format": "json",
        "event_types": ["fire_event", "alert"],
        "no_new_hardware": (
            "Mevcut dijital pano / LCD yayın yazılımı basit bir JSON nesnesini "
            "okuyabilir; yeni donanım gerekmez."
        ),
    },
    {
        "id": "traffic_vms",
        "name": "Trafik değişken mesaj işareti (VMS)",
        "format": "vms_text",
        "event_types": ["fire_event", "alert"],
        "no_new_hardware": (
            "Yoldaki mevcut değişken mesaj işaretleri karakter sınırlı düz "
            "metin bekler; yeni donanım gerekmez."
        ),
    },
    {
        "id": "public_alert",
        "name": "Kamu uyarı yayını (CAP-benzeri)",
        "format": "cap_like",
        "event_types": ["alert"],
        "no_new_hardware": (
            "Bölgesel kamu uyarı head-end'i CAP-benzeri bir alan kümesini "
            "beslenebilir; yeni donanım gerekmez."
        ),
    },
]

CHANNEL_IDS = tuple(channel["id"] for channel in CHANNEL_CATALOG)


class IntegrationTemplateError(ValueError):
    """Raised for an unknown channel or a malformed notification envelope."""


def _sender(settings: Any) -> str:
    return str(getattr(settings, "INTEGRATION_CAP_SENDER", "") or "").strip() or (
        "it.embermind.wildfire"
    )


def _language(settings: Any) -> str:
    return (
        str(getattr(settings, "INTEGRATION_ALERT_LANGUAGE", "") or "").strip() or "tr"
    )


def _notification(envelope: Any) -> dict[str, Any]:
    """Extract and validate the notification block of an EM-094 envelope."""
    if not isinstance(envelope, dict):
        raise IntegrationTemplateError("zarf bir JSON nesnesi olmalıdır")
    notification = envelope.get("notification")
    if not isinstance(notification, dict):
        raise IntegrationTemplateError("zarfta 'notification' bloğu yok")
    return notification


def _region_of(notification: dict[str, Any]) -> str:
    """Best-effort human area from the payload, else the event key/source."""
    payload = notification.get("payload")
    if isinstance(payload, dict):
        for key in ("region", "region_name", "area", "municipality"):
            value = payload.get(key)
            if value:
                return str(value)
    return str(
        notification.get("event_key")
        or notification.get("source")
        or "bilinmeyen bölge"
    )


def _severity_for(event_type: str) -> str:
    return _SEVERITY_BY_KIND.get(str(event_type), "info")


def example_envelope(event_type: str = "alert") -> dict[str, Any]:
    """A representative (illustrative) EM-094 signed envelope for ``event_type``.

    The content is a *sample* used to demonstrate a template - it is not a claim
    that any real event happened, and it is not marked as delivered anywhere.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise IntegrationTemplateError(f"bilinmeyen olay tipi: {event_type}")
    titles = {
        "fire_event": "Aktif yangın algılandı",
        "forecast": "Yayılım tahmini güncellendi",
        "alert": "Yüksek risk - kamu uyarısı",
    }
    messages = {
        "fire_event": "Uydudan algılanan aktif yangın kümesi bölgeye yaklaşıyor.",
        "forecast": "Rüzgar değişimi nedeniyle tahmini yayılım alanı güncellendi.",
        "alert": "Kapasite açığı ve risk artışı; hazırlık seviyesini yükseltin.",
    }
    return {
        "subscription_key": "whk-example0001",
        "event_type": event_type,
        "delivery_id": "dlg-example00000001",
        "notification": {
            "id": 1001,
            "kind": event_type,
            "event_key": f"evt-{event_type}-0001",
            "title": titles[event_type],
            "message": messages[event_type],
            "source": "embermind-live",
            "payload": {"region": "Pilot Bölge A", "risk_index": 82},
            "created_at": "2026-07-01T12:00:00+00:00",
        },
    }


def _render_municipality_board(
    envelope: dict[str, Any], settings: Any
) -> dict[str, Any]:
    notification = _notification(envelope)
    event_type = str(envelope.get("event_type") or notification.get("kind") or "")
    return {
        "channel": "municipality_board",
        "format": "json",
        "render": {
            "headline": str(notification.get("title") or ""),
            "body": str(notification.get("message") or ""),
            "severity": _severity_for(event_type),
            "area": _region_of(notification),
            "timestamp": str(notification.get("created_at") or ""),
            "source": "EmberMind",
            "language": _language(settings),
        },
    }


def _clip(text: str, limit: int = VMS_MAX_CHARS_PER_LINE) -> str:
    """Upper-case, single-line, character-capped rendering for a VMS sign."""
    flat = " ".join(str(text or "").split()).upper()
    if len(flat) <= limit:
        return flat
    return flat[: limit - 2].rstrip() + ".."


def _render_traffic_vms(envelope: dict[str, Any], _settings: Any) -> dict[str, Any]:
    notification = _notification(envelope)
    event_type = str(envelope.get("event_type") or notification.get("kind") or "")
    return {
        "channel": "traffic_vms",
        "format": "vms_text",
        "render": {
            "line1": _clip(str(notification.get("title") or "")),
            "line2": _clip(str(notification.get("message") or "")),
            "max_chars_per_line": VMS_MAX_CHARS_PER_LINE,
            "flash": _severity_for(event_type) == "emergency",
            "closure_hint": event_type in ("fire_event", "alert"),
        },
    }


def _render_public_alert(envelope: dict[str, Any], settings: Any) -> dict[str, Any]:
    notification = _notification(envelope)
    event_type = str(envelope.get("event_type") or notification.get("kind") or "")
    severity = _severity_for(event_type)
    cap = {
        "sender": _sender(settings),
        "sent": str(notification.get("created_at") or ""),
        "msgType": "alert",
        "severity": severity,
        "urgency": "expected",
        "areaDesc": _region_of(notification),
        "headline": str(notification.get("title") or ""),
        "description": str(notification.get("message") or ""),
        "language": _language(settings),
    }
    xml = (
        "<alert>\n"
        f"  <sender>{cap['sender']}</sender>\n"
        f"  <sent>{cap['sent']}</sent>\n"
        f"  <msgType>{cap['msgType']}</msgType>\n"
        f"  <severity>{cap['severity']}</severity>\n"
        f"  <urgency>{cap['urgency']}</urgency>\n"
        f"  <areaDesc>{cap['areaDesc']}</areaDesc>\n"
        f"  <headline>{cap['headline']}</headline>\n"
        f"  <description>{cap['description']}</description>\n"
        "</alert>\n"
    )
    return {
        "channel": "public_alert",
        "format": "cap_like",
        "render": cap,
        "cap_xml_example": xml,
    }


_RENDERERS = {
    "municipality_board": _render_municipality_board,
    "traffic_vms": _render_traffic_vms,
    "public_alert": _render_public_alert,
}


def transform(envelope: dict[str, Any], channel: str, settings: Any) -> dict[str, Any]:
    """Reshape one EM-094 envelope into a specific channel's native rendering."""
    if channel not in _RENDERERS:
        raise IntegrationTemplateError(f"bilinmeyen entegrasyon kanalı: {channel}")
    rendered = _RENDERERS[channel](envelope, settings)
    rendered["event_type"] = str(
        envelope.get("event_type") if isinstance(envelope, dict) else ""
    )
    return rendered


def templates_for(event_type: str, settings: Any) -> dict[str, Any]:
    """Every supported channel rendering for one illustrative envelope."""
    if event_type not in VALID_EVENT_TYPES:
        raise IntegrationTemplateError(f"bilinmeyen olay tipi: {event_type}")
    envelope = example_envelope(event_type)
    outputs = [transform(envelope, channel, settings) for channel in CHANNEL_IDS]
    return {
        "event_type": event_type,
        "sample_envelope": envelope,
        "templates": outputs,
        "signature_header": SIGNATURE_HEADER,
    }


def signature_verification_snippet() -> str:
    """Reference Python that verifies the EM-094 ``X-EmberMind-Signature``."""
    return (
        "import hashlib\n"
        "import hmac\n"
        "import os\n"
        "\n"
        f"SECRET = os.environ['EMBERMIND_WEBHOOK_SECRET'].encode()\n"
        f"HEADER = '{SIGNATURE_HEADER}'\n"
        "\n"
        "def verify(timestamp: str, body: bytes, header_value: str) -> bool:\n"
        "    # header_value looks like: 't=<timestamp>,v1=<hex>'\n"
        "    parts = dict(p.split('=', 1) for p in header_value.split(','))\n"
        "    expected = hmac.new(SECRET, f'{timestamp}.'.encode() + body, "
        "hashlib.sha256).hexdigest()\n"
        "    return hmac.compare_digest(expected, parts.get('v1', ''))\n"
    )


def example_consumer(settings: Any) -> dict[str, Any]:
    """A minimal receiver skeleton: verify, then dispatch to a channel."""
    return {
        "description": (
            "Emniyetle paylaşılan gizli anahtarla imzayı doğrula, ardından "
            "zarfı hedef kanal biçimine çevir (belediye panosu / VMS / kamu uyarısı)."
        ),
        "secret_env": "EMBERMIND_WEBHOOK_SECRET",
        "signature_header": SIGNATURE_HEADER,
        "signature_scheme": "HMAC-SHA256, t=<timestamp>,v1=<hex> over '<timestamp>.<body>'",
        "verify_snippet": signature_verification_snippet(),
        "dispatch_note": (
            "Bu şablon yalnızca alıcı tarafı örneklendirir; gönderim ve tekrar "
            "deneme sözleşmesi EM-094'tedir. Yeni donanım gerekmez."
        ),
    }


def integration_config(settings: Any) -> dict[str, Any]:
    """Descriptive payload: channels, kinds, signature contract, bounds."""
    return {
        "channels": [dict(channel) for channel in CHANNEL_CATALOG],
        "event_types": list(VALID_EVENT_TYPES),
        "signature_header": SIGNATURE_HEADER,
        "signature_scheme": "HMAC-SHA256, t=<timestamp>,v1=<hex>",
        "secret_placeholder": SECRET_PLACEHOLDER,
        "cap_sender": _sender(settings),
        "alert_language": _language(settings),
        "vms_max_chars_per_line": VMS_MAX_CHARS_PER_LINE,
        "no_new_hardware": True,
        "attribution": "Belediye/trafik/kamu uyarı entegrasyon şablonu: EM-093",
        "persistence": TEMPLATES_PERSISTENCE,
    }


def templates_bundle(settings: Any) -> dict[str, Any]:
    """Aggregate integrator-facing bundle for a single endpoint."""
    return {
        "config": integration_config(settings),
        "by_channel": {
            event_type: templates_for(event_type, settings)
            for event_type in VALID_EVENT_TYPES
        },
        "consumer": example_consumer(settings),
        "attribution": "Belediye/trafik/kamu uyarı entegrasyon şablonu: EM-093",
    }
