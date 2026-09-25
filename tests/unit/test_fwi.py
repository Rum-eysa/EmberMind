"""Unit tests for the Fire Weather Index (FWI) and drought layer (EM-014)."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from src.models.fwi import FireWeatherIndex
from src.models.weather import WeatherDataPoint
from src.services.fwi import (
    DEFAULT_DC,
    DEFAULT_DMC,
    DEFAULT_FFMC,
    compute_daily_fwi,
    compute_region_fwi,
    daily_summary,
    drought_category,
    fwi_map_layer,
    fwi_risk_category,
    initial_spread_index,
    iter_fwizones,
    previous_day_codes,
    zone_for_point,
)
from src.services.weather import OpenWeatherClient
from src.utils.timeutils import utc_now


class FwiSettings:
    """Minimal settings stub for FWI tests."""

    FWI_ZONE_SIZE_DEG = 0.5


def _seed_weather(
    session,
    day: date,
    lat: float,
    lon: float,
    temp: float,
    rh: float,
    wind: float,
    rain: float = 0.0,
) -> None:
    """Persist one weather data point for a zone test."""
    session.add(
        WeatherDataPoint(
            cluster_key="TEST-CLUSTER",
            latitude=lat,
            longitude=lon,
            temperature=temp,
            humidity=rh,
            wind_speed=wind,
            wind_deg=180.0,
            rain=rain,
            forecast_offset_hours=0,
            forecast_time=datetime(day.year, day.month, day.day, 6, 0),
            fetched_at=datetime(day.year, day.month, day.day, 5, 0),
            source="Test",
        )
    )
    session.commit()


def test_risk_category_boundaries():
    assert fwi_risk_category(0.0) == "very_low"
    assert fwi_risk_category(4.9) == "very_low"
    assert fwi_risk_category(5.0) == "low"
    assert fwi_risk_category(20.0) == "moderate"
    assert fwi_risk_category(30.0) == "high"
    assert fwi_risk_category(45.0) == "very_high"
    assert fwi_risk_category(60.0) == "extreme"


def test_drought_category_boundaries():
    assert drought_category(100.0) == "no_drought"
    assert drought_category(200.0) == "low"
    assert drought_category(270.0) == "moderate"
    assert drought_category(320.0) == "high"
    assert drought_category(380.0) == "very_high"
    assert drought_category(450.0) == "extreme"


def test_isi_increases_with_wind():
    calm = initial_spread_index(2.0, 90.0)
    windy = initial_spread_index(25.0, 90.0)
    assert windy > calm


def test_rain_thresholds_ignore_light_rain():
    # Below the FFMC 0.5 mm threshold the codes must not react to rain.
    dry = compute_daily_fwi(37.75, 7, 28.0, 25.0, 12.0, 0.0)
    drizzle = compute_daily_fwi(37.75, 7, 28.0, 25.0, 12.0, 0.4)
    assert abs(dry.ffmc - drizzle.ffmc) < 1e-9
    assert abs(dry.dmc - drizzle.dmc) < 1e-9
    assert abs(dry.dc - drizzle.dc) < 1e-9


def test_heavy_rain_cools_all_codes():
    dry = compute_daily_fwi(37.75, 7, 30.0, 25.0, 10.0, 0.0)
    wet = compute_daily_fwi(
        37.75,
        7,
        30.0,
        25.0,
        10.0,
        15.0,
        prev_ffmc_value=95.0,
        prev_dmc_value=dry.dmc,
        prev_dc_value=dry.dc,
    )
    assert wet.ffmc < 95.0
    assert wet.dmc < dry.dmc
    assert wet.dc < dry.dc


def test_multi_day_drought_chain_reaches_extreme():
    ffmc_prev, dmc_prev, dc_prev = DEFAULT_FFMC, DEFAULT_DMC, DEFAULT_DC
    components = None
    for _ in range(12):
        components = compute_daily_fwi(
            37.75, 7, 35.0, 15.0, 24.0, 0.0, ffmc_prev, dmc_prev, dc_prev
        )
        ffmc_prev, dmc_prev, dc_prev = components.ffmc, components.dmc, components.dc
    assert components is not None
    assert components.fwi > 40.0
    assert components.risk_category in ("very_high", "extreme")
    assert components.dc > 100.0


def test_wet_cool_day_is_very_low():
    components = compute_daily_fwi(37.75, 1, 8.0, 92.0, 4.0, 18.0, prev_ffmc_value=60.0)
    assert components.risk_category == "very_low"
    assert components.fwi < 5.0


def test_zones_tile_pilot_bbox_completely():
    zones = list(iter_fwizones(0.5))
    # bbox 36..39.5 x 26..30 -> 7 rows x 8 cols
    assert len(zones) == 56
    inside = zone_for_point(38.0, 27.5, 0.5)
    assert inside is not None
    assert inside.zone_key == "FWI_R4C3"
    assert zone_for_point(45.0, 27.5, 0.5) is None


def test_compute_region_fwi_persists_and_upserts(session):
    day = date(2026, 7, 15)
    _seed_weather(session, day, 38.0, 27.5, 34.0, 18.0, 22.0)
    _seed_weather(session, day, 38.1, 27.6, 35.0, 16.0, 24.0)

    result = compute_region_fwi(session, FwiSettings(), day)
    session.commit()
    assert result["zones_computed"] == 1
    assert result["day"] == day.isoformat()

    # Recompute the same day: must update in place (unique zone/day row).
    result2 = compute_region_fwi(session, FwiSettings(), day)
    session.commit()
    rows = session.scalars(
        select(FireWeatherIndex).where(FireWeatherIndex.day == day)
    ).all()
    assert result2["zones_computed"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row.data_point_count == 2
    assert row.risk_category == fwi_risk_category(row.fwi)


def test_compute_skips_zones_without_weather(session):
    day = date(2026, 7, 16)
    result = compute_region_fwi(session, FwiSettings(), day)
    session.commit()
    assert result["zones_computed"] == 0
    assert result["zones_skipped"] == 56


def test_previous_day_codes_carry_over(session):
    day1 = date(2026, 7, 10)
    day2 = date(2026, 7, 11)
    _seed_weather(session, day1, 38.0, 27.5, 33.0, 20.0, 18.0)
    compute_region_fwi(session, FwiSettings(), day1)
    session.commit()

    first = session.scalar(select(FireWeatherIndex).where(FireWeatherIndex.day == day1))
    assert first is not None
    prev = previous_day_codes(session, first.zone_key, day2)
    assert prev == (first.ffmc, first.dmc, first.dc)

    _seed_weather(session, day2, 38.0, 27.5, 36.0, 12.0, 26.0)
    compute_region_fwi(session, FwiSettings(), day2)
    session.commit()
    second = session.scalar(
        select(FireWeatherIndex).where(FireWeatherIndex.day == day2)
    )
    assert second is not None
    assert second.dc > first.dc  # drought keeps building on a hotter day

    # First day must still start from the canonical defaults.
    assert previous_day_codes(session, "FWI_R9C9", day1) == (
        DEFAULT_FFMC,
        DEFAULT_DMC,
        DEFAULT_DC,
    )


def test_rain_accumulates_per_forecast_slot(session):
    day = date(2026, 7, 20)
    # Two clusters in the same zone and same slot -> slot rain counted once.
    _seed_weather(session, day, 38.0, 27.5, 30.0, 40.0, 10.0, rain=4.0)
    _seed_weather(session, day, 38.05, 27.55, 30.0, 40.0, 10.0, rain=4.0)
    result = compute_region_fwi(session, FwiSettings(), day)
    session.commit()
    row = session.scalar(select(FireWeatherIndex).where(FireWeatherIndex.day == day))
    assert result["zones_computed"] == 1
    assert row is not None
    assert row.rain == pytest.approx(4.0)


def _compute_hot_chain(session) -> date:
    """Run 35 hot/dry/dry days in one zone; return the final day."""
    start = date(2026, 8, 1)
    for offset in range(35):
        day = start + timedelta(days=offset)
        _seed_weather(session, day, 37.2, 26.2, 36.0, 14.0, 25.0)
        compute_region_fwi(session, FwiSettings(), day)
        session.commit()
    return start + timedelta(days=34)


def test_daily_summary_focuses_on_high_risk(session):
    last_day = _compute_hot_chain(session)
    summary = daily_summary(session, FwiSettings(), last_day)
    assert summary["day"] == last_day.isoformat()
    assert summary["zones_total"] == 1
    assert summary["zones_high_risk"] == 1
    zone = summary["high_risk_zones"][0]
    assert zone["risk_category"] in ("high", "very_high", "extreme")
    assert summary["max_fwi_zone"]["zone_key"] == zone["zone_key"]
    assert "recommendation" in summary
    assert summary["drought_watch"]  # 35 drought days push DC into watch range


def test_daily_summary_quiet_day(session):
    day = date(2026, 1, 10)
    _seed_weather(session, day, 38.0, 27.5, 7.0, 95.0, 3.0, rain=20.0)
    compute_region_fwi(session, FwiSettings(), day)
    session.commit()
    summary = daily_summary(session, FwiSettings(), day)
    assert summary["zones_high_risk"] == 0
    assert summary["high_risk_zones"] == []
    assert "routine" in summary["recommendation"]


def test_map_layer_is_geojson(session):
    last_day = _compute_hot_chain(session)
    layer = fwi_map_layer(session, FwiSettings(), last_day)
    assert layer["type"] == "FeatureCollection"
    assert layer["layer"] == "fire_weather_index"
    assert layer["count"] == 1
    feature = layer["features"][0]
    ring = feature["geometry"]["coordinates"][0]
    assert len(ring) == 5 and ring[0] == ring[-1]
    assert feature["properties"]["risk_category"] in ("high", "very_high", "extreme")
    assert feature["properties"]["color"]
    assert "extreme" in layer["legend"]


def test_extract_rain_mm_handles_openweather_shapes():
    assert OpenWeatherClient._extract_rain_mm({"rain": {"3h": 2.5}}) == 2.5
    assert OpenWeatherClient._extract_rain_mm({"rain": {"1h": 0.4, "3h": 1.1}}) == 1.5
    assert OpenWeatherClient._extract_rain_mm({}) == 0.0
    assert OpenWeatherClient._extract_rain_mm({"rain": 3.0}) == 3.0


def test_fwi_endpoints(client, api):
    day = date(2026, 7, 5)
    with api.state.database.session() as session:
        _seed_weather(session, day, 38.0, 27.5, 34.0, 18.0, 22.0)

    compute = client.post(f"/api/v1/fwi/compute?day={day.isoformat()}")
    assert compute.status_code == 200
    assert compute.json()["zones_computed"] == 1

    listing = client.get("/api/v1/fwi").json()
    assert listing["count"] == 1
    assert listing["attribution"]

    layer = client.get("/api/v1/fwi/map").json()
    assert layer["day"] == day.isoformat()

    summary = client.get("/api/v1/fwi/daily-summary").json()
    assert summary["zones_total"] == 1

    bad = client.get("/api/v1/fwi?day=not-a-date")
    assert bad.status_code == 400


def test_empty_fwi_endpoints_before_first_compute(client):
    listing = client.get("/api/v1/fwi").json()
    assert listing["count"] == 0
    assert listing["day"] is None
    layer = client.get("/api/v1/fwi/map").json()
    assert layer["features"] == []
    summary = client.get("/api/v1/fwi/daily-summary").json()
    assert summary["zones_total"] == 0


def test_pipeline_trigger_includes_fwi(client, api):
    # The trigger computes for "today", so seed weather for the current day.
    day = utc_now().date()
    with api.state.database.session() as session:
        _seed_weather(session, day, 38.0, 27.5, 33.0, 20.0, 20.0)

    response = client.post("/api/v1/pipeline/trigger", json={"source": "fwi"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "triggered"
    assert body["results"]["fwi"]["zones_computed"] == 1

    status = client.get("/api/v1/pipeline/status").json()
    assert "FWI" in status["schedules"]
