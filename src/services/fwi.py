"""Fire Weather Index (FWI) and drought indicator per pilot-region zone (EM-014).

Implements the canonical Canadian Forest Fire Weather Index System equations
(Van Wagner & Pickett, 1985; Van Wagner, 1987) from daily zone weather
(temperature, relative humidity, wind speed, 24-h rainfall). The pilot region
bounding box is divided into coarse analysis zones; each zone gets one FWI
profile per day with carry-over of the previous day's fuel-moisture codes.

The Drought Code (DC) doubles as the drought indicator and is classified with
the Lawson & Armitage (2008) break points. Risk categories follow the CFS
FWI classification (Very Low .. Extreme).
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterator
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.fwi import FireWeatherIndex
from src.models.weather import WeatherDataPoint
from src.services.grid_standard import PilotRegionGridService
from src.utils.timeutils import to_utc_iso, utc_now

# Standard starting values when no previous-day codes are known
# (Van Wagner & Pickett, 1985).
DEFAULT_FFMC = 85.0
DEFAULT_DMC = 6.0
DEFAULT_DC = 15.0

# FWI risk categories (Canadian Forest Service classification).
RISK_ORDER = ["very_low", "low", "moderate", "high", "very_high", "extreme"]
HIGH_RISK_CATEGORIES = ("high", "very_high", "extreme")
DROUGHT_ORDER = [
    "no_drought",
    "low",
    "moderate",
    "high",
    "very_high",
    "extreme",
]
DROUGHT_WATCH_CATEGORIES = ("high", "very_high", "extreme")

# Monthly effective day-length factors (Le) for the Duff Moisture Code and
# monthly seasonal adjustment (Lf) for the Drought Code, from the Canadian
# Forest Fire Danger Rating System weather guide (reference latitudes).
_DMC_DAY_LENGTH_40N = [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0]
_DMC_DAY_LENGTH_20N = [7.9, 8.4, 8.9, 9.5, 9.9, 10.2, 10.1, 9.7, 9.1, 8.6, 8.1, 7.8]
_DMC_DAY_LENGTH_20S = [10.1, 9.6, 9.1, 8.5, 8.1, 7.8, 7.9, 8.3, 8.9, 9.4, 9.9, 10.2]
_DMC_DAY_LENGTH_40S = [11.5, 10.5, 9.2, 7.9, 6.8, 6.2, 6.5, 7.4, 8.7, 10.0, 11.2, 11.8]
_DC_SEASONAL_40N = [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6]


class FwiError(RuntimeError):
    """Raised when FWI inputs are invalid or computation cannot proceed."""


@dataclass(frozen=True)
class FwiComponents:
    """One day's FWI system output for a zone."""

    ffmc: float
    dmc: float
    dc: float
    isi: float
    bui: float
    fwi: float

    @property
    def risk_category(self) -> str:
        """CFS FWI risk class for this day's Fire Weather Index."""
        return fwi_risk_category(self.fwi)

    @property
    def drought_category(self) -> str:
        """Drought-indicator class derived from the Drought Code."""
        return drought_category(self.dc)

    def as_dict(self) -> dict[str, Any]:
        """JSON-compatible representation of the components."""
        return {
            "ffmc": round(self.ffmc, 2),
            "dmc": round(self.dmc, 2),
            "dc": round(self.dc, 2),
            "isi": round(self.isi, 2),
            "bui": round(self.bui, 2),
            "fwi": round(self.fwi, 2),
            "risk_category": self.risk_category,
            "drought_category": self.drought_category,
        }


@dataclass(frozen=True)
class FwiZone:
    """Coarse FWI analysis zone inside the pilot region bounding box."""

    zone_key: str
    region_name: str
    center_lat: float
    center_lon: float
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


@dataclass(frozen=True)
class ZoneWeather:
    """Zone-averaged daily weather driving one FWI computation."""

    temperature: float
    humidity: float
    wind_speed: float
    rain_mm: float
    point_count: int


def fwi_risk_category(fwi: float) -> str:
    """Map a Fire Weather Index value onto the CFS risk class."""
    if fwi < 5.0:
        return "very_low"
    if fwi < 16.0:
        return "low"
    if fwi < 26.0:
        return "moderate"
    if fwi < 41.0:
        return "high"
    if fwi <= 50.0:
        return "very_high"
    return "extreme"


