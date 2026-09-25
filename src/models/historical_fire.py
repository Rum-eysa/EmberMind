"""Historical fire perimeter model (EFFIS import for calibration/validation)."""
import json
from typing import Any

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text

from .base import BaseModel


class HistoricalFirePerimeter(BaseModel):
    """A past EFFIS fire perimeter, stored separately for model calibration/validation."""

    __tablename__ = "historical_fire_perimeters"

    perimeter_key = Column(String(96), unique=True, nullable=False, index=True)
    effis_objectid = Column(Integer, nullable=False, index=True)
    fire_year = Column(Integer, nullable=False, index=True)
    country_code = Column(String(8), nullable=True)
    country = Column(String(64), nullable=True)
    national_code = Column(String(64), nullable=True)
    date_start = Column(DateTime, nullable=True)
    date_end = Column(DateTime, nullable=True)
    area_km2 = Column(Float, nullable=False, default=0.0)
    mmi_level = Column(String(16), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geometry_json = Column(Text, nullable=False, default="{}")
    split = Column(String(16), nullable=True, index=True)
    source = Column(String(32), nullable=False, default="EFFIS")
    fetched_at = Column(DateTime, nullable=False, index=True)

    __table_args__ = (
        Index("idx_hist_fires_year_country", "fire_year", "country_code"),
        Index("idx_hist_fires_split", "split", "fire_year"),
        Index("idx_hist_fires_centroid", "latitude", "longitude"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation with parsed geometry."""
        try:
            geometry = json.loads(str(self.geometry_json or "{}"))
        except (TypeError, ValueError):
            geometry = {}
        return {
            "id": self.id,
            "perimeter_key": self.perimeter_key,
            "effis_objectid": self.effis_objectid,
            "fire_year": self.fire_year,
            "country_code": self.country_code,
            "country": self.country,
            "national_code": self.national_code,
            "date_start": self.date_start.isoformat() + "Z"
            if self.date_start
            else None,
            "date_end": self.date_end.isoformat() + "Z" if self.date_end else None,
            "area_km2": self.area_km2,
            "mmi_level": self.mmi_level,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "geometry": geometry,
            "split": self.split,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat() + "Z"
            if self.fetched_at
            else None,
        }
