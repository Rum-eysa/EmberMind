"""EM-065 external-support early-forecast tests.

The forecast is a deterministic projection over the EM-030/EM-033 capacity-gap
timeline: for each active event it reports the first minute the projected spread
demand outruns national capacity (``T+X``), the peak shortfall, the whole
reinforcement units that implies (``~ Y``) and a request-by deadline. The
shortfall is projected *ahead* of when it happens (early warning).
"""
import pytest

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.external_support import forecast_external_support
from src.services.risk_index import RiskIndexError
from src.utils.timeutils import utc_now


class _Settings:
    """Bands + horizons; capacity keys omitted so ha/hour defaults apply.

    crew 2.0 / helicopter 12.0 / uav 4.0, and the EM-065 unit/lead-time keys are
    omitted on purpose so the service falls back to 12.0 ha/hour and 60 minutes.
    """

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


class _Unit2Lead10(_Settings):
    EXTERNAL_SUPPORT_UNIT_HA_PER_HOUR = 2.0
    EXTERNAL_SUPPORT_LEAD_TIME_MINUTES = 10


def _event(session, key="EVT-ES", status="active"):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} destek testi",
            latitude=38.0,
            longitude=27.0,
            min_lat=37.95,
            max_lat=38.05,
            min_lon=26.95,
            max_lon=27.05,
            geometry_wkt="POINT(27 38)",
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


def _crew(session, key):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key,
            resource_type="crew",
            latitude=37.0,
            longitude=28.0,
            status="available",
            capacity=1.0,
        )
    )


def _seed(session, crews, areas):
    """``crews`` available crews (each 2.0 ha/h) + forecast areas per horizon."""
    _event(session)
    for index in range(crews):
        _crew(session, f"ES-C{index}")
    for horizon, area in zip([30, 60, 120], areas):
        _forecast(session, "EVT-ES", horizon, area)


def test_sufficient_capacity_no_warning(session):
    # capacity 20 ha/h vs demand 3/3/2 -> national capacity holds all window.
    _seed(session, crews=10, areas=[1.5, 1.5, 1.0])
    session.flush()
    result = forecast_external_support(session, _Settings())
    ev = result["events"][0]
    assert ev["predicted_shortfall"] is False
    assert ev["first_shortfall_minute"] is None
    assert ev["estimated_support_units"] == 0
    assert "yeterli" in ev["message"]
    assert result["summary"]["events_with_warning"] == 0


def test_predicts_shortfall_minute_units_and_peak(session):
    # capacity 4 ha/h (2 crews); demand 3/6/8 ha/h -> short by 2 (T+60), 4 (T+120)
    # interpolated first crossing between T+30 (demand 3, short -1) and T+60 -> T+40.
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    ev = forecast_external_support(session, _Unit2Lead10())["events"][0]
    assert ev["predicted_shortfall"] is True
    assert ev["first_shortfall_minute"] == pytest.approx(40.0)
    assert ev["peak_shortfall_ha_h"] == pytest.approx(4.0)
    assert ev["peak_shortfall_minute"] == 120
    # ceil(4.0 / 2.0) = 2 reinforcement units.
    assert ev["estimated_support_units"] == 2


def test_message_matches_acceptance_phrase(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    ev = forecast_external_support(session, _Unit2Lead10())["events"][0]
    assert ev["message"].startswith(
        "Ulusal kapasite T+40 dk sonra yetersiz kalacak, dış destek ihtiyacı ≈ 2 birim."
    )


def test_request_by_deadline_and_immediate(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    # lead 10 < shortfall 40 -> a real request-by minute (T+30).
    late = forecast_external_support(session, _Unit2Lead10())["events"][0]
    assert late["request_by_minute"] == pytest.approx(30.0)
    assert "en geç T+30" in late["message"]
    # lead 60 > shortfall 40 -> request must go out now.
    soon = forecast_external_support(session, _Settings())["events"][0]
    assert soon["request_by_minute"] == pytest.approx(0.0)
    assert "hemen" in soon["message"]


def test_zero_capacity_shortfall_at_first_horizon(session):
    # No national capacity -> the first horizon is already short (no earlier
    # minute can be resolved, conservative upper bound = T+30).
    _seed(session, crews=0, areas=[1.5, 6.0, 16.0])
    session.flush()
    ev = forecast_external_support(session, _Settings())["events"][0]
    assert ev["predicted_shortfall"] is True
    assert ev["first_shortfall_minute"] == pytest.approx(30.0)
    # peak demand 8.0 ha/h uncovered -> ceil(8/12) = 1 support unit.
    assert ev["peak_shortfall_ha_h"] == pytest.approx(8.0)
    assert ev["estimated_support_units"] == 1


def test_summary_reports_soonest_event(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    result = forecast_external_support(session, _Unit2Lead10())
    assert result["summary"]["events_with_warning"] == 1
    assert result["summary"]["earliest_shortfall_event"] == "EVT-ES"
    assert result["summary"]["earliest_shortfall_minute"] == pytest.approx(40.0)
    assert result["summary"]["earliest_support_units"] == 2


def test_no_events_returns_empty_assessment(session):
    result = forecast_external_support(session, _Settings())
    assert result["events"] == []
    assert result["summary"]["events_scored"] == 0
    assert result["summary"]["events_with_warning"] == 0
    assert "yeterli" in result["summary"]["message"]


def test_metadata_is_stateless(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    result = forecast_external_support(session, _Settings())
    assert result["panel"] == "external_support"
    assert result["persistence"] == "none"
    assert result["unit"] == "ha/saat"
    assert "attribution" in result


def test_unknown_event_raises(session):
    with pytest.raises(RiskIndexError):
        forecast_external_support(session, _Settings(), event_key="NOPE")


def test_endpoint_returns_forecast(client, session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.commit()
    resp = client.get("/api/v1/external-support")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "external_support"
    assert body["persistence"] == "none"
    assert len(body["events"]) == 1


def test_endpoint_unknown_event_404(client):
    resp = client.get("/api/v1/external-support", params={"event_key": "NOPE"})
    assert resp.status_code == 404


def test_endpoint_config(client):
    resp = client.get("/api/v1/external-support/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "support_unit_ha_per_hour" in body
    assert "lead_time_minutes" in body
    assert body["persistence"] == "none"
