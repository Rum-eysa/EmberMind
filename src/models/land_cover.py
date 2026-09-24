"""CORINE Land Cover & fuel class conversion persistence models."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from .base import BaseModel


class LandCoverDataPoint(BaseModel):
    """Land cover classification and mapped fire fuel model data point."""

    __tablename__ = "land_cover_data_points"

    cluster_key = Column(String(64), index=True, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    corine_code = Column(Integer, nullable=True)
    land_cover_class = Column(
        String(64), nullable=False, default="bilinmiyor"
    )  # e.g., kızılçam, karma orman, maki, tarım/zeytin, bilinmiyor
    fuel_model = Column(
        String(64), nullable=False, default="varsayilan"
    )  # e.g., FM10_RedPine, FM8_MixedForest, FM4_Maquis, FM1_Agriculture, varsayilan
    spread_factor = Column(Float, nullable=False, default=1.0)
    fetched_at = Column(DateTime, nullable=False, index=True)
    source = Column(String(64), nullable=False, default="CORINE/LandCover")

    @property
    def as_dict(self) -> dict:
        """Return the land cover data point in API-friendly JSON-compatible form."""
        return {
            "id": self.id,
            "cluster_key": self.cluster_key,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "corine_code": self.corine_code,
            "land_cover_class": self.land_cover_class,
            "fuel_model": self.fuel_model,
            "spread_factor": self.spread_factor,
            "fetched_at": self.fetched_at.isoformat() + "Z",
            "source": self.source,
        }
