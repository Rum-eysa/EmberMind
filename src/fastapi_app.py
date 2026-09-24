"""Single public FastAPI application for wildfire monitoring."""
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.config.settings import ProductionConfig, TestingConfig
from src.database import Database
from src.models.fire import FireCluster
from src.services.fire_sync import sync_firms, sync_status
from src.services.firms import FirmsSourceError


class FireClusterResponse(BaseModel):
    """Public representation of a FIRMS fire cluster."""

    cluster_key: str
    latitude: float
    longitude: float
    observation_count: int
    max_frp: float | None
    first_seen_at: str
    last_seen_at: str


class FiresResponse(BaseModel):
    """Response envelope for fire clusters."""

    source: str
    count: int
    fires: list[FireClusterResponse]


class SyncResponse(BaseModel):
    """Response returned after an on-demand FIRMS sync."""

    status: str
    observations: int
    clusters: int
    source: str
    last_success_at: str | None
    last_success_age_minutes: float | None = None
    last_observation_count: int | None = None
    last_error: str | None = None
    stale: bool


def create_fastapi_app(config_name: str = "production") -> FastAPI:
    """Create the FastAPI application and its database lifecycle."""
    settings = TestingConfig if config_name == "testing" else ProductionConfig
    database = Database(settings.DATABASE_URL)

    @asynccontextmanager
    async def lifespan(_api: FastAPI):
        database.create_all()
        yield

    api = FastAPI(
        title="Wildfire Monitoring API",
        version="1.0.0",
        description="NASA FIRMS active-fire monitoring service.",
        lifespan=lifespan,
    )
    api.state.database = database
    api.state.settings = settings

    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @api.get("/api/v1", tags=["system"])
    def api_root() -> dict[str, str]:
        return {"version": "1.0.0", "project": "Yangın İzleme Sistemi"}

    @api.get("/api/v1/fires", response_model=FiresResponse, tags=["fires"])
    def fires(limit: int = Query(default=500, ge=1, le=1000)) -> dict[str, Any]:
        with database.session() as session:
            rows = session.scalars(
                select(FireCluster)
                .order_by(FireCluster.last_seen_at.desc())
                .limit(limit)
            ).all()
            fire_rows = [row.as_dict for row in rows]
        return {"source": "NASA FIRMS", "count": len(fire_rows), "fires": fire_rows}

    @api.get("/api/v1/fires/status", tags=["fires"])
    def fires_status() -> dict[str, Any]:
        with database.session() as session:
            return sync_status(session)

    @api.post("/api/v1/fires/sync", response_model=SyncResponse, tags=["fires"])
    def sync_fires() -> dict[str, Any]:
        try:
            with database.session() as session:
                result = sync_firms(session, settings)
                return {"status": "ok", **result, **sync_status(session)}
        except FirmsSourceError as exc:
            with database.session() as session:
                status = sync_status(session)
            raise HTTPException(
                status_code=503,
                detail={"status": "stale", "error": str(exc), **status},
            ) from exc

    return api


app = create_fastapi_app()
