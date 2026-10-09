"""External-client access control endpoints (EM-092, Epic E9).

Two surfaces:

* ``GET /api/v1/external/status`` - a representative endpoint an external
  integration would call. It is guarded by the API-key + rate-limit layer: a bad
  or missing key is rejected with ``401``, an over-budget authenticated client is
  throttled with ``429`` (and a ``Retry-After``), and a permitted call answers
  ``200`` with the remaining budget in ``X-RateLimit-*`` headers. When
  enforcement is switched off the endpoint stays open but reports itself
  ``disabled`` rather than pretending to be guarded.
* ``GET /api/v1/api-access/config`` - an admin read of the current policy. It
  never reveals a key, only how many are configured and the throttling budget.

No database access: the throttle counters are process-local (see the service).
"""

from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response

from src.database import Database
from src.services.api_access import (
    API_KEY_HEADER,
    STATUS_ALLOWED,
    STATUS_RATE_LIMITED,
    STATUS_UNAUTHORIZED,
    RateLimiter,
    access_config,
    authorize,
)


def register_api_access_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the EM-092 external API-key + rate-limit surface."""
    del database  # EM-092 keeps throttle counters in memory; nothing is persisted.

    limiter = RateLimiter()

    def _rate_headers(decision: dict[str, Any], response: Response) -> None:
        """Publish the standard throttle headers for an authenticated call."""
        if decision.get("authenticated"):
            response.headers["X-RateLimit-Limit"] = str(decision["limit"])
            response.headers["X-RateLimit-Remaining"] = str(decision["remaining"])
            response.headers["X-RateLimit-Reset"] = str(int(decision["reset_at"]))

    @api.get("/api/v1/external/status", tags=["external"])
    def external_status(
        request: Request,
        response: Response,
        api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> dict[str, Any]:
        """A guarded sample endpoint for API-key authorized external clients."""
        client_id = request.client.host if request.client else "unknown"
        decision = authorize(api_key, client_id, settings, limiter)
        status = decision["status"]

        if status == STATUS_UNAUTHORIZED:
            raise HTTPException(
                status_code=401,
                detail={
                    "status": "error",
                    "error": f"Missing or invalid API key (send header '{API_KEY_HEADER}').",
                },
            )

        _rate_headers(decision, response)

        if status == STATUS_RATE_LIMITED:
            response.headers["Retry-After"] = str(int(round(decision["retry_after"])))
            raise HTTPException(
                status_code=429,
                detail={
                    "status": "error",
                    "error": "Rate limit exceeded; retry when the window resets.",
                    "retry_after": decision["retry_after"],
                },
            )

        return {
            "endpoint": "/api/v1/external/status",
            "status": status,
            "enforced": decision["enforced"],
            "authenticated": decision.get("authenticated", False),
            "rate_limit": (
                {
                    "limit": decision["limit"],
                    "remaining": decision["remaining"],
                    "reset_at": decision["reset_at"],
                }
                if status == STATUS_ALLOWED
                else None
            ),
            "attribution": "API anahtarı ve hız sınırlama: EM-092",
        }

    @api.get("/api/v1/api-access/config", tags=["panel"])
    def api_access_config() -> dict[str, Any]:
        """Current policy: enabled/enforced flags, header name and budget (no keys)."""
        return access_config(settings)
