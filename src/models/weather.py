"""OpenWeather forecast persistence models."""
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class WeatherDataPoint(BaseModel):
    """Weather condition & forecast data point for a specific location."""

    __tablename__ = "weather_data_points"

    cluster_key = Column(String(64), index=True, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    temperature = Column(Float, nullable=False)
    humidity = Column(Float, nullable=False)
    wind_speed = Column(Float, nullable=False)
    wind_deg = Column(Float, nullable=False)
    forecast_offset_hours = Column(Integer, nullable=False, default=0)
    forecast_time = Column(DateTime, nullable=False, index=True)
    fetched_at = Column(DateTime, nullable=False, index=True)
    source = Column(String(64), nullable=False, default="OpenWeatherMap")

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return the weather data point in API-friendly JSON-compatible form."""
        return {
            "id": self.id,
            "cluster_key": self.cluster_key,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "wind_speed": self.wind_speed,
            "wind_deg": self.wind_deg,
            "forecast_offset_hours": self.forecast_offset_hours,
            "forecast_time": to_utc_iso(self.forecast_time),
            "fetched_at": to_utc_iso(self.fetched_at),
            "source": self.source,
        }
