"""Cross-border shared situation endpoints (EM-066, Epic E7).

A read-only, scope-filtered view over the EM-029 risk index and EM-065
external-support forecast: Türkiye and Greece see both nations' active fires,
risk bands and reinforcement needs on one coordinated screen. The ``fields``
parameter narrows the data-sharing scope for a given view; nothing is stored.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.database import Database
from src.services.crossborder_situation import (
    COUNTRIES,
    COUNTRY_LABELS,
    CROSSBORDER_ATTRIBUTION,
    DEFAULT_SHARED_FIELDS,
    SHAREABLE_FIELD_GROUPS,
    CrossborderError,
    crossborder_situation,
)


def register_crossborder_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-066 cross-border situation feed."""

    @api.get("/api/v1/crossborder/situation", tags=["panel"])
    def crossborder_situation_view(
        fields: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Shared TR/GR situation, narrowed to the requested field groups."""
        try:
            with database.session() as session:
                return crossborder_situation(session, settings, fields)
        except CrossborderError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.get("/api/v1/crossborder/config", tags=["panel"])
    def crossborder_config() -> dict[str, Any]:
        """The border split, countries and shareable field groups in effect."""
        return {
            "border_longitude": float(
                getattr(settings, "CROSSBORDER_BORDER_LONGITUDE", 26.5)
            ),
            "countries": [
                {"code": code, "label": COUNTRY_LABELS.get(code, code)}
                for code in COUNTRIES
            ],
            "shareable_fields": list(SHAREABLE_FIELD_GROUPS),
            "default_shared_fields": str(
                getattr(settings, "CROSSBORDER_SHARED_FIELDS", DEFAULT_SHARED_FIELDS)
            ),
            "attribution": CROSSBORDER_ATTRIBUTION,
            "persistence": "none",
        }
