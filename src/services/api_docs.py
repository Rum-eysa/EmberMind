"""API documentation surface and example clients (EM-095, Epic E9).

An integrator wants to try the API quickly so the integration effort stays
small. FastAPI already publishes an interactive OpenAPI / Swagger UI at
``/docs`` (ReDoc at ``/redoc``, raw schema at ``/openapi.json``), but that alone
is not enough: the schema needs proper identity metadata (contact, license,
per-tag descriptions), and an integrator needs copy-pasteable example clients
(cURL + Python) plus a single, honest catalog of the error codes and the
rate-limit contract (which ties into the EM-092 external API-key layer).

This module is a pure read-time projection (``persistence: none``): it derives
everything from settings and static catalogs. Nothing here invents an endpoint -
the example clients only reference routes that actually exist, and the rate
limit numbers are read from the live EM-092 configuration rather than hardcoded.

Security note: the example clients never embed a real API key. They reference
the ``x-api-key`` header with a placeholder that the integrator fills from their
own environment, so a copy of this documentation is not a credential leak.
"""

from typing import Any

from src.services.api_access import (
    API_KEY_HEADER,
    auth_required,
    enforcement_enabled,
    rate_limit,
    window_seconds,
)

DOCS_PERSISTENCE = "none"

DEFAULT_BASE_URL = "http://localhost:8000"

# The docs endpoints themselves are unauthenticated; these are the FastAPI
# built-in schema/UI routes that are always published.
DOCS_PATHS = {
    "swagger_ui": "/docs",
    "redoc": "/redoc",
    "openapi_json": "/openapi.json",
}

# Identity metadata passed straight to the FastAPI app so the published OpenAPI
# schema carries a maintainer and a license instead of being anonymous.
OPENAPI_CONTACT = {
    "name": "EmberMind Wildfire Monitoring",
    "url": "https://github.com/Rum-eysa/EmberMind",
}
OPENAPI_LICENSE = {"name": "MIT License"}
OPENAPI_TERMS = (
    "Bu API bir karar destek sistemidir; operasyonel kararların nihai sahibi "
    "yetkili operatördür (EM-097)."
)

# Per-tag descriptions surfaced in the Swagger/ReDoc navigation. Only tags that
# are meaningful to an external integrator are documented here; the framework
# still lists any other tag used by internal panel routes.
OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "system", "description": "Health probe and API root/version info."},
    {
        "name": "external",
        "description": (
            "External-client surface guarded by an API key and rate limiting "
            "(EM-092). Send the key in the 'x-api-key' header."
        ),
    },
    {"name": "fires", "description": "NASA FIRMS active-fire clusters and sync."},
    {"name": "weather", "description": "Weather forecast points and sync."},
    {"name": "topography", "description": "USGS/SRTM elevation, slope, aspect."},
    {"name": "land-cover", "description": "CORINE land cover and fuel models."},
    {"name": "events", "description": "Fire events: manual creation, read, update."},
    {"name": "spatial", "description": "PostGIS spatial queries and silent regions."},
    {"name": "grid", "description": "Pilot-region grid standard and transforms."},
    {"name": "pipeline", "description": "Data-source sync jobs and schedules."},
    {
        "name": "panel",
        "description": "Operator/commander panel configuration and projections.",
    },
]

# Consolidated HTTP error contract actually used across the API. Each entry is
# factual: the code appears in the codebase with the described meaning.
ERROR_CATALOG: list[dict[str, Any]] = [
    {
        "code": 400,
        "name": "Bad Request",
        "when": "Invalid payload or parameters (e.g. unknown severity/status, "
        "bad grid coordinate, invalid pipeline source).",
    },
    {
        "code": 401,
        "name": "Unauthorized",
        "when": "External surface (EM-092): missing or invalid API key in the "
        f"'{API_KEY_HEADER}' header.",
    },
    {
        "code": 404,
        "name": "Not Found",
        "when": "Requested resource does not exist (e.g. unknown event key).",
    },
    {
        "code": 409,
        "name": "Conflict",
        "when": "Manual fire event location duplicates an existing satellite "
        "detection within the de-duplication threshold.",
    },
    {
        "code": 422,
        "name": "Unprocessable Entity",
        "when": "Request validation failed (Pydantic/FastAPI) or a malformed "
        "ISO-8601 datetime was supplied.",
    },
    {
        "code": 429,
        "name": "Too Many Requests",
        "when": "External surface (EM-092): authenticated client exceeded its "
        "per-window budget. Honour the Retry-After header.",
    },
    {
        "code": 500,
        "name": "Internal Server Error",
        "when": "Unexpected server-side failure while processing a request.",
    },
    {
        "code": 503,
        "name": "Service Unavailable",
        "when": "An upstream data source (FIRMS/weather/topography/land cover) "
        "is stale or unreachable for an on-demand sync.",
    },
]


