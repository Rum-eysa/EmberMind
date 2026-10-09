"""Isolation Forest silent-zone anomaly scoring (EM-036, Epic E4).

EM-035 learns *what normal looks like* per cell and EM-043 removes the
seasonality that made quiet nights look abnormal - but both still flag a silent
zone with a single hand-picked z-score. The data scientist's ask (acceptance:
"bölgelerin normal dışı sessizleşmesini otomatik puanlamak ... elle inceleme
gerekmesin" + "eşik: ortalama(baz çizgi) − 3σ; yapılandırılabilir") is a
**learned, multi-feature anomaly score**: instead of eyeballing one statistic,
an :class:`~sklearn.ensemble.IsolationForest` is fitted per cell over the same
baseline window and scores the latest reading automatically.

Design (kept deliberately read-time, ``persistence`` = ``none`` like the EM-035 /
EM-043 baselines it builds on):

* the EM-035 baseline is **reused** (:func:`compute_cell_baseline`) for the
  statistical side - the configurable ``mean - sigma * std`` quiet threshold is
  the acceptance criterion, and ``sigma`` defaults to 3.0 and is tunable;
* a two-feature ``[bugünkü sinyal, dünki sinyal]`` vector (level + day-to-day
  momentum) is fed to the Isolation Forest so the learned score captures an
  unusual *combination*, not just a low value - a genuinely multi-feature model;
* the estimator is pinned to a fixed ``random_state`` so scores are reproducible
  across runs (they must not drift with ``PYTHONHASHSEED``);
* "gerçek zamanlı ... 15 dakikalık aralıklarla" is modelled as a recompute cadence
  (``ANOMALY_INTERVAL_MINUTES``) driven by a Celery beat that calls
  :func:`score_silent_zone_anomalies`; nothing is stored, so the beat simply
  refreshes the numbers a caller reads.

Signal comes through the same swappable ``SignalSource`` interface as EM-035; for
the pilot we reuse the deterministic synthetic feeds (clearly ``synthetic``) and
real feeds would drop in behind the same interface - never faked here.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from src.services.signal_baseline import (
    MAX_WINDOW_DAYS,
    MIN_WINDOW_DAYS,
    DEFAULT_SENSITIVITY_Z,
    DEFAULT_SOURCE_KIND,
    DEFAULT_WINDOW_DAYS,
    PLANNED_SOURCE_KINDS,
    SYNTHETIC_LABEL,
    SignalBaselineError,
    SignalSource,
    available_source_kinds,
    compute_cell_baseline,
    monitoring_cells,
    resolve_source,
)

DEFAULT_SIGMA_MULTIPLIER = 3.0
MIN_SIGMA_MULTIPLIER = 1.0
MAX_SIGMA_MULTIPLIER = 5.0
DEFAULT_CONTAMINATION = 0.1
MAX_CONTAMINATION = 0.5
DEFAULT_N_ESTIMATORS = 100
DEFAULT_MAX_CELLS = 60
DEFAULT_INTERVAL_MINUTES = 15
# Pinned so the Isolation Forest is reproducible run-to-run; a learned score
# that wanders between requests would be un-reviewable and un-testable.
DEFAULT_RANDOM_STATE = 0

ANOMALY_ATTRIBUTION = (
    "EM-036: her hücre için baz penceresinde Isolation Forest eğitilir ve son "
    "okumun çok-özellikli anomali skoru otomatik üretilir; sessizlik eşiği "
    "ortalama(baz) - sigma*sapma (sigma varsayılan 3.0, yapılandırılabilir); "
    "gerçek zamanlı tazeleme 15 dakikalık aralıklarla (ANOMALY_INTERVAL_MINUTES)"
)
ANOMALY_PERSISTENCE = "none"
FEATURE_NAMES = ("signal_today", "signal_yesterday")


class IsolationForestAnomalyError(ValueError):
    """Raised for an invalid anomaly request (unknown source, bad date/window)."""


def _sigma_multiplier(settings: Any, override: Optional[float] = None) -> float:
    raw = (
        override
        if override is not None
        else getattr(settings, "ANOMALY_SIGMA_MULTIPLIER", DEFAULT_SIGMA_MULTIPLIER)
    )
    value = float(raw)
    if value < MIN_SIGMA_MULTIPLIER or value > MAX_SIGMA_MULTIPLIER:
        raise IsolationForestAnomalyError(
            f"geçersiz sigma katsayısı: {value}; "
            f"{MIN_SIGMA_MULTIPLIER}..{MAX_SIGMA_MULTIPLIER} olmalı"
        )
    return value


def _window_days(settings: Any, override: Optional[int] = None) -> int:
    raw = (
        override
        if override is not None
        else getattr(settings, "ANOMALY_WINDOW_DAYS", DEFAULT_WINDOW_DAYS)
    )
    value = int(raw)
    return max(MIN_WINDOW_DAYS, min(value, MAX_WINDOW_DAYS))


def _contamination(settings: Any) -> float:
    raw = float(getattr(settings, "ANOMALY_CONTAMINATION", DEFAULT_CONTAMINATION))
    if raw <= 0.0 or raw > MAX_CONTAMINATION:
        return DEFAULT_CONTAMINATION
    return raw


def _n_estimators(settings: Any) -> int:
    value = int(getattr(settings, "ANOMALY_N_ESTIMATORS", DEFAULT_N_ESTIMATORS))
    return max(10, min(value, 500))


def _random_state(settings: Any) -> int:
    return int(getattr(settings, "ANOMALY_RANDOM_STATE", DEFAULT_RANDOM_STATE))


def _sensitivity_z(settings: Any) -> float:
    return float(
        getattr(settings, "SIGNAL_BASELINE_SENSITIVITY_Z", DEFAULT_SENSITIVITY_Z)
    )


def _max_cells(settings: Any) -> int:
    return int(getattr(settings, "ANOMALY_MAX_CELLS", DEFAULT_MAX_CELLS))


def interval_minutes(settings: Any) -> int:
    """The real-time recompute cadence (minutes) the beat schedules on."""
    value = int(getattr(settings, "ANOMALY_INTERVAL_MINUTES", DEFAULT_INTERVAL_MINUTES))
    return max(1, value)


def _signal_map(
    source: SignalSource, region_key: str, as_of: date, window_days: int
) -> dict[date, float]:
    """Daily signals for ``as_of`` back to the extra day a lag feature needs.

    The window's oldest day still requires its previous day for the momentum
    feature, so we read one day further back than the baseline window itself.
    """
    series: dict[date, float] = {}
    for offset in range(0, window_days + 2):
        day = as_of - timedelta(days=offset)
        series[day] = source.daily_signal(region_key, day)
    return series


def build_feature_matrix(
    source: SignalSource, region_key: str, as_of: date, window_days: int
) -> tuple[list[list[float]], list[float]]:
    """Split the cell's window into Isolation-Forest training rows + latest row.

    Each observation is the ``[today, yesterday]`` signal pair, so the model
    learns both the level and the day-to-day momentum as normal. The training
    rows are the ``window_days`` days *ending the day before* ``as_of``; the
    latest row (``as_of``) is scored, never trained on - the same discipline
    EM-035's baseline uses so ``as_of`` can legitimately look anomalous.
    """
    series = _signal_map(source, region_key, as_of, window_days)
    training: list[list[float]] = []
    for offset in range(window_days, 0, -1):
        day = as_of - timedelta(days=offset)
        prev = day - timedelta(days=1)
        training.append([series[day], series[prev]])
    latest = [series[as_of], series[as_of - timedelta(days=1)]]
    return training, latest


def score_cell_anomaly(
    cell: Any,
    source: SignalSource,
    settings: Any,
    as_of: date,
    window_days: int,
    sigma_multiplier: float,
) -> dict[str, Any]:
    """Fit the cell's Isolation Forest on its window and score the latest day.

    Returns the learned ``anomaly_score`` (sklearn convention: lower is more
    anomalous) and ``learned_anomalous`` flag *alongside* the statistical
    ``mean - sigma * std`` quiet test, so the operator sees whether the model and
    the configurable threshold agree.
    """
    baseline = compute_cell_baseline(
        cell, source, as_of, window_days, _sensitivity_z(settings)
    )
    training, latest = build_feature_matrix(source, cell.region_key, as_of, window_days)
    model = IsolationForest(
        n_estimators=_n_estimators(settings),
        contamination=_contamination(settings),
        random_state=_random_state(settings),
    )
    matrix = np.asarray(training, dtype=float)
    model.fit(matrix)
    sample = np.asarray([latest], dtype=float)
    anomaly_score = float(model.score_samples(sample)[0])
    learned_anomalous = bool(int(model.predict(sample)[0]) == -1)

    mean = float(baseline["baseline_mean"])
    std = float(baseline["baseline_std"])
    current = float(baseline["latest_value"])
    quiet_threshold = round(mean - sigma_multiplier * std, 3) if std > 0 else None
    silent_anomaly = bool(
        std > 0 and quiet_threshold is not None and current < quiet_threshold
    )
    is_anomaly = bool(silent_anomaly or learned_anomalous)

    payload = cell.as_dict()
    payload.update(
        {
            "source_kind": source.kind,
            "window_days": window_days,
            "sigma_multiplier": sigma_multiplier,
            "as_of": as_of.isoformat(),
            "baseline_mean": baseline["baseline_mean"],
            "baseline_std": baseline["baseline_std"],
            "latest_value": baseline["latest_value"],
            "z_score": baseline["z_score"],
            "quiet_threshold": quiet_threshold,
            "anomaly_score": round(anomaly_score, 4),
            "learned_anomalous": learned_anomalous,
            "silent_anomaly": silent_anomaly,
            "is_anomaly": is_anomaly,
            "detection_basis": (
                "both"
                if silent_anomaly and learned_anomalous
                else "statistical"
                if silent_anomaly
                else "isolation_forest"
                if learned_anomalous
                else "none"
            ),
            "synthetic": bool(source.synthetic),
        }
    )
    if source.synthetic:
        payload["synthetic_label"] = SYNTHETIC_LABEL
    return payload


def _resolve_and_score(
    settings: Any,
    source: Optional[str],
    as_of: Optional[date],
    window_days: Optional[int],
    sigma: Optional[float],
    region_key: Optional[str],
) -> tuple[SignalSource, date, int, float, list[dict[str, Any]]]:
    """Shared resolution + per-cell scoring for the report and the beat sweep."""
    try:
        resolved = resolve_source(source, settings)
    except SignalBaselineError as exc:
        raise IsolationForestAnomalyError(str(exc)) from exc
    stamp = as_of or date.today()
    window = _window_days(settings, window_days)
    multiplier = _sigma_multiplier(settings, sigma)

    cells = monitoring_cells(settings)
    cells = cells[: _max_cells(settings)]
    wanted = region_key.strip() if region_key else None
    if wanted:
        cells = [c for c in cells if c.region_key == wanted]

    rows = [
        score_cell_anomaly(cell, resolved, settings, stamp, window, multiplier)
        for cell in cells
    ]
    return resolved, stamp, window, multiplier, rows


def anomaly_report(
    settings: Any,
    *,
    source: Optional[str] = None,
    as_of: Optional[date] = None,
    window_days: Optional[int] = None,
    sigma_multiplier: Optional[float] = None,
    region_key: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Per-cell learned anomaly scores + the configurable-threshold quiet test.

    Rows are ordered most-anomalous-first (ascending ``anomaly_score``), then by
    ``region_key`` for a stable tie-break, and can be narrowed to one cell or
    paged with ``limit`` while the summary stays global.
    """
    resolved, stamp, window, multiplier, rows = _resolve_and_score(
        settings, source, as_of, window_days, sigma_multiplier, region_key
    )
    rows.sort(key=lambda r: (r["anomaly_score"], r["region_key"]))

    anomaly_count = sum(1 for r in rows if r["is_anomaly"])
    silent_count = sum(1 for r in rows if r["silent_anomaly"])
    learned_count = sum(1 for r in rows if r["learned_anomalous"])

    shown = rows[: max(0, min(int(limit), len(rows)))] if limit is not None else rows
    return {
        "panel": "isolation_forest_anomaly",
        "source_kind": resolved.kind,
        "source_label": resolved.label,
        "as_of": stamp.isoformat(),
        "window_days": window,
        "sigma_multiplier": multiplier,
        "contamination": _contamination(settings),
        "n_estimators": _n_estimators(settings),
        "features": list(FEATURE_NAMES),
        "requested_region": region_key.strip() if region_key else None,
        "cell_count": len(rows),
        "anomaly_count": anomaly_count,
        "silent_anomaly_count": silent_count,
        "learned_anomaly_count": learned_count,
        "cells": shown,
        "attribution": ANOMALY_ATTRIBUTION,
        "persistence": ANOMALY_PERSISTENCE,
        "synthetic": bool(resolved.synthetic),
        "synthetic_label": SYNTHETIC_LABEL if resolved.synthetic else None,
    }


