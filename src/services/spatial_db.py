"""Spatial database repository and polygon intersection query service."""
from typing import Any
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.spatial import (
    FireEvent,
    FireForecast,
    SilentRegion,
    SimulationScenario,
    SpatialSource,
)


class SpatialQueryError(RuntimeError):
    """Raised when spatial query execution fails."""


def execute_polygon_intersection_query(
    session: Session,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> dict[str, Any]:
    """Perform spatial polygon bounding-box intersection across all spatial tables.

    Acceptance criteria requirement: Returns in under 1.0 second on pilot scale.
    """
    start_time = time.perf_counter()

    # 1. Query FireEvents intersecting bounding box
    events = session.scalars(
        select(FireEvent).where(
            FireEvent.min_lat <= max_lat,
            FireEvent.max_lat >= min_lat,
            FireEvent.min_lon <= max_lon,
            FireEvent.max_lon >= min_lon,
        )
    ).all()

    # 2. Query FireForecasts intersecting bounding box
    forecasts = session.scalars(
        select(FireForecast).where(
            FireForecast.latitude >= min_lat,
            FireForecast.latitude <= max_lat,
            FireForecast.longitude >= min_lon,
            FireForecast.longitude <= max_lon,
        )
    ).all()

    # 3. Query SpatialSources intersecting bounding box
    sources = session.scalars(
        select(SpatialSource).where(
            SpatialSource.min_lat <= max_lat,
            SpatialSource.max_lat >= min_lat,
            SpatialSource.min_lon <= max_lon,
            SpatialSource.max_lon >= min_lon,
        )
    ).all()

    # 4. Query SilentRegions intersecting bounding box
    silent_regions = session.scalars(
        select(SilentRegion).where(
            SilentRegion.min_lat <= max_lat,
            SilentRegion.max_lat >= min_lat,
            SilentRegion.min_lon <= max_lon,
            SilentRegion.max_lon >= min_lon,
            SilentRegion.is_active.is_(True),
        )
    ).all()

    # 5. Query SimulationScenarios intersecting bounding box
    scenarios = session.scalars(
        select(SimulationScenario).where(
            SimulationScenario.min_lat <= max_lat,
            SimulationScenario.max_lat >= min_lat,
            SimulationScenario.min_lon <= max_lon,
            SimulationScenario.max_lon >= min_lon,
        )
    ).all()

    duration_seconds = round(time.perf_counter() - start_time, 4)

    return {
        "benchmark_duration_seconds": duration_seconds,
        "under_1s_target_met": duration_seconds < 1.0,
        "counts": {
            "events": len(events),
            "forecasts": len(forecasts),
            "sources": len(sources),
            "silent_regions": len(silent_regions),
            "scenarios": len(scenarios),
        },
        "results": {
            "events": [event.as_dict for event in events],
            "forecasts": [forecast.as_dict for forecast in forecasts],
            "sources": [source.as_dict for source in sources],
            "silent_regions": [region.as_dict for region in silent_regions],
            "scenarios": [scenario.as_dict for scenario in scenarios],
        },
    }
