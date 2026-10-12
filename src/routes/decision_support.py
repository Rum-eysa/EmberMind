"""Decision-support framing endpoints (EM-097, Epic E10).

Read-only: the responsibility framing, data / model version and the scenario
(synthetic-data) badge are derived from settings on every request, so nothing is
written to the database. These feed the operator recommendation screen so the
commander always sees that the decision belongs to them and which version / kind
of data the advice rests on.
"""

from typing import Any

from fastapi import FastAPI

from src.database import Database
from src.services.decision_support import support_config, support_framing


def register_decision_support_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-097 decision-support framing feed."""
    del database  # EM-097 derives the framing read-time from settings; nothing is written.

    @api.get("/api/v1/decision-support", tags=["panel"])
    def decision_support_framing() -> dict[str, Any]:
        """Responsibility statement + data/model version + scenario badge."""
        return support_framing(settings)

    @api.get("/api/v1/decision-support/config", tags=["panel"])
    def decision_support_config() -> dict[str, Any]:
        """Defaults, current knobs and the label catalog for the framing."""
        return support_config(settings)
