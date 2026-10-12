"""EM-095 API documentation + example client tests (Epic E9).

An integrator wants to try the API quickly, so the published OpenAPI schema
needs identity metadata and there must be a single, honest catalog of error
codes, the rate-limit contract and copy-pasteable example clients. These tests
pin the pure read-time projection (base-url derivation, contact email, the
error catalog, live rate-limit numbers, example-client shape) and assert the
security posture: an example never embeds a real API key - only the ``x-api-key``
header plus an environment placeholder. They also verify the endpoints answer
and that the framework still publishes the Swagger schema with the new identity.
"""
from src.services.api_access import API_KEY_HEADER
from src.services.api_docs import (
    DEFAULT_BASE_URL,
    DOCS_PERSISTENCE,
    docs_bundle,
    error_codes,
    example_clients,
    openapi_meta,
    rate_limit_docs,
)


class _Settings:
    """Minimal settings stub; the service defaults every knob via ``getattr``."""

    def __init__(self, **overrides: object) -> None:
        for key, value in overrides.items():
            setattr(self, key, value)


# --------------------------------------------------------------------------- #
# openapi_meta
# --------------------------------------------------------------------------- #
def test_openapi_meta_shape_and_defaults():
    meta = openapi_meta(_Settings())
    assert meta["title"] == "Wildfire Monitoring API"
    assert meta["version"] == "1.0.0"
    assert meta["base_url"] == DEFAULT_BASE_URL
    assert meta["docs"]["swagger_ui"] == "/docs"
    assert meta["docs"]["openapi_json"] == "/openapi.json"
    assert "url" in meta["contact"]
    assert "email" not in meta["contact"]
    assert meta["license"]["name"]
    assert meta["persistence"] == DOCS_PERSISTENCE
    assert any(tag["name"] == "external" for tag in meta["tags"])


def test_openapi_meta_base_url_trimmed():
    meta = openapi_meta(_Settings(API_DOCS_BASE_URL="https://api.example.com///"))
    assert meta["base_url"] == "https://api.example.com"


def test_openapi_meta_blank_base_url_falls_back():
    meta = openapi_meta(_Settings(API_DOCS_BASE_URL="   "))
    assert meta["base_url"] == DEFAULT_BASE_URL


def test_openapi_meta_contact_email_added_when_configured():
    meta = openapi_meta(_Settings(API_DOCS_CONTACT_EMAIL="ops@example.com"))
    assert meta["contact"]["email"] == "ops@example.com"


# --------------------------------------------------------------------------- #
# error_codes
# --------------------------------------------------------------------------- #
def test_error_catalog_covers_documented_codes():
    codes = {entry["code"] for entry in error_codes()}
    for expected in (400, 401, 404, 409, 422, 429, 500, 503):
        assert expected in codes


def test_error_catalog_entries_are_wellformed():
    for entry in error_codes():
        assert entry["name"]
        assert entry["when"]


def test_error_catalog_documents_auth_and_throttle():
    catalog = {entry["code"]: entry for entry in error_codes()}
    assert API_KEY_HEADER in catalog[401]["when"]
    assert "Retry-After" in catalog[429]["when"]


def test_error_catalog_returns_copies():
    first = error_codes()
    first[0]["code"] = -1
    assert error_codes()[0]["code"] != -1


# --------------------------------------------------------------------------- #
# rate_limit_docs
# --------------------------------------------------------------------------- #
def test_rate_limit_docs_reflects_live_config():
    settings = _Settings(
        API_ACCESS_ENABLED=True,
        API_ACCESS_KEYS="key-one",
        API_ACCESS_RATE_LIMIT_REQUESTS=42,
        API_ACCESS_RATE_LIMIT_WINDOW_SECONDS=120,
    )
    doc = rate_limit_docs(settings)
    assert doc["enforced"] is True
    assert doc["header"] == API_KEY_HEADER
    assert doc["rate_limit_requests"] == 42
    assert doc["rate_limit_window_seconds"] == 120.0
    assert doc["status_codes"]["unauthorized"] == 401
    assert doc["status_codes"]["rate_limited"] == 429


def test_rate_limit_docs_when_disabled():
    doc = rate_limit_docs(_Settings())
    assert doc["enforcement_enabled"] is False
    assert doc["enforced"] is False


def test_rate_limit_docs_never_leaks_keys():
    settings = _Settings(API_ACCESS_ENABLED=True, API_ACCESS_KEYS="super-secret-key")
    assert "super-secret-key" not in str(rate_limit_docs(settings))


# --------------------------------------------------------------------------- #
# example_clients
# --------------------------------------------------------------------------- #
def test_example_clients_uses_base_url():
    examples = example_clients(_Settings(API_DOCS_BASE_URL="https://ops.example"))
    assert examples["base_url"] == "https://ops.example"
    joined = str(examples)
    assert "https://ops.example/health" in joined


def test_example_clients_has_curl_and_python():
    examples = example_clients(_Settings())
    names = {entry["name"] for entry in examples["curl"]}
    assert "health" in names
    assert "external-status-authenticated" in names
    assert "httpx" in examples["python"]


def test_example_clients_authenticated_uses_header_placeholder():
    examples = example_clients(_Settings())
    auth = next(
        c for c in examples["curl"] if c["name"] == "external-status-authenticated"
    )
    assert API_KEY_HEADER in auth["command"]
    assert "$WILDFIRE_API_KEY" in auth["command"]


def test_example_clients_never_embeds_real_key():
    settings = _Settings(API_ACCESS_KEYS="a-real-secret-key")
    payload = str(example_clients(settings))
    assert "a-real-secret-key" not in payload


# --------------------------------------------------------------------------- #
# docs_bundle
# --------------------------------------------------------------------------- #
def test_docs_bundle_shape_and_attribution():
    bundle = docs_bundle(_Settings())
    assert set(bundle) >= {"openapi", "errors", "rate_limits", "examples"}
    assert "EM-095" in bundle["attribution"]


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_docs_bundle_endpoint(client):
    resp = client.get("/api/v1/api-docs")
    assert resp.status_code == 200
    body = resp.json()
    assert "EM-095" in body["attribution"]
    # TestingConfig pins the base URL so examples are deterministic.
    assert body["examples"]["base_url"] == "http://testserver"


def test_docs_config_endpoint(client):
    resp = client.get("/api/v1/api-docs/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["license"]["name"]
    assert any(tag["name"] == "external" for tag in body["tags"])


def test_docs_errors_endpoint(client):
    resp = client.get("/api/v1/api-docs/errors")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 8
    assert any(entry["code"] == 429 for entry in body["errors"])


def test_docs_examples_endpoint_never_leaks_keys(client):
    resp = client.get("/api/v1/api-docs/examples")
    assert resp.status_code == 200
    # TestingConfig has two fixed external keys; neither may appear in examples.
    assert "test-external-key-alpha" not in str(resp.json())


def test_openapi_schema_published_with_identity(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["contact"]["name"]
    assert schema["info"]["license"]["name"]
    tag_names = {tag["name"] for tag in schema.get("tags", [])}
    assert "external" in tag_names
