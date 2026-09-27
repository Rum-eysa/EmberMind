"""Unit tests for EM-017: spread evaluation metrics service and endpoints."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.models.spatial import FireEvent, FireForecast
from src.models.spread_metrics import SpreadEvaluationMetric
from src.services.spread_metrics import (
    SpreadMetricsError,
    compute_area_error,
    compute_arrival_time_error,
    compute_iou,
    evaluate_forecast_against_actual,
    list_evaluation_metrics,
    version_summary,
)
from src.utils.timeutils import utc_now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _square_wkt(cx: float, cy: float, size: float) -> str:
    """Generate a WKT POLYGON for a square centered at (cx, cy)."""
    half = size / 2.0
    return (
        f"POLYGON(({cx - half} {cy - half},{cx + half} {cy - half},"
        f"{cx + half} {cy + half},{cx - half} {cy + half},"
        f"{cx - half} {cy - half}))"
    )


def _seed_event_and_forecasts(session, event_key: str = "eval_test_001"):
    """Seed a fire event with 3 forecast horizons for testing."""
    now = utc_now()
    event = FireEvent(
        event_key=event_key,
        name="Test Fire for Evaluation",
        latitude=37.0,
        longitude=28.0,
        min_lat=36.9,
        max_lat=37.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt=_square_wkt(28.0, 37.0, 0.01),
        severity="high",
        status="active",
        started_at=now,
        source="test",
    )
    session.add(event)

    # Create 3 forecasts at different horizons
    for horizon in (30, 60, 120):
        # Predicted polygon: a square slightly offset from actual
        offset = horizon * 0.0001
        fc = FireForecast(
            event_key=event_key,
            model_name="rothermel_v1",
            latitude=37.0,
            longitude=28.0,
            predicted_area_ha=float(horizon * 2),
            geometry_wkt=_square_wkt(28.0 + offset, 37.0, 0.02),
            forecast_for=now + timedelta(minutes=horizon),
            horizon_minutes=horizon,
            rate_of_spread_m_per_min=5.0,
            spread_direction_deg=90.0,
            inputs_json="{}",
        )
        session.add(fc)
    session.commit()
    return now


# ---------------------------------------------------------------------------
# Unit tests: compute_iou
# ---------------------------------------------------------------------------


class TestComputeIou:
    """Tests for IoU/Jaccard calculation."""

    def test_identical_polygons_give_iou_one(self):
        wkt = _square_wkt(0, 0, 1.0)
        assert compute_iou(wkt, wkt) == pytest.approx(1.0, abs=1e-6)

    def test_disjoint_polygons_give_iou_zero(self):
        a = _square_wkt(0, 0, 1.0)
        b = _square_wkt(10, 10, 1.0)
        assert compute_iou(a, b) == 0.0

    def test_partial_overlap_gives_intermediate_iou(self):
        # Two unit squares overlapping by 0.5 in x
        a = _square_wkt(0, 0, 1.0)  # -0.5 to 0.5
        b = _square_wkt(0.5, 0, 1.0)  # 0.0 to 1.0
        iou = compute_iou(a, b)
        # Intersection: 0.5 x 1.0 = 0.5, Union: 1.0 + 1.0 - 0.5 = 1.5
        assert iou == pytest.approx(0.5 / 1.5, abs=1e-4)

    def test_invalid_wkt_returns_zero(self):
        assert compute_iou("", "POLYGON((0 0, 1 1))") == 0.0
        assert compute_iou("INVALID", _square_wkt(0, 0, 1)) == 0.0

    def test_empty_polygon_returns_zero(self):
        assert compute_iou("POLYGON EMPTY", _square_wkt(0, 0, 1)) == 0.0


# ---------------------------------------------------------------------------
# Unit tests: compute_area_error
# ---------------------------------------------------------------------------


class TestComputeAreaError:
    """Tests for percentage area error."""

    def test_perfect_prediction_zero_error(self):
        assert compute_area_error(100.0, 100.0) == 0.0

    def test_overestimation(self):
        # Predicted 150, actual 100 → 50% error
        assert compute_area_error(150.0, 100.0) == 50.0

    def test_underestimation(self):
        # Predicted 60, actual 100 → 40% error
        assert compute_area_error(60.0, 100.0) == 40.0

    def test_zero_actual_is_undefined_not_perfect(self):
        # Regression: 0.0 here would masquerade as a flawless prediction.
        assert compute_area_error(50.0, 0.0) is None


# ---------------------------------------------------------------------------
# Unit tests: compute_arrival_time_error
# ---------------------------------------------------------------------------


class TestComputeArrivalTimeError:
    """Tests for arrival time error in minutes."""

    def test_perfect_arrival_zero_error(self):
        t = datetime(2025, 8, 1, 12, 0, tzinfo=timezone.utc)
        assert compute_arrival_time_error(t, t) == 0.0

    def test_ten_minutes_late(self):
        pred = datetime(2025, 8, 1, 12, 10, tzinfo=timezone.utc)
        actual = datetime(2025, 8, 1, 12, 0, tzinfo=timezone.utc)
        assert compute_arrival_time_error(pred, actual) == 10.0

    def test_fifteen_minutes_early(self):
        pred = datetime(2025, 8, 1, 11, 45, tzinfo=timezone.utc)
        actual = datetime(2025, 8, 1, 12, 0, tzinfo=timezone.utc)
        assert compute_arrival_time_error(pred, actual) == 15.0

    def test_none_is_unknown_not_zero(self):
        t = datetime(2025, 8, 1, 12, 0, tzinfo=timezone.utc)
        assert compute_arrival_time_error(None, t) is None
        assert compute_arrival_time_error(t, None) is None


# ---------------------------------------------------------------------------
# Integration tests: evaluate_forecast_against_actual
# ---------------------------------------------------------------------------


class TestEvaluateForecast:
    """End-to-end evaluation with DB persistence."""

    def test_evaluate_stores_metrics(self, session):
        now = _seed_event_and_forecasts(session, "eval_store_01")
        actual_wkt = _square_wkt(28.0, 37.0, 0.02)
        results = evaluate_forecast_against_actual(
            session,
            event_key="eval_store_01",
            actual_perimeter_wkt=actual_wkt,
            actual_area_ha=100.0,
            actual_arrival_time=now + timedelta(minutes=60),
        )
        assert len(results) == 3
        # All horizons should have IoU > 0 (overlapping squares)
        for r in results:
            assert r["iou_score"] >= 0.0
            assert r["area_error_pct"] >= 0.0
            # Flushed rows must carry id and created_at in the response
            assert r["id"] is not None
            assert r["created_at"] is not None
        # Verify persisted
        rows = session.scalars(
            select(SpreadEvaluationMetric).where(
                SpreadEvaluationMetric.event_key == "eval_store_01"
            )
        ).all()
        assert len(rows) == 3

    def test_evaluate_missing_event_raises(self, session):
        with pytest.raises(SpreadMetricsError, match="No stored forecasts"):
            evaluate_forecast_against_actual(
                session,
                event_key="nonexistent_event",
                actual_perimeter_wkt=_square_wkt(0, 0, 1),
                actual_area_ha=50.0,
            )

    def test_evaluate_empty_perimeter_raises(self, session):
        _seed_event_and_forecasts(session, "eval_empty_01")
        with pytest.raises(SpreadMetricsError, match="actual_perimeter_wkt"):
            evaluate_forecast_against_actual(
                session,
                event_key="eval_empty_01",
                actual_perimeter_wkt="",
                actual_area_ha=50.0,
            )

    def test_version_filter(self, session):
        _seed_event_and_forecasts(session, "eval_ver_01")
        results = evaluate_forecast_against_actual(
            session,
            event_key="eval_ver_01",
            actual_perimeter_wkt=_square_wkt(28.0, 37.0, 0.02),
            actual_area_ha=100.0,
            model_version="rothermel_v1",
        )
        assert len(results) == 3
        for r in results:
            assert r["model_version"] == "rothermel_v1"


# ---------------------------------------------------------------------------
# Integration tests: list and summary
# ---------------------------------------------------------------------------


class TestListAndSummary:
    """Query endpoints for stored metrics."""

    def test_list_metrics_filtered_by_event(self, session):
        now = _seed_event_and_forecasts(session, "eval_list_01")
        evaluate_forecast_against_actual(
            session,
            event_key="eval_list_01",
            actual_perimeter_wkt=_square_wkt(28.0, 37.0, 0.02),
            actual_area_ha=100.0,
            actual_arrival_time=now + timedelta(minutes=60),
        )
        rows = list_evaluation_metrics(session, event_key="eval_list_01")
        assert len(rows) == 3

    def test_version_summary_aggregates(self, session):
        now = _seed_event_and_forecasts(session, "eval_sum_01")
        evaluate_forecast_against_actual(
            session,
            event_key="eval_sum_01",
            actual_perimeter_wkt=_square_wkt(28.0, 37.0, 0.02),
            actual_area_ha=100.0,
            actual_arrival_time=now + timedelta(minutes=60),
        )
        summaries = version_summary(session)
        assert len(summaries) >= 1
        s = summaries[0]
        assert s["model_version"] == "rothermel_v1"
        assert s["evaluation_count"] == 3
        assert "mean_iou" in s
        assert "mean_area_error_pct" in s


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestSpreadMetricsEndpoints:
    """HTTP endpoint tests for EM-017 metrics."""

    def test_evaluate_endpoint(self, client, session):
        now = _seed_event_and_forecasts(session, "eval_api_01")
        resp = client.post(
            "/api/v1/spread/evaluate",
            json={
                "event_key": "eval_api_01",
                "actual_perimeter_wkt": _square_wkt(28.0, 37.0, 0.02),
                "actual_area_ha": 100.0,
                "actual_arrival_time": (now + timedelta(minutes=60)).isoformat(),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["count"] == 3
        assert len(body["metrics"]) == 3

    def test_evaluate_endpoint_bad_request(self, client):
        resp = client.post(
            "/api/v1/spread/evaluate",
            json={
                "event_key": "missing_event",
                "actual_perimeter_wkt": _square_wkt(0, 0, 1),
                "actual_area_ha": 50.0,
            },
        )
        assert resp.status_code == 400

    def test_evaluate_endpoint_bad_arrival_time(self, client, session):
        _seed_event_and_forecasts(session, "eval_api_badts")
        resp = client.post(
            "/api/v1/spread/evaluate",
            json={
                "event_key": "eval_api_badts",
                "actual_perimeter_wkt": _square_wkt(28.0, 37.0, 0.02),
                "actual_area_ha": 100.0,
                "actual_arrival_time": "not-a-timestamp",
            },
        )
        assert resp.status_code == 400
        assert "ISO-8601" in resp.text

    def test_metrics_list_endpoint(self, client, session):
        now = _seed_event_and_forecasts(session, "eval_api_02")
        evaluate_forecast_against_actual(
            session,
            event_key="eval_api_02",
            actual_perimeter_wkt=_square_wkt(28.0, 37.0, 0.02),
            actual_area_ha=100.0,
            actual_arrival_time=now + timedelta(minutes=60),
        )
        resp = client.get("/api/v1/spread/metrics", params={"event_key": "eval_api_02"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3

    def test_summary_endpoint(self, client, session):
        now = _seed_event_and_forecasts(session, "eval_api_03")
        evaluate_forecast_against_actual(
            session,
            event_key="eval_api_03",
            actual_perimeter_wkt=_square_wkt(28.0, 37.0, 0.02),
            actual_area_ha=100.0,
            actual_arrival_time=now + timedelta(minutes=60),
        )
        resp = client.get("/api/v1/spread/metrics/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] >= 1
        assert "mean_iou" in body["versions"][0]
