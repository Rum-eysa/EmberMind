"""NASA FIRMS ingestion tests."""
from datetime import datetime

import pytest

from src.services.firms import (
    FirmsClient,
    FirmsSourceError,
    NormalizedFire,
    cluster_observations,
    ingest_firms,
)
from src.models.fire import FireCluster, FireObservation


FIRMS_CSV = """latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp
39.9000,32.8000,2026-09-24,1200,Suomi NPP,VIIRS,nominal,12.5
39.9010,32.8010,2026-09-24,1205,Suomi NPP,VIIRS,80,10.0
40.5000,33.5000,2026-09-24,1200,Suomi NPP,VIIRS,high,20.0
"""


class Response:
    text = FIRMS_CSV

    def raise_for_status(self):
        return None


def test_firms_csv_is_normalized(monkeypatch):
    monkeypatch.setattr(
        "src.services.firms.requests.get", lambda *args, **kwargs: Response()
    )

    observations = FirmsClient("key", "VIIRS_SNPP_NRT", "25,35,45,43").fetch()

    assert len(observations) == 3
    assert observations[0].latitude == 39.9
    assert observations[0].confidence == 50.0
    assert observations[0].observed_at == datetime(2026, 9, 24, 12, 0)


def test_nearby_observations_are_clustered():
    observations = [
        NormalizedFire(
            "one", 39.9000, 32.8000, datetime(2026, 9, 24, 12), 10, 80, None, None
        ),
        NormalizedFire(
            "two", 39.9010, 32.8010, datetime(2026, 9, 24, 12, 5), 12, 80, None, None
        ),
        NormalizedFire(
            "three", 40.5, 33.5, datetime(2026, 9, 24, 12), 20, 80, None, None
        ),
    ]

    clusters = cluster_observations(observations)

    assert sorted(len(group) for _, group in clusters) == [1, 2]


def test_missing_api_key_fails_before_request():
    with pytest.raises(FirmsSourceError, match="FIRMS_API_KEY"):
        FirmsClient("", "VIIRS_SNPP_NRT", "25,35,45,43").fetch()


def test_ingest_reuses_nearby_cluster_on_later_fetch(api):
    first = NormalizedFire(
        "one", 39.9000, 32.8000, datetime(2026, 9, 24, 12), 10, 80, None, None
    )
    later = NormalizedFire(
        "two", 39.9010, 32.8010, datetime(2026, 9, 24, 12, 5), 12, 80, None, None
    )

    class Client:
        def __init__(self, observations):
            self.observations = observations

        def fetch(self):
            return self.observations

    database = api.state.database
    database.create_all()
    with database.session() as session:
        assert ingest_firms(session, Client([first])) == {
            "observations": 1,
            "clusters": 1,
        }
    with database.session() as session:
        assert ingest_firms(session, Client([later])) == {
            "observations": 1,
            "clusters": 0,
        }
        assert len(session.query(FireCluster).all()) == 1
        assert len(session.query(FireObservation).all()) == 2
