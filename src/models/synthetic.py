"""Synthetic scenario generation records (EM-104).

Tracks each deterministic generation run so demos can prove which data was
synthesized, from which seed/config, and whether it was persisted.
"""
from typing import Any

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class ScenarioRun(BaseModel):
    """One synthetic-data generation run (audit trail for demos)."""

    __tablename__ = "scenario_runs"

    run_key = Column(String(64), unique=True, nullable=False, index=True)
    scenario_tag = Column(String(32), nullable=False, index=True)
    seed = Column(Integer, nullable=False)
    preset = Column(String(64), nullable=True)
    config_hash = Column(String(64), nullable=False)
    result_hash = Column(String(64), nullable=False)
    base_time = Column(Float, nullable=False)
    record_count = Column(Integer, nullable=False, default=0)
    persisted = Column(Integer, nullable=False, default=0)  # 0/1 flag
    config_json = Column(Text, nullable=False)
    dataset_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False, index=True)

    __table_args__ = (Index("idx_scenario_runs_seed", "seed"),)

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation (no raw dataset)."""
        return {
            "id": self.id,
            "run_key": self.run_key,
            "scenario_tag": self.scenario_tag,
            "seed": self.seed,
            "preset": self.preset,
            "config_hash": self.config_hash,
            "result_hash": self.result_hash,
            "record_count": self.record_count,
            "persisted": bool(self.persisted),
            "generated_at": to_utc_iso(self.generated_at),
        }
