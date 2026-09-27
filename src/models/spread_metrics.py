"""Spread evaluation metrics ORM model (EM-017).

Stores per-version quantitative accuracy metrics (IoU, area error, arrival
time error) so that model improvements are evidence-based and trackable
across iterations (linked to E12 observability).
"""
from typing import Any

from sqlalchemy import Column, Float, Index, Integer, String, Text

from ..utils.timeutils import to_utc_iso
from .base import BaseModel


class SpreadEvaluationMetric(BaseModel):
    """One evaluation record comparing a forecast polygon to actual perimeter."""

    __tablename__ = "spread_evaluation_metrics"

    event_key = Column(String(64), nullable=False, index=True)
    model_version = Column(String(64), nullable=False, index=True)
    horizon_minutes = Column(Integer, nullable=False)
    # Core metrics (iou_score: 0 = no overlap credit; the *_error columns are
    # nullable because "undefined" must be stored as NULL, not as a fake 0.0)
    iou_score = Column(Float, nullable=False, default=0.0)
    area_error_pct = Column(Float, nullable=True)
    arrival_time_error_min = Column(Float, nullable=True)
    # Supporting data
    predicted_area_ha = Column(Float, nullable=False, default=0.0)
    actual_area_ha = Column(Float, nullable=False, default=0.0)
    predicted_arrival_min = Column(Float, nullable=True)
    actual_arrival_min = Column(Float, nullable=True)
    # Metadata
    evaluation_batch = Column(String(64), nullable=True)
    details_json = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_spread_eval_event_version", "event_key", "model_version"),
        Index("idx_spread_eval_batch", "evaluation_batch"),
    )

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return API-friendly dictionary representation."""
        return {
            "id": self.id,
            "event_key": self.event_key,
            "model_version": self.model_version,
            "horizon_minutes": self.horizon_minutes,
            "iou_score": self.iou_score,
            "area_error_pct": self.area_error_pct,
            "arrival_time_error_min": self.arrival_time_error_min,
            "predicted_area_ha": self.predicted_area_ha,
            "actual_area_ha": self.actual_area_ha,
            "predicted_arrival_min": self.predicted_arrival_min,
            "actual_arrival_min": self.actual_arrival_min,
            "evaluation_batch": self.evaluation_batch,
            "created_at": to_utc_iso(self.created_at),
        }
