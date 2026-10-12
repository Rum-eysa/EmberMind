"""EM-122 spread-engine reference scenarios (fuel x wind x slope combinations).

Acceptance criteria from the issue:
 - at least 5 reference scenarios covering fuel/slope/wind combinations,
 - outputs compared within an explicit tolerance (not brittle exact literals),
 - the scenarios run inside the ordinary CI pytest invocation.

The expected numbers below are the golden output of the pinned ``rothermel_v1``
engine. They were captured once from the engine itself and are asserted with a
tolerance, so a future regression in Rothermel's intermediates (fuel-bed sigma,
packing ratio, wind/slope factors, ellipse geometry) fails here even when the
change is small, while a deliberate model-version bump stays a conscious edit.

Scenario names encode the interesting physics being pinned:
 - calm + flat has no driving force at all (circular risk zone, no direction),
 - calm + steep is slope-driven only (fire runs upslope, i.e. away from aspect),
 - a gale from the north with flat terrain is wind-driven only (bearing 180),
 - moisture above the model's extinction threshold extinguishes the spread,
 - high winds on litter-heavy conifer fuel stay bounded rather than diverging.
"""
from __future__ import annotations

from typing import Optional

import pytest

from src.services.spread import (
    fire_ellipse_polygon,
    polygon_area_m2,
    spread_direction_deg,
    spread_rates,
)

POLYGON_VERTICES = 36
HORIZON_MINUTES = 60.0

