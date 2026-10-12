"""Joint cross-border early-warning notification (EM-069, Epic E7).

EM-067 *projects* whether a fire can reach the national border; EM-069 turns
that projection into an **action**: when the crossing likelihood and lead time
cross the agreed threshold, a pre-defined coordination channel to the partner
country is fired off, so the neighbour starts its own early warning instead of
being surprised. The notification is written down as a durable dispatch record
(who is told, over which channel, with what message and when), and it is
edge-triggered - one open notification per incident so a recompute never spams
the partner - and auto-resolves once the fire is no longer projected to cross.

The table is **append-only for history** but keeps a mutable ``status`` so the
open -> resolved lifecycle is auditable: the newest *open* row per
``(event_key, target_country)`` deduplicates a repeat dispatch, and resolved
rows stay as the audit trail of what was actually sent.
"""
from typing import Any

from sqlalchemy import Column, Float, Index, Integer, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# Notification lifecycle.
NOTIFICATION_STATUSES = ("open", "resolved")


class CrossborderNotification(BaseModel):
    """One joint early-warning dispatch to the partner coordination unit."""

    __tablename__ = "crossborder_notification"

    notification_key = Column(String(64), unique=True, nullable=False, index=True)
    event_key = Column(String(64), nullable=False, index=True)
    # Owner country the fire sits in, and the partner country being warned.
    source_country = Column(String(2), nullable=False)
    target_country = Column(String(2), nullable=False, index=True)
    likelihood = Column(Float, nullable=False)
    likelihood_level = Column(String(16), nullable=False)
    crossing_minutes = Column(Float, nullable=True)
    within_forecast_window = Column(Integer, nullable=False, default=0)
    # The pre-defined channel + recipient the warning is dispatched over.
    channel = Column(String(64), nullable=False)
    recipient = Column(String(120), nullable=False)
    message = Column(String(255), nullable=False)
    status = Column(String(16), nullable=False, default="open", index=True)
    resolved_at = Column(String(32), nullable=True)

    __table_args__ = (
        Index(
            "idx_xborder_notif_event_target_status",
            "event_key",
            "target_country",
            "status",
        ),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """API-friendly view of one dispatched notification."""
        return {
            "id": self.id,
            "notification_key": self.notification_key,
            "event_key": self.event_key,
            "source_country": self.source_country,
            "target_country": self.target_country,
            "likelihood": self.likelihood,
            "likelihood_level": self.likelihood_level,
            "crossing_minutes": self.crossing_minutes,
            "within_forecast_window": bool(self.within_forecast_window),
            "channel": self.channel,
            "recipient": self.recipient,
            "message": self.message,
            "status": self.status,
            "resolved_at": self.resolved_at,
            "created_at": to_utc_iso(self.created_at),
        }
