"""Unit tests for data quality and freshness monitoring (EM-010)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.config.settings import TestingConfig
from src.database import Database
from src.fastapi_app import create_fastapi_app
from src.models.pipeline import PipelineJobHistory
from src.services.data_quality import (
    evaluate_data_quality,
    get_data_quality_warnings,
)


@pytest.fixture(name="test_db")
def fixture_test_db():
    """Create a clean in-memory database instance."""
    db = Database("sqlite:///:memory:")
    db.create_all()
    return db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _add_job(session, source, status, now, minutes_ago, error=None):
    """Persist a synthetic pipeline job history entry at a fixed offset."""
    ts = now - timedelta(minutes=minutes_ago)
    session.add(
        PipelineJobHistory(
            job_name=f"sync_{source}",
            source=source,
            status=status,
            start_time=ts,
            end_time=ts if status != "RUNNING" else None,
            attempt_count=1,
            records_processed=0,
            error_message=error,
        )
    )
    session.commit()


def _by_key(report, key):
    return next(s for s in report["sources"] if s["source"] == key)


def test_report_covers_all_configured_sources(test_db):
    """Every ingestion source (including OpenStreetMap) is monitored."""
    with test_db.session() as session:
        report = evaluate_data_quality(session, TestingConfig, now=_utc_now())
    keys = {source["source"] for source in report["sources"]}
    assert keys == {"firms", "weather", "topography", "land_cover", "road_network"}


def test_fresh_source_has_no_warning(test_db):
    """A recent successful pull within the threshold is reported as fresh/ok."""
    now = _utc_now()
    with test_db.session() as session:
        _add_job(session, "FIRMS", "SUCCESS", now, minutes_ago=5)
        report = evaluate_data_quality(session, TestingConfig, now=now)
    firms = _by_key(report, "firms")
    assert firms["status"] == "fresh"
    assert firms["health"] == "ok"
    assert firms["warning"] is False
    assert firms["last_success_age_minutes"] == pytest.approx(5, abs=0.2)
    assert report["overall_status"] == "ok"


def test_stale_source_triggers_operator_warning(test_db):
    """A source older than its freshness threshold is stale and warns."""
    now = _utc_now()
    with test_db.session() as session:
        _add_job(session, "FIRMS", "SUCCESS", now, minutes_ago=60)
        report = evaluate_data_quality(session, TestingConfig, now=now)
    firms = _by_key(report, "firms")
    assert firms["status"] == "stale"
    assert firms["warning"] is True
    assert "stale" in firms["warning_message"]
    assert report["overall_status"] == "degraded"
    assert report["warning_count"] == 1


def test_repeated_failures_mark_source_down(test_db):
    """Consecutive failures beyond threshold with no fresh data mean DOWN."""
    now = _utc_now()
    with test_db.session() as session:
        _add_job(session, "FIRMS", "SUCCESS", now, minutes_ago=60)
        _add_job(session, "FIRMS", "FAILED", now, minutes_ago=3, error="timeout")
        _add_job(session, "FIRMS", "FAILED", now, minutes_ago=2, error="500")
        _add_job(session, "FIRMS", "FAILED", now, minutes_ago=1, error="503")
        report = evaluate_data_quality(session, TestingConfig, now=now)
    firms = _by_key(report, "firms")
    assert firms["status"] == "stale"
    assert firms["health"] == "down"
    assert firms["consecutive_failures"] == 3
    assert firms["last_error"] == "503"
    assert report["overall_status"] == "critical"
    down_warnings = [w for w in report["warnings"] if w["source"] == "firms"]
    assert down_warnings[0]["severity"] == "critical"


def test_never_synced_source_warns(test_db):
    """A source that has never succeeded is degraded and warns."""
    now = _utc_now()
    with test_db.session() as session:
        _add_job(session, "OpenWeather", "FAILED", now, minutes_ago=30, error="401")
        report = evaluate_data_quality(session, TestingConfig, now=now)
    weather = _by_key(report, "weather")
    assert weather["status"] == "never_synced"
    assert weather["health"] == "degraded"
    assert weather["last_success_at"] is None
    assert weather["warning"] is True


def test_unknown_source_without_any_job(test_db):
    """A source with no recorded runs is unknown and does not warn."""
    with test_db.session() as session:
        report = evaluate_data_quality(session, TestingConfig, now=_utc_now())
    road = _by_key(report, "road_network")
    assert road["status"] == "unknown"
    assert road["health"] == "unknown"
    assert road["warning"] is False


def test_running_job_does_not_count_as_failure(test_db):
    """An in-progress run is skipped when counting trailing failures."""
    now = _utc_now()
    with test_db.session() as session:
        _add_job(session, "FIRMS", "SUCCESS", now, minutes_ago=5)
        _add_job(session, "FIRMS", "FAILED", now, minutes_ago=4, error="x")
        _add_job(session, "FIRMS", "RUNNING", now, minutes_ago=1)
        report = evaluate_data_quality(session, TestingConfig, now=now)
    firms = _by_key(report, "firms")
    assert firms["status"] == "fresh"
    assert firms["consecutive_failures"] == 1


def test_warnings_subset_only_lists_problem_sources(test_db):
    """get_data_quality_warnings returns only sources breaching their threshold."""
    now = _utc_now()
    with test_db.session() as session:
        _add_job(session, "FIRMS", "SUCCESS", now, minutes_ago=60)  # stale
        _add_job(session, "OpenWeather", "SUCCESS", now, minutes_ago=5)  # fresh
        result = get_data_quality_warnings(session, TestingConfig, now=now)
    assert result["count"] == 1
    assert result["warnings"][0]["source"] == "firms"
    assert result["overall_status"] == "degraded"


def test_data_quality_endpoint(client):
    """GET /api/v1/data-quality returns the full monitoring report."""
    response = client.get("/api/v1/data-quality")
    assert response.status_code == 200
    body = response.json()
    assert "overall_status" in body
    assert len(body["sources"]) == 5


def test_data_quality_warnings_endpoint(client):
    """GET /api/v1/data-quality/warnings returns the operator warning feed."""
    response = client.get("/api/v1/data-quality/warnings")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(body["warnings"])


def test_openapi_documents_data_quality_paths():
    """The new endpoints are exposed in the OpenAPI schema."""
    app = create_fastapi_app("testing")
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/v1/data-quality" in paths
    assert "/api/v1/data-quality/warnings" in paths
