"""Frame and geodetic conversions with position and velocity support."""

from __future__ import annotations

from contextlib import ExitStack

import numpy as np
from astropy import units as u
from astropy.coordinates import (
    GCRS,
    ITRS,
    TEME,
    CartesianDifferential,
    CartesianRepresentation,
)
from astropy.time import Time
from astropy.utils import iers
from numpy.typing import ArrayLike, NDArray

from .constants import R_EARTH_EQUATOR, WGS84_FLATTENING
from .types import Ephemeris, OrbitState


def geodetic_to_ecef(
    latitude_rad: float, longitude_rad: float, altitude_m: float = 0.0
) -> NDArray[np.float64]:
    """Convert WGS-84 geodetic latitude/longitude/altitude to ITRS/ECEF."""

    e2 = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
    sin_lat = np.sin(latitude_rad)
    cos_lat = np.cos(latitude_rad)
    prime_vertical = R_EARTH_EQUATOR / np.sqrt(1.0 - e2 * sin_lat**2)
    return np.array(
        [
            (prime_vertical + altitude_m) * cos_lat * np.cos(longitude_rad),
            (prime_vertical + altitude_m) * cos_lat * np.sin(longitude_rad),
            (prime_vertical * (1.0 - e2) + altitude_m) * sin_lat,
        ]
    )


def ecef_to_geodetic(position_m: ArrayLike) -> tuple[float, float, float]:
    """Convert WGS-84 ECEF to geodetic latitude, longitude, altitude."""

    position = np.asarray(position_m, dtype=float)
    if position.shape != (3,):
        raise ValueError("position_m must have shape (3,)")
    x, y, z = position
    longitude = float(np.arctan2(y, x))
    horizontal = float(np.hypot(x, y))
    if horizontal < 1e-8:
        latitude = float(np.copysign(np.pi / 2.0, z))
        altitude = abs(float(z)) - R_EARTH_EQUATOR * (1.0 - WGS84_FLATTENING)
        return latitude, longitude, altitude
    e2 = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
    latitude = float(np.arctan2(z, horizontal * (1.0 - e2)))
    for _ in range(10):
        sin_lat = np.sin(latitude)
        prime_vertical = R_EARTH_EQUATOR / np.sqrt(1.0 - e2 * sin_lat**2)
        altitude = horizontal / max(np.cos(latitude), 1e-15) - prime_vertical
        updated = float(
            np.arctan2(z, horizontal * (1.0 - e2 * prime_vertical / (prime_vertical + altitude)))
        )
        if abs(updated - latitude) < 1e-13:
            latitude = updated
            break
        latitude = updated
    sin_lat = np.sin(latitude)
    prime_vertical = R_EARTH_EQUATOR / np.sqrt(1.0 - e2 * sin_lat**2)
    altitude = horizontal / np.cos(latitude) - prime_vertical
    return latitude, longitude, float(altitude)


def _frame_object(name: str, representation: CartesianRepresentation | None, time: Time):
    args = () if representation is None else (representation,)
    if name == "GCRS":
        return GCRS(*args, obstime=time)
    if name == "ITRS":
        return ITRS(*args, obstime=time)
    if name == "TEME":
        return TEME(*args, obstime=time)
    raise ValueError(f"Astropy conversion does not support frame {name!r}")


def transform_ephemeris(ephemeris: Ephemeris, target_frame: str) -> Ephemeris:
    """Transform a GCRS, ITRS, or TEME ephemeris using Astropy/ERFA.

    Astropy's bundled IERS table is used without network access.  For precision
    operations, update the IERS data in the runtime environment.
    """

    if target_frame == ephemeris.frame:
        return ephemeris
    if target_frame not in {"GCRS", "ITRS", "TEME"}:
        raise ValueError("target_frame must be GCRS, ITRS, or TEME")
    times = Time(list(ephemeris.times), scale="utc")
    representation = CartesianRepresentation(
        ephemeris.positions_m.T * u.m,
        differentials=CartesianDifferential(ephemeris.velocities_m_s.T * u.m / u.s),
    )
    source = _frame_object(ephemeris.frame, representation, times)
    target = _frame_object(target_frame, None, times)
    with ExitStack() as stack:
        stack.enter_context(iers.conf.set_temp("auto_download", False))
        stack.enter_context(iers.conf.set_temp("auto_max_age", None))
        converted = source.transform_to(target)
    positions = converted.cartesian.xyz.to_value(u.m).T
    velocities = converted.velocity.d_xyz.to_value(u.m / u.s).T
    return Ephemeris(ephemeris.times, positions, velocities, target_frame)


def _transform_state(state: OrbitState, target_frame: str) -> OrbitState:
    ephemeris = Ephemeris(
        (state.epoch,), state.position_m[None, :], state.velocity_m_s[None, :], state.frame
    )
    result = transform_ephemeris(ephemeris, target_frame)
    return result.state(0)


def eci_to_ecef(state: OrbitState) -> OrbitState:
    """Convert a GCRS state to ITRS/ECEF, including velocity transport terms."""

    if state.frame != "GCRS":
        raise ValueError("eci_to_ecef expects a GCRS state")
    return _transform_state(state, "ITRS")


def ecef_to_eci(state: OrbitState) -> OrbitState:
    """Convert an ITRS/ECEF state to GCRS, including velocity transport terms."""

    if state.frame != "ITRS":
        raise ValueError("ecef_to_eci expects an ITRS state")
    return _transform_state(state, "GCRS")
