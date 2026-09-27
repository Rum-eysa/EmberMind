"""Exposed-asset persistence for threat/exposure analysis (EM-023, Epic E2).

Settlements and energy lines imported from OpenStreetMap that the commander
wants protected or evacuated first. Roads are *not* duplicated here — the
exposure analysis reads them straight from ``road_segments`` (EM-011). Each
row keeps a representative point (for the map popup and sorting) plus the full
WKT geometry (a ``POINT`` for settlements, a ``LINESTRING`` for power lines) so
it can be intersected with the spread-forecast horizon polygons.
"""
from typing import Any

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel

# Canonical asset vocabularies shared by the service, routes and importer.
ASSET_TYPES = ("settlement", "power_line", "road")
SETTLEMENT_PLACE_CLASSES = (
    "city",
    "town",
    "village",
    "hamlet",
    "suburb",
    "neighbourhood",
    "quarter",
    "isolated_dwelling",
)


class ExposedAsset(BaseModel):
    """A settlement or energy line that can be threatened by a forecast."""

    __tablename__ = "exposed_assets"

    asset_key = Column(String(96), unique=True, nullable=False, index=True)
    asset_type = Column(String(32), nullable=False, index=True)
    name = Column(String(160), nullable=True)
    osm_id = Column(Integer, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    min_lat = Column(Float, nullable=False)
    max_lat = Column(Float, nullable=False)
    min_lon = Column(Float, nullable=False)
    max_lon = Column(Float, nullable=False)
    geometry_wkt = Column(Text, nullable=False)
    tags_json = Column(Text, nullable=True)
    source = Column(String(64), nullable=False, default="OpenStreetMap")
    fetched_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "idx_exposed_assets_spatial",
            "min_lat",
            "max_lat",
            "min_lon",
            "max_lon",
        ),
        Index("idx_exposed_assets_type", "asset_type"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "asset_key": self.asset_key,
            "asset_type": self.asset_type,
            "name": self.name,
            "osm_id": self.osm_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "geometry_wkt": self.geometry_wkt,
            "tags_json": self.tags_json,
            "source": self.source,
            "fetched_at": to_utc_iso(self.fetched_at),
        }
