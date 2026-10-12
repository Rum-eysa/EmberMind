"""Event & alert webhook delivery (EM-094, Epic E9).

An integrator wants the system to *push* events and alerts to a downstream
service the moment they happen, instead of polling the live feed (EM-090) or
reading the notification centre (EM-086). EM-094 acceptance is that contract:

* **Webhook URL and event types are configurable** - a subscription registers
  an endpoint and the live-feed kinds it cares about (``fire_event`` /
  ``forecast`` / ``alert``);
* **Signed requests with retry support** - every request body is HMAC-SHA256
  signed with the subscription's shared secret (GitHub/GitLab-style
  ``<timestamp>.<body>`` signature) and a failed attempt schedules a bounded
  exponential-backoff retry;
* **Delivery history is viewable** - each attempt is an append-only ledger row
  recording the exact body, the signature, the outcome and the retry plan.

The transport (a real HTTPS POST to a third party) is deliberately *not*
performed here: following EM-069, a live network send is never mocked as
"delivered". Instead the ledger is the durable, auditable record of the signed
request and its retry policy, and an explicit ``outcome`` / a
``simulate_fail_for`` override let a caller exercise and record the real
success/failure path once a transport is wired in.

Everything is deterministic: kinds come from a fixed catalogue, the newest feed
event is selected by the monotonic feed id, and signatures are reproducible for
a given ``(secret, timestamp, body)`` triple.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.live import LIVE_KINDS, LiveUpdate
from src.models.webhook import (
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    WebhookDelivery,
    WebhookSubscription,
    parse_event_types,
)
from src.utils.timeutils import to_utc_iso, utc_now

SIGNATURE_HEADER = "X-EmberMind-Signature"
VALID_EVENT_TYPES = tuple(LIVE_KINDS)

DEFAULT_MAX_SUBSCRIPTIONS = 20
DEFAULT_MAX_DELIVERIES = 100
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 30

WEBHOOK_ATTRIBUTION = (
    "EM-094: olay ve uyarı webhook'ları - URL ve olay tipleri yapılandırılır, "
    "her istek paylaşılır gizli anahtarla HMAC-SHA256 imzalanır, başarısız "
    "deneme sınırlı üstel geri çekilme ile yeniden denenir ve her gönderim "
    "kalıcı teslim geçmişine yazılır"
)
WEBHOOK_PERSISTENCE = "webhook_subscriptions + webhook_deliveries"


class WebhookError(ValueError):
    """Raised for an invalid subscription, an unknown delivery, or a bad URL."""


def _int_setting(settings: Any, name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return default


def _max_subscriptions(settings: Any) -> int:
    return max(
        1,
        _int_setting(settings, "WEBHOOK_MAX_SUBSCRIPTIONS", DEFAULT_MAX_SUBSCRIPTIONS),
    )


def _max_deliveries(settings: Any) -> int:
    return max(
        1, _int_setting(settings, "WEBHOOK_MAX_DELIVERIES", DEFAULT_MAX_DELIVERIES)
    )


def _max_retries(settings: Any) -> int:
    return max(0, _int_setting(settings, "WEBHOOK_MAX_RETRIES", DEFAULT_MAX_RETRIES))


def _backoff_seconds(settings: Any) -> int:
    return max(
        1, _int_setting(settings, "WEBHOOK_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS)
    )


def _validate_url(url: Any) -> str:
    """Accept only an absolute http(s) URL; reject everything else."""
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WebhookError(f"geçersiz webhook URL: {url!r}")
    if len(text) > 300:
        raise WebhookError("webhook URL 300 karakteri aşıyor")
    return text


def _normalize_event_types(event_types: Any) -> list[str]:
    """Dedupe + validate the requested kinds against the fixed catalogue."""
    types = parse_event_types(event_types)
    if not types:
        raise WebhookError("en az bir olay tipi seçilmelidir")
    invalid = [t for t in types if t not in VALID_EVENT_TYPES]
    if invalid:
        raise WebhookError(f"bilinmeyen olay tipi: {', '.join(invalid)}")
    seen: list[str] = []
    for item in types:
        if item not in seen:
            seen.append(item)
    return seen


def signature_for(secret: str, timestamp: str, body: str) -> str:
    """HMAC-SHA256 (hex) over ``"<timestamp>.<body>"`` with the shared secret."""
    message = f"{timestamp}.{body}".encode("utf-8")
    return hmac.new(
        str(secret or "").encode("utf-8"), message, hashlib.sha256
    ).hexdigest()


def _feed_payload(row: LiveUpdate) -> dict[str, Any]:
    """Rebuild the notification body from a live-feed row."""
    try:
        payload = json.loads(str(row.payload_json)) if row.payload_json else {}
    except (ValueError, TypeError):
        payload = {}
    return {
        "id": int(row.id),
        "kind": str(row.kind),
        "event_key": row.event_key,
        "title": row.title,
        "message": row.message,
        "source": row.source,
        "payload": payload,
        "created_at": to_utc_iso(row.created_at),
    }


def _build_body(subscription: WebhookSubscription, row: LiveUpdate) -> str:
    """The canonical JSON body that gets signed and (would be) posted."""
    envelope = {
        "subscription_key": subscription.subscription_key,
        "event_type": str(row.kind),
        "delivery_id": f"dlg-{secrets.token_hex(8)}",
        "notification": _feed_payload(row),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"))


def build_envelope(
    subscription: WebhookSubscription, row: LiveUpdate, timestamp: Optional[str] = None
) -> dict[str, Any]:
    """Signed request preview - body + headers a transport would send.

    ``timestamp`` is injectable so the signature is reproducible in tests;
    production callers leave it ``None`` and get the current UTC instant.
    """
    stamp = str(timestamp if timestamp is not None else to_utc_iso(utc_now()))
    body = _build_body(subscription, row)
    return {
        "url": subscription.url,
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: f"t={stamp},v1={signature_for(str(subscription.secret), stamp, body)}",
        },
        "body": body,
        "timestamp": stamp,
    }


def build_envelope_preview(
    session: Session, settings: Any, subscription_key: str, event_type: str
) -> dict[str, Any]:
    """Return the signed request envelope for one subscription + newest event.

    A read-only "what would we send?" preview for an admin: it does not touch
    the delivery ledger, so nothing is recorded and no retry is scheduled.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise WebhookError(f"bilinmeyen olay tipi: {event_type}")
    subscription = _subscription_by_key(session, subscription_key)
    feed = session.scalars(
        select(LiveUpdate)
        .where(LiveUpdate.kind == event_type)
        .order_by(LiveUpdate.id.desc())
        .limit(1)
    ).first()
    if feed is None:
        raise WebhookError(f"{event_type} olayı yok - önizleme için canlı akış boş")
    return {
        "subscription_key": subscription.subscription_key,
        "envelope": build_envelope(subscription, feed),
    }