def _base_url(settings: Any) -> str:
    value = getattr(settings, "API_DOCS_BASE_URL", "") or ""
    return str(value).strip().rstrip("/") or DEFAULT_BASE_URL


def _contact(settings: Any) -> dict[str, str]:
    contact = dict(OPENAPI_CONTACT)
    email = str(getattr(settings, "API_DOCS_CONTACT_EMAIL", "") or "").strip()
    if email:
        contact["email"] = email
    return contact


def openapi_meta(settings: Any) -> dict[str, Any]:
    """Identity + navigation metadata of the published OpenAPI schema."""
    return {
        "title": "Wildfire Monitoring API",
        "version": "1.0.0",
        "base_url": _base_url(settings),
        "docs": dict(DOCS_PATHS),
        "contact": _contact(settings),
        "license": dict(OPENAPI_LICENSE),
        "terms_of_service": OPENAPI_TERMS,
        "tags": [dict(tag) for tag in OPENAPI_TAGS],
        "persistence": DOCS_PERSISTENCE,
    }


def error_codes() -> list[dict[str, Any]]:
    """The consolidated HTTP error contract this API can return."""
    return [dict(entry) for entry in ERROR_CATALOG]


def rate_limit_docs(settings: Any) -> dict[str, Any]:
    """The EM-092 throttle contract, read live from current settings.

    Returns the numbers an integrator must code against without ever exposing a
    key value: which header to send, the budget/window, the response headers,
    and whether enforcement is currently active.
    """
    return {
        "applies_to": "/api/v1/external/* (EM-092 guarded surface)",
        "header": API_KEY_HEADER,
        "enforcement_enabled": enforcement_enabled(settings),
        "enforced": auth_required(settings),
        "rate_limit_requests": rate_limit(settings),
        "rate_limit_window_seconds": window_seconds(settings),
        "response_headers": [
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
        "status_codes": {"unauthorized": 401, "rate_limited": 429},
        "note": (
            "Enforcement is active only when switched on AND at least one key "
            "is configured; otherwise the surface reports itself disabled and "
            "stays open."
        ),
    }


def example_clients(settings: Any) -> dict[str, Any]:
    """Copy-pasteable cURL and Python snippets for real, existing endpoints."""
    base = _base_url(settings)
    curl = [
        {
            "name": "health",
            "command": f"curl {base}/health",
        },
        {
            "name": "fires",
            "command": f"curl {base}/api/v1/fires?limit=10",
        },
        {
            "name": "external-status-authenticated",
            "command": (
                f'curl -H "{API_KEY_HEADER}: $WILDFIRE_API_KEY" '
                f"{base}/api/v1/external/status"
            ),
        },
    ]
    python = (
        "import os\n"
        "import httpx\n"
        "\n"
        f'BASE = "{base}"\n'
        f"HEADERS = {{\"{API_KEY_HEADER}\": os.environ['WILDFIRE_API_KEY']}}\n"
        "\n"
        "with httpx.Client(timeout=10.0) as client:\n"
        "    # Unauthenticated core endpoint\n"
        '    fires = client.get(f"{BASE}/api/v1/fires", params={"limit": 10})\n'
        "    fires.raise_for_status()\n"
        '    print(fires.json()["count"], "fire clusters")\n'
        "\n"
        "    # API-key guarded external endpoint (EM-092)\n"
        '    status = client.get(f"{BASE}/api/v1/external/status", headers=HEADERS)\n'
        "    if status.status_code == 429:\n"
        "        print('rate limited; retry after', status.headers.get('Retry-After'))\n"
        "    else:\n"
        "        status.raise_for_status()\n"
        "        print('external status:', status.json()[\"status\"])\n"
    )
    return {
        "base_url": base,
        "curl": curl,
        "python": python,
        "security_note": (
            "Examples reference the API key via an environment placeholder; no "
            "real credential is ever embedded in this documentation."
        ),
    }


def docs_bundle(settings: Any) -> dict[str, Any]:
    """Aggregate documentation payload for a single integrator-facing endpoint."""
    return {
        "openapi": openapi_meta(settings),
        "errors": error_codes(),
        "rate_limits": rate_limit_docs(settings),
        "examples": example_clients(settings),
        "attribution": "API dokümantasyonu ve örnek istemci: EM-095",
    }
