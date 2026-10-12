"""EM-105 ready-made demo scenario library tests.

Covers the curated catalog (archetypes, keys), determinism (same scenario ->
same tag/hash), the settings-driven border anchor (default / override / clamp /
reject), one-click activation + deterministic replay against the operational
tables, activation-run scoping and the HTTP endpoints.
"""
import pytest
from sqlalchemy import select

from src.models.spatial import FireEvent
from src.models.synthetic import ScenarioRun
from src.services.scenario_library import (
    ATTRIBUTION,
    LIBRARY_KEYS,
    ScenarioLibraryError,
    activate,
    activated_runs,
    catalog,
    get_scenario,
    library_config,
    materialize_config,
    preview,
    replay,
)
from src.services.synthetic import SYNTHETIC_LABEL, build_dataset


class _Settings:
    """Minimal read-time settings stub (only the border knob is consulted)."""

    def __init__(self, border_lon=28.85):  # type: ignore[no-untyped-def]
        self.SCENARIO_BORDER_LON = border_lon


# --------------------------------------------------------------- catalog ---


def test_catalog_lists_three_archetypes():
    items = catalog()
    assert len(items) >= 3
    archetypes = {s["archetype"] for s in items}
    assert {
        "coastal_wind_reversal",
        "rural_silent_zone",
        "border_region",
    } <= archetypes
    keys = [s["key"] for s in items]
    assert len(keys) == len(set(keys)) == len(LIBRARY_KEYS)


def test_get_scenario_unknown_raises():
    with pytest.raises(ScenarioLibraryError, match="unknown scenario key"):
        get_scenario("yok-boyle-senaryo")


def test_get_scenario_is_case_insensitive():
    assert get_scenario("Sinir-BolgeSI")["key"] == "sinir-bolgesi"


# --------------------------------------------------------------- preview ---


def test_preview_is_deterministic():
    a = preview("kiyi-ruzgar-donusu", _Settings())
    b = preview("kiyi-ruzgar-donusu", _Settings())
    assert a["scenario_tag"] == b["scenario_tag"]
    assert a["result_hash"] == b["result_hash"]


def test_preview_labels_synthetic():
    result = preview("kirsal-sessiz-bolge", _Settings())
    assert result["synthetic_label"] == SYNTHETIC_LABEL


def test_preview_does_not_persist(session):
    preview("sinir-bolgesi", _Settings())
    assert session.query(FireEvent).count() == 0


def test_coastal_has_wide_wind_reversal():
    scenario = get_scenario("kiyi-ruzgar-donusu")
    cfg = materialize_config(scenario, _Settings())
    assert cfg["wind_history"]["direction_jitter_deg"] >= 60.0
    data = build_dataset(scenario["seed"], cfg)
    assert data["fire"]["longitude"] == pytest.approx(27.25)  # near the coast


def test_rural_wraps_multiple_outage_zones():
    result = preview("kirsal-sessiz-bolge", _Settings())
    assert result["outage_zone_count"] >= 2


# ---------------------------------------------------------------- border ---


def test_border_uses_default_longitude():
    result = preview("sinir-bolgesi", _Settings(28.85))
    assert result["fire"]["longitude"] == pytest.approx(28.85)


def test_border_honours_override():
    result = preview("sinir-bolgesi", _Settings(27.5))
    assert result["fire"]["longitude"] == pytest.approx(27.5)


def test_border_clamped_inside_bbox():
    high = preview("sinir-bolgesi", _Settings(30.0))
    assert high["fire"]["longitude"] <= 28.98
    low = preview("sinir-bolgesi", _Settings(20.0))
    assert low["fire"]["longitude"] >= 27.02


def test_border_rejects_non_numeric():
    with pytest.raises(ScenarioLibraryError, match="numeric"):
        preview("sinir-bolgesi", _Settings("deniz"))


# ----------------------------------------------------- activate / replay ---


