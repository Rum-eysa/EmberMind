"""OpenWeather data fetching, caching, retry, and persistence service."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from typing import Any

import requests  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.fire import FireCluster
from src.models.weather import WeatherDataPoint
from src.utils.timeutils import utc_now


class WeatherSourceError(RuntimeError):
    """Raised when weather forecast data cannot be fetched or parsed."""


@dataclass(frozen=True)
class NormalizedWeather:
    """Normalized weather observation / 0-6h forecast point."""

    latitude: float
    longitude: float
    temperature: float
    humidity: float
    wind_speed: float
    wind_deg: float
    forecast_offset_hours: int
    forecast_time: datetime
    fetched_at: datetime
    source: str = "OpenWeatherMap"


class OpenWeatherClient:
    """Client for fetching 0-6h weather forecasts with caching & retry logic."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openweathermap.org/data/2.5",
        cache_ttl_seconds: int = 1800,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        timeout: int = 10,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        self._cache: dict[str, tuple[float, list[NormalizedWeather]]] = {}

    def _cache_key(self, lat: float, lon: float) -> str:
        return f"{lat:.2f},{lon:.2f}"

    def fetch_forecast_0_6h(self, lat: float, lon: float) -> list[NormalizedWeather]:
        """Fetch 0–6 hour weather forecast for lat/lon, using cache & retries."""
        now_ts = time.time()
        cache_key = self._cache_key(lat, lon)

        # 1. Check cache
        if cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if now_ts - cached_time < self.cache_ttl_seconds:
                return cached_data

        if not self.api_key:
            raise WeatherSourceError("OPENWEATHER_API_KEY is not configured")

        url = f"{self.base_url}/forecast"
        params: dict[str, Any] = {
            "lat": lat,
            "lon": lon,
            "appid": self.api_key,
            "units": "metric",
        }

        # 2. Retry loop with exponential backoff
        last_exception: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                forecasts = self._parse_forecast_response(lat, lon, data)
                self._cache[cache_key] = (now_ts, forecasts)
                return forecasts
            except (requests.RequestException, ValueError, KeyError) as exc:
                last_exception = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_factor * (2**attempt))

        # 3. Quota/failure fallback: if expired cache exists, return stale cache
        if cache_key in self._cache:
            _, stale_data = self._cache[cache_key]
            return [
                NormalizedWeather(
                    latitude=item.latitude,
                    longitude=item.longitude,
                    temperature=item.temperature,
                    humidity=item.humidity,
                    wind_speed=item.wind_speed,
                    wind_deg=item.wind_deg,
                    forecast_offset_hours=item.forecast_offset_hours,
                    forecast_time=item.forecast_time,
                    fetched_at=item.fetched_at,
                    source="OpenWeatherMap-Cache",
                )
                for item in stale_data
            ]

        raise WeatherSourceError(
            f"OpenWeather request failed after {self.max_retries} attempts: {last_exception}"
        ) from last_exception

    def _parse_forecast_response(
        self, lat: float, lon: float, data: dict[str, Any]
    ) -> list[NormalizedWeather]:
        """Parse OpenWeather API JSON and extract 0-6h forecast items."""
        now = utc_now()
        max_horizon = now + timedelta(hours=6, minutes=30)
        results: list[NormalizedWeather] = []

        # OpenWeather /forecast endpoint format
        forecast_list = data.get("list", [])
        if not isinstance(forecast_list, list):
            forecast_list = [data]

        for item in forecast_list:
            dt_ts = item.get("dt")
            if dt_ts is not None:
                forecast_time = datetime.fromtimestamp(dt_ts, tz=timezone.utc).replace(
                    tzinfo=None
                )
            else:
                forecast_time = now

            # Filter for 0 - 6 hour forecast horizon
            if forecast_time > max_horizon:
                continue

            offset_seconds = (forecast_time - now).total_seconds()
            offset_hours = max(0, int(round(offset_seconds / 3600.0)))

            main = item.get("main", {})
            wind = item.get("wind", {})

            temp = float(main.get("temp", 0.0))
            humidity = float(main.get("humidity", 0.0))
            wind_speed = float(wind.get("speed", 0.0))
            wind_deg = float(wind.get("deg", 0.0))

            results.append(
                NormalizedWeather(
                    latitude=lat,
                    longitude=lon,
                    temperature=temp,
                    humidity=humidity,
                    wind_speed=wind_speed,
                    wind_deg=wind_deg,
                    forecast_offset_hours=offset_hours,
                    forecast_time=forecast_time,
                    fetched_at=now,
                    source="OpenWeatherMap",
                )
            )

        if not results and "main" in data:
            # Single observation fallback (e.g., /weather current endpoint)
            main = data.get("main", {})
            wind = data.get("wind", {})
            results.append(
                NormalizedWeather(
                    latitude=lat,
                    longitude=lon,
                    temperature=float(main.get("temp", 0.0)),
                    humidity=float(main.get("humidity", 0.0)),
                    wind_speed=float(wind.get("speed", 0.0)),
                    wind_deg=float(wind.get("deg", 0.0)),
                    forecast_offset_hours=0,
                    forecast_time=now,
                    fetched_at=now,
                    source="OpenWeatherMap",
                )
            )

        return results


def sync_weather_for_clusters(
    session: Session,
    settings: Any,
    client: OpenWeatherClient | None = None,
) -> dict[str, int]:
    """Fetch 0-6h weather forecasts for active fire clusters and persist them."""
    if client is None:
        client = OpenWeatherClient(
            api_key=settings.OPENWEATHER_API_KEY,
            base_url=settings.OPENWEATHER_BASE_URL,
            cache_ttl_seconds=settings.OPENWEATHER_CACHE_TTL_SECONDS,
            max_retries=settings.WEATHER_RETRY_COUNT,
        )

    clusters = session.scalars(select(FireCluster)).all()
    points_saved = 0
    clusters_processed = 0

    for cluster in clusters:
        try:
            forecasts = client.fetch_forecast_0_6h(
                lat=float(cluster.latitude), lon=float(cluster.longitude)  # type: ignore[arg-type]
            )
            for item in forecasts:
                record = WeatherDataPoint(
                    cluster_key=str(cluster.cluster_key),
                    latitude=item.latitude,
                    longitude=item.longitude,
                    temperature=item.temperature,
                    humidity=item.humidity,
                    wind_speed=item.wind_speed,
                    wind_deg=item.wind_deg,
                    forecast_offset_hours=item.forecast_offset_hours,
                    forecast_time=item.forecast_time,
                    fetched_at=item.fetched_at,
                    source=item.source,
                )
                session.add(record)
                points_saved += 1
            clusters_processed += 1

        except WeatherSourceError:
            # Log or handle individual cluster weather fetch errors
            continue

    session.flush()
    return {
        "clusters_processed": clusters_processed,
        "weather_points_saved": points_saved,
    }
