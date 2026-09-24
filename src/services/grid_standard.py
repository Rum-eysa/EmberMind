"""Pilot region definition, EPSG:4326/UTM coordinate transformation, and 30m grid resampling service."""
from dataclasses import dataclass
import json
import math
import os
from typing import Any


class GridStandardError(RuntimeError):
    """Raised when spatial transformation or grid resampling fails."""


@dataclass(frozen=True)
class CoordinatePoint:
    """Geographic or metric coordinate point."""

    latitude: float
    longitude: float
    crs: str = "EPSG:4326"
    easting_m: float | None = None
    northing_m: float | None = None
    utm_zone: str | None = None


@dataclass(frozen=True)
class GridCell:
    """30m spatial grid cell definition."""

    cell_id: str
    grid_lat: float
    grid_lon: float
    center_lat: float
    center_lon: float
    resolution_meters: int = 30


class PilotRegionGridService:
    """Service managing pilot region bounding box, EPSG:4326 <-> UTM projection, and 30m grid resampling."""

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            config_path = os.path.join(project_root, "config", "pilot_region.json")

        self.config_path = config_path
        self.min_lat = 36.0
        self.max_lat = 39.5
        self.min_lon = 26.0
        self.max_lon = 30.0
        self.resolution_meters = 30
        self.storage_crs = "EPSG:4326"
        self.metric_crs = "EPSG:32635"
        self.justification = (
            "TR-GR coastal wildfire zone (Aegean/Western Mediterranean)"
        )
        self.load_config()

    def load_config(self) -> None:
        """Load pilot region configuration from JSON file."""
        if not os.path.exists(self.config_path):
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                bbox = data.get("bounding_box", {})
                self.min_lat = float(bbox.get("min_latitude", 36.0))
                self.max_lat = float(bbox.get("max_latitude", 39.5))
                self.min_lon = float(bbox.get("min_longitude", 26.0))
                self.max_lon = float(bbox.get("max_longitude", 30.0))

                standards = data.get("coordinate_standards", {})
                self.storage_crs = str(standards.get("storage_crs", "EPSG:4326"))
                self.metric_crs = str(standards.get("metric_crs", "EPSG:32635"))

                grid_spec = data.get("grid_specification", {})
                self.resolution_meters = int(grid_spec.get("resolution_meters", 30))
                self.justification = str(data.get("justification", self.justification))
        except Exception as exc:
            raise GridStandardError(
                f"Failed to load pilot region config: {exc}"
            ) from exc

    def is_within_pilot_region(self, lat: float, lon: float) -> bool:
        """Check if coordinate falls within TR-GR coastal pilot region bounding box."""
        return (
            self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon
        )

    def wgs84_to_utm_35n(self, lat: float, lon: float) -> tuple[float, float, str]:
        """Convert WGS84 (EPSG:4326) coordinate to UTM Zone 35N (EPSG:32635) metric Easting/Northing."""
        # Central meridian for UTM Zone 35N = 27.0 deg East
        lon_0 = 27.0
        k0 = 0.9996
        a = 6378137.0  # WGS84 semi-major axis in meters
        f = 1 / 298.257223563
        e2 = 2 * f - f**2

        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        lon_0_rad = math.radians(lon_0)

        n = a / math.sqrt(1 - e2 * math.sin(lat_rad) ** 2)
        t = math.tan(lat_rad) ** 2
        c = (e2 / (1 - e2)) * math.cos(lat_rad) ** 2
        a_coeff = (lon_rad - lon_0_rad) * math.cos(lat_rad)

        # Meridional arc M calculation
        m = a * (
            (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * lat_rad
            - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024)
            * math.sin(2 * lat_rad)
            + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * lat_rad)
            - (35 * e2**3 / 3072) * math.sin(6 * lat_rad)
        )

        easting = 500000.0 + k0 * n * (
            a_coeff
            + (1 - t + c) * a_coeff**3 / 6
            + (5 - 18 * t + t**2 + 72 * c) * a_coeff**5 / 120
        )
        northing = k0 * (
            m
            + n
            * math.tan(lat_rad)
            * (
                a_coeff**2 / 2
                + (5 - t + 9 * c + 4 * c**2) * a_coeff**4 / 24
                + (61 - 58 * t + t**2 + 600 * c) * a_coeff**6 / 720
            )
        )

        return round(easting, 2), round(northing, 2), "EPSG:32635"

    def align_to_30m_grid(self, lat: float, lon: float) -> GridCell:
        """Snap coordinate to uniform 30m grid cell resolution (~0.00027 deg)."""
        deg_step = 0.00027
        grid_lat = round(round(lat / deg_step) * deg_step, 5)
        grid_lon = round(round(lon / deg_step) * deg_step, 5)

        cell_id = f"GRID_30M_{grid_lat:.5f}_{grid_lon:.5f}"

        return GridCell(
            cell_id=cell_id,
            grid_lat=grid_lat,
            grid_lon=grid_lon,
            center_lat=grid_lat,
            center_lon=grid_lon,
            resolution_meters=self.resolution_meters,
        )

    def resample_raster_layer_to_30m(
        self, raster_points: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Resample a spatial raster/point layer to uniform 30m grid cells using nearest neighbor."""
        grid_buckets: dict[str, dict[str, Any]] = {}

        for pt in raster_points:
            lat = float(pt.get("latitude", 0.0))
            lon = float(pt.get("longitude", 0.0))
            cell = self.align_to_30m_grid(lat, lon)

            if cell.cell_id not in grid_buckets:
                grid_buckets[cell.cell_id] = {
                    "cell_id": cell.cell_id,
                    "latitude": cell.center_lat,
                    "longitude": cell.center_lon,
                    "resolution_meters": self.resolution_meters,
                    "sample_count": 1,
                    "value": pt.get("value", 0.0),
                }
            else:
                bucket = grid_buckets[cell.cell_id]
                bucket["sample_count"] += 1
                # Average resampled value
                bucket["value"] = round(
                    (bucket["value"] + float(pt.get("value", 0.0))) / 2.0, 3
                )

        return list(grid_buckets.values())
