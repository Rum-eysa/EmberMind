"""EM-056 capacity-change what-if tests.

Covers the operator input normalisation (unknown type / negative / non-integer
counts), the scenario capacity arithmetic against EM-028's per-type ha/hour
assumptions, and the re-pricing engine: how the capacity gap and risk band move
per horizon when hypothetical units are added, which incidents the addition
actually resolves, event scoping and the ephemeral HTTP endpoint.
"""
import pytest

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.capacity_whatif import (
    CAPACITY_WHATIF_PANEL,
    CapacityWhatIfError,
    RiskIndexError,
    _validated_added,  # noqa: PLC2701 - direct unit coverage of input guard
    run_capacity_whatif,
    scenario_capacity,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Settings stub; capacity keys omitted so defaults apply (crew 2.0,
    helicopter 12.0, uav 4.0)."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


def _event(session, key="EVT-CW", status="active", lat=38.0, lon=27.0):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} what-if testi",
            latitude=lat,
            longitude=lon,
            min_lat=lat - 0.05,
            max_lat=lat + 0.05,
            min_lon=lon - 0.05,
            max_lon=lon + 0.05,
            geometry_wkt=f"POINT({lon} {lat})",
            status=status,
            started_at=utc_now().replace(tzinfo=None),
        )
    )


def _forecast(session, event, horizon, area_ha):
    session.add(
        FireForecast(
            event_key=event,
            model_name="rothermel_v1",
            latitude=38.0,
            longitude=27.0,
            predicted_area_ha=area_ha,
            geometry_wkt="POLYGON((27 38,27.01 38,27.01 38.01,27 38.01,27 38))",
            forecast_for=utc_now(),
            horizon_minutes=horizon,
            rate_of_spread_m_per_min=10.0,
            spread_direction_deg=45.0,
            inputs_json="{}",
        )
    )


def _resource(session, key, rtype="crew", status="available"):
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


def _seed_gap_scene(session, key="EVT-CW"):
    """One available crew (2.0 ha/h) vs demand 12.0 at T+30 -> open gap 10.0.

    A single added helicopter (+12.0 -> 14.0 scenario capacity) closes the gap,
    so the reinforcement resolves this incident (the EM-056 acceptance case).
    """
    _event(session, key=key)
    _resource(session, f"{key}-C1")
    _forecast(session, key, 30, 6.0)  # demand 12.0


# --------------------------------------------------- input validation ----


def test_validated_added_normalises_and_merges():
    added = _validated_added({" Crew ": 2, "helicopter": 1, "crew": 3, "uav": 0})
    assert added == {"crew": 5, "helicopter": 1}  # zero count dropped, merged


def test_validated_added_rejects_unknown_type():
    with pytest.raises(CapacityWhatIfError, match="unknown resource type"):
        _validated_added({"drone": 2})


def test_validated_added_rejects_negative_count():
    with pytest.raises(CapacityWhatIfError, match="must be >= 0"):
        _validated_added({"crew": -1})


def test_validated_added_rejects_non_integer_count():
    with pytest.raises(CapacityWhatIfError, match="must be an integer"):
        _validated_added({"crew": "two"})


# ------------------------------------------------------ scenario math -----


def test_scenario_capacity_prices_added_units(session):
    _resource(session, "CW-C1")  # one available crew -> current 2.0
    caps = scenario_capacity(session, _Settings(), {"helicopter": 1})
    assert caps["unit"] == "ha/saat"
    assert caps["current_ha_h"] == pytest.approx(2.0)
    assert caps["scenario_ha_h"] == pytest.approx(14.0)  # 2 + 1 * 12.0
    assert caps["delta_ha_h"] == pytest.approx(12.0)
    assert caps["added_breakdown"]["helicopter"]["added_ha_per_hour"] == pytest.approx(
        12.0
    )


def test_scenario_capacity_no_addition_is_identity(session):
    _resource(session, "CW-C1")
    _resource(session, "CW-C2")
    caps = scenario_capacity(session, _Settings(), {})
    assert caps["current_ha_h"] == pytest.approx(4.0)
    assert caps["scenario_ha_h"] == pytest.approx(4.0)
    assert caps["delta_ha_h"] == pytest.approx(0.0)


# ---------------------------------------------------- re-pricing engine ---


def test_run_capacity_whatif_resolves_gap_with_reinforcement(session):
    _seed_gap_scene(session)
    payload = run_capacity_whatif(session, _Settings(), {"helicopter": 1})
    assert payload["panel"] == CAPACITY_WHATIF_PANEL
    assert payload["persistence"] == "none"
    assert payload["added_resources"] == {"helicopter": 1}
    assert payload["capacity"]["scenario_ha_h"] == pytest.approx(14.0)

    event = payload["events"][0]
    peak = event["peak"]
    assert peak["horizon_minutes"] == 30
    assert peak["current_gap_ha_h"] == pytest.approx(10.0)  # 12 - 2
    assert peak["scenario_gap_ha_h"] == pytest.approx(0.0)  # 12 <= 14
    assert peak["gap_delta_ha_h"] == pytest.approx(-10.0)
    assert peak["current_level"] == "kritik"
    assert peak["scenario_level"] == "dikkat"  # 12 / 14 = 0.857
    assert peak["resolves_gap"] is True
    assert event["resolved_by_addition"] is True
    assert payload["summary"]["events_resolved_by_addition"] == 1


