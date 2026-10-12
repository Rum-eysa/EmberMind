"""Event & alert webhook subscriptions and delivery ledger (EM-094, Epic E9).

An integrator wants the system to *push* events and alerts to a downstream
service the moment they happen, instead of polling the live feed (EM-090) or the
notification centre (EM-086). EM-094 acceptance is exactly that contract:
configurable webhook URL + event types, a **signed** request with **retry**
support, and a **viewable delivery history**.

Two small persisted surfaces model it deterministically:

* :class:`WebhookSubscription` - one outbound endpoint the integrator registers:
  where to send (``url``), *which* live-feed kinds interest it (``event_types``),
  a shared ``secret`` used to HMAC-sign every request, and an ``enabled`` flag so
  a target can be paused without deleting its history.
* :class:`WebhookDelivery` - the append-only ledger of every attempt made for a
  subscription against one feed event. It records the exact body that was signed
  and (would be) posted, the signature header, the outcome, the attempt number
  and the next-retry timestamp - so "what was sent, to whom, did it stick, and
  when do we retry" is fully auditable.

Both tables are purely additive. The delivery transport itself (the real HTTPS
POST to a third party) is intentionally **not** performed here: like EM-069, a
live network send is never mocked as "delivered". The ledger is the durable
record of the signed request and its retry policy; an explicit ``outcome`` lets
a caller log a real success/failure once a transport is wired in.
"""
from typing import Any

from sqlalchemy import Column, Index, Integer, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# The outbound lifecycle of one delivery attempt.
DELIVERY_PENDING = "pending"
DELIVERY_DELIVERED = "delivered"
DELIVERY_FAILED = "failed"
DELIVERY_STATUSES = (DELIVERY_PENDING, DELIVERY_DELIVERED, DELIVERY_FAILED)


def parse_event_types(raw: Any) -> list[str]:
    """Normalise a stored/comma-joined ``event_types`` value into a list."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts = [str(item) for item in raw]
    else:
        parts = str(raw).split(",")
    return [part.strip() for part in parts if part and part.strip()]


class WebhookSubscription(BaseModel):
    """One registered outbound webhook endpoint and the events it wants."""

    __tablename__ = "webhook_subscriptions"

    subscription_key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    url = Column(String(300), nullable=False)
    # Comma-separated subset of the live-feed kinds (fire_event/forecast/alert).
    event_types = Column(String(200), nullable=False, default="")
    # Shared secret used to HMAC-sign each request body (never echoed in API).
    secret = Column(String(128), nullable=False, default="")
    enabled = Column(Integer, nullable=False, default=1)

    @property
    def as_dict(self) -> dict[str, Any]:
        """API view of a subscription; the signing secret is redacted."""
        return {
            "id": self.id,
            "subscription_key": self.subscription_key,
            "name": self.name,
            "url": self.url,
            "event_types": parse_event_types(self.event_types),
            "enabled": bool(self.enabled),
            "has_secret": bool(self.secret),
            "created_at": to_utc_iso(self.created_at),
            "updated_at": to_utc_iso(self.updated_at),
        }


class WebhookDelivery(BaseModel):
    """One signed delivery attempt for a subscription against a feed event."""

    __tablename__ = "webhook_deliveries"

    delivery_key = Column(String(64), unique=True, nullable=False, index=True)
    # Denormalised endpoint snapshot so history survives subscription edits.
    subscription_id = Column(Integer, nullable=False, index=True)
    subscription_key = Column(String(64), nullable=False, index=True)
    url = Column(String(300), nullable=False)
    # The originating live-feed row + its kind, for traceability.
    live_update_id = Column(Integer, nullable=True, index=True)
    event_type = Column(String(32), nullable=False, index=True)
    event_key = Column(String(64), nullable=True)
    # The exact JSON body that was signed / (would be) posted.
    request_body = Column(Text, nullable=False, default="")
    # The signature header value (hex HMAC of "<timestamp>.<body>").
    signature = Column(String(120), nullable=False, default="")
    timestamp_header = Column(String(40), nullable=False, default="")
    status = Column(String(16), nullable=False, default=DELIVERY_PENDING, index=True)
    http_status = Column(Integer, nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    next_retry_at = Column(String(32), nullable=True)
    error = Column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_webhook_deliveries_sub_status", "subscription_id", "status"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """API view of one delivery attempt (history row)."""
        return {
            "id": self.id,
            "delivery_key": self.delivery_key,
            "subscription_id": self.subscription_id,
            "subscription_key": self.subscription_key,
            "url": self.url,
            "live_update_id": self.live_update_id,
            "event_type": self.event_type,
            "event_key": self.event_key,
            "request_body": self.request_body,
            "signature": self.signature,
            "timestamp_header": self.timestamp_header,
            "status": self.status,
            "http_status": self.http_status,
            "attempt": self.attempt,
            "next_retry_at": self.next_retry_at,
            "error": self.error,
            "created_at": to_utc_iso(self.created_at),
        }