def score_silent_zone_anomalies(
    settings: Any,
    *,
    source: Optional[str] = None,
    as_of: Optional[date] = None,
    window_days: Optional[int] = None,
    sigma_multiplier: Optional[float] = None,
) -> dict[str, Any]:
    """Produce the current real-time anomaly snapshot (the 15-min beat target).

    EM-036's "15 dakikalık aralıklarla gerçek zamanlı anomali skoru üretilir" is
    this read-time sweep: a caller (or the Celery beat) runs it on the configured
    cadence and every cell's learned score + quiet-threshold flag are refreshed
    for ``as_of``. Nothing is persisted, so ``persistence`` stays ``none``.
    """
    resolved, stamp, window, multiplier, rows = _resolve_and_score(
        settings, source, as_of, window_days, sigma_multiplier, None
    )
    scored = sorted(rows, key=lambda r: (r["anomaly_score"], r["region_key"]))
    anomaly_cells = [r["region_key"] for r in scored if r["is_anomaly"]]
    return {
        "panel": "isolation_forest_anomaly",
        "scored_at": stamp.isoformat(),
        "interval_minutes": interval_minutes(settings),
        "source_kind": resolved.kind,
        "window_days": window,
        "sigma_multiplier": multiplier,
        "cell_count": len(rows),
        "anomaly_count": len(anomaly_cells),
        "anomaly_region_keys": anomaly_cells,
        "attribution": ANOMALY_ATTRIBUTION,
        "persistence": ANOMALY_PERSISTENCE,
        "synthetic": bool(resolved.synthetic),
    }


