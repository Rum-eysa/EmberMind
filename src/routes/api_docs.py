"""API documentation endpoints (EM-095, Epic E9).

Integrator-facing read-only surface that publishes, as JSON, everything needed
to consume the API quickly: the OpenAPI identity metadata, the consolidated
HTTP error contract, the EM-092 rate-limit contract, and copy-pasteable cURL /
Python example clients. These complement the framework's own interactive docs
(``/docs`` Swagger UI, ``/redoc``, ``/openapi.json``).

No database access, nothing is persisted - a pure read-time projection of
settings and static catalogs (see the service).
"""

from typing import Any

from fastapi import FastAPI

from src.database import Database
from src.services.api_docs import (
    docs_bundle,
    error_codes,
    example_clients,
    openapi_meta,
    rate_limit_docs,
)


def register_api_docs_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the EM-095 API-documentation surface."""
    del database  # EM-095 projects settings + static catalogs; nothing is persisted.

    @api.get("/api/v1/api-docs", tags=["panel"])
    def api_docs() -> dict[str, Any]:
        """Aggregate documentation bundle (openapi + errors + rate limits + examples)."""
        return docs_bundle(settings)

    @api.get("/api/v1/api-docs/config", tags=["panel"])
    def api_docs_config() -> dict[str, Any]:
        """OpenAPI identity metadata: title/version/contact/license/docs paths/tags."""
        return openapi_meta(settings)

    @api.get("/api/v1/api-docs/errors", tags=["panel"])
    def api_docs_errors() -> dict[str, Any]:
        """The consolidated HTTP error contract this API can return."""
        return {"errors": error_codes(), "count": len(error_codes())}

    @api.get("/api/v1/api-docs/rate-limits", tags=["panel"])
    def api_docs_rate_limits() -> dict[str, Any]:
        """The EM-092 throttle contract read live from current settings."""
        return rate_limit_docs(settings)

    @api.get("/api/v1/api-docs/examples", tags=["panel"])
    def api_docs_examples() -> dict[str, Any]:
        """Copy-pasteable cURL and Python example clients (never embeds a key)."""
        return example_clients(settings)
