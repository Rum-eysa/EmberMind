"""Audit trail for capacity unit assumption edits (EM-034, Epic E3).

EM-028 made the per-resource-type ha/hour assumption editable at runtime but
only stored the *latest* editor in a single ``updated_by`` column - an
administrator could quietly change crew/helicopter/UAV capacity and there was
no record of the old value, who changed it, or when. EM-034's acceptance
criterion "değişiklik denetim kaydına yazılır" needs a durable history.

One append-only row per *applied* change (a value that actually differs from
the stored one). The current effective assumptions still live in
``capacity_assumptions``; this table never feeds the risk/capacity maths, it
only records who moved which type's ha/hour from what to what. Purely additive.
"""
from typing import Any

from sqlalchemy import Column, Float, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class CapacityAssumptionAudit(BaseModel):
    """Append-only record of one capacity-assumption value change."""

    __tablename__ = "capacity_assumption_audit"

    resource_type = Column(String(32), nullable=False, index=True)
    old_value = Column(Float, nullable=False, default=0.0)
    new_value = Column(Float, nullable=False, default=0.0)
    updated_by = Column(String(64), nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "resource_type": self.resource_type,
            "old_value": float(self.old_value),
            "new_value": float(self.new_value),
            "updated_by": self.updated_by,
            "changed_at": to_utc_iso(self.created_at),
        }
