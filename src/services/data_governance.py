"""Data source license, attribution and quota governance (EM-013).

Every external open-data source carries legal (license/attribution) and
operational (quota/rate-limit) obligations. This module keeps one canonical
registry so the API, the UI footer and the documentation all cite the same
texts, and so quota pressure is classified before it becomes an outage.
Sources flagged with a real quota risk carry an explicit cache plan.
"""
from dataclasses import asdict, dataclass
from math import ceil
from typing import Any

MINUTES_PER_DAY = 24 * 60

# Documented usage limits of the public services we call (as of 2026).
FIRMS_QUOTA_TRANSACTIONS = 5000  # per MAP_KEY, per 10-minute interval
FIRMS_QUOTA_INTERVAL_MINUTES = 10
OPENWEATHER_QUOTA_REQUESTS_PER_DAY = 33_000  # ~1M/month free tier
OVERPASS_QUOTA_REQUESTS_PER_DAY = 10_000  # public-instance guideline

QUOTA_RISK_HIGH_RATIO = 0.5
QUOTA_RISK_MEDIUM_RATIO = 0.15


@dataclass(frozen=True)
class CachePlan:
    """How a source is cached to stay inside its quota envelope."""

    strategy: str
    ttl_seconds: int
    backend: str
    key_scope: str
    refresh_policy: str
    notes: str


@dataclass(frozen=True)
class SourceGovernance:
    """License, attribution and quota facts for one external data source."""

    key: str
    display_name: str
    license_name: str
    license_url: str
    attribution_text: str
    quota_note: str
    quota_requests_per_day: int | None
    sync_interval_minutes: int
    requests_per_sync: int
    community_hosted: bool
    offline: bool
    cache_plan: CachePlan


def estimated_daily_requests(source: SourceGovernance) -> int:
    """Predicted requests per day for one source at its configured cadence."""
    if source.offline or source.sync_interval_minutes <= 0:
        return 0
    syncs_per_day = ceil(MINUTES_PER_DAY / source.sync_interval_minutes)
    return syncs_per_day * source.requests_per_sync


def quota_risk(source: SourceGovernance) -> str:
    """Classify quota-overrun risk: low, medium or high."""
    if source.offline:
        return "low"
    if source.quota_requests_per_day is None:
        return "high" if source.community_hosted else "low"
    ratio = estimated_daily_requests(source) / source.quota_requests_per_day
    if ratio >= QUOTA_RISK_HIGH_RATIO:
        return "high"
    if ratio >= QUOTA_RISK_MEDIUM_RATIO:
        return "medium"
    return "low"


