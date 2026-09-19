"""Unit conversions and meteorological formulas.

Pure functions only. No Earth Engine, no network. This is where every
conversion the climate engine relies on is written down and tested,
because a units error here produces numbers that look entirely plausible.

The conversions that matter most in practice:

* ERA5 stores temperature in Kelvin. Anything presented to a user must be
  in Celsius, and a forgotten subtraction yields a 300 degree reading.
* ERA5 stores precipitation and evaporation in metres. Field-scale
  reporting needs millimetres, a factor of 1000.
* ERA5 radiation is a daily accumulation in joules per square metre, while
  agronomy usually works in megajoules and in photosynthetically active
  radiation rather than total shortwave.
"""

from __future__ import annotations

import math
from typing import Optional

__all__ = [
    "ABSOLUTE_ZERO_CELSIUS",
    "kelvin_to_celsius",
    "celsius_to_kelvin",
    "metres_to_millimetres",
    "millimetres_to_metres",
    "joules_per_m2_to_megajoules",
    "megajoules_to_millimetres_water",
    "dewpoint_to_vapour_pressure",
    "saturation_vapour_pressure",
    "vapour_pressure_deficit",
    "relative_humidity_from_dewpoint",
    "wind_speed_from_components",
    "solar_radiation_to_par",
    "growing_degree_days",
    "accumulated_gdd",
]

#: 0 degrees Celsius in Kelvin, exact by definition.
ABSOLUTE_ZERO_CELSIUS = 273.15

#: Latent heat of vaporisation of water at roughly 20 degrees Celsius,
#: in megajoules per kilogram. Used to convert an energy flux to a water
#: depth equivalent.
LATENT_HEAT_OF_VAPORISATION_MJ_PER_KG = 2.45

#: Fraction of incoming shortwave radiation that falls in the
#: photosynthetically active waveband, 400 to 700 nm. Widely used as a
#: constant approximation.
PAR_FRACTION_OF_SHORTWAVE = 0.45


