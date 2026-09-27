"""Dead fuel moisture classes derived from air temperature and humidity (EM-019).

Simple, deterministic model for the 1-hour / 10-hour / 100-hour dead fuel
time-lag classes used by the Rothermel spread engine (EM-015):

1. Equilibrium moisture content (EMC) of the current air follows Van
   Wagner's drying curve (Rothermel et al., 1986, Res. Pap. INT-359, eq 2a)
   — the same curve the FFMC code of the FWI service (EM-014) is built on.
2. The supplied observation is treated as the afternoon fire-weather hour
   (15:00 local: temperature maximum, relative humidity minimum). A
   standard sinusoidal diurnal cycle with configurable amplitudes is built
   around it, and each time-lag class relaxes towards the hourly EMC with
   the exponential response ``M <- M + (EMC - M) * (1 - exp(-1/tau))``,
   ``tau`` in {1, 10, 100} hours, over a conditioning window (default 48 h
   = two full cycles, which makes the result independent of the starting
   value for the fast classes and realistically lagged for the slow ones).
   Every class starts from the cycle's daily-mean EMC.
3. The three class values are load-weighted into the single effective dead
   fuel moisture consumed by the spread engine (see
   ``spread.effective_dead_fuel_moisture``).

With flat forcing (zero amplitudes) every class converges to the same EMC,
reproducing the pre-EM-019 behaviour. Under a diurnal cycle the coarse
classes stay wetter than the 1-hour class in the afternoon, which lowers
spread rates towards realistic values in deep-slash fuel models.

References:
 - Rothermel, R.C., Deeming, J.E., Everingham, W.A., 1986. Modeling
   moisture content of fine dead wildland fuels: Response to temperature
   and relative humidity. Res. Pap. INT-359, USDA Forest Service.
 - Van Wagner, C.E., 1987. The development and structure of the Canadian
   Forest Fire Danger Rating System. Forestry Chron. 63:138-145.
"""
from math import cos, exp, pi
from typing import Any

# Dead fuel time-lag classes (hours) traditionally used for fire behavior
# calculations: 1-h twigs/needles, 10-h sticks 1/4-1 in, 100-h logs 1-3 in.
TIME_LAG_HOURS: tuple[float, float, float] = (1.0, 10.0, 100.0)

# The driving observation represents this local hour (afternoon minimum RH,
# the standard fire-weather reading time, cf. Rothermel et al. 1986).
OBSERVED_HOUR_OF_DAY = 15

# Model label recorded in input provenance and API responses.
MODEL_NAME = "dead_fuel_moisture_v1"

# Default diurnal amplitudes for the synthetic conditioning cycle:
# temperature swings down by this much overnight, humidity rises by it.
DEFAULT_TEMP_AMPLITUDE_C = 8.0
DEFAULT_RH_AMPLITUDE_PCT = 25.0
DEFAULT_CONDITIONING_HOURS = 48


class FuelMoistureError(RuntimeError):
    """Raised when fuel moisture inputs are invalid."""


def equilibrium_moisture_content(air_temp_c: float, rel_humidity_pct: float) -> float:
    """1-hour dead fuel equilibrium moisture content [%] (Van Wagner curves).

    Rothermel et al. 1986 (INT-359) eq 2a: the drying equilibrium curve,
    used as the instantaneous equilibrium value for afternoon fire-danger
    weather. Reference anchors (T = 21.1 degC): RH 10% -> 4.50%,
    RH 20% -> 7.21%, RH 40% -> 11.56%.
    """
    rh = min(max(rel_humidity_pct, 1.0), 100.0)
    emc_dry = (
        0.942 * rh**0.679
        + 11.0 * exp((rh - 100.0) / 10.0)
        + 0.18 * (21.1 - air_temp_c) * (1.0 - exp(-0.115 * rh))
    )
    return max(emc_dry, 0.0)


def _diurnal_phase(hour_of_day: int) -> float:
    """0 at the observed afternoon hour, 1 at the opposite (pre-dawn) hour."""
    angle = 2.0 * pi * (hour_of_day - OBSERVED_HOUR_OF_DAY) / 24.0
    return (1.0 - cos(angle)) / 2.0


def _hourly_emc(
    air_temp_c: float,
    rel_humidity_pct: float,
    hour_of_day: int,
    temp_amplitude_c: float,
    rh_amplitude_pct: float,
) -> float:
    """EMC of one hour of the synthetic diurnal cycle around the observation."""
    phase = _diurnal_phase(hour_of_day)
    temp = air_temp_c - temp_amplitude_c * phase
    rh = min(max(rel_humidity_pct + rh_amplitude_pct * phase, 1.0), 100.0)
    return equilibrium_moisture_content(temp, rh)


def dead_fuel_moisture(
    air_temp_c: float,
    rel_humidity_pct: float,
    temp_amplitude_c: float = DEFAULT_TEMP_AMPLITUDE_C,
    rh_amplitude_pct: float = DEFAULT_RH_AMPLITUDE_PCT,
    conditioning_hours: int = DEFAULT_CONDITIONING_HOURS,
) -> dict[str, Any]:
    """1h/10h/100h dead fuel moisture [%] from current temperature and RH.

    Deterministic: identical inputs and amplitudes always produce identical
    class values (no wall-clock or database state involved).
    """
    if not -60.0 <= air_temp_c <= 60.0:
        raise FuelMoistureError(f"air temperature out of range: {air_temp_c}")
    if not 0.0 <= rel_humidity_pct <= 100.0:
        raise FuelMoistureError(f"relative humidity out of range: {rel_humidity_pct}")
    if temp_amplitude_c < 0 or rh_amplitude_pct < 0:
        raise FuelMoistureError("diurnal amplitudes must be >= 0")
    if conditioning_hours < 1:
        raise FuelMoistureError("conditioning window must span >= 1 hour")

    cycle_emc = [
        _hourly_emc(
            air_temp_c, rel_humidity_pct, hour, temp_amplitude_c, rh_amplitude_pct
        )
        for hour in range(24)
    ]
    # Start every class at the cycle's daily-mean EMC (neutral initial state).
    moisture = {tau: sum(cycle_emc) / 24.0 for tau in TIME_LAG_HOURS}

    for step in range(1, conditioning_hours + 1):
        hour_of_day = (OBSERVED_HOUR_OF_DAY - conditioning_hours + step) % 24
        emc = cycle_emc[hour_of_day]
        for tau in TIME_LAG_HOURS:
            response = 1.0 - exp(-1.0 / tau)
            moisture[tau] += (emc - moisture[tau]) * response

    return {
        "model": MODEL_NAME,
        "air_temp_c": round(air_temp_c, 2),
        "relative_humidity_pct": round(rel_humidity_pct, 2),
        "observed_emc_pct": round(
            equilibrium_moisture_content(air_temp_c, rel_humidity_pct), 2
        ),
        "moisture_1h_pct": round(moisture[1.0], 2),
        "moisture_10h_pct": round(moisture[10.0], 2),
        "moisture_100h_pct": round(moisture[100.0], 2),
        "temp_amplitude_c": temp_amplitude_c,
        "rh_amplitude_pct": rh_amplitude_pct,
        "conditioning_hours": conditioning_hours,
    }
