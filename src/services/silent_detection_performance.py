"""Silent-region detection performance measurement (EM-042, Epic E4).

A data scientist wants to *prove* the accuracy claims of silent-region
detection, not just run it (EM-042 acceptance: "sentetik senaryo setinde TPR,
FPR ve uyarı gecikmesi hesaplanır; sonuç 'sentetik senaryo' etiketiyle
raporlanır"). EM-035 learns each cell's pre-fire baseline and flags an
unusually quiet day (``candidate_silent``); EM-038 turns that into a
false-alarm confidence label. None of that says *how good* the detector is.

This service measures it. Because there is no labelled catalogue of real
outages in the pilot, the ground truth is manufactured deliberately: a
deterministic **synthetic scenario** injects a set of known silent episodes
(a cell's report signal drops to a fraction of normal for a few days) onto
the same synthetic communication flow EM-035 scores. The *actual* EM-035
detector is then replayed day by day over a horizon, and every cell-day is
compared to the injected truth, yielding the confusion matrix and the
headline metrics:

- **TPR** (recall) - of the truly-silent cell-days, how many were flagged;
- **FPR** - of the normal cell-days, how many were falsely flagged;
- **precision / F1** - the usual companions, so the number is interpretable;
- **alert delay** - days between an episode's onset and the first flag on it
  (``0`` means caught on the onset day; episodes never caught in the latency
  window are reported separately, never silently dropped).

Everything is a *synthetic scenario*: the result is always labelled so no one
mistakes a measured rate for a claim about production accuracy. Nothing is
learned from a database and nothing is written - the scenario is regenerated
and re-scored on each read, so ``persistence`` is ``none``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from src.services.signal_baseline import (
    SYNTHETIC_LABEL,
    SignalSource,
    SyntheticCommunicationSource,
    compute_cell_baseline,
    monitoring_cells,
    resolve_source,
)

# Scenario geometry (all overridable through settings).
DEFAULT_HORIZON_DAYS = 30
DEFAULT_BASELINE_WINDOW_DAYS = 14
DEFAULT_SENSITIVITY_Z = 1.5
DEFAULT_ONSET_RATE = 0.4
DEFAULT_OUTAGE_DAYS = 3
DEFAULT_OUTAGE_DEPTH = 0.05
DEFAULT_MAX_LATENCY_DAYS = 5
MIN_HORIZON_DAYS = 3
MAX_HORIZON_DAYS = 120
MIN_BASELINE_WINDOW_DAYS = 5
MAX_BASELINE_WINDOW_DAYS = 60

PERFORMANCE_ATTRIBUTION = (
    "EM-042: sessiz bölge tespitinin sentetik senaryo setinde ölçülen "
    "performansı (TPR/FPR/kesginlik/F1 + uyarı gecikmesi); gerçek "
    "etiketli kataloq yok, ground-truth senaryoya deterministik enjekte "
    "edilir - oranlar üretim doğruluk iddiası değildir"
)
PERFORMANCE_PERSISTENCE = "none"
SCENARIO_LABEL = (
    "SENTETİK SENARYO - enjekte edilmiş ground-truth, gerçek doğruluk ölçümü değil"
)
SCENARIO_SOURCE_KIND = "synthetic_outage_scenario"


class SilentDetectionPerformanceError(ValueError):
    """Raised for an invalid performance request (bad horizon/window)."""


def _det_unit(token: str) -> float:
    """Deterministic pseudo-uniform value in ``[0, 1)`` (PYTHONHASHSEED-safe)."""
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


@dataclass(frozen=True)
class SilentEpisode:
    """One injected ground-truth outage: a cell is truly silent over a window."""

    region_key: str
    onset: date
    duration_days: int

    def covers(self, day: date) -> bool:
        """Half-open membership test: ``onset <= day < onset + duration``."""
        return self.onset <= day < self.onset + timedelta(days=self.duration_days)

    def as_dict(self) -> dict[str, Any]:
        """Serialise the episode plus its attached evaluation results."""
        return {
            "region_key": self.region_key,
            "onset": self.onset.isoformat(),
            "duration_days": self.duration_days,
            "first_flag_day": self.first_flag_day.isoformat()
            if self.first_flag_day is not None
            else None,
            "detected": self.detected,
            "alert_delay_days": self.alert_delay_days,
            "positive_cell_days": self.positive_cell_days,
        }

    # Mutable evaluation scratch (episodes are frozen value objects; results
    # are attached with object.__setattr__ so the frozen contract holds).
    first_flag_day: Optional[date] = None
    detected: bool = False
    alert_delay_days: Optional[int] = None
    positive_cell_days: int = 0


@dataclass(frozen=True)
class ScenarioSpec:
    """A fully deterministic synthetic scenario: episodes + evaluation days."""

    episodes: tuple[SilentEpisode, ...]
    eval_days: tuple[date, ...]

    def truth(self, region_key: str, day: date) -> bool:
        """Whether the region sits inside an injected silent episode."""
        return any(
            episode.region_key == region_key and episode.covers(day)
            for episode in self.episodes
        )


class OutageInjectedSource(SignalSource):
    """Base signal with injected silent episodes layered on top.

    Outside any episode the cell behaves exactly like ``base``; during an
    episode the reading collapses to ``depth`` of normal, which is what the
    EM-035 detector is expected to catch.
    """

    kind = SCENARIO_SOURCE_KIND
    label = "Sentetik sessiz bölge senaryosu"
    synthetic = True

    def __init__(
        self, base: SignalSource, episodes: tuple[SilentEpisode, ...], depth: float
    ) -> None:
        self._base = base
        self._episodes = episodes
        self._depth = depth

    def daily_signal(self, region_key: str, day: date) -> float:
        """Collapse the base reading to ``depth`` while an episode is active."""
        value = self._base.daily_signal(region_key, day)
        for episode in self._episodes:
            if episode.region_key == region_key and episode.covers(day):
                return round(value * self._depth, 3)
        return value


def _horizon_days(settings: Any, override: Optional[int] = None) -> int:
    raw = (
        override
        if override is not None
        else getattr(settings, "SILENT_DETECTION_HORIZON_DAYS", DEFAULT_HORIZON_DAYS)
    )
    value = int(raw)
    if value < MIN_HORIZON_DAYS or value > MAX_HORIZON_DAYS:
        raise SilentDetectionPerformanceError(
            f"ufuk {MIN_HORIZON_DAYS}-{MAX_HORIZON_DAYS} gün arasında olmalı"
        )
    return value


def _baseline_window(settings: Any, override: Optional[int] = None) -> int:
    raw = (
        override
        if override is not None
        else getattr(
            settings,
            "SILENT_DETECTION_BASELINE_WINDOW_DAYS",
            DEFAULT_BASELINE_WINDOW_DAYS,
        )
    )
    value = int(raw)
    if value < MIN_BASELINE_WINDOW_DAYS or value > MAX_BASELINE_WINDOW_DAYS:
        raise SilentDetectionPerformanceError(
            f"baz penceresi {MIN_BASELINE_WINDOW_DAYS}-{MAX_BASELINE_WINDOW_DAYS} "
            "gün arasında olmalı"
        )
    return value


def _sensitivity_z(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_DETECTION_SENSITIVITY_Z", DEFAULT_SENSITIVITY_Z)
    )


def _onset_rate(settings: Any) -> float:
    rate = float(getattr(settings, "SILENT_DETECTION_ONSET_RATE", DEFAULT_ONSET_RATE))
    return max(0.0, min(rate, 1.0))


def _outage_days(settings: Any) -> int:
    return int(getattr(settings, "SILENT_DETECTION_OUTAGE_DAYS", DEFAULT_OUTAGE_DAYS))


def _outage_depth(settings: Any) -> float:
    return float(
        getattr(settings, "SILENT_DETECTION_OUTAGE_DEPTH", DEFAULT_OUTAGE_DEPTH)
    )


def _max_latency_days(settings: Any) -> int:
    return int(
        getattr(settings, "SILENT_DETECTION_MAX_LATENCY_DAYS", DEFAULT_MAX_LATENCY_DAYS)
    )


def build_scenario(
    cells: list[Any],
    *,
    reference: date,
    horizon_days: int,
    onset_rate: float,
    outage_days: int,
) -> ScenarioSpec:
    """Deterministically inject ground-truth silent episodes over the horizon.

    Each cell independently becomes an outage cell when its stable hash clears
    ``onset_rate``; its onset sits somewhere in the horizon and the episode runs
    for ``outage_days`` (clipped so it never extends past the reference day).
    The same inputs always produce the same scenario, so the measured metrics
    are reproducible.
    """
    eval_days = tuple(
        reference - timedelta(days=offset) for offset in range(horizon_days - 1, -1, -1)
    )
    episodes: list[SilentEpisode] = []
    for cell in cells:
        key = str(cell.region_key)
        if _det_unit(f"onset:{key}") >= onset_rate:
            continue
        slot = int(_det_unit(f"slot:{key}") * horizon_days)
        onset = eval_days[min(slot, horizon_days - 1)]
        span = min(outage_days, (reference - onset).days + 1)
        episodes.append(
            SilentEpisode(region_key=key, onset=onset, duration_days=max(span, 1))
        )
    return ScenarioSpec(episodes=tuple(episodes), eval_days=eval_days)


def confusion_metrics(
    true_positive: int,
    false_positive: int,
    false_negative: int,
    true_negative: int,
) -> dict[str, Any]:
    """Rates from a confusion matrix, undefined ratios reported as ``None``.

    An empty positive or negative class yields ``None`` (unknown), never a
    misleading ``0.0`` - a detector cannot be credited or blamed for a case
    that never occurred.
    """
    total = true_positive + false_positive + false_negative + true_negative
    positives = true_positive + false_negative
    negatives = false_positive + true_negative
    tpr = true_positive / positives if positives else None
    fpr = false_positive / negatives if negatives else None
    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive)
        else None
    )
    recall = tpr
    f1_score = (
        2 * precision * recall / (precision + recall)
        if precision and recall and (precision + recall) > 0
        else (0.0 if (precision is not None and recall is not None) else None)
    )
    accuracy = (true_positive + true_negative) / total if total else None
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "evaluated_cell_days": total,
        "positive_cell_days": positives,
        "negative_cell_days": negatives,
        "tpr": _round_rate(tpr),
        "fpr": _round_rate(fpr),
        "precision": _round_rate(precision),
        "recall": _round_rate(recall),
        "f1": _round_rate(f1_score),
        "accuracy": _round_rate(accuracy),
    }


def _round_rate(value: Optional[float]) -> Optional[float]:
    return round(value, 4) if value is not None else None


class _NullSettings:
    """Sentinel so ``performance_config()`` works with no settings supplied."""


def evaluate_detection(
    settings: Any,
    *,
    source: Optional[str] = None,
    reference: Optional[date] = None,
    horizon_days: Optional[int] = None,
    baseline_window_days: Optional[int] = None,
    onset_rate: Optional[float] = None,
    outage_days: Optional[int] = None,
    outage_depth: Optional[float] = None,
    sensitivity_z: Optional[float] = None,
) -> dict[str, Any]:
    """Replay the EM-035 detector over a synthetic scenario and score it.

    Returns the confusion matrix, the headline rates (TPR / FPR / precision /
    F1 / accuracy) and an alert-delay summary, always marked as a synthetic
    scenario.
    """
    base = (
        resolve_source(source, settings) if source else SyntheticCommunicationSource()
    )
    window = _baseline_window(settings, baseline_window_days)
    horizon = _horizon_days(settings, horizon_days)
    sensitivity = (
        float(sensitivity_z) if sensitivity_z is not None else _sensitivity_z(settings)
    )
    rate = (
        max(0.0, min(float(onset_rate), 1.0))
        if onset_rate is not None
        else _onset_rate(settings)
    )
    o_days = int(outage_days) if outage_days is not None else _outage_days(settings)
    depth = float(outage_depth) if outage_depth is not None else _outage_depth(settings)
    max_latency = _max_latency_days(settings)
    stamp = reference or date.today()

    cells = monitoring_cells(settings)
    scenario = build_scenario(
        cells,
        reference=stamp,
        horizon_days=horizon,
        onset_rate=rate,
        outage_days=o_days,
    )
    scored_source = OutageInjectedSource(base, scenario.episodes, depth)

    # Score every cell-day with the actual detector, tallying the confusion
    # matrix against the injected truth.
    truth_by_cell: dict[str, dict[str, bool]] = {}
    pred_by_cell: dict[str, dict[str, bool]] = {}
    tpos = fpos = fneg = tneg = 0
    for cell in cells:
        key = str(cell.region_key)
        truth_by_cell[key] = {}
        pred_by_cell[key] = {}
        for day in scenario.eval_days:
            row = compute_cell_baseline(cell, scored_source, day, window, sensitivity)
            pred = bool(row["candidate_silent"])
            truth = scenario.truth(key, day)
            truth_by_cell[key][day.isoformat()] = truth
            pred_by_cell[key][day.isoformat()] = pred
            if truth and pred:
                tpos += 1
            elif truth and not pred:
                fneg += 1
            elif not truth and pred:
                fpos += 1
            else:
                tneg += 1

    metrics = confusion_metrics(tpos, fpos, fneg, tneg)

    # Alert delay per episode: the first flagged day on/after onset, within the
    # latency window; never-detected episodes are counted but excluded from the
    # delay statistics (undefined delay, not zero).
    episode_rows: list[dict[str, Any]] = []
    delays: list[int] = []
    undetected = 0
    for episode in scenario.episodes:
        positive_days = 0
        first_flag: Optional[date] = None
        for day in scenario.eval_days:
            if episode.covers(day):
                positive_days += 1
                flagged = pred_by_cell[episode.region_key][day.isoformat()]
                if first_flag is None and flagged:
                    first_flag = day
        detected = first_flag is not None
        object.__setattr__(episode, "first_flag_day", first_flag)
        object.__setattr__(episode, "detected", detected)
        object.__setattr__(episode, "positive_cell_days", positive_days)
        if detected and first_flag is not None:
            delay = (first_flag - episode.onset).days
            object.__setattr__(episode, "alert_delay_days", delay)
            delays.append(delay)
        else:
            object.__setattr__(episode, "alert_delay_days", None)
            undetected += 1
        episode_rows.append(episode.as_dict())

    delay_summary = _delay_summary(delays, undetected, len(scenario.episodes))

    panel = {
        "panel": "silent_detection_performance",
        "reference": stamp.isoformat(),
        "horizon_days": horizon,
        "baseline_window_days": window,
        "sensitivity_z": sensitivity,
        "source_kind": scored_source.kind,
        "source_label": scored_source.label,
        "cell_count": len(cells),
        "episode_count": len(scenario.episodes),
        "onset_rate": rate,
        "outage_days": o_days,
        "outage_depth": depth,
        "max_latency_days": max_latency,
        "confusion": metrics,
        "tpr": metrics["tpr"],
        "fpr": metrics["fpr"],
        "precision": metrics["precision"],
        "f1": metrics["f1"],
        "accuracy": metrics["accuracy"],
        "alert_delay": delay_summary,
        "episodes": episode_rows,
        "attribution": PERFORMANCE_ATTRIBUTION,
        "persistence": PERFORMANCE_PERSISTENCE,
        "synthetic": True,
        "scenario_label": SCENARIO_LABEL,
        "synthetic_label": SYNTHETIC_LABEL,
    }
    return panel


def _delay_summary(
    delays: list[int], undetected: int, episode_count: int
) -> dict[str, Any]:
    """Mean/min/max alert delay over detected episodes + the miss count."""
    if not delays:
        return {
            "measured_episodes": 0,
            "undetected_episodes": undetected,
            "mean_days": None,
            "min_days": None,
            "max_days": None,
        }
    return {
        "measured_episodes": len(delays),
        "undetected_episodes": undetected,
        "total_episodes": episode_count,
        "mean_days": round(sum(delays) / len(delays), 2),
        "min_days": min(delays),
        "max_days": max(delays),
    }


def performance_config(settings: Any = None) -> dict[str, Any]:
    """The scenario knobs and bounds shared with the panel and integrators."""
    cfg = settings if settings is not None else _NullSettings()
    return {
        "horizon_days": {
            "default": int(
                getattr(cfg, "SILENT_DETECTION_HORIZON_DAYS", DEFAULT_HORIZON_DAYS)
            ),
            "min": MIN_HORIZON_DAYS,
            "max": MAX_HORIZON_DAYS,
        },
        "baseline_window_days": {
            "default": int(
                getattr(
                    cfg,
                    "SILENT_DETECTION_BASELINE_WINDOW_DAYS",
                    DEFAULT_BASELINE_WINDOW_DAYS,
                )
            ),
            "min": MIN_BASELINE_WINDOW_DAYS,
            "max": MAX_BASELINE_WINDOW_DAYS,
        },
        "sensitivity_z": _sensitivity_z(cfg),
        "onset_rate": _onset_rate(cfg),
        "outage_days": _outage_days(cfg),
        "outage_depth": _outage_depth(cfg),
        "max_latency_days": _max_latency_days(cfg),
        "metrics": ["tpr", "fpr", "precision", "recall", "f1", "accuracy"],
        "alert_delay": "days between an injected episode onset and the first flag",
        "attribution": PERFORMANCE_ATTRIBUTION,
        "persistence": PERFORMANCE_PERSISTENCE,
        "synthetic": True,
        "scenario_label": SCENARIO_LABEL,
    }


__all__ = [
    "PERFORMANCE_ATTRIBUTION",
    "PERFORMANCE_PERSISTENCE",
    "SCENARIO_LABEL",
    "SCENARIO_SOURCE_KIND",
    "OutageInjectedSource",
    "SilentDetectionPerformanceError",
    "SilentEpisode",
    "build_scenario",
    "confusion_metrics",
    "evaluate_detection",
    "performance_config",
]
