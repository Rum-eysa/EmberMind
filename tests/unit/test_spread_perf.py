"""EM-022 model performance optimization tests.

Covers the layer cache (hits/TTL/invalidation), the vectorized batch
land-cover sampler (must match the scalar per-vertex queries exactly), the
before/after benchmark report against the 10-second operator target, the
cProfile hot-function report and the REST endpoints.
"""
from datetime import timedelta

import pytest

from src.models.land_cover import LandCoverDataPoint
from src.models.topography import TopographyDataPoint
from src.models.weather import WeatherDataPoint
from src.services.barriers import register_barrier
from src.services.layer_cache import LayerCache, layer_cache
from src.services.spread import (
    _batch_fuel_numbers,
    _fuel_number_at_offset,
    fuel_transition_polygon,
    resolve_inputs,
)
from src.services.spread_perf import (
    REFERENCE_SCENARIO,
    benchmark_reference_scenario,
    list_performance_runs,
    profile_reference_scenario,
)
from src.utils.timeutils import utc_now

LAT0, LON0 = 37.0, 28.0
M_PER_DEG = 111320.0


class PerfOnSettings:
    """Settings stub with the EM-022 optimizations switched on."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"
    FUEL_TRANSITION_ENABLED = True
    SPREAD_BARRIERS_ENABLED = True
    FUEL_MOISTURE_MODEL_ENABLED = False
    SPREAD_UNCERTAINTY_WIND_DIR_DELTA_DEG = 10.0
    SPREAD_UNCERTAINTY_WIND_SPEED_FRACTION = 0.15
    SPREAD_PERF_ENABLED = True
    SPREAD_PERF_CACHE_TTL_SECONDS = 120.0
    SPREAD_PERF_CACHE_GRID_DEG = 0.001


class PerfOffSettings(PerfOnSettings):
    SPREAD_PERF_ENABLED = False


class BareSettings:
    """Legacy stub: no EM-022 attributes at all -> scalar path, no cache."""

    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SPREAD_POLYGON_VERTICES = 36
    SPREAD_MODEL_NAME = "rothermel_v1"


@pytest.fixture(autouse=True)
def _fresh_cache():
    layer_cache().reset()
    yield
    layer_cache().reset()


def _seed_layers(session):
    """One weather/topo/land-cover triple near the ignition point."""
    now = utc_now()
    session.add(
        WeatherDataPoint(
            latitude=LAT0,
            longitude=LON0,
            temperature=30.0,
            humidity=30.0,
            wind_speed=7.0,
            wind_deg=225.0,
            forecast_time=now,
            fetched_at=now - timedelta(hours=1),
        )
    )
    session.add(
        TopographyDataPoint(
            latitude=LAT0,
            longitude=LON0,
            elevation=300.0,
            slope=15.0,
            aspect=180.0,
            fetched_at=now - timedelta(hours=1),
        )
    )
    session.add(
        LandCoverDataPoint(
            latitude=LAT0,
            longitude=LON0,
            fuel_model="FM10_RedPine",
            land_cover_class="kızılçam",
            fetched_at=now - timedelta(hours=1),
        )
    )
    session.commit()


# --- LayerCache unit behaviour -------------------------------------------------


def test_layer_cache_hits_expiry_and_invalidation():
    clock = {"now": 1000.0}
    cache = LayerCache(clock=lambda: clock["now"])
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return f"value-{calls['n']}"

    session = _FakeSession()
    assert cache.get_or_load(session, ("w", 1, 2), loader, 60.0) == "value-1"
    assert cache.get_or_load(session, ("w", 1, 2), loader, 60.0) == "value-1"
    assert cache.stats()["hits"] == 1
    # TTL elapsed -> reload.
    clock["now"] += 61.0
    assert cache.get_or_load(session, ("w", 1, 2), loader, 60.0) == "value-2"
    # Prefix invalidation drops only matching keys.
    cache.get_or_load(session, ("b",), loader, 60.0)
    assert cache.invalidate(("w",)) == 1
    assert cache.get_or_load(session, ("b",), loader, 60.0) == "value-3"
    cache.reset()
    assert cache.stats() == {
        "hits": 0,
        "misses": 0,
        "invalidations": 0,
        "entries": 0,
    }


class _FakeSession:
    """Weak-referenceable stand-in for a DB session in cache unit tests."""


def test_layer_cache_ttl_zero_bypasses_cache():
    cache = LayerCache()
    session = _FakeSession()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    assert cache.get_or_load(session, ("k",), loader, 0.0) == 1
    assert cache.get_or_load(session, ("k",), loader, 0.0) == 2
    assert cache.stats()["hits"] == 0


def test_cache_is_isolated_per_session():
    cache = LayerCache()
    loader = lambda: "x"  # noqa: E731
    cache.get_or_load(_FakeSession(), ("k",), loader, 60.0)
    cache.get_or_load(_FakeSession(), ("k",), loader, 60.0)
    assert cache.stats()["misses"] == 2


# --- resolve_inputs through the cache ----------------------------------------


def test_resolve_inputs_serves_repeat_lookups_from_cache(session):
    _seed_layers(session)
    req = {"latitude": LAT0, "longitude": LON0}
    first = resolve_inputs(session, req, PerfOnSettings())
    second = resolve_inputs(session, req, PerfOnSettings())
    assert first["inputs"] == second["inputs"]
    assert first["provenance"] == second["provenance"]
    stats = layer_cache().stats()
    assert stats["misses"] == 3 and stats["hits"] == 3  # weather/topo/cover


def test_stale_cache_is_visible_until_invalidated(session):
    _seed_layers(session)
    req = {"latitude": LAT0, "longitude": LON0}
    resolve_inputs(session, req, PerfOnSettings())
    row = session.query(WeatherDataPoint).first()
    row.temperature = 40.0
    session.commit()
    cached = resolve_inputs(session, req, PerfOnSettings())
    assert cached["inputs"]["air_temp_c"] == 30.0  # served from cache
    layer_cache().invalidate()
    fresh = resolve_inputs(session, req, PerfOnSettings())
    assert fresh["inputs"]["air_temp_c"] == 40.0


def test_bare_settings_never_touch_the_cache(session):
    _seed_layers(session)
    resolve_inputs(session, {"latitude": LAT0, "longitude": LON0}, BareSettings())
    stats = layer_cache().stats()
    assert stats["hits"] == 0 and stats["misses"] == 0


# --- vectorized batch sampling -------------------------------------------------


def _seed_fuel_field(session):
    """Heterogeneous fuel mosaic with distinct fetch times around LON0/LAT0."""
    now = utc_now()
    for idx, (east_m, north_m, label, age_h) in enumerate(
        (
            (900.0, 0.0, "FM1_Agriculture", 5),
            (-900.0, 0.0, "FM4_Maquis", 4),
            (0.0, 900.0, "FM8_MixedForest", 3),
            (0.0, -900.0, "FM10_RedPine", 2),
            (400.0, 400.0, "FM1_Agriculture", 1),  # newest, overlaps the NE
            (400.0, 400.0, "FM4_Maquis", 9),  # older twin -> must lose
        )
    ):
        session.add(
            LandCoverDataPoint(
                latitude=LAT0 + north_m / M_PER_DEG,
                longitude=LON0 + east_m / (M_PER_DEG * 0.8),
                fuel_model=label,
                fetched_at=now - timedelta(hours=age_h),
                cluster_key=f"perf-{idx}",
            )
        )
    session.commit()


def test_batch_fuel_numbers_match_scalar_queries(session):
    _seed_fuel_field(session)
    samples = [
        (east, north)
        for east in (-1500.0, -400.0, 0.0, 400.0, 1500.0)
        for north in (-1500.0, 0.0, 400.0, 1500.0)
    ]
    batch = _batch_fuel_numbers(session, LAT0, LON0, samples, default_number=4)
    scalar = [
        _fuel_number_at_offset(session, LAT0, LON0, east, north, 4)
        for east, north in samples
    ]
    assert batch == scalar
    assert set(batch) != {4}  # the mosaic is actually being sampled


def test_fuel_transition_polygon_paths_produce_identical_rings(session):
    _seed_fuel_field(session)
    args = (session, 1600.0, 120.0, 37.8, 10)
    points_off, zones_off = fuel_transition_polygon(
        *args,
        ignition_lat=LAT0,
        ignition_lon=LON0,
        vertices=72,
        settings=PerfOffSettings(),
    )
    points_on, zones_on = fuel_transition_polygon(
        *args,
        ignition_lat=LAT0,
        ignition_lon=LON0,
        vertices=72,
        settings=PerfOnSettings(),
    )
    assert points_on == points_off
    assert zones_on == zones_off
    assert len(points_off) == 73


# --- barrier cache --------------------------------------------------------------


def _sea(barrier_key: str) -> dict:
    return {
        "barrier_key": barrier_key,
        "name": f"Deniz {barrier_key}",
        "barrier_type": "sea",
        "geometry_wkt": "POLYGON((28.05 37.05, 28.2 37.05, 28.2 37.2, 28.05 37.2, 28.05 37.05))",
    }


def test_barrier_load_is_cached_and_invalidated_by_writes(session):
    from src.services.barriers import load_active_barriers

    register_barrier(session, _sea("SEA-1"))
    first = load_active_barriers(session, PerfOnSettings())
    second = load_active_barriers(session, PerfOnSettings())
    assert first == second and len(first) == 1
    assert layer_cache().stats()["hits"] >= 1
    register_barrier(session, _sea("SEA-2"))  # write invalidates the cache
    assert len(load_active_barriers(session, PerfOnSettings())) == 2


# --- benchmark and profile reports ----------------------------------------------


def test_benchmark_reports_before_and_after_and_persists(session):
    _seed_layers(session)
    report = benchmark_reference_scenario(
        session, BareSettings(), scenario=REFERENCE_SCENARIO, repeats=1
    )
    assert report["scenario_key"] == "reference_pilot"
    assert report["baseline"]["total_ms"] > 0
    assert report["optimized"]["total_ms"] > 0
    assert report["optimized"]["cache_stats"]["misses"] > 0
    assert report["speedup"] > 0
    assert report["target_seconds"] == 10.0
    assert report["target_met"] is True  # reference scenario is ms-scale
    runs = list_performance_runs(session)
    assert len(runs) == 1
    assert runs[0]["run_key"] == report["run_key"]


def test_profile_lists_hot_functions(session):
    _seed_layers(session)
    profile = profile_reference_scenario(
        session, BareSettings(), scenario=REFERENCE_SCENARIO, samples=2, top=5
    )
    assert profile["model"] == "spread_perf_v1"
    assert profile["samples"] == 2
    assert profile["total_ms"] > 0
    assert 1 <= len(profile["top_functions"]) <= 5
    names = " ".join(fn["function"] for fn in profile["top_functions"])
    assert "spread" in names or "session" in names or "_" in names


# --- REST endpoints ---------------------------------------------------------------


def test_performance_endpoints(client):
    bench = client.post("/api/v1/spread/performance/benchmark", params={"repeats": 1})
    assert bench.status_code == 200
    assert bench.json()["target_met"] is True

    listing = client.get("/api/v1/spread/performance")
    assert listing.status_code == 200
    body = listing.json()
    assert body["model"] == "spread_perf_v1"
    assert body["count"] == 1
    assert {"hits", "misses", "entries"} <= set(body["cache"])

    profile = client.get(
        "/api/v1/spread/performance/profile", params={"samples": 1, "top": 3}
    )
    assert profile.status_code == 200
    assert len(profile.json()["top_functions"]) <= 3
