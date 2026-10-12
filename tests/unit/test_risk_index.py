"""EM-029 operational risk index tests.

Covers the ha/hour demand normalisation, the configurable severity bands and
their boundaries, the per-event/per-horizon payload (peak, summary, gap), the
zero-capacity case, busy-resource exclusion, newest-run forecast selection and
the HTTP endpoints (including the panel page wiring).
"""
import pytest

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.risk_index import (
    RISK_LEVELS,
    RiskIndexError,
    capacity_gap_timeline,
    classify_risk,
    compute_risk_index,
    demand_ha_h,
    level_thresholds,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Settings stub with the EM-029 bands and the 30/60/120 dk horizons.

    The capacity ha/hour keys are omitted on purpose so the service falls back
    to its defaults (crew 2.0, helicopter 12.0, uav 4.0).
    """

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


def _event(session, key="EVT-RI", status="active", lat=38.0, lon=27.0):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} risk testi",
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


def _seed_standard_scene(session):
    """Six available crews (6 x 2.0 = 12.0 ha/h total) and forecasts 6/9/10.8.

    Demand per horizon is 12/9/5.4 ha/h -> risk 1.0/0.75/0.45 covering three
    distinct severity bands, and 0.9 sits exactly on the dikkat boundary.
    """
    _event(session)
    for index in range(1, 7):
        _resource(session, f"RI-C{index}")
    _forecast(session, "EVT-RI", 30, 6.0)
    _forecast(session, "EVT-RI", 60, 9.0)
    _forecast(session, "EVT-RI", 120, 10.8)


# ------------------------------------------------------------ pure math ---


def test_demand_normalises_area_to_hectare_per_hour():
    assert demand_ha_h(6.0, 30) == pytest.approx(12.0)
    assert demand_ha_h(10.8, 120) == pytest.approx(5.4)
    # A non-positive horizon cannot define a growth rate.
    assert demand_ha_h(5.0, 0) == 0.0


def test_level_thresholds_read_configurable_bands():
    thresholds = level_thresholds(_Settings())
    assert thresholds == {
        "normal_max": 0.6,
        "caution_max": 0.9,
        "critical_near_max": 1.2,
    }


def test_level_thresholds_fall_back_when_settings_omit_keys():
    class _Empty:
        pass

    thresholds = level_thresholds(_Empty())
    assert thresholds["normal_max"] == pytest.approx(0.6)
    assert thresholds["critical_near_max"] == pytest.approx(1.2)


def test_classify_risk_band_boundaries():
    thresholds = level_thresholds(_Settings())
    assert classify_risk(0.59, thresholds) == "normal"
    assert classify_risk(0.6, thresholds) == "dikkat"
    assert classify_risk(0.89, thresholds) == "dikkat"
    assert classify_risk(0.9, thresholds) == "kritik-yakin"
    assert classify_risk(1.19, thresholds) == "kritik-yakin"
    assert classify_risk(1.2, thresholds) == "kritik"
    # Missing capacity (None) with a real demand is the worst band.
    assert classify_risk(None, thresholds) == "kritik"


# ------------------------------------------------------ payload shape -----


def test_compute_risk_index_payload_and_bands(session):
    _seed_standard_scene(session)
    payload = compute_risk_index(session, _Settings())
    assert payload["panel"] == "risk_index"
    assert payload["unit"] == "ha/saat"
    assert payload["levels"] == list(RISK_LEVELS)
    assert payload["horizon_minutes"] == [30, 60, 120]
    assert payload["capacity_effective_ha_h"] == pytest.approx(12.0)

    event = payload["events"][0]
    assert event["event_key"] == "EVT-RI"
    rows = {row["horizon_minutes"]: row for row in event["horizons"]}
    assert rows[30]["demand_ha_h"] == pytest.approx(12.0)
    assert rows[30]["risk_index"] == pytest.approx(1.0)
    assert rows[30]["level"] == "kritik-yakin"
    assert rows[60]["risk_index"] == pytest.approx(0.75)
    assert rows[60]["level"] == "dikkat"
    assert rows[120]["risk_index"] == pytest.approx(0.45)
    assert rows[120]["level"] == "normal"
    # Demand at or below capacity implies no gap.
    assert rows[30]["gap_ha_h"] == pytest.approx(0.0)
    assert event["peak_risk_index"] == pytest.approx(1.0)
    assert event["peak_level"] == "kritik-yakin"
    assert event["peak_horizon_minutes"] == 30

    summary = payload["summary"]
    assert summary["events_scored"] == 1
    assert summary["events_with_forecast"] == 1
    assert summary["max_risk_event"] == "EVT-RI"
    assert summary["level_counts"]["kritik-yakin"] == 1


def test_gap_reported_when_demand_outgrows_capacity(session):
    _event(session)
    _resource(session, "RI-C1")  # single crew -> 2.0 ha/h effective
    _forecast(session, "EVT-RI", 30, 6.0)  # demand 12.0 -> gap 10.0
    payload = compute_risk_index(session, _Settings())
    row = payload["events"][0]["horizons"][0]
    assert row["demand_ha_h"] == pytest.approx(12.0)
    assert row["gap_ha_h"] == pytest.approx(10.0)
    assert row["risk_index"] == pytest.approx(6.0)
    assert row["level"] == "kritik"


def test_zero_capacity_marks_unmeasurable_risk_as_critical(session):
    _event(session)
    _forecast(session, "EVT-RI", 30, 6.0)
    payload = compute_risk_index(session, _Settings())
    assert payload["capacity_effective_ha_h"] == pytest.approx(0.0)
    row = payload["events"][0]["horizons"][0]
    assert row["risk_index"] is None
    assert row["level"] == "kritik"
    assert payload["events"][0]["peak_level"] == "kritik"


def test_zero_demand_with_zero_capacity_is_zero_risk(session):
    _event(session)
    _forecast(session, "EVT-RI", 30, 0.0)
    payload = compute_risk_index(session, _Settings())
    row = payload["events"][0]["horizons"][0]
    assert row["risk_index"] == pytest.approx(0.0)
    assert row["level"] == "normal"


# ------------------------------------------------------ data selection ----


def test_busy_resources_are_excluded_from_capacity(session):
    _event(session)
    _resource(session, "RI-C1")
    _resource(session, "RI-C2", status="deployed")
    _resource(session, "RI-C3", status="en_route")
    _resource(session, "RI-H1", rtype="helicopter", status="maintenance")
    _forecast(session, "EVT-RI", 30, 6.0)
    payload = compute_risk_index(session, _Settings())
    # Only the one available crew (2.0 ha/h) counts: 12.0 / 2.0 -> 6.0.
    assert payload["capacity_effective_ha_h"] == pytest.approx(2.0)
    row = payload["events"][0]["horizons"][0]
    assert row["risk_index"] == pytest.approx(6.0)
    assert row["level"] == "kritik"


def test_newest_forecast_run_wins_per_horizon(session):
    _event(session)
    _resource(session, "RI-C1")  # 2.0 ha/h
    _forecast(session, "EVT-RI", 30, 100.0)
    _forecast(session, "EVT-RI", 30, 6.0)  # newer run (higher id)
    payload = compute_risk_index(session, _Settings())
    row = payload["events"][0]["horizons"][0]
    assert row["area_ha"] == pytest.approx(6.0)
    assert row["risk_index"] == pytest.approx(6.0)


def test_only_active_events_are_scored(session):
    _event(session, key="EVT-ACTIVE")
    _event(session, key="EVT-DONE", status="contained")
    payload = compute_risk_index(session, _Settings())
    keys = [event["event_key"] for event in payload["events"]]
    assert keys == ["EVT-ACTIVE"]
    assert payload["summary"]["events_scored"] == 1


def test_event_without_forecasts_scores_empty(session):
    _event(session)
    payload = compute_risk_index(session, _Settings())
    event = payload["events"][0]
    assert event["horizons"] == []
    assert event["peak_risk_index"] is None
    assert event["peak_level"] == "normal"
    assert payload["summary"]["events_with_forecast"] == 0


def test_explicit_event_key_scores_even_inactive_event(session):
    _event(session, key="EVT-OLD", status="contained")
    _forecast(session, "EVT-OLD", 30, 3.0)
    payload = compute_risk_index(session, _Settings(), event_key="EVT-OLD")
    assert [event["event_key"] for event in payload["events"]] == ["EVT-OLD"]


def test_unknown_event_key_raises(session):
    with pytest.raises(RiskIndexError, match="not found"):
        compute_risk_index(session, _Settings(), event_key="EVT-YOK")


# ------------------------------------------------------------ endpoints ---


def test_risk_index_config_endpoint(client):
    response = client.get("/api/v1/risk-index/config")
    assert response.status_code == 200
    data = response.json()
    assert data["levels"] == list(RISK_LEVELS)
    assert 0.0 < data["thresholds"]["normal_max"] <= 0.9
    assert data["horizon_minutes"]


def test_risk_index_endpoint_scores_seeded_scene(client, session):
    _seed_standard_scene(session)
    session.flush()
    response = client.get("/api/v1/risk-index")
    assert response.status_code == 200
    data = response.json()
    assert data["panel"] == "risk_index"
    assert data["events"][0]["event_key"] == "EVT-RI"
    assert len(data["events"][0]["horizons"]) == 3


def test_risk_index_endpoint_returns_404_for_unknown_event(client, session):
    _event(session)
    session.flush()
    response = client.get("/api/v1/risk-index", params={"event_key": "EVT-YOK"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]["error"]


def test_panel_page_embeds_risk_index_card(client):
    response = client.get("/panel")
    assert response.status_code == 200
    html = response.text
    assert 'id="risk-index"' in html
    assert "/api/v1/risk-index" in html


# ---------------------------------------------------- EM-030 timeline -----


def _seed_timeline_scene(session):
    """Five crews (10.0 ha/h) with demand 4/6/15 ha/h across 30/60/120.

    Risk ratio is 0.4/0.6/1.5, so the kritik band (>=1.2) is first crossed
    between the 60 and 120 dk horizons; linear interpolation lands on T+100.
    """
    _event(session, key="EVT-TL")
    for index in range(1, 6):
        _resource(session, f"TL-C{index}")
    _forecast(session, "EVT-TL", 30, 2.0)  # 2/30*60 = 4.0
    _forecast(session, "EVT-TL", 60, 6.0)  # 6/60*60 = 6.0
    _forecast(session, "EVT-TL", 120, 30.0)  # 30/120*60 = 15.0


def test_timeline_series_shape_and_gap(session):
    _seed_timeline_scene(session)
    payload = capacity_gap_timeline(session, _Settings())
    assert payload["panel"] == "capacity_gap_timeline"
    assert payload["unit"] == "ha/saat"
    assert payload["exceedance_level"] == "kritik"
    event = payload["events"][0]
    assert event["event_key"] == "EVT-TL"
    minutes = [row["minute"] for row in event["series"]]
    assert minutes == [30, 60, 120]
    by_min = {row["minute"]: row for row in event["series"]}
    assert by_min[30]["capacity_ha_h"] == pytest.approx(10.0)
    assert by_min[30]["gap_ha_h"] == pytest.approx(0.0)
    assert by_min[120]["demand_ha_h"] == pytest.approx(15.0)
    assert by_min[120]["gap_ha_h"] == pytest.approx(5.0)
    assert by_min[120]["level"] == "kritik"


def test_timeline_first_exceedance_interpolates_minute(session):
    _seed_timeline_scene(session)
    payload = capacity_gap_timeline(session, _Settings())
    event = payload["events"][0]
    assert event["exceedance_threshold"] == pytest.approx(1.2)
    # 0.6 -> 1.5 across 60..120 dk crosses 1.2 at 60 + (0.6/0.9)*60 = 100.
    assert event["first_exceedance_minute"] == pytest.approx(100.0)
    assert event["first_exceedance_level"] == "kritik"
    assert payload["summary"]["first_exceedance_event"] == "EVT-TL"
    assert payload["summary"]["first_exceedance_minute"] == pytest.approx(100.0)


def test_timeline_no_exceedance_within_horizon_window(session):
    _event(session, key="EVT-TL")
    _resource(session, "TL-C1")  # capacity 2.0
    _resource(session, "TL-C2")
    _resource(session, "TL-C3")
    _resource(session, "TL-C4")
    _resource(session, "TL-C5")  # 10.0 total; demand 2 -> ratio 0.2 always low
    _forecast(session, "EVT-TL", 30, 1.0)  # demand 2.0 -> ratio 0.2
    payload = capacity_gap_timeline(session, _Settings())
    event = payload["events"][0]
    assert event["first_exceedance_minute"] is None
    assert event["first_exceedance_level"] is None
    assert payload["summary"]["events_over_threshold"] == 0


def test_timeline_zero_capacity_exceeds_at_first_horizon(session):
    _event(session, key="EVT-TL")
    _forecast(session, "EVT-TL", 30, 2.0)
    _forecast(session, "EVT-TL", 60, 6.0)
    payload = capacity_gap_timeline(session, _Settings())
    event = payload["events"][0]
    # No capacity -> risk unmeasurable (None) -> worst case at first horizon.
    assert event["series"][0]["risk_index"] is None
    assert event["first_exceedance_minute"] == pytest.approx(30.0)


def test_timeline_summary_picks_soonest_event(session):
    _seed_timeline_scene(session)
    _event(session, key="EVT-TL2", lat=39.0, lon=28.0)
    _forecast(session, "EVT-TL2", 30, 20.0)  # demand 40 -> ratio 4.0 immediately
    payload = capacity_gap_timeline(session, _Settings())
    # EVT-TL2 already over at its first horizon (30 dk) -> soonest.
    assert payload["summary"]["first_exceedance_event"] == "EVT-TL2"
    assert payload["summary"]["first_exceedance_minute"] == pytest.approx(30.0)


def test_timeline_endpoint_returns_series(client, session):
    _seed_timeline_scene(session)
    session.flush()
    response = client.get("/api/v1/risk-index/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["panel"] == "capacity_gap_timeline"
    assert body["events"][0]["series"]


def test_timeline_endpoint_404_for_unknown_event(client, session):
    _event(session)
    session.flush()
    response = client.get(
        "/api/v1/risk-index/timeline", params={"event_key": "EVT-YOK"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]["error"]


def test_panel_page_embeds_timeline_chart(client):
    response = client.get("/panel")
    assert response.status_code == 200
    html = response.text
    assert 'id="gap-chart"' in html
    assert "/api/v1/risk-index/timeline" in html
