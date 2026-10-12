"""EM-108 UI-authored custom scenario editor tests.

Covers authored-scenario validation (slug key, reserved library keys, title,
seed range, EM-104 config validation via the bbox), the per-installation cap,
CRUD (create/update/delete/list/detail), determinism of the stored normalized
config (same seed -> same hash), preview (no persistence), one-click activation
against the operational tables + the ``ScenarioRun`` audit row stamped
``custom:<key>`` and the HTTP endpoints.
"""
import pytest
from sqlalchemy import select

from src.models.spatial import FireEvent
from src.models.synthetic import ScenarioRun
from src.services.scenario_editor import (
    ATTRIBUTION,
    ScenarioEditorError,
    activate,
    create,
    delete,
    detail,
    editor_config,
    list_scenarios,
    preview,
    update,
)
from src.services.synthetic import SYNTHETIC_LABEL


class _Settings:
    """Minimal settings stub (only the authored-scenario cap is consulted)."""

    def __init__(self, max_items=50):  # type: ignore[no-untyped-def]
        self.SCENARIO_EDITOR_MAX_ITEMS = max_items


def _config(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "fire_location": {
            "latitude": 37.5,
            "longitude": 27.5,
            "severity": "high",
        },
        "wind_history": {"base_speed_kmh": 30.0, "base_from_deg": 210.0},
        "outage_zones": {"count": 2},
    }
    base.update(overrides)
    return base


def _create(session, key="koyu-ortasu", **kw):  # type: ignore[no-untyped-def]
    params = {
        "key": key,
        "title": "Kıyı Ortasu Yangını",
        "seed": 404,
        "config": _config(),
    }
    params.update(kw)
    return create(session, _Settings(), **params)


# --------------------------------------------------------------- create ---


def test_create_returns_summary_and_preset(session):
    row = _create(session)
    session.commit()
    assert row["key"] == "koyu-ortasu"
    assert row["archetype"] == "custom"
    assert row["preset"] == "custom:koyu-ortasu"
    assert row["title"] == "Kıyı Ortasu Yangını"


def test_create_stores_normalized_config(session):
    _create(session)
    session.commit()
    payload = detail(session, "koyu-ortasu")
    # normalize_config merged the authored block over the EM-104 defaults, so
    # wind hours/step are present even though the author only set speed/direction.
    assert payload["config"]["wind_history"]["hours"] >= 1
    assert payload["config"]["fire_location"]["latitude"] == pytest.approx(37.5)


def test_create_rejects_bad_key(session):
    with pytest.raises(ScenarioEditorError, match="3-62"):
        _create(session, key="X")


def test_create_rejects_reserved_library_key(session):
    with pytest.raises(ScenarioEditorError, match="built-in library"):
        _create(session, key="sinir-bolgesi")


def test_create_rejects_empty_title(session):
    with pytest.raises(ScenarioEditorError, match="title"):
        _create(session, title="   ")


def test_create_rejects_out_of_range_seed(session):
    with pytest.raises(ScenarioEditorError, match="seed"):
        _create(session, seed=99_999_999)


def test_create_validates_config_via_engine(session):
    bad = _config(
        fire_location={"latitude": 40.0, "longitude": 27.5, "severity": "high"}
    )
    with pytest.raises(ScenarioEditorError):
        _create(session, config=bad)


def test_create_rejects_duplicate_key(session):
    _create(session)
    session.commit()
    with pytest.raises(ScenarioEditorError, match="already exists"):
        _create(session)


def test_create_respects_cap(session):
    create(
        session, _Settings(max_items=2), key="aa-1", title="A", seed=1, config=_config()
    )
    create(
        session, _Settings(max_items=2), key="aa-2", title="B", seed=2, config=_config()
    )
    session.commit()
    with pytest.raises(ScenarioEditorError, match="limit reached"):
        create(
            session,
            _Settings(max_items=2),
            key="aa-3",
            title="C",
            seed=3,
            config=_config(),
        )


# ----------------------------------------------------------- update/read ---


def test_update_changes_fields(session):
    _create(session)
    session.commit()
    row = update(session, "koyu-ortasu", title="Yeni Başlık", seed=999)
    session.commit()
    assert row["title"] == "Yeni Başlık"
    assert row["seed"] == 999


def test_update_validates_config(session):
    _create(session)
    session.commit()
    with pytest.raises(ScenarioEditorError):
        update(session, "koyu-ortasu", config={"wind_history": {"hours": 500}})


def test_delete_then_missing(session):
    _create(session)
    session.commit()
    assert delete(session, "koyu-ortasu")["status"] == "deleted"
    session.commit()
    with pytest.raises(ScenarioEditorError, match="not found"):
        detail(session, "koyu-ortasu")


def test_list_scenarios(session):
    _create(session, key="aa-1")
    _create(session, key="aa-2")
    session.commit()
    items = list_scenarios(session)
    assert {s["key"] for s in items} == {"aa-1", "aa-2"}


