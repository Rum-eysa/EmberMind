"""EM-078 silent-zone confidence panel tests (Epic E8).

The panel grades every active silent region by how much live fire data
contradicts it, buckets the score into high / moderate / low bands and lets the
operator filter the sorted list. These tests pin the deterministic derivation,
the band filter, the ordering and the read-only HTTP endpoints.
"""
from src.models.spatial import FireEvent, SilentRegion
from src.services.silent_zone_panel import (
    SILENT_ZONE_ATTRIBUTION,
    SILENT_ZONE_PERSISTENCE,
    silent_zone_report,
    zone_config,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Threshold stub so band boundaries are exercised explicitly."""

    def __init__(self, high=0.75, moderate=0.40, far=25.0):
        self.SILENT_ZONE_HIGH_CONFIDENCE = high
        self.SILENT_ZONE_MODERATE_CONFIDENCE = moderate
        self.SILENT_ZONE_PROXIMITY_FAR_KM = far


def _add_region(session, name, min_lat, max_lat, min_lon, max_lon, is_active=True):
    session.add(
        SilentRegion(
            region_name=name,
            reason="test bölge",
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
            geometry_wkt="",
            is_active=is_active,
        )
    )


def _add_fire(session, key, lat, lon, status="active"):
    session.add(
        FireEvent(
            event_key=key,
            name=key,
            latitude=lat,
            longitude=lon,
            min_lat=lat - 0.01,
            max_lat=lat + 0.01,
            min_lon=lon - 0.01,
            max_lon=lon + 0.01,
            geometry_wkt="",
            severity="high",
            status=status,
            started_at=utc_now(),
            source="manual",
        )
    )


def _seed_three_bands(session):
    """Remote (high), Near-fire (moderate) and On-fire (low) silent regions."""
    # A far-away zone with no fire within the proximity radius -> high.
    _add_region(session, "RemoteZone", 39.5, 39.6, 27.0, 27.1)
    # A zone holding an active fire at its centroid -> hard contradiction -> low.
    _add_region(session, "OnFireZone", 37.99, 38.01, 27.99, 28.01)
    _add_fire(session, "F-ON", 38.0, 28.0)
    # A zone whose centroid sits ~5 km from a nearby (non-overlapping) fire.
    _add_region(session, "NearZone", 38.49, 38.51, 28.49, 28.51)
    _add_fire(session, "F-NEAR", 38.545, 28.5)
    session.flush()


# --------------------------------------------------------------------------- #
# Confidence derivation + banding
# --------------------------------------------------------------------------- #
def test_no_fires_all_regions_high(session):
    _add_region(session, "Alpha", 38.0, 38.1, 28.0, 28.1)
    _add_region(session, "Beta", 39.0, 39.1, 27.0, 27.1)
    session.flush()
    report = silent_zone_report(session, _Settings())
    assert report["active_fire_count"] == 0
    assert report["count"] == 2
    bands = {r["region_name"]: r["confidence_band"] for r in report["regions"]}
    assert bands == {"Alpha": "high", "Beta": "high"}
    assert all(r["confidence"] == 1.0 for r in report["regions"])


def test_fire_inside_bbox_is_low_contradiction(session):
    _add_region(session, "OnFireZone", 37.99, 38.01, 27.99, 28.01)
    _add_fire(session, "F-ON", 38.0, 28.0)
    session.flush()
    report = silent_zone_report(session, _Settings())
    zone = report["regions"][0]
    assert zone["overlapping_fire_count"] == 1
    assert zone["confidence_band"] == "low"
    assert zone["confidence"] <= 0.05


def test_nearby_fire_erodes_to_moderate(session):
    # Centroid (38.5, 28.5); fire ~5 km north, outside the bbox (max_lat 38.51).
    _add_region(session, "NearZone", 38.49, 38.51, 28.49, 28.51)
    _add_fire(session, "F-NEAR", 38.545, 28.5)
    session.flush()
    report = silent_zone_report(session, _Settings())
    zone = report["regions"][0]
    assert zone["overlapping_fire_count"] == 0
    assert zone["nearest_fire_km"] is not None
    assert 0.0 < zone["nearest_fire_km"] < 25.0
    assert zone["confidence_band"] == "moderate"


def test_far_fire_beyond_radius_keeps_high(session):
    _add_region(session, "RemoteZone", 39.5, 39.6, 27.0, 27.1)
    # ~110 km away -> no proximity penalty.
    _add_fire(session, "F-FAR", 38.5, 27.05)
    session.flush()
    report = silent_zone_report(session, _Settings(far=25.0))
    zone = report["regions"][0]
    assert zone["confidence_band"] == "high"
    assert zone["confidence"] == 1.0


def test_non_active_fire_does_not_contradict(session):
    _add_region(session, "QuietZone", 37.99, 38.01, 27.99, 28.01)
    _add_fire(session, "F-CONTAINED", 38.0, 28.0, status="contained")
    session.flush()
    report = silent_zone_report(session, _Settings())
    assert report["active_fire_count"] == 0
    assert report["regions"][0]["confidence_band"] == "high"


# --------------------------------------------------------------------------- #
# Sorting + band filter
# --------------------------------------------------------------------------- #
def test_report_is_sorted_by_confidence_desc(session):
    _seed_three_bands(session)
    report = silent_zone_report(session, _Settings())
    confidences = [r["confidence"] for r in report["regions"]]
    assert confidences == sorted(confidences, reverse=True)
    names = [r["region_name"] for r in report["regions"]]
    assert names == ["RemoteZone", "NearZone", "OnFireZone"]


def test_band_counts_cover_all_regions(session):
    _seed_three_bands(session)
    report = silent_zone_report(session, _Settings())
    assert report["band_counts"] == {"high": 1, "moderate": 1, "low": 1}
    assert report["count"] == 3


def test_confidence_filter_keeps_only_that_band(session):
    _seed_three_bands(session)
    high = silent_zone_report(session, _Settings(), confidence="high")
    assert high["filter"] == "high"
    assert [r["region_name"] for r in high["regions"]] == ["RemoteZone"]

    low = silent_zone_report(session, _Settings(), confidence="low")
    assert [r["region_name"] for r in low["regions"]] == ["OnFireZone"]


def test_filter_is_case_insensitive(session):
    _seed_three_bands(session)
    report = silent_zone_report(session, _Settings(), confidence=" HIGH ")
    assert report["filter"] == "high"
    assert report["count"] == 1


def test_unknown_filter_returns_all_and_is_reported(session):
    _seed_three_bands(session)
    report = silent_zone_report(session, _Settings(), confidence="bogus")
    assert report["filter"] is None
    assert report["requested_filter"] == "bogus"
    assert report["count"] == 3


def test_inactive_regions_are_excluded(session):
    _add_region(session, "Active", 38.0, 38.1, 28.0, 28.1, is_active=True)
    _add_region(session, "Retired", 38.5, 38.6, 28.5, 28.6, is_active=False)
    session.flush()
    report = silent_zone_report(session, _Settings())
    names = [r["region_name"] for r in report["regions"]]
    assert names == ["Active"]
    assert report["count_active_regions"] == 1


def test_report_payload_metadata(session):
    _seed_three_bands(session)
    report = silent_zone_report(session, _Settings())
    assert report["panel"] == "silent_zone_panel"
    assert report["attribution"] == SILENT_ZONE_ATTRIBUTION
    assert report["persistence"] == SILENT_ZONE_PERSISTENCE
    assert report["thresholds"]["high_cutoff"] == 0.75


# --------------------------------------------------------------------------- #
# Config payload
# --------------------------------------------------------------------------- #
def test_zone_config_lists_three_bands():
    config = zone_config(_Settings())
    codes = [band["code"] for band in config["bands"]]
    assert codes == ["high", "moderate", "low"]
    assert config["bands"][0]["min_confidence"] == 0.75
    assert config["persistence"] == SILENT_ZONE_PERSISTENCE


def test_zone_config_defaults_without_settings():
    config = zone_config()
    assert config["proximity_far_km"] == 25.0
    assert config["overlap_penalty"] == 0.6


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_lists_silent_zones(client, session):
    _seed_three_bands(session)
    session.commit()
    resp = client.get("/api/v1/silent-zones")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "silent_zone_panel"
    assert body["count"] == 3
    assert [r["region_name"] for r in body["regions"]][0] == "RemoteZone"


def test_endpoint_band_filter(client, session):
    _seed_three_bands(session)
    session.commit()
    resp = client.get("/api/v1/silent-zones", params={"confidence": "high"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["filter"] == "high"
    assert body["count"] == 1


def test_endpoint_config(client):
    resp = client.get("/api/v1/silent-zones/config")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["bands"]) == 3
