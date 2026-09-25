"""VIIRS/MODIS multi-satellite merge, latency and deduplication tests (EM-012)."""
from datetime import datetime

import pytest

from src.models.fire import FireCluster, FireObservation
from src.services.firms import FirmsClient, NormalizedFire
from src.services.satellite_merge import (
    build_satellite_clients,
    deduplicate_detections,
    fetch_all_sources,
    ingest_satellite_observations,
    merge_satellite_detections,
)

VIIRS_CSV = """latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp,updated
38.9000,27.5000,2026-09-24,1200,Suomi NPP,VIIRS,nominal,12.5,2026-09-24 12:35:00
"""

MODIS_CSV = """latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp,updated
38.9010,27.5010,2026-09-24,1230,Terra,MODIS,80,30.0,2026-09-24 13:20:00
"""

CSV_BY_SOURCE = {
    "VIIRS_SNPP_NRT": VIIRS_CSV,
    "MODIS_Terra_CorrectedAnomalies": MODIS_CSV,
}


class Response:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def detection(
    source_id: str,
    satellite: str,
    instrument: str,
    latitude: float = 38.9,
    longitude: float = 27.5,
    observed_at: datetime | None = None,
    frp: float | None = 10.0,
    product: str | None = None,
    published_at: datetime | None = None,
) -> NormalizedFire:
    """Build a detection on the shared VIIRS/MODIS schema."""
    return NormalizedFire(
        source_id=source_id,
        latitude=latitude,
        longitude=longitude,
        observed_at=observed_at or datetime(2026, 9, 24, 12),
        frp=frp,
        confidence=None,
        satellite=satellite,
        instrument=instrument,
        product=product,
        published_at=published_at,
    )


def test_viirs_and_modis_products_share_one_common_schema(monkeypatch):
    def fake_get(url, **kwargs):
        # URL shape: .../area/csv/{api_key}/{source}/{bbox}/{days}
        source = url.split("/area/csv/")[1].split("/")[1]
        return Response(CSV_BY_SOURCE[source])

    monkeypatch.setattr("src.services.firms.requests.get", fake_get)

    viirs = FirmsClient("key", "VIIRS_SNPP_NRT", "25,35,45,43").fetch()
    modis = FirmsClient("key", "MODIS_Terra_CorrectedAnomalies", "25,35,45,43").fetch()

    assert type(viirs[0]) is type(modis[0]) is NormalizedFire
    assert viirs[0].product == "VIIRS_SNPP_NRT"
    assert modis[0].product == "MODIS_Terra_CorrectedAnomalies"
    assert viirs[0].published_at == datetime(2026, 9, 24, 12, 35)
    assert modis[0].published_at == datetime(2026, 9, 24, 13, 20)


def test_latency_is_minutes_between_overpass_and_publication():
    item = detection(
        "v1",
        "Suomi NPP",
        "VIIRS",
        published_at=datetime(2026, 9, 24, 12, 35),
    )

    assert item.latency_minutes == 35.0


def test_overlapping_modis_detection_is_deduplicated_in_favor_of_viirs():
    viirs = detection(
        "v1", "Suomi NPP", "VIIRS", published_at=datetime(2026, 9, 24, 12, 35)
    )
    modis = detection(
        "m1", "Terra", "MODIS", latitude=38.901, longitude=27.501, frp=30.0
    )

    kept, duplicates = deduplicate_detections([modis, viirs])

    assert [item.source_id for item in kept] == ["v1"]
    assert [(pair.dropped.source_id, pair.kept.source_id) for pair in duplicates] == [
        ("m1", "v1")
    ]


def test_distant_detections_are_not_merged():
    viirs = detection("v1", "Suomi NPP", "VIIRS")
    other = detection("m1", "Terra", "MODIS", latitude=39.9, longitude=28.5)

    kept, duplicates = deduplicate_detections([viirs, other])

    assert len(kept) == 2
    assert duplicates == []


def test_detections_outside_the_time_window_are_not_merged():
    viirs = detection("v1", "Suomi NPP", "VIIRS")
    late_modis = detection(
        "m1", "Terra", "MODIS", observed_at=datetime(2026, 9, 24, 18)
    )

    kept, duplicates = deduplicate_detections(
        [viirs, late_modis], radius_km=2.0, time_window_minutes=180
    )

    assert len(kept) == 2
    assert duplicates == []


def test_merge_reports_per_product_counts_and_duplicates():
    viirs = detection("v1", "Suomi NPP", "VIIRS", product="VIIRS_SNPP_NRT")
    modis = detection(
        "m1", "Terra", "MODIS", latitude=38.901, longitude=27.501, product="MODIS_T"
    )
    far_modis = detection(
        "m2", "Terra", "MODIS", latitude=39.5, longitude=28.9, product="MODIS_T"
    )

    merged = merge_satellite_detections(
        {
            "VIIRS_SNPP_NRT": [viirs],
            "MODIS_Terra_CorrectedAnomalies": [modis, far_modis],
        }
    )

    assert merged.per_source_counts == {
        "VIIRS_SNPP_NRT": 1,
        "MODIS_Terra_CorrectedAnomalies": 2,
    }
    assert merged.duplicates_removed == 1
    assert len(merged.observations) == 2
    assert merged.sources == ["Suomi NPP", "Terra"]