def drought_category(dc: float) -> str:
    """Map a Drought Code value onto a drought-indicator class."""
    if dc < 150.0:
        return "no_drought"
    if dc < 250.0:
        return "low"
    if dc < 300.0:
        return "moderate"
    if dc < 350.0:
        return "high"
    if dc < 400.0:
        return "very_high"
    return "extreme"


def _month_index(month: int) -> int:
    if not 1 <= month <= 12:
        raise FwiError(f"Invalid month {month}; expected 1..12")
    return month - 1


def _effective_day_length(latitude: float, month: int) -> float:
    """Monthly Le factor for the Duff Moisture Code by latitude band."""
    idx = _month_index(month)
    if latitude > 30.0:
        return _DMC_DAY_LENGTH_40N[idx]
    if latitude > 0.0:
        return _DMC_DAY_LENGTH_20N[idx]
    if latitude > -30.0:
        return _DMC_DAY_LENGTH_20S[idx]
    return _DMC_DAY_LENGTH_40S[idx]


def _dc_seasonal_adjustment(latitude: float, month: int) -> float:
    """Monthly Lf factor for the Drought Code (northern reference table)."""
    idx = _month_index(month)
    if latitude > 0.0:
        return _DC_SEASONAL_40N[idx]
    # Southern hemisphere shifts the same cycle by half a year.
    return _DC_SEASONAL_40N[(idx + 6) % 12]


def ffmc(temp: float, rh: float, wind: float, rain: float, prev_ffmc: float) -> float:
    """Fine Fuel Moisture Code: daily update of the 1-h dead fuel moisture."""
    mo = 147.2 * (101.0 - prev_ffmc) / (59.5 + prev_ffmc)

    if rain > 0.5:
        rf = rain - 0.5
        wet = mo + 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) * (
            1.0 - math.exp(-6.93 / rf)
        )
        if mo > 150.0:
            wet += 0.0015 * (mo - 150.0) ** 2 * math.sqrt(rf)
        mo = min(wet, 250.0)

    rh = min(max(rh, 1.0), 100.0)

    ed = (
        0.942 * rh**0.679
        + 11.0 * math.exp((rh - 100.0) / 10.0)
        + 0.18 * (21.1 - temp) * (1.0 - math.exp(-0.115 * rh))
    )

    if mo > ed:  # drying
        ko = 0.424 * (1.0 - (rh / 100.0) ** 1.7) + 0.0694 * math.sqrt(wind) * (
            1.0 - (rh / 100.0) ** 8
        )
        kd = ko * 0.581 * math.exp(0.0365 * temp)
        m = ed + (mo - ed) * 10.0 ** (-kd)
    else:  # wetting
        ew = (
            0.618 * rh**0.753
            + 10.0 * math.exp((rh - 100.0) / 10.0)
            + 0.18 * (21.1 - temp) * (1.0 - math.exp(-0.115 * rh))
        )
        if mo < ew:
            k1 = 0.424 * (1.0 - ((100.0 - rh) / 100.0) ** 1.7) + 0.0694 * math.sqrt(
                wind
            ) * (1.0 - ((100.0 - rh) / 100.0) ** 8)
            kw = k1 * 0.581 * math.exp(0.0365 * temp)
            m = ew - (ew - mo) * 10.0 ** (-kw)
        else:
            m = mo

    return 59.5 * (250.0 - m) / (147.2 + m)


def duff_moisture_code(
    temp: float, rh: float, rain: float, prev_dmc: float, latitude: float, month: int
) -> float:
    """Duff Moisture Code: moisture in the loosely compacted organic layer."""
    dmc_prev = prev_dmc

    if rain > 1.5:
        re = 0.92 * rain - 1.27
        mo = 20.0 + math.exp(5.6348 - dmc_prev / 43.43)

        if dmc_prev <= 33.0:
            b = 100.0 / (0.5 + 0.3 * dmc_prev)
        elif dmc_prev <= 65.0:
            b = 14.0 - 1.3 * math.log(dmc_prev)
        else:
            b = 6.2 * math.log(dmc_prev) - 17.2

        mr = mo + 1000.0 * re / (48.77 + b * re)
        pr = 244.72 - 43.43 * math.log(mr - 20.0)
        dmc_prev = max(pr, 0.0)

    t = max(temp, -1.1)
    le = _effective_day_length(latitude, month)
    k = 1.894 * (t + 1.1) * (100.0 - min(max(rh, 0.0), 100.0)) * le * 0.000001

    return dmc_prev + 100.0 * k


