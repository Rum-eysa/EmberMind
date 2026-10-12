"""EM-067 cross-border spread projection tests.

Deterministic geometry: the cosine of the angle between the EM-015 head
spread bearing and the due west/east border bearing is the crossing
likelihood; the crossing time is the centroid-to-border distance divided by
the toward-border share of the head rate of spread. The tests compute the
expected minutes with the same formula on hand-built scenarios.
"""
import math

from src.models.spatial import FireEvent, FireForecast
from src.services.crossborder_spread import project_border_crossing
from src.utils.timeutils import utc_now

_KM_PER_DEG_LON = 111.320


class _Settings:
    """Default pilot border (26.5) and the 30/60/120 forecast window."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]


class _Border28(_Settings):
    CROSSBORDER_BORDER_LONGITUDE = 28.0


def _event(session, key, longitude, latitude=38.0, status="active"):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} yayilim",
            latitude=latitude,
            longitude=longitude,
            min_lat=latitude - 0.05,
            max_lat=latitude + 0.05,
            min_lon=longitude - 0.05,
            max_lon=longitude + 0.05,
            geometry_wkt=f"POINT({longitude} {latitude})",
            status=status,
            started_at=utc_now().replace(tzinfo=None),
        )
    )


def _forecast(session, key, direction_deg, ros_m_min):
    session.add(
        FireForecast(
            event_key=key,
            model_name="rothermel_v1",
            latitude=38.0,
            longitude=27.5,
            predicted_area_ha=10.0,
            geometry_wkt="POLYGON((27 38,27.01 38,27.01 38.01,27 38.01,27 38))",
            forecast_for=utc_now(),
            horizon_minutes=120,
            rate_of_spread_m_per_min=ros_m_min,
            spread_direction_deg=direction_deg,
            inputs_json="{}",
        )
    )


def _expected_minutes(longitude, ros, alignment, latitude=38.0):
    distance_km = (
        abs(longitude - 26.5) * _KM_PER_DEG_LON * math.cos(math.radians(latitude))
    )
    return round(distance_km * 1000.0 / (ros * alignment), 1)


def _by_key(result):
    return {row["event_key"]: row for row in result["events"]}


def test_head_drives_straight_at_border(session):
    # TR-side incident, head bearing due west (270) = border bearing -> 1.0.
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 270.0, 10.0)
    session.flush()
    row = _by_key(project_border_crossing(session, _Settings()))["EVT-W"]
    assert row["country"] == "TR" and row["target_country"] == "GR"
    assert row["likelihood"] == 1.0
    assert row["likelihood_level"] == "yüksek"
    assert row["crossing_minutes"] == _expected_minutes(27.5, 10.0, 1.0)


def test_moving_away_never_crosses(session):
    # Due east (90) from the TR side points away from the border.
    _event(session, "EVT-E", 27.5)
    _forecast(session, "EVT-E", 90.0, 10.0)
    session.flush()
    row = _by_key(project_border_crossing(session, _Settings()))["EVT-E"]
    assert row["likelihood"] == 0.0
    assert row["crossing_minutes"] is None
    assert "aksi yönünde" in row["message"]


def test_perpendicular_bearing_no_spurious_crossing(session):
    # Due north has (float-noise-level) zero west/east component: no crossing.
    _event(session, "EVT-N", 27.5)
    _forecast(session, "EVT-N", 0.0, 10.0)
    session.flush()
    row = _by_key(project_border_crossing(session, _Settings()))["EVT-N"]
    assert row["likelihood"] == 0.0
    assert row["crossing_minutes"] is None


def test_half_alignment_scales_time_and_likelihood(session):
    # 45 degrees off the border bearing: alignment cos(45) ~ 0.71 (orta).
    _event(session, "EVT-SW", 27.5)
    _forecast(session, "EVT-SW", 315.0, 10.0)
    session.flush()
    row = _by_key(project_border_crossing(session, _Settings()))["EVT-SW"]
    alignment = math.cos(math.radians(45.0))
    assert row["likelihood"] == round(alignment, 2)
    assert row["likelihood_level"] == "orta"
    assert row["crossing_minutes"] == _expected_minutes(27.5, 10.0, alignment)


def test_forecast_window_flag(session):
    # Close to the border and fast: crossing lands inside the 120 dk window.
    distance_m = 0.05 * _KM_PER_DEG_LON * math.cos(math.radians(38.0)) * 1000.0
    ros = distance_m / 60.0  # exactly T+60, inside the window
    _event(session, "EVT-NEAR", 26.55)
    _forecast(session, "EVT-NEAR", 270.0, ros)
    session.flush()
    row = _by_key(project_border_crossing(session, _Settings()))["EVT-NEAR"]
    assert row["crossing_minutes"] == _expected_minutes(26.55, ros, 1.0)
    assert row["within_forecast_window"] is True
    assert "penceresi içinde" in row["message"]


def test_far_crossing_flagged_outside_window(session):
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 270.0, 10.0)
    session.flush()
    row = _by_key(project_border_crossing(session, _Settings()))["EVT-W"]
    assert row["within_forecast_window"] is False
    assert "penceresi dışı" in row["message"]


def test_gr_side_targets_tr(session):
    # West-of-border incident; border bearing is due east (90).
    _event(session, "EVT-GR", 26.2)
    _forecast(session, "EVT-GR", 90.0, 5.0)
    session.flush()
    row = _by_key(project_border_crossing(session, _Settings()))["EVT-GR"]
    assert row["country"] == "GR" and row["target_country"] == "TR"
    assert row["likelihood"] == 1.0
    assert row["crossing_minutes"] is not None


def test_no_forecast_is_uncertain(session):
    _event(session, "EVT-X", 27.5)
    session.flush()
    row = _by_key(project_border_crossing(session, _Settings()))["EVT-X"]
    assert row["likelihood"] is None
    assert row["likelihood_level"] == "belirsiz"
    assert row["crossing_minutes"] is None
    assert "Yayılım tahmini yok" in row["message"]


def test_custom_border_reorients_projection(session):
    # With the border at 28.0 the 27.5 incident is on the GR side facing east.
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 90.0, 10.0)
    session.flush()
    row = _by_key(project_border_crossing(session, _Border28()))["EVT-W"]
    assert row["country"] == "GR" and row["target_country"] == "TR"
    assert row["likelihood"] == 1.0


def test_summary_reports_earliest_crossing(session):
    _event(session, "EVT-FAR", 27.5)
    _forecast(session, "EVT-FAR", 270.0, 10.0)
    _event(session, "EVT-NEAR", 26.6)
    _forecast(session, "EVT-NEAR", 270.0, 60.0)
    _event(session, "EVT-AWAY", 29.0)
    _forecast(session, "EVT-AWAY", 90.0, 10.0)
    session.flush()
    result = project_border_crossing(session, _Settings())
    assert result["summary"]["events_scored"] == 3
    assert result["summary"]["crossings_predicted"] == 2
    assert result["summary"]["earliest_crossing_event"] == "EVT-NEAR"
    assert "geçebilir" in result["summary"]["message"]


def test_only_crossings_toward_border_count(session):
    # A moving-away event is scored but never counts as a projection.
    _event(session, "EVT-AWAY", 29.0)
    _forecast(session, "EVT-AWAY", 90.0, 10.0)
    session.flush()
    result = project_border_crossing(session, _Settings())
    assert result["summary"]["crossings_predicted"] == 0
    assert result["summary"]["earliest_crossing_event"] is None
    assert "sınır geçişi öngörülmüyor" in result["summary"]["message"]


def test_no_active_events(session):
    result = project_border_crossing(session, _Settings())
    assert result["events"] == []
    assert result["summary"]["events_scored"] == 0


def test_metadata_is_stateless(session):
    result = project_border_crossing(session, _Settings())
    assert result["panel"] == "crossborder_spread"
    assert result["persistence"] == "none"
    assert result["border_longitude"] == 26.5
    assert result["forecast_window_minutes"] == 120
    assert "attribution" in result


def test_endpoint_returns_projection(client, session):
    _event(session, "EVT-W", 27.5)
    _forecast(session, "EVT-W", 270.0, 10.0)
    session.commit()
    resp = client.get("/api/v1/crossborder/spread")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "crossborder_spread"
    assert body["events"][0]["likelihood"] == 1.0
