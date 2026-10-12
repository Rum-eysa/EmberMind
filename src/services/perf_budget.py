"""Recompute performance budget with automatic scale-down (EM-060, Epic E6).

The operator's promise is that a spread / what-if recomputation finishes
within ten seconds so a decision is not blocked during a crisis. A single
fast run proves nothing; what matters is the *tail*. This service keeps a
rolling window of the most recent recompute latencies (:class:`RecomputeLa
tencySample`) and grades their **p95** against the configured budget. When the
p95 is over budget the run is flagged ``breached`` and, if the scale-down is
enabled, every subsequent recomputation is automatically dropped to a
**coarse resolution** — fewer polygon vertices and a trimmed horizon set — so
the engine gets back under the target on its own.

Entering a breach pushes one ``alert`` onto the live change feed (EM-090); the
warning is edge-triggered (it only fires on the within-budget -> over-budget
transition), so a sustained breach does not spam the operator. Everything else
about a recomputation stays exactly as EM-055 / EM-022 designed it; this module
only observes and throttles.
"""
from math import floor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.perf_budget import RecomputeLatencySample
from src.services.live import record_update
from src.utils.timeutils import to_utc_iso, utc_now

PERF_BUDGET_PANEL = "perf_budget"
PERF_BUDGET_ATTRIBUTION = (
    "Performans bütçesi: yeniden hesaplama p95 gecikmesi / 10 sn hedef (EM-060)"
)
PERF_BUDGET_ALERT_SOURCE = "perf_budget"
RESOLUTION_FINE = "fine"
RESOLUTION_COARSE = "coarse"
# Fallbacks used only when a settings object omits the keys entirely (tests may
# pass a lightweight namespace). Real config always provides these values.
_DEFAULT_TARGET_SECONDS = 10.0
_DEFAULT_WINDOW = 50
_DEFAULT_MIN_SAMPLES = 5
_DEFAULT_COARSE_VERTICES = 12
_DEFAULT_COARSE_HORIZONS = [30, 120]


def budget_target_seconds(settings: Any) -> float:
    """p95 latency budget in seconds the recomputes are graded against."""
    try:
        target = float(
            getattr(settings, "PERF_BUDGET_TARGET_SECONDS", _DEFAULT_TARGET_SECONDS)
        )
    except (TypeError, ValueError):
        return _DEFAULT_TARGET_SECONDS
    return target if target > 0 else _DEFAULT_TARGET_SECONDS


def window_size(settings: Any) -> int:
    """Number of most-recent samples the p95 is measured over."""
    try:
        window = int(getattr(settings, "PERF_BUDGET_WINDOW", _DEFAULT_WINDOW))
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW
    return window if window > 0 else _DEFAULT_WINDOW


def min_samples(settings: Any) -> int:
    """Minimum samples before a breach may be declared (anti flapping)."""
    try:
        minimum = int(
            getattr(settings, "PERF_BUDGET_MIN_SAMPLES", _DEFAULT_MIN_SAMPLES)
        )
    except (TypeError, ValueError):
        return _DEFAULT_MIN_SAMPLES
    return minimum if minimum > 0 else 1


def coarse_vertices(settings: Any) -> int:
    """Polygon vertices used once the recompute is scaled down to coarse."""
    try:
        return int(
            getattr(settings, "PERF_BUDGET_COARSE_VERTICES", _DEFAULT_COARSE_VERTICES)
        )
    except (TypeError, ValueError):
        return _DEFAULT_COARSE_VERTICES


def coarse_horizons(settings: Any) -> list[int]:
    """Horizon set used once the recompute is scaled down to coarse."""
    raw = getattr(settings, "PERF_BUDGET_COARSE_HORIZONS", _DEFAULT_COARSE_HORIZONS)
    try:
        cleaned = sorted({int(h) for h in raw if int(h) > 0})
    except (TypeError, ValueError):
        return list(_DEFAULT_COARSE_HORIZONS)
    return cleaned or list(_DEFAULT_COARSE_HORIZONS)


def scale_down_enabled(settings: Any) -> bool:
    """Whether the automatic coarse-resolution throttle is switched on."""
    return bool(getattr(settings, "PERF_BUDGET_ENABLED", True))


