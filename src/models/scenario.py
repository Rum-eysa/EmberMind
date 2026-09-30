"""Saved, shareable operator what-if scenarios (EM-059, Epic E6).

The what-if recomputations (EM-055 wind/weather, EM-056 capacity) are
deliberately ephemeral — they never touch the database. EM-059 adds a thin
persistence layer *on top* so a commander can name a promising scenario, keep it
for a shift hand-over, and share it with the team through a link instead of
re-typing the knobs. A stored scenario is only the *inputs* (kind + params); a
fresh result is always produced by replaying those inputs through the existing
what-if endpoints, so nothing here duplicates the physics or the live data.
"""
import json
from typing import Any

from sqlalchemy import Column, Index, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# A scenario replays through one of the two what-if endpoints.
SCENARIO_KINDS = ("wind", "capacity")


class WhatIfScenario(BaseModel):
    """A named, optionally share-published what-if scenario (inputs only)."""

    __tablename__ = "whatif_scenarios"

    scenario_key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    kind = Column(String(16), nullable=False, index=True)
    event_key = Column(String(64), nullable=True, index=True)
    params_json = Column(Text, nullable=False)
    share_token = Column(String(64), nullable=True, unique=True, index=True)
    created_by = Column(String(64), nullable=True)
    notes = Column(String(255), nullable=True)

    __table_args__ = (Index("idx_whatif_scenarios_kind_key", "kind", "scenario_key"),)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return an API-friendly representation with the decoded params."""
        return {
            "id": self.id,
            "scenario_key": self.scenario_key,
            "name": self.name,
            "kind": self.kind,
            "event_key": self.event_key,
            "params": _decode_params(self.params_json),
            "share_token": self.share_token,
            "shared": bool(self.share_token),
            "created_by": self.created_by,
            "notes": self.notes,
            "created_at": to_utc_iso(self.created_at),
            "updated_at": to_utc_iso(self.updated_at),
        }


def _decode_params(raw: Any) -> dict[str, Any]:
    """Best-effort decode of the stored ``params_json`` into a dict."""
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
