"""Capacity unit assumptions persistence (EM-028, Epic E3).

One row per deployable resource type holding the admin-editable "effective
suppression capacity" (hectare/hour) assumed for a single unit of that type.
Normalising every resource to a common ha/hour unit is what lets capacity and
risk be measured in the same unit so the capacity-gap index is meaningful. The
rows are seeded from config defaults and stay editable at runtime by an
administrator through the panel.
"""
from typing import Any

from sqlalchemy import Column, Float, String

from .base import BaseModel


class CapacityAssumption(BaseModel):
    """Effective suppression capacity (ha/hour) assumed per resource type."""

    __tablename__ = "capacity_assumptions"

    resource_type = Column(String(32), unique=True, nullable=False, index=True)
    ha_per_hour = Column(Float, nullable=False, default=0.0)
    updated_by = Column(String(64), nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "resource_type": self.resource_type,
            "ha_per_hour": float(self.ha_per_hour),
            "updated_by": self.updated_by,
        }
