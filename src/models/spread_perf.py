"""Spread performance benchmark ORM model (EM-022).

Stores before/after optimization timings for the reference scenario so the
10-second recomputation target is evidenced and trackable across model
improvements (linked to E12 observability, like the EM-017 metrics).
"""
import json
from typing import Any

from sqlalchemy import Boolean, Column, Float, Index, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class SpreadPerformanceRun(BaseModel):
    """One benchmark record: baseline vs optimized scenario timings."""

    __tablename__ = "spread_performance_runs"

    run_key = Column(String(64), unique=True, nullable=False, index=True)
    scenario_key = Column(String(64), nullable=False, default="reference_pilot")
    scenario_json = Column(Text, nullable=False, default="{}")
    # Timings with the optimizations switched off / on (ms, best of N).
    baseline_json = Column(Text, nullable=False, default="{}")
    optimized_json = Column(Text, nullable=False, default="{}")
    baseline_total_ms = Column(Float, nullable=False, default=0.0)
    optimized_total_ms = Column(Float, nullable=False, default=0.0)
    speedup = Column(Float, nullable=False, default=1.0)
    target_seconds = Column(Float, nullable=False, default=10.0)
    target_met = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    __table_args__ = (Index("idx_spread_perf_scenario", "scenario_key"),)

    @staticmethod
    def _load(blob: Any) -> dict[str, Any]:
        """Decode one of the JSON columns defensively."""
        try:
            data = json.loads(blob or "{}")
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "run_key": self.run_key,
            "scenario_key": self.scenario_key,
            "scenario": self._load(self.scenario_json),
            "baseline": self._load(self.baseline_json),
            "optimized": self._load(self.optimized_json),
            "baseline_total_ms": self.baseline_total_ms,
            "optimized_total_ms": self.optimized_total_ms,
            "speedup": self.speedup,
            "target_seconds": self.target_seconds,
            "target_met": bool(self.target_met),
            "notes": self.notes,
            "created_at": to_utc_iso(self.created_at),
        }
