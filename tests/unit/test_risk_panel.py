"""EM-073 commander capacity & risk panel tests."""
from datetime import date

from src.models.fwi import FireWeatherIndex
from src.models.inventory import SuppressionResource
from src.models.road_network import CrewBase, RoadClosure
from src.models.spatial import FireEvent
from src.services.fwi import RISK_COLORS, fwi_risk_category
from src.services.risk_panel import (
    build_capacity_risk_panel,
    capacity_breakdown,
    first_exceedance_days,
)
from src.utils.timeutils import utc_now


class PanelSettings:
    """Settings stub for the command panel tests."""

    RISK_PANEL_THRESHOLD = 30.0


DAY1 = date(2026, 7, 10)
DAY2 = date(2026, 7, 11)
DAY3 = date(2026, 7, 12)


def _add_fwi(session, zone: str, day: date, fwi: float) -> None:
    """Store one zone-day FWI row with a consistent risk category."""
    session.add(
        FireWeatherIndex(
            zone_key=zone,
            region_name="Muğla pilot bölge",
            day=day,
            fwi=fwi,
            isi=fwi * 0.6,
            risk_category=fwi_risk_category(fwi),
            drought_category="moderate",
        )
    )


def _seed_panel_data(session) -> None:
    """Two zones over three days plus capacity records."""
    _add_fwi(session, "FWI_R1C1", DAY1, 20.0)
    _add_fwi(session, "FWI_R1C1", DAY2, 35.0)  # first exceedance (>= 30)
    _add_fwi(session, "FWI_R1C1", DAY3, 50.0)
    _add_fwi(session, "FWI_R2C2", DAY1, 5.0)
    _add_fwi(session, "FWI_R2C2", DAY2, 9.0)
    _add_fwi(session, "FWI_R2C2", DAY3, 12.0)  # never exceeds the threshold
    now = utc_now()
    session.add(
        CrewBase(
            base_key="B-1",
            name="Marmaris İlk Müdahale",
            latitude=36.85,
            longitude=28.27,
            crew_type="first_response",
            available=True,
        )
    )
    session.add(
        CrewBase(
            base_key="B-2",
            name="Ula İlk Müdahale",
            latitude=37.03,
            longitude=28.35,
            crew_type="first_response",
            available=False,
        )
    )
    session.add(
        CrewBase(
            base_key="B-3",
            name="Hava Aracı Üssü",
            latitude=37.25,
            longitude=28.12,
            crew_type="aircraft",
            available=True,
        )
    )
    session.add(
        FireEvent(
            event_key="EVT-P1",
            name="Aktif Olay",
            latitude=37.0,
            longitude=28.0,
            min_lat=36.9,
            max_lat=37.1,
            min_lon=27.9,
            max_lon=28.1,
            geometry_wkt="POLYGON((27.9 36.9, 28.1 37.1))",
            status="active",
            started_at=now,
        )
    )
    session.add(
        FireEvent(
            event_key="EVT-P2",
            name="Kontrol Altında",
            latitude=37.1,
            longitude=28.1,
            min_lat=37.0,
            max_lat=37.2,
            min_lon=28.0,
            max_lon=28.2,
            geometry_wkt="POLYGON((28.0 37.0, 28.2 37.2))",
            status="contained",
            started_at=now,
        )
    )
    session.add(
        RoadClosure(
            segment_key="SEG-P1",
            reason="yangın kapattı",
            status="active",
            reported_at=now,
        )
    )
    session.add(
        RoadClosure(
            segment_key="SEG-P2",
            reason="açıldı",
            status="resolved",
            reported_at=now,
            resolved_at=now,
        )
    )
    session.commit()


def test_first_exceedance_only_for_crossing_zones(session):
    _seed_panel_data(session)
    exceedance = first_exceedance_days(session, 30.0)
    assert exceedance == {"FWI_R1C1": DAY2.isoformat()}


