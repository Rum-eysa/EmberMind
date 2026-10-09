#!/usr/bin/env python3
"""EM-109: Demo ortamı veritabanı tohumlama betiği.

Docker compose demo profilinde konteyner başlangıcında çalışır.
SQLite'a tablo şemasını + sentetik senaryo verisini yazar.
"""
import json
import math
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.models  # noqa: F401,E402  (populate Base.metadata for a full reset)
from src.config.settings import Config  # noqa: E402
from src.database import Database  # noqa: E402
from src.models.exposure import ExposedAsset  # noqa: E402
from src.models.road_network import RoadSegment  # noqa: E402
from src.models.spatial import FireForecast  # noqa: E402
from src.services.auth import bootstrap_demo_user, demo_credentials  # noqa: E402
from src.services.synthetic import (  # noqa: E402
    SYNTHETIC_LABEL,
    build_dataset,
    persist_dataset,
    record_run,
)
from src.utils.timeutils import utc_now  # noqa: E402

# EM-023 demo exposure: a labelled placeholder forecast (concentric risk-zone
# discs) plus settlements / an energy line / road segments placed inside it, so
# the threat-analysis list and map layer are demonstrable offline. The analysis
# path itself (shapely intersection with the stored horizon polygons) is real.
DEMO_HORIZON_RADIUS_KM = {30: 0.8, 60: 1.6, 120: 3.0}


def _disc_wkt(lat: float, lon: float, radius_km: float, vertices: int = 24) -> str:
    """A closed circular polygon (lon-lat WKT) of ``radius_km`` around a point."""
    d_lat = radius_km / 111.0
    d_lon = radius_km / (111.0 * math.cos(math.radians(lat)))
    points = []
    for i in range(vertices):
        angle = 2 * math.pi * i / vertices
        y = lat + d_lat * math.sin(angle)
        x = lon + d_lon * math.cos(angle)
        points.append(f"{x:.6f} {y:.6f}")
    points.append(points[0])
    return "POLYGON((" + ",".join(points) + "))"


def _offset(
    lat: float, lon: float, north_km: float, east_km: float
) -> tuple[float, float]:
    """Return a coordinate offset from (lat, lon) in kilometres."""
    d_lat = north_km / 111.0
    d_lon = east_km / (111.0 * math.cos(math.radians(lat)))
    return round(lat + d_lat, 6), round(lon + d_lon, 6)


def _add_settlement(session, key, name, place, population, lat, lon):
    """Insert one demo settlement point asset (idempotent by key)."""
    row = session.query(ExposedAsset).filter_by(asset_key=key).first()
    if row is None:
        row = ExposedAsset(asset_key=key)
        session.add(row)
    row.asset_type = "settlement"
    row.name = name
    row.osm_id = None
    row.latitude = lat
    row.longitude = lon
    row.min_lat = row.max_lat = lat
    row.min_lon = row.max_lon = lon
    row.geometry_wkt = f"POINT({lon:.6f} {lat:.6f})"
    row.tags_json = json.dumps({"place": place, "population": population})
    row.source = "demo-fallback (EM-023)"
    row.fetched_at = utc_now()


def _add_power_line(session, key, name, lat, lon, length_km):
    """Insert one demo energy-line asset crossing near the fire."""
    end_lat, end_lon = _offset(lat, lon, 0.0, length_km)
    wkt = f"LINESTRING({lon:.6f} {lat:.6f},{end_lon:.6f} {end_lat:.6f})"
    row = session.query(ExposedAsset).filter_by(asset_key=key).first()
    if row is None:
        row = ExposedAsset(asset_key=key)
        session.add(row)
    row.asset_type = "power_line"
    row.name = name
    row.osm_id = None
    row.latitude = lat
    row.longitude = lon
    row.min_lat = row.max_lat = lat
    row.min_lon = min(lon, end_lon)
    row.max_lon = max(lon, end_lon)
    row.geometry_wkt = wkt
    row.tags_json = json.dumps({"power": "line", "voltage": "154000"})
    row.source = "demo-fallback (EM-023)"
    row.fetched_at = utc_now()


def _add_road(session, key, name, highway, lat, lon, length_km, way_id, from_id, to_id):
    """Insert one demo road segment so road exposure is visible offline."""
    end_lat, end_lon = _offset(lat, lon, length_km, 0.0)
    row = session.query(RoadSegment).filter_by(segment_key=key).first()
    if row is None:
        row = RoadSegment(segment_key=key)
        session.add(row)
    row.osm_way_id = way_id
    row.from_node_id = from_id
    row.to_node_id = to_id
    row.from_lat = lat
    row.from_lon = lon
    row.to_lat = end_lat
    row.to_lon = end_lon
    row.name = name
    row.highway = highway
    row.length_km = length_km
    row.max_speed_kmh = 90.0
    row.one_way = False
    row.fetched_at = utc_now()
    row.source = "demo-fallback (EM-023)"


