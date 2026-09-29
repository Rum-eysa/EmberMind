"""EM-028 capacity unit definition, normalisation and endpoint tests."""
import pytest

from src.models.inventory import SuppressionResource
from src.services.capacity import (
    CapacityError,
    available_counts_by_type,
    effective_capacity,
    ensure_defaults,
    list_assumptions,
    update_assumptions,
)
from src.services.risk_panel import build_capacity_risk_panel

# Settings stub: only the threshold is needed; the ha/hour defaults fall back
# to the service constants when the capacity keys are absent.
CREW_DEFAULT = 2.0
HELI_DEFAULT = 12.0
UAV_DEFAULT = 4.0


class _Settings:
    RISK_PANEL_THRESHOLD = 30.0


def _resource(session, key, rtype, status):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key,
            resource_type=rtype,
            latitude=37.0,
            longitude=28.0,
            status=status,
            capacity=1.0,
        )
    )


def test_ensure_defaults_seeds_three_types(session):
    ensure_defaults(session, _Settings())
    values = list_assumptions(session, _Settings())
    types = {a["resource_type"] for a in values["assumptions"]}
    assert types == {"crew", "helicopter", "uav"}
    assert values["unit"] == "ha/saat"


def test_ensure_defaults_is_idempotent(session):
    ensure_defaults(session, _Settings())
    ensure_defaults(session, _Settings())
    assert len(list_assumptions(session, _Settings())["assumptions"]) == 3


def test_list_assumptions_exposes_config_defaults(session):
    values = list_assumptions(session, _Settings())
    assert values["defaults"] == {
        "crew": CREW_DEFAULT,
        "helicopter": HELI_DEFAULT,
        "uav": UAV_DEFAULT,
    }


def test_update_assumptions_persists_edit(session):
    result = update_assumptions(session, _Settings(), {"crew": 3.5})
    crew = next(a for a in result["assumptions"] if a["resource_type"] == "crew")
    assert crew["ha_per_hour"] == pytest.approx(3.5)
    # Re-reading reflects the persisted change, not the config default.
    again = list_assumptions(session, _Settings())
    crew2 = next(a for a in again["assumptions"] if a["resource_type"] == "crew")
    assert crew2["ha_per_hour"] == pytest.approx(3.5)


def test_update_assumptions_accepts_turkish_alias(session):
    result = update_assumptions(session, _Settings(), {"ekip": 5.0})
    crew = next(a for a in result["assumptions"] if a["resource_type"] == "crew")
    assert crew["ha_per_hour"] == pytest.approx(5.0)


def test_update_assumptions_rejects_unknown_type(session):
    with pytest.raises(CapacityError):
        update_assumptions(session, _Settings(), {"submarine": 1.0})


def test_update_assumptions_rejects_negative(session):
    with pytest.raises(CapacityError):
        update_assumptions(session, _Settings(), {"crew": -1.0})


def test_update_assumptions_rejects_empty(session):
    with pytest.raises(CapacityError):
        update_assumptions(session, _Settings(), {})


def test_available_counts_only_counts_available(session):
    _resource(session, "EK1", "crew", "available")
    _resource(session, "EK2", "crew", "available")
    _resource(session, "EK3", "crew", "deployed")
    _resource(session, "HEL1", "helicopter", "available")
    session.flush()
    counts = available_counts_by_type(session)
    assert counts == {"crew": 2, "helicopter": 1}


def test_effective_capacity_normalises_to_ha_per_hour(session):
    _resource(session, "EK1", "crew", "available")
    _resource(session, "EK2", "crew", "available")
    _resource(session, "EK3", "crew", "deployed")  # not counted
    _resource(session, "HEL1", "helicopter", "available")
    session.flush()
    eff = effective_capacity(session, _Settings())
    assert eff["unit"] == "ha/saat"
    assert eff["by_type"]["crew"]["effective_ha_per_hour"] == pytest.approx(
        2 * CREW_DEFAULT
    )
    assert eff["by_type"]["helicopter"]["effective_ha_per_hour"] == pytest.approx(
        HELI_DEFAULT
    )
    assert eff["total_effective_ha_per_hour"] == pytest.approx(
        2 * CREW_DEFAULT + HELI_DEFAULT
    )


def test_panel_payload_includes_capacity_unit_view(session):
    payload = build_capacity_risk_panel(session, _Settings())
    assert payload["capacity"]["assumptions"]["unit"] == "ha/saat"
    assert "total_effective_ha_per_hour" in payload["capacity"]["effective"]


def test_assumptions_endpoint_roundtrip(client):
    got = client.get("/api/v1/capacity/assumptions")
    assert got.status_code == 200
    body = got.json()
    assert len(body["assumptions"]) == 3
    assert "attribution" in body

    put = client.put("/api/v1/capacity/assumptions", json={"uav": 6.0, "crew": 1.5})
    assert put.status_code == 200
    updated = {a["resource_type"]: a["ha_per_hour"] for a in put.json()["assumptions"]}
    assert updated["uav"] == pytest.approx(6.0)
    assert updated["crew"] == pytest.approx(1.5)

    refetch = client.get("/api/v1/capacity/assumptions").json()
    values = {a["resource_type"]: a["ha_per_hour"] for a in refetch["assumptions"]}
    assert values["uav"] == pytest.approx(6.0)


def test_assumptions_endpoint_rejects_bad_type(client):
    bad = client.put("/api/v1/capacity/assumptions", json={"submarine": 1.0})
    assert bad.status_code == 400


def test_effective_endpoint_reports_ha_per_hour(client):
    res = client.get("/api/v1/capacity/effective")
    assert res.status_code == 200
    assert res.json()["capacity"]["unit"] == "ha/saat"
