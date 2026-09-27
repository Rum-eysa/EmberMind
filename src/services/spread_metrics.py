"""Spread evaluation metrics service (EM-017).

Computes quantitative accuracy metrics comparing predicted spread polygons
against actual fire perimeters on historical events:
 - IoU / Jaccard (polygon overlap ratio)
 - Area error (percentage difference)
 - Arrival time error (minutes deviation)

Metrics are stored per model version for evidence-based model iteration
(linked to E12 observability requirements).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, cast

from shapely import wkt as shapely_wkt
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.spatial import FireEvent, FireForecast
from src.models.spread_metrics import SpreadEvaluationMetric


class SpreadMetricsError(RuntimeError):
    """Raised when spread evaluation cannot proceed."""


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _parse_wkt_polygon(wkt: str) -> Polygon | None:
    """Parse a WKT POLYGON string into a Shapely Polygon."""
    if not wkt or "EMPTY" in wkt:
        return None
    try:
        geom = shapely_wkt.loads(wkt)
        if isinstance(geom, Polygon) and geom.is_valid and geom.area > 0:
            return geom
        if isinstance(geom, MultiPolygon):
            # Take the largest polygon
            if geom.geoms:
                return max(geom.geoms, key=lambda g: g.area)
        return None
    except (GEOSException, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Core metric computations
# ---------------------------------------------------------------------------


def compute_iou(
    predicted_wkt: str,
    actual_wkt: str,
) -> float:
    """Intersection over Union (Jaccard index) between two WKT polygons.

    Returns a value in [0, 1]. Returns 0.0 if either polygon is invalid.
    """
    pred = _parse_wkt_polygon(predicted_wkt)
    actual = _parse_wkt_polygon(actual_wkt)
    if pred is None or actual is None:
        return 0.0
    try:
        intersection = pred.intersection(actual).area
        union = pred.union(actual).area
        if union <= 0:
            return 0.0
        return round(intersection / union, 6)
    except GEOSException:
        return 0.0


def compute_area_error(
    predicted_area_ha: float,
    actual_area_ha: float,
) -> float | None:
    """Percentage area error: |predicted - actual| / actual * 100.

    Returns ``None`` when the actual area is zero: the metric is undefined,
    which must not be reported as a perfect 0% error.
    """
    if actual_area_ha <= 0:
        return None
    error = abs(predicted_area_ha - actual_area_ha) / actual_area_ha * 100.0
    return round(error, 2)


def compute_arrival_time_error(
    forecast_for: datetime | None,
    actual_arrival: datetime | None,
) -> float | None:
    """Absolute arrival time error in minutes.

    Returns the unsigned deviation between predicted and actual arrival, or
    ``None`` when either timestamp is missing (unknown, not zero error).
    """
    if forecast_for is None or actual_arrival is None:
        return None
    # Normalize to naive UTC for subtraction
    pred_ts = forecast_for.replace(tzinfo=None) if forecast_for.tzinfo else forecast_for
    act_ts = (
        actual_arrival.replace(tzinfo=None) if actual_arrival.tzinfo else actual_arrival
    )
    delta = (pred_ts - act_ts).total_seconds() / 60.0
    return round(abs(delta), 2)


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------


def evaluate_forecast_against_actual(  # pylint: disable=too-many-arguments
    session: Session,
    event_key: str,
    actual_perimeter_wkt: str,
    actual_area_ha: float,
    actual_arrival_time: datetime | None = None,
    model_version: str | None = None,
) -> list[dict[str, Any]]:
    """Evaluate all stored forecasts for an event against the actual perimeter.

    For each horizon, computes IoU, area error, and arrival time error.
    Persists results in spread_evaluation_metrics table.
    Returns a list of metric dicts (one per horizon).
    """
    if not event_key:
        raise SpreadMetricsError("event_key is required")
    if not actual_perimeter_wkt:
        raise SpreadMetricsError("actual_perimeter_wkt is required")

    actual_poly = _parse_wkt_polygon(actual_perimeter_wkt)
    if actual_poly is None:
        raise SpreadMetricsError("actual_perimeter_wkt could not be parsed")

    # Fetch stored forecasts for this event
    query = select(FireForecast).where(FireForecast.event_key == event_key)
    if model_version:
        query = query.where(FireForecast.model_name == model_version)
    forecasts = session.scalars(query.order_by(FireForecast.horizon_minutes)).all()

    if not forecasts:
        raise SpreadMetricsError(
            f"No stored forecasts found for event_key='{event_key}'"
        )

    version = model_version or forecasts[0].model_name
    batch_key = f"EVAL-{uuid.uuid4().hex[:12]}"

    # Event start time (used to derive actual arrival in minutes from start)
    actual_arrival_min: float | None = None
    if actual_arrival_time:
        event = session.scalar(
            select(FireEvent).where(FireEvent.event_key == event_key)
        )
        if event and event.started_at:
            start = (
                event.started_at.replace(tzinfo=None)
                if event.started_at.tzinfo
                else event.started_at
            )
            act = (
                actual_arrival_time.replace(tzinfo=None)
                if actual_arrival_time.tzinfo
                else actual_arrival_time
            )
            actual_arrival_min = round((act - start).total_seconds() / 60.0, 1)

    results: list[dict[str, Any]] = []
    metric_rows: list[SpreadEvaluationMetric] = []

    for forecast in forecasts:
        # IoU
        iou = compute_iou(str(forecast.geometry_wkt), actual_perimeter_wkt)

        # Area error
        area_err = compute_area_error(float(forecast.predicted_area_ha), actual_area_ha)

        # Arrival time error (None = unknown, e.g. no actual arrival given)
        arrival_err: float | None = None
        fc_forecast_for = cast(datetime, forecast.forecast_for)
        if actual_arrival_time and fc_forecast_for:
            arrival_err = compute_arrival_time_error(
                fc_forecast_for, actual_arrival_time
            )

        # Predicted arrival expressed as minutes from event start (horizon)
        predicted_arrival_min = float(forecast.horizon_minutes)

        metric_row = SpreadEvaluationMetric(
            event_key=event_key,
            model_version=version,
            horizon_minutes=forecast.horizon_minutes,
            iou_score=iou,
            area_error_pct=area_err,
            arrival_time_error_min=arrival_err,
            predicted_area_ha=forecast.predicted_area_ha,
            actual_area_ha=actual_area_ha,
            predicted_arrival_min=predicted_arrival_min,
            actual_arrival_min=actual_arrival_min,
            evaluation_batch=batch_key,
            details_json=json.dumps(
                {
                    "forecast_id": forecast.id,
                    "model_name": forecast.model_name,
                    "batch_key": batch_key,
                },
                default=str,
            ),
        )
        session.add(metric_row)
        metric_rows.append(metric_row)

    # Flush so ids/timestamps are populated before serializing the response
    session.flush()
    results.extend(row.as_dict for row in metric_rows)
    session.commit()
    return results


def list_evaluation_metrics(
    session: Session,
    event_key: str | None = None,
    model_version: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Retrieve stored evaluation metrics, newest first."""
    query = select(SpreadEvaluationMetric).order_by(
        SpreadEvaluationMetric.created_at.desc()
    )
    if event_key:
        query = query.where(SpreadEvaluationMetric.event_key == event_key)
    if model_version:
        query = query.where(SpreadEvaluationMetric.model_version == model_version)
    rows = session.scalars(query.limit(limit)).all()
    return [row.as_dict for row in rows]


