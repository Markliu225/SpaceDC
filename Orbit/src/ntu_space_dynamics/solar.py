"""Solar geometry, eclipse, irradiance, beta angle, and SRP models."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime

import numpy as np
from astropy import units as u
from astropy.coordinates import (
    GCRS,
    PrecessedGeocentric,
    SkyCoord,
    get_body_barycentric,
)
from astropy.coordinates import CartesianRepresentation, solar_system_ephemeris
from astropy.time import Time
from astropy.utils import iers
from numpy.typing import ArrayLike, NDArray

from .constants import (
    ASTRONOMICAL_UNIT,
    R_EARTH_EQUATOR,
    R_SUN,
    SOLAR_CONSTANT,
    SOLAR_PRESSURE_1_AU,
)
from .time import ensure_utc, ensure_utc_sequence


def sun_position_analytical(
    epoch: datetime, *, frame: str = "GCRS"
) -> NDArray[np.float64]:
    """Analytical geocentric Sun vector in metres.

    The low-order model follows the mean-elements approach used by the supplied
    Python reference.  Its native frame is mean equator/equinox of date (``MOD``).
    ``frame='GCRS'`` applies Astropy's precession/frame transform so the result can
    be used with package orbit states.
    """

    epoch = ensure_utc(epoch)
    time = Time(epoch, scale="utc")
    centuries = (time.tt.jd - 2451545.0) / 36525.0
    eccentricity = 0.01670862 - 0.00004204 * centuries - 0.00000124 * centuries**2
    obliquity = np.deg2rad(
        23.439302 - 0.013004 * centuries - 0.16e-6 * centuries**2
    )
    perihelion = np.deg2rad(
        282.937347 + 1.719533 * centuries + 0.46e-6 * centuries**2
    )
    mean_longitude = np.deg2rad(
        280.466447 + 36000.769822 * centuries + 0.000304 * centuries**2
    )
    mean_anomaly = mean_longitude - perihelion
    true_anomaly = (
        mean_anomaly
        + eccentricity * (2.0 - 0.25 * eccentricity**2) * np.sin(mean_anomaly)
        + eccentricity**2
        * (1.25 - (11.0 / 24.0) * eccentricity**2)
        * np.sin(2.0 * mean_anomaly)
    )
    longitude = perihelion + true_anomaly
    semi_major_axis = 1.00000102 * ASTRONOMICAL_UNIT
    distance = semi_major_axis * (1.0 - eccentricity**2) / (
        1.0 + eccentricity * np.cos(true_anomaly)
    )
    mod_vector = distance * np.array(
        [
            np.cos(longitude),
            np.sin(longitude) * np.cos(obliquity),
            np.sin(longitude) * np.sin(obliquity),
        ]
    )
    if frame == "MOD":
        return mod_vector
    if frame != "GCRS":
        raise ValueError("frame must be 'MOD' or 'GCRS'")
    coordinate = SkyCoord(
        CartesianRepresentation(mod_vector * u.m),
        frame=PrecessedGeocentric(equinox=time, obstime=time),
    )
    with ExitStack() as stack:
        stack.enter_context(iers.conf.set_temp("auto_download", False))
        stack.enter_context(iers.conf.set_temp("auto_max_age", None))
        converted = coordinate.transform_to(GCRS(obstime=time))
    return converted.cartesian.xyz.to_value(u.m)


def _body_positions_ephemeris(
    body: str, epochs: tuple[datetime, ...], ephemeris: str = "builtin"
) -> NDArray[np.float64]:
    epochs = ensure_utc_sequence(epochs)
    time = Time(list(epochs), scale="utc")
    with ExitStack() as stack:
        stack.enter_context(iers.conf.set_temp("auto_download", False))
        stack.enter_context(iers.conf.set_temp("auto_max_age", None))
        stack.enter_context(solar_system_ephemeris.set(ephemeris))
        body_barycentric = get_body_barycentric(body, time)
        earth_barycentric = get_body_barycentric("earth", time)
        geometric = body_barycentric - earth_barycentric
    # GCRS is kinematically non-rotating with axes aligned to ICRS, so this
    # Earth-centred geometric vector is appropriate for force and eclipse models.
    return geometric.xyz.to_value(u.m).T


def _body_position_ephemeris(
    body: str, epoch: datetime, ephemeris: str = "builtin"
) -> NDArray[np.float64]:
    return _body_positions_ephemeris(body, (ensure_utc(epoch),), ephemeris)[0]


def sun_position_ephemeris(
    epoch: datetime, *, ephemeris: str = "builtin"
) -> NDArray[np.float64]:
    """Astropy geometric Earth-to-Sun vector on GCRS-aligned axes, in metres.

    ``ephemeris='builtin'`` is offline and deterministic.  A local JPL kernel
    path or a configured JPL ephemeris name can be supplied for mission work.
    """

    return _body_position_ephemeris("sun", epoch, ephemeris)


def moon_position_ephemeris(
    epoch: datetime, *, ephemeris: str = "builtin"
) -> NDArray[np.float64]:
    return _body_position_ephemeris("moon", epoch, ephemeris)


def sun_beta_angle(
    position_m: ArrayLike,
    velocity_m_s: ArrayLike,
    sun_position_m: ArrayLike,
    *,
    degrees: bool = False,
) -> float:
    """Signed angle of the Sun above the orbital plane."""

    normal = np.cross(np.asarray(position_m, dtype=float), np.asarray(velocity_m_s, dtype=float))
    sun = np.asarray(sun_position_m, dtype=float)
    if normal.shape != (3,) or sun.shape != (3,):
        raise ValueError("all vectors must have shape (3,)")
    value = float(
        np.arcsin(np.clip(np.dot(normal, sun) / (np.linalg.norm(normal) * np.linalg.norm(sun)), -1.0, 1.0))
    )
    return float(np.rad2deg(value)) if degrees else value


def _circle_overlap_area(radius1: float, radius2: float, separation: float) -> float:
    if separation == 0.0:
        return float(np.pi * min(radius1, radius2) ** 2)
    first = np.clip(
        (separation**2 + radius1**2 - radius2**2) / (2.0 * separation * radius1),
        -1.0,
        1.0,
    )
    second = np.clip(
        (separation**2 + radius2**2 - radius1**2) / (2.0 * separation * radius2),
        -1.0,
        1.0,
    )
    radical = max(
        0.0,
        (-separation + radius1 + radius2)
        * (separation + radius1 - radius2)
        * (separation - radius1 + radius2)
        * (separation + radius1 + radius2),
    )
    return float(
        radius1**2 * np.arccos(first)
        + radius2**2 * np.arccos(second)
        - 0.5 * np.sqrt(radical)
    )


def eclipse_fraction(
    satellite_position_m: ArrayLike,
    sun_position_m: ArrayLike,
    *,
    earth_radius_m: float = R_EARTH_EQUATOR,
    sun_radius_m: float = R_SUN,
) -> float:
    """Visible fraction of the solar disc using conical umbra/penumbra geometry."""

    satellite = np.asarray(satellite_position_m, dtype=float)
    sun = np.asarray(sun_position_m, dtype=float)
    if satellite.shape != (3,) or sun.shape != (3,):
        raise ValueError("satellite_position_m and sun_position_m must have shape (3,)")
    satellite_to_sun = sun - satellite
    satellite_to_earth = -satellite
    sun_distance = np.linalg.norm(satellite_to_sun)
    earth_distance = np.linalg.norm(satellite_to_earth)
    if earth_distance <= earth_radius_m:
        raise ValueError("satellite must lie outside the Earth")
    sun_angle = float(np.arcsin(np.clip(sun_radius_m / sun_distance, 0.0, 1.0)))
    earth_angle = float(np.arcsin(np.clip(earth_radius_m / earth_distance, 0.0, 1.0)))
    separation = float(
        np.arccos(
            np.clip(
                np.dot(satellite_to_sun, satellite_to_earth)
                / (sun_distance * earth_distance),
                -1.0,
                1.0,
            )
        )
    )
    if separation >= sun_angle + earth_angle:
        return 1.0
    if earth_angle >= separation + sun_angle:
        return 0.0
    if sun_angle >= separation + earth_angle:
        return float(1.0 - (earth_angle / sun_angle) ** 2)
    overlap = _circle_overlap_area(sun_angle, earth_angle, separation)
    return float(np.clip(1.0 - overlap / (np.pi * sun_angle**2), 0.0, 1.0))


def sun_intensity(
    satellite_position_m: ArrayLike,
    sun_position_m: ArrayLike,
    *,
    include_eclipse: bool = True,
) -> float:
    """Direct solar irradiance at the spacecraft in W/m^2."""

    satellite = np.asarray(satellite_position_m, dtype=float)
    sun = np.asarray(sun_position_m, dtype=float)
    distance = np.linalg.norm(sun - satellite)
    illumination = eclipse_fraction(satellite, sun) if include_eclipse else 1.0
    return float(illumination * SOLAR_CONSTANT * (ASTRONOMICAL_UNIT / distance) ** 2)


def sun_radiation_pressure(
    satellite_position_m: ArrayLike,
    sun_position_m: ArrayLike,
    *,
    area_to_mass_m2_kg: float,
    reflectivity_coefficient: float = 1.3,
    include_eclipse: bool = True,
) -> NDArray[np.float64]:
    """Cannonball solar-radiation-pressure acceleration in m/s^2."""

    if area_to_mass_m2_kg < 0.0:
        raise ValueError("area_to_mass_m2_kg must be non-negative")
    satellite = np.asarray(satellite_position_m, dtype=float)
    sun = np.asarray(sun_position_m, dtype=float)
    direction = satellite - sun
    distance = np.linalg.norm(direction)
    illumination = eclipse_fraction(satellite, sun) if include_eclipse else 1.0
    return (
        illumination
        * SOLAR_PRESSURE_1_AU
        * (ASTRONOMICAL_UNIT / distance) ** 2
        * reflectivity_coefficient
        * area_to_mass_m2_kg
        * direction
        / distance
    )
