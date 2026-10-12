"""EM-059 saved/shareable what-if scenario tests.

Covers the service layer (validation of kind/params, CRUD, share-token
lifecycle) and the HTTP endpoints, plus the operator_map.html integration that
lets a commander name a run, reload it and hand it to the team as a link.
"""
import pytest

from src.services.scenario_share import (
    ScenarioError,
    create_scenario,
    delete_scenario,
    disable_share,
    enable_share,
    get_by_share_token,
    get_scenario,
    list_scenarios,
    rename_scenario,
)

WIND_PARAMS = {
    "latitude": 37.0,
    "longitude": 27.5,
    "wind_rotation_delta_deg": 45,
    "wind_speed_factor": 1.2,
}


# --- service: creation + validation ---------------------------------------
def test_create_wind_scenario(session):
    row = create_scenario(session, name="Karadag 45", kind="wind", params=WIND_PARAMS)
    assert row["scenario_key"].startswith("wsc-")
    assert row["kind"] == "wind"
    assert row["name"] == "Karadag 45"
    assert row["params"]["latitude"] == 37.0
    assert row["shared"] is False


def test_create_requires_name(session):
    with pytest.raises(ScenarioError):
        create_scenario(session, name="  ", kind="wind", params=WIND_PARAMS)


def test_create_rejects_long_name(session):
    with pytest.raises(ScenarioError):
        create_scenario(session, name="x" * 121, kind="wind", params=WIND_PARAMS)


def test_create_rejects_unknown_kind(session):
    with pytest.raises(ScenarioError):
        create_scenario(session, name="n", kind="flood", params=WIND_PARAMS)


def test_create_wind_needs_ignition_point(session):
    with pytest.raises(ScenarioError):
        create_scenario(session, name="n", kind="wind", params={"wind_speed_factor": 1})


def test_create_capacity_needs_added_resources(session):
    with pytest.raises(ScenarioError):
        create_scenario(session, name="n", kind="capacity", params={})
    row = create_scenario(
        session,
        name="Ilave ekip",
        kind="capacity",
        params={"added_resources": {"crew": 3}},
    )
    assert row["kind"] == "capacity"
    assert row["params"]["added_resources"]["crew"] == 3


# --- service: read + list + rename ----------------------------------------
def test_list_filters(session):
    create_scenario(session, name="a", kind="wind", params=WIND_PARAMS, event_key="ev1")
    create_scenario(
        session, name="b", kind="capacity", params={"added_resources": {"a": 1}}
    )
    assert len(list_scenarios(session)) == 2
    wind_only = list_scenarios(session, kind="wind")
    assert [s["name"] for s in wind_only] == ["a"]
    ev_only = list_scenarios(session, event_key="ev1")
    assert len(ev_only) == 1


def test_get_scenario_and_missing(session):
    row = create_scenario(session, name="a", kind="wind", params=WIND_PARAMS)
    assert get_scenario(session, row["scenario_key"])["name"] == "a"
    with pytest.raises(ScenarioError):
        get_scenario(session, "wsc-does-not-exist")


def test_rename_validation(session):
    row = create_scenario(session, name="old", kind="wind", params=WIND_PARAMS)
    assert rename_scenario(session, row["scenario_key"], "new")["name"] == "new"
    with pytest.raises(ScenarioError):
        rename_scenario(session, row["scenario_key"], "   ")


# --- service: share token lifecycle ---------------------------------------
def test_share_then_by_token_then_revoke(session):
    row = create_scenario(session, name="share me", kind="wind", params=WIND_PARAMS)
    key = row["scenario_key"]

    shared = enable_share(session, key)
    assert shared["shared"] is True
    assert shared["share_path"].endswith(shared["share_token"])

    fetched = get_by_share_token(session, shared["share_token"])
    assert fetched["scenario_key"] == key

    revoked = disable_share(session, key)
    assert revoked["shared"] is False
    with pytest.raises(ScenarioError):
        get_by_share_token(session, shared["share_token"])


def test_share_is_stable_token(session):
    row = create_scenario(session, name="s", kind="wind", params=WIND_PARAMS)
    first = enable_share(session, row["scenario_key"])["share_token"]
    second = enable_share(session, row["scenario_key"])["share_token"]
    assert first == second  # re-share does not rotate the token


def test_by_token_invalid(session):
    with pytest.raises(ScenarioError):
        get_by_share_token(session, "nope")


def test_delete_scenario(session):
    row = create_scenario(session, name="del", kind="wind", params=WIND_PARAMS)
    assert delete_scenario(session, row["scenario_key"]) is True
    assert delete_scenario(session, row["scenario_key"]) is False


# --- HTTP endpoints --------------------------------------------------------
def test_endpoint_config(client):
    res = client.get("/api/v1/whatif/scenarios/config")
    assert res.status_code == 200
    assert "wind" in res.json()["kinds"]


def test_endpoint_create_and_list(client):
    res = client.post(
        "/api/v1/whatif/scenarios",
        json={"name": "Run A", "kind": "wind", "params": WIND_PARAMS},
    )
    assert res.status_code == 200
    key = res.json()["scenario"]["scenario_key"]
    listing = client.get("/api/v1/whatif/scenarios?kind=wind")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert client.get(f"/api/v1/whatif/scenarios/{key}").status_code == 200


def test_endpoint_create_invalid_is_400(client):
    res = client.post(
        "/api/v1/whatif/scenarios",
        json={"name": "no point", "kind": "wind", "params": {"wind_speed_factor": 1}},
    )
    assert res.status_code == 400


def test_endpoint_missing_is_404(client):
    assert client.get("/api/v1/whatif/scenarios/wsc-absent").status_code == 404
    assert client.get("/api/v1/whatif/scenarios/by-token/zzz").status_code == 404


def test_endpoint_share_flow(client):
    created = client.post(
        "/api/v1/whatif/scenarios",
        json={"name": "S", "kind": "wind", "params": WIND_PARAMS},
    ).json()["scenario"]
    shared = client.post(f"/api/v1/whatif/scenarios/{created['scenario_key']}/share")
    assert shared.status_code == 200
    path = shared.json()["scenario"]["share_path"]
    by_token = client.get(path)
    assert by_token.status_code == 200
    assert by_token.json()["scenario"]["scenario_key"] == created["scenario_key"]

    unshared = client.delete(
        f"/api/v1/whatif/scenarios/{created['scenario_key']}/share"
    )
    assert unshared.status_code == 200
    assert client.get(path).status_code == 404


def test_endpoint_delete(client):
    created = client.post(
        "/api/v1/whatif/scenarios",
        json={"name": "D", "kind": "wind", "params": WIND_PARAMS},
    ).json()["scenario"]
    key = created["scenario_key"]
    assert client.delete(f"/api/v1/whatif/scenarios/{key}").status_code == 200
    assert client.delete(f"/api/v1/whatif/scenarios/{key}").status_code == 404


# --- UI integration --------------------------------------------------------
def test_operator_map_has_scenario_toolbar():
    from pathlib import Path

    from tests.ui_bundle import operator_map_bundle

    html = operator_map_bundle()
    assert 'id="whatif-scenario"' in html
    assert 'id="whatif-scen-save"' in html
    assert "/api/v1/whatif/scenarios" in html
    assert "function shareScenario" in html
