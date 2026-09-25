"""Fire Weather Index (FWI) and drought indicator persistence per zone."""
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, UniqueConstraint

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class FireWeatherIndex(BaseModel):
    """One day of FWI components and drought indicator for an analysis zone."""

    __tablename__ = "fire_weather_index"
    __table_args__ = (UniqueConstraint("zone_key", "day", name="uq_fwi_zone_day"),)

    zone_key = Column(String(32), index=True, nullable=False)
    region_name = Column(String(64), nullable=False, default="")
    day = Column(Date, index=True, nullable=False)

    center_lat = Column(Float, nullable=False, default=0.0)
    center_lon = Column(Float, nullable=False, default=0.0)
    min_lat = Column(Float, nullable=False, default=0.0)
    min_lon = Column(Float, nullable=False, default=0.0)
    max_lat = Column(Float, nullable=False, default=0.0)
    max_lon = Column(Float, nullable=False, default=0.0)

    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)
    rain = Column(Float, nullable=True)

    ffmc = Column(Float, nullable=False, default=0.0)
    dmc = Column(Float, nullable=False, default=0.0)
    dc = Column(Float, nullable=False, default=0.0)
    isi = Column(Float, nullable=False, default=0.0)
    bui = Column(Float, nullable=False, default=0.0)
    fwi = Column(Float, nullable=False, default=0.0, index=True)
    risk_category = Column(String(16), nullable=False, default="very_low")
    drought_category = Column(String(16), nullable=False, default="no_drought")
    data_point_count = Column(Integer, nullable=False, default=0)
    computed_at = Column(DateTime, nullable=True)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return the zone FWI profile in API-friendly JSON-compatible form."""
        return {
            "id": self.id,
            "zone_key": self.zone_key,
            "region_name": self.region_name,
            "day": self.day.isoformat() if self.day is not None else None,
            "center_lat": self.center_lat,
            "center_lon": self.center_lon,
            "bounding_box": {
                "min_latitude": self.min_lat,
                "min_longitude": self.min_lon,
                "max_latitude": self.max_lat,
                "max_longitude": self.max_lon,
            },
            "temperature": self.temperature,
            "humidity": self.humidity,
            "wind_speed": self.wind_speed,
            "rain": self.rain,
            "ffmc": self.ffmc,
            "dmc": self.dmc,
            "dc": self.dc,
            "isi": self.isi,
            "bui": self.bui,
            "fwi": self.fwi,
            "risk_category": self.risk_category,
            "drought_category": self.drought_category,
            "data_point_count": self.data_point_count,
            "computed_at": to_utc_iso(self.computed_at)
            if isinstance(self.computed_at, datetime)
            else None,
        }
