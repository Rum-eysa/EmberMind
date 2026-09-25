"""Road network models (OpenStreetMap import, closures, crew bases)."""
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class RoadSegment(BaseModel):
    """A directed road link imported from the OpenStreetMap network."""

    __tablename__ = "road_segments"

    segment_key = Column(String(96), unique=True, nullable=False, index=True)
    osm_way_id = Column(Integer, nullable=False, index=True)
    from_node_id = Column(Integer, nullable=False, index=True)
    to_node_id = Column(Integer, nullable=False, index=True)
    from_lat = Column(Float, nullable=False)
    from_lon = Column(Float, nullable=False)
    to_lat = Column(Float, nullable=False)
    to_lon = Column(Float, nullable=False)
    name = Column(String(128), nullable=True)
    highway = Column(String(64), nullable=False, default="unclassified")
    length_km = Column(Float, nullable=False, default=0.0)
    max_speed_kmh = Column(Float, nullable=False, default=50.0)
    one_way = Column(Boolean, nullable=False, default=False)
    fetched_at = Column(DateTime, nullable=False, index=True)
    source = Column(String(64), nullable=False, default="OpenStreetMap")

    __table_args__ = (
        Index("idx_road_segments_endpoints", "from_node_id", "to_node_id"),
        Index(
            "idx_road_segments_spatial",
            "from_lat",
            "to_lat",
            "from_lon",
            "to_lon",
        ),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "segment_key": self.segment_key,
            "osm_way_id": self.osm_way_id,
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "from_lat": self.from_lat,
            "from_lon": self.from_lon,
            "to_lat": self.to_lat,
            "to_lon": self.to_lon,
            "name": self.name,
            "highway": self.highway,
            "length_km": self.length_km,
            "max_speed_kmh": self.max_speed_kmh,
            "one_way": self.one_way,
            "fetched_at": to_utc_iso(self.fetched_at),
            "source": self.source,
        }


class RoadClosure(BaseModel):
    """A closure marker on a road segment (drives route recalculation, E6 linked)."""

    __tablename__ = "road_closures"

    segment_key = Column(String(96), nullable=False, index=True)
    osm_way_id = Column(Integer, nullable=True)
    reason = Column(String(256), nullable=False, default="unspecified")
    status = Column(String(32), nullable=False, default="active")
    reported_by = Column(String(128), nullable=True)
    reported_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_road_closures_segment_status", "segment_key", "status"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "segment_key": self.segment_key,
            "osm_way_id": self.osm_way_id,
            "reason": self.reason,
            "status": self.status,
            "reported_by": self.reported_by,
            "reported_at": to_utc_iso(self.reported_at),
            "resolved_at": to_utc_iso(self.resolved_at),
        }


class CrewBase(BaseModel):
    """A firefighting crew station used as a routing origin."""

    __tablename__ = "crew_bases"

    base_key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    crew_type = Column(String(64), nullable=False, default="first_response")
    available = Column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("idx_crew_bases_coords", "latitude", "longitude"),)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "base_key": self.base_key,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "crew_type": self.crew_type,
            "available": self.available,
        }