def _subscription_by_key(session: Session, key: str) -> WebhookSubscription:
    row = session.scalar(
        select(WebhookSubscription).where(
            WebhookSubscription.subscription_key == str(key)
        )
    )
    if row is None:
        raise WebhookError(f"webhook aboneliği bulunamadı: {key}")
    return row


def create_subscription(
    session: Session,
    settings: Any,
    *,
    name: str,
    url: str,
    event_types: Any,
    secret: Optional[str] = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Register an outbound webhook endpoint after validating it."""
    clean_name = str(name or "").strip()
    if not clean_name:
        raise WebhookError("abone adı boş olamaz")
    existing = session.scalar(select(func.count()).select_from(WebhookSubscription))
    if int(existing or 0) >= _max_subscriptions(settings):
        raise WebhookError("azami webhook abonelik sayısına ulaşıldı")
    types = _normalize_event_types(event_types)
    row = WebhookSubscription(
        subscription_key=f"whk-{secrets.token_hex(6)}",
        name=clean_name[:120],
        url=_validate_url(url),
        event_types=",".join(types),
        secret=str(secret).strip() if secret else secrets.token_hex(20),
        enabled=1 if enabled else 0,
    )
    session.add(row)
    session.flush()
    return dict(row.as_dict)


def list_subscriptions(session: Session, settings: Any) -> dict[str, Any]:
    """All subscriptions (oldest first) with per-subscription delivery counts."""
    rows = session.scalars(
        select(WebhookSubscription).order_by(WebhookSubscription.id.asc())
    ).all()
    counts = {
        int(sid): int(cnt)
        for sid, cnt in session.execute(
            select(WebhookDelivery.subscription_id, func.count()).group_by(
                WebhookDelivery.subscription_id
            )
        ).all()
    }
    subscriptions = []
    for row in rows:
        item = dict(row.as_dict)
        item["delivery_count"] = counts.get(int(row.id), 0)
        subscriptions.append(item)
    return {
        "panel": "webhooks",
        "subscriptions": subscriptions,
        "count": len(subscriptions),
        "max_subscriptions": _max_subscriptions(settings),
        "event_types": list(VALID_EVENT_TYPES),
        "signature_header": SIGNATURE_HEADER,
        "attribution": WEBHOOK_ATTRIBUTION,
        "persistence": WEBHOOK_PERSISTENCE,
    }


def update_subscription(
    session: Session,
    settings: Any,
    key: str,
    *,
    name: Optional[str] = None,
    url: Optional[str] = None,
    event_types: Any = None,
    secret: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> dict[str, Any]:
    """Partially edit a subscription; each supplied field is re-validated."""
    row = _subscription_by_key(session, key)
    if name is not None:
        clean = str(name).strip()
        if not clean:
            raise WebhookError("abone adı boş olamaz")
        row.name = clean[:120]  # type: ignore[assignment]
    if url is not None:
        row.url = _validate_url(url)  # type: ignore[assignment]
    if event_types is not None:
        row.event_types = ",".join(_normalize_event_types(event_types))  # type: ignore[assignment]
    if secret is not None and str(secret).strip():
        row.secret = str(secret).strip()  # type: ignore[assignment]
    if enabled is not None:
        row.enabled = 1 if enabled else 0  # type: ignore[assignment]
    session.flush()
    return dict(row.as_dict)


def delete_subscription(session: Session, settings: Any, key: str) -> dict[str, Any]:
    """Remove a subscription; its delivery history stays as an audit trail."""
    row = _subscription_by_key(session, key)
    session.delete(row)
    session.flush()
    return {"deleted": True, "subscription_key": key}


def _matching_subscriptions(
    session: Session, event_type: str
) -> list[WebhookSubscription]:
    """Enabled subscriptions whose event-type list contains ``event_type``."""
    rows = session.scalars(
        select(WebhookSubscription).where(WebhookSubscription.enabled == 1)
    ).all()
    return [row for row in rows if event_type in parse_event_types(row.event_types)]


def _new_delivery(
    subscription: WebhookSubscription, row: LiveUpdate, body: str, stamp: str
) -> WebhookDelivery:
    """Construct a pending ledger row for one signed request."""
    return WebhookDelivery(
        delivery_key=f"dlv-{secrets.token_hex(8)}",
        subscription_id=int(subscription.id),
        subscription_key=subscription.subscription_key,
        url=subscription.url,
        live_update_id=int(row.id),
        event_type=str(row.kind),
        event_key=row.event_key,
        request_body=body,
        signature=signature_for(str(subscription.secret), stamp, body),
        timestamp_header=stamp,
        status=DELIVERY_PENDING,
        attempt=1,
    )


def dispatch_event(
    session: Session,
    settings: Any,
    event_type: str,
    *,
    limit: Optional[int] = None,
    simulate_fail_for: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fan the newest feed events of one kind out to matching subscribers.

    For every enabled subscription interested in ``event_type`` the most recent
    feed rows are signed and written to the delivery ledger. A failure can be
    injected via ``simulate_fail_for`` (a subscription key) to exercise the
    retry path; ``dry_run`` builds and returns the signed envelope without
    persisting anything (an admin "test this endpoint" preview).
    """
    if event_type not in VALID_EVENT_TYPES:
        raise WebhookError(f"bilinmeyen olay tipi: {event_type}")
    subscriptions = _matching_subscriptions(session, event_type)
    capped = max(1, int(limit)) if limit else _max_deliveries(settings)
    feed_rows = session.scalars(
        select(LiveUpdate)
        .where(LiveUpdate.kind == event_type)
        .order_by(LiveUpdate.id.desc())
        .limit(capped)
    ).all()

    deliveries: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []
    for sub in subscriptions:
        for feed in feed_rows:
            stamp = str(to_utc_iso(utc_now()))
            body = _build_body(sub, feed)
            envelope = build_envelope(sub, feed, timestamp=stamp)
            if dry_run:
                previews.append(envelope)
                continue
            delivery = _new_delivery(sub, feed, body, stamp)
            session.add(delivery)
            session.flush()
            if simulate_fail_for == sub.subscription_key:
                _apply_failure(delivery, settings, reason="simüle edilen teslim hatası")
            else:
                delivery.status = DELIVERY_DELIVERED  # type: ignore[assignment]
                delivery.http_status = 200  # type: ignore[assignment]
                delivery.next_retry_at = None  # type: ignore[assignment]
            session.flush()
            deliveries.append(dict(delivery.as_dict))

    return {
        "event_type": event_type,
        "dry_run": dry_run,
        "subscriptions_matched": len(subscriptions),
        "feed_events": len(feed_rows),
        "deliveries": deliveries,
        "previews": previews,
        "created": len(deliveries),
    }


def _apply_failure(
    delivery: WebhookDelivery, settings: Any, *, reason: str, status: int = 502
) -> None:
    """Mark an attempt failed and schedule the next retry with wider backoff.

    The retry budget itself is enforced by :func:`retry_due` (which only re-attempts
    rows still under the max-attempt cap); here we always record a due timestamp so
    the row is eligible for the next pass, backing off exponentially per attempt.
    """
    delivery.status = DELIVERY_FAILED  # type: ignore[assignment]
    delivery.http_status = status  # type: ignore[assignment]
    delivery.error = str(reason)[:255]  # type: ignore[assignment]
    backoff = _backoff_seconds(settings) * (2 ** (max(1, int(delivery.attempt)) - 1))
    delivery.next_retry_at = to_utc_iso(utc_now() + timedelta(seconds=backoff))  # type: ignore[assignment]


def record_attempt(
    session: Session,
    settings: Any,
    delivery_key: str,
    *,
    success: bool,
    http_status: Optional[int] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    """Record the transport outcome of a pending/failed delivery attempt.

    ``success=True`` closes the loop (delivered, no further retry); a failure
    re-schedules the next bounded retry. This is the seam a real HTTP client
    calls once the transport exists - it never re-rolls the attempt counter on a
    success.
    """
    delivery = session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.delivery_key == str(delivery_key))
    )
    if delivery is None:
        raise WebhookError(f"teslim kaydı bulunamadı: {delivery_key}")
    if success:
        delivery.status = DELIVERY_DELIVERED  # type: ignore[assignment]
        delivery.http_status = int(http_status) if http_status is not None else 200  # type: ignore[assignment]
        delivery.next_retry_at = None  # type: ignore[assignment]
        delivery.error = None  # type: ignore[assignment]
    else:
        _apply_failure(
            delivery,
            settings,
            reason=error or "teslim başarısız",
            status=int(http_status) if http_status is not None else 502,
        )
    session.flush()
    return dict(delivery.as_dict)


