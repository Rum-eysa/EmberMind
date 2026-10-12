"""EM-050 constraint-based positioning optimisation tests.

Proposals that violate a declared operating limit must never reach the
commander: menzil (``range_km``), mesai/yakıt (``shift_minutes``), the night
ban (``night_capable`` False + arrival inside the night window) and origins
left unreachable by active road closures are filtered out and surface with the
violated constraint names + a human reason. Resources without declared limits
keep proposing exactly as before (backward compatibility with EM-052/EM-046).
"""
from datetime import datetime, timezone

import pytest

from src.models.inventory import SuppressionResource
from src.models.road_network import CrewBase
from src.services.positioning import (
    CONSTRAINT_NAMES,
    _assess_constraints,
    build_proposals,
)
from src.services.road_network import upsert_segments
from tests.unit.test_positioning import (
    ISLAND_1,
    NODE_A,
    NODE_B,
    NODE_C,
    _asset,
    _base,
    _event,
    _network,
)


def _rejected_origin(key, coord, **limits):
    origin = {
        "resource_key": key,
        "name": key,
        "resource_type": "crew",
        "kind": "suppression_resource",
        "coord": coord,
    }
    origin.update(limits)
    return origin


# ------------------------------------------------------- pure assessment ---


def test_assess_flags_range_shift_and_night_together():
    origin = _rejected_origin(
        "r1", NODE_A, range_km=5.0, shift_minutes=10.0, night_capable=False
    )
    night_now = datetime(2025, 7, 1, 21, 0, tzinfo=timezone.utc)
    breach = _assess_constraints(origin, 30.0, 10.0, night_now, True)
    assert breach is not None
    assert breach[0] == ["range", "shift", "night"]
    assert "menzil" in breach[1] and "mesai" in breach[1] and "gece" in breach[1]


def test_assess_null_limits_never_reject():
    origin = _rejected_origin("r2", NODE_A)
    noon = datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert _assess_constraints(origin, 999.0, 999.0, noon, True) is None


def test_assess_night_ban_disable_and_daytime_pass():
    origin = _rejected_origin("r3", NODE_A, night_capable=False)
    night_now = datetime(2025, 7, 1, 22, 0, tzinfo=timezone.utc)
    assert _assess_constraints(origin, 10.0, 10.0, night_now, False) is None
    noon = datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert _assess_constraints(origin, 10.0, 10.0, noon, True) is None


# ------------------------------------------------------------- filtering ---


def _seed_mixed(session):
    upsert_segments(session, _network())
    _base(session, "fast", NODE_A)
    _base(session, "island", ISLAND_1)  # disconnected -> road_closure reject
    _event(session)
    session.flush()


def test_filter_mode_drops_unreachable_into_rejected(session):
    _seed_mixed(session)
    _asset(session, "far", NODE_A, rtype="crew")
    session.flush()
    far = session.query(SuppressionResource).filter_by(resource_key="far").one()
    far.range_km = 0.01  # menzil much smaller than the ~2.2 km route
    session.flush()
    rejected: list[dict] = []
    proposals = build_proposals(session, None, "EVT-1", rejected_out=rejected)
    keys = {p["resource_key"] for p in proposals}
    assert keys == {"fast"}
    by_key = {r["resource_key"]: r for r in rejected}
    assert by_key["island"]["constraints"] == ["road_closure"]
    assert by_key["far"]["constraints"] == ["range"]
    assert "menzil" in by_key["far"]["reason"]
    assert by_key["far"]["eta_minutes"] is not None


def test_shift_limit_rejects_road_origin(session):
    _seed_mixed(session)
    _base(session, "slow", NODE_C)  # residential branch, ~8 min ETA
    _asset(session, "tired", NODE_A, rtype="crew")
    session.flush()
    tired = session.query(SuppressionResource).filter_by(resource_key="tired").one()
    tired.shift_minutes = 1.0  # duty window shorter than the fastest route
    session.flush()
    rejected: list[dict] = []
    proposals = build_proposals(session, None, "EVT-1", rejected_out=rejected)
    assert "tired" not in {p["resource_key"] for p in proposals}
    shift_rej = next(r for r in rejected if r["resource_key"] == "tired")
    assert shift_rej["constraints"] == ["shift"]


