"""Region communication-signal baseline (EM-035, Epic E4).

Silent-zone *detection* (EM-036 and on) only means something once we know what
"normal" looks like. Before a fire, every monitored cell emits a background
*communication / report* signal - how busy a zone's reporting channels and
sensors usually are. This service learns that pre-fire **normal**: for each
monitored cell it computes a rolling **30-day baseline** (mean, spread, median,
range) of the signal and compares the latest reading against it, so a zone that
is unusually quiet *today* surfaces as a candidate (EM-035 acceptance: "30
günlük baz çizgi bölge (hücre) bazında hesaplanır; sinyal kaynağı: pilot için
sentetik iletişim/rapor akışı, gerçek kaynak arayüzü (trafik yoğunluğu, sosyal
medya, sensör) soyutlanır").

Scope discipline: this is the *baseline*, not the anomaly classifier. The full
multi-feature anomaly score is EM-036 (Isolation Forest) and is deliberately not
implemented here; the ``z_score`` / ``candidate_silent`` fields are a plain
statistical preview of "today vs the learned normal", not a learned model.

The signal comes through a swappable ``SignalSource`` interface. For the pilot
we ship a deterministic ``SyntheticCommunicationSource`` - a synthetic report
flow (weekly seasonality + per-day jitter), clearly labelled ``synthetic``. Real
feeds (traffic density, social media, sensors) would drop in behind the same
interface; they are declared as planned kinds but never faked here (no network).

Nothing is written and no schedule is needed: the baseline is recomputed on read
from the source, so ``persistence`` is ``none``.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

# Default pilot bounding box, mirroring ``config/pilot_region.json``. Overridable
# through settings so the cell lattice can track a re-scoped pilot without a code
# change.
DEFAULT_MIN_LAT = 36.0
DEFAULT_MAX_LAT = 39.5
DEFAULT_MIN_LON = 26.0
DEFAULT_MAX_LON = 30.0

DEFAULT_WINDOW_DAYS = 30
MIN_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 120
DEFAULT_CELL_ROWS = 4
DEFAULT_CELL_COLS = 5
DEFAULT_MAX_CELLS = 60
DEFAULT_SENSITIVITY_Z = 1.5
DEFAULT_SOURCE_KIND = "synthetic_communication"

BASELINE_ATTRIBUTION = (
    "EM-035: hücre bazında 30 günlük iletişim/rapor sinyali baz çizgisi "
    "(ortalama/yayılım/medyan/aralık) + son okumanın baz çizgiye göre "
    "z-skoru; anomali sınıflandırıcısı EM-036'ya aittir, burada öğrenilmez"
)
BASELINE_PERSISTENCE = "none"
SYNTHETIC_LABEL = "SENTETİK VERİ - pilot iletişim/rapor akışı, gerçek kaynak değil"


def _hash01(token: str) -> float:
    """Deterministic pseudo-uniform value in ``[0, 1)`` from a stable hash.

    ``hashlib`` (not ``hash()``) so the synthetic flow is reproducible across
    processes and runs - the baseline must not drift with PYTHONHASHSEED.
    """
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


class SignalSource(ABC):
    """Interface every signal provider implements (synthetic + real feeds).

    A source answers "how strong was the communication / report signal in this
    cell on this day?". Swapping the synthetic pilot feed for traffic density,
    social media or sensor counts is a matter of implementing this one method -
    nothing upstream changes.
    """

    kind: str = "signal_source"
    label: str = "Sinyal kaynağı"
    synthetic: bool = False
    has_hourly: bool = False

    @abstractmethod
    def daily_signal(self, region_key: str, day: date) -> float:
        """Return the observed signal strength for one cell on one day."""

    def hourly_signal(self, region_key: str, day: date, hour: int) -> float:
        """Hour-resolution signal, defined only when ``has_hourly`` is True.

        Day-granularity sources leave this unimplemented; an hourly consumer must
        check ``has_hourly`` before calling. EM-043's seasonal source overrides it.
        """
        raise NotImplementedError(f"{self.kind} saatlik sinyal üretmez")


class SyntheticCommunicationSource(SignalSource):
    """Deterministic synthetic report flow for the pilot region.

    Each cell has a stable base level (so zones differ), a weekly rhythm
    (weekends report less) and per-day jitter. Nothing is learned or random
    across runs; the same ``(region_key, day)`` always yields the same value.
    """

    kind = DEFAULT_SOURCE_KIND
    label = "Sentetik iletişim/rapor akışı"
    synthetic = True

    def daily_signal(self, region_key: str, day: date) -> float:
        base = 80.0 + _hash01(f"base:{region_key}") * 160.0
        weekend = 0.62 if day.weekday() >= 5 else 1.0
        jitter = 0.85 + _hash01(f"noise:{region_key}:{day.isoformat()}") * 0.30
        return round(base * weekend * jitter, 2)


# Implemented sources keyed by kind. Real feeds land here once their adapters
# exist; the kinds below are declared so the abstraction is visible but they are
# not implemented (and never faked as if they were).
SIGNAL_SOURCES: dict[str, SignalSource] = {
    SyntheticCommunicationSource.kind: SyntheticCommunicationSource(),
}
PLANNED_SOURCE_KINDS: tuple[str, ...] = (
    "traffic_density",
    "social_media",
    "ground_sensor",
)


class SignalBaselineError(ValueError):
    """Raised for an invalid baseline request (unknown source, bad date)."""


@dataclass(frozen=True)
class MonitorCell:
    """One coarse monitoring cell (bölge/hücre) of the pilot lattice."""

    region_key: str
    name: str
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    center_lat: float
    center_lon: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "region_key": self.region_key,
            "name": self.name,
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
            "center_lat": self.center_lat,
            "center_lon": self.center_lon,
        }


def _window_days(settings: Any, override: Optional[int] = None) -> int:
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


def _grid_dims(settings: Any) -> tuple[int, int]:
    rows = int(getattr(settings, "SIGNAL_BASELINE_CELL_ROWS", DEFAULT_CELL_ROWS))
    cols = int(getattr(settings, "SIGNAL_BASELINE_CELL_COLS", DEFAULT_CELL_COLS))
    return max(1, rows), max(1, cols)


def _max_cells(settings: Any) -> int:
    return int(getattr(settings, "SIGNAL_BASELINE_MAX_CELLS", DEFAULT_MAX_CELLS))


def _pilot_bbox(settings: Any) -> tuple[float, float, float, float]:
    min_lat = float(getattr(settings, "SIGNAL_PILOT_MIN_LAT", DEFAULT_MIN_LAT))
    max_lat = float(getattr(settings, "SIGNAL_PILOT_MAX_LAT", DEFAULT_MAX_LAT))
    min_lon = float(getattr(settings, "SIGNAL_PILOT_MIN_LON", DEFAULT_MIN_LON))
    max_lon = float(getattr(settings, "SIGNAL_PILOT_MAX_LON", DEFAULT_MAX_LON))
    return min_lat, max_lat, min_lon, max_lon


def resolve_source(kind: Optional[str], settings: Any) -> SignalSource:
    """Pick an implemented source by kind; default is the synthetic pilot feed."""
    chosen = kind or str(
        getattr(settings, "SIGNAL_BASELINE_DEFAULT_SOURCE", DEFAULT_SOURCE_KIND)
    )
    chosen = chosen.strip().lower()
    source = SIGNAL_SOURCES.get(chosen)
    if source is None:
        raise SignalBaselineError(
            f"bilinmeyen sinyal kaynağı: {chosen}; kullanılabilir: "
            f"{', '.join(available_source_kinds())}"
        )
    return source


def available_source_kinds() -> list[str]:
    """The kinds that actually produce a signal today (synthetic pilot)."""
    return sorted(SIGNAL_SOURCES)


def monitoring_cells(settings: Any = None) -> list[MonitorCell]:
    """Coarse rows x cols lattice over the pilot bbox - the monitored cells."""
    min_lat, max_lat, min_lon, max_lon = _pilot_bbox(settings or _NullSettings())
    rows, cols = _grid_dims(settings)
    cap = _max_cells(settings)
    lat_step = (max_lat - min_lat) / rows
    lon_step = (max_lon - min_lon) / cols

    cells: list[MonitorCell] = []
    for r in range(rows):
        for c in range(cols):
            lo_lat = round(min_lat + r * lat_step, 5)
            hi_lat = round(lo_lat + lat_step, 5)
            lo_lon = round(min_lon + c * lon_step, 5)
            hi_lon = round(lo_lon + lon_step, 5)
            key = f"SB-R{r + 1}C{c + 1}"
            cells.append(
                MonitorCell(
                    region_key=key,
                    name=f"Hücre R{r + 1}-C{c + 1}",
                    min_lat=lo_lat,
                    max_lat=hi_lat,
                    min_lon=lo_lon,
                    max_lon=hi_lon,
                    center_lat=round((lo_lat + hi_lat) / 2.0, 5),
                    center_lon=round((lo_lon + hi_lon) / 2.0, 5),
                )
            )
    return cells[:cap]


class _NullSettings:
    """Sentinel so ``monitoring_cells()`` works with no settings supplied."""


def compute_cell_baseline(
    cell: MonitorCell,
    source: SignalSource,
    as_of: date,
    window_days: int,
    sensitivity_z: float,
) -> dict[str, Any]:
    """Learn the ``window_days`` normal for one cell and score the latest day.

    The baseline window is the ``window_days`` days *ending the day before*
    ``as_of``; ``as_of`` itself is the reading compared against that learned
    normal (never part of it), which is why its z-score can flag an unusually
    quiet day.
    """
    days = [as_of - timedelta(days=offset) for offset in range(window_days, 0, -1)]
    obs = [source.daily_signal(cell.region_key, d) for d in days]
    count = len(obs)
    mean = sum(obs) / count
    variance = sum((x - mean) ** 2 for x in obs) / count
    std = math.sqrt(variance)
    ordered = sorted(obs)
    mid = count // 2
    median = ordered[mid] if count % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0

    current = source.daily_signal(cell.region_key, as_of)
    deviation = current - mean
    z_score = round(deviation / std, 3) if std > 0 else 0.0
    silence_ratio = round(current / mean, 3) if mean > 0 else 0.0
    candidate_silent = bool(std > 0 and mean > 0 and z_score <= -sensitivity_z)

    payload = cell.as_dict()
    payload.update(
        {
            "source_kind": source.kind,
            "window_days": window_days,
            "window_start": days[0].isoformat(),
            "window_end": days[-1].isoformat(),
            "as_of": as_of.isoformat(),
            "observation_count": count,
            "baseline_mean": round(mean, 3),
            "baseline_std": round(std, 3),
            "baseline_median": round(median, 3),
            "baseline_min": round(min(obs), 3),
            "baseline_max": round(max(obs), 3),
            "latest_value": round(current, 3),
            "deviation": round(deviation, 3),
            "z_score": z_score,
            "silence_ratio": silence_ratio,
            "candidate_silent": candidate_silent,
            "synthetic": bool(source.synthetic),
        }
    )
    if source.synthetic:
        payload["synthetic_label"] = SYNTHETIC_LABEL
    return payload


def baseline_report(
    settings: Any,
    *,
    source: Optional[str] = None,
    as_of: Optional[date] = None,
    window_days: Optional[int] = None,
    region_key: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Per-cell 30-day baselines, most-suspicious-quiet first.

    ``region_key`` narrows to a single cell (an unknown key yields an empty
    listing rather than an error, mirroring the panel-filter convention). The
    list is ordered by ``candidate_silent`` then ascending ``z_score`` so the
    quietest-versus-normal cells sit at the top.
    """
    resolved = resolve_source(source, settings)
    window = _window_days(settings, window_days)
    sensitivity = _sensitivity_z(settings)
    stamp = as_of or date.today()

    cells = monitoring_cells(settings)
    requested = region_key.strip() if region_key else None
    if requested:
        cells = [c for c in cells if c.region_key == requested]

    rows = [
        compute_cell_baseline(cell, resolved, stamp, window, sensitivity)
        for cell in cells
    ]
    rows.sort(key=lambda r: (not r["candidate_silent"], r["z_score"], r["region_key"]))

    page_limit = limit if limit is not None else len(rows)
    page_limit = max(0, min(int(page_limit), len(rows)))
    shown = rows[:page_limit] if limit is not None else rows

    silent_count = sum(1 for r in rows if r["candidate_silent"])
    return {
        "panel": "signal_baseline",
        "source_kind": resolved.kind,
        "source_label": resolved.label,
        "as_of": stamp.isoformat(),
        "window_days": window,
        "sensitivity_z": sensitivity,
        "requested_region": requested,
        "cell_count": len(rows),
        "candidate_silent_count": silent_count,
        "cells": shown,
        "attribution": BASELINE_ATTRIBUTION,
        "persistence": BASELINE_PERSISTENCE,
        "synthetic": bool(resolved.synthetic),
        "synthetic_label": SYNTHETIC_LABEL if resolved.synthetic else None,
    }


