"""EM-066 cross-border shared situation tests.

The view attributes every active incident to TR (east) or GR (west) from a
configurable border longitude, rolls each country up (peak risk band + external
support need) and emits only the enabled data-sharing field groups. These tests
focus on that EM-066 behaviour - attribution, scope filtering and rollups -
reusing the EM-029/EM-065 services underneath (whose own math is tested there).
"""
import pytest

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.crossborder_situation import (
    SHAREABLE_FIELD_GROUPS,
    CrossborderError,
    crossborder_situation,
)
from src.services.risk_index import RISK_LEVELS
from src.utils.timeutils import utc_now


class _Settings:
    """Bands + horizons; capacity/EM-066 keys omitted so defaults apply
    (crew 2.0 ha/h, border 26.5, share everything)."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


class _Border28(_Settings):
    """A westward border so mid-corridor longitudes fall into GR."""

    CROSSBORDER_BORDER_LONGITUDE = 28.0


def _event(session, key, longitude=27.5):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} olay",
            latitude=38.0,
            longitude=longitude,
            min_lat=37.95,
            max_lat=38.05,
            min_lon=longitude - 0.05,
            max_lon=longitude + 0.05,
            geometry_wkt=f"POINT({longitude} 38)",
            status="active",
            started_at=utc_now().replace(tzinfo=None),
        )
    )


def _forecast(session, key, area):
    for horizon, a in zip([30, 60, 120], area):
        session.add(
            FireForecast(
                event_key=key,
                model_name="rothermel_v1",
                latitude=38.0,
                longitude=27.5,
                predicted_area_ha=a,
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


def _two_country_scene(session):
    """One TR (lon 27.5) and one GR (lon 26.2) incident, both forecast-backed."""
    for index in range(4):  # 4 crews -> 8.0 ha/h effective capacity
        _crew(session, f"XB-C{index}")
    _event(session, "EVT-TR", longitude=27.5)
    _forecast(session, "EVT-TR", [6.0, 12.0, 30.0])
    _event(session, "EVT-GR", longitude=26.2)
    _forecast(session, "EVT-GR", [1.5, 3.0, 6.0])


def _by_country(result):
    return {block["country"]: block for block in result["countries"]}


def test_attribution_splits_two_countries(session):
    _two_country_scene(session)
    session.flush()
    result = crossborder_situation(session, _Settings())
    assert set(result["summary"]["countries_present"]) == {"TR", "GR"}
    blocks = _by_country(result)
    tr_keys = {e["event_key"] for e in blocks["TR"]["events"]}
    gr_keys = {e["event_key"] for e in blocks["GR"]["events"]}
    assert tr_keys == {"EVT-TR"}
    assert gr_keys == {"EVT-GR"}


def test_border_is_inclusive_to_the_east(session):
    # An event exactly on the border longitude belongs to TR (east branch).
    _crew(session, "XB-E")
    _event(session, "EVT-ON", longitude=26.5)
    _forecast(session, "EVT-ON", [3.0, 3.0, 3.0])
    session.flush()
    blocks = _by_country(crossborder_situation(session, _Settings()))
    assert "EVT-ON" in {e["event_key"] for e in blocks["TR"]["events"]}


def test_custom_border_reassigns_incident(session):
    _two_country_scene(session)
    session.flush()
    # With the border pushed to 28.0 the 27.5 incident now falls to GR.
    blocks = _by_country(crossborder_situation(session, _Border28()))
    assert "EVT-TR" in {e["event_key"] for e in blocks["GR"]["events"]}
    assert "TR" not in blocks


def test_default_scope_emits_all_field_groups(session):
    _two_country_scene(session)
    session.flush()
    result = crossborder_situation(session, _Settings())
    assert result["shared_fields"] == list(SHAREABLE_FIELD_GROUPS)
    row = _by_country(result)["TR"]["events"][0]
    assert {"fire", "risk", "support"} <= set(row)


def test_risk_only_scope_withholds_fire_and_support(session):
    _two_country_scene(session)
    session.flush()
    result = crossborder_situation(session, _Settings(), shared_fields="risk")
    assert result["shared_fields"] == ["risk"]
    block = _by_country(result)["TR"]
    row = block["events"][0]
    assert "risk" in row and "fire" not in row and "support" not in row
    assert block["peak_level"] in RISK_LEVELS
    assert block["total_support_units"] is None


def test_support_only_scope_withholds_risk(session):
    _two_country_scene(session)
    session.flush()
    result = crossborder_situation(session, _Settings(), shared_fields="support")
    block = _by_country(result)["TR"]
    row = block["events"][0]
    assert "support" in row and "risk" not in row
    assert block["peak_level"] is None
    assert isinstance(block["total_support_units"], int)


def test_fire_only_scope_aggregates_are_empty(session):
    _two_country_scene(session)
    session.flush()
    result = crossborder_situation(session, _Settings(), shared_fields="fire")
    block = _by_country(result)["TR"]
    row = block["events"][0]
    assert set(row) == {"event_key", "fire"}
    assert block["peak_level"] is None
    assert block["total_support_units"] is None


def test_country_support_total_is_sum_of_events(session):
    _two_country_scene(session)
    session.flush()
    block = _by_country(crossborder_situation(session, _Settings()))["TR"]
    from_events = sum(e["support"]["estimated_support_units"] for e in block["events"])
    assert block["total_support_units"] == from_events


def test_country_peak_level_is_worst_event_band(session):
    _two_country_scene(session)
    session.flush()
    block = _by_country(crossborder_situation(session, _Settings()))["TR"]
    ranks = [RISK_LEVELS.index(e["risk"]["peak_level"]) for e in block["events"]]
    assert block["peak_level"] == RISK_LEVELS[max(ranks)]


def test_unknown_field_raises(session):
    _two_country_scene(session)
    session.flush()
    with pytest.raises(CrossborderError):
        crossborder_situation(session, _Settings(), shared_fields="secret")


def test_no_active_events_yields_no_countries(session):
    result = crossborder_situation(session, _Settings())
    assert result["countries"] == []
    assert result["summary"]["total_events"] == 0
    assert result["summary"]["overall_peak_level"] is None


def test_metadata_is_stateless(session):
    _two_country_scene(session)
    session.flush()
    result = crossborder_situation(session, _Settings())
    assert result["panel"] == "crossborder_situation"
    assert result["persistence"] == "none"
    assert result["unit"] == "ha/saat"
    assert result["border_longitude"] == pytest.approx(26.5)
    assert "attribution" in result


def test_endpoint_returns_situation(client, session):
    _two_country_scene(session)
    session.commit()
    resp = client.get("/api/v1/crossborder/situation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "crossborder_situation"
    assert body["persistence"] == "none"
    assert set(body["summary"]["countries_present"]) == {"TR", "GR"}


def test_endpoint_fields_filter(client, session):
    _two_country_scene(session)
    session.commit()
    resp = client.get("/api/v1/crossborder/situation", params={"fields": "risk"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["shared_fields"] == ["risk"]
    row = body["countries"][0]["events"][0]
    assert "risk" in row and "fire" not in row


def test_endpoint_bad_field_400(client):
    resp = client.get("/api/v1/crossborder/situation", params={"fields": "secret"})
    assert resp.status_code == 400


def test_endpoint_config(client):
    resp = client.get("/api/v1/crossborder/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["border_longitude"] == pytest.approx(26.5)
    assert body["shareable_fields"] == list(SHAREABLE_FIELD_GROUPS)
    assert {c["code"] for c in body["countries"]} == {"TR", "GR"}
    assert body["persistence"] == "none"
