"""EM-123 risk/capacity index boundary-value tests (Epic E13).

Acceptance criteria pinned here:
 - zero capacity, the band edges (0.6 / 0.9 / 1.2) and extreme magnitudes are
   exercised,
 - the effect of a capacity change on the index is asserted,
 - the tests run in the ordinary CI pytest invocation.

``tests/unit/test_risk_index.py`` covers the EM-029 payload shape and the
timeline; this slice is deliberately about *numbers at the edges*: the exact
comparison semantics of every band boundary (including the epsilon on both
sides), what happens when capacity is zero, tiny, enormous or edited while the
incident burns, and that absurd magnitudes stay finite and JSON-serialisable
instead of overflowing into ``None``/``NaN``.
"""
import math

import pytest

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.capacity import update_assumptions
from src.services.risk_index import (
    classify_risk,
    compute_risk_index,
    demand_ha_h,
    level_thresholds,
)
from src.utils.timeutils import utc_now

EPSILON = 1e-9

# 30 dk horizon on a 6.0 ha polygon is exactly 12.0 ha/h of demand, so the
# capacity needed to land on any band edge is a round number (12/ratio).
DEMAND_12 = 12.0


class _Settings:
    """Stock EM-029 bands (0.6 / 0.9 / 1.2) with the 30/60/120 dk horizons."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


class _RetunedSettings:
    """Same engine, operator-retuned bands - the edges must move with config."""

    RISK_INDEX_NORMAL_MAX = 0.4
    RISK_INDEX_CAUTION_MAX = 0.8
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.5
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


class _CrewSettings:
    """Bands stay stock; the per-crew ha/hour assumption is configurable."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]

    def __init__(self, crew_ha_per_hour: float) -> None:
        self.CAPACITY_HA_PER_HOUR_CREW = crew_ha_per_hour


def _event(session, key="EVT-B"):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} sinir testi",
            latitude=38.0,
            longitude=27.0,
            min_lat=37.95,
            max_lat=38.05,
            min_lon=26.95,
            max_lon=27.05,
            geometry_wkt="POINT(27 38)",
            status="active",
            started_at=utc_now().replace(tzinfo=None),
        )
    )


