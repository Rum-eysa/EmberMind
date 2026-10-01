"""EM-071 external-support request draft tests.

The draft is composed entirely from the EM-065 early forecast: need
(``estimated_support_units``), time (first-shortfall / request-by minute) and
location (event coordinates via the EM-063 formatter) collapse into an automatic
one-line summary plus an editable multi-line body, rendered in TR / EN / EL.
Nothing is persisted (``persistence`` is ``none``).
"""
import pytest

from src.models.inventory import SuppressionResource
from src.models.spatial import FireEvent, FireForecast
from src.services.i18n import I18nError
from src.services.risk_index import RiskIndexError
from src.services.support_request_draft import (
    build_request_draft,
    config_payload,
    default_draft_language,
    requestable_events,
)
from src.utils.timeutils import utc_now


class _Settings:
    """Horizons + bands; capacity / EM-065 keys omitted so defaults apply.

    crew 2.0 ha/h; the EM-065 unit/lead-time keys fall back to 12.0 ha/hour and
    60 minutes, so a shortfall projected at T+40 lands on a ``request-now``
    deadline (lead 60 > 40).
    """

    RISK_INDEX_NORMAL_MAX = 0.6
    RISK_INDEX_CAUTION_MAX = 0.9
    RISK_INDEX_CRITICAL_NEAR_MAX = 1.2
    SPREAD_HORIZON_MINUTES = [30, 60, 120]


class _Unit2Lead10(_Settings):
    EXTERNAL_SUPPORT_UNIT_HA_PER_HOUR = 2.0
    EXTERNAL_SUPPORT_LEAD_TIME_MINUTES = 10


class _LangEn(_Settings):
    SUPPORT_REQUEST_DEFAULT_LANGUAGE = "en"


