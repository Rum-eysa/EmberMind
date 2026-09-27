"""Multi-satellite detection merging and deduplication (EM-012).

VIIRS (375 m, frequent) and MODIS (1 km, complementary orbits) products are
fetched from NASA FIRMS, translated onto the shared ``NormalizedFire`` schema
by :mod:`src.services.firms`, then merged here. When two detections describe
the same fire — within the cluster radius and the acquisition time window —
the finer-resolution sensor wins and the redundant detection is dropped and
counted, so the same fire is never reported twice to operators.
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FireCluster, FireObservation
from src.services.firms import (
    FirmsClient,
    NormalizedFire,
    distance_km,
    persist_observations,
)

_LOG = logging.getLogger(__name__)

# Lower value = finer resolution = preferred when deduplicating.
SENSOR_PRIORITY: dict[str, int] = {"VIIRS": 0, "MODIS": 1}
DEFAULT_SENSOR_PRIORITY = 2


@dataclass(frozen=True)
class DuplicatePair:
    """A dropped detection and the surviving detection it duplicated."""

    dropped: NormalizedFire
    kept: NormalizedFire


@dataclass
class MergeResult:
    """Outcome of merging every configured satellite product."""

    observations: list[NormalizedFire] = field(default_factory=list)
    duplicates: list[DuplicatePair] = field(default_factory=list)
    per_source_counts: dict[str, int] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)

    @property
    def duplicates_removed(self) -> int:
        return len(self.duplicates)

    @property
    def sources(self) -> list[str]:
        """Satellites that actually contributed detections to the merge."""
        return sorted(
            {item.satellite or item.product or "unknown" for item in self.observations}
        )


def _priority(item: NormalizedFire) -> int:
    instrument = (item.instrument or "").upper()
    for sensor, value in SENSOR_PRIORITY.items():
        if sensor in instrument:
            return value
    return DEFAULT_SENSOR_PRIORITY


def _sort_key(item: NormalizedFire) -> tuple[int, Any, str]:
    """Preferred detections first: sensor resolution, then recency, then id."""
    return (_priority(item), item.observed_at, item.source_id)


def deduplicate_detections(
    observations: Iterable[NormalizedFire],
    radius_km: float = 2.0,
    time_window_minutes: int = 180,
) -> tuple[list[NormalizedFire], list[DuplicatePair]]:
    """Collapse overlapping detections of the same fire into one record.

    Two detections are considered the same fire when they are within
    ``radius_km`` of each other and acquired within ``time_window_minutes``.
    The preferred survivor is the finer-resolution sensor (VIIRS over MODIS),
    breaking ties by earliest acquisition.
    """
    window = timedelta(minutes=time_window_minutes)
    kept: list[NormalizedFire] = []
    duplicates: list[DuplicatePair] = []
    for item in sorted(observations, key=_sort_key):
        match = next(
            (
                survivor
                for survivor in kept
                if abs(item.observed_at - survivor.observed_at) <= window
                and distance_km(item, survivor) <= radius_km
            ),
            None,
        )
        if match is None:
            kept.append(item)
        else:
            duplicates.append(DuplicatePair(dropped=item, kept=match))
    return kept, duplicates


def merge_satellite_detections(
    detections_by_product: dict[str, list[NormalizedFire]],
    radius_km: float = 2.0,
    time_window_minutes: int = 180,
) -> MergeResult:
    """Merge per-product detection lists and deduplicate overlapping fires."""
    all_items = [item for items in detections_by_product.values() for item in items]
    kept, duplicates = deduplicate_detections(all_items, radius_km, time_window_minutes)
    return MergeResult(
        observations=kept,
        duplicates=duplicates,
        per_source_counts={
            product: len(items) for product, items in detections_by_product.items()
        },
    )


def build_satellite_clients(settings: Any) -> list[FirmsClient]:
    """Create one FIRMS client per configured VIIRS/MODIS product."""
    sources = getattr(settings, "FIRMS_SOURCES", None)
    if not sources:
        legacy = getattr(settings, "FIRMS_SOURCE", "VIIRS_SNPP_NRT")
        sources = [legacy]
    return [
        FirmsClient(
            api_key=settings.FIRMS_API_KEY,
            source=source,
            bbox=settings.FIRMS_BBOX,
            days=settings.FIRMS_DAYS,
        )
        for source in sources
    ]


def fetch_all_sources(
    clients: list[FirmsClient],
) -> tuple[dict[str, list[NormalizedFire]], list[str]]:
    """Fetch every client, tolerating individual product outages.

    Returns the detections grouped by product plus the list of products that
    failed. Only when *every* product fails is the merge considered failed;
    partial coverage is preferred over no coverage.
    """
    detections: dict[str, list[NormalizedFire]] = {}
    failed: list[str] = []
    for client in clients:
        try:
            detections[client.source] = client.fetch()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Any single product outage must not kill the whole sync, but it
            # must leave a trace for the on-call operator.
            _LOG.warning("satellite product %s fetch failed: %s", client.source, exc)
            failed.append(client.source)
    return detections, failed


def ingest_satellite_observations(
    session: Session,
    merged: MergeResult,
    cluster_radius_km: float = 2.0,
) -> dict[str, int]:
    """Persist merged detections and attribute deduplicated counts to clusters."""
    result = persist_observations(session, merged.observations, cluster_radius_km)
    for pair in merged.duplicates:
        survivor = session.scalar(
            select(FireObservation).where(
                FireObservation.source_id == pair.kept.source_id
            )
        )
        if survivor is None or not survivor.cluster_key:
            continue
        cluster = session.scalar(
            select(FireCluster).where(FireCluster.cluster_key == survivor.cluster_key)
        )
        if cluster is not None:
            cluster.deduplicated_count = int(cluster.deduplicated_count or 0) + 1  # type: ignore[assignment]
    session.flush()
    result["duplicates_removed"] = merged.duplicates_removed
    return result


def satellite_coverage_summary(merged: MergeResult) -> dict[str, Any]:
    """Describe which products contributed detections and which were dropped."""
    coverage: dict[str, Any] = {
        "products": dict(sorted(merged.per_source_counts.items())),
        "failed_products": list(merged.failed_sources),
        "merged_detections": merged.duplicates_removed,
        "unique_detections": len(merged.observations),
    }
    return coverage


def merge_and_ingest(
    session: Session,
    detections_by_product: dict[str, list[NormalizedFire]],
    failed_sources: Optional[list[str]] = None,
    radius_km: float = 2.0,
    time_window_minutes: int = 180,
) -> tuple[MergeResult, dict[str, int]]:
    """One-shot pipeline entry: merge raw per-product lists then persist."""
    merged = merge_satellite_detections(
        detections_by_product, radius_km, time_window_minutes
    )
    merged.failed_sources = list(failed_sources or [])
    result = ingest_satellite_observations(session, merged, radius_km)
    return merged, result
