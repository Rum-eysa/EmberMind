"""One-page situation report (SITREP) endpoints (EM-087, Epic E8).

A printable, single-page status report assembled from the active fires, the
spread forecast, the risk index and the top dispatch recommendations, stamped
with a report time and a synthetic-data badge. It is a read-time projection -
nothing is persisted and no new table exists.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.risk_index import RiskIndexError
from src.services.sitrep_report import build_sitrep, sitrep_config


def register_sitrep_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the EM-087 SITREP report endpoints."""

    @api.get("/api/v1/sitrep/config", tags=["panel"])
    def sitrep_config_endpoint() -> dict[str, Any]:
        """Report sections, vocabularies, export formats and the badge label."""
        return sitrep_config(settings)

    @api.get("/api/v1/sitrep", tags=["panel"])
    def sitrep_endpoint(event_key: str | None = Query(default=None)) -> dict[str, Any]:
        """Assemble the one-page report for all active fires, or one incident."""
        with database.session() as session:
            try:
                return build_sitrep(session, settings, event_key=event_key)
            except RiskIndexError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
