"""EM-022 input-layer cache shared by the spread engine.

The spread pipeline reads the same pilot data points over and over: every
prediction resolves nearest weather/topography/land-cover rows, the EM-016
fuel-transition polygon samples the land-cover layer at up to 72 vertices
per horizon, and each barrier-aware run reloads the active barrier set.
This module gives those reads a small per-session TTL cache so a
recomputation stays well inside the 10-second operator target.

Design notes:

* Entries live in a ``WeakKeyDictionary`` keyed by the SQLAlchemy session,
  so cached values can never outlive (or leak across) sessions and test
  fixtures stay isolated.
* Only plain snapshots (``RowView`` / decoded dicts) are cached, never ORM
  instances, so detached-instance errors are impossible.
* Coordinates are quantized to a grid (default ~111 m) before lookup;
  points inside one cell share the cached nearest-row answer.
* Freshness is TTL-based (default 120 s); barrier registration/deletion
  invalidates explicitly because it is rare and cheap.
"""
import threading
import time
from typing import Any, Callable
from weakref import WeakKeyDictionary

# Cache is opt-in: settings stubs without the flag keep the scalar path.
DEFAULT_CACHE_TTL_SECONDS = 120.0
DEFAULT_CACHE_GRID_DEG = 0.001  # ~111 m quantization cell


class RowView:
    """Attribute snapshot of one data point (safe to cache after commit)."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        keys = ",".join(sorted(self.__dict__))
        return f"RowView({keys})"


def perf_enabled(settings: Any) -> bool:
    """Whether EM-022 layer caching / vectorized sampling is active."""
    return bool(getattr(settings, "SPREAD_PERF_ENABLED", False))


def cache_params(settings: Any) -> tuple[float, float]:
    """(ttl_seconds, grid_degrees) cache tuning read from settings."""
    ttl = float(
        getattr(settings, "SPREAD_PERF_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS)
    )
    grid = float(
        getattr(settings, "SPREAD_PERF_CACHE_GRID_DEG", DEFAULT_CACHE_GRID_DEG)
    )
    return max(ttl, 0.0), max(grid, 1e-9)


class LayerCache:
    """Thread-safe per-session TTL cache with hit/miss statistics."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: WeakKeyDictionary[
            Any, dict[tuple[Any, ...], tuple[float, Any]]
        ] = WeakKeyDictionary()
        self._hits = 0
        self._misses = 0
        self._invalidations = 0

    def set_clock(self, clock: Callable[[], float]) -> None:
        """Swap the time source (tests drive TTL expiry deterministically)."""
        with self._lock:
            self._clock = clock

    def get_or_load(
        self,
        session: Any,
        key: tuple[Any, ...],
        loader: Callable[[], Any],
        ttl_seconds: float,
    ) -> Any:
        """Cached value for ``key`` in this session, loaded on miss/expiry.

        A ttl of 0 disables caching (loader runs every time, counted as a
        miss) so tuning settings can switch the cache off at runtime.
        """
        if ttl_seconds <= 0:
            with self._lock:
                self._misses += 1
            return loader()
        now = self._clock()
        with self._lock:
            bucket = self._entries.get(session)
            if bucket is None:
                bucket = self._entries[session] = {}
            entry = bucket.get(key)
            if entry is not None and entry[0] > now:
                self._hits += 1
                return entry[1]
        value = loader()
        with self._lock:
            self._misses += 1
            self._entries.setdefault(session, {})[key] = (
                self._clock() + ttl_seconds,
                value,
            )
        return value

    def invalidate(self, key_prefix: tuple[Any, ...] = ()) -> int:
        """Drop entries whose key starts with ``key_prefix``; returns count."""
        dropped = 0
        with self._lock:
            self._invalidations += 1
            for bucket in list(self._entries.values()):
                for key in [k for k in bucket if k[: len(key_prefix)] == key_prefix]:
                    del bucket[key]
                    dropped += 1
        return dropped

    def reset(self) -> None:
        """Forget everything (used between tests and after bulk imports)."""
        with self._lock:
            self._entries = WeakKeyDictionary()
            self._hits = 0
            self._misses = 0
            self._invalidations = 0

    def stats(self) -> dict[str, Any]:
        """Hit/miss counters plus current entry count."""
        with self._lock:
            entries = sum(len(bucket) for bucket in self._entries.values())
            return {
                "hits": self._hits,
                "misses": self._misses,
                "invalidations": self._invalidations,
                "entries": entries,
            }


_CACHE = LayerCache()


def layer_cache() -> LayerCache:
    """The process-wide layer cache instance."""
    return _CACHE


def cached_nearest_value(
    session: Any,
    kind: str,
    latitude: float,
    longitude: float,
    loader: Callable[[], Any],
    settings: Any,
) -> Any:
    """Cache one nearest-row snapshot on a quantized coordinate grid."""
    grid = cache_params(settings)[1]
    key = (kind, round(latitude / grid), round(longitude / grid))
    return cached_value(session, key, loader, settings)


def cached_value(
    session: Any,
    key: tuple[Any, ...],
    loader: Callable[[], Any],
    settings: Any,
) -> Any:
    """Cache one arbitrary read (e.g. the active barrier list) by key."""
    ttl, _ = cache_params(settings)
    return _CACHE.get_or_load(session, key, loader, ttl)
