"""Multilingual UI catalogue endpoints (EM-068, Epic E7).

Serve the interface text catalogue (titles, card headings, labels, buttons and
the fixed resource / risk-band enums) so a Greek or Turkish operator reads the
coordination panel in their own language. ``TR`` and ``EN`` are complete, ``EL``
covers the core screens with an ``EN`` bridge fallback. The catalogue is
compiled into the app and the chosen locale lives only in the browser, so both
endpoints report ``persistence: none``.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.i18n import I18nError, config_payload, messages_payload


def register_i18n_routes(api: FastAPI, _database: Database, settings: Any) -> None:
    """Attach the EM-068 interface-text feeds."""

    @api.get("/api/v1/i18n/messages", tags=["panel"])
    def i18n_messages(lang: str | None = Query(default=None)) -> dict[str, Any]:
        """The complete message catalogue for the requested locale."""
        try:
            return messages_payload(lang, settings)
        except I18nError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/i18n/config", tags=["panel"])
    def i18n_config() -> dict[str, Any]:
        """Supported locales, their labels, coverage and the default."""
        return config_payload(settings)
