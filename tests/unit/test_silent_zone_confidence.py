"""EM-038 silent-zone confidence labelling tests (Epic E4).

EM-035 flags unusually quiet cells; EM-038 stops false alarms by labelling each
silent *candidate* low / medium / high confidence from its structural coverage
strength and the severity of the drop. These tests pin the pure classifier
(prioritising "structurally weak => low" over a dramatic drop), the read-time
report that reuses ``baseline_report`` (tiers, ordering, filters, global
summary), the config payload and the read-only HTTP endpoints.
"""
from datetime import date

import pytest

from src.services.silent_zone_confidence import (
    CONFIDENCE_ORDER,
    SILENT_ZONE_CONFIDENCE_ATTRIBUTION,
    SILENT_ZONE_CONFIDENCE_PERSISTENCE,
    SilentZoneConfidenceError,
    classify_cell,
    silent_zone_confidence_config,
    silent_zone_confidence_report,
)


class _Settings:
    """Supplies the EM-035 baseline knobs plus the EM-038 confidence thresholds."""

    def __init__(self, **over):
        # EM-035 (signal_baseline) knobs.
        self.SIGNAL_BASELINE_WINDOW_DAYS = over.get("window", 30)
        self.SIGNAL_BASELINE_SENSITIVITY_Z = over.get("sensitivity", 1.5)
        self.SIGNAL_BASELINE_CELL_ROWS = over.get("rows", 4)
        self.SIGNAL_BASELINE_CELL_COLS = over.get("cols", 5)
        self.SIGNAL_BASELINE_MAX_CELLS = over.get("max_cells", 60)
        self.SIGNAL_PILOT_MIN_LAT = over.get("min_lat", 36.0)
        self.SIGNAL_PILOT_MAX_LAT = over.get("max_lat", 39.5)
        self.SIGNAL_PILOT_MIN_LON = over.get("min_lon", 26.0)
        self.SIGNAL_PILOT_MAX_LON = over.get("max_lon", 30.0)
        # EM-038 confidence thresholds.
        self.FALSE_ALARM_MIN_COVERAGE_SIGNAL = over.get("min_coverage_signal", 100.0)
        self.FALSE_ALARM_MIN_OBSERVATIONS = over.get("min_observations", 7)
        self.FALSE_ALARM_STRONG_DROP_Z = over.get("strong_drop_z", 2.5)
        self.FALSE_ALARM_MAX_LIMIT = over.get("max_limit", 200)


def _row(
    *,
    region_key="SB-R1C1",
    candidate=True,
    observation_count=30,
    baseline_mean=150.0,
    z_score=-3.0,
):
    return {
        "region_key": region_key,
        "name": f"Hücre {region_key}",
        "candidate_silent": candidate,
        "observation_count": observation_count,
        "baseline_mean": baseline_mean,
        "z_score": z_score,
    }


# --------------------------------------------------------------------------- #
# Pure classifier
# --------------------------------------------------------------------------- #
def test_sound_coverage_sudden_drop_is_high():
    s = _Settings(min_coverage_signal=100.0, min_observations=7, strong_drop_z=2.5)
    labelled = classify_cell(_row(baseline_mean=150.0, z_score=-3.0), s)
    assert labelled["coverage_strength"] == "sound"
    assert labelled["sudden_drop"] is True
    assert labelled["confidence_code"] == "high"
    assert labelled["confidence_label"] == "Yüksek güven"


def test_sound_coverage_mild_drop_is_medium():
    s = _Settings(min_coverage_signal=100.0, strong_drop_z=2.5)
    labelled = classify_cell(_row(baseline_mean=150.0, z_score=-1.8), s)
    assert labelled["confidence_code"] == "medium"


def test_weak_coverage_is_low_false_alarm():
    s = _Settings(min_coverage_signal=100.0)
    labelled = classify_cell(_row(baseline_mean=50.0, z_score=-3.0), s)
    assert labelled["coverage_strength"] == "weak"
    assert labelled["confidence_code"] == "low"


def test_insufficient_data_is_low():
    s = _Settings(min_observations=7)
    labelled = classify_cell(
        _row(observation_count=3, baseline_mean=200.0, z_score=-3.0), s
    )
    assert labelled["coverage_strength"] == "insufficient_data"
    assert labelled["confidence_code"] == "low"


def test_weak_coverage_beats_sudden_drop():
    # Structurally weak coverage stays a false alarm even with a dramatic drop.
    s = _Settings(min_coverage_signal=100.0, strong_drop_z=2.5)
    labelled = classify_cell(_row(baseline_mean=20.0, z_score=-9.0), s)
    assert labelled["sudden_drop"] is True
    assert labelled["confidence_code"] == "low"


def test_not_candidate_has_no_confidence():
    s = _Settings()
    labelled = classify_cell(_row(candidate=False, z_score=0.5), s)
    assert labelled["confidence_code"] is None
    assert labelled["confidence_label"] == "Sessiz aday değil"


def test_classifier_populates_reasons():
    s = _Settings()
    labelled = classify_cell(_row(), s)
    assert labelled["confidence_reasons"]
    assert isinstance(labelled["confidence_reasons"], list)