# name, fuel model, moisture %, wind km/h @10 m, slope deg, wind-from deg,
# aspect deg -> golden outputs of the pinned engine.
REFERENCE_SCENARIOS: list[dict[str, object]] = [
    {
        "name": "S1_shortgrass_calm_flat",
        "fuel_model": 1,
        "fuel_moisture_pct": 6.0,
        "wind_kmh_10m": 0.0,
        "slope_deg": 0.0,
        "wind_from_deg": 225.0,
        "aspect_deg": 180.0,
        "base_m_min": 1.404,
        "head_m_min": 1.404,
        "wind_factor": 0.0,
        "slope_factor": 0.0,
        "reaction_intensity": 826.13,
        "direction_deg": None,
        "area_60min_ha": 2.218,
        "first_vertex": [0.0, 84.24],
    },
    {
        "name": "S2_shortgrass_windward_flat",
        "fuel_model": 1,
        "fuel_moisture_pct": 6.0,
        "wind_kmh_10m": 30.0,
        "slope_deg": 0.0,
        "wind_from_deg": 225.0,
        "aspect_deg": 180.0,
        "base_m_min": 1.404,
        "head_m_min": 57.402,
        "wind_factor": 39.8938,
        "slope_factor": 0.0,
        "reaction_intensity": 826.13,
        "direction_deg": 45.0,
        "area_60min_ha": 276.588,
        "first_vertex": [2435.36, 2435.36],
    },
    {
        "name": "S3_tallgrass_wind_and_slope",
        "fuel_model": 3,
        "fuel_moisture_pct": 8.0,
        "wind_kmh_10m": 20.0,
        "slope_deg": 25.0,
        "wind_from_deg": 270.0,
        "aspect_deg": 180.0,
        "base_m_min": 1.31,
        "head_m_min": 48.414,
        "wind_factor": 28.223,
        "slope_factor": 7.7363,
        "reaction_intensity": 2691.17,
        "direction_deg": 74.7,
        "area_60min_ha": 208.917,
        "first_vertex": [2801.88, 766.51],
    },
    {
        "name": "S4_chaparral_typical_summer",
        "fuel_model": 4,
        "fuel_moisture_pct": 12.0,
        "wind_kmh_10m": 25.0,
        "slope_deg": 15.0,
        "wind_from_deg": 225.0,
        "aspect_deg": 180.0,
        "base_m_min": 3.895,
        "head_m_min": 154.892,
        "wind_factor": 36.755,
        "slope_factor": 2.0103,
        "reaction_intensity": 17259.87,
        "direction_deg": 42.9,
        "area_60min_ha": 2047.415,
        "first_vertex": [6326.29, 6807.9],
    },
    {
        "name": "S5_conifer_litter_steep",
        "fuel_model": 10,
        "fuel_moisture_pct": 12.0,
        "wind_kmh_10m": 25.0,
        "slope_deg": 20.0,
        "wind_from_deg": 225.0,
        "aspect_deg": 180.0,
        "base_m_min": 0.903,
        "head_m_min": 13.468,
        "wind_factor": 11.5451,
        "slope_factor": 2.3622,
        "reaction_intensity": 12022.41,
        "direction_deg": 37.8,
        "area_60min_ha": 27.518,
        "first_vertex": [495.28, 638.51],
    },
    {
        "name": "S6_slash_damp_light_wind",
        "fuel_model": 6,
        "fuel_moisture_pct": 18.0,
        "wind_kmh_10m": 10.0,
        "slope_deg": 10.0,
        "wind_from_deg": 135.0,
        "aspect_deg": 0.0,
        "base_m_min": 1.071,
        "head_m_min": 10.879,
        "wind_factor": 8.2596,
        "slope_factor": 0.8985,
        "reaction_intensity": 5438.78,
        "direction_deg": 310.2,
        "area_60min_ha": 22.595,
        "first_vertex": [-498.56, 421.32],
    },
    {
        "name": "S7_shortneedle_litter_wet",
        "fuel_model": 8,
        "fuel_moisture_pct": 25.0,
        "wind_kmh_10m": 15.0,
        "slope_deg": 5.0,
        "wind_from_deg": 90.0,
        "aspect_deg": 45.0,
        "base_m_min": 0.082,
        "head_m_min": 0.319,
        "wind_factor": 2.8037,
        "slope_factor": 0.1095,
        "reaction_intensity": 1657.93,
        "direction_deg": 268.5,
        "area_60min_ha": 0.036,
        "first_vertex": [-19.13, -0.5],
    },
    {
        "name": "S8_chaparral_calm_steep",
        "fuel_model": 4,
        "fuel_moisture_pct": 12.0,
        "wind_kmh_10m": 0.0,
        "slope_deg": 20.0,
        "wind_from_deg": 225.0,
        "aspect_deg": 180.0,
        "base_m_min": 3.895,
        "head_m_min": 18.343,
        "wind_factor": 0.0,
        "slope_factor": 3.7092,
        "reaction_intensity": 17259.87,
        "direction_deg": 0.0,
        "area_60min_ha": 105.171,
        "first_vertex": [0.0, 1100.58],
    },
    {
        "name": "S9_shortgrass_over_moisture_extinction",
        "fuel_model": 1,
        "fuel_moisture_pct": 25.0,
        "wind_kmh_10m": 20.0,
        "slope_deg": 10.0,
        "wind_from_deg": 225.0,
        "aspect_deg": 180.0,
        "base_m_min": 0.0,
        "head_m_min": 0.0,
        "wind_factor": 17.2257,
        "slope_factor": 1.2793,
        "reaction_intensity": 0.0,
        "direction_deg": 42.1,
        "area_60min_ha": 0.0,
        "first_vertex": None,
    },
    {
        "name": "S10_conifer_litter_gale_flat",
        "fuel_model": 10,
        "fuel_moisture_pct": 10.0,
        "wind_kmh_10m": 60.0,
        "slope_deg": 0.0,
        "wind_from_deg": 0.0,
        "aspect_deg": 90.0,
        "base_m_min": 0.979,
        "head_m_min": 40.549,
        "wind_factor": 40.4029,
        "slope_factor": 0.0,
        "reaction_intensity": 12275.27,
        "direction_deg": 180.0,
        "area_60min_ha": 136.955,
        "first_vertex": [0.0, -2432.94],
    },
]

# Tolerances: rates and factors are rounded by the engine itself (3 and 4
# decimals), so the band only absorbs float noise; intensity and area keep a
# relative band because they span three orders of magnitude across scenarios.
RATE_TOLERANCE = 1e-3
FACTOR_TOLERANCE = 1e-4
INTENSITY_REL_TOLERANCE = 1e-3
DIRECTION_TOLERANCE = 0.05
AREA_REL_TOLERANCE = 1e-2
VERTEX_TOLERANCE = 0.01


def _scenario_ids() -> list[str]:
    return [str(item["name"]) for item in REFERENCE_SCENARIOS]


def _rates(scenario: dict[str, object]):
    return spread_rates(
        scenario["fuel_model"],  # type: ignore[arg-type]
        float(scenario["fuel_moisture_pct"]),  # type: ignore[arg-type]
        float(scenario["wind_kmh_10m"]),  # type: ignore[arg-type]
        float(scenario["slope_deg"]),  # type: ignore[arg-type]
    )