def _finite(value: Optional[float]) -> Optional[float]:
    """Return the value if it is a finite real number, else None."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def kelvin_to_celsius(kelvin: Optional[float]) -> Optional[float]:
    """Convert Kelvin to Celsius.

    Returns ``None`` for non-finite input rather than propagating a
    meaningless value.
    """
    value = _finite(kelvin)
    return None if value is None else value - ABSOLUTE_ZERO_CELSIUS


def celsius_to_kelvin(celsius: Optional[float]) -> Optional[float]:
    value = _finite(celsius)
    return None if value is None else value + ABSOLUTE_ZERO_CELSIUS


def metres_to_millimetres(metres: Optional[float]) -> Optional[float]:
    """Convert metres of water to millimetres.

    ERA5 reports both precipitation and evaporation in metres. Presenting
    that directly would understate rainfall by a factor of a thousand.
    """
    value = _finite(metres)
    return None if value is None else value * 1000.0


def millimetres_to_metres(millimetres: Optional[float]) -> Optional[float]:
    value = _finite(millimetres)
    return None if value is None else value / 1000.0


def joules_per_m2_to_megajoules(joules: Optional[float]) -> Optional[float]:
    """Convert joules per square metre to megajoules per square metre."""
    value = _finite(joules)
    return None if value is None else value / 1.0e6


def megajoules_to_millimetres_water(
    megajoules_per_m2: Optional[float],
) -> Optional[float]:
    """Convert an energy flux to an equivalent depth of evaporated water.

    Uses the latent heat of vaporisation. The result is the depth of water
    that the given energy could evaporate, in millimetres. This is an
    energy-equivalence conversion, not an observation of evaporation.
    """
    value = _finite(megajoules_per_m2)
    if value is None:
        return None
    # MJ/m2 divided by MJ/kg gives kg/m2, which is numerically equal to mm.
    return value / LATENT_HEAT_OF_VAPORISATION_MJ_PER_KG


# --------------------------------------------------------------------------
# Humidity and vapour pressure
# --------------------------------------------------------------------------


def saturation_vapour_pressure(
    temperature_c: Optional[float],
) -> Optional[float]:
    """Saturation vapour pressure in kilopascals.

    Uses the Magnus formula with coefficients for water, valid from about
    -40 to +50 degrees Celsius:

        es = 0.6108 * exp(17.27 * T / (T + 237.3))

    This is the form recommended by FAO-56 for agricultural use.
    """
    temperature = _finite(temperature_c)
    if temperature is None:
        return None
    return 0.6108 * math.exp(17.27 * temperature / (temperature + 237.3))


def dewpoint_to_vapour_pressure(
    dewpoint_c: Optional[float],
) -> Optional[float]:
    """Actual vapour pressure in kilopascals, from the dewpoint.

    Uses the same Magnus form as the saturation calculation, because at
    the dewpoint the air is saturated and the actual vapour pressure
    equals the saturation vapour pressure.
    """
    return saturation_vapour_pressure(dewpoint_c)


def vapour_pressure_deficit(
    temperature_c: Optional[float],
    dewpoint_c: Optional[float],
) -> Optional[float]:
    """Vapour pressure deficit in kilopascals.

    The difference between how much water vapour the air could hold at the
    current temperature and how much it actually holds. This is the
    quantity that drives transpiration, and it is a far better indicator
    of atmospheric water demand than relative humidity alone, because it
    does not rise as temperature falls.

    Returns ``None`` if either input is missing, since VPD cannot be
    estimated from one of the two.
    """
    es = saturation_vapour_pressure(temperature_c)
    ea = dewpoint_to_vapour_pressure(dewpoint_c)
    if es is None or ea is None:
        return None
    deficit = es - ea
    # Small negative values can arise from rounding in the source data.
    # A genuine negative VPD is not physically meaningful.
    if deficit < 0 and deficit > -0.05:
        return 0.0
    if deficit < 0:
        return None
    return deficit


def relative_humidity_from_dewpoint(
    temperature_c: Optional[float],
    dewpoint_c: Optional[float],
) -> Optional[float]:
    """Relative humidity as a percentage, from temperature and dewpoint.

    ERA5-Land does not publish relative humidity directly, so it must be
    derived. The result is clamped to the range 0 to 100, since values
    slightly outside that range occur through rounding in the source data
    and reporting 103 percent humidity would be nonsense.
    """
    es = saturation_vapour_pressure(temperature_c)
    ea = dewpoint_to_vapour_pressure(dewpoint_c)
    if es is None or ea is None:
        return None
    if es <= 0:
        return None
    humidity = 100.0 * ea / es
    if humidity < 0:
        humidity = 0.0
    elif humidity > 100.0:
        humidity = 100.0
    return humidity


# --------------------------------------------------------------------------
# Wind
# --------------------------------------------------------------------------


def wind_speed_from_components(
    u: Optional[float],
    v: Optional[float],
) -> Optional[float]:
    """Wind speed in metres per second from eastward and northward components.

    ERA5 provides wind as a vector pair. Speed is the magnitude of that
    vector. Direction is deliberately not returned here: it would need a
    meteorological convention choice, and a speed is what most
    agricultural uses require.
    """
    u_value = _finite(u)
    v_value = _finite(v)
    if u_value is None or v_value is None:
        return None
    return math.hypot(u_value, v_value)


# --------------------------------------------------------------------------
# Radiation
# --------------------------------------------------------------------------


def solar_radiation_to_par(
    shortwave_mj_per_m2: Optional[float],
) -> Optional[float]:
    """Estimate photosynthetically active radiation from shortwave radiation.

    PAR is approximated as 45 percent of incoming shortwave radiation. This
    is a fixed-coefficient approximation, not a measurement, and the
    fraction varies with cloud cover, atmospheric composition, solar
    elevation and surface albedo. Every metric built on this must report
    itself as a proxy.
    """
    value = _finite(shortwave_mj_per_m2)
    if value is None:
        return None
    return value * PAR_FRACTION_OF_SHORTWAVE


# --------------------------------------------------------------------------
# Growing degree days
# --------------------------------------------------------------------------


def growing_degree_days(
    t_min_c: Optional[float],
    t_max_c: Optional[float],
    base_temperature_c: float = 10.0,
    upper_temperature_c: Optional[float] = None,
) -> Optional[float]:
    """Growing degree days accumulated on a single day.

    Uses the simple averaging method, which is what the majority of
    published crop coefficient tables assume:

        GDD = ((Tmin + Tmax) / 2) - Tbase

    Two standard refinements are applied and both are reported in the
    provenance:

    * The daily value is clamped at zero. A day colder than the base
      temperature contributes nothing; it does not subtract from the
      season total.
    * When an upper threshold is supplied, both Tmin and Tmax are capped
      at it, which suppresses the spurious acceleration that hot days
      would otherwise produce.

    Returns ``None`` if either temperature is missing, because a GDD from
    one temperature would be a fabrication.
    """
    t_min = _finite(t_min_c)
    t_max = _finite(t_max_c)
    if t_min is None or t_max is None:
        return None
    if not math.isfinite(base_temperature_c):
        return None

    if upper_temperature_c is not None and math.isfinite(upper_temperature_c):
        t_min = min(t_min, upper_temperature_c)
        t_max = min(t_max, upper_temperature_c)

    # Guard against a swapped pair, which happens when a dataset reports
    # min and max in an unexpected order.
    if t_min > t_max:
        t_min, t_max = t_max, t_min

    mean_temperature = (t_min + t_max) / 2.0
    value = mean_temperature - base_temperature_c
    return value if value > 0 else 0.0


def accumulated_gdd(
    daily_values: list,
    base_temperature_c: float = 10.0,
) -> Optional[float]:
    """Sum a series of daily growing degree day values.

    Days that could not be computed are skipped rather than treated as
    zero, but the count of skipped days is what the caller needs in order
    to judge the total. This function returns ``None`` only when no day
    could be computed at all.

    Note that skipping unknown days biases the total low. Callers
    presenting an accumulated GDD should report how many days were
    missing; that is why the metric layer tracks it separately.
    """
    usable = [v for v in daily_values if v is not None]
    if not usable:
        return None
    total = 0.0
    for value in usable:
        numeric = _finite(value)
        if numeric is None:
            continue
        total += numeric
    return total