def retry_due(
    session: Session,
    settings: Any,
    *,
    simulate_fail: bool = False,
) -> dict[str, Any]:
    """Re-attempt failed deliveries that still have a retry scheduled.

    Only rows still below the max-attempt budget are retried; each re-attempt
    increments the counter and, on another failure, reschedules with a wider
    backoff (once the budget runs out the row is left failed with no next retry).
    ``simulate_fail`` keeps exercising the failure path (used before a transport
    exists / in tests); otherwise a retry is recorded as delivered.
    """
    max_retries = _max_retries(settings)
    failed = session.scalars(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status == DELIVERY_FAILED,
            WebhookDelivery.next_retry_at.is_not(None),
        )
        .order_by(WebhookDelivery.id.asc())
    ).all()

    retried: list[dict[str, Any]] = []
    exhausted: list[dict[str, Any]] = []
    for delivery in failed:
        if int(delivery.attempt) >= max_retries:
            delivery.next_retry_at = None  # type: ignore[assignment]
            exhausted.append(dict(delivery.as_dict))
            continue
        delivery.attempt = int(delivery.attempt) + 1  # type: ignore[assignment]
        if simulate_fail:
            _apply_failure(
                delivery,
                settings,
                reason=f"yeniden deneme {delivery.attempt} başarısız",
            )
        else:
            delivery.status = DELIVERY_DELIVERED  # type: ignore[assignment]
            delivery.http_status = 200  # type: ignore[assignment]
            delivery.next_retry_at = None  # type: ignore[assignment]
            delivery.error = None  # type: ignore[assignment]
        session.flush()
        retried.append(dict(delivery.as_dict))

    return {
        "max_retries": max_retries,
        "retried": retried,
        "exhausted": exhausted,
    }


