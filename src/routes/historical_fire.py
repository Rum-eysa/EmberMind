"""EFFIS historical fire perimeter routes (import, dataset splits, calibration export)."""
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.database import Database
from src.models.historical_fire import HistoricalFirePerimeter
from src.services.data_governance import attribution_for
from src.services.effis import (
    DEFAULT_EFFIS_BASE_URL,
    EffisClient,
    EffisSourceError,
    assign_dataset_splits,
    bootstrap_sample_dataset,
    build_calibration_dataset,
    import_effis_perimeters,
)
from src.services.grid_standard import PilotRegionGridService


class EffisImportRequest(BaseModel):
    """Optional bbox/year overrides for a live EFFIS perimeter import."""

    min_lat: float | None = None
    min_lon: float | None = None
    max_lat: float | None = None
    max_lon: float | None = None
    years: list[int] | None = None


class DatasetSplitRequest(BaseModel):
    """Request payload to (re)assign train/test/validation dataset splits."""

    test_fraction: float = 0.2
    validation_fraction: float = 0.2


class BootstrapSampleRequest(BaseModel):
    """Request payload to load an offline EFFIS-style sample dataset."""

    count: int = 24
    min_lat: float | None = None
    min_lon: float | None = None
    max_lat: float | None = None
    max_lon: float | None = None


def _resolve_bbox(
    req: EffisImportRequest | BootstrapSampleRequest,
) -> tuple[float, float, float, float]:
    grid = PilotRegionGridService()
    return (
        req.min_lat if req.min_lat is not None else grid.min_lat,
        req.min_lon if req.min_lon is not None else grid.min_lon,
        req.max_lat if req.max_lat is not None else grid.max_lat,
        req.max_lon if req.max_lon is not None else grid.max_lon,
    )


def register_historical_fire_routes(
    api: FastAPI, database: Database, settings: Any
) -> None:
    """Attach the EFFIS historical fire perimeter endpoints to the application."""

    @api.get("/api/v1/historical-fires", tags=["historical-fires"])
    def list_historical_fires(
        fire_year: int | None = None,
        country_code: str | None = None,
        split: str | None = None,
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        """List stored historical fire perimeters with optional filters."""
        with database.session() as session:
            query = select(HistoricalFirePerimeter)
            if fire_year is not None:
                query = query.where(HistoricalFirePerimeter.fire_year == fire_year)
            if country_code:
                query = query.where(
                    HistoricalFirePerimeter.country_code == country_code
                )
            if split:
                query = query.where(HistoricalFirePerimeter.split == split)
            rows = session.scalars(
                query.order_by(HistoricalFirePerimeter.id.asc()).limit(limit)
            ).all()
            perimeters = [row.as_dict for row in rows]
        return {
            "source": "EFFIS",
            "count": len(perimeters),
            "perimeters": perimeters,
            "attribution": attribution_for(settings, "historical_fire"),
        }

    @api.get("/api/v1/historical-fires/dataset", tags=["historical-fires"])
    def historical_fire_dataset(
        include_geometry: bool = True,
    ) -> dict[str, Any]:
        """Return the calibration/validation dataset split and readiness status."""
        with database.session() as session:
            return build_calibration_dataset(session, include_geometry)

    @api.post("/api/v1/historical-fires/import", tags=["historical-fires"])
    def historical_fires_import(req: EffisImportRequest) -> dict[str, Any]:
        """Import historical fire perimeters from the live EFFIS service."""
        bbox = _resolve_bbox(req)
        client = None
        if req.years:
            if not all(1980 <= y <= 2100 for y in req.years):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "status": "error",
                        "error": "years must be between 1980 and 2100",
                    },
                )
            # Honour the requested year list instead of the configured default.
            client = EffisClient(
                base_url=getattr(settings, "EFFIS_BASE_URL", DEFAULT_EFFIS_BASE_URL),
                years=sorted(set(req.years)),
            )
        try:
            with database.session() as session:
                result = import_effis_perimeters(session, settings, bbox, client=client)
                return {"status": "ok", "bbox": bbox, "years": req.years, **result}
        except EffisSourceError as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "error", "error": str(exc)},
            ) from exc

    @api.post("/api/v1/historical-fires/bootstrap-sample", tags=["historical-fires"])
    def historical_fires_bootstrap(req: BootstrapSampleRequest) -> dict[str, Any]:
        """Load an offline EFFIS-style sample dataset (>=20 events) without network."""
        bbox = _resolve_bbox(req)
        with database.session() as session:
            result = bootstrap_sample_dataset(session, bbox, req.count)
            return {"status": "ok", "bbox": bbox, **result}

    @api.post("/api/v1/historical-fires/splits", tags=["historical-fires"])
    def historical_fires_splits(req: DatasetSplitRequest) -> dict[str, Any]:
        """Assign deterministic train/test/validation splits for calibration."""
        try:
            with database.session() as session:
                counts = assign_dataset_splits(
                    session, req.test_fraction, req.validation_fraction
                )
                return {"status": "ok", **counts}
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "error": str(exc)},
            ) from exc
