"""EM-036 Isolation Forest silent-zone anomaly tests (Epic E4).

EM-036 replaces the single hand-picked z-score of EM-035/EM-043 with a *learned,
multi-feature* anomaly score: an :class:`IsolationForest` is fitted per cell over
the same baseline window on a ``[today, yesterday]`` feature vector, and the
latest reading is scored automatically. Alongside it sits the configurable
``mean - sigma * std`` quiet threshold (sigma default 3.0) - the acceptance
criterion. These tests pin the feature matrix (level + momentum, ``as_of`` never
trained on), the reproducibility of the fixed ``random_state`` estimator, the
statistical quiet-drop detection, the sigma/window clamping, the config shape and
the read-only HTTP endpoints (including the real-time ``/latest`` sweep).
"""
from datetime import date, timedelta

import pytest

from src.services.isolation_forest_anomaly import (
    ANOMALY_PERSISTENCE,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_SIGMA_MULTIPLIER,
    FEATURE_NAMES,
    IsolationForestAnomalyError,
    anomaly_config,
    anomaly_report,
    build_feature_matrix,
    interval_minutes,
    score_cell_anomaly,
    score_silent_zone_anomalies,
)
from src.services.signal_baseline import (
    DEFAULT_SOURCE_KIND,
    MAX_WINDOW_DAYS,
    MIN_WINDOW_DAYS,
    SignalSource,
    monitoring_cells,
)

_AS_OF = date(2026, 8, 15)


class _Settings:
    """Config stub; every anomaly key has a service default so this stays empty."""

    def __init__(self, **overrides):
        for key, value in overrides.items():
            setattr(self, key, value)


class _FlatSource(SignalSource):
    """Constant signal - zero variance, so no statistical quiet threshold exists."""

    kind = "flat"
    label = "Düz akış"
    synthetic = False

    def daily_signal(self, region_key: str, day: date) -> float:
        return 100.0


class _DipSource(SignalSource):
    """Stable parity-driven rhythm with one deep dip on ``dip_on``.

    The window (all days before ``as_of``) has genuine spread, so the ``mean -
    sigma * std`` quiet threshold is well defined; placing the dip on ``as_of``
    makes that reading an unambiguous statistical silent anomaly.
    """

    kind = "dip"
    label = "Çöküntülü akış"
    synthetic = False

    def __init__(self, base: float = 100.0, dip_value: float = 1.0, dip_on=None):
        self._base = base
        self._dip = dip_value
        self._dip_on = dip_on

    def daily_signal(self, region_key: str, day: date) -> float:
        if self._dip_on is not None and day == self._dip_on:
            return self._dip
        return self._base + (1.0 if day.toordinal() % 2 else -1.0)


# --------------------------------------------------------------------------- #
# Feature matrix: level + momentum, as_of scored but never trained on
# --------------------------------------------------------------------------- #
def test_feature_matrix_shapes_and_latest():
    source = _DipSource()
    window = 10
    training, latest = build_feature_matrix(source, "SB-R1C1", _AS_OF, window)
    assert len(training) == window
    # The scored row is exactly [as_of, as_of-1]; it is never in the training set.
    assert latest == [
        source.daily_signal("SB-R1C1", _AS_OF),
        source.daily_signal("SB-R1C1", _AS_OF - timedelta(days=1)),
    ]
    # Oldest training row starts window_days back (as_of itself is never trained on).
    assert training[0][0] == source.daily_signal(
        "SB-R1C1", _AS_OF - timedelta(days=window)
    )


def test_feature_matrix_rows_are_lag_pairs():
    source = _DipSource()
    training, _latest = build_feature_matrix(source, "SB-R1C1", _AS_OF, 8)
    # Oldest training row = window_days back; each row is [day, day-1].
    for offset, row in zip(range(8, 0, -1), training):
        day = _AS_OF - timedelta(days=offset)
        prev = day - timedelta(days=1)
        assert row == [
            source.daily_signal("SB-R1C1", day),
            source.daily_signal("SB-R1C1", prev),
        ]


