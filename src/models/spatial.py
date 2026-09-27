"""Spatial database models for events, forecasts, sources, silent regions,
scenarios and natural barriers (EM-021)."""
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text

from ..utils.timeutils import to_utc_iso
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
    # Text: WKT polygons can exceed the legacy 512-char cap (V015).
    geometry_wkt = Column(Text, nullable=False)
    severity = Column(String(32), nullable=False, default="medium")
    status = Column(String(32), nullable=False, default="active")
    started_at = Column(DateTime, nullable=False)
    source = Column(String(32), nullable=False, default="satellite")
    notes = Column(Text, nullable=True)
    reported_by = Column(String(128), nullable=True)
    reported_at = Column(DateTime, nullable=True)

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
    def as_dict(self) -> dict[str, Any]:
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
            "started_at": to_utc_iso(self.started_at),
            "source": self.source,
            "notes": self.notes,
            "reported_by": self.reported_by,
            "reported_at": to_utc_iso(self.reported_at),
        }


class FireForecast(BaseModel):
    """Wildfire forecast entity (Tahmin)."""

    __tablename__ = "fire_forecasts"

    event_key = Column(String(64), nullable=False, index=True)
    model_name = Column(String(64), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    predicted_area_ha = Column(Float, nullable=False, default=0.0)
    # Text: EM-015 elliptical horizon polygons exceed the legacy 512-char cap.
    geometry_wkt = Column(Text, nullable=False)
    forecast_for = Column(DateTime, nullable=False)
    # EM-015 spread-engine extras (see scripts/migration/V007).
    horizon_minutes = Column(Integer, nullable=False, default=0)
    rate_of_spread_m_per_min = Column(Float, nullable=False, default=0.0)
    spread_direction_deg = Column(Float, nullable=False, default=0.0)
    inputs_json = Column(Text, nullable=True)

    __table_args__ = (Index("idx_fire_forecasts_spatial", "latitude", "longitude"),)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "event_key": self.event_key,
            "model_name": self.model_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "predicted_area_ha": self.predicted_area_ha,
            "geometry_wkt": self.geometry_wkt,
            "forecast_for": to_utc_iso(self.forecast_for),
            "horizon_minutes": self.horizon_minutes,
            "rate_of_spread_m_per_min": self.rate_of_spread_m_per_min,
            "spread_direction_deg": self.spread_direction_deg,
            "inputs_json": self.inputs_json,
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
    # Text: WKT polygons can exceed the legacy 512-char cap (V015).
    geometry_wkt = Column(Text, nullable=False)
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
    def as_dict(self) -> dict[str, Any]:
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
            "last_synced_at": to_utc_iso(self.last_synced_at),
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
    # Text: WKT polygons can exceed the legacy 512-char cap (V015).
    geometry_wkt = Column(Text, nullable=False)
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
    def as_dict(self) -> dict[str, Any]:
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
    # Text: WKT polygons can exceed the legacy 512-char cap (V015).
    geometry_wkt = Column(Text, nullable=False)
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
    def as_dict(self) -> dict[str, Any]:
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


class NaturalBarrier(BaseModel):
    """Water body or partial barrier excluded from spread (EM-021).

    ``slowdown_factor`` 0.0 means the fire cannot cross (sea, lake, wide
    river, non-burnable surface); 0 < factor < 1 models partial obstacles
    like roads and small streams that slow the spread down.
    """

    __tablename__ = "natural_barriers"

    barrier_key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    barrier_type = Column(String(32), nullable=False)
    geometry_wkt = Column(Text, nullable=False)
    slowdown_factor = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, nullable=False, default=True)
    source = Column(String(64), nullable=False, default="operator")
    notes = Column(Text, nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "barrier_key": self.barrier_key,
            "name": self.name,
            "barrier_type": self.barrier_type,
            "geometry_wkt": self.geometry_wkt,
            "slowdown_factor": self.slowdown_factor,
            "is_active": self.is_active,
            "source": self.source,
            "notes": self.notes,
        }
