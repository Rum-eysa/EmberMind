"""Free-text operator notes on a fire event (EM-089, Epic E8).

At shift handover the operator has to pass on the things the automated feeds
never capture - a road the crew mentioned is passable only for 4x4, a water
point that ran dry, an access agreement with a landowner. The live change feed
(EM-090), the accepted recommendations (EM-047) and the read-time timeline
(EM-081) are all machine-generated; none of them gives the operator a way to
type a note against an incident and have it survive the shift, and none of them
produces the "hand this over in one click" summary EM-089 asks for.

:class:`EventNote` is the small persisted surface that closes that gap: one
free-text row per note, keyed to an incident's ``event_key`` and stamped with
who wrote it. It deliberately stores *only* the human commentary - the fire
status, risk band and resource roster stay in their own tables and are composed
into the handover summary at read time (see ``services/shift_handover.py``).
The table is purely additive.
"""
from typing import Any

from sqlalchemy import Column, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class EventNote(BaseModel):
    """One free-text operator note attached to a fire event."""

    __tablename__ = "event_notes"

    # Not unique: an incident carries many notes. Indexed for the handover join.
    event_key = Column(String(64), nullable=False, index=True)
    body = Column(Text, nullable=False)
    author = Column(String(128), nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """API-friendly view of one note."""
        return {
            "id": self.id,
            "event_key": self.event_key,
            "body": self.body,
            "author": self.author,
            "created_at": to_utc_iso(self.created_at),
            "updated_at": to_utc_iso(self.updated_at),
        }
