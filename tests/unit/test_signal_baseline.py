"""EM-035 region communication-signal baseline tests (Epic E4).

The service learns a rolling per-cell "normal" from a swappable signal source
and scores the latest reading against it. These tests pin the deterministic
synthetic flow, the source abstraction, the cell lattice, the baseline maths
(mean/std/z with an injected quiet day), the report ordering/filters and the
read-only HTTP endpoints.
"""
from datetime import date

import pytest

from src.services.signal_baseline import (
    BASELINE_ATTRIBUTION,
    BASELINE_PERSISTENCE,
    DEFAULT_CELL_COLS,
    DEFAULT_CELL_ROWS,
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    MIN_WINDOW_DAYS,
    SYNTHETIC_LABEL,
    SignalBaselineError,
    SignalSource,
    available_source_kinds,
    baseline_cell,
    baseline_config,
    baseline_report,
    compute_cell_baseline,
    monitoring_cells,
    resolve_source,
)


class _Settings:
    """Grid/window stub so the lattice and bounds are exercised explicitly."""

    def __init__(self, rows=None, cols=None, window=None, max_cells=None, z=None):
        if rows is not None:
            self.SIGNAL_BASELINE_CELL_ROWS = rows
        if cols is not None:
            self.SIGNAL_BASELINE_CELL_COLS = cols
        if window is not None:
            self.SIGNAL_BASELINE_WINDOW_DAYS = window
        if max_cells is not None:
            self.SIGNAL_BASELINE_MAX_CELLS = max_cells
        if z is not None:
            self.SIGNAL_BASELINE_SENSITIVITY_Z = z


class _FakeSource(SignalSource):
    """Alternating constant baseline that can dip (or spike) on ``as_of``.

    Window days alternate between ``level`` and ``level+10`` so the learned
    normal has a non-zero spread; ``current=(day, value)`` overrides exactly
    one day - used to place an artificial quiet/spike reading on ``as_of``.
    """

    kind = "fake"
    label = "Sahte kaynak"
    synthetic = False

    def __init__(self, level=100.0, current=None, vary=True):
        self._level = level
        self._current = current
        self._vary = vary

    def daily_signal(self, region_key: str, day: date) -> float:
        if self._current is not None and day == self._current[0]:
            return self._current[1]
        step = 10.0 if self._vary and day.toordinal() % 2 else 0.0
        return self._level + step


_AS_OF = date(2026, 8, 15)


# --------------------------------------------------------------------------- #
# Synthetic source determinism + abstraction
# --------------------------------------------------------------------------- #
def test_synthetic_source_is_deterministic():
    source = resolve_source(None, _Settings())
    first = source.daily_signal("SB-R1C1", _AS_OF)
    second = source.daily_signal("SB-R1C1", _AS_OF)
    assert first == second > 0


def test_synthetic_source_varies_between_cells():
    source = resolve_source("synthetic_communication", _Settings())
    values = {source.daily_signal(f"SB-R1C{c}", _AS_OF) for c in range(1, 6)}
    assert len(values) > 1


def test_synthetic_source_stays_in_plausible_band():
    # base in [80, 240), weekend factor 0.62, jitter in [0.85, 1.15]: readings
    # must remain positive and can never exceed the weekday envelope.
    source = resolve_source("synthetic_communication", _Settings())
    for day in (date(2026, 8, 14), date(2026, 8, 15), date(2026, 8, 16)):
        for col in range(1, 6):
            value = source.daily_signal(f"SB-R2C{col}", day)
            assert 0.0 < value < 240.0 * 1.15


def test_resolve_source_unknown_kind_raises():
    with pytest.raises(SignalBaselineError, match="bilinmeyen sinyal kaynağı"):
        resolve_source("uydu", _Settings())


def test_resolve_source_is_case_insensitive():
    source = resolve_source("SYNTHETIC_Communication", _Settings())
    assert source.kind == "synthetic_communication"


def test_available_kinds_only_lists_implemented_sources():
    kinds = available_source_kinds()
    assert kinds == ["synthetic_communication"]


# --------------------------------------------------------------------------- #
# Monitoring cell lattice
# --------------------------------------------------------------------------- #
def test_monitoring_cells_default_lattice():
    cells = monitoring_cells(_Settings())
    assert len(cells) == DEFAULT_CELL_ROWS * DEFAULT_CELL_COLS
    keys = {cell.region_key for cell in cells}
    assert "SB-R1C1" in keys and "SB-R4C5" in keys