def test_activate_persists_rows_and_run(session):
    result = activate(session, "kiyi-ruzgar-donusu", _Settings())
    session.commit()
    assert result["status"] == "activated"
    tag = result["scenario"]["scenario_tag"]
    assert result["scenario"]["persisted_counts"]["events"] == 1
    assert result["attribution"] == ATTRIBUTION
    matched = (
        session.query(FireEvent)
        .filter(FireEvent.event_key.like(f"%{tag}%"))  # type: ignore[attr-defined]
        .count()
    )
    assert matched == 1
    run = session.scalars(
        select(ScenarioRun).where(
            ScenarioRun.preset == "library:kiyi-ruzgar-donusu"  # type: ignore[attr-defined]
        )
    ).first()
    assert run is not None
    assert run.persisted == 1
    assert run.result_hash == result["scenario"]["result_hash"]


def test_replay_is_deterministic_without_duplicates(session):
    first = activate(session, "kirsal-sessiz-bolge", _Settings())
    session.commit()
    second = replay(session, "kirsal-sessiz-bolge", _Settings())
    session.commit()
    assert second["status"] == "replayed"
    assert second["scenario"]["result_hash"] == first["scenario"]["result_hash"]
    assert isinstance(second["rewound"], dict)
    # Rewind + relaunch leaves exactly one fire event for the tag (no dupes).
    tag = second["scenario"]["scenario_tag"]
    assert (
        session.query(FireEvent)
        .filter(FireEvent.event_key.like(f"%{tag}%"))  # type: ignore[attr-defined]
        .count()
        == 1
    )


def test_activated_runs_scope_and_prefix(session):
    activate(session, "kirsal-sessiz-bolge", _Settings())
    activate(session, "sinir-bolgesi", _Settings())
    session.commit()
    all_runs = activated_runs(session)
    assert len(all_runs) >= 2
    assert all(str(r.preset or "").startswith("library:") for r in all_runs)
    scoped = activated_runs(session, key="kirsal-sessiz-bolge")
    assert scoped
    assert all(r.preset == "library:kirsal-sessiz-bolge" for r in scoped)


def test_activated_runs_unknown_key_raises(session):
    with pytest.raises(ScenarioLibraryError):
        activated_runs(session, key="olmayan-anahtar")


# ------------------------------------------------------------ library cfg ---


def test_library_config_summary():
    cfg = library_config(_Settings())
    assert cfg["count"] >= 3
    assert cfg["border_lon"] == pytest.approx(28.85)
    assert cfg["version"]
    assert cfg["attribution"] == ATTRIBUTION
    assert cfg["synthetic_label"] == SYNTHETIC_LABEL


# ------------------------------------------------------------------- api ---


def test_http_library_catalog(client):
    response = client.get("/api/v1/scenarios/library")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 3
    assert "border_lon" in body
    assert {s["key"] for s in body["scenarios"]} == set(LIBRARY_KEYS)


def test_http_scenario_detail_does_not_persist(client):
    ok = client.get("/api/v1/scenarios/library/sinir-bolgesi")
    assert ok.status_code == 200
    assert ok.json()["synthetic_label"] == SYNTHETIC_LABEL
    missing = client.get("/api/v1/scenarios/library/yok")
    assert missing.status_code == 404


def test_http_activate_replay_and_runs(client):
    act = client.post("/api/v1/scenarios/library/kiyi-ruzgar-donusu/activate")
    assert act.status_code == 200
    assert act.json()["status"] == "activated"
    rep = client.post("/api/v1/scenarios/library/kiyi-ruzgar-donusu/replay")
    assert rep.status_code == 200
    assert rep.json()["status"] == "replayed"
    runs = client.get("/api/v1/scenarios/library/runs")
    assert runs.status_code == 200
    assert runs.json()["count"] >= 1
    scoped = client.get("/api/v1/scenarios/library/runs?key=kiyi-ruzgar-donusu")
    assert scoped.status_code == 200
    assert all(
        r["preset"] == "library:kiyi-ruzgar-donusu" for r in scoped.json()["runs"]
    )
    bad = client.get("/api/v1/scenarios/library/runs?key=yok-boyle")
    assert bad.status_code == 404


def test_openapi_publishes_library_path(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert "/api/v1/scenarios/library" in spec.json()["paths"]
