"""EM-022 spread-model performance optimization: profiling and benchmarking.

The operator target is a spread recomputation within 10 seconds. This module
measures the reference scenario (pilot-region ignition, wind-driven FM10,
fuel-transition polygons, natural barriers and the EM-020 wind ensemble)
twice - once with the optimizations switched off (scalar per-vertex layer
queries, no cache) and once with them on (EM-022 layer cache + vectorized
batch sampling) - and persists the before/after timings as a
SpreadPerformanceRun so every engine change has an evidence trail.

``profile_reference_scenario`` additionally runs the scenario under cProfile
and returns the hottest functions, which is how the input-layer reads were
identified as the dominant cost (216 land-cover queries per prediction).
"""
import cProfile
import json
import pstats
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spread_perf import SpreadPerformanceRun
from src.services.layer_cache import layer_cache
from src.services.spread import predict_spread
from src.services.spread_uncertainty import uncertainty_envelope
from src.utils.timeutils import to_utc_iso, utc_now

BENCHMARK_MODEL_NAME = "spread_perf_v1"
DEFAULT_REPEATS = 3
DEFAULT_TARGET_SECONDS = 10.0

# Reference scenario: the pilot-region demo ignition (same spot demo_api and
# the EM-015..021 anchors use), fully specified so the benchmark measures
# engine + layer reads, not input fallbacks.
REFERENCE_SCENARIO: dict[str, Any] = {
    "latitude": 38.9005,
    "longitude": 27.5005,
    "wind_speed_kmh": 25.0,
    "wind_from_deg": 225.0,
    "air_temp_c": 31.0,
    "relative_humidity_pct": 22.0,
    "fuel_moisture_pct": 12.0,
    "slope_deg": 15.0,
    "aspect_deg": 180.0,
    "fuel_model": "FM10_RedPine",
}


class _ModeSettings:
    """Delegate to a real settings object, overriding one EM-022 flag."""

    def __init__(self, base: Any, perf_enabled: bool) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_enabled", perf_enabled)

    def __getattr__(self, name: str) -> Any:
        if name == "SPREAD_PERF_ENABLED":
            return bool(object.__getattribute__(self, "_enabled"))
        return getattr(object.__getattribute__(self, "_base"), name)


def recompute_target_seconds(settings: Any) -> float:
    """Operator recomputation target the benchmark is graded against."""
    return float(
        getattr(settings, "SPREAD_RECOMPUTE_TARGET_SECONDS", DEFAULT_TARGET_SECONDS)
    )


def _run_phases(
    session: Session, mode: Any, req: dict[str, Any]
) -> tuple[float, float]:
    """(predict_ms, envelope_ms) for one reference-scenario recomputation."""
    start = perf_counter()
    predict_spread(session, mode, req)
    predict_ms = (perf_counter() - start) * 1000.0
    start = perf_counter()
    uncertainty_envelope(session, mode, req)
    return predict_ms, (perf_counter() - start) * 1000.0


def _measure_mode(
    session: Session, mode: Any, req: dict[str, Any], repeats: int
) -> dict[str, float]:
    """Best-of-``repeats`` phase timings for one optimization mode."""
    _run_phases(session, mode, req)  # warm-up: fuel beds, imports, plans
    best = _run_phases(session, mode, req)  # first measured run
    for _ in range(max(repeats, 1) - 1):
        candidate = _run_phases(session, mode, req)
        if candidate[0] + candidate[1] < best[0] + best[1]:
            best = candidate
    return {
        "predict_ms": round(best[0], 1),
        "envelope_ms": round(best[1], 1),
        "total_ms": round(best[0] + best[1], 1),
    }


def benchmark_reference_scenario(
    session: Session,
    settings: Any,
    scenario: dict[str, Any] | None = None,
    repeats: int = DEFAULT_REPEATS,
) -> dict[str, Any]:
    """Measure the reference scenario before/after the EM-022 optimizations.

    Both modes run against the same database state; the optimized pass is
    measured warm (after its own warm-up), which is exactly the situation of
    the 10-second auto-trigger recomputation loop. The result is persisted
    as a SpreadPerformanceRun and returned as its ``as_dict``.
    """
    req = dict(scenario or REFERENCE_SCENARIO)
    target = recompute_target_seconds(settings)

    layer_cache().reset()
    baseline = _measure_mode(session, _ModeSettings(settings, False), req, repeats)
    layer_cache().reset()
    optimized = _measure_mode(session, _ModeSettings(settings, True), req, repeats)
    cache_stats = layer_cache().stats()

    speedup = (
        round(baseline["total_ms"] / optimized["total_ms"], 2)
        if optimized["total_ms"] > 0
        else 1.0
    )
    row = SpreadPerformanceRun(
        run_key=f"PERF-{uuid4().hex[:10]}",
        scenario_key="reference_pilot",
        scenario_json=json.dumps(req, sort_keys=True, default=str),
        baseline_json=json.dumps({**baseline, "repeats": repeats}),
        optimized_json=json.dumps(
            {**optimized, "repeats": repeats, "cache_stats": cache_stats}
        ),
        baseline_total_ms=baseline["total_ms"],
        optimized_total_ms=optimized["total_ms"],
        speedup=speedup,
        target_seconds=target,
        target_met=optimized["total_ms"] / 1000.0 <= target,
        notes=f"model={BENCHMARK_MODEL_NAME}",
    )
    session.add(row)
    session.commit()
    return row.as_dict


def profile_reference_scenario(
    session: Session,
    settings: Any,
    scenario: dict[str, Any] | None = None,
    samples: int = 5,
    top: int = 10,
) -> dict[str, Any]:
    """cProfile the optimized reference recomputation; return hot functions."""
    req = dict(scenario or REFERENCE_SCENARIO)
    mode = _ModeSettings(settings, True)
    _run_phases(session, mode, req)  # warm-up outside the profile
    profiler = cProfile.Profile()
    start = perf_counter()
    profiler.enable()
    for _ in range(max(samples, 1)):
        predict_spread(session, mode, req)
        uncertainty_envelope(session, mode, req)
    profiler.disable()
    elapsed_ms = (perf_counter() - start) * 1000.0

    top_functions = []
    raw_stats: dict[Any, tuple[Any, int, float, float, Any]] = getattr(
        pstats.Stats(profiler), "stats", {}
    )
    for (filename, line, func_name), value in raw_stats.items():
        _cc, ncalls, tottime, cumtime, _callers = value
        top_functions.append(
            {
                "function": f"{func_name} (line {line})",
                "file": filename,
                "calls": int(ncalls),
                "tottime_ms": round(tottime * 1000.0, 2),
                "cumtime_ms": round(cumtime * 1000.0, 2),
            }
        )
    top_functions.sort(key=lambda e: e["tottime_ms"], reverse=True)
    return {
        "model": BENCHMARK_MODEL_NAME,
        "generated_at": to_utc_iso(utc_now()),
        "samples": samples,
        "total_ms": round(elapsed_ms, 1),
        "per_sample_ms": round(elapsed_ms / max(samples, 1), 1),
        "top_functions": top_functions[: max(top, 1)],
    }


def list_performance_runs(session: Session, limit: int = 20) -> list[dict[str, Any]]:
    """Stored benchmark runs, newest first."""
    rows = session.scalars(
        select(SpreadPerformanceRun)
        .order_by(SpreadPerformanceRun.created_at.desc())
        .limit(limit)
    ).all()
    return [row.as_dict for row in rows]