def test_monitoring_cells_tile_the_pilot_bbox():
    cells = monitoring_cells(_Settings())
    assert min(cell.min_lat for cell in cells) == pytest.approx(36.0, abs=1e-4)
    assert max(cell.max_lat for cell in cells) == pytest.approx(39.5, abs=1e-4)
    assert min(cell.min_lon for cell in cells) == pytest.approx(26.0, abs=1e-4)
    assert max(cell.max_lon for cell in cells) == pytest.approx(30.0, abs=1e-4)
    for cell in cells:
        assert cell.min_lat < cell.center_lat < cell.max_lat
        assert cell.min_lon < cell.center_lon < cell.max_lon


def test_monitoring_cells_custom_grid_and_cap():
    cells = monitoring_cells(_Settings(rows=3, cols=4, max_cells=8))
    assert len(cells) == 8  # 12 cells capped to 8
    grid = monitoring_cells(_Settings(rows=0, cols=-3))
    assert len(grid) == 1  # dims clamp to >= 1


# --------------------------------------------------------------------------- #
# Window clamping
# --------------------------------------------------------------------------- #
def test_window_clamps_to_min_and_max():
    source = _FakeSource()
    cell = monitoring_cells(_Settings())[0]
    tiny = compute_cell_baseline(cell, source, _AS_OF, 2, 1.5)
    assert tiny["window_days"] == 2  # compute honours the given window
    report = baseline_report(_Settings(window=2), as_of=_AS_OF)
    assert report["window_days"] == MIN_WINDOW_DAYS
    report = baseline_report(_Settings(window=999), as_of=_AS_OF)
    assert report["window_days"] == MAX_WINDOW_DAYS
    default = baseline_report(_Settings(), as_of=_AS_OF)
    assert default["window_days"] == DEFAULT_WINDOW_DAYS


def test_baseline_window_ends_day_before_as_of():
    source = _FakeSource()
    cell = monitoring_cells(_Settings())[0]
    row = compute_cell_baseline(cell, source, _AS_OF, 30, 1.5)
    # 30 observations: as_of-30 .. as_of-1; the scored day is never inside.
    assert row["window_start"] == "2026-07-16"
    assert row["window_end"] == "2026-08-14"
    assert row["observation_count"] == 30
    assert row["as_of"] == "2026-08-15"


# --------------------------------------------------------------------------- #
# Baseline maths: quiet day flags a candidate, normal day does not
# --------------------------------------------------------------------------- #
def test_quiet_latest_day_flags_candidate_silent():
    source = _FakeSource(level=100.0, current=(_AS_OF, 10.0))
    cell = monitoring_cells(_Settings())[0]
    row = compute_cell_baseline(cell, source, _AS_OF, 20, 1.5)
    assert row["baseline_mean"] == pytest.approx(105.0)
    assert row["baseline_std"] > 0
    assert row["latest_value"] == 10.0
    assert row["z_score"] < -1.5
    assert row["candidate_silent"] is True
    assert row["silence_ratio"] == pytest.approx(10.0 / 105.0, abs=0.001)
    assert row["synthetic"] is False
    assert "synthetic_label" not in row


def test_flat_series_never_flags_silent():
    # vary=False: zero-spread window -> std 0 -> z pinned to 0.0, no candidate.
    source = _FakeSource(level=100.0, current=(_AS_OF, 100.0), vary=False)
    cell = monitoring_cells(_Settings())[0]
    row = compute_cell_baseline(cell, source, _AS_OF, 30, 1.5)
    assert row["baseline_std"] == 0.0
    assert row["z_score"] == 0.0
    assert row["candidate_silent"] is False


def test_spike_is_not_silence():
    source = _FakeSource(level=100.0, current=(_AS_OF, 400.0))
    cell = monitoring_cells(_Settings())[0]
    row = compute_cell_baseline(cell, source, _AS_OF, 30, 1.5)
    assert row["z_score"] > 0
    assert row["candidate_silent"] is False


def test_sensitivity_threshold_is_configurable():
    source = _FakeSource(level=100.0, current=(_AS_OF, 80.0))
    cell = monitoring_cells(_Settings())[0]
    row = compute_cell_baseline(cell, source, _AS_OF, 20, 0.2)
    # z ~= -5.7 with one dip day inside the window; a lax threshold agrees.
    assert row["z_score"] < -0.2
    assert row["candidate_silent"] is True


def test_compute_payload_carries_stats_and_cell_geometry():
    source = _FakeSource()
    cell = monitoring_cells(_Settings())[0]
    row = compute_cell_baseline(cell, source, _AS_OF, 30, 1.5)
    assert row["region_key"] == cell.region_key
    assert row["min_lat"] == cell.min_lat
    assert row["baseline_median"] == pytest.approx(105.0)
    assert row["baseline_min"] == 100.0 and row["baseline_max"] == 110.0
    assert row["source_kind"] == "fake"


