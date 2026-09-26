"""Resource inventory endpoints: CRUD and CSV bulk import (EM-103)."""
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.database import Database
from src.services.inventory import (
    InventoryError,
    capacity_summary,
    create_resource,
    delete_resource,
    get_resource,
    import_resources_csv,
    list_resources,
    update_resource,
)

# The inventory is internally managed (not an external data source), so it
# carries a fixed attribution rather than a governance-registry lookup.
INVENTORY_ATTRIBUTION = "Kaynak envanteri: EmberMind koordinatör kayıtları (EM-103)"

# Shipped with the package: src/routes/../static/inventory.html
INVENTORY_PAGE = Path(__file__).resolve().parent.parent / "static" / "inventory.html"


class ResourceCreateRequest(BaseModel):
    """Payload to register a suppression resource in the inventory."""

    resource_key: str
    resource_type: str
    latitude: float
    longitude: float
    name: str | None = None
    base_key: str | None = None
    country: str | None = None
    status: str = "available"
    capacity: float = 0.0
    capacity_unit: str | None = None


class ResourceUpdateRequest(BaseModel):
    """Partial update payload; only provided fields are changed."""

    name: str | None = None
    resource_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    base_key: str | None = None
    country: str | None = None
    status: str | None = None
    capacity: float | None = None
    capacity_unit: str | None = None


def _bad_request(exc: InventoryError) -> HTTPException:
    return HTTPException(status_code=400, detail={"status": "error", "error": str(exc)})


def register_inventory_routes(api: FastAPI, database: Database, _settings: Any) -> None:
    """Attach the coordinator resource-inventory CRUD and CSV import endpoints.

    The inventory is an internal coordinator store, so no governance settings
    lookup is needed here; the signature matches the other register_* helpers.
    """

    @api.get("/inventory", tags=["ui"], response_class=FileResponse)
    def inventory_page() -> FileResponse:
        """Coordinator inventory screen: CRUD table, capacity card,
        CSV bulk-import box (EM-103 acceptance UI)."""
        if not INVENTORY_PAGE.is_file():
            raise HTTPException(status_code=404, detail="Inventory page missing")
        return FileResponse(INVENTORY_PAGE, media_type="text/html")

    @api.get("/api/v1/resources", tags=["inventory"])
    def resources(
        resource_type: str | None = Query(default=None),
        status: str | None = Query(default=None),
        base_key: str | None = Query(default=None),
        country: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        """List the inventory with optional filters plus a capacity rollup."""
        try:
            with database.session() as session:
                rows = list_resources(
                    session, resource_type, status, base_key, country, limit
                )
                summary = capacity_summary(session)
                items = [row.as_dict for row in rows]
        except InventoryError as exc:
            raise _bad_request(exc) from exc
        return {
            "count": len(items),
            "resources": items,
            "capacity": summary,
            "attribution": INVENTORY_ATTRIBUTION,
        }

    @api.get("/api/v1/resources/capacity", tags=["inventory"])
    def resources_capacity() -> dict[str, Any]:
        """Capacity breakdown by resource type (keeps the panel current)."""
        with database.session() as session:
            return {"capacity": capacity_summary(session)}

    @api.post("/api/v1/resources", tags=["inventory"])
    def create(req: ResourceCreateRequest) -> dict[str, Any]:
        """Register a new crew / helicopter / uav asset."""
        try:
            with database.session() as session:
                resource = create_resource(session, req.model_dump())
                session.commit()
                return {"status": "created", "resource": resource.as_dict}
        except InventoryError as exc:
            message = str(exc)
            status_code = 409 if "already exists" in message else 400
            raise HTTPException(
                status_code=status_code,
                detail={"status": "error", "error": message},
            ) from exc

    @api.get("/api/v1/resources/{resource_key}", tags=["inventory"])
    def read(resource_key: str) -> dict[str, Any]:
        """Fetch a single inventory record by key."""
        with database.session() as session:
            resource = get_resource(session, resource_key)
            if resource is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "status": "not_found",
                        "error": f"no resource {resource_key}",
                    },
                )
            return resource.as_dict

    @api.put("/api/v1/resources/{resource_key}", tags=["inventory"])
    def update(resource_key: str, req: ResourceUpdateRequest) -> dict[str, Any]:
        """Edit fields of an existing inventory record."""
        changes = req.model_dump(exclude_unset=True)
        try:
            with database.session() as session:
                resource = update_resource(session, resource_key, changes)
                session.commit()
                return {"status": "updated", "resource": resource.as_dict}
        except InventoryError as exc:
            message = str(exc)
            status_code = 404 if "not found" in message else 400
            raise HTTPException(
                status_code=status_code,
                detail={"status": "error", "error": message},
            ) from exc

    @api.delete("/api/v1/resources/{resource_key}", tags=["inventory"])
    def remove(resource_key: str) -> dict[str, Any]:
        """Delete an inventory record."""
        with database.session() as session:
            removed = delete_resource(session, resource_key)
            session.commit()
        if not removed:
            raise HTTPException(
                status_code=404,
                detail={"status": "not_found", "error": f"no resource {resource_key}"},
            )
        return {"status": "deleted", "resource_key": resource_key}

    @api.post("/api/v1/resources/import/csv", tags=["inventory"])
    async def import_csv(request: Request) -> dict[str, Any]:
        """Bulk import resources from raw CSV text (upsert by resource_key)."""
        body = await request.body()
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": "CSV body must be UTF-8"},
            ) from exc
        try:
            with database.session() as session:
                result = import_resources_csv(session, text)
        except InventoryError as exc:
            raise _bad_request(exc) from exc
        return {"status": "ok", **result}
