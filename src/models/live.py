"""Live-update change feed ORM model (EM-090).

A monotonic log of operator-relevant changes — fire events, spread forecasts
and risk alerts — that the WebSocket endpoint streams to connected clients so
the operator map refreshes without a page reload. The autoincrement ``id``
doubles as the sequence number: a reconnecting client sends the last ``id`` it
saw (``since=<id>``) and only receives what it missed.
"""
import json
from typing import Any

from sqlalchemy import Column, Index, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# The three operator-facing update kinds the feed may carry.
LIVE_KINDS = ("fire_event", "forecast", "alert")


class LiveUpdate(BaseModel):
    """One entry in the live change feed (newest = highest ``id``)."""

    __tablename__ = "live_updates"

    kind = Column(String(32), nullable=False, index=True)
    event_key = Column(String(64), nullable=True, index=True)
    title = Column(String(200), nullable=True)
    message = Column(String(500), nullable=True)
    payload_json = Column(Text, nullable=True)
    source = Column(String(64), nullable=True)

    __table_args__ = (Index("idx_live_updates_kind_id", "kind", "id"),)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return an API/WebSocket-friendly dictionary representation."""
        payload: Any = None
        if self.payload_json:
            try:
                payload = json.loads(str(self.payload_json))
            except (ValueError, TypeError):
                payload = None
        return {
            "id": self.id,
            "kind": self.kind,
            "event_key": self.event_key,
            "title": self.title,
            "message": self.message,
            "payload": payload,
            "source": self.source,
            "created_at": to_utc_iso(self.created_at),
        }
