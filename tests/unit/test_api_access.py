"""EM-092 external-client API-key + rate-limit tests (Epic E9).

A system administrator wants external integrations authorized with an API key and
throttled so the platform cannot be abused. These tests pin the pure decision
layer (disabled / unauthorized / allowed / rate-limited, per-client windowed
budgets, window rollover, key parsing, floors), the admin config shape (never
leaks a key) and the guarded HTTP endpoint (401 without a valid key, 200 with
the standard ``X-RateLimit-*`` headers for an authenticated call).
"""
from src.services.api_access import (
    API_KEY_HEADER,
    AUTH_PERSISTENCE,
    DEFAULT_RATE_LIMIT_REQUESTS,
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    STATUS_ALLOWED,
    STATUS_DISABLED,
    STATUS_RATE_LIMITED,
    STATUS_UNAUTHORIZED,
    RateLimiter,
    access_config,
    auth_required,
    authorize,
    window_seconds,
)

TEST_KEY = "a-valid-external-key"


class _Settings:
    """Minimal settings stub; the service defaults every knob via ``getattr``."""

    def __init__(self, **overrides: object) -> None:
        for key, value in overrides.items():
            setattr(self, key, value)


def _enforced(**overrides: object) -> _Settings:
    base = {"API_ACCESS_ENABLED": True, "API_ACCESS_KEYS": TEST_KEY}
    base.update(overrides)
    return _Settings(**base)


# --------------------------------------------------------------------------- #
# Enforcement gate + key parsing
# --------------------------------------------------------------------------- #
def test_disabled_when_switch_off():
    assert auth_required(_Settings(API_ACCESS_KEYS=TEST_KEY)) is False


def test_disabled_when_no_keys_configured():
    assert auth_required(_Settings(API_ACCESS_ENABLED=True)) is False


def test_enforced_when_switch_on_and_key_present():
    assert auth_required(_enforced()) is True


def test_trailing_comma_and_whitespace_do_not_create_empty_key():
    settings = _Settings(API_ACCESS_ENABLED=True, API_ACCESS_KEYS=f" , {TEST_KEY} , ")
    assert auth_required(settings) is True
    decision = authorize(" ", "1.2.3.4", settings, RateLimiter(), now=0.0)
    assert decision["status"] == STATUS_UNAUTHORIZED


# --------------------------------------------------------------------------- #
# authorize() decision matrix
# --------------------------------------------------------------------------- #
def test_authorize_disabled_reports_open_but_unauthenticated():
    decision = authorize(TEST_KEY, "1.2.3.4", _Settings(), RateLimiter(), now=0.0)
    assert decision["status"] == STATUS_DISABLED
    assert decision["enforced"] is False
    assert decision["authenticated"] is False


def test_authorize_missing_key_is_unauthorized():
    decision = authorize(None, "1.2.3.4", _enforced(), RateLimiter(), now=0.0)
    assert decision["status"] == STATUS_UNAUTHORIZED
    assert decision["authenticated"] is False


def test_authorize_wrong_key_is_unauthorized():
    decision = authorize("nope", "1.2.3.4", _enforced(), RateLimiter(), now=0.0)
    assert decision["status"] == STATUS_UNAUTHORIZED


def test_authorize_valid_key_allowed_with_budget():
    decision = authorize(TEST_KEY, "1.2.3.4", _enforced(), RateLimiter(), now=0.0)
    assert decision["status"] == STATUS_ALLOWED
    assert decision["authenticated"] is True
    assert decision["limit"] == DEFAULT_RATE_LIMIT_REQUESTS
    assert decision["remaining"] == DEFAULT_RATE_LIMIT_REQUESTS - 1


def test_authorize_never_echoes_raw_key():
    decision = authorize(TEST_KEY, "1.2.3.4", _enforced(), RateLimiter(), now=0.0)
    assert TEST_KEY not in str(decision)
    assert decision["client_id"].startswith("key:")


