"""Suppression resource inventory persistence (EM-103, Epic E11).

Deployable suppression units — ground crews, helicopters and UAVs (İHA) —
each with a location, home base, country, operational status and a numeric
capacity. This inventory is the coordinator-managed source of truth that keeps
the capacity picture current; it is separate from ``crew_bases`` (which are
road-network routing origins).
"""
from typing import Any

from sqlalchemy import Column, Float, Index, String

from .base import BaseModel

# Canonical vocabularies shared by the service, routes and CSV importer.
RESOURCE_TYPES = ("crew", "helicopter", "uav")
# EM-031: "en_route" (yolda) is a transient committed-but-not-on-station
# status; only "available" counts toward effective suppression capacity.
RESOURCE_STATUSES = (
    "available",
    "deployed",
    "en_route",
    "maintenance",
    "out_of_service",
)


class SuppressionResource(BaseModel):
    """A single managed suppression asset in the coordinator inventory."""

    __tablename__ = "suppression_resources"

    resource_key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    resource_type = Column(String(32), nullable=False, default="crew")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    base_key = Column(String(64), nullable=True, index=True)
    country = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="available")
    capacity = Column(Float, nullable=False, default=0.0)
    capacity_unit = Column(String(24), nullable=True)

    __table_args__ = (
        Index("idx_suppression_resources_type_status", "resource_type", "status"),
        Index("idx_suppression_resources_coords", "latitude", "longitude"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "resource_key": self.resource_key,
            "name": self.name,
            "resource_type": self.resource_type,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "base_key": self.base_key,
            "country": self.country,
            "status": self.status,
            "capacity": self.capacity,
            "capacity_unit": self.capacity_unit,
        }
