"""Unit tests for data pipeline scheduler, Celery tasks, and observability endpoints."""
import pytest
from fastapi.testclient import TestClient

from src.database import Database
from src.fastapi_app import create_fastapi_app
from src.models.pipeline import PipelineJobHistory
from src.services.pipeline_tracker import PipelineTracker
from src.tasks import (
    sync_land_cover,
    sync_nasa_firms,
    sync_openweather,
    sync_topography,
)


@pytest.fixture(name="test_db")
def fixture_test_db():
    """Create a clean in-memory database instance."""
    db = Database("sqlite:///:memory:")
    db.create_all()
    return db


@pytest.fixture(name="client")
def fixture_client():
    """Create FastAPI test client with testing config."""
    app = create_fastapi_app("testing")
    with TestClient(app) as test_client:
        yield test_client


class _SharedTestDb:
    """Route the tasks' per-run Database through the shared in-memory test db.

    The task runner disposes its engine after every execution; disposing the
    shared StaticPool in-memory engine would wipe the schema between tasks,
    so the engine handle is inert here.
    """

    def __init__(self, _url, inner):
        self._inner = inner

    def create_all(self):
        self._inner.create_all()

    def session(self):
        return self._inner.session()

    @property
    def engine(self):
        import types

        return types.SimpleNamespace(dispose=lambda: None)


def test_pipeline_job_history_model(test_db):
    """Test PipelineJobHistory model creation and dictionary property."""
    with test_db.session() as session:
        job = PipelineJobHistory(
            job_name="sync_nasa_firms",
            source="FIRMS",
            status="SUCCESS",
            records_processed=15,
            duration_seconds=1.23,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        data = job.as_dict
        assert data["job_name"] == "sync_nasa_firms"
        assert data["source"] == "FIRMS"
        assert data["status"] == "SUCCESS"
        assert data["records_processed"] == 15
        assert data["duration_seconds"] == 1.23


def test_pipeline_tracker_lifecycle(test_db):
    """Test start, complete, fail, history, and summary methods of PipelineTracker."""
    with test_db.session() as session:
        job1 = PipelineTracker.start_job(session, "sync_nasa_firms", "FIRMS")
        assert job1.status == "RUNNING"

        completed = PipelineTracker.complete_job(session, job1.id, records_processed=10)
        assert completed.status == "SUCCESS"
        assert completed.records_processed == 10
        assert completed.duration_seconds is not None

        job2 = PipelineTracker.start_job(session, "sync_openweather", "OpenWeather")
        failed = PipelineTracker.fail_job(session, job2.id, "API connection error")
        assert failed.status == "FAILED"
        assert failed.error_message == "API connection error"

        history = PipelineTracker.get_job_history(session)
        assert len(history) == 2

        summary = PipelineTracker.get_pipeline_summary(session)
        assert summary["status"] == "healthy"
        assert summary["total_job_runs"] == 2
        assert "FIRMS" in summary["sources"]
        assert summary["sources"]["FIRMS"]["successful_runs"] == 1


def test_celery_tasks_execution(monkeypatch, test_db):
    """Test Celery sync tasks execution with mocked underlying sync services."""
    monkeypatch.setattr(
        "src.tasks.sync_firms",
        lambda session, config: {"observations": 5, "clusters": 2},
    )
    monkeypatch.setattr(
        "src.tasks.sync_weather_for_clusters",
        lambda session, config: {
            "clusters_processed": 2,
            "weather_points_saved": 16,
        },
    )
    monkeypatch.setattr(
        "src.tasks.sync_topography_for_clusters",
        lambda session, config: {
            "clusters_processed": 2,
            "topography_points_saved": 2,
        },
    )
    monkeypatch.setattr(
        "src.tasks.sync_land_cover_for_clusters",
        lambda session, config: {
            "clusters_processed": 2,
            "land_cover_points_saved": 2,
        },
    )
    monkeypatch.setattr(
        "src.tasks.Database",
        lambda url: _SharedTestDb(url, test_db),
    )

    res_firms = sync_nasa_firms()
    assert res_firms["status"] == "ok"
    assert res_firms["observations"] == 5

    res_weather = sync_openweather()
    assert res_weather["status"] == "ok"

    res_topo = sync_topography()
    assert res_topo["status"] == "ok"

    res_lc = sync_land_cover()
    assert res_lc["status"] == "ok"

    with test_db.session() as session:
        jobs = PipelineTracker.get_job_history(session)
        assert len(jobs) == 4


def test_pipeline_fastapi_endpoints(client, monkeypatch):
    """Test /api/v1/pipeline endpoints for status, history, and trigger."""
    # The pipeline-trigger route now lives in src.routes.grid_pipeline (extracted
    # from the create_fastapi_app monolith); its closure resolves the sync
    # helpers from that module namespace, so the patch targets follow the code.
    monkeypatch.setattr(
        "src.routes.grid_pipeline.sync_firms",
        lambda session, config: {"observations": 3, "clusters": 1},
    )
    monkeypatch.setattr(
        "src.routes.grid_pipeline.sync_weather_for_clusters",
        lambda session, config: {
            "clusters_processed": 1,
            "weather_points_saved": 8,
        },
    )
    monkeypatch.setattr(
        "src.routes.grid_pipeline.sync_topography_for_clusters",
        lambda session, config: {
            "clusters_processed": 1,
            "topography_points_saved": 1,
        },
    )
    monkeypatch.setattr(
        "src.routes.grid_pipeline.sync_land_cover_for_clusters",
        lambda session, config: {
            "clusters_processed": 1,
            "land_cover_points_saved": 1,
        },
    )

    resp_status = client.get("/api/v1/pipeline/status")
    assert resp_status.status_code == 200
    data_status = resp_status.json()
    assert data_status["status"] == "healthy"
    assert "schedules" in data_status
    assert data_status["schedules"]["FIRMS"] == "10m"

    resp_trigger = client.post("/api/v1/pipeline/trigger", json={"source": "all"})
    assert resp_trigger.status_code == 200
    data_trigger = resp_trigger.json()
    assert data_trigger["status"] == "triggered"
    assert "firms" in data_trigger["results"]

    resp_jobs = client.get("/api/v1/pipeline/jobs")
    assert resp_jobs.status_code == 200
    data_jobs = resp_jobs.json()
    assert data_jobs["count"] >= 4

    resp_invalid = client.post(
        "/api/v1/pipeline/trigger", json={"source": "invalid_source"}
    )
    assert resp_invalid.status_code == 400
