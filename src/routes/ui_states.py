"""Panel state catalogue endpoints (EM-079, Epic E8).

Read-only, deterministic strings that drive every operator panel's loading /
empty / error affordances and the connection-lost band. Nothing is persisted;
the surfaces fetch the catalogue once and render consistent states from it.
"""
from typing import Any

from fastapi import FastAPI, HTTPException

from src.database import Database
from src.services.ui_states import panel_state, ui_state_catalog


def register_ui_state_routes(api: FastAPI, _database: Database, settings: Any) -> None:
    """Attach the EM-079 panel-state catalogue feed.

    The catalogue is static config, so the database handle is unused here; the
    signature matches the other ``register_*`` helpers.
    """

    @api.get("/api/v1/ui-states", tags=["ui"])
    def ui_states() -> dict[str, Any]:
        """Loading/empty/error copy for every panel plus the connection band."""
        return ui_state_catalog(settings)

    @api.get("/api/v1/ui-states/panel/{panel_key}", tags=["ui"])
    def ui_state_panel(panel_key: str) -> dict[str, Any]:
        """The four-state block for a single panel (404 for an unknown key)."""
        try:
            return panel_state(panel_key)
        except LookupError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "error", "error": str(exc)},
            ) from exc
