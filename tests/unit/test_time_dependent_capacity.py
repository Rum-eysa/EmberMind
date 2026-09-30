"""EM-033 time-dependent capacity tests (Epic E3).

An ``en_route`` resource with a committed ``arrival_eta`` is not on station now
(so it stays out of the current effective capacity, EM-031) but it *will* add
capacity from its ETA onward. These tests pin the arrival bucketing, the
per-minute capacity arithmetic, the flat fallback when no en-route asset has an
ETA (the EM-030 regression guard), the capacity-gap timeline stepping its
capacity line and deferring the first ``kritik`` crossing, the CRUD round-trip
of ``arrival_minutes`` and the schedule endpoint.
"""
from datetime import timedelta

import pytest

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.capacity import (
    capacity_at_minute,
    capacity_schedule,
    effective_capacity,
    enroute_arrival_minutes,
)
from src.services.inventory import InventoryError, create_resource
from src.services.risk_index import capacity_gap_timeline
from src.utils.timeutils import utc_now

CREW_DEFAULT = 2.0
HELI_DEFAULT = 12.0
UAV_DEFAULT = 4.0


class _Settings:
    """Bands + horizons; capacity ha/hour keys omitted to use service defaults."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    TIME_DEPENDENT_CAPACITY = True


class _FlatSettings(_Settings):
    """EM-030 flat-capacity behaviour when the feature flag is off."""

    TIME_DEPENDENT_CAPACITY = False


def _event(session, key="EVT-TDC"):
    lat, lon = 38.0, 27.0
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} time-dependent capacity testi",
            latitude=lat,
            longitude=lon,
            min_lat=lat - 0.05,
            max_lat=lat + 0.05,
            min_lon=lon - 0.05,
            max_lon=lon + 0.05,
            geometry_wkt=f"POINT({lon} {lat})",
            status="active",
            started_at=utc_now(),
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


def _resource(session, key, rtype="crew", status="available", eta_minutes=None):
    arrival = (
        utc_now() + timedelta(minutes=eta_minutes) if eta_minutes is not None else None
    )
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key,
            resource_type=rtype,
            latitude=37.0,
            longitude=28.0,
            status=status,
            capacity=1.0,
            arrival_eta=arrival,
        )
    )


def _seed_scene(session, available_crews, en_route_heli_eta):
    """Forecast 6/9/18 -> demand 12/9/9 ha/h; base crews + one en-route heli."""
    _event(session)
    for horizon, area in ((30, 6.0), (60, 9.0), (120, 18.0)):
        _forecast(session, "EVT-TDC", horizon, area)
    for i in range(available_crews):
        _resource(session, f"EK-{i}", "crew", "available")
    if en_route_heli_eta is not None:
        _resource(session, "HEL-ETA", "helicopter", "en_route", en_route_heli_eta)
    session.flush()


def _seed_deferred(session):
    """1 crew on station + 1 en-route heli arriving late (T+75, covers T+120)."""
    _seed_scene(session, available_crews=1, en_route_heli_eta=75)


def _seed_flat(session):
    """1 crew only, no reinforcement -> capacity flat at 2.0 ha/h (all kritik)."""
    _seed_scene(session, available_crews=1, en_route_heli_eta=None)


def _seed_breach_choice(session, with_heli):
    """2 crews (8.0 ha/h) with demand 4/4.5/7.2; optional heli at T+75.

    Near-term horizons stay under kritik on base capacity alone. Without the
    reinforcement the flat capacity lets T+120 breach; with a helicopter online
    at T+75 the last horizon is reinforced and the breach is deferred past the
    forecast window.
    """
    _event(session)
    for horizon, area in ((30, 2.0), (60, 4.5), (120, 14.4)):
        _forecast(session, "EVT-TDC", horizon, area)
    _resource(session, "EK-0", "crew", "available")
    _resource(session, "EK-1", "crew", "available")
    if with_heli:
        _resource(session, "HEL-LATE", "helicopter", "en_route", 75)
    session.flush()


# ------------------------------------------------------------------ arrivals --


def test_enroute_without_eta_is_excluded(session):
    _resource(session, "EK1", "crew", "available")
    _resource(session, "HEL-X", "helicopter", "en_route", None)
    session.flush()
    # EM-031 invariant: a no-ETA en-route asset never contributes capacity.
    assert enroute_arrival_minutes(session) == []
    total = effective_capacity(session, _Settings())["total_effective_ha_per_hour"]
    assert total == pytest.approx(CREW_DEFAULT)


def test_enroute_arrival_minutes_reads_future_eta(session):
    _resource(session, "EK1", "crew", "available")
    _resource(session, "HEL-1", "helicopter", "en_route", 45)
    session.flush()
    arrivals = enroute_arrival_minutes(session)
    assert len(arrivals) == 1
    rtype, minute = arrivals[0]
    assert rtype == "helicopter"
    assert 44 <= minute <= 46


def test_capacity_at_minute_counts_only_arrived():
    assumptions = {"crew": CREW_DEFAULT, "helicopter": HELI_DEFAULT, "uav": UAV_DEFAULT}
    arrivals = [("helicopter", 45), ("uav", 75)]
    assert capacity_at_minute(2.0, assumptions, arrivals, 30) == pytest.approx(2.0)
    assert capacity_at_minute(2.0, assumptions, arrivals, 60) == pytest.approx(14.0)
    assert capacity_at_minute(2.0, assumptions, arrivals, 120) == pytest.approx(18.0)


# ------------------------------------------------------------------- schedule --


def test_capacity_schedule_flat_when_no_arrivals(session):
    _resource(session, "EK1", "crew", "available")
    _resource(session, "EK2", "crew", "available")
    session.flush()
    sched = capacity_schedule(session, _Settings(), [30, 60, 120])
    assert sched["time_dependent"] is False
    assert sched["arrivals"] == []
    assert sched["base_ha_h"] == pytest.approx(2 * CREW_DEFAULT)
    assert all(v == pytest.approx(2 * CREW_DEFAULT) for v in sched["schedule"].values())


def test_capacity_schedule_steps_at_arrivals(session):
    _resource(session, "EK1", "crew", "available")
    _resource(session, "HEL-1", "helicopter", "en_route", 45)
    _resource(session, "UAV-1", "uav", "en_route", 100)
    session.flush()
    sched = capacity_schedule(session, _Settings(), [30, 60, 120])
    assert sched["time_dependent"] is True
    assert sched["base_ha_h"] == pytest.approx(CREW_DEFAULT)
    assert sched["schedule"][30] == pytest.approx(CREW_DEFAULT)  # nothing yet
    assert sched["schedule"][60] == pytest.approx(CREW_DEFAULT + HELI_DEFAULT)
    assert sched["schedule"][120] == pytest.approx(
        CREW_DEFAULT + HELI_DEFAULT + UAV_DEFAULT
    )


# ------------------------------------------------------------------- timeline --


def test_timeline_capacity_steps_up_at_arrival(session):
    _seed_deferred(session)
    data = capacity_gap_timeline(session, _Settings(), "EVT-TDC")
    series = data["events"][0]["series"]
    caps = [row["capacity_ha_h"] for row in series]
    # Heli ETA T+75: only the last horizon (T+120) credits it -> 2.0 then 14.0.
    assert caps[0] == pytest.approx(CREW_DEFAULT)
    assert caps[1] == pytest.approx(CREW_DEFAULT)
    assert caps[2] == pytest.approx(CREW_DEFAULT + HELI_DEFAULT)
    assert "capacity_schedule" in data
    assert data["capacity_schedule"]["time_dependent"] is True


def test_timeline_first_exceedance_deferred_vs_none(session):
    # Same demand and same 2 crews (8.0 ha/h base). Without reinforcement the
    # flat capacity lets risk cross kritik between T+60 and T+120 (interpolated
    # ~T+67); a helicopter online at T+75 lifts that horizon to 20.0 ha/h so the
    # crossing is deferred entirely (``None``) within the forecast window.
    _seed_breach_choice(session, with_heli=True)
    deferred = capacity_gap_timeline(session, _Settings(), "EVT-TDC")
    session.rollback()
    _seed_breach_choice(session, with_heli=False)
    flat = capacity_gap_timeline(session, _Settings(), "EVT-TDC")
    d_first = deferred["events"][0]["first_exceedance_minute"]
    f_first = flat["events"][0]["first_exceedance_minute"]
    assert f_first is not None and 60.0 < f_first < 120.0
    assert d_first is None


def test_timeline_flag_off_is_flat(session):
    _seed_scene(session, available_crews=1, en_route_heli_eta=75)
    data = capacity_gap_timeline(session, _FlatSettings(), "EVT-TDC")
    series = data["events"][0]["series"]
    assert all(row["capacity_ha_h"] == pytest.approx(CREW_DEFAULT) for row in series)
    assert "capacity_schedule" not in data


# ----------------------------------------------------------------------- crud --


def test_create_and_read_arrival_minutes(session):
    resource = create_resource(
        session,
        {
            "resource_key": "HEL-NEW",
            "resource_type": "helicopter",
            "latitude": 37.0,
            "longitude": 28.0,
            "status": "en_route",
            "arrival_minutes": 45,
        },
    )
    session.flush()
    payload = resource.as_dict
    assert payload["arrival_eta"] is not None
    assert payload["arrival_eta"].endswith("Z")
    assert enroute_arrival_minutes(session) == [
        ("helicopter", pytest.approx(45, abs=1))
    ]


def test_create_rejects_negative_arrival(session):
    with pytest.raises(InventoryError):
        create_resource(
            session,
            {
                "resource_key": "HEL-BAD",
                "resource_type": "helicopter",
                "latitude": 37.0,
                "longitude": 28.0,
                "status": "en_route",
                "arrival_minutes": -5,
            },
        )


# --------------------------------------------------------------------- endpoint --


def test_capacity_schedule_endpoint(client):
    got = client.get("/api/v1/capacity/schedule")
    assert got.status_code == 200
    sched = got.json()["schedule"]
    assert sched["unit"] == "ha/saat"
    assert "schedule" in sched and "arrivals" in sched


def test_capacity_schedule_endpoint_custom_minutes(client):
    got = client.get("/api/v1/capacity/schedule?minutes=15&minutes=90")
    assert got.status_code == 200
    assert set(got.json()["schedule"]["schedule"].keys()) == {"15", "90"}


# --------------------------------------------------------------------------- UI --


def test_panel_and_inventory_embed_arrival_wiring():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    panel = (root / "src/static/risk_panel.html").read_text(encoding="utf-8")
    assert "capacity_schedule" in panel
    assert "sched.arrivals" in panel
    inventory = (root / "src/static/inventory.html").read_text(encoding="utf-8")
    assert 'id="r-arrival"' in inventory
    assert "arrival_minutes" in inventory