def _direction(scenario: dict[str, object]) -> Optional[float]:
    rates = _rates(scenario)
    return spread_direction_deg(
        float(scenario["wind_from_deg"]),  # type: ignore[arg-type]
        rates.wind_factor,
        float(scenario["aspect_deg"]),  # type: ignore[arg-type]
        float(scenario["slope_deg"]),  # type: ignore[arg-type]
        rates.slope_factor,
    )


def _polygon(scenario: dict[str, object]) -> list[list[float]]:
    rates = _rates(scenario)
    return fire_ellipse_polygon(
        rates.head_m_min * HORIZON_MINUTES,
        rates.base_m_min * HORIZON_MINUTES,
        _direction(scenario),
        POLYGON_VERTICES,
    )


def test_reference_suite_covers_the_acceptance_minimum():
    """Acceptance: >= 5 scenarios, >= 4 distinct fuel models, wind x slope mix."""
    assert len(REFERENCE_SCENARIOS) >= 5
    fuels = {item["fuel_model"] for item in REFERENCE_SCENARIOS}
    assert len(fuels) >= 4
    assert any(
        float(item["wind_kmh_10m"]) > 0 and float(item["slope_deg"]) > 0  # type: ignore[arg-type]
        for item in REFERENCE_SCENARIOS
    )
    assert any(
        float(item["wind_kmh_10m"]) == 0 and float(item["slope_deg"]) == 0  # type: ignore[arg-type]
        for item in REFERENCE_SCENARIOS
    )


@pytest.mark.parametrize("scenario", REFERENCE_SCENARIOS, ids=_scenario_ids())
def test_reference_scenario_rates_within_tolerance(scenario: dict[str, object]):
    """Acceptance: fuel x wind x slope combinations reproduce golden rates."""
    rates = _rates(scenario)
    assert rates.base_m_min == pytest.approx(
        float(scenario["base_m_min"]), abs=RATE_TOLERANCE  # type: ignore[arg-type]
    )
    assert rates.head_m_min == pytest.approx(
        float(scenario["head_m_min"]), abs=RATE_TOLERANCE  # type: ignore[arg-type]
    )
    assert rates.wind_factor == pytest.approx(
        float(scenario["wind_factor"]), abs=FACTOR_TOLERANCE  # type: ignore[arg-type]
    )
    assert rates.slope_factor == pytest.approx(
        float(scenario["slope_factor"]), abs=FACTOR_TOLERANCE  # type: ignore[arg-type]
    )
    assert rates.reaction_intensity == pytest.approx(
        float(scenario["reaction_intensity"]),  # type: ignore[arg-type]
        rel=INTENSITY_REL_TOLERANCE,
        abs=RATE_TOLERANCE,
    )
    assert rates.spread_multiplier == pytest.approx(
        1.0
        + float(scenario["wind_factor"])  # type: ignore[arg-type]
        + float(scenario["slope_factor"]),  # type: ignore[arg-type]
        abs=2 * FACTOR_TOLERANCE,
    )


@pytest.mark.parametrize("scenario", REFERENCE_SCENARIOS, ids=_scenario_ids())
def test_reference_scenario_direction_within_tolerance(scenario: dict[str, object]):
    expected = scenario["direction_deg"]
    direction = _direction(scenario)
    if expected is None:
        assert direction is None
        return
    assert direction is not None
    assert direction == pytest.approx(float(expected), abs=DIRECTION_TOLERANCE)


@pytest.mark.parametrize("scenario", REFERENCE_SCENARIOS, ids=_scenario_ids())
def test_reference_scenario_ellipse_within_tolerance(scenario: dict[str, object]):
    """Acceptance: the derived risk-zone geometry is pinned too, not only rates."""
    polygon = _polygon(scenario)
    expected_vertex = scenario["first_vertex"]
    if expected_vertex is None:
        assert polygon == []
        assert polygon_area_m2(polygon) == pytest.approx(0.0, abs=RATE_TOLERANCE)
        return
    area_ha = polygon_area_m2(polygon) / 1e4
    assert area_ha == pytest.approx(
        float(scenario["area_60min_ha"]),  # type: ignore[arg-type]
        rel=AREA_REL_TOLERANCE,
        abs=RATE_TOLERANCE,
    )
    assert polygon[0] == pytest.approx(
        [float(v) for v in expected_vertex], abs=VERTEX_TOLERANCE  # type: ignore[arg-type]
    )
    # The ring is closed and holds exactly the configured vertex count.
    assert polygon[-1] == polygon[0]
    assert len(polygon) == POLYGON_VERTICES + 1