def drought_code(
    temp: float, rain: float, prev_dc: float, latitude: float, month: int
) -> float:
    """Drought Code: deep-layer moisture deficit; also the drought indicator."""
    dc_prev = prev_dc

    if rain > 2.8:
        rd = 0.83 * rain - 1.27
        qo = 800.0 * math.exp(-dc_prev / 400.0)
        qr = qo + 3.937 * rd
        dr = 400.0 * math.log(800.0 / qr) if qr > 0 else 0.0
        dc_prev = max(dr, 0.0)

    lf = _dc_seasonal_adjustment(latitude, month)
    v = max(0.36 * (max(temp, -2.8) + 2.8) + lf, 0.0)

    return dc_prev + 0.5 * v


def initial_spread_index(wind: float, day_ffmc: float) -> float:
    """Initial Spread Index: rate of spread in open grass-like fuels."""
    f_wind = math.exp(0.05039 * wind)
    m = 147.2 * (101.0 - day_ffmc) / (59.5 + day_ffmc)
    f_ffmc = 91.9 * math.exp(-0.1386 * m) * (1.0 + m**5.31 / 49300000.0)
    return 0.208 * f_wind * f_ffmc


def build_up_index(day_dmc: float, day_dc: float) -> float:
    """Build-Up Index: total fuel available for combustion."""
    if day_dmc <= 0.4 * day_dc:
        u = 0.8 * day_dmc * day_dc / (day_dmc + 0.4 * day_dc + 1e-12)
    else:
        u = day_dmc - (1.0 - (0.8 * day_dc) / (day_dmc + 0.4 * day_dc + 1e-12)) * (
            0.92 + (0.0114 * day_dmc) ** 1.7
        )
    return max(u, 0.0)


def fire_weather_index(isi: float, bui: float) -> float:
    """Fire Weather Index: combined daily fire behaviour potential."""
    if bui <= 80.0:
        f_d = 0.626 * bui**0.809 + 2.0
    else:
        f_d = 1000.0 / (25.0 + 108.64 * math.exp(-0.023 * bui))

    b = 0.1 * isi * f_d
    if b > 1.0:
        return math.exp(2.72 * (0.434 * math.log(b)) ** 0.647)
    return b


def compute_daily_fwi(
    latitude: float,
    month: int,
    temp: float,
    rh: float,
    wind: float,
    rain: float,
    prev_ffmc_value: float = DEFAULT_FFMC,
    prev_dmc_value: float = DEFAULT_DMC,
    prev_dc_value: float = DEFAULT_DC,
) -> FwiComponents:
    """Compute one full FWI day profile from zone-averaged weather."""
    day_ffmc = ffmc(temp, rh, wind, rain, prev_ffmc_value)
    day_dmc = duff_moisture_code(temp, rh, rain, prev_dmc_value, latitude, month)
    day_dc = drought_code(temp, rain, prev_dc_value, latitude, month)
    day_isi = initial_spread_index(wind, day_ffmc)
    day_bui = build_up_index(day_dmc, day_dc)
    day_fwi = fire_weather_index(day_isi, day_bui)
    return FwiComponents(
        ffmc=day_ffmc,
        dmc=day_dmc,
        dc=day_dc,
        isi=day_isi,
        bui=day_bui,
        fwi=day_fwi,
    )


