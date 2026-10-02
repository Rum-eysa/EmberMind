"""EM-037 high-priority silent-region risk tests (Epic E4).

A silent region is graded by how far the *active* fires' spread-forecast polygons
reach into it (risk) multiplied by its EM-078 silence confidence (silence). These
tests pin the deterministic coverage math, the risk x silence ordering, the
high-priority flag (and its silence gate), the containment of the threat to
active fires only, the flagged/limit filters and the read-only HTTP endpoints.
"""
import pytest

from src.models.spatial import FireEvent, FireForecast, SilentRegion
from src.services.silent_region_risk import (
    SILENT_REGION_RISK_ATTRIBUTION,
    SILENT_REGION_RISK_PERSISTENCE,
    SilentRegionRiskError,
    silent_region_risk_config,
    silent_region_risk_report,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Carries both the EM-078 band thresholds and the EM-037 risk thresholds."""

    def __init__(
        self,
        high=0.75,
        moderate=0.40,
        far=25.0,
        min_coverage=0.05,
        min_confidence=0.5,
        max_forecasts=200,
        max_limit=200,
    ):
        self.SILENT_ZONE_HIGH_CONFIDENCE = high
        self.SILENT_ZONE_MODERATE_CONFIDENCE = moderate
        self.SILENT_ZONE_PROXIMITY_FAR_KM = far
        self.SILENT_REGION_RISK_MIN_COVERAGE = min_coverage
        self.SILENT_REGION_RISK_MIN_CONFIDENCE = min_confidence
        self.SILENT_REGION_RISK_MAX_FORECASTS = max_forecasts
        self.SILENT_REGION_RISK_MAX_LIMIT = max_limit


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


def _add_fire(session, key, lat, lon, status="active", severity="high"):
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
            severity=severity,
            status=status,
            started_at=utc_now(),
            source="manual",
        )
    )


def _add_forecast(session, event_key, wkt, horizon=120):
    session.add(
        FireForecast(
            event_key=event_key,
            model_name="test-spread",
            latitude=38.0,
            longitude=28.0,
            predicted_area_ha=100.0,
            geometry_wkt=wkt,
            forecast_for=utc_now(),
            horizon_minutes=horizon,
            rate_of_spread_m_per_min=5.0,
            spread_direction_deg=45.0,
        )
    )


# A silent region bbox and a forecast rectangle that fully engulfs it.
_REGION = (38.0, 38.1, 28.0, 28.1)
_COVER_WKT = "POLYGON((27.9 37.9, 28.3 37.9, 28.3 38.3, 27.9 38.3, 27.9 37.9))"
# Same rectangle narrowed to the west half of the region (lon <= 28.05) -> ~0.5.
_HALF_WKT = "POLYGON((27.99 37.9, 28.05 37.9, 28.05 38.3, 27.99 38.3, 27.99 37.9))"
# A rectangle far to the north-east that never touches the region.
_FAR_WKT = "POLYGON((29.0 39.0, 29.2 39.0, 29.2 39.2, 29.0 39.2, 29.0 39.0))"


def _lookup(report, name):
    return next(r for r in report["regions"] if r["region_name"] == name)


# --------------------------------------------------------------------------- #
# Coverage -> risk degree
# --------------------------------------------------------------------------- #
def test_full_cover_yields_high_priority(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)  # outside the bbox -> stays silent
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    row = _lookup(silent_region_risk_report(session, _Settings()), "QZone")
    assert row["risk_degree"] == 1.0
    assert row["silence_degree"] >= 0.5
    assert row["is_high_priority"] is True
    assert row["worst_threat"]["event_key"] == "F-A"


def test_no_forecast_zero_risk(session):
    _add_region(session, "QZone", *_REGION)
    session.flush()
    report = silent_region_risk_report(session, _Settings())
    row = _lookup(report, "QZone")
    assert row["risk_degree"] == 0.0
    assert row["is_high_priority"] is False
    assert report["summary"]["active_forecast_polygons"] == 0


def test_forecast_missing_region_zero_risk(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 39.5, 29.5)  # far away
    _add_forecast(session, "F-A", _FAR_WKT)
    session.flush()
    row = _lookup(silent_region_risk_report(session, _Settings()), "QZone")
    assert row["risk_degree"] == 0.0
    assert row["worst_threat"] is None


def test_partial_coverage_ratio(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _HALF_WKT)
    session.flush()
    row = _lookup(silent_region_risk_report(session, _Settings()), "QZone")
    assert 0.4 < row["risk_degree"] < 0.6


# --------------------------------------------------------------------------- #
# Silence gate + priority = risk x silence
# --------------------------------------------------------------------------- #
def test_fire_inside_region_breaks_silence_gate(session):
    # Fire centre inside the bbox -> EM-078 confidence collapses -> not silent.
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-ON", 38.05, 28.05)
    _add_forecast(session, "F-ON", _COVER_WKT)
    session.flush()
    row = _lookup(silent_region_risk_report(session, _Settings()), "QZone")
    assert row["risk_degree"] == 1.0
    assert row["silence_degree"] < 0.5
    assert row["is_high_priority"] is False


def test_priority_equals_risk_times_silence(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    row = _lookup(silent_region_risk_report(session, _Settings()), "QZone")
    assert row["priority_score"] == round(row["risk_degree"] * row["silence_degree"], 4)


# --------------------------------------------------------------------------- #
# Active-only containment + graceful bad geometry
# --------------------------------------------------------------------------- #
def test_contained_fire_forecast_ignored(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-OLD", 37.9, 27.9, status="contained")
    _add_forecast(session, "F-OLD", _COVER_WKT)
    session.flush()
    report = silent_region_risk_report(session, _Settings())
    assert report["summary"]["active_forecast_polygons"] == 0
    assert _lookup(report, "QZone")["risk_degree"] == 0.0


def test_unparseable_forecast_geometry_skipped(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", "POINT(28 38)")  # not a polygon
    _add_forecast(session, "F-A", "")  # empty
    session.flush()
    report = silent_region_risk_report(session, _Settings())
    assert report["summary"]["active_forecast_polygons"] == 0


# --------------------------------------------------------------------------- #
# Ordering + filters
# --------------------------------------------------------------------------- #
def test_sort_by_priority_desc(session):
    # Quiet-but-covered (high) vs half-covered (lower risk) vs uncovered.
    _add_region(session, "FullCover", *_REGION)
    _add_region(session, "HalfCover", 38.0, 38.1, 28.2, 28.3)
    _add_region(session, "NoCover", 39.0, 39.1, 27.0, 27.1)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)  # reaches FullCover bbox
    session.flush()
    report = silent_region_risk_report(session, _Settings())
    priorities = [r["priority_score"] for r in report["regions"]]
    assert priorities == sorted(priorities, reverse=True)


def test_flagged_only_keeps_high_priority(session):
    _add_region(session, "FullCover", *_REGION)
    _add_region(session, "NoCover", 39.0, 39.1, 27.0, 27.1)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    report = silent_region_risk_report(session, _Settings(), flagged_only=True)
    assert [r["region_name"] for r in report["regions"]] == ["FullCover"]


def test_limit_clips_listing_but_summary_is_global(session):
    _add_region(session, "FullCover", *_REGION)
    _add_region(session, "HalfCover", 38.0, 38.1, 28.2, 28.3)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    _add_forecast(session, "F-A", _HALF_WKT)
    session.flush()
    report = silent_region_risk_report(session, _Settings(), limit=1)
    assert len(report["regions"]) == 1
    assert report["summary"]["active_silent_regions"] == 2


def test_limit_below_one_raises(session):
    _add_region(session, "QZone", *_REGION)
    session.flush()
    with pytest.raises(SilentRegionRiskError):
        silent_region_risk_report(session, _Settings(), limit=0)


def test_summary_counts(session):
    _add_region(session, "FullCover", *_REGION)
    _add_region(session, "NoCover", 39.0, 39.1, 27.0, 27.1)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    summary = silent_region_risk_report(session, _Settings())["summary"]
    assert summary["active_silent_regions"] == 2
    assert summary["intersecting_regions"] == 1
    assert summary["high_priority_regions"] == 1
    assert summary["active_forecast_polygons"] == 1


# --------------------------------------------------------------------------- #
# Payload + config
# --------------------------------------------------------------------------- #
def test_report_metadata(session):
    _add_region(session, "QZone", *_REGION)
    session.flush()
    report = silent_region_risk_report(session, _Settings())
    assert report["panel"] == "silent_region_risk"
    assert report["attribution"] == SILENT_REGION_RISK_ATTRIBUTION
    assert report["persistence"] == SILENT_REGION_RISK_PERSISTENCE
    assert report["thresholds"]["min_coverage"] == 0.05


def test_config_payload():
    config = silent_region_risk_config(_Settings())
    assert config["formula"] == "priority = risk_degree x silence_degree"
    assert config["thresholds"]["min_confidence"] == 0.5
    assert config["persistence"] == SILENT_REGION_RISK_PERSISTENCE


def test_config_defaults_without_settings():
    config = silent_region_risk_config()
    assert config["thresholds"]["min_coverage"] == 0.05
    assert config["thresholds"]["max_forecasts"] == 200


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_report(client, session):
    _add_region(session, "FullCover", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.commit()
    resp = client.get("/api/v1/silent-region-risk")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "silent_region_risk"
    assert body["summary"]["high_priority_regions"] == 1


def test_endpoint_flagged_only(client, session):
    _add_region(session, "FullCover", *_REGION)
    _add_region(session, "NoCover", 39.0, 39.1, 27.0, 27.1)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.commit()
    resp = client.get("/api/v1/silent-region-risk", params={"flagged_only": "true"})
    assert resp.status_code == 200
    body = resp.json()
    assert [r["region_name"] for r in body["regions"]] == ["FullCover"]


def test_endpoint_rejects_bad_limit(client):
    resp = client.get("/api/v1/silent-region-risk", params={"limit": 0})
    assert resp.status_code == 422


def test_endpoint_config(client):
    resp = client.get("/api/v1/silent-region-risk/config")
    assert resp.status_code == 200
    assert resp.json()["formula"] == "priority = risk_degree x silence_degree"
