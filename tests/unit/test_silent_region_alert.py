"""EM-040 high-priority silent-region alert feed tests (Epic E4).

The alert feed is a read-only composition on top of EM-037's graded report: every
``is_high_priority`` silent region becomes exactly one alert carrying the region,
how long it has been silent (from the record's ``created_at``) and a Turkish risk
level. Repeat threats against the *same* region are folded into that single alert
(``suppressed_duplicate_alerts``). These tests pin the alert content, the per-region
suppression, the risk-level banding, the level/limit filters, the ``persistence=none``
contract and the read-only HTTP endpoints.
"""
from datetime import timedelta

import pytest

from src.models.spatial import FireEvent, FireForecast, SilentRegion
from src.services.silent_region_alert import (
    RISK_LEVEL_ORDER,
    SILENT_REGION_ALERT_ATTRIBUTION,
    SILENT_REGION_ALERT_PERSISTENCE,
    SilentRegionAlertError,
    silent_region_alert_config,
    silent_region_alert_report,
)
from src.utils.timeutils import utc_now


class _Settings:
    """EM-037 risk thresholds plus the EM-040 risk-level bands and alert limit."""

    def __init__(
        self,
        high=0.75,
        moderate=0.40,
        far=25.0,
        min_coverage=0.05,
        min_confidence=0.5,
        max_forecasts=200,
        max_limit=200,
        crit=0.6,
        hi=0.4,
        med=0.2,
        alert_limit=200,
    ):
        self.SILENT_ZONE_HIGH_CONFIDENCE = high
        self.SILENT_ZONE_MODERATE_CONFIDENCE = moderate
        self.SILENT_ZONE_PROXIMITY_FAR_KM = far
        self.SILENT_REGION_RISK_MIN_COVERAGE = min_coverage
        self.SILENT_REGION_RISK_MIN_CONFIDENCE = min_confidence
        self.SILENT_REGION_RISK_MAX_FORECASTS = max_forecasts
        self.SILENT_REGION_RISK_MAX_LIMIT = max_limit
        self.SILENT_ALERT_CRITICAL_PRIORITY = crit
        self.SILENT_ALERT_HIGH_PRIORITY = hi
        self.SILENT_ALERT_MEDIUM_PRIORITY = med
        self.SILENT_ALERT_MAX_LIMIT = alert_limit


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


# Silent region bbox and a forecast rectangle that fully engulfs it.
_REGION = (38.0, 38.1, 28.0, 28.1)
_SECOND_REGION = (38.0, 38.1, 28.2, 28.3)
_COVER_WKT = "POLYGON((27.9 37.9, 28.3 37.9, 28.3 38.3, 27.9 38.3, 27.9 37.9))"
_FAR_WKT = "POLYGON((29.0 39.0, 29.2 39.0, 29.2 39.2, 29.0 39.2, 29.0 39.0))"


# --------------------------------------------------------------------------- #
# Alert emission for a high-priority region
# --------------------------------------------------------------------------- #
def test_alert_emitted_for_high_priority_region(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)  # outside bbox -> region stays silent
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    report = silent_region_alert_report(session, _Settings())
    assert report["panel"] == "silent_region_alert"
    assert report["count"] == 1
    alert = report["alerts"][0]
    assert alert["region_name"] == "QZone"
    assert alert["alert_id"] == f"SA-{alert['region_id']}"
    assert alert["risk_level_code"] in RISK_LEVEL_ORDER
    assert alert["risk_level_label"]
    assert alert["threatening_fire_count"] >= 1


