"""Per-region silent-zone tuning endpoints (EM-044, Epic E4).

Lets the operator read and adjust, per silent region, the two detection knobs -
the silence z-score **eşik** and the **minimum sessizlik süresi** - with a
one-click **varsayılana dön**. Every change (and every reset) is written to the
unified audit ledger; nothing here closes an issue or fabricates data.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.silent_zone_tuning import (
    SILENT_ZONE_TUNING_ATTRIBUTION,
    SILENT_ZONE_TUNING_PERSISTENCE,
    SilentZoneTuningError,
    effective_for_region,
    list_effective,
    reset_tuning,
    set_tuning,
    tuning_config,
)


class TuningRequest(BaseModel):
    """One region's override of the silent-zone knobs."""

    model_config = {"protected_namespaces": ()}

    region_id: int
    sensitivity_z: float | None = None
    min_silence_hours: float | None = None
    actor: str | None = None


class TuningResetRequest(BaseModel):
    """Return one region's tuning to the global default."""

    model_config = {"protected_namespaces": ()}

    region_id: int
    actor: str | None = None


def _http_error(exc: SilentZoneTuningError) -> HTTPException:
    """Map a service error to the right HTTP status (missing vs invalid)."""
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(
        status_code=status, detail={"status": "error", "error": str(exc)}
    )


def register_silent_zone_tuning_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EM-044 per-region silent-zone tuning surface."""

    @api.get("/api/v1/silent-zone-tuning/config", tags=["panel"])
    def silent_zone_tuning_config() -> dict[str, Any]:
        """Defaults, bounds, inheritance rule and the audit domain."""
        return tuning_config(settings)

    @api.get("/api/v1/silent-zone-tuning/effective", tags=["panel"])
    def silent_zone_tuning_effective(
        region_id: int | None = Query(default=None),
    ) -> dict[str, Any]:
        """Effective tuning: one region's, or every active region's."""
        with database.session() as session:
            if region_id is not None:
                try:
                    one = effective_for_region(session, settings, region_id)
                except SilentZoneTuningError as exc:
                    raise _http_error(exc) from exc
                return {
                    "region_id": region_id,
                    "effective": one,
                    "attribution": SILENT_ZONE_TUNING_ATTRIBUTION,
                    "persistence": SILENT_ZONE_TUNING_PERSISTENCE,
                }
            rows = list_effective(session, settings)
        return {
            "count": len(rows),
            "regions": rows,
            "attribution": SILENT_ZONE_TUNING_ATTRIBUTION,
            "persistence": SILENT_ZONE_TUNING_PERSISTENCE,
        }

    @api.post("/api/v1/silent-zone-tuning", tags=["panel"])
    def silent_zone_tuning_set(req: TuningRequest) -> dict[str, Any]:
        """Persist (upsert) one region's override and audit the change."""
        try:
            with database.session() as session:
                result = set_tuning(
                    session,
                    settings,
                    req.region_id,
                    sensitivity_z=req.sensitivity_z,
                    min_silence_hours=req.min_silence_hours,
                    actor=req.actor,
                )
                session.commit()
        except SilentZoneTuningError as exc:
            raise _http_error(exc) from exc
        return {
            "status": "saved",
            **result,
            "attribution": SILENT_ZONE_TUNING_ATTRIBUTION,
            "persistence": SILENT_ZONE_TUNING_PERSISTENCE,
        }

    @api.post("/api/v1/silent-zone-tuning/reset", tags=["panel"])
    def silent_zone_tuning_reset(req: TuningResetRequest) -> dict[str, Any]:
        """Drop one region's override so it inherits the default again."""
        try:
            with database.session() as session:
                result = reset_tuning(session, settings, req.region_id, actor=req.actor)
                session.commit()
        except SilentZoneTuningError as exc:
            raise _http_error(exc) from exc
        return {
            "status": "reset",
            **result,
            "attribution": SILENT_ZONE_TUNING_ATTRIBUTION,
            "persistence": SILENT_ZONE_TUNING_PERSISTENCE,
        }