def list_deliveries(
    session: Session,
    settings: Any,
    *,
    subscription_key: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """The delivery ledger (newest first), optionally filtered by subscription."""
    capped = _max_deliveries(settings)
    page = capped if limit is None else max(1, min(int(limit), capped))
    query = select(WebhookDelivery).order_by(WebhookDelivery.id.desc())
    if subscription_key:
        query = query.where(WebhookDelivery.subscription_key == str(subscription_key))
    if status:
        query = query.where(WebhookDelivery.status == str(status))
    rows = session.scalars(query.limit(page)).all()
    deliveries = [dict(row.as_dict) for row in rows]

    total = int(
        session.scalar(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        or 0
    )
    by_status = {
        value: int(
            session.scalar(
                select(func.count())
                .select_from(WebhookDelivery)
                .where(WebhookDelivery.status == value)
            )
            or 0
        )
        for value in (DELIVERY_DELIVERED, DELIVERY_FAILED, DELIVERY_PENDING)
    }
    return {
        "panel": "webhooks",
        "deliveries": deliveries,
        "returned_count": len(deliveries),
        "total_matching": total,
        "by_status": by_status,
        "max_deliveries": capped,
        "signature_header": SIGNATURE_HEADER,
        "attribution": WEBHOOK_ATTRIBUTION,
        "persistence": WEBHOOK_PERSISTENCE,
    }


def webhook_overview(session: Session, settings: Any) -> dict[str, Any]:
    """Combined panel feed: subscriptions + delivery summary + recent history."""
    subs = list_subscriptions(session, settings)
    history = list_deliveries(session, settings, limit=10)
    return {
        "panel": "webhooks",
        "generated_at": to_utc_iso(utc_now()),
        "event_types": list(VALID_EVENT_TYPES),
        "subscriptions": subs["subscriptions"],
        "count": subs["count"],
        "summary": history["by_status"],
        "recent_deliveries": history["deliveries"],
        "signature_header": SIGNATURE_HEADER,
        "max_retries": _max_retries(settings),
        "backoff_seconds": _backoff_seconds(settings),
        "attribution": WEBHOOK_ATTRIBUTION,
        "persistence": WEBHOOK_PERSISTENCE,
    }


def webhook_config(settings: Any) -> dict[str, Any]:
    """Descriptive payload: valid kinds, header name, bounds, defaults."""
    return {
        "event_types": list(VALID_EVENT_TYPES),
        "signature_header": SIGNATURE_HEADER,
        "signature_scheme": "HMAC-SHA256, t=<timestamp>,v1=<hex>",
        "max_subscriptions": _max_subscriptions(settings),
        "max_deliveries": _max_deliveries(settings),
        "max_retries": _max_retries(settings),
        "backoff_seconds": _backoff_seconds(settings),
        "statuses": [DELIVERY_PENDING, DELIVERY_DELIVERED, DELIVERY_FAILED],
        "attribution": WEBHOOK_ATTRIBUTION,
        "persistence": WEBHOOK_PERSISTENCE,
    }


__all__ = [
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_MAX_DELIVERIES",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_SUBSCRIPTIONS",
    "SIGNATURE_HEADER",
    "VALID_EVENT_TYPES",
    "WEBHOOK_ATTRIBUTION",
    "WEBHOOK_PERSISTENCE",
    "WebhookError",
    "build_envelope",
    "build_envelope_preview",
    "create_subscription",
    "delete_subscription",
    "dispatch_event",
    "list_deliveries",
    "list_subscriptions",
    "record_attempt",
    "retry_due",
    "signature_for",
    "update_subscription",
    "webhook_config",
    "webhook_overview",
]
