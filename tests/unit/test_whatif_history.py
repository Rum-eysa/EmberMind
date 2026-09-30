"""EM-062 rolling what-if run history tests.

Covers the service (auto-capture, exact-repeat debounce, rolling trim to the
last N, revert fetch, clear) and the HTTP endpoints, plus the operator_map.html
integration that records a run and jumps back to it in one click.
"""
import pytest

from src.services.whatif_history import (
    HistoryError,
    clear_history,
    get_history,
    list_history,
    record_history,
)

BASE = {
    "latitude": 37.0,
    "longitude": 27.5,
    "wind_rotation_delta_deg": 0,
    "wind_speed_factor": 1.0,
    "temperature_delta_c": 0,
    "humidity_delta_pct": 0,
}


def _variant(**over):
    p = dict(BASE)
    p.update(over)
    return p


# --- service ---------------------------------------------------------------
def test_record_and_list(session):
    res = record_history(
        session, enabled=True, limit=10, params=_variant(), kind="wind"
    )
    assert res["recorded"] is True
    assert res["count"] == 1
    assert list_history(session)[0]["params"]["latitude"] == 37.0


def test_disabled_does_not_record(session):
    res = record_history(session, enabled=False, limit=10, params=_variant())
    assert res["recorded"] is False
    assert res["reason"] == "disabled"
    assert list_history(session) == []


def test_exact_repeat_is_deduped(session):
    record_history(session, enabled=True, limit=10, params=_variant(), event_key="ev1")
    again = record_history(
        session, enabled=True, limit=10, params=_variant(), event_key="ev1"
    )
    assert again["recorded"] is False
    assert again["reason"] == "duplicate"
    assert len(list_history(session, event_key="ev1")) == 1


def test_rolling_trim_keeps_last_n(session):
    for i in range(12):
        record_history(
            session, enabled=True, limit=3, params=_variant(wind_rotation_delta_deg=i)
        )
    rows = list_history(session)
    assert len(rows) == 3
    # newest-first; the three most recent rotation deltas survive
    assert [r["params"]["wind_rotation_delta_deg"] for r in rows] == [11, 10, 9]


def test_get_history_and_missing(session):
    entry = record_history(session, enabled=True, limit=10, params=_variant())["entry"]
    assert get_history(session, entry["id"])["id"] == entry["id"]
    with pytest.raises(HistoryError):
        get_history(session, 999999)


def test_clear_scoped_by_event(session):
    record_history(session, enabled=True, limit=10, params=_variant(), event_key="evA")
    record_history(
        session,
        enabled=True,
        limit=10,
        params=_variant(wind_speed_factor=1.2),
        event_key="evB",
    )
    assert clear_history(session, event_key="evA") == 1
    assert len(list_history(session)) == 1
    assert clear_history(session) == 1
    assert list_history(session) == []


# --- HTTP endpoints --------------------------------------------------------
def test_endpoint_config(client):
    res = client.get("/api/v1/whatif/history/config")
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert body["limit"] >= 1


def test_endpoint_record_list_get(client):
    rec = client.post(
        "/api/v1/whatif/history",
        json={"params": _variant(), "kind": "wind", "label": "L"},
    )
    assert rec.status_code == 200
    hist_id = rec.json()["entry"]["id"]
    assert rec.json()["recorded"] is True
    listing = client.get("/api/v1/whatif/history?kind=wind")
    assert listing.status_code == 200 and listing.json()["count"] == 1
    got = client.get(f"/api/v1/whatif/history/{hist_id}")
    assert got.status_code == 200 and got.json()["entry"]["label"] == "L"


def test_endpoint_duplicate_is_skipped(client):
    client.post("/api/v1/whatif/history", json={"params": _variant()})
    dup = client.post("/api/v1/whatif/history", json={"params": _variant()})
    assert dup.status_code == 200
    assert dup.json()["recorded"] is False
    assert dup.json()["reason"] == "duplicate"


def test_endpoint_get_missing_is_404(client):
    assert client.get("/api/v1/whatif/history/424242").status_code == 404


def test_endpoint_clear(client):
    client.post("/api/v1/whatif/history", json={"params": _variant()})
    client.post(
        "/api/v1/whatif/history", json={"params": _variant(wind_speed_factor=1.5)}
    )
    cleared = client.delete("/api/v1/whatif/history")
    assert cleared.status_code == 200
    assert cleared.json()["removed"] == 2
    assert client.get("/api/v1/whatif/history").json()["count"] == 0


# --- UI integration --------------------------------------------------------
def test_operator_map_has_history_toolbar():
    from pathlib import Path

    html = (
        Path(__file__).resolve().parents[2] / "src" / "static" / "operator_map.html"
    ).read_text(encoding="utf-8")
    assert 'id="whatif-hist-list"' in html
    assert 'id="whatif-hist-revert"' in html
    assert "recordWhatifHistory(body" in html
    assert "/api/v1/whatif/history" in html