def _event(session, key="EVT-SD", status="active"):
    session.add(
        FireEvent(
            event_key=key,
            name=f"{key} taslak testi",
            latitude=38.0,
            longitude=27.0,
            min_lat=37.95,
            max_lat=38.05,
            min_lon=26.95,
            max_lon=27.05,
            geometry_wkt="POINT(27 38)",
            status=status,
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


def _seed(session, crews, areas, key="EVT-SD"):
    _event(session, key)
    for index in range(crews):
        _crew(session, f"SD-C{index}")
    for horizon, area in zip([30, 60, 120], areas):
        _forecast(session, key, horizon, area)


# --- auto summary from need + time + location (acceptance #1) ---------------


def test_shortfall_summary_carries_need_time_location(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    draft = build_request_draft(session, _Unit2Lead10(), "EVT-SD", "tr")
    assert draft["predicted_shortfall"] is True
    assert draft["estimated_support_units"] == 2
    # location: standardised decimal coordinate string appears in the summary.
    assert "38.000000, 27.000000" in draft["summary"]
    # need + time both rendered into the one-liner.
    assert "2 birim" in draft["summary"]
    assert "T+40" in draft["summary"]
    assert "en geç T+30" in draft["summary"]


def test_draft_text_is_editable_multiline_and_labels(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    draft = build_request_draft(session, _Unit2Lead10(), "EVT-SD", "tr")
    text = draft["draft_text"]
    assert draft["editable"] is True
    assert "\n" in text
    assert text.startswith("DIŞ DESTEK TALEBİ — TASLAK")
    for label in ("Olay:", "Konum:", "Tahmini ihtiyaç:", "Talep son tarih:"):
        assert label in text
    assert "EVT-SD" in text


def test_request_now_when_lead_exceeds_shortfall(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    draft = build_request_draft(session, _Settings(), "EVT-SD", "tr")
    # lead 60 > shortfall 40 -> request-by collapses to "hemen".
    assert draft["request_by_minute"] == pytest.approx(0.0)
    assert "hemen" in draft["summary"]


def test_no_shortfall_still_returns_draft_with_note(session):
    _seed(session, crews=10, areas=[1.5, 1.5, 1.0])
    session.flush()
    draft = build_request_draft(session, _Settings(), "EVT-SD", "tr")
    assert draft["predicted_shortfall"] is False
    assert draft["estimated_support_units"] == 0
    assert "yeterli" in draft["summary"]
    assert draft["draft_text"].count("\n") > 5


# --- TR / EN / EL rendering (acceptance #3) ----------------------------------


def test_three_languages_render_distinct_drafts(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    drafts = {
        lang: build_request_draft(session, _Unit2Lead10(), "EVT-SD", lang)
        for lang in ("tr", "en", "el")
    }
    assert drafts["tr"]["draft_text"] != drafts["en"]["draft_text"]
    assert drafts["en"]["draft_text"] != drafts["el"]["draft_text"]
    assert drafts["tr"]["language"] == "tr"
    assert drafts["en"]["language_label"] == "English"
    assert drafts["en"]["draft_text"].startswith("EXTERNAL SUPPORT REQUEST")
    assert "ΕΞΩΤΕΡΙΚΗΣ ΥΠΟΣΤΗΡΙΞΗΣ" in drafts["el"]["draft_text"]
    # the need value is localised too.
    assert "2 reinforcement units" in drafts["en"]["draft_text"]


def test_bcp47_tag_is_normalised(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    draft = build_request_draft(session, _Unit2Lead10(), "EVT-SD", "en-GB")
    assert draft["language"] == "en"


def test_unsupported_language_rejected(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    with pytest.raises(I18nError):
        build_request_draft(session, _Settings(), "EVT-SD", "de")


def test_default_language_from_settings(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    assert default_draft_language(_LangEn()) == "en"
    assert default_draft_language(_Settings()) == "tr"
    draft = build_request_draft(session, _LangEn(), "EVT-SD", None)
    assert draft["language"] == "en"


# --- error + metadata paths --------------------------------------------------


def test_unknown_event_raises(session):
    with pytest.raises(RiskIndexError):
        build_request_draft(session, _Settings(), "NOPE", "tr")


def test_metadata_is_stateless(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    draft = build_request_draft(session, _Settings(), "EVT-SD", "tr")
    assert draft["panel"] == "support_request_draft"
    assert draft["persistence"] == "none"
    assert "attribution" in draft


def test_config_payload_offers_locales_and_pdf(session):
    cfg = config_payload(_Settings())
    codes = [entry["code"] for entry in cfg["supported_languages"]]
    assert codes == ["tr", "en", "el"]
    assert cfg["editable"] is True
    assert "pdf" in cfg["export_formats"]
    assert cfg["persistence"] == "none"
    assert cfg["default_language"] == "tr"


def test_requestable_events_lists_and_suggests(session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.flush()
    result = requestable_events(session, _Unit2Lead10())
    assert result["panel"] == "support_request_draft_events"
    keys = [e["event_key"] for e in result["events"]]
    assert "EVT-SD" in keys
    assert result["suggested_event_key"] == "EVT-SD"


def test_requestable_events_no_warning_null_suggestion(session):
    _seed(session, crews=10, areas=[1.5, 1.5, 1.0])
    session.flush()
    result = requestable_events(session, _Settings())
    assert result["suggested_event_key"] is None


# --- endpoints ---------------------------------------------------------------


def test_endpoint_config(client):
    resp = client.get("/api/v1/support-request-draft/config")
    assert resp.status_code == 200
    assert "pdf" in resp.json()["export_formats"]


def test_endpoint_events(client, session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.commit()
    resp = client.get("/api/v1/support-request-draft/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["panel"] == "support_request_draft_events"
    assert len(body["events"]) == 1


def test_endpoint_returns_draft(client, session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.commit()
    resp = client.get("/api/v1/support-request-draft", params={"event_key": "EVT-SD"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["language"] == "tr"
    assert body["draft_text"]


def test_endpoint_draft_language_query(client, session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.commit()
    resp = client.get(
        "/api/v1/support-request-draft",
        params={"event_key": "EVT-SD", "lang": "en"},
    )
    assert resp.status_code == 200
    assert resp.json()["language"] == "en"


def test_endpoint_unknown_event_404(client):
    resp = client.get("/api/v1/support-request-draft", params={"event_key": "NOPE"})
    assert resp.status_code == 404


def test_endpoint_bad_language_400(client, session):
    _seed(session, crews=2, areas=[1.5, 6.0, 16.0])
    session.commit()
    resp = client.get(
        "/api/v1/support-request-draft",
        params={"event_key": "EVT-SD", "lang": "de"},
    )
    assert resp.status_code == 400
