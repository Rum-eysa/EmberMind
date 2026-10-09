"""Scenario playback controls for the demo host (EM-107, Epic E11).

EM-105 lets the presenter *launch* a named scenario; EM-107 lets them *drive*
its on-screen timeline: play / pause and a speed multiplier so a demo advances
at a controllable pace instead of all at once.

A "frame" is one step of the scenario's own wind-history time series (built by
the EM-104 generator, curated by EM-105): a fixed ``(seed, config)`` pair always
produces the same ordered steps, so playback is fully deterministic — frame *i*
of ``kiyi-ruzgar-donusu`` is identical on every run. Nothing is persisted here:
the frames are projected at read time from the same dataset the library builds,
so there is no new table / migration.

Playback separates two clocks:

* the **scenario clock** — the simulated time a frame represents (the wind
  history ``offset_hours`` from the run's base epoch);
* the **wall clock** — how long the presenter waits between frames. One frame
  ticks every ``PLAYBACK_FRAME_INTERVAL_SECONDS`` at ``1x``; the speed factor
  divides that interval (``4x`` → a quarter of the real-time wait).

The "pause" control is a client-side concern (the schedule is a pure function of
elapsed time), so the server exposes the frame timeline, the wall-clock schedule
for a chosen speed factor, and a cursor resolver mapping elapsed wall seconds
back to the current frame.
"""
from typing import Any

from src.services.scenario_library import (
    LIBRARY,
    get_scenario,
    materialize_config,
)
from src.services.synthetic import SYNTHETIC_LABEL, build_dataset

PLAYBACK_VERSION = "EM-107 v1"
PLAYBACK_PERSISTENCE = (
    "frame'ler okuma zamanı EM-104/EM-105 verisinden türetilir (yeni tablo yok)"
)
ATTRIBUTION = (
    "Senaryo oynatma zaman çizelgesi: EmberMind senaryo kütüphanesi (EM-107) — "
    "EM-104/EM-105 sentetik verisi üzerinde, gerçek gözlem değildir"
)

# Fallbacks when the settings object does not carry a playback knob.
DEFAULT_SPEED_FACTOR = 1.0
MAX_SPEED_FACTOR = 8.0
DEFAULT_FRAME_INTERVAL_SECONDS = 2.0
SPEED_PRESETS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0)


class ScenarioPlaybackError(ValueError):
    """Raised for an out-of-range speed factor or a negative elapsed time."""


# ----------------------------------------------------------- settings ----


def _speed_factor(settings: Any) -> float:
    raw = getattr(settings, "PLAYBACK_DEFAULT_SPEED_FACTOR", DEFAULT_SPEED_FACTOR)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioPlaybackError(
            "PLAYBACK_DEFAULT_SPEED_FACTOR must be numeric"
        ) from exc
    if not 0.0 < value <= MAX_SPEED_FACTOR:
        raise ScenarioPlaybackError(
            f"PLAYBACK_DEFAULT_SPEED_FACTOR must be in (0, {MAX_SPEED_FACTOR}]"
        )
    return value


def _max_speed(settings: Any) -> float:
    raw = getattr(settings, "PLAYBACK_MAX_SPEED_FACTOR", MAX_SPEED_FACTOR)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioPlaybackError(
            "PLAYBACK_MAX_SPEED_FACTOR must be numeric"
        ) from exc
    return value if value > 0 else MAX_SPEED_FACTOR


def _frame_interval(settings: Any) -> float:
    raw = getattr(
        settings, "PLAYBACK_FRAME_INTERVAL_SECONDS", DEFAULT_FRAME_INTERVAL_SECONDS
    )
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioPlaybackError(
            "PLAYBACK_FRAME_INTERVAL_SECONDS must be numeric"
        ) from exc
    if value <= 0:
        raise ScenarioPlaybackError("PLAYBACK_FRAME_INTERVAL_SECONDS must be > 0")
    return value


def _validate_speed(speed: float, settings: Any) -> float:
    """Clamp a requested speed factor into the configured (0, max] window."""
    try:
        value = float(speed)
    except (TypeError, ValueError) as exc:
        raise ScenarioPlaybackError("speed_factor must be numeric") from exc
    if not 0.0 < value <= _max_speed(settings):
        raise ScenarioPlaybackError(
            f"speed_factor must be in (0, {_max_speed(settings)}]"
        )
    return value


# -------------------------------------------------------------- frames ----


def _dataset_frames(key: str, settings: Any) -> dict[str, Any]:
    """Build the scenario dataset and project its wind history into frames."""
    scenario = get_scenario(key)
    cfg = materialize_config(scenario, settings)
    dataset = build_dataset(int(scenario["seed"]), cfg)
    step_seconds = int(dataset["config"]["wind_history"]["step_minutes"]) * 60
    frames: list[dict[str, Any]] = []
    for index, sample in enumerate(dataset["wind_history"]):
        frames.append(
            {
                "index": index,
                "scenario_time": str(sample["t"]),
                "offset_hours": float(sample["offset_hours"]),
                "scenario_elapsed_seconds": round(
                    float(sample["offset_hours"]) * 3600.0, 3
                ),
                "wind_speed_kmh": float(sample["wind_speed_kmh"]),
                "wind_from_deg": float(sample["wind_from_deg"]),
                "air_temp_c": float(sample["air_temp_c"]),
                "relative_humidity_pct": float(sample["relative_humidity_pct"]),
            }
        )
    duration = frames[-1]["scenario_elapsed_seconds"] if frames else 0.0
    return {
        "scenario": {
            "key": str(scenario["key"]),
            "title": str(scenario["title"]),
            "archetype": str(scenario["archetype"]),
            "seed": int(scenario["seed"]),
            "scenario_tag": str(dataset["meta"]["scenario_tag"]),
            "result_hash": str(dataset["meta"]["result_hash"]),
        },
        "frames": frames,
        "frame_count": len(frames),
        "step_seconds": step_seconds,
        "scenario_duration_seconds": duration,
        "synthetic_label": SYNTHETIC_LABEL,
    }


