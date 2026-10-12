"""EM-087 one-page situation report (SITREP) tests (Epic E8).

The report is a read-time projection that gathers, in one deterministic pass,
the active fires, the EM-029 spread forecast + risk index, the top dispatch
recommendations (EM-052), a report timestamp and a synthetic-data badge. These
tests pin: the always-present section list, the timestamp, per-fire enrichment
(severity / start time) and the risk + forecast projection, the report ordering
(most severe then hottest), the ``max_fires`` trim with a global total, the
synthetic badge on/off, the graceful no-road recommendation degradation, the
hottest-incident targeting (via a stubbed proposal builder), the single-incident
scope, the unknown-event error, the config payload and the HTTP endpoints.
"""
from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services import sitrep_report
from src.services.risk_index import RiskIndexError
from src.services.sitrep_report import (
    REPORT_SECTIONS,
    SITREP_ATTRIBUTION,
    SITREP_PERSISTENCE,
    build_sitrep,
    sitrep_config,
)
from src.services.synthetic import SYNTHETIC_LABEL
from src.utils.timeutils import utc_now


class _Settings:
    """Risk bands + horizons (EM-029) + the SITREP caps. Capacity keys omitted
    so ``effective_capacity`` falls back to its defaults (crew 2.0 ha/h)."""

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]
    SITREP_MAX_FIRES = 20
    SITREP_RECOMMENDATION_LIMIT = 5
    POSITIONING_MAX_PROPOSALS = 5


def _event(
    session, key, status="active", lat=38.0, lon=27.0, severity="high", notes=None
):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} test",
            latitude=lat,
            longitude=lon,
            min_lat=lat - 0.05,
            max_lat=lat + 0.05,
            min_lon=lon - 0.05,
            max_lon=lon + 0.05,
            geometry_wkt=f"POINT({lon} {lat})",
            status=status,
            severity=severity,
            notes=notes,
            started_at=utc_now().replace(tzinfo=None),
        )
    )


def _forecast(session, event, horizon, area_ha):
    session.add(
        FireForecast(
            event_key=event,
            model_name="rothermel_v1",
            latitude=38.0,
            longitude=27.0,
            predicted_area_ha=area_ha,
            geometry_wkt="POLYGON((27 38,27.01 38,27.01 38.01,27 38.01,27 38))",
            forecast_for=utc_now(),
            horizon_minutes=horizon,
            rate_of_spread_m_per_min=10.0,
            spread_direction_deg=45.0,
            inputs_json="{}",
        )
    )


def _crew(session, key):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key,
            resource_type="crew",
            latitude=37.0,
            longitude=28.0,
            status="available",
            capacity=1.0,
        )
    )


def _seed_risky_fire(session, key="SIT-A", severity="high"):
    """One scored fire: six crews (12.0 ha/h) and 6/9/10.8 ha forecasts giving
    risk 1.0/0.75/0.45 -> peak kritik-yakin at 30 dk."""
    _event(session, key, severity=severity)
    for index in range(1, 7):
        _crew(session, f"{key}-C{index}")
    _forecast(session, key, 30, 6.0)
    _forecast(session, key, 60, 9.0)
    _forecast(session, key, 120, 10.8)


# ------------------------------------------------------------- structure ---


def test_empty_report_has_all_sections_and_no_fires(session):
    data = build_sitrep(session, _Settings())
    assert data["panel"] == "sitrep"
    assert data["sections"] == list(REPORT_SECTIONS)
    assert data["fires"] == []
    assert data["fire_count"] == 0
    assert data["active_fire_total"] == 0
    assert data["synthetic"]["is_synthetic"] is False
    assert data["recommendations"]["available"] is False
    assert data["recommendations"]["items"] == []


def test_report_sections_cover_the_acceptance_surface():
    assert set(REPORT_SECTIONS) == {
        "fires",
        "forecast",
        "risk_index",
        "recommendations",
        "timestamp",
    }


def test_report_carries_a_timestamp(session):
    data = build_sitrep(session, _Settings())
    assert isinstance(data["generated_at"], str)
    assert data["generated_at"]


def test_persistence_and_attribution(session):
    data = build_sitrep(session, _Settings())
    assert data["persistence"] == SITREP_PERSISTENCE == "none"
    assert data["attribution"] == SITREP_ATTRIBUTION


# ------------------------------------------------------------- fires -------


def test_fire_enriched_with_severity_and_start_time(session):
    _seed_risky_fire(session)
    session.flush()
    data = build_sitrep(session, _Settings())
    fire = data["fires"][0]
    assert fire["severity"] == "high"
    assert fire["started_at"] is not None
    assert fire["peak_level"] == "kritik-yakin"
    assert fire["peak_risk_index"] is not None


def test_forecast_projection_carries_area_per_horizon(session):
    _seed_risky_fire(session)
    session.flush()
    data = build_sitrep(session, _Settings())
    per_event = data["forecast"]["per_event"]
    assert len(per_event) == 1
    horizons = per_event[0]["horizons"]
    assert [h["horizon_minutes"] for h in horizons] == [30, 60, 120]
    assert horizons[0]["area_ha"] == 6.0


def test_risk_index_summary_is_reported(session):
    _seed_risky_fire(session)
    session.flush()
    data = build_sitrep(session, _Settings())
    summary = data["risk_index"]["summary"]
    assert summary["events_scored"] == 1
    assert summary["max_risk_level"] == "kritik-yakin"
    assert data["headline"]["most_severe"] == "high"