def iter_fwizones(
    zone_size_deg: float, grid: PilotRegionGridService | None = None
) -> Iterator[FwiZone]:
    """Yield every FWI analysis zone covering the pilot region bbox."""
    if zone_size_deg <= 0:
        raise FwiError(f"FWI zone size must be positive, got {zone_size_deg}")
    grid = grid or PilotRegionGridService()

    rows = int(math.ceil((grid.max_lat - grid.min_lat) / zone_size_deg))
    cols = int(math.ceil((grid.max_lon - grid.min_lon) / zone_size_deg))

    for row in range(rows):
        for col in range(cols):
            min_lat = round(grid.min_lat + row * zone_size_deg, 5)
            max_lat = round(min(min_lat + zone_size_deg, grid.max_lat), 5)
            min_lon = round(grid.min_lon + col * zone_size_deg, 5)
            max_lon = round(min(min_lon + zone_size_deg, grid.max_lon), 5)
            yield FwiZone(
                zone_key=f"FWI_R{row}C{col}",
                region_name=f"Pilot Zone R{row}C{col}",
                center_lat=round((min_lat + max_lat) / 2.0, 5),
                center_lon=round((min_lon + max_lon) / 2.0, 5),
                min_lat=min_lat,
                min_lon=min_lon,
                max_lat=max_lat,
                max_lon=max_lon,
            )


