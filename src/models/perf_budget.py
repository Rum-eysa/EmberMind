"""Recompute latency telemetry ORM model (EM-060, Epic E6).

One row per spread/what-if recomputation records how long it took, the
resolution it ran at and the operator budget in force at that moment, so the
p95 recompute latency can be measured over a rolling window and a sustained
breach of the 10-second target can trigger automatic scale-down to a coarser
resolution. The table is a pure append-only telemetry log: it never feeds the
operational picture, only the performance-budget read-out.
"""
from typing import Any

from sqlalchemy import Boolean, Column, Float, String

from .base import BaseModel


class RecomputeLatencySample(BaseModel):
    """Wall-clock duration of one recompute, for the p95 budget window."""

    __tablename__ = "recompute_latency_samples"

    source = Column(String(64), nullable=False, default="recompute", index=True)
    latency_ms = Column(Float, nullable=False, default=0.0)
    target_seconds = Column(Float, nullable=False, default=10.0)
    # "fine" or "coarse": whether the automatic scale-down was active for it.
    resolution = Column(String(16), nullable=False, default="fine")
    # Whether the running p95 over the window was already over budget after
    # this sample landed; lets the breach edge be detected without re-reading.
    breached = Column(Boolean, nullable=False, default=False)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "source": self.source,
            "latency_ms": float(self.latency_ms),
            "target_seconds": float(self.target_seconds),
            "resolution": self.resolution,
            "breached": bool(self.breached),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
