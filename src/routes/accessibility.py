"""Operator-surface accessibility endpoints (EM-085, Epic E8).

Read-only: the non-colour risk encoding, the colour-blind-safe palette contract
and the global keyboard-shortcut registry are derived from settings plus
``RISK_COLORS`` on every request, so nothing is written to the database. The
operator surfaces fetch these once and drive their legend / theme / shortcut
affordances from a single source of truth.
"""

from typing import Any

from fastapi import FastAPI

from src.database import Database
from src.services.accessibility import (
    accessibility_config,
    keyboard_shortcuts,
    palette_contract,
    risk_encodings,
)


def register_accessibility_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-085 accessibility contract feed."""
    del database  # EM-085 derives the contract read-time; nothing is persisted.

    @api.get("/api/v1/accessibility/config", tags=["panel"])
    def accessibility_config_endpoint() -> dict[str, Any]:
        """Full contract: theme, non-colour risk encoding, palette, shortcuts."""
        return accessibility_config(settings)

    @api.get("/api/v1/accessibility/risk-encodings", tags=["panel"])
    def accessibility_risk_encodings() -> dict[str, Any]:
        """Per-level colour + label + glyph + pattern (no colour-only info)."""
        return {"encodings": risk_encodings(), "palette": palette_contract()}

    @api.get("/api/v1/accessibility/shortcuts", tags=["panel"])
    def accessibility_shortcuts() -> dict[str, Any]:
        """Global keyboard-shortcut registry the operator map binds at load."""
        return {"shortcuts": keyboard_shortcuts()}
