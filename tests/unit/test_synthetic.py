"""EM-104 synthetic scenario generator tests.

Covers the two acceptance guarantees — same seed yields the same result, and
every synthetic record is explicitly labelled — plus config validation,
persistence/cleanup and the HTTP endpoints.
"""
from datetime import datetime

import pytest

from src.models.inventory import SuppressionResource
from src.models.road_network import CrewBase
from src.models.spatial import FireEvent
from src.models.weather import WeatherDataPoint
from src.services.synthetic import (
    DEFAULT_CONFIG,
    PRESETS,
    SYNTHETIC_LABEL,
    SyntheticError,
    build_dataset,
    canonical_json,
    cleanup_scenario,
    list_runs,
    normalize_config,
    persist_dataset,
    record_run,
    sha256_of,
)


# ------------------------------------------------------------ generator ---


def test_same_seed_same_result():
    first = build_dataset(42)
    second = build_dataset(42)
    assert canonical_json(first) == canonical_json(second)
    assert first["meta"]["result_hash"] == second["meta"]["result_hash"]


def test_different_seed_different_result():
    assert (
        build_dataset(1)["meta"]["result_hash"]
        != build_dataset(2)["meta"]["result_hash"]
    )


def test_preset_changes_scenario_but_seed_stays_deterministic():
    a = build_dataset(5, preset="firtina")
    b = build_dataset(5, preset="firtina")
    c = build_dataset(5, preset="standart")
    assert canonical_json(a) == canonical_json(b)
    assert a["meta"]["result_hash"] != c["meta"]["result_hash"]
    a_mean = sum(w["wind_speed_kmh"] for w in a["wind_history"]) / len(
        a["wind_history"]
    )
    c_mean = sum(w["wind_speed_kmh"] for w in c["wind_history"]) / len(
        c["wind_history"]
    )
    assert a_mean > c_mean  # "fırtına" has a stronger base wind, same seed
    assert a["meta"]["config_hash"] != c["meta"]["config_hash"]


def test_configurable_fire_location_wind_outages_resources():
    config = {
        "fire_location": {"latitude": 37.5, "longitude": 28.0},
        "wind_history": {"hours": 6, "step_minutes": 30},
        "outage_zones": {"count": 2},
        "resource_distribution": {
            "counts": {"crew": 3, "helicopter": 0, "uav": 1},
            "base_count": 1,
        },
    }
    data = build_dataset(7, config=config)
    assert data["fire"]["latitude"] == 37.5
    assert data["fire"]["longitude"] == 28.0
    assert len(data["wind_history"]) == 13  # 6h / 30min + base sample
    assert len(data["outage_zones"]) == 2
    assert len(data["resource_distribution"]["resources"]) == 4
    assert len(data["resource_distribution"]["bases"]) == 1


def test_every_record_is_labelled_synthetic():
    data = build_dataset(3)
    records = [data["fire"]] + data["wind_history"] + data["outage_zones"]
    records += data["resource_distribution"]["bases"]
    records += data["resource_distribution"]["resources"]
    assert records
    for record in records:
        assert record["synthetic"] is True
        assert record["synthetic_label"] == SYNTHETIC_LABEL
        assert "SENTETİK" in record["synthetic_label"]
    assert data["meta"]["synthetic"] is True
    assert data["meta"]["notice"]


def test_hash_helpers_are_canonical():
    assert sha256_of({"b": 1, "a": 2}) == sha256_of({"a": 2, "b": 1})
    assert sha256_of({"a": 2}) != sha256_of({"a": 3})


# ------------------------------------------------------------- validation ---


def test_normalize_config_does_not_mutate_defaults():
    """Regression: a shallow copy let per-request writes poison DEFAULT_CONFIG."""
    import copy

    before = copy.deepcopy(DEFAULT_CONFIG)
    cfg = normalize_config(
        {"fire_location": {"latitude": 37.5, "longitude": 28.0}}, preset="firtina"
    )
    # The returned config is fully populated and independent...
    assert cfg["fire_location"]["latitude"] == 37.5
    # ...but the module-level template is untouched.
    assert DEFAULT_CONFIG == before


def test_invalid_config_rejected():
    with pytest.raises(SyntheticError, match="outside bbox"):
        build_dataset(1, config={"fire_location": {"latitude": 10.0}})
    with pytest.raises(SyntheticError, match="step_minutes"):
        build_dataset(1, config={"wind_history": {"step_minutes": 7}})
    with pytest.raises(SyntheticError, match="preset"):
        normalize_config(None, preset="olmayan-preset")
    with pytest.raises(SyntheticError, match="seed"):
        build_dataset("abc")  # type: ignore[arg-type]
    with pytest.raises(SyntheticError, match="unknown types"):
        build_dataset(1, config={"resource_distribution": {"counts": {"gemi": 2}}})


# ------------------------------------------------------- persistence/runs ---