# --------------------------------------------------------------------------- #
# Read-time report over the synthetic baseline (candidates forced on)
# --------------------------------------------------------------------------- #
_AS_OF = date(2026, 9, 1)


def _report(confidence=None, limit=None, **over):
    # sensitivity=-100 makes every cell a silent candidate so tiers are steered
    # purely through the EM-038 thresholds (deterministic across runs).
    settings = _Settings(sensitivity=-100.0, **over)
    return silent_zone_confidence_report(
        settings, as_of=_AS_OF, confidence=confidence, limit=limit
    )


def _cell_count(report):
    return report["summary"]["cell_count"]


def test_report_all_high_when_drop_forced():
    report = _report(min_coverage_signal=0.0, min_observations=0, strong_drop_z=-1000.0)
    total = _cell_count(report)
    assert report["summary"]["candidate_silent_count"] == total
    assert report["summary"]["high_confidence"] == total
    assert report["summary"]["low_confidence"] == 0


def test_report_all_low_when_coverage_weak():
    report = _report(min_coverage_signal=1e9)
    total = _cell_count(report)
    assert report["summary"]["low_confidence"] == total
    assert report["summary"]["weak_coverage_candidates"] == total


def test_report_all_medium_when_drop_never_qualifies():
    report = _report(min_coverage_signal=0.0, min_observations=0, strong_drop_z=1000.0)
    total = _cell_count(report)
    assert report["summary"]["medium_confidence"] == total
    assert report["summary"]["high_confidence"] == 0


def test_report_tiers_sum_to_candidates():
    report = _report(min_coverage_signal=150.0, min_observations=0, strong_drop_z=2.5)
    s = report["summary"]
    assert s["high_confidence"] + s["medium_confidence"] + s["low_confidence"] == (
        s["candidate_silent_count"]
    )


def test_report_orders_by_tier_then_z():
    report = _report(min_coverage_signal=150.0, min_observations=0, strong_drop_z=2.5)
    rank = {code: i for i, code in enumerate(CONFIDENCE_ORDER)}
    ranks = [rank[c["confidence_code"]] for c in report["candidates"]]
    assert ranks == sorted(ranks)


def test_report_confidence_filter_keeps_tier():
    report = _report(min_coverage_signal=1e9, confidence="low")
    assert report["filter"] == "low"
    assert all(c["confidence_code"] == "low" for c in report["candidates"])
    assert report["count"] == _cell_count(report)


def test_report_unknown_filter_returns_all_and_reports():
    report = _report(confidence="bogus")
    assert report["filter"] is None
    assert report["requested_filter"] == "bogus"
    assert report["count"] == _cell_count(report)


def test_report_limit_clips_but_summary_global():
    report = _report(
        min_coverage_signal=0.0, min_observations=0, strong_drop_z=-1000.0, limit=2
    )
    assert report["count"] == 2
    assert report["summary"]["candidate_silent_count"] == _cell_count(report)


def test_report_limit_below_one_raises():
    settings = _Settings(sensitivity=-100.0)
    with pytest.raises(SilentZoneConfidenceError):
        silent_zone_confidence_report(settings, as_of=_AS_OF, limit=0)


def test_report_metadata_and_synthetic_flag():
    report = _report()
    assert report["panel"] == "silent_zone_confidence"
    assert report["attribution"] == SILENT_ZONE_CONFIDENCE_ATTRIBUTION
    assert report["persistence"] == SILENT_ZONE_CONFIDENCE_PERSISTENCE
    assert report["synthetic"] is True
    assert report["thresholds"]["strong_drop_z"] == 2.5


# --------------------------------------------------------------------------- #
# Config payload
# --------------------------------------------------------------------------- #
def test_config_ladder():
    config = silent_zone_confidence_config(_Settings())
    assert [band["code"] for band in config["ladder"]] == ["high", "medium", "low"]
    assert config["persistence"] == SILENT_ZONE_CONFIDENCE_PERSISTENCE


def test_config_defaults_without_settings():
    config = silent_zone_confidence_config()
    assert config["thresholds"]["min_coverage_signal"] == 100.0
    assert config["thresholds"]["strong_drop_z"] == 2.5


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_report(client):
    resp = client.get("/api/v1/silent-zone-confidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "silent_zone_confidence"
    assert "candidates" in body and "summary" in body


def test_endpoint_confidence_filter(client):
    resp = client.get("/api/v1/silent-zone-confidence", params={"confidence": "high"})
    assert resp.status_code == 200
    assert resp.json()["filter"] == "high"


def test_endpoint_rejects_bad_limit(client):
    resp = client.get("/api/v1/silent-zone-confidence", params={"limit": 0})
    assert resp.status_code == 422


def test_endpoint_rejects_bad_as_of(client):
    resp = client.get("/api/v1/silent-zone-confidence", params={"as_of": "not-a-date"})
    assert resp.status_code == 400


def test_endpoint_config(client):
    resp = client.get("/api/v1/silent-zone-confidence/config")
    assert resp.status_code == 200
    assert len(resp.json()["ladder"]) == 3