def _forecast(session, event_key, horizon, area_ha):
    session.add(
        FireForecast(
            event_key=event_key,
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


def _crew(session, key, status="available"):
    resource = SuppressionResource(
        resource_key=key,
        name=key,
        resource_type="crew",
        latitude=37.0,
        longitude=28.0,
        status=status,
        capacity=1.0,
    )
    session.add(resource)
    return resource


def _scene(session, crews, area_ha=6.0, horizon=30):
    """One active incident with a fixed demand, ``crews`` available crews."""
    _event(session)
    for index in range(1, crews + 1):
        _crew(session, f"B-C{index}")
    _forecast(session, "EVT-B", horizon, area_ha)


def _only_row(session, settings=None):
    payload = compute_risk_index(session, settings or _Settings())
    return payload["events"][0]["horizons"][0]


# ------------------------------------------------------- band semantics ---


@pytest.mark.parametrize(
    "value,expected",
    [
        (-EPSILON, "normal"),  # defensive: never produced, must not crash
        (0.0, "normal"),
        (0.599999, "normal"),
        (0.6 - EPSILON, "normal"),
        (0.6, "dikkat"),  # the boundary value belongs to the higher band
        (0.6 + EPSILON, "dikkat"),
        (0.899999, "dikkat"),
        (0.9 - EPSILON, "dikkat"),
        (0.9, "kritik-yakin"),
        (0.9 + EPSILON, "kritik-yakin"),
        (1.199999, "kritik-yakin"),
        (1.2 - EPSILON, "kritik-yakin"),
        (1.2, "kritik"),
        (1.2 + EPSILON, "kritik"),
        (1e6, "kritik"),
        (float("inf"), "kritik"),
        (None, "kritik"),
    ],
)
def test_stock_band_edges_are_half_open_upper_inclusive(value, expected):
    assert classify_risk(value, level_thresholds(_Settings())) == expected


@pytest.mark.parametrize(
    "value,retuned,stock",
    [
        (0.39, "normal", "normal"),
        (0.4, "dikkat", "normal"),
        (0.79, "dikkat", "dikkat"),
        (0.8, "kritik-yakin", "dikkat"),
        (1.49, "kritik-yakin", "kritik"),
        (1.5, "kritik", "kritik"),
    ],
)
def test_retuned_bands_move_the_edges_with_config(value, retuned, stock):
    thresholds = level_thresholds(_RetunedSettings())
    assert thresholds == {
        "normal_max": 0.4,
        "caution_max": 0.8,
        "critical_near_max": 1.5,
    }
    assert classify_risk(value, thresholds) == retuned
    assert classify_risk(value, level_thresholds(_Settings())) == stock


def test_extreme_demand_stays_finite_and_critical(session):
    """1e9 ha polygon over 30 dk: 2e9 ha/h demand against one crew."""
    _scene(session, crews=1, area_ha=1e9)
    row = _only_row(session)
    assert row["demand_ha_h"] == pytest.approx(2e9)
    assert row["risk_index"] is not None
    assert math.isfinite(row["risk_index"])
    assert row["risk_index"] > 1.2
    assert row["level"] == "kritik"
    assert row["gap_ha_h"] == pytest.approx(2e9 - 2.0)


def test_extreme_capacity_washes_out_to_zero_risk(session):
    """One absurdly effective crew: ratio underflows the 3-decimal rounding."""
    _scene(session, crews=1, area_ha=6.0)
    row = _only_row(session, _CrewSettings(1_000_000.0))
    assert row["risk_index"] == pytest.approx(0.0)
    assert row["level"] == "normal"
    assert row["gap_ha_h"] == pytest.approx(0.0)


def test_tiny_nonzero_capacity_does_not_become_zero(session):
    """0.001 ha/h is not "no capacity": risk is measurable, not None."""
    _scene(session, crews=1, area_ha=6.0)
    row = _only_row(session, _CrewSettings(0.001))
    assert row["risk_index"] == pytest.approx(12000.0)
    assert math.isfinite(row["risk_index"])
    assert row["level"] == "kritik"


def test_zero_capacity_with_demand_is_unmeasurable_and_worst(session):
    _scene(session, crews=0, area_ha=6.0)
    payload = compute_risk_index(session, _Settings())
    assert payload["capacity_effective_ha_h"] == pytest.approx(0.0)
    row = payload["events"][0]["horizons"][0]
    assert row["risk_index"] is None
    assert row["level"] == "kritik"
    # With nothing to suppress with, the whole demand is the gap.
    assert row["gap_ha_h"] == pytest.approx(DEMAND_12)
    assert payload["events"][0]["peak_level"] == "kritik"
    assert payload["events"][0]["peak_risk_index"] is None
    assert payload["summary"]["max_risk_index"] is None
    assert payload["summary"]["level_counts"]["kritik"] == 1


def test_zero_capacity_and_zero_demand_is_zero_risk(session):
    _scene(session, crews=0, area_ha=0.0)
    row = _only_row(session)
    assert row["demand_ha_h"] == pytest.approx(0.0)
    assert row["risk_index"] == pytest.approx(0.0)
    assert row["level"] == "normal"


def test_degenerate_demand_inputs_do_not_divide_by_zero():
    """Degenerate inputs must not divide by zero."""
    assert demand_ha_h(0.0, 30) == 0.0
    assert demand_ha_h(1e9, 0) == 0.0
    assert demand_ha_h(1e9, -5) == 0.0


# --------------------------------------------- capacity change -> index ---


@pytest.mark.parametrize(
    "crews,expected_ratio,expected_level",
    [
        (1, 6.0, "kritik"),
        (2, 3.0, "kritik"),
        (3, 2.0, "kritik"),
        (5, 1.2, "kritik"),  # exactly on the kritik edge
        (6, 1.0, "kritik-yakin"),
        (7, 0.857, "dikkat"),
        (10, 0.6, "dikkat"),  # exactly on the dikkat edge
        (13, 0.462, "normal"),
        (20, 0.3, "normal"),
    ],
)
def test_capacity_change_moves_index_and_bands(
    session, crews, expected_ratio, expected_level
):
    """Fixed demand 12.0 ha/h, capacity = crews x 2.0 -> risk = 6/crews."""
    _scene(session, crews=crews)
    row = _only_row(session)
    assert row["demand_ha_h"] == pytest.approx(DEMAND_12)
    assert row["risk_index"] == pytest.approx(expected_ratio, abs=1e-3)
    assert row["level"] == expected_level


def test_index_is_monotonically_non_increasing_as_capacity_grows(session):
    _scene(session, crews=0)
    ratios = []
    for crews in range(1, 21):
        _crew(session, f"MON-C{crews}")
        payload = compute_risk_index(session, _Settings())
        row = payload["events"][0]["horizons"][0]
        ratios.append(row["risk_index"])
        assert payload["capacity_effective_ha_h"] == pytest.approx(2.0 * crews)
    assert all(current <= previous for previous, current in zip(ratios, ratios[1:]))
    assert ratios[0] > ratios[-1]


def test_freeing_a_busy_resource_lowers_the_index(session):
    _event(session)
    _forecast(session, "EVT-B", 30, 6.0)
    for index in range(1, 11):  # 10 crews, one of them deployed
        _crew(session, f"FR-C{index}", status="available")
    busy = _crew(session, "FR-C11", status="deployed")
    before = _only_row(session)
    assert before["risk_index"] == pytest.approx(0.6)  # 12.0 / 20.0

    busy.status = "available"
    session.commit()

    after = _only_row(session)
    assert after["risk_index"] == pytest.approx(0.545)  # 12.0 / 22.0
    assert after["risk_index"] < before["risk_index"]
    assert after["level"] == "normal"


def test_deployed_crews_hold_the_index_in_a_higher_band(session):
    """Same eight crews: keeping two busy lifts the index one band higher."""
    _event(session)
    _forecast(session, "EVT-B", 30, 6.0)
    busy = [_crew(session, f"DP-C{index}", status="deployed") for index in (1, 2)]
    for index in range(3, 9):
        _crew(session, f"DP-C{index}", status="available")
    busy_row = _only_row(session)
    assert busy_row["risk_index"] == pytest.approx(1.0)  # 12.0 / 12.0
    assert busy_row["level"] == "kritik-yakin"

    for resource in busy:
        resource.status = "available"
    session.commit()
    released = _only_row(session)
    assert released["risk_index"] == pytest.approx(0.75)  # 12.0 / 16.0
    assert released["level"] == "dikkat"
    assert released["gap_ha_h"] == pytest.approx(0.0)


def test_assumption_edit_rescales_the_whole_index(session):
    """Admin doubles the per-crew ha/hour unit: the index halves, band by band."""
    _scene(session, crews=6)
    before = _only_row(session)
    assert before["risk_index"] == pytest.approx(1.0)  # 12.0 / 12.0
    assert before["level"] == "kritik-yakin"

    update_assumptions(session, _Settings(), {"crew": 4.0}, updated_by="test")
    after = _only_row(session)
    assert after["risk_index"] == pytest.approx(0.5)  # 12.0 / 24.0
    assert after["level"] == "normal"

    update_assumptions(session, _Settings(), {"crew": 1.0}, updated_by="test")
    weaker = _only_row(session)
    assert weaker["risk_index"] == pytest.approx(2.0)  # 12.0 / 6.0
    assert weaker["level"] == "kritik"


def test_losing_all_capacity_flips_the_event_to_unmeasurable(session):
    _event(session)
    _forecast(session, "EVT-B", 30, 6.0)
    crews = [_crew(session, f"LO-C{index}") for index in range(1, 4)]
    assert _only_row(session)["risk_index"] == pytest.approx(2.0)  # 12.0 / 6.0
    for resource in crews:
        resource.status = "maintenance"
    session.commit()
    row = _only_row(session)
    assert row["risk_index"] is None
    assert row["level"] == "kritik"


def test_zero_assumption_nulls_capacity_even_with_crews_on_site(session):
    """A 0.0 ha/hour unit makes every crew count for nothing: unmeasurable."""
    _scene(session, crews=4)
    assert _only_row(session)["risk_index"] == pytest.approx(1.5)  # 12.0 / 8.0
    update_assumptions(session, _Settings(), {"crew": 0.0}, updated_by="test")
    payload = compute_risk_index(session, _Settings())
    assert payload["capacity_effective_ha_h"] == pytest.approx(0.0)
    row = payload["events"][0]["horizons"][0]
    assert row["risk_index"] is None
    assert row["level"] == "kritik"


def test_sub_rounding_assumption_collapses_to_no_capacity(session):
    """Capacity is kept at 3 decimals, so 0.0004 ha/h reads as genuine zero."""
    _scene(session, crews=1)
    update_assumptions(session, _Settings(), {"crew": 0.0004}, updated_by="test")
    assert _only_row(session)["risk_index"] is None
    # One order of magnitude up it survives the rounding and stays measurable.
    update_assumptions(session, _Settings(), {"crew": 0.004}, updated_by="test")
    measurable = _only_row(session)
    assert measurable["risk_index"] == pytest.approx(3000.0)  # 12.0 / 0.004
    assert measurable["level"] == "kritik"


def test_enormous_assumption_holds_any_forecast(session):
    """A billion-ha/h unit against a 1e6 ha polygon is a negligible ratio."""
    _scene(session, crews=1, area_ha=1e6)
    row = _only_row(session, _CrewSettings(1e9))
    assert row["demand_ha_h"] == pytest.approx(2e6)
    assert row["risk_index"] == pytest.approx(0.002)  # 2e6 / 1e9
    assert row["level"] == "normal"
    assert row["gap_ha_h"] == pytest.approx(0.0)


# -------------------------------------------------------- robustness -----


def test_index_is_repeatable_across_extremes(session):
    _scene(session, crews=1, area_ha=1e9)
    first = _only_row(session)
    second = _only_row(session)
    assert first == second


def test_peak_and_summary_survive_mixed_magnitudes(session):
    """A giant incident and a trivial one scored in the same pass."""
    _event(session, key="EVT-HUGE")
    _forecast(session, "EVT-HUGE", 30, 1e6)  # demand 2e6 ha/h
    _event(session, key="EVT-TINY")
    _forecast(session, "EVT-TINY", 120, 0.001)  # demand 0.0005 ha/h
    _crew(session, "MIX-C1")  # 2.0 ha/h
    payload = compute_risk_index(session, _Settings())
    by_key = {event["event_key"]: event for event in payload["events"]}
    assert by_key["EVT-HUGE"]["peak_level"] == "kritik"
    assert math.isfinite(by_key["EVT-HUGE"]["peak_risk_index"])
    tiny = by_key["EVT-TINY"]["peak_risk_index"]
    assert tiny is not None and tiny < 0.6  # rounds to nothing against capacity
    assert by_key["EVT-TINY"]["peak_level"] == "normal"
    assert payload["summary"]["max_risk_event"] == "EVT-HUGE"
    assert payload["summary"]["level_counts"]["kritik"] == 1


def test_endpoint_accepts_extreme_magnitudes(client, session):
    _scene(session, crews=1, area_ha=1e9)
    session.commit()
    response = client.get("/api/v1/risk-index", params={"event_key": "EVT-B"})
    assert response.status_code == 200
    row = response.json()["events"][0]["horizons"][0]
    assert row["risk_index"] is not None
    assert math.isfinite(row["risk_index"])
    assert row["level"] == "kritik"