def test_run_capacity_whatif_no_addition_leaves_gap(session):
    _seed_gap_scene(session)
    payload = run_capacity_whatif(session, _Settings(), {})
    event = payload["events"][0]
    peak = event["peak"]
    assert peak["current_gap_ha_h"] == pytest.approx(10.0)
    assert peak["scenario_gap_ha_h"] == pytest.approx(10.0)
    assert peak["gap_delta_ha_h"] == pytest.approx(0.0)
    assert peak["resolves_gap"] is False
    assert event["resolved_by_addition"] is False
    assert payload["summary"]["events_resolved_by_addition"] == 0


def test_run_capacity_whatif_partial_reinforcement_keeps_gap(session):
    _seed_gap_scene(session)
    # +1 crew (2 -> 4 ha/h) still far below the 12.0 demand: gap narrows but
    # does not close, so the incident is not "resolved".
    payload = run_capacity_whatif(session, _Settings(), {"crew": 1})
    peak = payload["events"][0]["peak"]
    assert peak["current_gap_ha_h"] == pytest.approx(10.0)
    assert peak["scenario_gap_ha_h"] == pytest.approx(8.0)  # 12 - 4
    assert peak["gap_delta_ha_h"] == pytest.approx(-2.0)
    assert peak["resolves_gap"] is False


def test_run_capacity_whatif_scopes_to_event_key(session):
    _seed_gap_scene(session, key="EVT-A")
    _seed_gap_scene(session, key="EVT-B")
    payload = run_capacity_whatif(
        session, _Settings(), {"helicopter": 1}, event_key="EVT-A"
    )
    assert [event["event_key"] for event in payload["events"]] == ["EVT-A"]


def test_run_capacity_whatif_unknown_event_raises(session):
    _seed_gap_scene(session)
    with pytest.raises(RiskIndexError, match="not found"):
        run_capacity_whatif(session, _Settings(), {"crew": 1}, event_key="EVT-YOK")


def test_run_capacity_whatif_no_active_events(session):
    payload = run_capacity_whatif(session, _Settings(), {"crew": 2})
    assert payload["events"] == []
    assert payload["summary"]["events_scored"] == 0
    assert payload["capacity"]["current_ha_h"] == pytest.approx(0.0)


def test_run_capacity_whatif_event_without_forecast(session):
    _event(session, key="EVT-CW")  # no forecast rows
    payload = run_capacity_whatif(session, _Settings(), {"uav": 1})
    event = payload["events"][0]
    assert event["horizons"] == []
    assert event["peak"] is None
    assert event["resolved_by_addition"] is False


def test_run_capacity_whatif_invalid_type_raises(session):
    _seed_gap_scene(session)
    with pytest.raises(CapacityWhatIfError):
        run_capacity_whatif(session, _Settings(), {"tanker": 1})


# ------------------------------------------------------------ endpoints ---


def test_capacity_whatif_endpoint_scores_seeded_scene(client, session):
    _seed_gap_scene(session)
    session.flush()
    response = client.post(
        "/api/v1/whatif/capacity",
        json={"added_resources": {"helicopter": 1}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["panel"] == CAPACITY_WHATIF_PANEL
    assert data["capacity"]["scenario_ha_h"] == pytest.approx(14.0)
    assert data["events"][0]["resolved_by_addition"] is True


def test_capacity_whatif_endpoint_rejects_unknown_type(client, session):
    _seed_gap_scene(session)
    session.flush()
    response = client.post(
        "/api/v1/whatif/capacity",
        json={"added_resources": {"drone": 1}},
    )
    assert response.status_code == 400
    assert "unknown resource type" in response.json()["detail"]["error"]


def test_capacity_whatif_endpoint_rejects_unknown_event(client, session):
    _seed_gap_scene(session)
    session.flush()
    response = client.post(
        "/api/v1/whatif/capacity",
        json={"added_resources": {"crew": 1}, "event_key": "EVT-YOK"},
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"]["error"]


def test_whatif_config_exposes_capacity_attribution(client):
    response = client.get("/api/v1/whatif/config")
    assert response.status_code == 200
    assert "capacity_attribution" in response.json()


def test_panel_page_embeds_capacity_whatif_card(client):
    response = client.get("/panel")
    assert response.status_code == 200
    html = response.text
    assert 'id="wi-crew"' in html
    assert "/api/v1/whatif/capacity" in html
