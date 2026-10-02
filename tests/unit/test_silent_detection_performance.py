"""EM-042 silent-region detection performance tests (Epic E4).

There is no labelled catalogue of real outages in the pilot, so EM-042
manufactures its own ground truth: a deterministic synthetic scenario injects a
set of silent episodes onto the EM-035 signal flow and re-scores the *actual*
detector day by day, producing TPR / FPR / precision / F1 and an alert-delay
summary. These tests pin the pure confusion math (undefined rates stay ``None``,
never a misleading ``0.0``), the deterministic scenario builder, the full
read-time evaluation under forced detectors (always/never flag), the config
payload and the read-only HTTP endpoints - every result always labelled as a
synthetic scenario.
"""
from datetime import date

import pytest

from src.services.signal_baseline import monitoring_cells
from src.services.silent_detection_performance import (
    PERFORMANCE_ATTRIBUTION,
    PERFORMANCE_PERSISTENCE,
    SCENARIO_LABEL,
    SilentDetectionPerformanceError,
    SilentEpisode,
    build_scenario,
    confusion_metrics,
    evaluate_detection,
    performance_config,
)

_AS_OF = date(2026, 9, 1)


class _Settings:
    """Supplies the EM-035 baseline grid/pilot plus the EM-042 scenario knobs."""

    def __init__(self, **over):
        # EM-035 (signal_baseline) grid + pilot.
        self.SIGNAL_BASELINE_CELL_ROWS = over.get("rows", 3)
        self.SIGNAL_BASELINE_CELL_COLS = over.get("cols", 3)
        self.SIGNAL_BASELINE_MAX_CELLS = over.get("max_cells", 60)
        self.SIGNAL_PILOT_MIN_LAT = over.get("min_lat", 36.0)
        self.SIGNAL_PILOT_MAX_LAT = over.get("max_lat", 39.5)
        self.SIGNAL_PILOT_MIN_LON = over.get("min_lon", 26.0)
        self.SIGNAL_PILOT_MAX_LON = over.get("max_lon", 30.0)
        # EM-042 scenario knobs.
        self.SILENT_DETECTION_HORIZON_DAYS = over.get("horizon", 30)
        self.SILENT_DETECTION_BASELINE_WINDOW_DAYS = over.get("window", 14)
        self.SILENT_DETECTION_SENSITIVITY_Z = over.get("sensitivity", 1.5)
        self.SILENT_DETECTION_ONSET_RATE = over.get("onset_rate", 0.4)
        self.SILENT_DETECTION_OUTAGE_DAYS = over.get("outage_days", 3)
        self.SILENT_DETECTION_OUTAGE_DEPTH = over.get("outage_depth", 0.05)
        self.SILENT_DETECTION_MAX_LATENCY_DAYS = over.get("max_latency", 5)


def _cells(settings=None):
    return monitoring_cells(settings or _Settings())


# --------------------------------------------------------------------------- #
# Pure confusion metrics
# --------------------------------------------------------------------------- #
def test_confusion_perfect_detector():
    m = confusion_metrics(
        true_positive=10, false_positive=0, false_negative=0, true_negative=10
    )
    assert m["tpr"] == 1.0
    assert m["fpr"] == 0.0
    assert m["precision"] == 1.0
    assert m["f1"] == 1.0
    assert m["accuracy"] == 1.0


def test_confusion_all_wrong():
    m = confusion_metrics(
        true_positive=0, false_positive=5, false_negative=5, true_negative=0
    )
    assert m["tpr"] == 0.0
    assert m["fpr"] == 1.0
    assert m["precision"] == 0.0
    assert m["f1"] == 0.0


def test_confusion_no_positives_is_none():
    # An empty positive class must not report a 0.0 TPR (undefined, not zero).
    m = confusion_metrics(
        true_positive=0, false_positive=2, false_negative=0, true_negative=8
    )
    assert m["tpr"] is None
    assert m["recall"] is None
    assert m["fpr"] == 0.2


