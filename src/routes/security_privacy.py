"""Data-privacy and security-fundamentals conformance endpoints (EM-100, Epic E10).

Read-only: the privacy-by-design verdict, the (redacted) secret-hygiene posture
and the honest transport-security knobs are derived on every request from the
live SQLAlchemy metadata and the current settings, so nothing is written to the
database (``persistence: none``). They give the system administrator a
verifiable - not asserted - view that EmberMind keeps observation data keyed by
region / cell (never by person) and that secrets are supplied only through the
environment. TLS termination and CI secret / dependency scanning are deployment
concerns (E12 / EM-102) and are reported as such rather than faked here.
"""

from typing import Any

from fastapi import FastAPI

from src.database import Database
from src.services.security_privacy import (
    conformance_report,
    security_privacy_config,
)


def register_security_privacy_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-100 security & privacy conformance feed."""
    del database  # EM-100 is a read-time projection over metadata + settings.

    @api.get("/api/v1/security-privacy", tags=["panel"])
    def security_privacy_conformance() -> dict[str, Any]:
        """Combined privacy-by-design + secret-hygiene + transport conformance."""
        return conformance_report(settings)

    @api.get("/api/v1/security-privacy/config", tags=["panel"])
    def security_privacy_config_endpoint() -> dict[str, Any]:
        """Account/domain catalogue, secret list and the honest scope note."""
        return security_privacy_config(settings)