def zone_for_point(
    lat: float,
    lon: float,
    zone_size_deg: float,
    grid: PilotRegionGridService | None = None,
) -> FwiZone | None:
    """Return the FWI zone containing a coordinate, or None if outside bbox."""
    grid = grid or PilotRegionGridService()
    if not grid.is_within_pilot_region(lat, lon):
        return None

    row = int((lat - grid.min_lat) // zone_size_deg)
    col = int((lon - grid.min_lon) // zone_size_deg)
    min_lat = round(grid.min_lat + row * zone_size_deg, 5)
    max_lat = round(min(min_lat + zone_size_deg, grid.max_lat), 5)
    min_lon = round(grid.min_lon + col * zone_size_deg, 5)
    max_lon = round(min(min_lon + zone_size_deg, grid.max_lon), 5)
    return FwiZone(
        zone_key=f"FWI_R{row}C{col}",
        region_name=f"Pilot Zone R{row}C{col}",
        center_lat=round((min_lat + max_lat) / 2.0, 5),
        center_lon=round((min_lon + max_lon) / 2.0, 5),
        min_lat=min_lat,
        min_lon=min_lon,
        max_lat=max_lat,
        max_lon=max_lon,
    )


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def aggregate_zone_weather(
    session: Session,
    day: date,
    zone_size_deg: float,
    grid: PilotRegionGridService | None = None,
) -> dict[str, tuple[FwiZone, ZoneWeather]]:
    """Bucket a day's weather data points into zones and average them.

    Rainfall is accumulated per forecast slot (mean across clusters inside the
    same zone and hour, summed across slots) so repeated cluster sampling does
    not double-count the same storm.
    """
    grid = grid or PilotRegionGridService()
    start, end = _day_bounds(day)
    points = session.scalars(
        select(WeatherDataPoint).where(
            WeatherDataPoint.forecast_time >= start,
            WeatherDataPoint.forecast_time < end,
        )
    ).all()

    buckets: dict[str, dict[str, Any]] = {}
    for point in points:
        zone = zone_for_point(
            float(point.latitude), float(point.longitude), zone_size_deg, grid
        )
        if zone is None:
            continue
        bucket = buckets.setdefault(
            zone.zone_key,
            {
                "zone": zone,
                "temps": [],
                "rhums": [],
                "winds": [],
                "rain_slots": {},
                "count": 0,
            },
        )
        bucket["temps"].append(float(point.temperature))
        bucket["rhums"].append(min(max(float(point.humidity), 0.0), 100.0))
        bucket["winds"].append(max(float(point.wind_speed), 0.0))
        slot = bucket["rain_slots"].setdefault(point.forecast_time, [])
        slot.append(max(float(getattr(point, "rain", 0.0) or 0.0), 0.0))
        bucket["count"] += 1

    result: dict[str, tuple[FwiZone, ZoneWeather]] = {}
    for key, bucket in buckets.items():
        rain_total = sum(
            sum(values) / len(values) for values in bucket["rain_slots"].values()
        )
        weather = ZoneWeather(
            temperature=sum(bucket["temps"]) / len(bucket["temps"]),
            humidity=sum(bucket["rhums"]) / len(bucket["rhums"]),
            wind_speed=sum(bucket["winds"]) / len(bucket["winds"]),
            rain_mm=round(rain_total, 2),
            point_count=bucket["count"],
        )
        result[key] = (bucket["zone"], weather)
    return result


def previous_day_codes(
    session: Session, zone_key: str, day: date
) -> tuple[float, float, float]:
    """Return the most recent stored FFMC/DMC/DC before ``day`` for a zone."""
    row = session.scalar(
        select(FireWeatherIndex)
        .where(
            FireWeatherIndex.zone_key == zone_key,
            FireWeatherIndex.day < day,
        )
        .order_by(FireWeatherIndex.day.desc())
        .limit(1)
    )
    if row is None:
        return DEFAULT_FFMC, DEFAULT_DMC, DEFAULT_DC
    return float(row.ffmc), float(row.dmc), float(row.dc)


def latest_fwi_day(session: Session) -> date | None:
    """Return the most recent day stored in the FWI layer, if any."""
    return session.scalar(select(func.max(FireWeatherIndex.day)))


def _resolve_day(session: Session, day: date | None) -> date | None:
    if day is not None:
        return day
    return latest_fwi_day(session)


def _num(value: float, digits: int = 2) -> Any:
    """Round a float; ``Any`` keeps SQLAlchemy Column assignment mypy-friendly."""
    return round(value, digits)


def compute_region_fwi(
    session: Session, settings: Any, day: date | None = None
) -> dict[str, Any]:
    """Compute and persist one day of zone FWI profiles for the pilot region.

    High-risk zones are those whose FWI falls in the ``high`` category or
    above; the previous day's codes are carried over per zone.
    """
    zone_size = float(getattr(settings, "FWI_ZONE_SIZE_DEG", 0.5))
    target_day = day or utc_now().date()
    grid = PilotRegionGridService()
    reference_lat = (grid.min_lat + grid.max_lat) / 2.0

    weather_by_zone = aggregate_zone_weather(session, target_day, zone_size, grid)

    existing = {
        str(row.zone_key): row
        for row in session.scalars(
            select(FireWeatherIndex).where(FireWeatherIndex.day == target_day)
        ).all()
    }

    computed = 0
    high_risk = 0
    max_fwi = 0.0
    for zone_key, (zone, weather) in sorted(weather_by_zone.items()):
        prev_ffmc_value, prev_dmc_value, prev_dc_value = previous_day_codes(
            session, zone_key, target_day
        )
        components = compute_daily_fwi(
            latitude=reference_lat,
            month=target_day.month,
            temp=weather.temperature,
            rh=weather.humidity,
            wind=weather.wind_speed,
            rain=weather.rain_mm,
            prev_ffmc_value=prev_ffmc_value,
            prev_dmc_value=prev_dmc_value,
            prev_dc_value=prev_dc_value,
        )
        row = existing.get(zone_key)
        if row is None:
            row = FireWeatherIndex(zone_key=zone_key, day=target_day)
            session.add(row)
        row.region_name = zone.region_name  # type: ignore[assignment]
        row.center_lat = zone.center_lat  # type: ignore[assignment]
        row.center_lon = zone.center_lon  # type: ignore[assignment]
        row.min_lat = zone.min_lat  # type: ignore[assignment]
        row.min_lon = zone.min_lon  # type: ignore[assignment]
        row.max_lat = zone.max_lat  # type: ignore[assignment]
        row.max_lon = zone.max_lon  # type: ignore[assignment]
        row.temperature = _num(weather.temperature)  # type: ignore[assignment]
        row.humidity = _num(weather.humidity, 1)  # type: ignore[assignment]
        row.wind_speed = _num(weather.wind_speed)  # type: ignore[assignment]
        row.rain = weather.rain_mm  # type: ignore[assignment]
        row.ffmc = _num(components.ffmc)  # type: ignore[assignment]
        row.dmc = _num(components.dmc)  # type: ignore[assignment]
        row.dc = _num(components.dc)  # type: ignore[assignment]
        row.isi = _num(components.isi)  # type: ignore[assignment]
        row.bui = _num(components.bui)  # type: ignore[assignment]
        row.fwi = _num(components.fwi)  # type: ignore[assignment]
        row.risk_category = components.risk_category  # type: ignore[assignment]
        row.drought_category = components.drought_category  # type: ignore[assignment]
        row.data_point_count = weather.point_count  # type: ignore[assignment]
        row.computed_at = utc_now()  # type: ignore[assignment]

        computed += 1
        max_fwi = max(max_fwi, components.fwi)
        if components.risk_category in HIGH_RISK_CATEGORIES:
            high_risk += 1

    session.flush()
    return {
        "day": target_day.isoformat(),
        "zones_computed": computed,
        "zones_skipped": sum(1 for _ in iter_fwizones(zone_size, grid)) - computed,
        "high_risk_zones": high_risk,
        "max_fwi": round(max_fwi, 2),
    }


def list_fwi_rows(
    session: Session, settings: Any, day: date | None = None
) -> tuple[date | None, list[FireWeatherIndex]]:
    """Return all zone profiles stored for one day (latest day by default)."""
    target_day = _resolve_day(session, day)
    if target_day is None:
        return None, []
    rows = session.scalars(
        select(FireWeatherIndex)
        .where(FireWeatherIndex.day == target_day)
        .order_by(FireWeatherIndex.fwi.desc())
    ).all()
    return target_day, list(rows)


RISK_COLORS = {
    "very_low": "#ffffff",
    "low": "#98eb18",
    "moderate": "#ffc616",
    "high": "#f98313",
    "very_high": "#d0111d",
    "extreme": "#77279d",
}


def fwi_map_layer(
    session: Session, settings: Any, day: date | None = None
) -> dict[str, Any]:
    """Render the zone FWI layer as GeoJSON polygons for the UI map."""
    target_day, rows = list_fwi_rows(session, settings, day)
    features: list[dict[str, Any]] = []
    for row in rows:
        polygon = [
            [row.min_lon, row.min_lat],
            [row.max_lon, row.min_lat],
            [row.max_lon, row.max_lat],
            [row.min_lon, row.max_lat],
            [row.min_lon, row.min_lat],
        ]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [polygon]},
                "properties": {
                    "zone_key": row.zone_key,
                    "region_name": row.region_name,
                    "day": row.day.isoformat(),
                    "fwi": row.fwi,
                    "risk_category": row.risk_category,
                    "color": RISK_COLORS.get(str(row.risk_category), "#cccccc"),
                    "isi": row.isi,
                    "bui": row.bui,
                    "ffmc": row.ffmc,
                    "dmc": row.dmc,
                    "dc": row.dc,
                    "drought_category": row.drought_category,
                    "temperature": row.temperature,
                    "humidity": row.humidity,
                    "wind_speed": row.wind_speed,
                    "rain": row.rain,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "layer": "fire_weather_index",
        "day": target_day.isoformat() if target_day else None,
        "count": len(features),
        "legend": dict(RISK_COLORS),
        "features": features,
    }


def daily_summary(
    session: Session, settings: Any, day: date | None = None
) -> dict[str, Any]:
    """Produce the analyst's daily FWI digest for high-risk preparation."""
    target_day, rows = list_fwi_rows(session, settings, day)
    high_risk = [
        row.as_dict for row in rows if row.risk_category in HIGH_RISK_CATEGORIES
    ]
    drought_watch = [
        {
            "zone_key": row.zone_key,
            "region_name": row.region_name,
            "dc": row.dc,
            "drought_category": row.drought_category,
            "fwi": row.fwi,
        }
        for row in rows
        if row.drought_category in DROUGHT_WATCH_CATEGORIES
    ]
    hottest = rows[0].as_dict if rows else None

    if high_risk:
        recommendation = (
            f"{len(high_risk)} zone(s) at high or greater fire weather risk: "
            "pre-position crews and equipment, restrict planned burns, and "
            "verify satellite/weather feed freshness."
        )
    else:
        recommendation = (
            "No zone reached the high FWI threshold; maintain routine "
            "monitoring readiness."
        )

    return {
        "day": target_day.isoformat() if target_day else None,
        "generated_at": to_utc_iso(utc_now()),
        "zones_total": len(rows),
        "zones_high_risk": len(high_risk),
        "max_fwi_zone": hottest,
        "high_risk_zones": high_risk,
        "drought_watch": drought_watch,
        "drought_order": DROUGHT_ORDER,
        "risk_order": RISK_ORDER,
        "recommendation": recommendation,
    }
