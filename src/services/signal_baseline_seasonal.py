"""Seasonally-adjusted signal baseline + daily refresh (EM-043, Epic E4).

EM-035 learns a *flat* 30-day normal per cell, so a reading that is quiet for a
structural reason - the small hours of the night, a weekend - sits far below that
flat mean and scores as a false "silent" candidate. EM-043 closes that gap for the
data scientist (acceptance: "saat ve haftanın günü etkisi modele eklenir; baz
çizgisi günlük yeniden hesaplanır; yanlış alarm oranı yenileme öncesi/sonrası
karşılaştırılır"): it learns **hour-of-day** and **day-of-week** seasonal factors,
deseasonalises the signal, and scores the *residual* against the seasonal normal -
so night/weekend quiet is expected, not anomalous.

The seasonal factors come from a multiplicative two-way decomposition fitted with a
few iterative-normalisation passes (a statistical adjustment, deliberately *not* the
learned anomaly classifier EM-036). A dedicated ``SyntheticDiurnalSource`` emits an
hourly signal (quiet nights, busy midday, lighter weekends) so the hour dimension is
real and testable; a daily-only source degrades honestly to weekday-only seasonality.

"Günlük yeniden hesaplama" is modelled read-time: :func:`refresh_daily_baselines`
recomputes every cell's seasonal baseline *as of* a requested date, so a caller that
runs it once per day keeps the baseline current - nothing is persisted, so
``persistence`` is ``none`` like the EM-035 baseline it builds on. The report always
carries the **flat (before) vs seasonal (after)** candidate flags so the false-alarm
reduction from seasonal adjustment is directly comparable per cell.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Optional

from src.services.signal_baseline import (
    MAX_WINDOW_DAYS,
    MIN_WINDOW_DAYS,
    DEFAULT_SENSITIVITY_Z,
    DEFAULT_WINDOW_DAYS,
    SYNTHETIC_LABEL,
    SignalSource,
    _hash01,
    monitoring_cells,
)

HOURS_IN_DAY = 24
DAYS_IN_WEEK = 7
DEFAULT_NIGHT_CHECK_HOUR = 3
DEFAULT_NORMALIZATION_ITERATIONS = 3
DEFAULT_MAX_CELLS = 60
DIURNAL_SOURCE_KIND = "synthetic_diurnal"

# Relative diurnal shape: deep-quiet night, ramp through the morning, a broad
# midday/afternoon peak, tapering into the evening. Normalised during learning, so
# the raw level does not matter - only the hour-to-hour ratio. Index == hour (0..23).
DIURNAL_PROFILE = [
    0.30,
    0.26,
    0.24,
    0.24,
    0.26,
    0.34,  # 00-05 night
    0.55,
    0.80,
    1.05,
    1.20,
    1.28,
    1.30,  # 06-11 morning ramp
    1.25,
    1.15,
    1.10,
    1.12,
    1.20,
    1.30,  # 12-17 midday/afternoon
    1.20,
    1.05,
    0.85,
    0.65,
    0.48,
    0.36,  # 18-23 evening taper
]

TURKISH_WEEKDAYS = (
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
)

SEASONAL_ATTRIBUTION = (
    "EM-043: saat-in-günü + haftanın-günü mevsimsel kat sayıları öğrenilip baz "
    "çizgisi mevsimsellikten arındırılır; gece/hafta sonu sessizliği anomali "
    "sayılmaz; baz çizgisi istenen tarih için günlük yeniden hesaplanır; düz "
    "(önceki) ile mevsimsel (sonraki) aday işaretleri yanlış-alarm karşılaştırması "
    "için birlikte raporlanır - anomali sınıflandırıcısı EM-036'ya aittir"
)
SEASONAL_PERSISTENCE = "none"
SEASONALITY_DIMENSIONS = ("hour_of_day", "day_of_week")


class SignalSeasonalError(ValueError):
    """Raised for an invalid seasonal-baseline request (unknown source, bad hour)."""


class SyntheticDiurnalSource(SignalSource):
    """Deterministic hourly report flow: quiet nights, busy days, lighter weekends.

    Emits an *hourly* signal so the hour-of-day seasonal factor is learnable, which
    is exactly what makes night silence a normal (not an anomaly). Same ``(cell, day,
    hour)`` always yields the same value; nothing is random across runs.
    """

    kind = DIURNAL_SOURCE_KIND
    label = "Sentetik gündüz/gece + haftalık iletişim akışı"
    synthetic = True
    has_hourly = True

    def __init__(self) -> None:
        # The per-cell base level is constant across every (day, hour) of a
        # region, so cache it by region key rather than re-deriving the same
        # ``dbase:`` hash on all ``window_days * 24`` sample reads.
        self._base_cache: dict[str, float] = {}

    def _base_for(self, region_key: str) -> float:
        """Cached constant base signal for one region cell."""
        cached = self._base_cache.get(region_key)
        if cached is None:
            cached = 60.0 + _hash01(f"dbase:{region_key}") * 140.0
            self._base_cache[region_key] = cached
        return cached

    def hourly_signal(self, region_key: str, day: date, hour: int) -> float:
        """Signal strength for one cell at one hour of one day."""
        bounded = hour % HOURS_IN_DAY
        base = self._base_for(region_key)
        diurnal = DIURNAL_PROFILE[bounded]
        weekend = 0.72 if day.weekday() >= 5 else 1.0
        jitter = 0.85 + _hash01(f"dn:{region_key}:{day.isoformat()}:{bounded}") * 0.30
        return round(base * diurnal * weekend * jitter, 3)

    def daily_signal(self, region_key: str, day: date) -> float:
        """Mean of the day's hourly signal (the daily aggregate of the same flow)."""
        hours = [self.hourly_signal(region_key, day, h) for h in range(HOURS_IN_DAY)]
        return round(sum(hours) / len(hours), 3)


