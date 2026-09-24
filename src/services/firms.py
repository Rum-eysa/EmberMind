"""NASA FIRMS ingestion, normalization, and clustering service."""
import csv
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FireCluster, FireObservation


class FirmsSourceError(RuntimeError):
    """Raised when NASA FIRMS cannot be reached or returns invalid data."""


@dataclass(frozen=True)
class NormalizedFire:
    source_id: str
    latitude: float
    longitude: float
    observed_at: datetime
    frp: float | None
    confidence: float | None
    satellite: str | None
    instrument: str | None


class FirmsClient:
    """Small client for the NASA FIRMS area CSV endpoint."""

    base_url = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

    def __init__(
        self, api_key: str, source: str, bbox: str, days: int = 1, timeout: int = 30
    ):
        self.api_key = api_key
        self.source = source
        self.bbox = bbox
        self.days = days
        self.timeout = timeout

    def fetch(self) -> list[NormalizedFire]:
        if not self.api_key:
            raise FirmsSourceError("FIRMS_API_KEY is not configured")

        url = f"{self.base_url}/{self.api_key}/{self.source}/{self.bbox}/{self.days}"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FirmsSourceError(f"NASA FIRMS request failed: {exc}") from exc

        try:
            rows = csv.DictReader(io.StringIO(response.text))
            return [self._normalize(row) for row in rows if row.get("latitude")]
        except (KeyError, TypeError, ValueError) as exc:
            raise FirmsSourceError(f"NASA FIRMS response is invalid: {exc}") from exc

    @staticmethod
    def _normalize(row: dict[str, str]) -> NormalizedFire:
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("coordinates are outside valid bounds")

        observed_at = (
            datetime.strptime(
                f"{row['acq_date']} {row['acq_time'].zfill(4)}", "%Y-%m-%d %H%M"
            )
            .replace(tzinfo=timezone.utc)
            .replace(tzinfo=None)
        )
        source_id = hashlib.sha256(
            f"{row.get('satellite', '')}|{row.get('instrument', '')}|{row['latitude']}|"
            f"{row['longitude']}|{row['acq_date']}|{row['acq_time']}".encode()
        ).hexdigest()[:32]

        return NormalizedFire(
            source_id=source_id,
            latitude=latitude,
            longitude=longitude,
            observed_at=observed_at,
            frp=_optional_float(row.get("frp")),
            confidence=_confidence(row.get("confidence")),
            satellite=row.get("satellite"),
            instrument=row.get("instrument"),
        )


def _optional_float(value: str | None) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    return float(value)


def _confidence(value: str | None) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return float(value)
    except ValueError:
        return {"low": 25.0, "nominal": 50.0, "high": 90.0}.get(value.lower())


def _distance_km(left: NormalizedFire, right: NormalizedFire) -> float:
    radius = 6371.0
    lat1, lat2 = math.radians(left.latitude), math.radians(right.latitude)
    delta_lat = math.radians(right.latitude - left.latitude)
    delta_lon = math.radians(right.longitude - left.longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(haversine))


def _distance_to_cluster(item: NormalizedFire, cluster: FireCluster) -> float:
    """Calculate distance from an observation to a persisted cluster center."""
    radius = 6371.0
    lat1, lat2 = math.radians(item.latitude), math.radians(cluster.latitude)
    delta_lat = math.radians(cluster.latitude - item.latitude)
    delta_lon = math.radians(cluster.longitude - item.longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(haversine))


def cluster_observations(
    observations: Iterable[NormalizedFire], radius_km: float = 2.0
) -> list[tuple[str, list[NormalizedFire]]]:
    """Group same-day observations whose coordinates are within radius_km."""
    items = list(observations)
    parents = list(range(len(items)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if (
                items[left].observed_at.date() == items[right].observed_at.date()
                and _distance_km(items[left], items[right]) <= radius_km
            ):
                union(left, right)

    groups: dict[int, list[NormalizedFire]] = {}
    for index, item in enumerate(items):
        groups.setdefault(find(index), []).append(item)

    result = []
    for group in groups.values():
        key = hashlib.sha256(
            "|".join(sorted(item.source_id for item in group)).encode()
        ).hexdigest()[:32]
        result.append((key, group))
    return result


def ingest_firms(
    session: Session, client: FirmsClient, cluster_radius_km: float = 2.0
) -> dict[str, int]:
    """Fetch FIRMS data and upsert normalized observations and clusters."""
    observations = client.fetch()
    total = 0
    clusters = 0
    for cluster_key, group in cluster_observations(observations, cluster_radius_km):
        first_seen = min(item.observed_at for item in group)
        last_seen = max(item.observed_at for item in group)
        existing = session.scalar(
            select(FireCluster).where(FireCluster.cluster_key == cluster_key)
        )
        if existing is None:
            existing = next(
                (
                    cluster
                    for cluster in session.scalars(select(FireCluster))
                    if cluster.first_seen_at.date() == first_seen.date()
                    and _distance_to_cluster(group[0], cluster) <= cluster_radius_km
                ),
                None,
            )
        latitude = sum(item.latitude for item in group) / len(group)
        longitude = sum(item.longitude for item in group) / len(group)
        frps = [item.frp for item in group if item.frp is not None]
        if existing is None:
            existing = FireCluster(cluster_key=cluster_key, first_seen_at=first_seen)
            session.add(existing)
            clusters += 1
        existing.latitude = latitude  # type: ignore[assignment]
        existing.longitude = longitude  # type: ignore[assignment]
        existing.observation_count = len(group)  # type: ignore[assignment]
        existing.max_frp = max(frps) if frps else None  # type: ignore[assignment]
        existing.last_seen_at = last_seen  # type: ignore[assignment]

        for item in group:
            record = session.scalar(
                select(FireObservation).where(
                    FireObservation.source_id == item.source_id
                )
            )
            if record is None:
                record = FireObservation(source_id=item.source_id)
                session.add(record)
            record.cluster_key = cluster_key  # type: ignore[assignment]
            record.latitude = item.latitude  # type: ignore[assignment]
            record.longitude = item.longitude  # type: ignore[assignment]
            record.observed_at = item.observed_at  # type: ignore[assignment]
            record.frp = item.frp  # type: ignore[assignment]
            record.confidence = item.confidence  # type: ignore[assignment]
            record.satellite = item.satellite  # type: ignore[assignment]
            record.instrument = item.instrument  # type: ignore[assignment]
            total += 1
            session.flush()
    return {"observations": total, "clusters": clusters}
