"""UI-authored custom demo scenarios (EM-108, Epic E11).

EM-105 ships a *code-constant* library of curated archetypes; the demo host also
wants to author a brand-new scenario from the interface without writing code
(EM-108 acceptance: "fire location, wind history and exclusion zones are entered
through the UI; the scenario is saved and added to the library; input validation
is enforced"). This table stores one authored scenario *definition* per row: a
slug key, a display title, a deterministic seed and the EM-104 scenario config.

The stored ``config_json`` is the **normalized** config (the EM-104
``normalize_config`` output, merged over the defaults and validated), so an
activation is byte-reproducible and independent of any later change to
``DEFAULT_CONFIG``. Launching a custom scenario reuses the exact EM-104/EM-105
path (``build_dataset`` + ``persist_dataset`` + one ``ScenarioRun`` audit row
stamped ``preset=custom:<key>``) — no operational row is invented here. The only
persisted artefact of *this* feature is the definition row.
"""
from typing import Any

from sqlalchemy import Column, Integer, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class CustomScenario(BaseModel):
    """One authored demo scenario definition (validated EM-104 config)."""

    __tablename__ = "custom_scenarios"

    scenario_key = Column(String(64), unique=True, nullable=False, index=True)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    seed = Column(Integer, nullable=False)
    # The normalized (validated) EM-104 config, canonical JSON.
    config_json = Column(Text, nullable=False)
    archetype = Column(String(48), nullable=False, default="custom")
    created_by = Column(String(64), nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Lightweight API view of the definition (config omitted on purpose)."""
        return {
            "id": self.id,
            "key": self.scenario_key,
            "title": self.title,
            "description": self.description,
            "seed": int(self.seed),
            "archetype": self.archetype,
            "created_by": self.created_by,
            "created_at": to_utc_iso(self.created_at),
            "updated_at": to_utc_iso(self.updated_at),
        }
