"""EM-064 country-separated capacity accounting tests.

Every suppression resource belongs to a country and the capacity account is
totalled per country, shown separately; resources with no declared country are
isolated in an explicit unassigned bucket so no screen silently merges two
nations' resources.
"""
import pytest

from src.models.inventory import SuppressionResource
from src.services.capacity import (
    UNASSIGNED_COUNTRY,
    capacity_by_country,
    effective_capacity,
)

CREW_DEFAULT = 2.0
HELI_DEFAULT = 12.0
UAV_DEFAULT = 4.0


class _Settings:
    RISK_PANEL_THRESHOLD = 30.0


def _resource(session, key, rtype, status="available", country="TR", **extra):
    session.add(
        SuppressionResource(
            resource_key=key,
            name=key,
            resource_type=rtype,
            latitude=37.0,
            longitude=28.0,
            status=status,
            capacity=1.0,
            country=country,
            **extra,
        )
    )


def _country_map(result):
    return {row["country"]: row for row in result["countries"]}


def test_countries_are_never_merged(session):
    _resource(session, "crew-tr-1", "crew", country="TR")
    _resource(session, "crew-gr-1", "crew", country="GR")
    session.flush()
    result = capacity_by_country(session, _Settings())
    assert result["merged_by_default"] is False
    countries = _country_map(result)
    assert {"TR", "GR"} <= set(countries)
    # Each country carries exactly its own single crew (2.0 ha/hour).
    assert countries["TR"]["total_effective_ha_per_hour"] == pytest.approx(CREW_DEFAULT)
    assert countries["GR"]["total_effective_ha_per_hour"] == pytest.approx(CREW_DEFAULT)


def test_per_country_breakdown_by_type(session):
    _resource(session, "crew-tr-1", "crew", country="TR")
    _resource(session, "crew-tr-2", "crew", country="TR")
    _resource(session, "heli-tr-1", "helicopter", country="TR")
    session.flush()
    countries = _country_map(capacity_by_country(session, _Settings()))
    tr = countries["TR"]["by_type"]
    assert tr["crew"]["available"] == 2
    assert tr["crew"]["effective_ha_per_hour"] == pytest.approx(2 * CREW_DEFAULT)
    assert tr["helicopter"]["effective_ha_per_hour"] == pytest.approx(HELI_DEFAULT)
    assert countries["TR"]["total_effective_ha_per_hour"] == pytest.approx(
        2 * CREW_DEFAULT + HELI_DEFAULT
    )


def test_unassigned_country_isolated_explicitly(session):
    _resource(session, "crew-tr-1", "crew", country="TR")
    _resource(session, "crew-none-1", "crew", country=None)
    session.flush()
    countries = _country_map(capacity_by_country(session, _Settings()))
    assert UNASSIGNED_COUNTRY in countries
    assert countries[UNASSIGNED_COUNTRY][
        "total_effective_ha_per_hour"
    ] == pytest.approx(CREW_DEFAULT)
    # The unassigned bucket is its own row, never folded into TR.
    assert countries["TR"]["total_effective_ha_per_hour"] == pytest.approx(CREW_DEFAULT)


def test_only_available_status_counts(session):
    _resource(session, "crew-tr-avail", "crew", status="available", country="TR")
    _resource(session, "crew-tr-deployed", "crew", status="deployed", country="TR")
    _resource(session, "crew-tr-route", "crew", status="en_route", country="TR")
    _resource(session, "crew-tr-maint", "crew", status="maintenance", country="TR")
    session.flush()
    countries = _country_map(capacity_by_country(session, _Settings()))
    assert countries["TR"]["by_type"]["crew"]["available"] == 1
    assert countries["TR"]["total_effective_ha_per_hour"] == pytest.approx(CREW_DEFAULT)


def test_unknown_resource_type_ignored(session):
    _resource(session, "crew-tr-1", "crew", country="TR")
    _resource(session, "boat-tr-1", "boat", country="TR")  # not a known type
    session.flush()
    countries = _country_map(capacity_by_country(session, _Settings()))
    assert "boat" not in countries["TR"]["by_type"]
    assert countries["TR"]["total_effective_ha_per_hour"] == pytest.approx(CREW_DEFAULT)


def test_country_totals_sum_to_global_effective(session):
    _resource(session, "crew-tr-1", "crew", country="TR")
    _resource(session, "heli-tr-1", "helicopter", country="TR")
    _resource(session, "crew-gr-1", "crew", country="GR")
    _resource(session, "uav-gr-1", "uav", country="GR")
    _resource(session, "crew-x-1", "crew", country=None)
    session.flush()
    result = capacity_by_country(session, _Settings())
    per_country = sum(row["total_effective_ha_per_hour"] for row in result["countries"])
    global_total = effective_capacity(session, _Settings())[
        "total_effective_ha_per_hour"
    ]
    assert result["grand_total_effective_ha_per_hour"] == pytest.approx(global_total)
    assert per_country == pytest.approx(global_total)


def test_countries_sorted_deterministically(session):
    _resource(session, "crew-tr-1", "crew", country="TR")
    _resource(session, "crew-gr-1", "crew", country="GR")
    _resource(session, "crew-none-1", "crew", country=None)
    session.flush()
    names = [
        row["country"] for row in capacity_by_country(session, _Settings())["countries"]
    ]
    assert names == sorted(names)


def test_empty_inventory_returns_no_countries(session):
    result = capacity_by_country(session, _Settings())
    assert result["countries"] == []
    assert result["grand_total_effective_ha_per_hour"] == pytest.approx(0.0)
    assert result["merged_by_default"] is False


def test_endpoint_returns_country_capacity(client, session):
    _resource(session, "crew-tr-1", "crew", country="TR")
    _resource(session, "crew-gr-1", "crew", country="GR")
    session.commit()
    resp = client.get("/api/v1/capacity/by-country")
    assert resp.status_code == 200
    body = resp.json()
    assert "attribution" in body
    cap = body["capacity"]
    assert cap["merged_by_default"] is False
    assert cap["unit"] == "ha/saat"
    assert {row["country"] for row in cap["countries"]} == {"TR", "GR"}