def test_confusion_no_negatives_is_none():
    m = confusion_metrics(
        true_positive=3, false_positive=0, false_negative=1, true_negative=0
    )
    assert m["fpr"] is None
    assert m["tpr"] == 0.75


def test_confusion_counts_sum_to_total():
    m = confusion_metrics(
        true_positive=3, false_positive=2, false_negative=4, true_negative=5
    )
    assert m["evaluated_cell_days"] == 14
    assert m["positive_cell_days"] == 7
    assert m["negative_cell_days"] == 7
    assert (
        m["true_positive"]
        + m["false_positive"]
        + m["false_negative"]
        + m["true_negative"]
        == m["evaluated_cell_days"]
    )


# --------------------------------------------------------------------------- #
# Episode value object
# --------------------------------------------------------------------------- #
def test_episode_covers_window_half_open():
    ep = SilentEpisode(region_key="SB-R1C1", onset=date(2026, 9, 1), duration_days=3)
    assert ep.covers(date(2026, 9, 1))
    assert ep.covers(date(2026, 9, 3))
    assert not ep.covers(date(2026, 9, 4))
    assert not ep.covers(date(2026, 8, 31))


# --------------------------------------------------------------------------- #
# Deterministic scenario builder
# --------------------------------------------------------------------------- #
def test_scenario_is_deterministic():
    cells = _cells()
    a = build_scenario(
        cells, reference=_AS_OF, horizon_days=30, onset_rate=0.5, outage_days=3
    )
    b = build_scenario(
        cells, reference=_AS_OF, horizon_days=30, onset_rate=0.5, outage_days=3
    )
    assert [e.region_key for e in a.episodes] == [e.region_key for e in b.episodes]


def test_scenario_zero_onset_rate_has_no_episodes():
    scenario = build_scenario(
        _cells(), reference=_AS_OF, horizon_days=30, onset_rate=0.0, outage_days=3
    )
    assert scenario.episodes == ()


def test_scenario_full_onset_rate_flags_every_cell():
    cells = _cells()
    scenario = build_scenario(
        cells, reference=_AS_OF, horizon_days=30, onset_rate=1.0, outage_days=3
    )
    assert len(scenario.episodes) == len(cells)
    keys = {e.region_key for e in scenario.episodes}
    assert keys == {str(c.region_key) for c in cells}


def test_scenario_eval_days_span_horizon_ending_at_reference():
    scenario = build_scenario(
        _cells(), reference=_AS_OF, horizon_days=10, onset_rate=0.5, outage_days=3
    )
    assert len(scenario.eval_days) == 10
    assert scenario.eval_days[-1] == _AS_OF


# --------------------------------------------------------------------------- #
# Full read-time evaluation
# --------------------------------------------------------------------------- #
def test_evaluate_default_metrics_are_rates_or_none():
    report = evaluate_detection(_Settings(), reference=_AS_OF)
    for key in ("tpr", "fpr", "precision", "f1", "accuracy"):
        value = report[key]
        assert value is None or 0.0 <= value <= 1.0


def test_evaluate_counts_sum_to_cell_days():
    settings = _Settings(rows=3, cols=3)
    report = evaluate_detection(settings, reference=_AS_OF, horizon_days=12)
    c = report["confusion"]
    total = (
        c["true_positive"]
        + c["false_positive"]
        + c["false_negative"]
        + c["true_negative"]
    )
    assert total == report["cell_count"] * 12


def test_evaluate_always_flag_detector_is_perfect_recall_all_false_alarm():
    # sensitivity_z <= 0 with a tiny threshold flags every cell-day (z <= -sens
    # is trivially satisfied), so every positive is caught (TPR=1) and every
    # negative becomes a false alarm (FPR=1).
    report = evaluate_detection(
        _Settings(), reference=_AS_OF, onset_rate=1.0, sensitivity_z=-100.0
    )
    assert report["tpr"] == 1.0
    assert report["fpr"] == 1.0
    assert report["confusion"]["false_negative"] == 0
    assert report["alert_delay"]["undetected_episodes"] == 0