# Sources selectable for the seasonal panel: the EM-043 diurnal feed plus EM-035's
# daily synthetic feed (weekday-only seasonality). Real feeds would land here too.
SEASONAL_SOURCES: dict[str, SignalSource] = {
    DIURNAL_SOURCE_KIND: SyntheticDiurnalSource(),
}


def _daily_source() -> Optional[SignalSource]:
    """Best-effort access to EM-035's daily source for a non-hourly comparison."""
    from src.services import signal_baseline  # local import to avoid a cycle

    return signal_baseline.SIGNAL_SOURCES.get(signal_baseline.DEFAULT_SOURCE_KIND)


def available_seasonal_source_kinds() -> list[str]:
    """Source kinds the seasonal panel can drive (diurnal + EM-035 daily)."""
    kinds = set(SEASONAL_SOURCES)
    daily = _daily_source()
    if daily is not None:
        kinds.add(daily.kind)
    return sorted(kinds)


def resolve_seasonal_source(kind: Optional[str], settings: Any) -> SignalSource:
    """Pick a seasonal-capable source by kind; default is the diurnal feed."""
    chosen = (
        (
            kind
            or str(
                getattr(settings, "SIGNAL_SEASONAL_DEFAULT_SOURCE", DIURNAL_SOURCE_KIND)
            )
        )
        .strip()
        .lower()
    )
    if chosen in SEASONAL_SOURCES:
        return SEASONAL_SOURCES[chosen]
    daily = _daily_source()
    if daily is not None and chosen == daily.kind:
        return daily
    raise SignalSeasonalError(
        f"bilinmeyen mevsimsel sinyal kaynağı: {chosen}; kullanılabilir: "
        f"{', '.join(available_seasonal_source_kinds())}"
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    center = _mean(values)
    variance = sum((x - center) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _normalize(factors: list[float]) -> list[float]:
    """Scale a factor list so its positive mean is 1 (a neutral baseline)."""
    positive = [f for f in factors if f > 0]
    center = _mean(positive) if positive else 0.0
    if center <= 0:
        return [1.0 for _ in factors]
    return [f / center if f > 0 else 1.0 for f in factors]


def _window_days(settings: Any, override: Optional[int]) -> int:
    raw = (
        override
        if override is not None
        else getattr(settings, "SIGNAL_BASELINE_WINDOW_DAYS", DEFAULT_WINDOW_DAYS)
    )
    value = int(raw)
    return max(MIN_WINDOW_DAYS, min(value, MAX_WINDOW_DAYS))


def _sensitivity_z(settings: Any) -> float:
    return float(
        getattr(settings, "SIGNAL_BASELINE_SENSITIVITY_Z", DEFAULT_SENSITIVITY_Z)
    )


def _night_hour(settings: Any, override: Optional[int]) -> int:
    raw = (
        override
        if override is not None
        else getattr(
            settings, "SIGNAL_SEASONAL_NIGHT_CHECK_HOUR", DEFAULT_NIGHT_CHECK_HOUR
        )
    )
    hour = int(raw)
    if hour < 0 or hour >= HOURS_IN_DAY:
        raise SignalSeasonalError(
            f"geçersiz saat: {hour}; 0..{HOURS_IN_DAY - 1} olmalı"
        )
    return hour


def _iterations(settings: Any) -> int:
    value = int(
        getattr(
            settings,
            "SIGNAL_SEASONAL_NORMALIZATION_ITERATIONS",
            DEFAULT_NORMALIZATION_ITERATIONS,
        )
    )
    return max(1, min(value, 10))


def _max_cells(settings: Any) -> int:
    return int(getattr(settings, "SIGNAL_SEASONAL_MAX_CELLS", DEFAULT_MAX_CELLS))


def _samples(
    source: SignalSource, region_key: str, days: list[date], hour: int
) -> list[tuple[int, int, float]]:
    """Collect ``(weekday, hour, value)`` samples over the window.

    An hourly source contributes one sample per ``(day, hour)``; a daily-only
    source contributes one sample per day (which yields a neutral hour factor).
    """
    samples: list[tuple[int, int, float]] = []
    for day in days:
        weekday = day.weekday()
        if getattr(source, "has_hourly", False):
            for h in range(HOURS_IN_DAY):
                samples.append((weekday, h, source.hourly_signal(region_key, day, h)))
        else:
            samples.append((weekday, hour, source.daily_signal(region_key, day)))
    return samples


def learn_seasonal_factors(
    source: SignalSource,
    region_key: str,
    days: list[date],
    hour: int,
    iterations: int = DEFAULT_NORMALIZATION_ITERATIONS,
) -> dict[str, Any]:
    """Fit hour-of-day and day-of-week factors by iterative two-way normalisation.

    Returns the factors plus the deseasonalised residual level/spread and the raw
    (flat) mean/spread, so a caller can score a reading both ways. With a daily-only
    source the hour factors all collapse to 1 (honest weekday-only seasonality).
    """
    samples = _samples(source, region_key, days, hour)
    hour_factors = [1.0] * HOURS_IN_DAY
    weekday_factors = [1.0] * DAYS_IN_WEEK
    is_hourly = bool(getattr(source, "has_hourly", False))

    # Bucket the samples once by hour and by weekday. Each normalisation pass then
    # walks only the relevant bucket instead of re-scanning the whole sample list
    # 24 + 7 times per pass; the per-bucket order is preserved, so every mean is
    # bit-for-bit identical to the naive full-scan version.
    by_hour: list[list[tuple[int, float]]] = [[] for _ in range(HOURS_IN_DAY)]
    by_weekday: list[list[tuple[int, float]]] = [[] for _ in range(DAYS_IN_WEEK)]
    for weekday_idx, hour_idx, value in samples:
        by_hour[hour_idx].append((weekday_idx, value))
        by_weekday[weekday_idx].append((hour_idx, value))

    for _ in range(max(1, iterations)):
        # A daily-only source carries no hour information, so the hour dimension
        # stays neutral (all 1.0) and only the weekday rhythm is learned - an
        # honest degrade to weekday-only seasonality rather than noise on the one
        # probed hour.
        if is_hourly:
            for h in range(HOURS_IN_DAY):
                adjusted = [
                    value / weekday_factors[w]
                    for (w, value) in by_hour[h]
                    if weekday_factors[w] > 0
                ]
                hour_factors[h] = _mean(adjusted) if adjusted else 1.0
            hour_factors = _normalize(hour_factors)
        for w in range(DAYS_IN_WEEK):
            adjusted = [
                value / hour_factors[h]
                for (h, value) in by_weekday[w]
                if hour_factors[h] > 0
            ]
            weekday_factors[w] = _mean(adjusted) if adjusted else 1.0
        weekday_factors = _normalize(weekday_factors)

    residual = [
        value / (hour_factors[h] * weekday_factors[w])
        for (w, h, value) in samples
        if hour_factors[h] > 0 and weekday_factors[w] > 0
    ]
    raw_values = [value for (_, _, value) in samples]
    return {
        "hour_factors": hour_factors,
        "weekday_factors": weekday_factors,
        "residual_mean": _mean(residual),
        "residual_std": _std(residual),
        "flat_mean": _mean(raw_values),
        "flat_std": _std(raw_values),
        "sample_count": len(samples),
        "hourly_available": bool(getattr(source, "has_hourly", False)),
    }


def seasonal_cell(
    settings: Any,
    cell: Any,
    source: SignalSource,
    as_of: date,
    hour: int,
    window_days: int,
    sensitivity_z: float,
) -> dict[str, Any]:
    """Score one cell's reading at ``(as_of, hour)`` both flat and seasonal."""
    days = [as_of - timedelta(offset) for offset in range(window_days, 0, -1)]
    learned = learn_seasonal_factors(
        source, cell.region_key, days, hour, _iterations(settings)
    )
    weekday = as_of.weekday()
    hf = learned["hour_factors"][hour]
    wf = learned["weekday_factors"][weekday]
    if getattr(source, "has_hourly", False):
        current = source.hourly_signal(cell.region_key, as_of, hour)
    else:
        current = source.daily_signal(cell.region_key, as_of)

    residual_std = learned["residual_std"]
    flat_std = learned["flat_std"]
    # Seasonal expectation for this (weekday, hour) in the raw signal scale.
    expected = learned["residual_mean"] * hf * wf
    current_residual = current / (hf * wf) if hf > 0 and wf > 0 else current
    z_seasonal = (
        round((current_residual - learned["residual_mean"]) / residual_std, 3)
        if residual_std > 0
        else 0.0
    )
    z_flat = (
        round((current - learned["flat_mean"]) / flat_std, 3) if flat_std > 0 else 0.0
    )
    candidate_seasonal = bool(residual_std > 0 and z_seasonal <= -sensitivity_z)
    candidate_flat = bool(flat_std > 0 and z_flat <= -sensitivity_z)

    payload = cell.as_dict()
    payload.update(
        {
            "source_kind": source.kind,
            "as_of": as_of.isoformat(),
            "check_hour": hour,
            "weekday_label": TURKISH_WEEKDAYS[weekday],
            "window_days": window_days,
            "sensitivity_z": sensitivity_z,
            "hour_factor": round(hf, 4),
            "weekday_factor": round(wf, 4),
            "seasonal_expected": round(expected, 3),
            "latest_value": round(current, 3),
            "z_flat": z_flat,
            "z_seasonal": z_seasonal,
            "candidate_flat": candidate_flat,
            "candidate_seasonal": candidate_seasonal,
            "false_alarm_removed": bool(candidate_flat and not candidate_seasonal),
            "hourly_available": bool(getattr(source, "has_hourly", False)),
            "synthetic": bool(source.synthetic),
        }
    )
    if source.synthetic:
        payload["synthetic_label"] = SYNTHETIC_LABEL
    return payload


def _evaluate(
    settings: Any,
    source_kind: Optional[str],
    as_of: Optional[date],
    window_days: Optional[int],
    hour: Optional[int],
    region_key: Optional[str],
) -> tuple[SignalSource, date, int, int, float, list[dict[str, Any]]]:
    """Resolve inputs and score every (selected) cell; shared by report + refresh."""
    resolved = resolve_seasonal_source(source_kind, settings)
    stamp = as_of or date.today()
    window = _window_days(settings, window_days)
    probe_hour = _night_hour(settings, hour)
    sensitivity = _sensitivity_z(settings)

    cells = monitoring_cells(settings)
    cells = cells[: _max_cells(settings)]
    wanted = region_key.strip() if region_key else None
    if wanted:
        cells = [c for c in cells if c.region_key == wanted]
    rows = [
        seasonal_cell(settings, cell, resolved, stamp, probe_hour, window, sensitivity)
        for cell in cells
    ]
    return resolved, stamp, window, probe_hour, sensitivity, rows


def seasonal_report(
    settings: Any,
    *,
    source: Optional[str] = None,
    as_of: Optional[date] = None,
    window_days: Optional[int] = None,
    hour: Optional[int] = None,
    region_key: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Per-cell seasonal vs flat scores + the false-alarm reduction summary."""
    resolved, stamp, window, probe_hour, sensitivity, rows = _evaluate(
        settings, source, as_of, window_days, hour, region_key
    )
    rows.sort(
        key=lambda r: (not r["candidate_seasonal"], r["z_seasonal"], r["region_key"])
    )
    flat_candidates = sum(1 for r in rows if r["candidate_flat"])
    seasonal_candidates = sum(1 for r in rows if r["candidate_seasonal"])
    removed = sum(1 for r in rows if r["false_alarm_removed"])

    shown = rows[: max(0, min(int(limit), len(rows)))] if limit is not None else rows
    return {
        "panel": "signal_baseline_seasonal",
        "source_kind": resolved.kind,
        "source_label": resolved.label,
        "as_of": stamp.isoformat(),
        "window_days": window,
        "sensitivity_z": sensitivity,
        "night_check_hour": probe_hour,
        "requested_region": region_key.strip() if region_key else None,
        "cell_count": len(rows),
        "flat_candidate_count": flat_candidates,
        "seasonal_candidate_count": seasonal_candidates,
        "false_alarms_removed": removed,
        "hourly_available": bool(getattr(resolved, "has_hourly", False)),
        "seasonality_dimensions": list(SEASONALITY_DIMENSIONS),
        "cells": shown,
        "attribution": SEASONAL_ATTRIBUTION,
        "persistence": SEASONAL_PERSISTENCE,
        "synthetic": bool(resolved.synthetic),
        "synthetic_label": SYNTHETIC_LABEL if resolved.synthetic else None,
    }


def refresh_daily_baselines(
    settings: Any,
    *,
    source: Optional[str] = None,
    as_of: Optional[date] = None,
    window_days: Optional[int] = None,
    hour: Optional[int] = None,
) -> dict[str, Any]:
    """Recompute every cell's seasonal baseline *as of* the requested date.

    This is EM-043's "günlük yeniden hesaplama": a caller running it once per day
    refreshes each cell's learned factors through that date. It is read-time (no
    schedule row, nothing persisted), so ``persistence`` stays ``none``.
    """
    resolved, stamp, window, probe_hour, _sensitivity, rows = _evaluate(
        settings, source, as_of, window_days, hour, None
    )
    cells = [
        {
            "region_key": r["region_key"],
            "name": r["name"],
            "hour_factor": r["hour_factor"],
            "weekday_factor": r["weekday_factor"],
            "seasonal_expected": r["seasonal_expected"],
            "refreshed_for": r["as_of"],
        }
        for r in rows
    ]
    return {
        "panel": "signal_baseline_seasonal",
        "refreshed_for": stamp.isoformat(),
        "refresh_interval_days": 1,
        "recomputed_cells": len(cells),
        "source_kind": resolved.kind,
        "night_check_hour": probe_hour,
        "window_days": window,
        "cells": cells,
        "attribution": SEASONAL_ATTRIBUTION,
        "persistence": SEASONAL_PERSISTENCE,
    }


def seasonal_baseline_config(settings: Any = None) -> dict[str, Any]:
    """Descriptor: sources, seasonal dimensions, bounds and the daily-refresh mode."""
    cfg = settings if settings is not None else _NullSeasonal()
    cell_count = len(monitoring_cells(cfg)[: _max_cells(cfg)])
    return {
        "sources": {
            "available": available_seasonal_source_kinds(),
            "default": str(
                getattr(cfg, "SIGNAL_SEASONAL_DEFAULT_SOURCE", DIURNAL_SOURCE_KIND)
            ),
        },
        "seasonality_dimensions": list(SEASONALITY_DIMENSIONS),
        "hours_in_day": HOURS_IN_DAY,
        "weekdays": list(TURKISH_WEEKDAYS),
        "night_check_hour": int(
            getattr(cfg, "SIGNAL_SEASONAL_NIGHT_CHECK_HOUR", DEFAULT_NIGHT_CHECK_HOUR)
        ),
        "normalization_iterations": _iterations(cfg),
        "window_days": {
            "default": int(
                getattr(cfg, "SIGNAL_BASELINE_WINDOW_DAYS", DEFAULT_WINDOW_DAYS)
            ),
            "min": MIN_WINDOW_DAYS,
            "max": MAX_WINDOW_DAYS,
        },
        "sensitivity_z": _sensitivity_z(cfg),
        "cell_count": cell_count,
        "refresh": {
            "interval_days": 1,
            "mode": "istek zamanı, istenen tarih için yeniden hesaplanır",
        },
        "attribution": SEASONAL_ATTRIBUTION,
        "persistence": SEASONAL_PERSISTENCE,
        "synthetic": True,
        "synthetic_label": SYNTHETIC_LABEL,
    }


class _NullSeasonal:
    """Sentinel so ``seasonal_baseline_config()`` works with no settings supplied."""


__all__ = [
    "DIURNAL_PROFILE",
    "DIURNAL_SOURCE_KIND",
    "SEASONALITY_DIMENSIONS",
    "SEASONAL_ATTRIBUTION",
    "SEASONAL_PERSISTENCE",
    "SYNTHETIC_LABEL",
    "SignalSeasonalError",
    "SyntheticDiurnalSource",
    "available_seasonal_source_kinds",
    "learn_seasonal_factors",
    "refresh_daily_baselines",
    "resolve_seasonal_source",
    "seasonal_baseline_config",
    "seasonal_cell",
    "seasonal_report",
    "TURKISH_WEEKDAYS",
]