def test_persist_and_cleanup(session):
    data = build_dataset(11, config={"outage_zones": {"count": 2}})
    counts = persist_dataset(session, data)
    session.commit()
    tag = data["meta"]["scenario_tag"]
    assert counts["events"] == 1
    assert counts["silent_regions"] == 2
    assert (
        session.query(FireEvent)
        .filter(  # type: ignore[attr-defined]
            FireEvent.event_key.like(f"%{tag}%")  # type: ignore[attr-defined]
        )
        .count()
        == 1
    )
    event = session.query(FireEvent).first()
    assert event.source == "synthetic"
    assert "SENTETİK" in event.notes
    weather = session.query(WeatherDataPoint).first()
    assert weather.source == "synthetic (EM-104)"
    assert weather.cluster_key == data["fire"]["event_key"].replace("-FIRE", "-WIND")
    resources = (
        session.query(SuppressionResource)
        .filter(SuppressionResource.resource_key.like(f"SYN-{tag}%"))  # type: ignore[attr-defined]
        .all()
    )
    assert resources
    assert session.query(CrewBase).count() >= 1
    deleted = cleanup_scenario(session, tag)
    session.commit()
    assert deleted["fire_events"] == 1
    assert deleted["silent_regions"] == 2
    assert deleted["suppression_resources"] == len(resources)
    assert session.query(FireEvent).count() == 0
    assert session.query(WeatherDataPoint).count() == 0


def test_cleanup_escapes_like_wildcards(session):
    """Regression: a bare '%' tag must not widen DELETE to every synthetic row."""
    data = build_dataset(7, config={"outage_zones": {"count": 1}})
    persist_dataset(session, data)
    # An unrelated synthetic event that a naive '%...%' LIKE would also match.
    session.add(
        FireEvent(
            event_key="SYN-OTHER-FIRE",
            name="other",
            latitude=37.0,
            longitude=28.0,
            min_lat=36.9,
            max_lat=37.1,
            min_lon=27.9,
            max_lon=28.1,
            geometry_wkt="POINT(28.0 37.0)",
            started_at=datetime(2025, 1, 1),
            source="synthetic",
        )
    )
    session.commit()
    # Tag '%bad%' would, unescaped, match every SYNthetic key via the wildcard.
    deleted = cleanup_scenario(session, "syn-%bad%_")
    session.commit()
    assert sum(deleted.values()) == 0
    # Legit rows survive the escaped delete untouched.
    assert (
        session.query(FireEvent)
        .filter(FireEvent.event_key == "SYN-OTHER-FIRE")  # type: ignore[attr-defined]
        .count()
        == 1
    )
    assert (
        session.query(FireEvent)
        .filter(  # type: ignore[attr-defined]
            FireEvent.event_key.like(f"%{data['meta']['scenario_tag']}%")  # type: ignore[attr-defined]
        )
        .count()
        == 1
    )


def test_cleanup_rejects_foreign_tags(session):
    with pytest.raises(SyntheticError, match="syn-"):
        cleanup_scenario(session, "demo-base-001")


def test_record_run_audit_and_dedup(session):
    data = build_dataset(21)
    run = record_run(session, data, persisted=False, preset="standart")
    session.commit()
    again = record_run(session, build_dataset(21), persisted=False)
    assert again.run_key == run.run_key  # same result hash -> one audit row
    assert run.result_hash == data["meta"]["result_hash"]
    assert run.config_hash == data["meta"]["config_hash"]
    assert run.seed == 21
    assert run.preset == "standart"
    assert list_runs(session)[0].run_key == run.run_key


# ------------------------------------------------------------------ api ---


def test_generate_endpoint_deterministic(client):
    payload = {"seed": 99, "preset": "standart", "persist": False}
    first = client.post("/api/v1/scenarios/synthetic/generate", json=payload)
    second = client.post("/api/v1/scenarios/synthetic/generate", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    a, b = first.json(), second.json()
    assert a["run"]["result_hash"] == b["run"]["result_hash"]
    dataset = a["dataset"]
    assert dataset["meta"]["synthetic"] is True
    assert dataset["fire"]["synthetic_label"]
    assert a["persisted_counts"] is None


def test_generate_persist_and_runs_endpoints(client):
    bad = client.post(
        "/api/v1/scenarios/synthetic/generate",
        json={"seed": 1, "config": {"wind_history": {"hours": 9999}}},
    )
    assert bad.status_code == 400
    ok = client.post(
        "/api/v1/scenarios/synthetic/generate",
        json={
            "seed": 5,
            "persist": True,
            "config": {
                "resource_distribution": {"counts": {"crew": 2}, "base_count": 1}
            },
        },
    )
    assert ok.status_code == 200
    assert ok.json()["persisted_counts"]["events"] == 1
    runs = client.get("/api/v1/scenarios/synthetic/runs")
    assert runs.status_code == 200
    items = runs.json()["runs"]
    assert any(r["persisted"] for r in items)
    run_key = items[0]["run_key"]
    detail = client.get(f"/api/v1/scenarios/synthetic/runs/{run_key}")
    assert detail.status_code == 200
    assert detail.json()["record_sample"][0]["synthetic"] is True
    missing = client.get("/api/v1/scenarios/synthetic/runs/synrun-yok")
    assert missing.status_code == 404


def test_presets_endpoint_lists_presets(client):
    response = client.get("/api/v1/scenarios/presets")
    assert response.status_code == 200
    assert response.json()["presets"] == sorted(PRESETS)


def test_cleanup_endpoint(client):
    gen = client.post(
        "/api/v1/scenarios/synthetic/generate",
        json={"seed": 8, "persist": True, "include_dataset": False},
    )
    assert gen.status_code == 200
    tag = gen.json()["run"]["scenario_tag"]
    bad = client.delete("/api/v1/scenarios/synthetic/demo-tag")
    assert bad.status_code == 400
    done = client.delete(f"/api/v1/scenarios/synthetic/{tag}")
    assert done.status_code == 200
    assert done.json()["deleted"]["fire_events"] == 1