def test_night_ban_rejects_airborne_asset_by_arrival(session):
    _seed_mixed(session)
    _asset(session, "heli1", NODE_B, rtype="helicopter")
    session.flush()
    heli = session.query(SuppressionResource).filter_by(resource_key="heli1").one()
    heli.night_capable = False
    session.flush()
    night_now = datetime(2025, 7, 1, 23, 0, tzinfo=timezone.utc)
    rejected: list[dict] = []
    proposals = build_proposals(
        session, None, "EVT-1", now_utc=night_now, rejected_out=rejected
    )
    assert "heli1" not in {p["resource_key"] for p in proposals}
    night_rej = next(r for r in rejected if r["resource_key"] == "heli1")
    assert night_rej["constraints"] == ["night"]
    # Daytime arrival passes the very same limit.
    day_rejected: list[dict] = []
    proposals = build_proposals(
        session,
        None,
        "EVT-1",
        now_utc=datetime(2025, 7, 1, 9, 0, tzinfo=timezone.utc),
        rejected_out=day_rejected,
    )
    assert "heli1" in {p["resource_key"] for p in proposals}


def test_no_sink_keeps_em052_contract_and_annotates_violations(session):
    _seed_mixed(session)
    _base(session, "shortleg", NODE_A)
    session.flush()
    base = session.query(CrewBase).filter_by(base_key="shortleg").one()
    base.range_km = 0.01  # a crew base can carry limits too
    session.flush()
    proposals = build_proposals(session, None, "EVT-1")  # EM-046 explain mode
    by_key = {p["resource_key"]: p for p in proposals}
    # Unreachable stays listed last exactly as before, now annotated.
    assert list(by_key)[-1] == "island"
    assert by_key["island"]["reachable"] is False
    assert by_key["island"]["constraint_violations"] == ["road_closure"]
    assert by_key["shortleg"]["constraint_violations"] == ["range"]
    assert "menzil" in by_key["shortleg"]["constraint_reason"]
    # Clean origins carry no violation keys at all (contract untouched).
    assert "constraint_violations" not in by_key["fast"]


# ------------------------------------------------------------ endpoint ---


def _seed_endpoint(session):
    _seed_mixed(session)
    _asset(session, "far", NODE_A, rtype="crew")
    session.flush()
    far = session.query(SuppressionResource).filter_by(resource_key="far").one()
    far.range_km = 0.01
    session.commit()


def test_endpoint_exposes_rejected_proposals(client, session):
    _seed_endpoint(session)
    body = client.get("/api/v1/positioning/proposals?event_key=EVT-1").json()
    keys = {p["resource_key"] for p in body["proposals"]}
    assert "far" not in keys and "island" not in keys
    assert body["rejected_count"] == len(body["rejected"]) == 2
    by_key = {r["resource_key"]: r for r in body["rejected"]}
    assert by_key["far"]["constraints"] == ["range"]
    assert by_key["island"]["constraints"] == ["road_closure"]


def test_endpoint_constraints_config(client):
    body = client.get("/api/v1/positioning/constraints").json()
    assert body["constraints"] == list(CONSTRAINT_NAMES)
    assert body["night_ban_enabled"] is True
    assert body["unbounded_means_unknown"] is True
    assert body["resource_count_limit"] >= 1
    assert "menzil" in body["fields"]["range_km"]


def test_endpoint_unknown_event_still_404(client):
    res = client.get("/api/v1/positioning/proposals?event_key=NOPE")
    assert res.status_code == 404


# ------------------------------------------------------------- inventory ---


def test_inventory_persists_and_validates_limits(client, session):
    created = client.post(
        "/api/v1/resources",
        json={
            "resource_key": "EM50-1",
            "resource_type": "helicopter",
            "latitude": 38.0,
            "longitude": 27.0,
            "range_km": 40,
            "shift_minutes": 90,
            "night_capable": False,
        },
    )
    assert created.status_code == 200
    resource = created.json()["resource"]
    assert resource["range_km"] == 40.0
    assert resource["shift_minutes"] == 90.0
    assert resource["night_capable"] is False
    updated = client.put(
        "/api/v1/resources/EM50-1", json={"range_km": None, "night_capable": True}
    )
    assert updated.status_code == 200
    # exclude_none on the route means None clears nothing; bool flips fine.
    assert updated.json()["resource"]["night_capable"] is True
    bad = client.post(
        "/api/v1/resources",
        json={
            "resource_key": "EM50-BAD",
            "resource_type": "crew",
            "latitude": 38.0,
            "longitude": 27.0,
            "range_km": -5,
        },
    )
    assert bad.status_code == 400


# ------------------------------------------------------------------ ui ---


def test_ui_wires_rejected_proposals():
    from pathlib import Path

    from tests.ui_bundle import operator_map_bundle

    html = operator_map_bundle()
    assert "loadRejectedProposals" in html
    assert "positioning-rejected" in html
    assert "rj-item" in html
    inv = Path("src/static/inventory.html").read_text(encoding="utf-8")
    assert "r-range" in inv
    assert "r-shift" in inv
    assert "r-night" in inv