def _firms(settings: Any) -> SourceGovernance:
    products = getattr(settings, "FIRMS_SOURCES", None) or ["VIIRS_SNPP_NRT"]
    return SourceGovernance(
        key="firms",
        display_name="NASA FIRMS (VIIRS/MODIS)",
        license_name="NASA Open Data (public domain, credit requested)",
        license_url="https://firms.modaps.eosdis.nasa.gov/using-firms-data/",
        attribution_text=(
            "Fire detections are courtesy of NASA/LANCE/FIRMS "
            "(https://firms.modaps.eosdis.nasa.gov)."
        ),
        quota_note=(
            f"MAP_KEY limit: {FIRMS_QUOTA_TRANSACTIONS} transactions per "
            f"{FIRMS_QUOTA_INTERVAL_MINUTES} min; {len(products)} products "
            "fetched per sync."
        ),
        quota_requests_per_day=(
            FIRMS_QUOTA_TRANSACTIONS * (MINUTES_PER_DAY // FIRMS_QUOTA_INTERVAL_MINUTES)
        ),
        sync_interval_minutes=int(getattr(settings, "FIRMS_SYNC_INTERVAL_MINUTES", 10)),
        requests_per_sync=len(products),
        community_hosted=False,
        offline=False,
        cache_plan=CachePlan(
            strategy="response cache + merged multi-product fetch",
            ttl_seconds=300,
            backend="redis (CACHE_REDIS_URL)",
            key_scope="product + bbox + acquisition day",
            refresh_policy="skip re-pull while cached copy is < 5 min old",
            notes=(
                "EM-012 merge already deduplicates products client-side; "
                "reduce product list or widen interval if key usage spikes."
            ),
        ),
    )


def _weather(settings: Any) -> SourceGovernance:
    return SourceGovernance(
        key="weather",
        display_name="OpenWeather Forecast",
        license_name="CC BY 4.0 (OpenWeatherMap data)",
        license_url="https://openweathermap.org/copyright",
        attribution_text=(
            "Weather data by OpenWeatherMap (https://openweathermap.org/), "
            "licensed under CC BY 4.0."
        ),
        quota_note=(
            "Free tier: 60 calls/min and ~1M calls/month "
            f"(~{OPENWEATHER_QUOTA_REQUESTS_PER_DAY}/day); one call per "
            "active cluster per sync."
        ),
        quota_requests_per_day=OPENWEATHER_QUOTA_REQUESTS_PER_DAY,
        sync_interval_minutes=int(
            getattr(settings, "WEATHER_SYNC_INTERVAL_MINUTES", 10)
        ),
        requests_per_sync=20,  # planning estimate: ~20 active clusters
        community_hosted=False,
        offline=False,
        cache_plan=CachePlan(
            strategy="in-process TTL cache (already implemented in client)",
            ttl_seconds=int(getattr(settings, "OPENWEATHER_CACHE_TTL_SECONDS", 1800)),
            backend="memory + redis when configured",
            key_scope="rounded lat/lon + forecast horizon",
            refresh_policy="serve cached forecast until TTL expires",
            notes=(
                "Cluster count drives volume; if active clusters grow past "
                "~100, widen WEATHER_SYNC_INTERVAL_MINUTES before quota hurts."
            ),
        ),
    )


def _topography(settings: Any) -> SourceGovernance:
    return SourceGovernance(
        key="topography",
        display_name="USGS SRTM via Open-Elevation",
        license_name="NASA SRTM (public domain); community-hosted service",
        license_url="https://open-elevation.com/",
        attribution_text=(
            "Elevation data: NASA SRTM via the Open-Elevation project "
            "(https://open-elevation.com/)."
        ),
        quota_note=(
            "Community demo instance: no published quota and no SLA; "
            "abuse-based throttling applies."
        ),
        quota_requests_per_day=None,
        sync_interval_minutes=int(
            getattr(settings, "TOPOGRAPHY_SYNC_INTERVAL_MINUTES", 10)
        ),
        requests_per_sync=1,  # batched /lookup per sync run
        community_hosted=True,
        offline=False,
        cache_plan=CachePlan(
            strategy="persist-then-skip (elevation is static)",
            ttl_seconds=int(getattr(settings, "TOPOGRAPHY_CACHE_TTL_SECONDS", 86400)),
            backend="database (topography_data_points)",
            key_scope="30 m grid cell (EM-005 standard grid)",
            refresh_policy=(
                "only fetch cells never seen before; annual re-check for "
                "newly added clusters"
            ),
            notes=(
                "Highest-risk source: switch base URL to a self-hosted "
                "Open-Elevation or direct SRTM tile server if throttled."
            ),
        ),
    )


def _roads(settings: Any) -> SourceGovernance:
    return SourceGovernance(
        key="road_network",
        display_name="OpenStreetMap via Overpass",
        license_name="ODbL 1.0 (OpenStreetMap contributors)",
        license_url="https://www.openstreetmap.org/copyright",
        attribution_text="\u00a9 OpenStreetMap contributors (https://www.openstreetmap.org/copyright).",
        quota_note=(
            f"Public-instance guideline: ~{OVERPASS_QUOTA_REQUESTS_PER_DAY} "
            "queries/day and download-volume caps; heavy area queries."
        ),
        quota_requests_per_day=OVERPASS_QUOTA_REQUESTS_PER_DAY,
        sync_interval_minutes=int(
            getattr(settings, "ROAD_NETWORK_SYNC_INTERVAL_MINUTES", 720)
        ),
        requests_per_sync=1,
        community_hosted=True,
        offline=False,
        cache_plan=CachePlan(
            strategy="persist-then-skip (network imported once, refreshed rarely)",
            ttl_seconds=30 * 24 * 3600,
            backend="database (road_segments)",
            key_scope="pilot-region bbox",
            refresh_policy="monthly re-import; on-demand sync only for changes",
            notes=(
                "If public instances throttle us, import from a Geofabrik "
                "extract or a self-hosted Overpass instance."
            ),
        ),
    )


def _land_cover(settings: Any) -> SourceGovernance:
    return SourceGovernance(
        key="land_cover",
        display_name="CORINE Land Cover (Copernicus)",
        license_name="Copernicus licence (free re-use, attribution required)",
        license_url="https://land.copernicus.eu/corine/land-cover",
        attribution_text=(
            "Land cover classification: Copernicus Land Monitoring Service / "
            "EEA CORINE (https://land.copernicus.eu)."
        ),
        quota_note=(
            "No runtime API calls: annual raster is pre-processed into the "
            "local fuel mapping file (config/corine_fuel_map.json)."
        ),
        quota_requests_per_day=None,
        sync_interval_minutes=int(
            getattr(settings, "LAND_COVER_SYNC_INTERVAL_MINUTES", 10)
        ),
        requests_per_sync=0,
        community_hosted=False,
        offline=True,
        cache_plan=CachePlan(
            strategy="static local dataset",
            ttl_seconds=365 * 24 * 3600,
            backend="filesystem (config/corine_fuel_map.json)",
            key_scope="CORINE class code -> fuel model",
            refresh_policy="rebuild mapping file when a new CORINE edition ships",
            notes="Zero quota exposure at runtime.",
        ),
    )


def _effis(settings: Any) -> SourceGovernance:
    years = getattr(settings, "EFFIS_HISTORICAL_YEARS", [2007, 2008, 2012, 2017, 2021])
    return SourceGovernance(
        key="historical_fire",
        display_name="EFFIS Historical Perimeters",
        license_name="EFFIS/JRC data terms (re-use with source acknowledgement)",
        license_url="https://effis.jrc.ec.europa.eu/about-effis/term-of-use/",
        attribution_text=(
            "Historical fire perimeters: EFFIS, European Commission / JRC "
            "(https://effis.jrc.ec.europa.eu)."
        ),
        quota_note=(
            "ArcGIS REST service under fair-use; one query per fire year " "per import."
        ),
        quota_requests_per_day=None,
        sync_interval_minutes=int(
            getattr(settings, "EFFIS_HISTORICAL_SYNC_INTERVAL_MINUTES", 10080)
        ),
        requests_per_sync=len(years),
        community_hosted=False,
        offline=False,
        cache_plan=CachePlan(
            strategy="persist-then-skip (perimeters are immutable history)",
            ttl_seconds=7 * 24 * 3600,
            backend="database (historical_fire_perimeters)",
            key_scope="perimeter_key (effis_year_objectid)",
            refresh_policy="weekly import only pulls years not fully stored",
            notes="Bulk dataset changes once a year; keep an offline snapshot.",
        ),
    )


def build_governance_registry(settings: Any) -> list[SourceGovernance]:
    """Return the license/quota record for every external data source."""
    return [
        _firms(settings),
        _weather(settings),
        _topography(settings),
        _roads(settings),
        _land_cover(settings),
        _effis(settings),
    ]


def _row(source: SourceGovernance) -> dict[str, Any]:
    data = asdict(source)
    data["estimated_daily_requests"] = estimated_daily_requests(source)
    data["quota_risk"] = quota_risk(source)
    return data


def license_table(settings: Any) -> dict[str, Any]:
    """Full license/attribution/quota table for API and documentation use."""
    rows = [_row(source) for source in build_governance_registry(settings)]
    return {
        "source": "EM-013 data governance registry",
        "count": len(rows),
        "risk_summary": {
            risk: sum(1 for row in rows if row["quota_risk"] == risk)
            for risk in ("low", "medium", "high")
        },
        "sources": rows,
    }


def attribution_for(settings: Any, key: str) -> str | None:
    """Attribution text for one source key (used by data endpoints and UI)."""
    for source in build_governance_registry(settings):
        if source.key == key:
            return source.attribution_text
    return None


def attribution_block(settings: Any) -> dict[str, Any]:
    """All attribution texts plus a combined string for the UI footer."""
    sources = build_governance_registry(settings)
    return {
        "count": len(sources),
        "attributions": [
            {
                "source": source.key,
                "display_name": source.display_name,
                "attribution_text": source.attribution_text,
                "license_name": source.license_name,
            }
            for source in sources
        ],
        "combined_footer": "  |  ".join(source.attribution_text for source in sources),
    }


def cache_plan_report(settings: Any) -> dict[str, Any]:
    """Cache plans, highlighting the sources that carry quota-overrun risk."""
    rows = [_row(source) for source in build_governance_registry(settings)]
    at_risk = [row for row in rows if row["quota_risk"] in ("medium", "high")]
    return {
        "at_risk_count": len(at_risk),
        "at_risk_sources": [
            {
                "source": row["key"],
                "display_name": row["display_name"],
                "quota_risk": row["quota_risk"],
                "estimated_daily_requests": row["estimated_daily_requests"],
                "quota_requests_per_day": row["quota_requests_per_day"],
                "cache_plan": row["cache_plan"],
            }
            for row in at_risk
        ],
        "all_plans": {row["key"]: row["cache_plan"] for row in rows},
    }
