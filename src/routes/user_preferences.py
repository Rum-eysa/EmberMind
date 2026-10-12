"""Persisted operator preference endpoints (EM-088, Epic E8).

Reads / writes the single saved operator profile (interface language, theme,
display time zone and coordinate format) and offers a one-action reset back to
the settings-derived defaults. The allowed value sets and the current defaults
are exposed via ``config`` so the UI can render the switches without hard-coding
them.
"""
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.database import Database
from src.services.user_preferences import (
    UserPreferenceError,
    get_preferences,
    preference_config,
    reset_preferences,
    update_preferences,
)


class PreferenceRequest(BaseModel):
    """Any subset of the operator profile; unsupplied fields are left as-is."""

    language: Optional[str] = None
    theme: Optional[str] = None
    timezone: Optional[str] = None
    coordinate_format: Optional[str] = None


def register_user_preference_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-088 saved-preference endpoints."""

    @api.get("/api/v1/preferences/config", tags=["panel"])
    def preferences_config() -> dict[str, Any]:
        """Allowed value sets, the settings-derived defaults and the key."""
        return preference_config(settings)

    @api.get("/api/v1/preferences", tags=["panel"])
    def preferences_get() -> dict[str, Any]:
        """The saved operator profile, or the defaults when none is stored."""
        with database.session() as session:
            return get_preferences(session, settings)

    @api.put("/api/v1/preferences", tags=["panel"])
    def preferences_put(req: PreferenceRequest) -> dict[str, Any]:
        """Validate and persist any subset of the profile, applied at once."""
        try:
            with database.session() as session:
                result = update_preferences(
                    session,
                    settings,
                    language=req.language,
                    theme=req.theme,
                    timezone=req.timezone,
                    coordinate_format=req.coordinate_format,
                )
                session.commit()
        except UserPreferenceError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
        return result

    @api.delete("/api/v1/preferences", tags=["panel"])
    def preferences_reset() -> dict[str, Any]:
        """Drop the saved profile so the panel reverts to the defaults."""
        with database.session() as session:
            result = reset_preferences(session, settings)
            session.commit()
        return result
