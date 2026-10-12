"""Municipality / traffic / public-alert integration template endpoints (EM-093).

Integrator-facing read-only surface that publishes, as JSON, the connection
templates for wiring *existing* downstream equipment to the EM-094 signed
webhook - a municipality information board, a traffic variable-message sign,
and a CAP-style public-alert head-end - plus a signature-verification snippet
and a minimal example consumer. No new hardware is required.

No database access, nothing is persisted - a pure read-time projection of the
live EM-094 envelope contract and static channel catalogs (see the service).
"""

from typing import Any

from fastapi import FastAPI

from src.database import Database
from src.services.integration_templates import (
    example_consumer,
    integration_config,
    templates_bundle,
    templates_for,
    transform,
)
from src.services.webhook_delivery import VALID_EVENT_TYPES


def register_integration_template_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-093 integration-template surface."""
    del database  # EM-093 projects the EM-094 contract + static catalogs; nothing persists.

    @api.get("/api/v1/integration-templates", tags=["panel"])
    def integration_templates() -> dict[str, Any]:
        """Aggregate bundle: config + per-channel samples + example consumer."""
        return templates_bundle(settings)

    @api.get("/api/v1/integration-templates/config", tags=["panel"])
    def integration_templates_config() -> dict[str, Any]:
        """Channel catalog, event kinds, signature contract, bounds."""
        return integration_config(settings)

    @api.get("/api/v1/integration-templates/consumer", tags=["panel"])
    def integration_templates_consumer() -> dict[str, Any]:
        """Verify-signature snippet + dispatch note (never embeds a secret)."""
        return example_consumer(settings)

    @api.get(
        "/api/v1/integration-templates/{event_type}",
        tags=["panel"],
        responses={400: {"description": "Bilinmeyen olay tipi"}},
    )
    def integration_templates_for(event_type: str) -> dict[str, Any]:
        """Every channel rendering for one illustrative envelope of ``event_type``."""
        if event_type not in VALID_EVENT_TYPES:
            return {
                "error": f"bilinmeyen olay tipi: {event_type}",
                "event_types": list(VALID_EVENT_TYPES),
            }
        return templates_for(event_type, settings)

    @api.get(
        "/api/v1/integration-templates/{event_type}/{channel}",
        tags=["panel"],
        responses={400: {"description": "Bilinmeyen olay tipi veya kanal"}},
    )
    def integration_templates_channel(event_type: str, channel: str) -> dict[str, Any]:
        """A single channel rendering of one illustrative envelope."""
        if event_type not in VALID_EVENT_TYPES:
            return {
                "error": f"bilinmeyen olay tipi: {event_type}",
                "event_types": list(VALID_EVENT_TYPES),
            }
        try:
            return transform(
                templates_for(event_type, settings)["sample_envelope"],
                channel,
                settings,
            )
        except ValueError as exc:
            return {"error": str(exc)}
