"""Design system endpoints: styleguide page and shared static assets (EM-075)."""
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from src.database import Database

# Shipped with the package: src/routes/../static
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STYLEGUIDE_PAGE = STATIC_DIR / "styleguide.html"

# Whitelist of servable static assets; no arbitrary file reads.
STATIC_ASSETS = {"tokens.css", "components.css", "app.js"}


def register_design_system_routes(
    api: FastAPI, _database: Database, _settings: Any
) -> None:
    """Attach the styleguide page and the design-system CSS assets.

    The static assets are file-based, so the database/settings handles are
    unused here; the signature matches the other register_* helpers.
    """

    @api.get("/styleguide", tags=["ui"], response_class=FileResponse)
    def styleguide() -> FileResponse:
        """Component library showcase with the light/dark theme switch."""
        if not STYLEGUIDE_PAGE.is_file():
            raise HTTPException(status_code=404, detail="Styleguide page missing")
        return FileResponse(STYLEGUIDE_PAGE, media_type="text/html")

    @api.get("/static/{asset_name}", tags=["ui"], include_in_schema=False)
    def static_asset(asset_name: str) -> FileResponse:
        """Serve the whitelisted design-system CSS/JS assets."""
        if asset_name not in STATIC_ASSETS:
            raise HTTPException(status_code=404, detail="Unknown asset")
        media_type = (
            "application/javascript" if asset_name.endswith(".js") else "text/css"
        )
        return FileResponse(STATIC_DIR / asset_name, media_type=media_type)
