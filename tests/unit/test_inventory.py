"""EM-103 resource inventory tests: CRUD, capacity and CSV import."""
import pytest

from src.services.inventory import (
    InventoryError,
    capacity_summary,
    create_resource,
    delete_resource,
    get_resource,
    import_resources_csv,
    list_resources,
    normalize_status,
    normalize_type,
    parse_resource_csv,
    update_resource,
)


def _crew_payload(**overrides):
    payload = {
        "resource_key": "EKIP-01",
        "resource_type": "crew",
        "latitude": 37.03,
        "longitude": 28.35,
        "name": "Ula Müdahale Ekibi",
        "base_key": "B-2",
        "country": "TR",
        "status": "available",
        "capacity": 25.0,
        "capacity_unit": "personnel",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- service ---


def test_create_and_read_resource(session):
    resource = create_resource(session, _crew_payload())
    session.commit()
    fetched = get_resource(session, "EKIP-01")
    assert fetched is not None
    assert fetched.as_dict["resource_type"] == "crew"
    assert fetched.as_dict["capacity"] == 25.0
    assert resource.as_dict["name"] == "Ula Müdahale Ekibi"


def test_create_normalizes_turkish_aliases(session):
    resource = create_resource(
        session,
        _crew_payload(resource_type="ekip", status="müsait"),
    )
    assert resource.resource_type == "crew"
    assert resource.status == "available"


def test_create_rejects_duplicate_key(session):
    create_resource(session, _crew_payload())
    session.commit()
    with pytest.raises(InventoryError, match="already exists"):
        create_resource(session, _crew_payload())


@pytest.mark.parametrize(
    "payload, message",
    [
        (_crew_payload(resource_type="jet"), "invalid resource_type"),
        (_crew_payload(status="emekli"), "invalid status"),
        (_crew_payload(latitude=95.0), "latitude"),
        (_crew_payload(longitude=200.0), "longitude"),
        (_crew_payload(capacity=-3), "capacity must be >= 0"),
        (_crew_payload(resource_key="  "), "resource_key is required"),
    ],
)
def test_create_validation_errors(session, payload, message):
    with pytest.raises(InventoryError, match=message):
        create_resource(session, payload)


def test_update_partial_fields(session):
    create_resource(session, _crew_payload())
    session.commit()
    updated = update_resource(
        session, "EKIP-01", {"status": "görevde", "capacity": 18.5}
    )
    assert updated.status == "deployed"
    assert updated.capacity == 18.5
    assert updated.name == "Ula Müdahale Ekibi"  # untouched field kept


def test_update_rejects_unknown_field_and_missing_key(session):
    create_resource(session, _crew_payload())
    session.commit()
    with pytest.raises(InventoryError, match="unknown fields"):
        update_resource(session, "EKIP-01", {"fuel": "diesel"})
    with pytest.raises(InventoryError, match="not found"):
        update_resource(session, "YOK-99", {"status": "available"})


def test_delete_resource(session):
    create_resource(session, _crew_payload())
    session.commit()
    assert delete_resource(session, "EKIP-01") is True
    session.commit()
    assert get_resource(session, "EKIP-01") is None
    assert delete_resource(session, "EKIP-01") is False


def test_list_filters(session):
    create_resource(session, _crew_payload())
    create_resource(
        session,
        _crew_payload(
            resource_key="HEL-01",
            resource_type="helicopter",
            status="maintenance",
            capacity=10.0,
            country="GR",
        ),
    )
    create_resource(
        session,
        _crew_payload(resource_key="IHA-01", resource_type="iha", capacity=2.0),
    )
    session.commit()
    assert [r.resource_key for r in list_resources(session)] == [
        "EKIP-01",
        "HEL-01",
        "IHA-01",
    ]
    crews = list_resources(session, resource_type="ekip")
    assert [r.resource_key for r in crews] == ["EKIP-01"]
    avail = list_resources(session, status="available")
    assert {r.resource_key for r in avail} == {"EKIP-01", "IHA-01"}
    by_base = list_resources(session, base_key="B-2")
    assert len(by_base) == 3
    by_country = list_resources(session, country="GR")
    assert [r.resource_key for r in by_country] == ["HEL-01"]


def test_capacity_summary(session):
    create_resource(session, _crew_payload(capacity=25.0))
    create_resource(
        session,
        _crew_payload(resource_key="EKIP-02", status="görevde", capacity=30.0),
    )
    create_resource(
        session,
        _crew_payload(
            resource_key="HEL-01",
            resource_type="helikopter",
            capacity=15.0,
            capacity_unit="tons",
        ),
    )
    session.commit()
    summary = capacity_summary(session)
    assert summary["total_resources"] == 3
    assert summary["available_resources"] == 2
    crew = summary["by_type"]["crew"]
    assert crew == {
        "total": 2,
        "available": 1,
        "deployed": 1,
        "en_route": 0,
        "capacity": 55.0,
    }
    heli = summary["by_type"]["helicopter"]
    assert heli["total"] == 1
    assert heli["capacity"] == 15.0
    assert summary["by_type"]["uav"]["total"] == 0


def test_en_route_status_counts_in_summary(session):
    # EM-031: "yolda" (en_route) is a first-class status and must be visible
    # in the coordinator rollup next to available/deployed.
    create_resource(session, _crew_payload(resource_key="EKIP-09"))
    create_resource(
        session,
        _crew_payload(
            resource_key="HEL-09", resource_type="helikopter", status="yolda"
        ),
    )
    session.commit()
    heli = capacity_summary(session)["by_type"]["helicopter"]
    assert heli["en_route"] == 1
    assert heli["available"] == 0


def test_normalize_helpers():
    # Turkish dotted capital "İ" must fold to the ASCII "iha" alias, not
    # decompose into a combining dot that would break the lookup.
    assert normalize_type("İHA") == "uav"
    assert normalize_type("iha") == "uav"
    assert normalize_status("MÜSAİT") == "available"
    assert normalize_status("MAINTENANCE") == "maintenance"
    # EM-031: en_route is accepted through its Turkish and hyphen aliases.
    assert normalize_status("yolda") == "en_route"
    assert normalize_status("EN-ROUTE") == "en_route"
    with pytest.raises(InventoryError):
        normalize_type("uzay-meki")
    with pytest.raises(InventoryError):
        normalize_status("kayıp")


# ------------------------------------------------------------------- csv ---

CSV_TEXT = """key,tur,enlem,boylam,ad,üs,ülke,durum,kapasite,unit
EKIP-09,ekip,36.85,28.27,Marmale Ekibi,B-1,TR,müsait,20,personnel
HEL-09,helikopter,36.71,28.52,Düşen Ateç,B-1,TR,görevde,12,tons
IHA-09,iha,37.0,28.4,Rot-3,B-2,TR,bakım,4,flights
"""


def test_parse_resource_csv_turkish_headers():
    rows = parse_resource_csv(CSV_TEXT)
    assert len(rows) == 3
    first = rows[0]
    assert first["resource_key"] == "EKIP-09"
    assert first["resource_type"] == "ekip"
    assert first["latitude"] == "36.85"
    assert first["capacity_unit"] == "personnel"


def test_parse_resource_csv_requires_columns():
    with pytest.raises(InventoryError, match="missing required column"):
        parse_resource_csv("name,ad\nE1,Alpha\n")
    with pytest.raises(InventoryError, match="no header row"):
        parse_resource_csv("")


def test_import_resources_csv_creates_and_upserts(session):
    create_resource(session, _crew_payload(resource_key="EKIP-09"))
    session.commit()
    result = import_resources_csv(session, CSV_TEXT)
    assert result["rows"] == 3
    assert result["created"] == 2  # HEL-09 and IHA-09 are new
    assert result["updated"] == 1  # EKIP-09 existed already
    assert result["errors"] == []
    heli = get_resource(session, "HEL-09")
    assert heli is not None
    assert heli.resource_type == "helicopter"
    assert heli.status == "deployed"
    crew = get_resource(session, "EKIP-09")
    assert crew is not None
    assert crew.capacity == 20.0


def test_import_resources_csv_tolerates_bad_rows(session):
    broken = (
        "resource_key,resource_type,latitude,longitude,status,capacity\n"
        "OK-01,crew,36.8,28.2,available,10\n"
        "BAD-01,uzay,36.9,28.3,available,10\n"
        "BAD-02,helicopter,999,28.3,available,10\n"
        "BAD-03,uav,36.9,28.3,kayıp,10\n"
    )
    result = import_resources_csv(session, broken)
    assert result["created"] == 1
    assert result["skipped"] == 3
    reported = {e["row"] for e in result["errors"]}
    assert reported == {3, 4, 5}
    assert get_resource(session, "OK-01") is not None
    assert get_resource(session, "BAD-01") is None


# ---------------------------------------------------------------- routes ---


def test_resource_crud_endpoints(client):
    created = client.post("/api/v1/resources", json=_crew_payload())
    assert created.status_code == 200
    assert created.json()["status"] == "created"
    key = created.json()["resource"]["resource_key"]

    read = client.get(f"/api/v1/resources/{key}")
    assert read.status_code == 200
    assert read.json()["name"] == "Ula Müdahale Ekibi"

    updated = client.put(
        f"/api/v1/resources/{key}",
        json={"status": "görevde", "capacity": 12.0},
    )
    assert updated.status_code == 200
    assert updated.json()["resource"]["status"] == "deployed"

    deleted = client.delete(f"/api/v1/resources/{key}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert client.get(f"/api/v1/resources/{key}").status_code == 404


def test_create_conflict_and_validation(client):
    ok = client.post("/api/v1/resources", json=_crew_payload())
    assert ok.status_code == 200
    dup = client.post("/api/v1/resources", json=_crew_payload())
    assert dup.status_code == 409
    bad = client.post(
        "/api/v1/resources",
        json=_crew_payload(resource_key="BAD-1", resource_type="jet"),
    )
    assert bad.status_code == 400
    assert "invalid resource_type" in bad.json()["detail"]["error"]
    assert (
        client.put("/api/v1/resources/YOK", json={"status": "available"}).status_code
        == 404
    )
    assert client.delete("/api/v1/resources/YOK").status_code == 404


def test_list_and_capacity_endpoints(client):
    client.post("/api/v1/resources", json=_crew_payload())
    client.post(
        "/api/v1/resources",
        json=_crew_payload(resource_key="IHA-01", resource_type="iha", capacity=2.0),
    )
    listing = client.get("/api/v1/resources", params={"resource_type": "uav"})
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    assert body["resources"][0]["resource_key"] == "IHA-01"
    assert body["capacity"]["total_resources"] == 2  # rollup is global
    assert "attribution" in body

    capacity = client.get("/api/v1/resources/capacity")
    assert capacity.status_code == 200
    assert capacity.json()["capacity"]["by_type"]["uav"]["available"] == 1

    with_bad_filter = client.get("/api/v1/resources", params={"status": "yok"})
    assert with_bad_filter.status_code == 400


def test_csv_import_endpoint(client):
    response = client.post(
        "/api/v1/resources/import/csv",
        content=CSV_TEXT.encode("utf-8"),
        headers={"Content-Type": "text/csv"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["created"] == 3
    listing = client.get("/api/v1/resources")
    assert listing.json()["count"] == 3


def test_csv_import_endpoint_errors(client):
    header_only = client.post(
        "/api/v1/resources/import/csv",
        content=b"name,ad\n",
        headers={"Content-Type": "text/csv"},
    )
    assert header_only.status_code == 400
    assert "missing required column" in header_only.json()["detail"]["error"]
    undecodable = client.post(
        "/api/v1/resources/import/csv",
        content=b"\xff\xfe\x00bad",
        headers={"Content-Type": "text/csv"},
    )
    assert undecodable.status_code == 400
    assert "UTF-8" in undecodable.json()["detail"]["error"]


# ------------------------------------------------------------------ ui ---


def test_inventory_page_served_with_design_system(client):
    response = client.get("/inventory")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    # EM-075 bileşenleri + canlı API sözleşmesi (CRUD, kapasite, CSV).
    for fragment in (
        "/static/tokens.css",
        "/static/components.css",
        "em-table",
        "em-form",
        "theme-toggle",
        "/api/v1/resources",
        "/import/csv",  # URL, API sabitinden kuruluyor (${API}/import/csv)
        "Kaynak Envanteri",
    ):
        assert fragment in html, fragment


def test_inventory_screen_wired_into_map_and_panel(client):
    """Kabul: kapasite hesabı güncel kalsın — ekranlar arası bağlantı."""
    assert "/inventory" in client.get("/ui").text
    assert "Kaynak Envanteri (EM-103)" in client.get("/panel").text
