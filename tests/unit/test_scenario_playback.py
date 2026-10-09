"""EM-107 scenario playback control tests.

Covers the frame timeline derived from a scenario's own wind history
(ordering, determinism, scenario-clock offsets), the wall-clock playback
schedule at a chosen speed factor (interval division, monotonic schedule), the
elapsed-time cursor resolver (play / pause semantics, clamping, progress), the
speed-factor validation window, the read-time playback config and the HTTP
endpoints. Nothing here persists — playback is projected from EM-104/EM-105.
"""
import pytest

from src.services.scenario_library import LIBRARY_KEYS, ScenarioLibraryError
from src.services.scenario_playback import (
    ATTRIBUTION,
    PLAYBACK_VERSION,
    ScenarioPlaybackError,
    frame_at,
    playback_config,
    playback_plan,
    timeline_frames,
)
from src.services.synthetic import SYNTHETIC_LABEL


class _Settings:
    """Deterministic playback knobs (fixed interval / speed window)."""

    def __init__(  # type: ignore[no-untyped-def]
        self,
        *,
        border_lon=28.85,
        default_speed=1.0,
        max_speed=8.0,
        interval=2.0,
    ):
        self.SCENARIO_BORDER_LON = border_lon
        self.PLAYBACK_DEFAULT_SPEED_FACTOR = default_speed
        self.PLAYBACK_MAX_SPEED_FACTOR = max_speed
        self.PLAYBACK_FRAME_INTERVAL_SECONDS = interval


# --------------------------------------------------------------- frames ----


def test_frames_are_ordered_and_labelled():
    result = timeline_frames("kiyi-ruzgar-donusu", _Settings())
    frames = result["frames"]
    assert result["frame_count"] == len(frames) > 1
    assert [f["index"] for f in frames] == list(range(len(frames)))
    offsets = [f["offset_hours"] for f in frames]
    assert offsets == sorted(offsets)
    for frame in frames:
        assert frame["scenario_elapsed_seconds"] == round(
            frame["offset_hours"] * 3600.0, 3
        )
    assert result["synthetic_label"] == SYNTHETIC_LABEL
    assert result["attribution"] == ATTRIBUTION


def test_frames_are_deterministic():
    a = timeline_frames("kiyi-ruzgar-donusu", _Settings())
    b = timeline_frames("kiyi-ruzgar-donusu", _Settings())
    assert a["scenario"]["scenario_tag"] == b["scenario"]["scenario_tag"]
    assert a["scenario"]["result_hash"] == b["scenario"]["result_hash"]
    assert a["frames"] == b["frames"]


def test_frames_step_seconds_matches_config():
    result = timeline_frames("kiyi-ruzgar-donusu", _Settings())
    # Library wind history is hourly (60 min) -> 3600 s between scenario frames.
    assert result["step_seconds"] == 3600
    assert (
        result["scenario_duration_seconds"]
        == result["frames"][-1]["scenario_elapsed_seconds"]
    )


def test_frames_unknown_key_raises():
    with pytest.raises(ScenarioLibraryError, match="unknown scenario key"):
        timeline_frames("yok-boyle-senaryo", _Settings())


# ---------------------------------------------------------------- plan ----


def test_plan_uses_default_speed_from_settings():
    plan = playback_plan("kiyi-ruzgar-donusu", _Settings(interval=2.0))
    assert plan["speed_factor"] == 1.0
    assert plan["frame_interval_seconds"] == 2.0
    assert plan["interval_seconds"] == 2.0  # 2.0 / 1.0
    assert plan["controls"] == ["play", "pause", "speed"]


def test_speed_factor_divides_the_wall_interval():
    slow = playback_plan("kiyi-ruzgar-donusu", _Settings(), speed_factor=2.0)
    fast = playback_plan("kiyi-ruzgar-donusu", _Settings(), speed_factor=4.0)
    assert slow["interval_seconds"] == 1.0
    assert fast["interval_seconds"] == 0.5
    total = fast["frame_count"]
    assert fast["wall_duration_seconds"] == round((total - 1) * 0.5, 4)


def test_plan_schedule_is_monotonic_wall_clock():
    plan = playback_plan(
        "kiyi-ruzgar-donusu", _Settings(interval=2.0), speed_factor=1.0
    )
    wall = [s["wall_clock_seconds"] for s in plan["schedule"]]
    assert wall == sorted(wall)
    assert wall[0] == 0.0
    assert len(wall) == plan["frame_count"]


