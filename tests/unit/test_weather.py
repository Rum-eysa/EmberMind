"""OpenWeather integration and persistence unit tests."""
from datetime import datetime, timedelta, timezone
import time

from typing import Any, cast

import pytest
import requests

from src.models.fire import FireCluster
from src.models.weather import WeatherDataPoint
from src.services.weather import (
    NormalizedWeather,
    OpenWeatherClient,
    WeatherSourceError,
    sync_weather_for_clusters,
)


class MockResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}", response=cast(requests.Response, self)
            )


def build_mock_forecast_json(now_ts: float) -> dict:
    return {
        "list": [
            {
                "dt": int(now_ts),
                "main": {"temp": 28.5, "humidity": 35.0},
                "wind": {"speed": 5.4, "deg": 180.0},
            },
            {
                "dt": int(now_ts + 10800),  # +3h
                "main": {"temp": 29.0, "humidity": 32.0},
                "wind": {"speed": 6.1, "deg": 190.0},
            },
            {
                "dt": int(now_ts + 21600),  # +6h
                "main": {"temp": 26.2, "humidity": 40.0},
                "wind": {"speed": 4.8, "deg": 175.0},
            },
            {
                "dt": int(now_ts + 43200),  # +12h (outside 0-6h horizon)
                "main": {"temp": 21.0, "humidity": 55.0},
                "wind": {"speed": 3.0, "deg": 160.0},
            },
        ]
    }


def test_missing_api_key_raises_error():
    client = OpenWeatherClient(api_key="")
    with pytest.raises(WeatherSourceError, match="OPENWEATHER_API_KEY"):
        client.fetch_forecast_0_6h(39.9, 32.8)


def test_openweather_fetch_0_6h_normalization(monkeypatch):
    now_ts = time.time()
    mock_json = build_mock_forecast_json(now_ts)

    def mock_get(url, params, timeout):
        return MockResponse(mock_json)

    monkeypatch.setattr("src.services.weather.requests.get", mock_get)

    client = OpenWeatherClient(api_key="valid_key")
    forecasts = client.fetch_forecast_0_6h(39.9, 32.8)

    # 3 points within 0-6h (0h, +3h, +6h)
    assert len(forecasts) == 3
    assert forecasts[0].temperature == 28.5
    assert forecasts[0].humidity == 35.0
    assert forecasts[0].wind_speed == 5.4
    assert forecasts[0].wind_deg == 180.0
    assert forecasts[0].source == "OpenWeatherMap"
    assert forecasts[1].forecast_offset_hours == 3
    assert forecasts[2].forecast_offset_hours == 6


def test_openweather_cache_prevents_duplicate_http_calls(monkeypatch):
    call_count = 0
    now_ts = time.time()
    mock_json = build_mock_forecast_json(now_ts)

    def mock_get(url, params, timeout):
        nonlocal call_count
        call_count += 1
        return MockResponse(mock_json)

    monkeypatch.setattr("src.services.weather.requests.get", mock_get)

    client = OpenWeatherClient(api_key="valid_key", cache_ttl_seconds=300)

    res1 = client.fetch_forecast_0_6h(39.9, 32.8)
    res2 = client.fetch_forecast_0_6h(39.9, 32.8)

    assert call_count == 1
    assert len(res1) == len(res2)


def test_openweather_retry_logic_and_stale_cache_fallback(monkeypatch):
    call_count = 0

    def mock_get_failing(url, params, timeout):
        nonlocal call_count
        call_count += 1
        return MockResponse({}, status_code=500)

    monkeypatch.setattr("src.services.weather.requests.get", mock_get_failing)

    client = OpenWeatherClient(api_key="valid_key", max_retries=3, backoff_factor=0.01)

    # No cache yet -> throws WeatherSourceError
    with pytest.raises(WeatherSourceError, match="OpenWeather request failed"):
        client.fetch_forecast_0_6h(39.9, 32.8)

    assert call_count == 3

    # Seed stale cache and test fallback
    cache_key = client._cache_key(39.9, 32.8)
    stale_item = NormalizedWeather(
        latitude=39.9,
        longitude=32.8,
        temperature=25.0,
        humidity=40.0,
        wind_speed=5.0,
        wind_deg=180.0,
        forecast_offset_hours=0,
        forecast_time=datetime.now(timezone.utc).replace(tzinfo=None),
        fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    client._cache[cache_key] = (0.0, [stale_item])  # expired cache entry

    call_count = 0
    stale_res = client.fetch_forecast_0_6h(39.9, 32.8)
    assert call_count == 3
    assert len(stale_res) == 1
    assert stale_res[0].source == "OpenWeatherMap-Cache"


def test_sync_weather_for_clusters_persists_to_db(api, monkeypatch):
    now_ts = time.time()
    mock_json = build_mock_forecast_json(now_ts)

    def mock_get(url, params, timeout):
        return MockResponse(mock_json)

    monkeypatch.setattr("src.services.weather.requests.get", mock_get)

    database = api.state.database
    database.create_all()

    with database.session() as session:
        cluster = FireCluster(
            cluster_key="cluster_alpha",
            latitude=39.9,
            longitude=32.8,
            observation_count=3,
            max_frp=15.0,
            first_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
            last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        session.add(cluster)

    with database.session() as session:
        settings = api.state.settings
        client = OpenWeatherClient(api_key="mock_key")
        res = sync_weather_for_clusters(session, settings, client=client)

        assert res["clusters_processed"] == 1
        assert res["weather_points_saved"] == 3

        points = session.query(WeatherDataPoint).all()
        assert len(points) == 3
        assert points[0].cluster_key == "cluster_alpha"
        assert points[0].temperature == 28.5
        assert points[0].wind_speed == 5.4


def test_fastapi_weather_endpoints(client, monkeypatch):
    now_ts = time.time()
    mock_json = build_mock_forecast_json(now_ts)

    def mock_get(url, params, timeout):
        return MockResponse(mock_json)

    monkeypatch.setattr("src.services.weather.requests.get", mock_get)

    # Initial GET empty
    get_res = client.get("/api/v1/weather")
    assert get_res.status_code == 200
    assert get_res.json()["count"] == 0

    # Trigger sync with mock key set
    client.app.state.settings.OPENWEATHER_API_KEY = "mock_key"
    sync_res = client.post("/api/v1/weather/sync")
    assert sync_res.status_code == 200
    assert sync_res.json()["status"] == "ok"