def test_report_orders_most_severe_then_hottest(session):
    _seed_risky_fire(session, key="SIT-LOW", severity="low")
    _seed_risky_fire(session, key="SIT-CRIT", severity="critical")
    session.flush()
    data = build_sitrep(session, _Settings())
    assert [f["event_key"] for f in data["fires"]][0] == "SIT-CRIT"


def test_max_fires_trims_list_but_keeps_global_total(session):
    _seed_risky_fire(session, key="SIT-1", severity="high")
    _seed_risky_fire(session, key="SIT-2", severity="medium")
    session.flush()
    settings = _Settings()
    settings.SITREP_MAX_FIRES = 1
    data = build_sitrep(session, settings)
    assert data["fire_count"] == 1
    assert data["active_fire_total"] == 2


# ------------------------------------------------------------ synthetic ----


def test_synthetic_badge_when_demo_note_present(session):
    _event(session, "SIT-SYN", notes=SYNTHETIC_LABEL)
    session.flush()
    data = build_sitrep(session, _Settings())
    assert data["synthetic"]["is_synthetic"] is True
    assert data["synthetic"]["badge"] == SYNTHETIC_LABEL
    assert "SIT-SYN" in data["synthetic"]["matched_events"]


def test_synthetic_badge_absent_for_real_observation(session):
    _event(session, "SIT-REAL", notes="uydu tespiti")
    session.flush()
    data = build_sitrep(session, _Settings())
    assert data["synthetic"]["is_synthetic"] is False
    assert data["synthetic"]["badge"] is None


# ------------------------------------------------------ recommendations ----


def test_recommendations_degrade_without_road_network(session):
    # A fire is present but the test DB carries no road segments, so the
    # report must still build with an explicitly unavailable section.
    _seed_risky_fire(session)
    session.flush()
    data = build_sitrep(session, _Settings())
    assert data["recommendations"]["available"] is False
    assert data["recommendations"]["reason"]
    assert data["recommendations"]["items"] == []


def test_recommendations_available_with_stubbed_builder(session, monkeypatch):
    captured = {}

    def _fake(session_arg, settings_arg, event_key, limit=None, **kwargs):
        captured["event_key"] = event_key
        return [
            {
                "resource_key": "HELI-1",
                "name": "Helikopter 1",
                "resource_type": "helicopter",
                "travel_mode": "air",
                "reachable": True,
                "eta_minutes": 12.5,
            }
        ]

    monkeypatch.setattr(sitrep_report, "build_proposals", _fake)
    _seed_risky_fire(session)
    session.flush()
    data = build_sitrep(session, _Settings())
    rec = data["recommendations"]
    assert rec["available"] is True
    assert rec["items"][0]["rank"] == 1
    assert rec["items"][0]["resource_key"] == "HELI-1"
    # The recommendations target the hottest scored incident.
    assert captured["event_key"] == data["risk_index"]["summary"]["max_risk_event"]


def test_recommendation_target_is_scoped_event(session, monkeypatch):
    monkeypatch.setattr(
        sitrep_report,
        "build_proposals",
        lambda *a, **k: [],
    )
    _seed_risky_fire(session, key="SIT-SCOPE")
    session.flush()
    data = build_sitrep(session, _Settings(), event_key="SIT-SCOPE")
    assert data["scope"]["event_key"] == "SIT-SCOPE"
    assert data["recommendations"]["for_event"] == "SIT-SCOPE"


# ---------------------------------------------------------------- scope ----


def test_scope_single_event(session):
    _seed_risky_fire(session, key="SIT-ONE", severity="high")
    _seed_risky_fire(session, key="SIT-TWO", severity="low")
    session.flush()
    data = build_sitrep(session, _Settings(), event_key="SIT-ONE")
    assert [f["event_key"] for f in data["fires"]] == ["SIT-ONE"]


def test_unknown_event_raises(session):
    import pytest

    with pytest.raises(RiskIndexError):
        build_sitrep(session, _Settings(), event_key="does-not-exist")


# ---------------------------------------------------------------- config ---


def test_config_payload(session):
    cfg = sitrep_config(_Settings())
    assert cfg["panel"] == "sitrep"
    assert cfg["sections"] == list(REPORT_SECTIONS)
    assert cfg["export"]["formats"] == ["pdf", "print"]
    assert cfg["export"]["one_click"] is True
    assert cfg["synthetic_badge_label"] == SYNTHETIC_LABEL
    assert cfg["max_fires"] == 20
    assert cfg["persistence"] == "none"
    assert len(cfg["sources"]) == 4


# -------------------------------------------------------------- endpoints --


def test_endpoint_returns_report(api, client, session):
    _seed_risky_fire(session)
    session.commit()
    resp = client.get("/api/v1/sitrep")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "sitrep"
    assert body["fire_count"] == 1
    assert body["fires"][0]["event_key"] == "SIT-A"


def test_endpoint_unknown_event_404(api, client):
    resp = client.get("/api/v1/sitrep", params={"event_key": "nope"})
    assert resp.status_code == 404


def test_endpoint_config(api, client):
    resp = client.get("/api/v1/sitrep/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sections"] == list(REPORT_SECTIONS)
    assert body["export"]["one_click"] is True