# --------------------------------------------------------------------------- #
# Report: ordering, filters, counts, synthetic labelling
# --------------------------------------------------------------------------- #
def test_report_lists_all_cells_with_synthetic_labels():
    report = baseline_report(_Settings(), as_of=_AS_OF)
    assert report["panel"] == "signal_baseline"
    assert report["persistence"] == BASELINE_PERSISTENCE
    assert report["attribution"] == BASELINE_ATTRIBUTION
    assert report["cell_count"] == DEFAULT_CELL_ROWS * DEFAULT_CELL_COLS
    assert report["synthetic"] is True
    assert report["synthetic_label"] == SYNTHETIC_LABEL
    assert all(row["synthetic"] for row in report["cells"])


def test_report_orders_quietest_first():
    report = baseline_report(_Settings(), as_of=_AS_OF)
    zs = [(row["candidate_silent"], row["z_score"]) for row in report["cells"]]
    assert zs == sorted(zs, key=lambda t: (not t[0], t[1]))


def test_report_region_filter_narrows_without_error():
    report = baseline_report(_Settings(), as_of=_AS_OF, region_key="SB-R2C3")
    assert report["cell_count"] == 1
    assert report["cells"][0]["region_key"] == "SB-R2C3"
    missing = baseline_report(_Settings(), as_of=_AS_OF, region_key="YOK")
    assert missing["cell_count"] == 0
    assert missing["cells"] == []


def test_report_limit_pages_cells():
    report = baseline_report(_Settings(), as_of=_AS_OF, limit=5)
    assert len(report["cells"]) == 5
    assert report["cell_count"] == DEFAULT_CELL_ROWS * DEFAULT_CELL_COLS


def test_baseline_cell_single_lookup():
    row = baseline_cell(_Settings(), "SB-R1C2", as_of=_AS_OF)
    assert row["region_key"] == "SB-R1C2"


def test_baseline_cell_unknown_key_raises():
    with pytest.raises(SignalBaselineError, match="bilinmeyen hücre"):
        baseline_cell(_Settings(), "YOK-R9C9", as_of=_AS_OF)


# --------------------------------------------------------------------------- #
# Config catalogue
# --------------------------------------------------------------------------- #
def test_config_catalogues_sources_and_bounds():
    cfg = baseline_config()
    assert cfg["sources"]["available"] == ["synthetic_communication"]
    assert "traffic_density" in cfg["sources"]["planned"]
    assert cfg["sources"]["default"] == "synthetic_communication"
    assert cfg["window_days"] == {
        "default": DEFAULT_WINDOW_DAYS,
        "min": MIN_WINDOW_DAYS,
        "max": MAX_WINDOW_DAYS,
    }
    assert cfg["grid"]["cell_count"] == DEFAULT_CELL_ROWS * DEFAULT_CELL_COLS
    assert cfg["attribution"] == BASELINE_ATTRIBUTION
    assert cfg["persistence"] == "none"


# --------------------------------------------------------------------------- #
# HTTP endpoints (read-only)
# --------------------------------------------------------------------------- #
def test_endpoint_config(client):
    resp = client.get("/api/v1/signal-baseline/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"]["available"] == ["synthetic_communication"]


def test_endpoint_report(client):
    resp = client.get("/api/v1/signal-baseline", params={"as_of": "2026-08-15"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "signal_baseline"
    assert body["as_of"] == "2026-08-15"
    assert len(body["cells"]) == DEFAULT_CELL_ROWS * DEFAULT_CELL_COLS


def test_endpoint_rejects_bad_as_of(client):
    resp = client.get("/api/v1/signal-baseline", params={"as_of": "15-08-2026"})
    assert resp.status_code == 400
    assert "YYYY-MM-DD" in resp.json()["detail"]["error"]


def test_endpoint_rejects_unknown_source(client):
    resp = client.get("/api/v1/signal-baseline", params={"source": "radar"})
    assert resp.status_code == 400
    assert "bilinmeyen sinyal kaynağı" in resp.json()["detail"]["error"]


def test_endpoint_single_cell_ok_and_missing(client):
    ok = client.get("/api/v1/signal-baseline/cells/SB-R1C1")
    assert ok.status_code == 200
    assert ok.json()["region_key"] == "SB-R1C1"
    missing = client.get("/api/v1/signal-baseline/cells/YOK-R9C9")
    assert missing.status_code == 404