def timeline_frames(key: str, settings: Any) -> dict[str, Any]:
    """The scenario's ordered playback frames (nothing persisted)."""
    projection = _dataset_frames(key, settings)
    projection["status"] = "ok"
    projection["attribution"] = ATTRIBUTION
    return projection


def playback_plan(
    key: str, settings: Any, speed_factor: float | None = None
) -> dict[str, Any]:
    """Wall-clock schedule for one scenario at a chosen speed factor.

    ``interval_seconds`` is the real-time wait between frames at this speed; a
    presenter plays through the schedule and may pause by simply stopping the
    advance (the cursor is a pure function of elapsed wall seconds).
    """
    speed = _validate_speed(
        _speed_factor(settings) if speed_factor is None else speed_factor, settings
    )
    interval = _frame_interval(settings)
    wall_interval = round(interval / speed, 4)
    projection = _dataset_frames(key, settings)
    schedule = [
        {
            "index": frame["index"],
            "scenario_time": frame["scenario_time"],
            "offset_hours": frame["offset_hours"],
            "wall_clock_seconds": round(frame["index"] * wall_interval, 4),
        }
        for frame in projection["frames"]
    ]
    total = projection["frame_count"]
    return {
        "status": "ok",
        "scenario": projection["scenario"],
        "speed_factor": speed,
        "frame_interval_seconds": interval,
        "interval_seconds": wall_interval,
        "frame_count": total,
        "wall_duration_seconds": round((total - 1) * wall_interval, 4)
        if total
        else 0.0,
        "scenario_duration_seconds": projection["scenario_duration_seconds"],
        "schedule": schedule,
        "controls": ["play", "pause", "speed"],
        "synthetic_label": projection["synthetic_label"],
        "attribution": ATTRIBUTION,
    }


def frame_at(
    key: str,
    settings: Any,
    elapsed_seconds: float,
    speed_factor: float | None = None,
) -> dict[str, Any]:
    """Resolve the current frame for a wall-clock elapsed time.

    The cursor is derived purely from ``elapsed_seconds`` so pause is just
    freezing that value on the client; no server state is kept.
    """
    speed = _validate_speed(
        _speed_factor(settings) if speed_factor is None else speed_factor, settings
    )
    try:
        elapsed = float(elapsed_seconds)
    except (TypeError, ValueError) as exc:
        raise ScenarioPlaybackError("elapsed_seconds must be numeric") from exc
    if elapsed < 0:
        raise ScenarioPlaybackError("elapsed_seconds must be >= 0")
    interval = _frame_interval(settings)
    wall_interval = interval / speed
    projection = _dataset_frames(key, settings)
    total = projection["frame_count"]
    if total == 0:
        raise ScenarioPlaybackError("scenario has no playback frames")
    raw_index = int(elapsed // wall_interval) if wall_interval > 0 else total - 1
    current = min(raw_index, total - 1)
    finished = elapsed >= (total - 1) * wall_interval
    frame = projection["frames"][current]
    progress = 1.0 if total == 1 else current / (total - 1)
    return {
        "status": "ok",
        "scenario": projection["scenario"],
        "speed_factor": speed,
        "elapsed_seconds": round(elapsed, 4),
        "interval_seconds": round(wall_interval, 4),
        "current_index": current,
        "frame_count": total,
        "finished": finished,
        "progress": round(progress, 4),
        "frame": frame,
        "synthetic_label": projection["synthetic_label"],
        "attribution": ATTRIBUTION,
    }


def playback_config(settings: Any) -> dict[str, Any]:
    """Read-time projection of the playback knobs (no scenario build)."""
    try:
        default_speed = _speed_factor(settings)
    except ScenarioPlaybackError:
        default_speed = DEFAULT_SPEED_FACTOR
    try:
        interval = _frame_interval(settings)
    except ScenarioPlaybackError:
        interval = DEFAULT_FRAME_INTERVAL_SECONDS
    return {
        "version": PLAYBACK_VERSION,
        "default_speed_factor": default_speed,
        "max_speed_factor": _max_speed(settings),
        "speed_presets": list(SPEED_PRESETS),
        "frame_interval_seconds": interval,
        "controls": ["play", "pause", "speed"],
        "determinism": "aynı (seed, config) → aynı adım sırası; oynatma sabit",
        "persistence": PLAYBACK_PERSISTENCE,
        "synthetic_label": SYNTHETIC_LABEL,
        "attribution": ATTRIBUTION,
        "scenarios": [
            {
                "key": str(item["key"]),
                "title": str(item["title"]),
                "archetype": str(item["archetype"]),
            }
            for item in LIBRARY
        ],
    }
