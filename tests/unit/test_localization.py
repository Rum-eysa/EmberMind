"""Unit tests for EM-063 cross-border display standardization.

Covers the pure presentation helpers (UTC -> local time, wind bearing ->
compass, coordinate -> decimal/DMS, metric measures, the standardize bundle)
and the two endpoints wired into the FastAPI app.
"""
import pytest

from src.services.localization import (
    LocalizationError,
    format_coordinates,
    format_metric,
    format_wind_direction,
    resolve_zone,
    standardize,
    to_local_time,
)

# A fixed UTC summer instant: Turkey is UTC+3, so local time is 15:00.
_UTC_NOON = "2026-07-01T12:00:00Z"


# --------------------------------------------------------------- time zone --


def test_to_local_time_istanbul_is_utc_plus_three():
    result = to_local_time(_UTC_NOON, "Europe/Istanbul")
    assert result["local_iso"] == "2026-07-01T15:00:00+03:00"
    assert result["utc_offset"] == "+0300"
    assert result["timezone"] == "Europe/Istanbul"
    assert result["utc"] == _UTC_NOON


def test_to_local_time_accepts_trailing_z_and_naive():
    assert (
        to_local_time("2026-07-01T12:00:00", "Europe/Athens")["local_iso"]
        == "2026-07-01T15:00:00+03:00"
    )
    assert to_local_time(_UTC_NOON, "UTC")["local_iso"] == "2026-07-01T12:00:00+00:00"


def test_resolve_zone_rejects_unknown_and_bad_timestamp():
    with pytest.raises(LocalizationError):
        resolve_zone("Mars/Olympus")
    with pytest.raises(LocalizationError):
        to_local_time("not-a-date", "Europe/Istanbul")


# ------------------------------------------------------------------- wind --


@pytest.mark.parametrize(
    "degrees,compass",
    [(0, "N"), (90, "E"), (45, "NE"), (180, "S"), (360, "N"), (225, "SW")],
)
def test_format_wind_direction_labels(degrees, compass):
    assert format_wind_direction(degrees)["compass"] == compass


def test_format_wind_direction_none_and_modulo():
    assert format_wind_direction(None) == {
        "degrees": None,
        "compass": None,
        "compass_full": None,
    }
    assert format_wind_direction(450)["compass"] == "E"  # 450 % 360 == 90 -> East
    assert format_wind_direction(-90)["degrees"] == 270.0


# ------------------------------------------------------------ coordinates --


def test_format_coordinates_decimal_and_dms():
    result = format_coordinates(38.42, 27.14, "decimal")
    assert result["format"] == "decimal"
    assert result["display"] == "38.420000, 27.140000"
    assert result["dms"]["latitude"].startswith("38\u00b025'")
    assert result["dms"]["latitude"].endswith("N")
    assert result["dms"]["longitude"].endswith("E")


def test_format_coordinates_dms_display_and_southern():
    result = format_coordinates(-33.86, -70.66, "dms")
    assert result["format"] == "dms"
    assert result["dms"]["latitude"].endswith("S")
    assert result["dms"]["longitude"].endswith("W")
    assert result["display"] == result["dms"]["string"]


def test_format_coordinates_validation():
    with pytest.raises(LocalizationError):
        format_coordinates(95.0, 10.0)  # latitude out of range
    with pytest.raises(LocalizationError):
        format_coordinates(10.0, 200.0)  # longitude out of range
    with pytest.raises(LocalizationError):
        format_coordinates(None, 10.0)  # missing pair
    with pytest.raises(LocalizationError):
        format_coordinates(10.0, 10.0, "mgrs")  # unknown format


# ------------------------------------------------------------------ metric --


def test_format_metric_units():
    assert format_metric(5.5555, "km") == {
        "value": 5.556,
        "unit": "km",
        "display": "5.556 km",
    }
    assert format_metric(None, "ha")["display"] == "\u2014"


# -------------------------------------------------------------- the bundle --


def test_standardize_composes_all_blocks():
    payload = {
        "time": _UTC_NOON,
        "timezone": "Europe/Istanbul",
        "latitude": 38.42,
        "longitude": 27.14,
        "coordinate_format": "dms",
        "wind_direction_deg": 90,
        "distance_km": 12.0,
    }
    result = standardize(payload)
    assert result["persistence"] == "none"
    assert result["units"]["system"] == "metric"
    assert result["time"]["local_iso"] == "2026-07-01T15:00:00+03:00"
    assert result["coordinate"]["format"] == "dms"
    assert result["wind"]["compass"] == "E"
    assert result["measures"]["distance_km"]["unit"] == "km"


def test_standardize_only_requested_blocks():
    result = standardize({"timezone": "UTC"})
    assert "time" not in result
    assert "coordinate" not in result
    assert result["requested_timezone"] == "UTC"


# ------------------------------------------------------------- endpoints --


def test_display_config_endpoint(client):
    response = client.get("/api/v1/display/config")
    assert response.status_code == 200
    body = response.json()
    assert body["units"]["system"] == "metric"
    assert "Europe/Istanbul" in body["supported_timezones"]
    assert "decimal" in body["coordinate_formats"]
    assert body["persistence"] == "none"


def test_display_standardize_endpoint(client):
    response = client.post(
        "/api/v1/display/standardize",
        json={
            "time": _UTC_NOON,
            "timezone": "Europe/Istanbul",
            "latitude": 38.42,
            "longitude": 27.14,
            "coordinate_format": "dms",
            "wind_direction_deg": 90,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["time"]["local_iso"] == "2026-07-01T15:00:00+03:00"
    assert body["coordinate"]["format"] == "dms"
    assert body["wind"]["compass"] == "E"


def test_display_standardize_endpoint_rejects_bad_zone(client):
    response = client.post(
        "/api/v1/display/standardize",
        json={"time": _UTC_NOON, "timezone": "Mars/Olympus"},
    )
    assert response.status_code == 422
    assert "time zone" in response.json()["detail"]["error"]