def test_alert_carries_region_duration_and_risk_level(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    alert = silent_region_alert_report(session, _Settings())["alerts"][0]
    # Acceptance: alert must carry region, how long it is silent, and risk level.
    assert alert["region_name"] == "QZone"
    assert alert["silence_duration_hours"] >= 0.0
    assert alert["silence_duration_days"] == round(
        alert["silence_duration_hours"] / 24.0, 2
    )
    assert alert["risk_level_code"] in RISK_LEVEL_ORDER
    assert "QZone" in alert["message"]


def test_risk_level_matches_priority_band(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    report = silent_region_alert_report(session, _Settings())
    th = report["thresholds"]
    alert = report["alerts"][0]
    score = alert["priority_score"]
    if score >= th["critical_priority"]:
        expected = "kritik"
    elif score >= th["high_priority"]:
        expected = "yuksek"
    elif score >= th["medium_priority"]:
        expected = "orta"
    else:
        expected = "dusuk"
    assert alert["risk_level_code"] == expected


def test_silence_duration_grows_with_created_at_gap(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    future = utc_now() + timedelta(hours=50)
    report = silent_region_alert_report(session, _Settings(), now=future)
    hours = report["alerts"][0]["silence_duration_hours"]
    # created_at is ~ now, so a +50h clock advance reads ~50 silent hours.
    assert 48.0 < hours < 52.0


# --------------------------------------------------------------------------- #
# Per-region suppression of repeat alerts
# --------------------------------------------------------------------------- #
def test_repeat_threats_suppressed_to_single_alert(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_fire(session, "F-B", 37.9, 27.92)
    _add_forecast(session, "F-A", _COVER_WKT)
    _add_forecast(session, "F-B", _COVER_WKT)
    session.flush()
    report = silent_region_alert_report(session, _Settings())
    assert len(report["alerts"]) == 1  # one alert per region
    alert = report["alerts"][0]
    assert alert["threatening_fire_count"] == 2
    assert alert["suppressed_duplicate_alerts"] == 1
    summary = report["summary"]
    assert summary["high_priority_regions"] == 1
    assert summary["raw_candidate_alerts"] == 2
    assert summary["suppressed_duplicate_alerts"] == 1


def test_alerts_sorted_by_priority_desc(session):
    _add_region(session, "FullCover", *_REGION)
    _add_region(session, "FullCover2", *_SECOND_REGION)
    # Both fully covered -> equal priority; region-name tiebreak keeps it stable.
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    report = silent_region_alert_report(session, _Settings())
    scores = [a["priority_score"] for a in report["alerts"]]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------- #
# Empty when nothing is high priority
# --------------------------------------------------------------------------- #
def test_no_high_priority_yields_no_alerts(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 39.5, 29.5)  # far away -> forecast never reaches
    _add_forecast(session, "F-A", _FAR_WKT)
    session.flush()
    report = silent_region_alert_report(session, _Settings())
    assert report["alerts"] == []
    assert report["count"] == 0
    assert report["summary"]["high_priority_regions"] == 0


# --------------------------------------------------------------------------- #
# Level filter + limit
# --------------------------------------------------------------------------- #
def test_level_filter_keeps_only_matching_band(session):
    _add_region(session, "QZone", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    # critical band pushed below zero -> every alert lands in "kritik".
    settings = _Settings(crit=-1.0)
    report = silent_region_alert_report(session, settings, level="kritik")
    assert report["count"] >= 1
    assert all(a["risk_level_code"] == "kritik" for a in report["alerts"])
    # A band nothing falls into yields an empty (but valid) alert list.
    empty = silent_region_alert_report(session, settings, level="dusuk")
    assert empty["alerts"] == []
    assert empty["filter_level"] == "dusuk"
    # The summary still describes the whole de-duplicated set, not just the clip.
    assert report["summary"]["high_priority_regions"] >= 1


def test_limit_clips_alerts_but_summary_is_global(session):
    _add_region(session, "FullCover", *_REGION)
    _add_region(session, "FullCover2", *_SECOND_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.flush()
    report = silent_region_alert_report(session, _Settings(), limit=1)
    assert len(report["alerts"]) == 1
    assert report["summary"]["high_priority_regions"] == 2


def test_limit_below_one_raises(session):
    _add_region(session, "QZone", *_REGION)
    session.flush()
    with pytest.raises(SilentRegionAlertError):
        silent_region_alert_report(session, _Settings(), limit=0)


def test_invalid_level_raises(session):
    _add_region(session, "QZone", *_REGION)
    session.flush()
    with pytest.raises(SilentRegionAlertError):
        silent_region_alert_report(session, _Settings(), level="bogus")


# --------------------------------------------------------------------------- #
# Payload metadata + config
# --------------------------------------------------------------------------- #
def test_report_metadata_and_persistence_none(session):
    _add_region(session, "QZone", *_REGION)
    session.flush()
    report = silent_region_alert_report(session, _Settings())
    assert report["attribution"] == SILENT_REGION_ALERT_ATTRIBUTION
    assert report["persistence"] == SILENT_REGION_ALERT_PERSISTENCE == "none"
    assert [lvl["code"] for lvl in report["risk_levels"]] == list(RISK_LEVEL_ORDER)
    assert all(lvl["label"] for lvl in report["risk_levels"])


def test_config_payload():
    config = silent_region_alert_config(_Settings())
    assert config["persistence"] == SILENT_REGION_ALERT_PERSISTENCE
    assert config["sort"] == "priority_score desc, region_name asc"
    assert "bastırılır" in config["suppression_rule"]
    assert [lvl["code"] for lvl in config["risk_level_ladder"]] == list(
        RISK_LEVEL_ORDER
    )


def test_config_defaults_without_settings():
    config = silent_region_alert_config()
    th = config["thresholds"]
    assert th["critical_priority"] == 0.6
    assert th["high_priority"] == 0.4
    assert th["medium_priority"] == 0.2
    assert th["max_limit"] == 200


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
def test_endpoint_report(client, session):
    _add_region(session, "FullCover", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.commit()
    resp = client.get("/api/v1/silent-region-alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "silent_region_alert"
    assert body["count"] == 1
    assert body["alerts"][0]["region_name"] == "FullCover"


def test_endpoint_level_filter(client, session):
    _add_region(session, "FullCover", *_REGION)
    _add_fire(session, "F-A", 37.9, 27.9)
    _add_forecast(session, "F-A", _COVER_WKT)
    session.commit()
    resp = client.get("/api/v1/silent-region-alerts", params={"level": "kritik"})
    assert resp.status_code == 200
    assert resp.json()["filter_level"] == "kritik"


def test_endpoint_rejects_bad_level(client):
    resp = client.get("/api/v1/silent-region-alerts", params={"level": "bogus"})
    assert resp.status_code == 400


def test_endpoint_rejects_bad_limit(client):
    resp = client.get("/api/v1/silent-region-alerts", params={"limit": 0})
    assert resp.status_code == 422


def test_endpoint_config(client):
    resp = client.get("/api/v1/silent-region-alerts/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persistence"] == SILENT_REGION_ALERT_PERSISTENCE
    assert body["sort"] == "priority_score desc, region_name asc"
