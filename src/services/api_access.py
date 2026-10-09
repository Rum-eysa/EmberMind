"""External-client API-key authorization + rate limiting (EM-092, Epic E9).

A system administrator wants external integrations to be authorized with an API
key and throttled, so the platform cannot be abused or accidentally hammered.
This module is the pure decision layer:

* a small set of accepted API keys comes from settings (never stored in the
  database, never returned by the config endpoint);
* requests without a valid key are ``unauthorized`` (HTTP ``401``);
* each authenticated client gets an independent fixed-window counter; once it
  crosses the per-window budget the request is ``rate_limited`` (HTTP ``429``)
  with a ``Retry-After`` telling the client when the next window opens;
* enforcement is only active when it is switched on *and* at least one key is
  configured - otherwise the surface is deliberately reported as ``disabled``
  so local development is not locked out and we never fake a security control
  that is not actually guarding anything.

Persistence is ``none``: the window counters live only in process memory for the
lifetime of the running app. No table, no migration.
"""

import hashlib
import time
from typing import Any

AUTH_PERSISTENCE = "none"

# The header an external client must send its key in. Kept lowercase because ASGI
# normalizes incoming header names to lowercase; FastAPI matches case-insensitively.
API_KEY_HEADER = "x-api-key"

DEFAULT_RATE_LIMIT_REQUESTS = 30
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60.0

# Human-readable status tokens returned by :func:`authorize`.
STATUS_ALLOWED = "allowed"
STATUS_UNAUTHORIZED = "unauthorized"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_DISABLED = "disabled"


def _raw_keys(settings: Any) -> list[str]:
    """Accepted API keys as configured by settings.

    ``API_ACCESS_KEYS`` is a comma-separated string; a list/tuple/set is also
    accepted for programmatic settings. Empty / whitespace-only entries are
    dropped so a trailing comma cannot create an anonymous "empty key" client.
    """
    value = getattr(settings, "API_ACCESS_KEYS", "")
    if isinstance(value, (list, tuple, set, frozenset)):
        parts = [str(item) for item in value]
    else:
        parts = str(value).split(",")
    return [part.strip() for part in parts if part.strip()]


def accepted_keys(settings: Any) -> frozenset[str]:
    """The frozenset of currently accepted API keys (config layer, no secrets)."""
    return frozenset(_raw_keys(settings))


def enforcement_enabled(settings: Any) -> bool:
    """Whether the switch is on (independent of whether any key is configured)."""
    return bool(getattr(settings, "API_ACCESS_ENABLED", False))


def auth_required(settings: Any) -> bool:
    """Enforcement is active only when switched on *and* at least one key exists."""
    return enforcement_enabled(settings) and bool(accepted_keys(settings))


def rate_limit(settings: Any) -> int:
    """Requests allowed per client per window (floored at 1)."""
    raw = getattr(settings, "API_ACCESS_RATE_LIMIT_REQUESTS", None)
    if raw is None:
        return DEFAULT_RATE_LIMIT_REQUESTS
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_RATE_LIMIT_REQUESTS
    return max(1, limit)


def window_seconds(settings: Any) -> float:
    """Fixed-window length in seconds (floored at 1.0 so buckets are meaningful)."""
    raw = getattr(settings, "API_ACCESS_RATE_LIMIT_WINDOW_SECONDS", None)
    if raw is None:
        return DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    try:
        window = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    return max(1.0, window)


class RateLimiter:
    """Fixed-window request counter, bucketed per client identity.

    A window is ``floor(now / window)``; each ``(client_id, window_index)`` keeps
    one counter. Counters from stale windows are pruned on every call so the map
    stays bounded to roughly the active window without a background sweeper.
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = {}

    def check(
        self, client_id: str, limit: int, window: float, now: float
    ) -> dict[str, Any]:
        """Count one hit for ``client_id`` and report the resulting budget."""
        window_index = int(now // window) if window > 0 else 0
        reset_at = (window_index + 1) * window
        # Prune anything that is not the current window to keep memory bounded.
        for stale in [key for key in self._counts if key[1] != window_index]:
            del self._counts[stale]
        bucket = (client_id, window_index)
        used = self._counts.get(bucket, 0) + 1
        self._counts[bucket] = used
        allowed = used <= limit
        return {
            "allowed": allowed,
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used),
            "reset_at": reset_at,
            "retry_after": 0.0 if allowed else max(0.0, reset_at - now),
        }

    def reset(self) -> None:
        """Drop every counter (used by tests and admin tooling)."""
        self._counts.clear()


def authorize(
    api_key: str | None,
    client_id: str,
    settings: Any,
    limiter: RateLimiter,
    now: float | None = None,
) -> dict[str, Any]:
    """Return an access decision for one request.

    The route turns the ``status`` field into an HTTP outcome:
    ``unauthorized`` -> 401, ``rate_limited`` -> 429, ``allowed`` / ``disabled``
    -> 200. The decision never echoes the raw key back, only whether it matched.
    """
    current = time.time() if now is None else now
    enforced = auth_required(settings)
    if not enforced:
        return {
            "status": STATUS_DISABLED,
            "enforced": False,
            "authenticated": False,
            "client_id": client_id,
        }
    supplied = (api_key or "").strip()
    if supplied not in accepted_keys(settings):
        return {
            "status": STATUS_UNAUTHORIZED,
            "enforced": True,
            "authenticated": False,
            "client_id": client_id,
        }
    # Bucket per authenticated key so each external client has its own budget.
    bucket_id = f"key:{_key_fingerprint(supplied)}"
    decision = limiter.check(
        bucket_id, rate_limit(settings), window_seconds(settings), current
    )
    status = STATUS_ALLOWED if decision["allowed"] else STATUS_RATE_LIMITED
    return {
        "status": status,
        "enforced": True,
        "authenticated": True,
        "client_id": bucket_id,
        **decision,
    }


def _key_fingerprint(api_key: str) -> str:
    """A short, non-reversible label for a key - safe to log (no secret round-trip)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def access_config(settings: Any) -> dict[str, Any]:
    """Admin-facing description of the access surface. Never returns raw keys."""
    return {
        "enabled": enforcement_enabled(settings),
        "enforced": auth_required(settings),
        "header": API_KEY_HEADER,
        "configured_key_count": len(accepted_keys(settings)),
        "rate_limit_requests": rate_limit(settings),
        "rate_limit_window_seconds": window_seconds(settings),
        "defaults": {
            "rate_limit_requests": DEFAULT_RATE_LIMIT_REQUESTS,
            "rate_limit_window_seconds": DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        },
        "editable_settings": [
            "API_ACCESS_ENABLED",
            "API_ACCESS_KEYS",
            "API_ACCESS_RATE_LIMIT_REQUESTS",
            "API_ACCESS_RATE_LIMIT_WINDOW_SECONDS",
        ],
        "persistence": AUTH_PERSISTENCE,
        "attribution": "API anahtarı ve hız sınırlama: EM-092",
    }