# --------------------------------------------------------------------------- #
# Per-cell scoring
# --------------------------------------------------------------------------- #
def test_score_cell_normal_shape_and_threshold():
    cell = monitoring_cells(_Settings())[0]
    source = _DipSource()
    row = score_cell_anomaly(
        cell, source, _Settings(), _AS_OF, 20, DEFAULT_SIGMA_MULTIPLIER
    )
    assert isinstance(row["anomaly_score"], float)
    assert row["source_kind"] == "dip"
    assert row["detection_basis"] in {"both", "statistical", "isolation_forest", "none"}
    expected = round(
        float(row["baseline_mean"])
        - DEFAULT_SIGMA_MULTIPLIER * float(row["baseline_std"]),
        3,
    )
    assert row["quiet_threshold"] == expected


def test_score_cell_is_reproducible():
    cell = monitoring_cells(_Settings())[0]
    source = _DipSource()
    a = score_cell_anomaly(
        cell, source, _Settings(), _AS_OF, 20, DEFAULT_SIGMA_MULTIPLIER
    )
    b = score_cell_anomaly(
        cell, source, _Settings(), _AS_OF, 20, DEFAULT_SIGMA_MULTIPLIER
    )
    assert a["anomaly_score"] == b["anomaly_score"]
    assert a["learned_anomalous"] == b["learned_anomalous"]


def test_score_cell_quiet_drop_is_statistical():
    cell = monitoring_cells(_Settings())[0]
    # Dip exactly on as_of -> below the mean - 3*std quiet threshold.
    source = _DipSource(dip_on=_AS_OF)
    row = score_cell_anomaly(
        cell, source, _Settings(), _AS_OF, 20, DEFAULT_SIGMA_MULTIPLIER
    )
    assert row["silent_anomaly"] is True
    assert row["is_anomaly"] is True
    assert row["detection_basis"] in {"statistical", "both"}


def test_score_cell_flat_source_has_no_quiet_threshold():
    cell = monitoring_cells(_Settings())[0]
    row = score_cell_anomaly(
        cell, _FlatSource(), _Settings(), _AS_OF, 20, DEFAULT_SIGMA_MULTIPLIER
    )
    assert row["quiet_threshold"] is None
    assert row["silent_anomaly"] is False


# --------------------------------------------------------------------------- #
# sigma / window clamping
# --------------------------------------------------------------------------- #
def test_sigma_multiplier_out_of_range_raises():
    with pytest.raises(IsolationForestAnomalyError):
        anomaly_report(_Settings(), sigma_multiplier=0.5)
    with pytest.raises(IsolationForestAnomalyError):
        anomaly_report(_Settings(), sigma_multiplier=6.0)


def test_window_days_is_clamped_to_bounds():
    low = anomaly_report(_Settings(), window_days=1)
    assert low["window_days"] == MIN_WINDOW_DAYS
    high = anomaly_report(_Settings(), window_days=999)
    assert high["window_days"] == MAX_WINDOW_DAYS


def test_interval_minutes_default_and_custom():
    assert interval_minutes(_Settings()) == DEFAULT_INTERVAL_MINUTES
    assert interval_minutes(_Settings(ANOMALY_INTERVAL_MINUTES=5)) == 5


# --------------------------------------------------------------------------- #
# Report + real-time snapshot
# --------------------------------------------------------------------------- #
def test_anomaly_report_summary_and_ordering():
    report = anomaly_report(_Settings(), as_of=_AS_OF)
    assert report["panel"] == "isolation_forest_anomaly"
    assert report["persistence"] == ANOMALY_PERSISTENCE
    assert report["source_kind"] == DEFAULT_SOURCE_KIND
    scores = [c["anomaly_score"] for c in report["cells"]]
    assert scores == sorted(scores)
    total = report["cell_count"]
    assert report["anomaly_count"] == sum(1 for c in report["cells"] if c["is_anomaly"])
    assert report["anomaly_count"] <= total


