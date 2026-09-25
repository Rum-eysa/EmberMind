"""Unit tests for EFFIS historical fire perimeter import and dataset readiness (EM-011)."""
import pytest
from fastapi.testclient import TestClient

from src.config.settings import TestingConfig
from src.database import Database
from src.fastapi_app import create_fastapi_app
from src.models.historical_fire import HistoricalFirePerimeter
from src.services.effis import (
    EffisClient,
    assign_dataset_splits,
    bootstrap_sample_dataset,
    build_calibration_dataset,
    import_effis_perimeters,
    parse_effis_response,
    sample_effis_payload,
)

BBOX = (36.0, 26.0, 39.5, 30.0)


@pytest.fixture(name="test_db")
def fixture_test_db():
    """Create a clean in-memory database instance."""
    db = Database("sqlite:///:memory:")
    db.create_all()
    return db


class _FakeResponse:
    """Minimal stand-in for a requests.Response used in injected HTTP calls."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _single_feature_payload():
    return {
        "features": [
            {
                "attributes": {
                    "OBJECTID": 5001,
                    "FIRE_YEAR": 2007,
                    "COUNTRY": "Turkey",
                    "ISO_CODE": "TR",
                    "NATIONAL_CODE": "TR-2007-01",
                    "MMI_LEVEL": "high",
                    "DATE_START": "2007-07-15",
                    "DATE_END": "2007-07-22",
                },
                "geometry": {
                    "rings": [
                        [
                            [27.0, 38.0],
                            [27.05, 38.0],
                            [27.05, 38.05],
                            [27.0, 38.05],
                            [27.0, 38.0],
                        ]
                    ]
                },
            },
            {
                "attributes": {
                    "OBJECTID": 5002,
                    "FIRE_YEAR": 2008,
                    "COUNTRY": "Greece",
                },
                "geometry": {"rings": []},
            },
        ]
    }


def test_parse_effis_response_normalises_and_skips_empty():
    """Valid rings become perimeters with geometry; ring-less features are skipped."""
    perimeters = parse_effis_response(_single_feature_payload(), default_year=2007)
    assert len(perimeters) == 1
    item = perimeters[0]
    assert item.perimeter_key == "effis_2007_5001"
    assert item.country_code == "TR"
    assert item.mmi_level == "high"
    assert item.area_km2 > 0
    assert BBOX[0] <= item.latitude <= BBOX[2]
    assert item.geometry["type"] == "Polygon"
    assert item.date_start is not None


def test_import_via_injected_client_is_idempotent(test_db):
    """A live-style import stores perimeters and re-import does not duplicate them."""
    payload = sample_effis_payload(BBOX, count=22)
    client = EffisClient(
        years=[2007], http_get=lambda url, timeout: _FakeResponse(payload)
    )
    with test_db.session() as session:
        first = import_effis_perimeters(session, TestingConfig, BBOX, client=client)
        assert first["perimeters_saved"] == 22
        total = session.query(HistoricalFirePerimeter).count()
        assert total == 22
        second = import_effis_perimeters(session, TestingConfig, BBOX, client=client)
        assert second["perimeters_saved"] == 22
        assert session.query(HistoricalFirePerimeter).count() == 22


def test_bootstrap_sample_dataset_provides_at_least_20_events(test_db):
    """The offline sample bootstrap makes >=20 historical events available."""
    with test_db.session() as session:
        result = bootstrap_sample_dataset(session, BBOX, count=24)
        assert result["perimeters_saved"] >= 20
        assert session.query(HistoricalFirePerimeter).count() == 24


def test_dataset_split_and_calibration_readiness(test_db):
    """Splits cover every event and the dataset is ready for training/validation."""
    with test_db.session() as session:
        bootstrap_sample_dataset(session, BBOX, count=24)
        counts = assign_dataset_splits(session, 0.2, 0.2)
        assert counts["total"] == 24
        assert counts["ready_for_training"] is True
        assert counts["train"] + counts["test"] + counts["validation"] == 24

        dataset = build_calibration_dataset(session)
        assert dataset["total"] == 24
        assert dataset["ready_for_training"] is True
        assert dataset["counts"]["unassigned"] == 0
        assert len(dataset["splits"]["train"]) == counts["train"]
        assert len(dataset["splits"]["test"]) == counts["test"]
        feature = dataset["splits"]["train"][0]
        assert feature["geometry"]["type"] == "Polygon"


def test_assign_dataset_splits_rejects_invalid_fractions(test_db):
    """Overlapping fractions are rejected with ValueError."""
    with test_db.session() as session:
        bootstrap_sample_dataset(session, BBOX, count=5)
        with pytest.raises(ValueError):
            assign_dataset_splits(session, 0.6, 0.6)


def test_historical_fires_list_and_dataset_empty(client):
    """Endpoints respond correctly on an empty store."""
    listing = client.get("/api/v1/historical-fires")
    assert listing.status_code == 200
    assert listing.json()["source"] == "EFFIS"
    assert listing.json()["count"] == 0

    dataset = client.get("/api/v1/historical-fires/dataset")
    assert dataset.status_code == 200
    assert dataset.json()["total"] == 0
    assert dataset.json()["ready_for_training"] is False


def test_bootstrap_then_split_flow_via_api(client):
    """Bootstrap, dataset readiness and split assignment work end to end."""
    boot = client.post("/api/v1/historical-fires/bootstrap-sample", json={"count": 24})
    assert boot.status_code == 200
    assert boot.json()["perimeters_saved"] >= 20

    dataset = client.get("/api/v1/historical-fires/dataset").json()
    assert dataset["total"] == 24
    assert dataset["ready_for_training"] is True

    split = client.post(
        "/api/v1/historical-fires/splits",
        json={"test_fraction": 0.2, "validation_fraction": 0.2},
    )
    assert split.status_code == 200
    body = split.json()
    assert body["train"] + body["test"] + body["validation"] == 24

    dataset_after = client.get("/api/v1/historical-fires/dataset").json()
    assert dataset_after["counts"]["unassigned"] == 0
    assert dataset_after["counts"]["test"] >= 1


def test_import_endpoint_uses_service(client, monkeypatch):
    """The import endpoint delegates to the EFFIS import service."""
    monkeypatch.setattr(
        "src.routes.historical_fire.import_effis_perimeters",
        lambda session, settings, bbox: {
            "perimeters_fetched": 3,
            "perimeters_saved": 3,
        },
    )
    response = client.post("/api/v1/historical-fires/import", json={})
    assert response.status_code == 200
    assert response.json()["perimeters_saved"] == 3


def test_splits_endpoint_rejects_invalid_request(client):
    """Invalid split fractions return HTTP 400."""
    client.post("/api/v1/historical-fires/bootstrap-sample", json={"count": 5})
    response = client.post(
        "/api/v1/historical-fires/splits",
        json={"test_fraction": 0.7, "validation_fraction": 0.7},
    )
    assert response.status_code == 400


def test_openapi_documents_historical_fire_paths():
    """The new endpoints are exposed in the OpenAPI schema."""
    app = create_fastapi_app("testing")
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/v1/historical-fires" in paths
    assert "/api/v1/historical-fires/import" in paths
    assert "/api/v1/historical-fires/dataset" in paths