def test_ingest_persists_latency_sources_and_dedup_counts(api):
    viirs = detection(
        "v1",
        "Suomi NPP",
        "VIIRS",
        product="VIIRS_SNPP_NRT",
        published_at=datetime(2026, 9, 24, 12, 35),
    )
    modis = detection(
        "m1",
        "Terra",
        "MODIS",
        latitude=38.901,
        longitude=27.501,
        product="MODIS_Terra_CorrectedAnomalies",
    )
    merged = merge_satellite_detections(
        {"VIIRS_SNPP_NRT": [viirs], "MODIS_Terra_CorrectedAnomalies": [modis]}
    )

    database = api.state.database
    database.create_all()
    with database.session() as session:
        result = ingest_satellite_observations(session, merged, cluster_radius_km=2.0)
        assert result["observations"] == 1
        assert result["clusters"] == 1
        assert result["duplicates_removed"] == 1

        cluster = session.query(FireCluster).one()
        assert cluster.sources == "Suomi NPP"
        assert cluster.latency_minutes == 35.0
        assert cluster.deduplicated_count == 1

        observation = session.query(FireObservation).one()
        assert observation.product == "VIIRS_SNPP_NRT"
        assert observation.latency_minutes == 35.0
        assert observation.as_dict["published_at"] == "2026-09-24T12:35:00Z"


def test_fires_endpoint_exposes_latency_and_sources(client, api):
    database = api.state.database
    database.create_all()
    with database.session() as session:
        session.add(
            FireCluster(
                cluster_key="merged-1",
                latitude=38.9,
                longitude=27.5,
                observation_count=2,
                max_frp=30.0,
                first_seen_at=datetime(2026, 9, 24, 12),
                last_seen_at=datetime(2026, 9, 24, 12, 30),
                sources="Suomi NPP;Terra",
                latency_minutes=35.0,
                deduplicated_count=1,
            )
        )

    response = client.get("/api/v1/fires")

    assert response.status_code == 200
    fire = response.json()["fires"][0]
    assert fire["sources"] == "Suomi NPP;Terra"
    assert fire["latency_minutes"] == 35.0
    assert fire["deduplicated_count"] == 1


def test_build_satellite_clients_creates_one_client_per_product():
    class Settings:
        FIRMS_API_KEY = "key"
        FIRMS_SOURCES = ["VIIRS_SNPP_NRT", "MODIS_Terra_CorrectedAnomalies"]
        FIRMS_BBOX = "25,35,45,43"
        FIRMS_DAYS = 1

    clients = build_satellite_clients(Settings())

    assert [client.source for client in clients] == Settings.FIRMS_SOURCES


def test_build_satellite_clients_falls_back_to_legacy_source():
    class Settings:
        FIRMS_API_KEY = "key"
        FIRMS_SOURCE = "VIIRS_SNPP_NRT"
        FIRMS_BBOX = "25,35,45,43"
        FIRMS_DAYS = 1

    clients = build_satellite_clients(Settings())

    assert [client.source for client in clients] == ["VIIRS_SNPP_NRT"]


def test_partial_product_outage_does_not_fail_the_sync():
    class FailingClient:
        source = "MODIS_Aqua_CorrectedAnomalies"

        def fetch(self):
            raise RuntimeError("upstream 503")

    class WorkingClient:
        source = "VIIRS_SNPP_NRT"

        def fetch(self):
            return [detection("v1", "Suomi NPP", "VIIRS")]

    detections, failed = fetch_all_sources([FailingClient(), WorkingClient()])

    assert list(detections) == ["VIIRS_SNPP_NRT"]
    assert failed == ["MODIS_Aqua_CorrectedAnomalies"]


def test_all_products_failing_raises(api):
    from src.models.fire import FirmsSyncStatus
    from src.services.fire_sync import sync_firms
    from src.services.firms import FirmsSourceError

    class Settings:
        FIRMS_API_KEY = ""
        FIRMS_SOURCES = ["VIIRS_SNPP_NRT"]
        FIRMS_BBOX = "25,35,45,43"
        FIRMS_DAYS = 1
        FIRMS_CLUSTER_RADIUS_KM = 2.0
        SATELLITE_DEDUP_TIME_WINDOW_MINUTES = 180

    database = api.state.database
    database.create_all()
    session = database.session_factory()
    try:
        with pytest.raises(FirmsSourceError, match="All FIRMS satellite products"):
            sync_firms(session, Settings())
        session.commit()
        status = session.query(FirmsSyncStatus).one()
        assert "All FIRMS satellite products" in status.last_error
    finally:
        session.close()