class _NullAnomaly:
    """Sentinel so ``anomaly_config()`` works with no settings supplied."""


def anomaly_config(settings: Any = None) -> dict[str, Any]:
    """Catalogue the panel and integrators share: sources, bounds, cadence."""

    cfg = settings if settings is not None else _NullAnomaly()
    return {
        "sources": {
            "available": available_source_kinds(),
            "planned": list(PLANNED_SOURCE_KINDS),
            "default": str(getattr(cfg, "ANOMALY_DEFAULT_SOURCE", DEFAULT_SOURCE_KIND)),
        },
        "sigma_multiplier": {
            "default": float(
                getattr(cfg, "ANOMALY_SIGMA_MULTIPLIER", DEFAULT_SIGMA_MULTIPLIER)
            ),
            "min": MIN_SIGMA_MULTIPLIER,
            "max": MAX_SIGMA_MULTIPLIER,
        },
        "window_days": {
            "default": int(getattr(cfg, "ANOMALY_WINDOW_DAYS", DEFAULT_WINDOW_DAYS)),
            "min": MIN_WINDOW_DAYS,
            "max": MAX_WINDOW_DAYS,
        },
        "model": {
            "algorithm": "IsolationForest",
            "contamination": _contamination(cfg),
            "n_estimators": _n_estimators(cfg),
            "random_state": _random_state(cfg),
            "features": list(FEATURE_NAMES),
        },
        "realtime": {
            "interval_minutes": interval_minutes(cfg),
            "enabled": bool(getattr(cfg, "ANOMALY_SCORING_ENABLED", True)),
            "note": "Celery beat, okuma zamanı yeniden hesap - kalıcılık yok",
        },
        "cell_count": len(monitoring_cells(cfg)[: _max_cells(cfg)]),
        "attribution": ANOMALY_ATTRIBUTION,
        "persistence": ANOMALY_PERSISTENCE,
        "synthetic": True,
        "synthetic_label": SYNTHETIC_LABEL,
    }


__all__ = [
    "ANOMALY_ATTRIBUTION",
    "ANOMALY_PERSISTENCE",
    "FEATURE_NAMES",
    "IsolationForestAnomalyError",
    "anomaly_config",
    "anomaly_report",
    "build_feature_matrix",
    "interval_minutes",
    "score_cell_anomaly",
    "score_silent_zone_anomalies",
]
