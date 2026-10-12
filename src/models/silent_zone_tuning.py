"""Per-region silent-zone sensitivity and threshold tuning (EM-044, Epic E4).

EM-035 learns one global silence z-score and EM-040 alerts on one global ladder,
but "how quiet counts as silent" and "how long before we ping the operator" are
precisely the false-alarm vs. miss trade-off an operator owns *per region*
(EM-044 acceptance: "eşik ve minimum sessizlik süresi arayüzden ayarlanır;
değişiklik denetim kaydına yazılır; varsayılana dönme seçeneği vardır").

This table stores one *override* row per region. Only the knobs the operator
actually changes are kept; a ``NULL`` column means "inherit the global default",
so a reset-to-default simply clears (or drops) the row. The change itself is
recorded in the unified ``audit_trail`` ledger under the ``threshold`` domain -
this table holds the current setting, the ledger holds the who/when/old→new.
"""
from typing import Any

from sqlalchemy import Column, Float, Integer, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class SilentZoneTuning(BaseModel):
    """One region's persisted override of the silent-zone detection knobs."""

    __tablename__ = "silent_zone_tuning"

    tuning_key = Column(String(64), unique=True, nullable=False, index=True)
    # One override per silent region (FK to silent_regions.id, kept loose).
    region_id = Column(Integer, unique=True, nullable=False, index=True)
    # z-score magnitude below which a cell counts as silent (EM-035 semantics);
    # ``NULL`` inherits the global sensitivity.
    sensitivity_z = Column(Float, nullable=True)
    # Minimum hours a region must stay silent before EM-040 alerts on it;
    # ``NULL`` inherits the global minimum.
    min_silence_hours = Column(Float, nullable=True)
    updated_by = Column(String(64), nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return an API-friendly representation of the override row."""
        return {
            "id": self.id,
            "tuning_key": self.tuning_key,
            "region_id": self.region_id,
            "sensitivity_z": self.sensitivity_z,
            "min_silence_hours": self.min_silence_hours,
            "updated_by": self.updated_by,
            "created_at": to_utc_iso(self.created_at),
            "updated_at": to_utc_iso(self.updated_at),
        }