def test_anomaly_report_region_filter_and_limit():
    full = anomaly_report(_Settings(), as_of=_AS_OF)
    single = anomaly_report(_Settings(), as_of=_AS_OF, region_key="SB-R1C1")
    assert single["cell_count"] == 1
    assert single["requested_region"] == "SB-R1C1"
    limited = anomaly_report(_Settings(), as_of=_AS_OF, limit=3)
    assert len(limited["cells"]) == 3
    assert limited["cell_count"] == full["cell_count"]


def test_anomaly_report_reports_features():
    report = anomaly_report(_Settings(), as_of=_AS_OF)
    assert report["features"] == list(FEATURE_NAMES)


def test_score_silent_zone_snapshot():
    snapshot = score_silent_zone_anomalies(_Settings(), as_of=_AS_OF)
    assert snapshot["panel"] == "isolation_forest_anomaly"
    assert snapshot["persistence"] == ANOMALY_PERSISTENCE
    assert snapshot["interval_minutes"] == DEFAULT_INTERVAL_MINUTES
    assert snapshot["anomaly_count"] == len(snapshot["anomaly_region_keys"])
    assert snapshot["cell_count"] == len(monitoring_cells(_Settings()))


# --------------------------------------------------------------------------- #
# Config catalogue
# --------------------------------------------------------------------------- #
def test_anomaly_config_shape():
    cfg = anomaly_config(_Settings())
    assert DEFAULT_SOURCE_KIND in cfg["sources"]["available"]
    assert cfg["sigma_multiplier"]["default"] == DEFAULT_SIGMA_MULTIPLIER
    assert cfg["sigma_multiplier"]["min"] <= cfg["sigma_multiplier"]["default"]
    assert cfg["sigma_multiplier"]["default"] <= cfg["sigma_multiplier"]["max"]
    assert cfg["model"]["algorithm"] == "IsolationForest"
    assert cfg["model"]["features"] == list(FEATURE_NAMES)
    assert cfg["realtime"]["interval_minutes"] == DEFAULT_INTERVAL_MINUTES
    assert cfg["persistence"] == ANOMALY_PERSISTENCE


def test_anomaly_config_works_without_settings():
    cfg = anomaly_config()
    assert cfg["model"]["random_state"] == 0
    assert cfg["window_days"]["min"] == MIN_WINDOW_DAYS


# --------------------------------------------------------------------------- #
# HTTP endpoints (read-only)
# --------------------------------------------------------------------------- #
def test_endpoint_config(client):
    resp = client.get("/api/v1/isolation-forest-anomaly/config")
    assert resp.status_code == 200
    assert DEFAULT_SOURCE_KIND in resp.json()["sources"]["available"]


def test_endpoint_report(client):
    resp = client.get(
        "/api/v1/isolation-forest-anomaly", params={"as_of": "2026-08-15"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "isolation_forest_anomaly"
    assert body["as_of"] == "2026-08-15"
    assert len(body["cells"]) == len(monitoring_cells(_Settings()))


def test_endpoint_latest(client):
    resp = client.get(
        "/api/v1/isolation-forest-anomaly/latest", params={"as_of": "2026-08-15"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["interval_minutes"] == DEFAULT_INTERVAL_MINUTES
    assert body["anomaly_count"] == len(body["anomaly_region_keys"])


def test_endpoint_rejects_bad_as_of(client):
    resp = client.get(
        "/api/v1/isolation-forest-anomaly", params={"as_of": "15-08-2026"}
    )
    assert resp.status_code == 400
    assert "YYYY-MM-DD" in resp.json()["detail"]["error"]


def test_endpoint_rejects_unknown_source(client):
    resp = client.get("/api/v1/isolation-forest-anomaly", params={"source": "radar"})
    assert resp.status_code == 400
    assert "bilinmeyen sinyal kaynağı" in resp.json()["detail"]["error"]


def test_endpoint_rejects_out_of_range_sigma(client):
    resp = client.get(
        "/api/v1/isolation-forest-anomaly", params={"sigma_multiplier": "9"}
    )
    assert resp.status_code == 422
