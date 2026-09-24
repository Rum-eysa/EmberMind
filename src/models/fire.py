"""NASA FIRMS active-fire persistence models."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from .base import BaseModel


class FireCluster(BaseModel):
    """A group of nearby FIRMS observations representing one fire event."""

    __tablename__ = "fire_clusters"

    cluster_key = Column(String(64), unique=True, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    observation_count = Column(Integer, nullable=False, default=0)
    max_frp = Column(Float)
    first_seen_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=False, index=True)
    source = Column(String(32), nullable=False, default="NASA FIRMS")

    @property
    def as_dict(self):
        """Return the cluster in API-friendly JSON-compatible form."""
        return {
            "cluster_key": self.cluster_key,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "observation_count": self.observation_count,
            "max_frp": self.max_frp,
            "first_seen_at": self.first_seen_at.isoformat() + "Z",
            "last_seen_at": self.last_seen_at.isoformat() + "Z",
        }


class FireObservation(BaseModel):
    """One normalized active-fire detection received from NASA FIRMS."""

    __tablename__ = "fire_observations"

    source_id = Column(String(64), unique=True, nullable=False, index=True)
    cluster_key = Column(String(64), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    observed_at = Column(DateTime, nullable=False, index=True)
    frp = Column(Float)
    confidence = Column(Float)
    satellite = Column(String(32))
    instrument = Column(String(32))
    source = Column(String(32), nullable=False, default="NASA FIRMS")

    @property
    def as_dict(self):
        """Return the observation in API-friendly JSON-compatible form."""
        return {
            "source_id": self.source_id,
            "cluster_key": self.cluster_key,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "observed_at": self.observed_at.isoformat() + "Z",
            "frp": self.frp,
            "confidence": self.confidence,
            "satellite": self.satellite,
            "instrument": self.instrument,
        }


class FirmsSyncStatus(BaseModel):
    """Operational status of the FIRMS ingestion source."""

    __tablename__ = "firms_sync_status"

    source = Column(String(32), unique=True, nullable=False)
    last_success_at = Column(DateTime)
    last_error_at = Column(DateTime)
    last_error = Column(String(500))
    last_observation_count = Column(Integer, nullable=False, default=0)