def baseline_cell(
    settings: Any,
    region_key: str,
    *,
    source: Optional[str] = None,
    as_of: Optional[date] = None,
    window_days: Optional[int] = None,
) -> dict[str, Any]:
    """Baseline for one cell by key. Raises for an unknown ``region_key``."""
    resolved = resolve_source(source, settings)
    window = _window_days(settings, window_days)
    sensitivity = _sensitivity_z(settings)
    stamp = as_of or date.today()
    wanted = region_key.strip()
    for cell in monitoring_cells(settings):
        if cell.region_key == wanted:
            return compute_cell_baseline(cell, resolved, stamp, window, sensitivity)
    raise SignalBaselineError(f"bilinmeyen hücre anahtarı: {wanted}")


def baseline_config(settings: Any = None) -> dict[str, Any]:
    """The catalogues and bounds the panel and integrators share."""
    cfg_settings = settings if settings is not None else _NullSettings()
    min_lat, max_lat, min_lon, max_lon = _pilot_bbox(cfg_settings)
    rows, cols = _grid_dims(cfg_settings)
    return {
        "sources": {
            "available": available_source_kinds(),
            "planned": list(PLANNED_SOURCE_KINDS),
            "default": str(
                getattr(
                    cfg_settings, "SIGNAL_BASELINE_DEFAULT_SOURCE", DEFAULT_SOURCE_KIND
                )
            ),
        },
        "window_days": {
            "default": int(
                getattr(
                    cfg_settings, "SIGNAL_BASELINE_WINDOW_DAYS", DEFAULT_WINDOW_DAYS
                )
            ),
            "min": MIN_WINDOW_DAYS,
            "max": MAX_WINDOW_DAYS,
        },
        "grid": {
            "rows": rows,
            "cols": cols,
            "cell_count": min(rows * cols, _max_cells(cfg_settings)),
            "bbox": {
                "min_lat": min_lat,
                "max_lat": max_lat,
                "min_lon": min_lon,
                "max_lon": max_lon,
            },
        },
        "sensitivity_z": _sensitivity_z(cfg_settings),
        "attribution": BASELINE_ATTRIBUTION,
        "persistence": BASELINE_PERSISTENCE,
        "synthetic": True,
        "synthetic_label": SYNTHETIC_LABEL,
    }


__all__ = [
    "BASELINE_ATTRIBUTION",
    "BASELINE_PERSISTENCE",
    "PLANNED_SOURCE_KINDS",
    "SIGNAL_SOURCES",
    "SignalBaselineError",
    "SignalSource",
    "SyntheticCommunicationSource",
    "available_source_kinds",
    "baseline_cell",
    "baseline_config",
    "baseline_report",
    "compute_cell_baseline",
    "monitoring_cells",
    "resolve_source",
]