# ------------------------------------------------- preview/activation ---


def test_preview_is_deterministic(session):
    _create(session)
    session.commit()
    a = preview(session, "koyu-ortasu")
    b = preview(session, "koyu-ortasu")
    assert a["result_hash"] == b["result_hash"]
    assert a["synthetic_label"] == SYNTHETIC_LABEL


def test_preview_does_not_persist(session):
    _create(session)
    session.commit()
    preview(session, "koyu-ortasu")
    assert session.query(FireEvent).count() == 0


def test_activate_persists_rows_and_run(session):
    _create(session)
    session.commit()
    result = activate(session, "koyu-ortasu")
    session.commit()
    assert result["status"] == "activated"
    assert result["attribution"] == ATTRIBUTION
    tag = result["scenario"]["scenario_tag"]
    assert result["scenario"]["persisted_counts"]["events"] == 1
    matched = (
        session.query(FireEvent)
        .filter(FireEvent.event_key.like(f"%{tag}%"))  # type: ignore[attr-defined]
        .count()
    )
    assert matched == 1
    run = session.scalars(
        select(ScenarioRun).where(
            ScenarioRun.preset == "custom:koyu-ortasu"  # type: ignore[attr-defined]
        )
    ).first()
    assert run is not None
    assert run.persisted == 1
    assert run.result_hash == result["scenario"]["result_hash"]


def test_activate_is_reproducible(session):
    _create(session)
    session.commit()
    first = activate(session, "koyu-ortasu")
    second = activate(session, "koyu-ortasu")
    assert first["scenario"]["result_hash"] == second["scenario"]["result_hash"]


# -------------------------------------------------------------- config ---


def test_editor_config_shape():
    cfg = editor_config(_Settings())
    assert cfg["version"]
    assert cfg["max_items"] == 50
    assert cfg["archetype"] == "custom"
    assert "sinir-bolgesi" in cfg["reserved_keys"]
    assert cfg["synthetic_label"] == SYNTHETIC_LABEL


# ------------------------------------------------------------------- api ---


def test_http_config(client):
    response = client.get("/api/v1/scenarios/custom/config")
    assert response.status_code == 200
    assert "reserved_keys" in response.json()


def test_http_create_list_detail_delete(client):
    created = client.post(
        "/api/v1/scenarios/custom",
        json={"key": "koyu-ortasu", "title": "Kıyı", "seed": 404, "config": _config()},
    )
    assert created.status_code == 200
    assert created.json()["status"] == "created"
    listing = client.get("/api/v1/scenarios/custom")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    got = client.get("/api/v1/scenarios/custom/koyu-ortasu")
    assert got.status_code == 200
    assert got.json()["scenario"]["key"] == "koyu-ortasu"
    deleted = client.delete("/api/v1/scenarios/custom/koyu-ortasu")
    assert deleted.status_code == 200
    assert client.get("/api/v1/scenarios/custom/koyu-ortasu").status_code == 404


def test_http_create_invalid_returns_400(client):
    bad = client.post(
        "/api/v1/scenarios/custom",
        json={"key": "X", "title": "Kıyı", "seed": 404, "config": _config()},
    )
    assert bad.status_code == 400


def test_http_config_validation_returns_400(client):
    bad = client.post(
        "/api/v1/scenarios/custom",
        json={
            "key": "boguk-onu",
            "title": "Kıyı",
            "seed": 404,
            "config": {"fire_location": {"latitude": 40.0}},
        },
    )
    assert bad.status_code == 400


def test_http_preview_and_activate(client):
    client.post(
        "/api/v1/scenarios/custom",
        json={"key": "koyu-ortasu", "title": "Kıyı", "seed": 404, "config": _config()},
    )
    prev = client.get("/api/v1/scenarios/custom/koyu-ortasu/preview")
    assert prev.status_code == 200
    assert prev.json()["synthetic_label"] == SYNTHETIC_LABEL
    act = client.post("/api/v1/scenarios/custom/koyu-ortasu/activate")
    assert act.status_code == 200
    assert act.json()["status"] == "activated"


def test_http_missing_key_returns_404(client):
    assert client.get("/api/v1/scenarios/custom/yok-boyle").status_code == 404
    assert client.post("/api/v1/scenarios/custom/yok-boyle/activate").status_code == 404


def test_openapi_publishes_editor_path(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert "/api/v1/scenarios/custom" in spec.json()["paths"]


# -------------------------------------------------------------------- ui ---


def test_inventory_page_has_editor():
    from pathlib import Path

    html = Path("src/static/inventory.html").read_text(encoding="utf-8")
    assert "Senaryo Düzenleyici" in html
    assert "/api/v1/scenarios/custom" in html
    assert 'id="ed-save"' in html
    assert "function edBuildConfig" in html
