"""EM-032 risk threshold-crossing alert tests.

Covers the escalation rule (alert only when a band climbs above the last
alerted high-water mark), hysteresis repeat-suppression across re-evaluations,
the never-alert-on-normal and disabled cases, and the evaluate endpoint
wiring plus the operator-map visual/audio hooks.
"""
import json

from sqlalchemy import select

from src.models.inventory import SuppressionResource
from src.models.live import LiveUpdate
from src.models.spatial import FireEvent, FireForecast
from src.services.risk_alert import (
    ALERT_SOURCE,
    LEVEL_ORDER,
    evaluate_risk_alerts,
)
from src.utils.timeutils import utc_now


class _Settings:
    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    RISK_ALERTS_ENABLED = True
    LIVE_UPDATES_ENABLED = True


class _DisabledSettings(_Settings):
    RISK_ALERTS_ENABLED = False


def _event(session, key="EVT-AL", status="active", lat=38.0, lon=27.0):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} alarm",
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


def _crew(session, idx):
    session.add(
        SuppressionResource(
            resource_key=f"AL-C{idx}",
            name=f"AL-C{idx}",
            resource_type="crew",
            latitude=37.0,
            longitude=28.0,
            status="available",
            capacity=1.0,
        )
    )


def _dikkat_scene(session):
    """Capacity 8.0 (4 crews), single-horizon demand 6.0 -> ratio 0.75 dikkat."""
    _event(session)
    for idx in range(1, 5):
        _crew(session, idx)
    _forecast(session, "EVT-AL", 30, 3.0)  # 3/30*60 = 6.0 -> 6/8 = 0.75 dikkat


def _alert_rows(session, event_key="EVT-AL"):
    return session.scalars(
        select(LiveUpdate)
        .where(
            LiveUpdate.kind == "alert",
            LiveUpdate.event_key == event_key,
            LiveUpdate.source == ALERT_SOURCE,
        )
        .order_by(LiveUpdate.id.asc())
    ).all()


def test_level_order_is_monotonic():
    assert LEVEL_ORDER["normal"] < LEVEL_ORDER["dikkat"]
    assert LEVEL_ORDER["dikkat"] < LEVEL_ORDER["kritik-yakin"]
    assert LEVEL_ORDER["kritik-yakin"] < LEVEL_ORDER["kritik"]


def test_escalation_to_dikkat_raises_one_alert(session):
    _dikkat_scene(session)
    result = evaluate_risk_alerts(session, _Settings())
    assert result["panel"] == "risk_alerts"
    assert result["enabled"] is True
    assert result["summary"]["alerts_raised"] == 1
    state = result["events"][0]
    assert state["peak_level"] == "dikkat"
    assert state["last_alerted_level"] == "normal"
    assert state["escalated"] is True
    rows = _alert_rows(session)
    assert len(rows) == 1
    payload = json.loads(str(rows[0].payload_json))
    assert payload["from_level"] == "normal"
    assert payload["to_level"] == "dikkat"


def test_hysteresis_suppresses_repeat_at_same_level(session):
    _dikkat_scene(session)
    first = evaluate_risk_alerts(session, _Settings())
    assert first["summary"]["alerts_raised"] == 1
    # Re-evaluate with no change: same band -> suppressed (hysteresis latch).
    second = evaluate_risk_alerts(session, _Settings())
    assert second["summary"]["alerts_raised"] == 0
    assert second["events"][0]["last_alerted_level"] == "dikkat"
    assert second["events"][0]["escalated"] is False
    assert len(_alert_rows(session)) == 1


def test_further_escalation_raises_again(session):
    _dikkat_scene(session)
    evaluate_risk_alerts(session, _Settings())  # dikkat latch
    # A bigger far-horizon forecast pushes the peak into kritik (15/8 = 1.875).
    _forecast(session, "EVT-AL", 120, 30.0)
    result = evaluate_risk_alerts(session, _Settings())
    assert result["events"][0]["peak_level"] == "kritik"
    assert result["summary"]["alerts_raised"] == 1
    rows = _alert_rows(session)
    assert len(rows) == 2
    latest = json.loads(str(rows[-1].payload_json))
    assert latest["from_level"] == "dikkat"
    assert latest["to_level"] == "kritik"


def test_normal_band_never_alerts(session):
    _event(session)
    for idx in range(1, 5):
        _crew(session, idx)
    _forecast(session, "EVT-AL", 30, 1.0)  # demand 2.0 -> ratio 0.25 normal
    result = evaluate_risk_alerts(session, _Settings())
    assert result["events"][0]["peak_level"] == "normal"
    assert result["summary"]["alerts_raised"] == 0
    assert len(_alert_rows(session)) == 0


def test_event_without_forecast_does_not_alert(session):
    _event(session)
    _crew(session, 1)
    result = evaluate_risk_alerts(session, _Settings())
    assert result["events"][0]["peak_level"] == "normal"
    assert result["summary"]["alerts_raised"] == 0


def test_disabled_setting_raises_no_alerts(session):
    _dikkat_scene(session)
    result = evaluate_risk_alerts(session, _DisabledSettings())
    assert result["enabled"] is False
    assert result["summary"]["alerts_raised"] == 0
    assert len(_alert_rows(session)) == 0


def test_evaluate_endpoint_writes_feed(client, session):
    _dikkat_scene(session)
    session.flush()
    response = client.post("/api/v1/risk-index/alerts/evaluate")
    assert response.status_code == 200
    body = response.json()
    assert body["panel"] == "risk_alerts"
    assert body["summary"]["alerts_raised"] == 1
    feed = client.get("/api/v1/live/updates", params={"since": 0}).json()
    alerts = [u for u in feed["updates"] if u["kind"] == "alert"]
    assert alerts and alerts[-1]["event_key"] == "EVT-AL"


def test_operator_map_embeds_alert_notification(client):
    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text
    assert 'id="alert-banner"' in html
    assert 'id="sound-toggle"' in html
    assert "/api/v1/risk-index/alerts/evaluate" in html
    assert "beepTwice" in html