def _alerts_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "PERF_BUDGET_ALERTS_ENABLED", True))


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation ``pct``-th percentile of ``values`` (None if empty).

    Matches the common (numpy default) definition: rank ``= (n-1) * pct`` on
    the ascending-sorted list, interpolated between the two neighbours.
    """
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (float(pct) / 100.0)
    lower = int(floor(rank))
    upper = min(lower + 1, len(ordered) - 1)
    if upper == lower:
        return ordered[lower]
    fraction = rank - lower
    return round(ordered[lower] + fraction * (ordered[upper] - ordered[lower]), 3)


def _recent_samples(session: Session, window: int) -> list[RecomputeLatencySample]:
    """The ``window`` most recent latency samples, oldest first."""
    rows = list(
        session.scalars(
            select(RecomputeLatencySample)
            .order_by(RecomputeLatencySample.id.desc())
            .limit(window)
        ).all()
    )
    return list(reversed(rows))


def _coerce_resolution(resolution: Any) -> str:
    value = str(resolution or RESOLUTION_FINE).strip().lower()
    return RESOLUTION_COARSE if value == RESOLUTION_COARSE else RESOLUTION_FINE


def _evaluate(
    latencies: list[float], target_seconds: float, minimum: int
) -> dict[str, Any]:
    """p95, breach edge and scale-down flag for one window snapshot."""
    p95 = percentile(latencies, 95.0)
    target_ms = target_seconds * 1000.0
    samples = len(latencies)
    decided = samples >= minimum and p95 is not None
    breach = bool(decided and p95 is not None and p95 > target_ms)
    return {
        "samples": samples,
        "p95_ms": p95,
        "target_ms": round(target_ms, 3),
        "min_samples_met": samples >= minimum,
        "breached": breach,
        "within_budget": (not breach) if decided else None,
    }


def budget_status(session: Session, settings: Any) -> dict[str, Any]:
    """Rolling p95 recompute-latency read-out against the EM-060 budget."""
    target_seconds = budget_target_seconds(settings)
    snapshot = _evaluate(
        [
            float(row.latency_ms)
            for row in _recent_samples(session, window_size(settings))
        ],
        target_seconds,
        min_samples(settings),
    )
    enabled = scale_down_enabled(settings)
    scale_down_active = snapshot["breached"] and enabled
    return {
        "panel": PERF_BUDGET_PANEL,
        "generated_at": to_utc_iso(utc_now()),
        "attribution": PERF_BUDGET_ATTRIBUTION,
        "target_seconds": target_seconds,
        "window": window_size(settings),
        "min_samples": min_samples(settings),
        "scale_down_enabled": enabled,
        "samples": snapshot["samples"],
        "p95_ms": snapshot["p95_ms"],
        "target_ms": snapshot["target_ms"],
        "min_samples_met": snapshot["min_samples_met"],
        "breached": snapshot["breached"],
        "within_budget": snapshot["within_budget"],
        "scale_down_active": scale_down_active,
        "recommended_resolution": RESOLUTION_COARSE
        if scale_down_active
        else RESOLUTION_FINE,
        "coarse": {
            "vertices": coarse_vertices(settings),
            "horizon_minutes": coarse_horizons(settings),
        },
    }


def next_resolution(session: Session, settings: Any) -> str:
    """Resolution the *next* recompute should run at given the current p95."""
    return (
        RESOLUTION_COARSE
        if budget_status(session, settings)["scale_down_active"]
        else RESOLUTION_FINE
    )


class _CoarseSettings:
    """Delegate to a real settings object, forcing a coarse recompute.

    Only the two knobs that drive recompute cost are overridden; every other
    attribute (fuel model, exposure reference, the target itself) passes
    through untouched, so a scaled-down what-if is otherwise identical to a
    full-resolution one.
    """

    def __init__(self, base: Any, vertices: int, horizons: list[int]) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_vertices", vertices)
        object.__setattr__(self, "_horizons", horizons)

    def __getattr__(self, name: str) -> Any:
        if name == "SPREAD_POLYGON_VERTICES":
            return object.__getattribute__(self, "_vertices")
        if name == "SPREAD_HORIZON_MINUTES":
            return object.__getattribute__(self, "_horizons")
        return getattr(object.__getattribute__(self, "_base"), name)


def with_coarse_resolution(settings: Any) -> Any:
    """Wrap ``settings`` so a recompute runs at the coarse budget resolution."""
    return _CoarseSettings(
        settings, coarse_vertices(settings), coarse_horizons(settings)
    )


def resolve_recompute_settings(session: Session, settings: Any) -> tuple[Any, str]:
    """(settings_to_use, resolution) the next recompute should run with.

    Single call sites use: consult the live p95 budget, and when it is over
    target and the throttle is enabled, hand back a coarse-resolved settings
    wrapper plus the ``"coarse"`` marker to record on the resulting sample.
    """
    if next_resolution(session, settings) == RESOLUTION_COARSE:
        return with_coarse_resolution(settings), RESOLUTION_COARSE
    return settings, RESOLUTION_FINE


def record_recompute_latency(
    session: Session,
    settings: Any,
    latency_ms: float,
    source: str = "recompute",
    resolution: str = RESOLUTION_FINE,
) -> dict[str, Any]:
    """Append one recompute timing and return the post-insert budget status.

    A warning ``alert`` is pushed onto the live feed on the within-budget ->
    over-budget edge only (not for every subsequent breaching sample), so the
    operator hears about a new slowdown but is not spammed while it persists.
    """
    target_seconds = budget_target_seconds(settings)
    window = window_size(settings)
    minimum = min_samples(settings)
    latencies = [float(row.latency_ms) for row in _recent_samples(session, window)]

    row = RecomputeLatencySample(
        source=str(source)[:64],
        latency_ms=float(latency_ms),
        target_seconds=float(target_seconds),
        resolution=_coerce_resolution(resolution),
    )
    session.add(row)
    session.flush()

    latencies.append(float(latency_ms))
    latencies = latencies[-window:]
    snapshot = _evaluate(latencies, target_seconds, minimum)
    row.breached = snapshot["breached"]  # type: ignore[assignment]
    session.flush()

    was_breached = _previous_breached(session, int(row.id), minimum)
    if snapshot["breached"] and not was_breached and _alerts_enabled(settings):
        record_update(
            session,
            settings,
            "alert",
            title="Yeniden hesaplama bütçesi aşıldı",
            message=(
                f"p95 {snapshot['p95_ms']} ms > {snapshot['target_ms']} ms hedefi"
                + (
                    " — otomatik kaba çözünürlüğe geçildi"
                    if scale_down_enabled(settings)
                    else ""
                )
            ),
            payload={
                "p95_ms": snapshot["p95_ms"],
                "target_ms": snapshot["target_ms"],
                "samples": snapshot["samples"],
                "scale_down_active": snapshot["breached"]
                and scale_down_enabled(settings),
            },
            source=PERF_BUDGET_ALERT_SOURCE,
        )
    return budget_status(session, settings)


def _previous_breached(session: Session, before_id: int, minimum: int) -> bool:
    """Whether the newest sample older than ``before_id`` was already breaching.

    With fewer than ``minimum`` earlier samples there is no established budget
    state, so the edge is treated as "was not breaching" (no alert baseline).
    """
    rows = list(
        session.scalars(
            select(RecomputeLatencySample)
            .where(RecomputeLatencySample.id < before_id)
            .order_by(RecomputeLatencySample.id.desc())
            .limit(minimum)
        ).all()
    )
    if len(rows) < minimum:
        return False
    return bool(rows[0].breached)


__all__ = [
    "PERF_BUDGET_ATTRIBUTION",
    "PERF_BUDGET_PANEL",
    "RESOLUTION_COARSE",
    "RESOLUTION_FINE",
    "budget_status",
    "budget_target_seconds",
    "coarse_horizons",
    "coarse_vertices",
    "next_resolution",
    "percentile",
    "record_recompute_latency",
    "resolve_recompute_settings",
    "with_coarse_resolution",
]