def test_panel_single_view_fields(session):
    _seed_panel_data(session)
    panel = build_capacity_risk_panel(session, PanelSettings())
    assert panel["panel"] == "capacity_risk"
    assert panel["day"] == DAY3.isoformat()  # latest FWI day
    assert panel["risk_threshold"] == 30.0
    summary = panel["summary"]
    assert summary["max_risk_index"] == 50.0
    assert summary["max_risk_zone"] == "FWI_R1C1"
    assert summary["max_risk_color"] == RISK_COLORS["very_high"]
    assert summary["zones_over_threshold"] == 1
    assert summary["first_exceedance_day"] == DAY2.isoformat()
    hot, cool = panel["zones"]  # hottest first
    assert hot["zone_key"] == "FWI_R1C1"
    assert hot["over_threshold"] is True
    assert hot["threshold_color"] == RISK_COLORS["very_high"]
    assert hot["first_exceedance_day"] == DAY2.isoformat()
    assert cool["over_threshold"] is False
    assert cool["first_exceedance_day"] is None
    assert cool["threshold_color"] == RISK_COLORS["low"]


def test_capacity_breakdown(session):
    _seed_panel_data(session)
    capacity = capacity_breakdown(session, PanelSettings())
    bases = capacity["crew_bases"]
    assert bases["total"] == 3
    assert bases["available"] == 2
    assert bases["by_crew_type"]["first_response"] == {
        "total": 2,
        "available": 1,
        "unavailable": 1,
    }
    assert bases["by_crew_type"]["aircraft"]["available"] == 1
    assert capacity["active_incidents"] == 1
    assert capacity["active_road_closures"] == 1


def test_panel_capacity_includes_inventory_rollup(session):
    """EM-103: the coordinator inventory feeds the panel capacity account."""
    session.add(
        SuppressionResource(
            resource_key="EKIP-P1",
            name="Piyade Timi",
            resource_type="crew",
            latitude=37.0,
            longitude=28.0,
            status="available",
            capacity=25.0,
        )
    )
    session.add(
        SuppressionResource(
            resource_key="HEL-P1",
            name="Söndürme Helikopteri",
            resource_type="helicopter",
            latitude=36.8,
            longitude=28.1,
            status="deployed",
            capacity=12.0,
        )
    )
    session.commit()
    inventory = capacity_breakdown(session, PanelSettings())["inventory"]
    assert inventory["total_resources"] == 2
    assert inventory["available_resources"] == 1
    assert inventory["by_type"]["crew"]["capacity"] == 25.0
    assert inventory["by_type"]["helicopter"]["deployed"] == 1


def test_panel_empty_without_fwi_history(session):
    panel = build_capacity_risk_panel(session, PanelSettings())
    assert panel["day"] is None
    assert panel["zones"] == []
    assert panel["summary"]["max_risk_index"] is None
    assert panel["summary"]["first_exceedance_day"] is None
    assert panel["capacity"]["crew_bases"]["total"] == 0


def test_capacity_risk_endpoint(client, session):
    _seed_panel_data(session)
    response = client.get("/api/v1/panel/capacity-risk")
    assert response.status_code == 200
    body = response.json()
    assert body["panel"] == "capacity_risk"
    assert body["summary"]["max_risk_index"] == 50.0
    assert len(body["zones"]) == 2
    assert "attribution" in body


def test_capacity_risk_endpoint_day_and_bad_day(client, session):
    _seed_panel_data(session)
    day1 = client.get("/api/v1/panel/capacity-risk", params={"day": DAY1.isoformat()})
    assert day1.status_code == 200
    assert day1.json()["summary"]["zones_over_threshold"] == 0
    bad = client.get("/api/v1/panel/capacity-risk", params={"day": "12.07.2026"})
    assert bad.status_code == 400
    assert "YYYY-MM-DD" in bad.json()["detail"]["error"]


def test_panel_page_served_as_single_panel(client):
    response = client.get("/panel")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    # Tek panel: risk indeksi, eşik rengi, ilk aşım zamanı, kapasite kırılımı
    # ve EM-103 envanter kartı.
    for fragment in (
        "max-risk",
        "Eşik Renkleri",
        "İlk Aşım",
        "Kapasite Kırılımı",
        "Kaynak Envanteri (EM-103)",
        "/api/v1/panel/capacity-risk",
    ):
        assert fragment in html


def test_operator_map_links_to_command_panel(client):
    html = client.get("/ui").text
    assert "/panel" in html
