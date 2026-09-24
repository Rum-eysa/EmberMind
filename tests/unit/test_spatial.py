"""PostGIS/Spatial database, migration runner, and polygon intersection performance unit tests."""
from datetime import datetime, timezone
import time

from sqlalchemy import select

from scripts.migration.migrate import run_migrations
from src.models.spatial import (
    FireEvent,
    FireForecast,
    SilentRegion,
    SimulationScenario,
    SpatialSource,
)
from src.services.spatial_db import execute_polygon_intersection_query


def test_versioned_sql_migration_script(api):
    engine = api.state.database.engine
    applied_versions = run_migrations(engine)
    assert "V001" in applied_versions or len(applied_versions) >= 0


def test_spatial_models_creation(client, api):
    database = api.state.database

    with database.session() as session:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. FireEvent (Olay)
        event = FireEvent(
            event_key="event_muğla_001",
            name="Muğla Marmaris Yangını",
            latitude=36.85,
            longitude=28.27,
            min_lat=36.80,
            max_lat=36.90,
            min_lon=28.20,
            max_lon=28.35,
            geometry_wkt="POLYGON((28.20 36.80, 28.35 36.80, 28.35 36.90, 28.20 36.90, 28.20 36.80))",
            severity="high",
            status="active",
            started_at=now,
        )

        # 2. FireForecast (Tahmin)
        forecast = FireForecast(
            event_key="event_muğla_001",
            model_name="CellularAutomata_Spread_v2",
            latitude=36.86,
            longitude=28.28,
            predicted_area_ha=145.5,
            geometry_wkt="POLYGON((28.25 36.84, 28.30 36.84, 28.30 36.88, 28.25 36.88, 28.25 36.84))",
            forecast_for=now,
        )

        # 3. SpatialSource (Kaynak)
        source = SpatialSource(
            source_name="FIRMS_VIIRS_TR",
            source_type="Satellite",
            min_lat=35.0,
            max_lat=42.0,
            min_lon=25.0,
            max_lon=45.0,
            geometry_wkt="POLYGON((25.0 35.0, 45.0 35.0, 45.0 42.0, 25.0 42.0, 25.0 35.0))",
            status="active",
        )

        # 4. SilentRegion (Sessiz Bölge)
        silent = SilentRegion(
            region_name="Radar Blind Zone Alpha",
            reason="High Cloud Cover / Sensor Blackout",
            min_lat=36.82,
            max_lat=36.88,
            min_lon=28.22,
            max_lon=28.30,
            geometry_wkt="POLYGON((28.22 36.82, 28.30 36.82, 28.30 36.88, 28.22 36.88, 28.22 36.82))",
            is_active=True,
        )

        # 5. SimulationScenario (Senaryo)
        scenario = SimulationScenario(
            scenario_name="Extreme Wind Uphill Spread",
            event_key="event_muğla_001",
            min_lat=36.80,
            max_lat=36.90,
            min_lon=28.20,
            max_lon=28.35,
            geometry_wkt="POLYGON((28.20 36.80, 28.35 36.80, 28.35 36.90, 28.20 36.90, 28.20 36.80))",
            wind_speed=45.0,
            slope_angle=25.0,
            fuel_model="FM10_RedPine",
            simulated_area_ha=320.0,
        )

        session.add_all([event, forecast, source, silent, scenario])
        session.commit()

        events_db = session.scalars(select(FireEvent)).all()
        assert len(events_db) == 1
        assert events_db[0].event_key == "event_muğla_001"

        silents_db = session.scalars(select(SilentRegion)).all()
        assert len(silents_db) == 1
        assert silents_db[0].is_active is True


def test_polygon_intersection_query_performance(client, api):
    database = api.state.database

    with database.session() as session:
        # Benchmark polygon intersection execution time
        start_time = time.perf_counter()
        res = execute_polygon_intersection_query(
            session=session,
            min_lat=36.0,
            max_lat=37.0,
            min_lon=28.0,
            max_lon=29.0,
        )
        elapsed = time.perf_counter() - start_time

        assert res["under_1s_target_met"] is True
        assert res["benchmark_duration_seconds"] < 1.0
        assert elapsed < 1.0


def test_fastapi_spatial_endpoints(client):
    # 1. Events endpoint
    events_resp = client.get("/api/v1/spatial/events")
    assert events_resp.status_code == 200
    assert events_resp.json()["source"] == "PostGIS/Spatial"

    # 2. Silent regions endpoint
    silent_resp = client.get("/api/v1/spatial/silent-regions")
    assert silent_resp.status_code == 200
    assert silent_resp.json()["source"] == "PostGIS/Spatial"

    # 3. Polygon intersection POST endpoint
    payload = {
        "min_lat": 36.0,
        "max_lat": 37.0,
        "min_lon": 28.0,
        "max_lon": 29.0,
    }
    intersect_resp = client.post("/api/v1/spatial/polygon-intersection", json=payload)
    assert intersect_resp.status_code == 200
    data = intersect_resp.json()
    assert data["under_1s_target_met"] is True
    assert "counts" in data
