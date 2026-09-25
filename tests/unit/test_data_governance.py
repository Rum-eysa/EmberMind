"""Data source license, attribution and quota governance tests (EM-013)."""
from typing import Any

from src.services.data_governance import (
    attribution_block,
    attribution_for,
    build_governance_registry,
    cache_plan_report,
    estimated_daily_requests,
    license_table,
    quota_risk,
)

EXPECTED_KEYS = {
    "firms",
    "weather",
    "topography",
    "road_network",
    "land_cover",
    "historical_fire",
}


class Settings:
    """Minimal settings stand-in matching the production Config defaults."""

    FIRMS_SOURCES = ["VIIRS_SNPP_NRT", "MODIS_Terra_CorrectedAnomalies"]
    FIRMS_SYNC_INTERVAL_MINUTES = 10
    WEATHER_SYNC_INTERVAL_MINUTES = 10
    OPENWEATHER_CACHE_TTL_SECONDS = 1800
    TOPOGRAPHY_SYNC_INTERVAL_MINUTES = 10
    TOPOGRAPHY_CACHE_TTL_SECONDS = 86400
    ROAD_NETWORK_SYNC_INTERVAL_MINUTES = 720
    LAND_COVER_SYNC_INTERVAL_MINUTES = 10
    EFFIS_HISTORICAL_SYNC_INTERVAL_MINUTES = 10080
    EFFIS_HISTORICAL_YEARS = [2007, 2008, 2012, 2017, 2021]


def _by_key(settings: Any) -> dict[str, Any]:
    return {source.key: source for source in build_governance_registry(settings)}


def test_registry_covers_every_external_source():
    registry = build_governance_registry(Settings())

    assert {source.key for source in registry} == EXPECTED_KEYS


def test_every_source_has_license_attribution_and_cache_plan():
    for source in build_governance_registry(Settings()):
        assert source.license_name, source.key
        assert source.license_url.startswith("https://"), source.key
        assert len(source.attribution_text) > 10, source.key
        assert source.cache_plan.strategy, source.key
        assert source.cache_plan.ttl_seconds > 0, source.key


def test_mandatory_attribution_texts_are_present():
    sources = _by_key(Settings())

    assert "OpenStreetMap contributors" in sources["road_network"].attribution_text
    assert "\u00a9" in sources["road_network"].attribution_text  # ODbL visible notice
    assert "CC BY 4.0" in sources["weather"].attribution_text
    assert "NASA" in sources["firms"].attribution_text
    assert "Copernicus" in sources["land_cover"].attribution_text
    assert "EFFIS" in sources["historical_fire"].attribution_text


def test_community_hosted_source_without_quota_is_high_risk():
    sources = _by_key(Settings())

    assert quota_risk(sources["topography"]) == "high"


def test_offline_source_estimates_zero_requests():
    sources = _by_key(Settings())

    assert estimated_daily_requests(sources["land_cover"]) == 0
    assert quota_risk(sources["land_cover"]) == "low"


def test_firms_daily_estimate_follows_product_count_and_interval():
    sources = _by_key(Settings())
    # 2 products x (1440 / 10 min) = 288 requests/day.
    assert estimated_daily_requests(sources["firms"]) == 288
    assert quota_risk(sources["firms"]) == "low"

    class SlowerSettings(Settings):
        FIRMS_SYNC_INTERVAL_MINUTES = 60

    slower = _by_key(SlowerSettings())
    assert estimated_daily_requests(slower["firms"]) == 48


def test_license_table_reports_risk_summary():
    table = license_table(Settings())

    assert table["count"] == len(EXPECTED_KEYS)
    assert sum(table["risk_summary"].values()) == len(EXPECTED_KEYS)
    rows = {row["key"]: row for row in table["sources"]}
    assert rows["topography"]["quota_risk"] == "high"
    assert rows["topography"]["cache_plan"]["ttl_seconds"] == 86400


def test_attribution_block_builds_ui_footer():
    block = attribution_block(Settings())

    assert block["count"] == len(EXPECTED_KEYS)
    assert "OpenStreetMap contributors" in block["combined_footer"]
    keys = {entry["source"] for entry in block["attributions"]}
    assert keys == EXPECTED_KEYS


def test_attribution_for_unknown_key_returns_none():
    assert attribution_for(Settings(), "nope") is None


def test_cache_plan_report_focuses_on_at_risk_sources():
    report = cache_plan_report(Settings())

    risky = {entry["source"] for entry in report["at_risk_sources"]}
    assert "topography" in risky
    assert "land_cover" not in risky
    assert set(report["all_plans"]) == EXPECTED_KEYS


def test_data_source_endpoints(client):
    table = client.get("/api/v1/data-sources")
    attribution = client.get("/api/v1/data-sources/attribution")
    plan = client.get("/api/v1/data-sources/cache-plan")

    assert table.status_code == 200
    assert table.json()["count"] == len(EXPECTED_KEYS)
    assert attribution.status_code == 200
    assert "NASA" in attribution.json()["combined_footer"]
    assert plan.status_code == 200
    assert plan.json()["at_risk_count"] >= 1


def test_fires_endpoint_carries_attribution(client):
    response = client.get("/api/v1/fires")

    assert response.status_code == 200
    assert "NASA" in response.json()["attribution"]