def version_summary(
    session: Session,
    model_version: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregated metrics per model version (mean IoU, mean area error, etc.)."""
    base_cols = [
        SpreadEvaluationMetric.model_version,
        func.avg(SpreadEvaluationMetric.iou_score).label("mean_iou"),
        func.avg(SpreadEvaluationMetric.area_error_pct).label("mean_area_error_pct"),
        func.avg(SpreadEvaluationMetric.arrival_time_error_min).label(
            "mean_arrival_time_error_min"
        ),
        # pylint: disable=not-callable
        func.count(SpreadEvaluationMetric.id).label("evaluation_count"),
    ]
    query = select(*base_cols).group_by(SpreadEvaluationMetric.model_version)
    if model_version:
        query = query.where(SpreadEvaluationMetric.model_version == model_version)
    rows = session.execute(query).all()
    return [
        {
            "model_version": row.model_version,
            "mean_iou": round(float(row.mean_iou), 4)
            if row.mean_iou is not None
            else None,
            "mean_area_error_pct": (
                round(float(row.mean_area_error_pct), 2)
                if row.mean_area_error_pct is not None
                else None
            ),
            "mean_arrival_time_error_min": (
                round(float(row.mean_arrival_time_error_min), 2)
                if row.mean_arrival_time_error_min is not None
                else None
            ),
            "evaluation_count": int(row.evaluation_count),
        }
        for row in rows
    ]
