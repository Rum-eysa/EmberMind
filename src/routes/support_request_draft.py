"""External-support request draft endpoints (EM-071, Epic E7).

Read-only composition over the EM-065 early forecast: build an editable,
copyable / printable international support-request draft (auto-summarised from
need + time + location) for one incident in TR / EN / EL. Nothing is persisted.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.i18n import I18nError
from src.services.risk_index import RiskIndexError
from src.services.support_request_draft import (
    build_request_draft,
    config_payload,
    requestable_events,
)


def register_support_request_draft_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-071 support-request draft feed."""

    @api.get("/api/v1/support-request-draft/config", tags=["panel"])
    def support_draft_config() -> dict[str, Any]:
        """Supported draft locales, default language and export formats."""
        return config_payload(settings)

    @api.get("/api/v1/support-request-draft/events", tags=["panel"])
    def support_draft_events() -> dict[str, Any]:
        """Active incidents (with projected shortfall) for the draft picker."""
        with database.session() as session:
            return requestable_events(session, settings)

    @api.get("/api/v1/support-request-draft", tags=["panel"])
    def support_draft(
        event_key: str = Query(...),
        lang: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Compose an editable support-request draft for one incident."""
        try:
            with database.session() as session:
                return build_request_draft(session, settings, event_key, lang)
        except I18nError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
        except RiskIndexError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "error", "error": str(exc)},
            ) from exc
        except LookupError as exc:
            raise HTTPException(
                status_code=404,
                detail={"status": "error", "error": str(exc)},
            ) from exc