@pytest.mark.parametrize("bad", [0.0, -1.0, 9.0, "abc"])
def test_plan_rejects_out_of_range_speed(bad):
    with pytest.raises(ScenarioPlaybackError):
        playback_plan("kiyi-ruzgar-donusu", _Settings(), speed_factor=bad)


# ------------------------------------------------------------- cursor ----


def test_cursor_starts_at_first_frame():
    cur = frame_at("kiyi-ruzgar-donusu", _Settings(interval=2.0), 0.0)
    assert cur["current_index"] == 0
    assert cur["finished"] is False
    assert cur["progress"] == 0.0


def test_cursor_advances_with_elapsed_time():
    # wall interval 2.0 s at 1x -> 5.0 s lands on frame index 2.
    cur = frame_at("kiyi-ruzgar-donusu", _Settings(interval=2.0), 5.0, speed_factor=1.0)
    assert cur["current_index"] == 2
    assert cur["frame"]["index"] == 2


def test_cursor_speed_factor_accelerates_cursor():
    # 2.0 s elapsed at 4x (interval 0.5 s) -> index 4.
    cur = frame_at("kiyi-ruzgar-donusu", _Settings(interval=2.0), 2.0, speed_factor=4.0)
    assert cur["current_index"] == 4
    assert cur["interval_seconds"] == 0.5


def test_cursor_clamps_and_marks_finished():
    plan = playback_plan(
        "kiyi-ruzgar-donusu", _Settings(interval=2.0), speed_factor=1.0
    )
    tail = plan["wall_duration_seconds"] + 100.0
    cur = frame_at("kiyi-ruzgar-donusu", _Settings(interval=2.0), tail)
    assert cur["current_index"] == plan["frame_count"] - 1
    assert cur["finished"] is True
    assert cur["progress"] == 1.0


def test_cursor_rejects_negative_elapsed():
    with pytest.raises(ScenarioPlaybackError, match="elapsed_seconds"):
        frame_at("kiyi-ruzgar-donusu", _Settings(), -1.0)


# -------------------------------------------------------------- config ----


def test_config_exposes_playback_knobs_and_scenarios():
    cfg = playback_config(_Settings())
    assert cfg["version"] == PLAYBACK_VERSION
    assert cfg["default_speed_factor"] == 1.0
    assert cfg["max_speed_factor"] == 8.0
    assert cfg["controls"] == ["play", "pause", "speed"]
    assert cfg["speed_presets"] == [0.5, 1.0, 2.0, 4.0, 8.0]
    assert {s["key"] for s in cfg["scenarios"]} == set(LIBRARY_KEYS)
    assert cfg["synthetic_label"] == SYNTHETIC_LABEL


def test_config_falls_back_on_invalid_interval():
    cfg = playback_config(_Settings(interval=0.0))
    # invalid interval must not raise; config reports the safe default.
    assert cfg["frame_interval_seconds"] == 2.0


# ------------------------------------------------------------------ api ----


def test_http_playback_config(client):
    response = client.get("/api/v1/scenarios/playback/config")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == PLAYBACK_VERSION
    assert body["controls"] == ["play", "pause", "speed"]


def test_http_frames_and_label(client):
    ok = client.get("/api/v1/scenarios/playback/kirsal-sessiz-bolge/frames")
    assert ok.status_code == 200
    assert ok.json()["frame_count"] > 1
    assert ok.json()["synthetic_label"] == SYNTHETIC_LABEL
    missing = client.get("/api/v1/scenarios/playback/yok-boyle/frames")
    assert missing.status_code == 404


def test_http_plan_and_cursor(client):
    plan = client.get("/api/v1/scenarios/playback/sinir-bolgesi/plan?speed_factor=4.0")
    assert plan.status_code == 200
    assert plan.json()["speed_factor"] == 4.0
    cursor = client.get(
        "/api/v1/scenarios/playback/sinir-bolgesi/cursor?elapsed_seconds=2.0"
        "&speed_factor=4.0"
    )
    assert cursor.status_code == 200
    assert cursor.json()["current_index"] == 4


def test_http_bad_speed_returns_422(client):
    # Query validation (gt=0.0) rejects speed_factor=0 before the handler runs.
    bad = client.get(
        "/api/v1/scenarios/playback/kiyi-ruzgar-donusu/plan?speed_factor=0"
    )
    assert bad.status_code == 422


def test_openapi_publishes_playback_paths(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/v1/scenarios/playback/config" in paths
    assert "/api/v1/scenarios/playback/{key}/frames" in paths
