"""CORINE Land Cover to fuel model conversion unit tests."""
from datetime import datetime, timezone

from sqlalchemy import select

from src.models.fire import FireCluster
from src.models.land_cover import LandCoverDataPoint
from src.services.land_cover import (
    LandCoverFuelService,
    sync_land_cover_for_clusters,
)


def test_corine_mapping_supported_classes():
    service = LandCoverFuelService()

    # 1. Kızılçam (Coniferous forest - 312)
    lc, fuel, spread = service.map_corine_to_fuel(312)
    assert lc == "kızılçam"
    assert fuel == "FM10_RedPine"
    assert spread > 1.0

    # 2. Karma orman (Mixed forest - 313)
    lc, fuel, spread = service.map_corine_to_fuel(313)
    assert lc == "karma orman"
    assert fuel == "FM8_MixedForest"
    assert spread > 1.0

    # 3. Maki (Maquis / Sclerophyllous - 323)
    lc, fuel, spread = service.map_corine_to_fuel(323)
    assert lc == "maki"
    assert fuel == "FM4_Maquis"
    assert spread > 1.0

    # 4. Tarım/Zeytin (Olive groves - 223)
    lc, fuel, spread = service.map_corine_to_fuel(223)
    assert lc == "tarım/zeytin"
    assert fuel == "FM1_Agriculture"
    assert spread > 0.0


def test_unclassified_corine_code_fallback():
    service = LandCoverFuelService()

    # Unmapped code
    lc, fuel, spread = service.map_corine_to_fuel(9999)
    assert lc == "bilinmiyor"
    assert fuel == "varsayilan"
    assert spread == 1.0

    # None code
    lc, fuel, spread = service.map_corine_to_fuel(None)
    assert lc == "bilinmiyor"
    assert fuel == "varsayilan"
    assert spread == 1.0


def test_sync_land_cover_for_clusters_persists_to_db(client, api):
    database = api.state.database

    with database.session() as session:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cluster = FireCluster(
            cluster_key="cluster_lc_test_1",
            latitude=39.9,
            longitude=32.8,
            observation_count=3,
            max_frp=85.0,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(cluster)
        session.commit()

        result = sync_land_cover_for_clusters(session, api.state.settings)
        assert result["clusters_processed"] == 1
        assert result["land_cover_points_saved"] == 1

        points = session.scalars(select(LandCoverDataPoint)).all()
        assert len(points) == 1
        assert points[0].cluster_key == "cluster_lc_test_1"
        assert points[0].land_cover_class in [
            "kızılçam",
            "karma orman",
            "maki",
            "tarım/zeytin",
            "bilinmiyor",
        ]
        assert points[0].fuel_model != ""


def test_synthetic_grid_provenance_is_labelled_honestly():
    """Regression: a coordinate-hash code must not masquerade as real CORINE."""
    service = LandCoverFuelService()
    # No corine_code -> value invented from a coordinate hash.
    invented = service.fetch_land_cover_fuel(36.85, 28.27)
    assert invented.source == "CORINE/synthetic-grid"
    # An explicit code is treated as a real read from the raster.
    real = service.fetch_land_cover_fuel(36.85, 28.27, corine_code=312)
    assert real.source == "CORINE/LandCover"
    assert real.corine_code == 312


def test_fastapi_land_cover_endpoints(client):
    # Sync land cover endpoint
    sync_resp = client.post("/api/v1/land-cover/sync")
    assert sync_resp.status_code == 200
    assert sync_resp.json()["status"] == "ok"

    # Get land cover endpoint
    get_resp = client.get("/api/v1/land-cover")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["source"] == "CORINE/LandCover"
    assert isinstance(data["land_cover_data"], list)