def seed_exposure_demo(session, fire: dict) -> dict:
    """Seed a labelled EM-023 demo forecast plus exposed assets around a fire."""
    lat = float(fire["latitude"])
    lon = float(fire["longitude"])
    event_key = str(fire["event_key"])
    started = utc_now()
    stored_inputs = json.dumps(
        {
            "air_temp_c": 32.0,
            "relative_humidity_pct": 22.0,
            "fuel_moisture_pct": 8.0,
            "wind_speed_kmh": 35.0,
            "wind_from_deg": 45.0,
            "slope_deg": 12.0,
            "aspect_deg": 180.0,
            "fuel_model": "demo",
            # P2 marker: these are demo placeholders, not real model output.
            "demo_forecast": True,
        },
        sort_keys=True,
    )
    forecasts = 0
    for horizon, radius in DEMO_HORIZON_RADIUS_KM.items():
        exists = (
            session.query(FireForecast)
            .filter_by(event_key=event_key, horizon_minutes=horizon)
            .first()
        )
        if exists is not None:
            continue
        session.add(
            FireForecast(
                event_key=event_key,
                model_name="rothermel_v1_demo",
                latitude=lat,
                longitude=lon,
                predicted_area_ha=round(math.pi * radius * radius * 100.0, 3),
                geometry_wkt=_disc_wkt(lat, lon, radius),
                forecast_for=started + timedelta(minutes=horizon),
                horizon_minutes=horizon,
                rate_of_spread_m_per_min=round(radius * 1000.0 / horizon, 3),
                spread_direction_deg=45.0,
                inputs_json=stored_inputs,
            )
        )
        forecasts += 1

    # Place settlements toward the spread head (south-west for wind_from=45)
    # and one in the ignition core, so each forecast horizon reaches at least
    # one settlement regardless of the exact ellipse size.
    v1_lat, v1_lon = _offset(lat, lon, -0.1, -0.1)  # ignition core -> T+30
    t1_lat, t1_lon = _offset(lat, lon, -0.5, -0.5)  # near head -> T+30/60
    h1_lat, h1_lon = _offset(lat, lon, -0.9, -0.9)  # further head -> T+60/120
    _add_settlement(
        session, "demo-exposure-v1", "Çamköy", "village", 420, v1_lat, v1_lon
    )
    _add_settlement(
        session, "demo-exposure-t1", "Zeytindağ", "town", 3200, t1_lat, t1_lon
    )
    _add_settlement(
        session, "demo-exposure-h1", "Su Deposu mevkii", "hamlet", 60, h1_lat, h1_lon
    )
    _add_power_line(session, "demo-exposure-line1", "154kV Ege hattı", lat, lon, 2.0)
    _add_road(
        session,
        "demo-exposure-road1",
        "D-550",
        "primary",
        lat,
        lon,
        1.5,
        900001,
        910001,
        910002,
    )
    _add_road(
        session,
        "demo-exposure-road2",
        "Çamköy bağlantı yolu",
        "secondary",
        t1_lat,
        t1_lon,
        0.9,
        900002,
        910003,
        910004,
    )
    session.flush()
    return {
        "forecasts": forecasts,
        "settlements": 3,
        "power_lines": 1,
        "roads": 2,
    }


def seed_demo(database: Database, seed: int, preset: str, reset: bool = False) -> dict:
    """Reset (optional) then seed the demo DB with a labelled synthetic scenario.

    When ``reset`` is true every registered table is dropped and recreated so
    the demo starts from a clean slate; otherwise existing rows are upserted
    idempotently. Returns a report dict describing what was written.
    """
    if reset:
        database.reset_all()
    else:
        database.create_all()

    dataset = build_dataset(seed, preset=preset)
    settings = Config()
    with database.session() as session:
        counts = persist_dataset(session, dataset)
        record_run(session, dataset, persisted=True, preset=preset)
        exposure = seed_exposure_demo(session, dataset["fire"])
        # EM-098: provision one clearly-labelled demo operator only when the
        # user table is empty, so the login flow is real end to end offline.
        demo_email, _ = demo_credentials(settings)
        created = bootstrap_demo_user(session, settings) is not None
        session.commit()

    return {
        "reset": reset,
        "seed": seed,
        "preset": preset,
        "scenario_tag": dataset["meta"]["scenario_tag"],
        "counts": counts,
        "exposure": exposure,
        "demo_account": {"email": demo_email, "created": created},
        "synthetic_label": SYNTHETIC_LABEL,
    }


def _reset_requested(argv: list[str]) -> bool:
    """True when ``--reset`` is passed or the DEMO_RESET env is truthy."""
    if "--reset" in argv:
        return True
    return os.getenv("DEMO_RESET", "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> None:
    """Seed the demo database with base tables + synthetic scenario (EM-106)."""
    args = list(sys.argv[1:] if argv is None else argv)
    db_path = os.getenv("DATABASE_URL", "sqlite:///instance/wildfire-demo.db")
    seed = int(os.getenv("DEMO_SYNTHETIC_SEED", "7"))
    preset = os.getenv("DEMO_SYNTHETIC_PRESET", "standart")
    reset = _reset_requested(args)

    # Ensure SQLite parent directory exists (CI-safe)
    if db_path.startswith("sqlite:///"):
        rel = db_path.replace("sqlite:///", "")
        parent = os.path.dirname(rel)
        if parent:
            os.makedirs(parent, exist_ok=True)

    print(f"[demo_seed] DB: {db_path} reset={reset}")
    database = Database(db_path)
    report = seed_demo(database, seed, preset, reset=reset)

    print(
        f"[demo_seed] Sentetik senaryo: seed={seed} preset={preset} "
        f"tag={report['scenario_tag']} counts={report['counts']}"
    )
    print(f"[demo_seed] EM-023 maruziyet demosu: {report['exposure']}")
    print(f"[demo_seed] {report['synthetic_label']}")
    print("[demo_seed] Tamamlandı.")


if __name__ == "__main__":
    main()
