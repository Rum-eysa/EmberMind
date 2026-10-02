"""Capacity unit assumption endpoints (EM-028, Epic E3).

Expose the admin-editable per-resource-type "effective suppression capacity"
(hectare/hour) assumptions and the normalised ha/hour capacity account so the
command panel can show capacity and risk in one unit and let an administrator
tune the assumptions from the interface.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

from src.database import Database
from src.services.capacity import (
    CapacityError,
    capacity_by_country,
    capacity_schedule,
    effective_capacity,
    list_assumptions,
    list_audit,
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
    updated_by: str | None = None


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
        """Administrator updates one or more resource-type assumptions.

        EM-034: each applied change is written to the append-only audit trail
        with the editor carried in ``updated_by``; the response echoes both the
        new assumptions and the recent audit entries.
        """
        payload = AssumptionsUpdateRequest.model_validate(await request.json())
        edited = payload.model_dump()
        editor = edited.pop("updated_by", None)
        values = {k: v for k, v in edited.items() if v is not None}
        try:
            with database.session() as session:
                result = update_assumptions(session, settings, values, editor)
                audit = list_audit(session, settings)
                session.commit()
        except CapacityError as exc:
            raise _error(exc) from exc
        return {"status": "updated", **result, "audit": audit["entries"]}

    @api.get("/api/v1/capacity/assumptions/audit", tags=["capacity"])
    def read_assumptions_audit(
        resource_type: str | None = Query(default=None),
        limit: int | None = Query(default=None),
    ) -> dict[str, Any]:
        """Capacity-assumption change history (EM-034), newest first."""
        with database.session() as session:
            return list_audit(
                session, settings, resource_type=resource_type, limit=limit
            )

    @api.get("/api/v1/capacity/effective", tags=["capacity"])
    def read_effective() -> dict[str, Any]:
        """Available inventory normalised into a single ha/hour figure."""
        with database.session() as session:
            return {
                "capacity": effective_capacity(session, settings),
                "attribution": CAPACITY_ATTRIBUTION,
            }

    @api.get("/api/v1/capacity/by-country", tags=["capacity"])
    def read_by_country() -> dict[str, Any]:
        """Country-separated capacity account (EM-064): two nations never merge.

        Each resource belongs to a country and capacity is totalled per country,
        shown separately; resources with no declared country are isolated in an
        explicit unassigned bucket so nothing is silently merged.
        """
        with database.session() as session:
            return {
                "capacity": capacity_by_country(session, settings),
                "attribution": CAPACITY_ATTRIBUTION,
            }

    @api.get("/api/v1/capacity/schedule", tags=["capacity"])
    def read_schedule(
        minutes: list[int] | None = Query(default=None),
    ) -> dict[str, Any]:
        """Time-dependent capacity (EM-033): ha/hour at each forecast horizon.

        Credits en-route units from their arrival ETA so the commander sees the
        real risk crossing when reinforcements come online. Defaults to the
        configured ``SPREAD_HORIZON_MINUTES`` when no ``minutes`` are supplied.
        """
        horizon_minutes = (
            [int(m) for m in minutes]
            if minutes
            else [
                int(h)
                for h in getattr(settings, "SPREAD_HORIZON_MINUTES", [30, 60, 120])
            ]
        )
        with database.session() as session:
            return {
                "schedule": capacity_schedule(session, settings, horizon_minutes),
                "attribution": CAPACITY_ATTRIBUTION,
            }