def test_calm_flat_scenario_is_circular_and_directionless():
    """No wind and no slope: nothing drives the head, so the zone is a circle."""
    scenario = REFERENCE_SCENARIOS[0]
    assert _direction(scenario) is None
    polygon = _polygon(scenario)
    radii = [pytest.approx(round((x**2 + y**2) ** 0.5, 2)) for x, y in polygon[:-1]]
    head_m = float(scenario["head_m_min"]) * HORIZON_MINUTES  # type: ignore[arg-type]
    assert all(
        radius == pytest.approx(head_m, abs=VERTEX_TOLERANCE) for radius in radii
    )


def test_calm_steep_scenario_runs_upslope():
    """Aspect is the downslope bearing, so a slope-driven head points uphill."""
    scenario = next(
        s for s in REFERENCE_SCENARIOS if s["name"] == "S8_chaparral_calm_steep"
    )
    assert float(scenario["wind_factor"]) == 0.0  # type: ignore[arg-type]
    assert _direction(scenario) == pytest.approx(
        (float(scenario["aspect_deg"]) + 180.0) % 360.0,  # type: ignore[arg-type]
        abs=DIRECTION_TOLERANCE,
    )


def test_gale_from_north_on_flat_terrain_points_south():
    scenario = next(
        s for s in REFERENCE_SCENARIOS if s["name"] == "S10_conifer_litter_gale_flat"
    )
    assert float(scenario["slope_factor"]) == 0.0  # type: ignore[arg-type]
    assert _direction(scenario) == pytest.approx(180.0, abs=DIRECTION_TOLERANCE)


def test_moisture_above_extinction_threshold_stops_the_fire():
    """FM1 extinction moisture is 12 %: 25 % must not spread even in a wind."""
    dry = spread_rates(1, 6.0, 20.0, 10.0)
    wet = spread_rates(1, 25.0, 20.0, 10.0)
    assert dry.head_m_min > 0.0
    assert wet.base_m_min == 0.0
    assert wet.head_m_min == 0.0
    assert wet.reaction_intensity == 0.0
    assert _polygon(REFERENCE_SCENARIOS[8]) == []


@pytest.mark.parametrize("scenario", REFERENCE_SCENARIOS, ids=_scenario_ids())
def test_each_reference_scenario_is_repeatable(scenario: dict[str, object]):
    """Acceptance: the engine is deterministic for every pinned scenario."""
    assert _rates(scenario) == _rates(scenario)
    assert _direction(scenario) == _direction(scenario)
    assert _polygon(scenario) == _polygon(scenario)


def test_head_rate_grows_monotonically_with_wind():
    scenario = next(
        s for s in REFERENCE_SCENARIOS if s["name"] == "S1_shortgrass_calm_flat"
    )
    fuel = scenario["fuel_model"]
    moisture = float(scenario["fuel_moisture_pct"])  # type: ignore[arg-type]
    heads = [
        spread_rates(fuel, moisture, wind, 0.0).head_m_min  # type: ignore[arg-type]
        for wind in (0.0, 10.0, 20.0, 30.0)
    ]
    assert heads == sorted(heads)
    assert heads[-1] > heads[0]


def test_head_rate_grows_monotonically_with_slope():
    scenario = next(
        s for s in REFERENCE_SCENARIOS if s["name"] == "S4_chaparral_typical_summer"
    )
    fuel = scenario["fuel_model"]
    moisture = float(scenario["fuel_moisture_pct"])  # type: ignore[arg-type]
    wind = float(scenario["wind_kmh_10m"])  # type: ignore[arg-type]
    heads = [
        spread_rates(fuel, moisture, wind, slope).head_m_min  # type: ignore[arg-type]
        for slope in (0.0, 10.0, 20.0, 30.0)
    ]
    assert heads == sorted(heads)
    assert heads[-1] > heads[0]


def test_drier_fuel_burns_faster_for_every_reference_fuel_model():
    for scenario in REFERENCE_SCENARIOS:
        fuel = scenario["fuel_model"]
        wind = float(scenario["wind_kmh_10m"])  # type: ignore[arg-type]
        slope = float(scenario["slope_deg"])  # type: ignore[arg-type]
        wet = spread_rates(fuel, 20.0, wind, slope).head_m_min  # type: ignore[arg-type]
        dry = spread_rates(fuel, 8.0, wind, slope).head_m_min  # type: ignore[arg-type]
        assert dry >= wet
