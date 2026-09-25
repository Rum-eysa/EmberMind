"""Gelistirme yardimcisi: API'yi EM-012 demo verisiyle yerelde calistirir.

Kullanim:
    python scripts/demo_api.py
    -> http://127.0.0.1:8000/docs (Swagger UI)
     -> http://127.0.0.1:8000/api/v1/fires (birlestirilmis VIIRS/MODIS kumeleri)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import uvicorn  # noqa: E402

from src.fastapi_app import create_fastapi_app  # noqa: E402
from src.models.fire import FireCluster, FireObservation, FirmsSyncStatus  # noqa: E402
from src.utils.timeutils import utc_now  # noqa: E402

api = create_fastapi_app("testing")


def seed_demo_data() -> None:
    """Load a small merged-satellite demo dataset into the in-memory database."""
    database = api.state.database
    database.create_all()
    now = utc_now()
    with database.session() as session:
        session.add(
            FireCluster(
                cluster_key="demo-merged-001",
                latitude=38.9005,
                longitude=27.5005,
                observation_count=2,
                max_frp=30.0,
                first_seen_at=now.replace(hour=12, minute=0, second=0),
                last_seen_at=now.replace(hour=12, minute=30, second=0),
                sources="Suomi NPP;Terra",
                latency_minutes=35.0,
                deduplicated_count=1,
            )
        )
        session.add(
            FireObservation(
                source_id="demo-viirs-001",
                cluster_key="demo-merged-001",
                latitude=38.9000,
                longitude=27.5000,
                observed_at=now.replace(hour=12, minute=0, second=0),
                frp=12.5,
                confidence=50.0,
                satellite="Suomi NPP",
                instrument="VIIRS",
                product="VIIRS_SNPP_NRT",
                published_at=now.replace(hour=12, minute=35, second=0),
                latency_minutes=35.0,
            )
        )
        session.add(
            FireObservation(
                source_id="demo-modis-001",
                cluster_key="demo-merged-001",
                latitude=38.9010,
                longitude=27.5010,
                observed_at=now.replace(hour=12, minute=30, second=0),
                frp=30.0,
                confidence=80.0,
                satellite="Terra",
                instrument="MODIS",
                product="MODIS_Terra_CorrectedAnomalies",
                published_at=now.replace(hour=13, minute=20, second=0),
                latency_minutes=50.0,
            )
        )
        session.add(
            FireCluster(
                cluster_key="demo-modis-only-002",
                latitude=37.2400,
                longitude=28.0600,
                observation_count=1,
                max_frp=18.4,
                first_seen_at=now.replace(hour=14, minute=5, second=0),
                last_seen_at=now.replace(hour=14, minute=5, second=0),
                sources="Aqua",
                latency_minutes=42.0,
                deduplicated_count=0,
            )
        )
        session.add(
            FireObservation(
                source_id="demo-modis-002",
                cluster_key="demo-modis-only-002",
                latitude=37.2400,
                longitude=28.0600,
                observed_at=now.replace(hour=14, minute=5, second=0),
                frp=18.4,
                confidence=90.0,
                satellite="Aqua",
                instrument="MODIS",
                product="MODIS_Aqua_CorrectedAnomalies",
                published_at=now.replace(hour=14, minute=47, second=0),
                latency_minutes=42.0,
            )
        )
        session.add(
            FirmsSyncStatus(
                source="NASA FIRMS",
                last_success_at=now,
                last_observation_count=3,
            )
        )


if __name__ == "__main__":
    # The app defines a custom lifespan, so seed up-front (the in-memory
    # SQLite uses StaticPool, so the data survives across sessions inside
    # this process).
    seed_demo_data()
    uvicorn.run(api, host="127.0.0.1", port=8000, log_level="info")
