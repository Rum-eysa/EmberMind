"""Spatial database models (PostGIS/SQLite RTree compatible) for events, forecasts, sources, silent regions, and scenarios."""
from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String

from .base import BaseModel


class FireEvent(BaseModel):
    """Wildfire event entity (Olay)."""

    __tablename__ = "fire_events"

    event_key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    min_lat = Column(Float, nullable=False)
    max_lat = Column(Float, nullable=False)
    min_lon = Column(Float, nullable=False)
    max_lon = Column(Float, nullable=False)
    geometry_wkt = Column(String(512), nullable=False)
    severity = Column(String(32), nullable=False, default="medium")
    status = Column(String(32), nullable=False, default="active")
    started_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index(
            "idx_fire_events_spatial",
            "min_lat",
            "max_lat",
            "min_lon",
            "max_lon",
        ),
        Index("idx_fire_events_coords", "latitude", "longitude"),
    )

    @property
    def as_dict(self) -> dict:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "event_key": self.event_key,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
            "geometry_wkt": self.geometry_wkt,
            "severity": self.severity,
            "status": self.status,
            "started_at": self.started_at.isoformat() + "Z",
        }


class FireForecast(BaseModel):
    """Wildfire forecast entity (Tahmin)."""

    __tablename__ = "fire_forecasts"

    event_key = Column(String(64), nullable=False, index=True)
    model_name = Column(String(64), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    predicted_area_ha = Column(Float, nullable=False, default=0.0)
    geometry_wkt = Column(String(512), nullable=False)
    forecast_for = Column(DateTime, nullable=False)

    __table_args__ = (Index("idx_fire_forecasts_spatial", "latitude", "longitude"),)

    @property
    def as_dict(self) -> dict:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "event_key": self.event_key,
            "model_name": self.model_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "predicted_area_ha": self.predicted_area_ha,
            "geometry_wkt": self.geometry_wkt,
            "forecast_for": self.forecast_for.isoformat() + "Z",
        }


class SpatialSource(BaseModel):
    """Geographic data source entity (Kaynak)."""

    __tablename__ = "spatial_sources"

    source_name = Column(String(64), unique=True, nullable=False)
    source_type = Column(String(32), nullable=False)
    min_lat = Column(Float, nullable=False)
    max_lat = Column(Float, nullable=False)
    min_lon = Column(Float, nullable=False)
    max_lon = Column(Float, nullable=False)
    geometry_wkt = Column(String(512), nullable=False)
    last_synced_at = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False, default="active")

    __table_args__ = (
        Index(
            "idx_spatial_sources_spatial",
            "min_lat",
            "max_lat",
            "min_lon",
            "max_lon",
        ),
    )

    @property
    def as_dict(self) -> dict:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
            "geometry_wkt": self.geometry_wkt,
            "last_synced_at": self.last_synced_at.isoformat() + "Z"
            if self.last_synced_at
            else None,
            "status": self.status,
        }


class SilentRegion(BaseModel):
    """Silent / blackout zone entity (Sessiz Bölge)."""

    __tablename__ = "silent_regions"

    region_name = Column(String(128), nullable=False)
    reason = Column(String(256), nullable=False)
    min_lat = Column(Float, nullable=False)
    max_lat = Column(Float, nullable=False)
    min_lon = Column(Float, nullable=False)
    max_lon = Column(Float, nullable=False)
    geometry_wkt = Column(String(512), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index(
            "idx_silent_regions_spatial",
            "min_lat",
            "max_lat",
            "min_lon",
            "max_lon",
        ),
    )

    @property
    def as_dict(self) -> dict:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "region_name": self.region_name,
            "reason": self.reason,
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
            "geometry_wkt": self.geometry_wkt,
            "is_active": self.is_active,
        }


class SimulationScenario(BaseModel):
    """Wildfire simulation scenario entity (Senaryo)."""

    __tablename__ = "simulation_scenarios"

    scenario_name = Column(String(128), nullable=False)
    event_key = Column(String(64), nullable=False)
    min_lat = Column(Float, nullable=False)
    max_lat = Column(Float, nullable=False)
    min_lon = Column(Float, nullable=False)
    max_lon = Column(Float, nullable=False)
    geometry_wkt = Column(String(512), nullable=False)
    wind_speed = Column(Float, nullable=False, default=0.0)
    slope_angle = Column(Float, nullable=False, default=0.0)
    fuel_model = Column(String(64), nullable=False, default="varsayilan")
    simulated_area_ha = Column(Float, nullable=False, default=0.0)

    __table_args__ = (
        Index(
            "idx_simulation_scenarios_spatial",
            "min_lat",
            "max_lat",
            "min_lon",
            "max_lon",
        ),
    )

    @property
    def as_dict(self) -> dict:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "scenario_name": self.scenario_name,
            "event_key": self.event_key,
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
            "geometry_wkt": self.geometry_wkt,
            "wind_speed": self.wind_speed,
            "slope_angle": self.slope_angle,
            "fuel_model": self.fuel_model,
            "simulated_area_ha": self.simulated_area_ha,
        }
