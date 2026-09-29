"""Capacity unit assumption endpoints (EM-028, Epic E3).

Expose the admin-editable per-resource-type "effective suppression capacity"
(hectare/hour) assumptions and the normalised ha/hour capacity account so the
command panel can show capacity and risk in one unit and let an administrator
tune the assumptions from the interface.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from src.database import Database
from src.services.capacity import (
    CapacityError,
    effective_capacity,
    list_assumptions,
    update_assumptions,
)

# Internal configuration store (not an external data source): fixed attribution.
CAPACITY_ATTRIBUTION = (
    "Kapasite varsayımları: EmberMind yönetici konfigürasyonu (EM-028)"
)


class AssumptionsUpdateRequest(BaseModel):
    """Partial admin edit; only the provided resource types are changed."""

    crew: float | None = None
    helicopter: float | None = None
    uav: float | None = None


def _error(exc: CapacityError) -> HTTPException:
    return HTTPException(status_code=400, detail={"status": "error", "error": str(exc)})


def register_capacity_routes(api: FastAPI, database: Database, settings: Any) -> None:
    """Attach the capacity-unit assumption read/edit and normalised capacity."""

    @api.get("/api/v1/capacity/assumptions", tags=["capacity"])
    def read_assumptions() -> dict[str, Any]:
        """Current per-type effective capacity assumptions (ha/hour)."""
        with database.session() as session:
            return {
                **list_assumptions(session, settings),
                "attribution": CAPACITY_ATTRIBUTION,
            }

    @api.put("/api/v1/capacity/assumptions", tags=["capacity"])
    async def edit_assumptions(request: Request) -> dict[str, Any]:
        """Administrator updates one or more resource-type assumptions."""
        payload = AssumptionsUpdateRequest.model_validate(await request.json())
        values = {k: v for k, v in payload.model_dump().items() if v is not None}
        try:
            with database.session() as session:
                result = update_assumptions(session, settings, values)
                session.commit()
        except CapacityError as exc:
            raise _error(exc) from exc
        return {"status": "updated", **result}

    @api.get("/api/v1/capacity/effective", tags=["capacity"])
    def read_effective() -> dict[str, Any]:
        """Available inventory normalised into a single ha/hour figure."""
        with database.session() as session:
            return {
                "capacity": effective_capacity(session, settings),
                "attribution": CAPACITY_ATTRIBUTION,
            }
