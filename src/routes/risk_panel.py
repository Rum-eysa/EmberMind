"""Commander capacity & risk panel endpoints (EM-073)."""
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from src.database import Database
from src.services.data_governance import attribution_for
from src.services.risk_panel import build_capacity_risk_panel

# Shipped with the package: src/routes/../static/risk_panel.html
PANEL_PAGE = Path(__file__).resolve().parent.parent / "static" / "risk_panel.html"


def _parse_day(day: str | None) -> date | None:
    """Parse an optional YYYY-MM-DD query parameter."""
    if not day:
        return None
    try:
        return date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "error": f"Invalid day '{day}'; use YYYY-MM-DD"},
        ) from exc


def register_risk_panel_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the commander capacity & risk panel page and its feed."""

    @api.get("/panel", tags=["ui"], response_class=FileResponse)
    def risk_panel_page() -> FileResponse:
        """Single-panel command view: risk index, threshold colour,
        first exceedance time and capacity breakdown."""
        return FileResponse(PANEL_PAGE, media_type="text/html")

    @api.get("/api/v1/panel/capacity-risk", tags=["panel"])
    def capacity_risk_panel(day: str | None = None) -> dict[str, Any]:
        """Panel payload for one day (latest FWI day by default)."""
        with database.session() as session:
            payload = build_capacity_risk_panel(session, settings, _parse_day(day))
            return {
                **payload,
                "attribution": attribution_for(settings, "weather"),
            }