def test_evaluate_never_flag_detector_misses_everything():
    report = evaluate_detection(
        _Settings(), reference=_AS_OF, onset_rate=1.0, sensitivity_z=1000.0
    )
    assert report["tpr"] == 0.0
    assert report["fpr"] == 0.0
    assert report["confusion"]["true_positive"] == 0
    delay = report["alert_delay"]
    assert delay["mean_days"] is None
    assert delay["undetected_episodes"] == report["episode_count"]


def test_evaluate_zero_onset_rate_leaves_tpr_undefined():
    report = evaluate_detection(
        _Settings(), reference=_AS_OF, onset_rate=0.0, sensitivity_z=1000.0
    )
    assert report["episode_count"] == 0
    assert report["tpr"] is None


def test_evaluate_detected_episodes_have_alert_delay_defined():
    report = evaluate_detection(
        _Settings(), reference=_AS_OF, onset_rate=1.0, sensitivity_z=-100.0
    )
    episodes = report["episodes"]
    assert episodes
    for ep in episodes:
        assert ep["detected"] is True
        assert ep["alert_delay_days"] == 0
        assert ep["first_flag_day"] == ep["onset"]


def test_evaluate_is_labelled_synthetic_scenario():
    report = evaluate_detection(_Settings(), reference=_AS_OF)
    assert report["panel"] == "silent_detection_performance"
    assert report["persistence"] == PERFORMANCE_PERSISTENCE
    assert report["attribution"] == PERFORMANCE_ATTRIBUTION
    assert report["synthetic"] is True
    assert report["scenario_label"] == SCENARIO_LABEL


def test_evaluate_rejects_horizon_below_minimum():
    with pytest.raises(SilentDetectionPerformanceError):
        evaluate_detection(_Settings(), reference=_AS_OF, horizon_days=2)


def test_evaluate_rejects_window_below_minimum():
    with pytest.raises(SilentDetectionPerformanceError):
        evaluate_detection(_Settings(), reference=_AS_OF, baseline_window_days=1)


# --------------------------------------------------------------------------- #
# Config payload
# --------------------------------------------------------------------------- #
def test_config_reports_bounds_and_metrics():
    config = performance_config(_Settings())
    assert config["horizon_days"]["min"] == 3
    assert config["baseline_window_days"]["default"] == 14
    assert "tpr" in config["metrics"] and "fpr" in config["metrics"]
    assert config["persistence"] == PERFORMANCE_PERSISTENCE


def test_config_defaults_without_settings():
    config = performance_config()
    assert config["onset_rate"] == 0.4
    assert config["outage_depth"] == 0.05
    assert config["sensitivity_z"] == 1.5


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_report(client):
    resp = client.get("/api/v1/silent-detection-performance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "silent_detection_performance"
    assert "confusion" in body and "alert_delay" in body and "episodes" in body


def test_endpoint_horizon_override(client):
    resp = client.get(
        "/api/v1/silent-detection-performance", params={"horizon_days": 10}
    )
    assert resp.status_code == 200
    assert resp.json()["horizon_days"] == 10


def test_endpoint_rejects_bad_horizon(client):
    resp = client.get(
        "/api/v1/silent-detection-performance", params={"horizon_days": 0}
    )
    assert resp.status_code == 422


def test_endpoint_rejects_bad_onset_rate(client):
    resp = client.get(
        "/api/v1/silent-detection-performance", params={"onset_rate": 2.0}
    )
    assert resp.status_code == 422


def test_endpoint_rejects_bad_as_of(client):
    resp = client.get(
        "/api/v1/silent-detection-performance", params={"as_of": "not-a-date"}
    )
    assert resp.status_code == 400


def test_endpoint_config(client):
    resp = client.get("/api/v1/silent-detection-performance/config")
    assert resp.status_code == 200
    assert resp.json()["persistence"] == PERFORMANCE_PERSISTENCE
