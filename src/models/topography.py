"""USGS/SRTM topography (elevation, slope, aspect) persistence models."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from .base import BaseModel


class TopographyDataPoint(BaseModel):
    """Topography data point (elevation, slope, aspect) at 30m resolution."""

    __tablename__ = "topography_data_points"

    cluster_key = Column(String(64), index=True, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    elevation = Column(Float, nullable=False)  # Meters above sea level
    slope = Column(Float, nullable=False)  # Slope in degrees (0 - 90°)
    aspect = Column(
        Float, nullable=False
    )  # Aspect in degrees (0 - 360°, N=0, E=90, S=180, W=270)
    resolution_meters = Column(Integer, nullable=False, default=30)
    fetched_at = Column(DateTime, nullable=False, index=True)
    source = Column(String(64), nullable=False, default="USGS/SRTM")

    @property
    def as_dict(self) -> dict:
        """Return the topography data point in API-friendly JSON-compatible form."""
        return {
            "id": self.id,
            "cluster_key": self.cluster_key,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation": self.elevation,
            "slope": self.slope,
            "aspect": self.aspect,
            "resolution_meters": self.resolution_meters,
            "fetched_at": self.fetched_at.isoformat() + "Z",
            "source": self.source,
        }
