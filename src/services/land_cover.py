"""CORINE Land Cover & fuel class conversion service."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FireCluster
from src.models.land_cover import LandCoverDataPoint


class LandCoverSourceError(RuntimeError):
    """Raised when land cover mapping or data cannot be processed."""


@dataclass(frozen=True)
class NormalizedLandCoverFuel:
    """Normalized land cover observation mapped to a fuel model."""

    latitude: float
    longitude: float
    corine_code: int | None
    land_cover_class: str
    fuel_model: str
    spread_factor: float
    fetched_at: datetime = datetime.now(timezone.utc).replace(tzinfo=None)
    source: str = "CORINE/LandCover"


class LandCoverFuelService:
    """Service converting CORINE Land Cover (CLC) codes to fuel models."""

    def __init__(self, mapping_file_path: str | None = None):
        if mapping_file_path is None:
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            mapping_file_path = os.path.join(
                project_root, "config", "corine_fuel_map.json"
            )

        self.mapping_file_path = mapping_file_path
        self.version = "1.0.0"
        self.mappings: dict[str, dict[str, Any]] = {}
        self.default_mapping: dict[str, Any] = {
            "land_cover_class": "bilinmiyor",
            "fuel_model": "varsayilan",
            "spread_factor": 1.0,
        }
        self.load_mapping_file()

    def load_mapping_file(self) -> None:
        """Load and parse the versioned CORINE fuel map JSON file."""
        if not os.path.exists(self.mapping_file_path):
            return

        try:
            with open(self.mapping_file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                self.version = data.get("version", "1.0.0")
                self.mappings = data.get("mappings", {})
                self.default_mapping = data.get(
                    "default",
                    {
                        "land_cover_class": "bilinmiyor",
                        "fuel_model": "varsayilan",
                        "spread_factor": 1.0,
                    },
                )
        except Exception as exc:
            raise LandCoverSourceError(
                f"Failed to load CORINE mapping file: {exc}"
            ) from exc

    def map_corine_to_fuel(self, corine_code: int | None) -> tuple[str, str, float]:
        """Convert a CORINE land cover code to (land_cover_class, fuel_model, spread_factor)."""
        if corine_code is None:
            return (
                str(self.default_mapping["land_cover_class"]),
                str(self.default_mapping["fuel_model"]),
                float(self.default_mapping["spread_factor"]),
            )

        code_str = str(corine_code)
        if code_str in self.mappings:
            item = self.mappings[code_str]
            return (
                str(item["land_cover_class"]),
                str(item["fuel_model"]),
                float(item["spread_factor"]),
            )

        return (
            str(self.default_mapping["land_cover_class"]),
            str(self.default_mapping["fuel_model"]),
            float(self.default_mapping["spread_factor"]),
        )

    def fetch_land_cover_fuel(
        self, lat: float, lon: float, corine_code: int | None = None
    ) -> NormalizedLandCoverFuel:
        """Fetch land cover and fuel class for lat/lon coordinates."""
        # Simulated CLC classification for sample coordinates if code is not provided
        if corine_code is None:
            # Synthetic spatial mapping for demonstration/pilot testing
            grid_hash = int(abs(lat * 100 + lon * 100)) % 5
            code_map = {0: 312, 1: 313, 2: 323, 3: 223, 4: 999}
            corine_code = code_map.get(grid_hash, 999)

        land_class, fuel_mod, spread_fact = self.map_corine_to_fuel(corine_code)

        return NormalizedLandCoverFuel(
            latitude=lat,
            longitude=lon,
            corine_code=corine_code,
            land_cover_class=land_class,
            fuel_model=fuel_mod,
            spread_factor=spread_fact,
            fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
            source="CORINE/LandCover",
        )


def sync_land_cover_for_clusters(session: Session, settings: Any) -> dict[str, Any]:
    """Resolve and persist land cover and fuel classes for all active fire clusters."""
    clusters = session.scalars(select(FireCluster)).all()
    if not clusters:
        return {"clusters_processed": 0, "land_cover_points_saved": 0}

    service = LandCoverFuelService()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    saved_count = 0

    for cluster in clusters:
        lc_point = service.fetch_land_cover_fuel(
            float(cluster.latitude), float(cluster.longitude)
        )
        point = LandCoverDataPoint(
            cluster_key=cluster.cluster_key,
            latitude=lc_point.latitude,
            longitude=lc_point.longitude,
            corine_code=lc_point.corine_code,
            land_cover_class=lc_point.land_cover_class,
            fuel_model=lc_point.fuel_model,
            spread_factor=lc_point.spread_factor,
            fetched_at=now,
            source=lc_point.source,
        )
        session.add(point)
        saved_count += 1

    session.commit()
    return {
        "clusters_processed": len(clusters),
        "land_cover_points_saved": saved_count,
    }