def test_authorize_rate_limits_after_budget_exhausted():
    settings = _enforced(API_ACCESS_RATE_LIMIT_REQUESTS=2)
    limiter = RateLimiter()
    assert (
        authorize(TEST_KEY, "c", settings, limiter, now=0.0)["status"] == STATUS_ALLOWED
    )
    assert (
        authorize(TEST_KEY, "c", settings, limiter, now=0.0)["status"] == STATUS_ALLOWED
    )
    blocked = authorize(TEST_KEY, "c", settings, limiter, now=0.0)
    assert blocked["status"] == STATUS_RATE_LIMITED
    assert blocked["remaining"] == 0
    assert blocked["retry_after"] > 0.0


def test_rate_limit_resets_in_next_window():
    settings = _enforced(
        API_ACCESS_RATE_LIMIT_REQUESTS=1, API_ACCESS_RATE_LIMIT_WINDOW_SECONDS=60
    )
    limiter = RateLimiter()
    assert (
        authorize(TEST_KEY, "c", settings, limiter, now=1.0)["status"] == STATUS_ALLOWED
    )
    # same window -> blocked
    assert (
        authorize(TEST_KEY, "c", settings, limiter, now=10.0)["status"]
        == STATUS_RATE_LIMITED
    )
    # next window (>= 60) -> allowed again
    assert (
        authorize(TEST_KEY, "c", settings, limiter, now=61.0)["status"]
        == STATUS_ALLOWED
    )


def test_buckets_are_independent_per_key():
    settings = _enforced(
        API_ACCESS_KEYS=f"{TEST_KEY},second-key", API_ACCESS_RATE_LIMIT_REQUESTS=1
    )
    limiter = RateLimiter()
    assert (
        authorize(TEST_KEY, "c", settings, limiter, now=0.0)["status"] == STATUS_ALLOWED
    )
    # a different key has its own fresh budget even though the first is spent
    assert (
        authorize("second-key", "c", settings, limiter, now=0.0)["status"]
        == STATUS_ALLOWED
    )
    assert (
        authorize(TEST_KEY, "c", settings, limiter, now=0.0)["status"]
        == STATUS_RATE_LIMITED
    )


# --------------------------------------------------------------------------- #
# RateLimiter + floors
# --------------------------------------------------------------------------- #
def test_limiter_prunes_stale_window():
    limiter = RateLimiter()
    limiter.check("c", 5, 60.0, now=5.0)
    limiter.check("c", 5, 60.0, now=125.0)  # window 2
    # only the current window counter survives pruning
    assert list(limiter._counts) == [("c", 2)]


def test_limiter_reset_clears_counters():
    limiter = RateLimiter()
    limiter.check("c", 5, 60.0, now=0.0)
    limiter.reset()
    assert limiter._counts == {}


def test_window_floor_prevents_zero_buckets():
    assert window_seconds(_Settings(API_ACCESS_RATE_LIMIT_WINDOW_SECONDS=0)) == 1.0
    assert window_seconds(_Settings(API_ACCESS_RATE_LIMIT_WINDOW_SECONDS="bad")) == (
        DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    )


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_config_shape_and_no_key_leak():
    config = access_config(_enforced())
    assert config["enabled"] is True
    assert config["enforced"] is True
    assert config["header"] == API_KEY_HEADER
    assert config["configured_key_count"] == 1
    assert config["persistence"] == AUTH_PERSISTENCE
    assert "EM-092" in config["attribution"]
    assert TEST_KEY not in str(config)
    assert "API_ACCESS_KEYS" in config["editable_settings"]


def test_config_defaults_are_exposed():
    config = access_config(_Settings())
    assert config["defaults"]["rate_limit_requests"] == DEFAULT_RATE_LIMIT_REQUESTS
    assert config["enforced"] is False


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_requires_valid_key(client):
    missing = client.get("/api/v1/external/status")
    assert missing.status_code == 401
    wrong = client.get("/api/v1/external/status", headers={API_KEY_HEADER: "bogus"})
    assert wrong.status_code == 401


def test_endpoint_allows_valid_key_with_rate_headers(client):
    resp = client.get(
        "/api/v1/external/status", headers={API_KEY_HEADER: "test-external-key-alpha"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == STATUS_ALLOWED
    assert body["enforced"] is True
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers


def test_endpoint_config_never_leaks_keys(client):
    resp = client.get("/api/v1/api-access/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enforced"] is True
    assert body["configured_key_count"] == 2
    assert "test-external-key-alpha" not in str(body)
