"""Composable acceleration models for numerical orbit propagation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import CubicSpline

from ..constants import (
    J2_EARTH,
    MU_EARTH,
    MU_MOON,
    MU_SUN,
    OMEGA_EARTH,
    R_EARTH_EQUATOR,
    SOLAR_PRESSURE_1_AU,
)
from ..solar import (
    _body_positions_ephemeris,
    eclipse_fraction,
    moon_position_ephemeris,
    sun_position_ephemeris,
)


class ForceModel(Protocol):
    def acceleration(
        self, elapsed_s: float, state: NDArray[np.float64], epoch: datetime
    ) -> NDArray[np.float64]: ...


@dataclass
class BodyEphemerisCache:
    """Shared cubic ephemeris cache used during a numerical propagation."""

    sample_step_s: float = 900.0
    ephemeris: str = "builtin"
    _epoch: datetime | None = field(default=None, init=False, repr=False)
    _duration_s: float = field(default=0.0, init=False, repr=False)
    _splines: dict[str, CubicSpline] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not np.isfinite(self.sample_step_s) or self.sample_step_s <= 0.0:
            raise ValueError("sample_step_s must be a finite positive number")

    def prepare(self, body: str, epoch: datetime, duration_s: float) -> None:
        if self._epoch != epoch or duration_s > self._duration_s:
            self._epoch = epoch
            self._duration_s = float(duration_s)
            self._splines.clear()
        if body in self._splines:
            return
        seconds = np.arange(0.0, self._duration_s, self.sample_step_s)
        if len(seconds) == 0 or seconds[-1] != self._duration_s:
            seconds = np.append(seconds, self._duration_s)
        if len(seconds) == 1:
            seconds = np.array([0.0, max(1.0, self.sample_step_s)])
        times = tuple(epoch + timedelta(seconds=float(value)) for value in seconds)
        positions = _body_positions_ephemeris(body, times, self.ephemeris)
        self._splines[body] = CubicSpline(seconds, positions, axis=0)

    def position(self, body: str, elapsed_s: float, epoch: datetime) -> np.ndarray:
        spline = self._splines.get(body)
        if spline is not None and epoch == self._epoch:
            return np.asarray(spline(elapsed_s), dtype=float)
        if body == "sun":
            return sun_position_ephemeris(epoch + timedelta(seconds=float(elapsed_s)))
        return moon_position_ephemeris(epoch + timedelta(seconds=float(elapsed_s)))


@dataclass(frozen=True)
class PointMassGravity:
    mu_m3_s2: float = MU_EARTH

    def acceleration(self, elapsed_s: float, state: np.ndarray, epoch: datetime) -> np.ndarray:
        del elapsed_s, epoch
        position = state[:3]
        radius = np.linalg.norm(position)
        return -self.mu_m3_s2 * position / radius**3


@dataclass(frozen=True)
class J2Gravity:
    mu_m3_s2: float = MU_EARTH
    equatorial_radius_m: float = R_EARTH_EQUATOR
    j2: float = J2_EARTH

    def acceleration(self, elapsed_s: float, state: np.ndarray, epoch: datetime) -> np.ndarray:
        del elapsed_s, epoch
        x, y, z = state[:3]
        radius2 = x * x + y * y + z * z
        radius = np.sqrt(radius2)
        z_ratio2 = z * z / radius2
        factor = 1.5 * self.j2 * self.mu_m3_s2 * self.equatorial_radius_m**2 / radius**5
        return factor * np.array(
            [x * (5.0 * z_ratio2 - 1.0), y * (5.0 * z_ratio2 - 1.0), z * (5.0 * z_ratio2 - 3.0)]
        )


@dataclass(frozen=True)
class ThirdBodyGravity:
    body: str
    ephemeris_cache: BodyEphemerisCache | None = None

    def __post_init__(self) -> None:
        if self.body not in {"sun", "moon"}:
            raise ValueError("body must be 'sun' or 'moon'")

    def acceleration(self, elapsed_s: float, state: np.ndarray, epoch: datetime) -> np.ndarray:
        if self.ephemeris_cache is not None:
            body_position = self.ephemeris_cache.position(self.body, elapsed_s, epoch)
        else:
            at_time = epoch + timedelta(seconds=float(elapsed_s))
            body_position = (
                sun_position_ephemeris(at_time)
                if self.body == "sun"
                else moon_position_ephemeris(at_time)
            )
        mu = MU_SUN if self.body == "sun" else MU_MOON
        spacecraft_position = state[:3]
        relative = body_position - spacecraft_position
        return mu * (
            relative / np.linalg.norm(relative) ** 3
            - body_position / np.linalg.norm(body_position) ** 3
        )

    def prepare(self, epoch: datetime, duration_s: float) -> None:
        if self.ephemeris_cache is not None:
            self.ephemeris_cache.prepare(self.body, epoch, duration_s)


_ATMOSPHERE_HEIGHT_KM = np.array(
    [0, 25, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 180,
     200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000],
    dtype=float,
)
_ATMOSPHERE_DENSITY_KG_M3 = np.array(
    [1.225, 3.899e-2, 1.774e-2, 3.972e-3, 1.057e-3, 3.206e-4, 8.770e-5,
     1.905e-5, 3.396e-6, 5.297e-7, 9.661e-8, 2.438e-8, 8.484e-9, 3.845e-9,
     2.070e-9, 5.464e-10, 2.789e-10, 7.248e-11, 2.418e-11, 9.518e-12,
     3.725e-12, 1.585e-12, 6.967e-13, 1.454e-13, 3.614e-14, 1.170e-14,
     5.245e-15, 3.019e-15],
    dtype=float,
)
_ATMOSPHERE_SCALE_HEIGHT_KM = np.array(
    [7.249, 6.349, 6.682, 7.554, 8.382, 7.714, 6.549, 5.799, 5.382, 5.877,
     7.263, 9.473, 12.636, 16.149, 22.523, 29.740, 37.105, 45.546, 53.628,
     53.298, 58.515, 60.828, 63.822, 71.835, 88.667, 124.640, 181.050, 268.000],
    dtype=float,
)


def exponential_atmosphere_density(altitude_m: float) -> float:
    """Piecewise exponential reference atmosphere (engineering model)."""

    altitude_km = max(float(altitude_m) / 1000.0, 0.0)
    index = int(np.searchsorted(_ATMOSPHERE_HEIGHT_KM, altitude_km, side="right") - 1)
    index = int(np.clip(index, 0, len(_ATMOSPHERE_HEIGHT_KM) - 1))
    return float(
        _ATMOSPHERE_DENSITY_KG_M3[index]
        * np.exp(
            -(altitude_km - _ATMOSPHERE_HEIGHT_KM[index])
            / _ATMOSPHERE_SCALE_HEIGHT_KM[index]
        )
    )


@dataclass(frozen=True)
class ExponentialAtmosphericDrag:
    area_to_mass_m2_kg: float
    drag_coefficient: float = 2.2

    def acceleration(self, elapsed_s: float, state: np.ndarray, epoch: datetime) -> np.ndarray:
        del elapsed_s, epoch
        position = state[:3]
        velocity = state[3:]
        altitude = np.linalg.norm(position) - R_EARTH_EQUATOR
        density = exponential_atmosphere_density(altitude)
        atmosphere_velocity = np.cross(np.array([0.0, 0.0, OMEGA_EARTH]), position)
        relative_velocity = velocity - atmosphere_velocity
        speed = np.linalg.norm(relative_velocity)
        return (
            -0.5
            * self.drag_coefficient
            * self.area_to_mass_m2_kg
            * density
            * speed
            * relative_velocity
        )


@dataclass(frozen=True)
class SolarRadiationPressureForce:
    area_to_mass_m2_kg: float
    reflectivity_coefficient: float = 1.3
    ephemeris_cache: BodyEphemerisCache | None = None

    def acceleration(self, elapsed_s: float, state: np.ndarray, epoch: datetime) -> np.ndarray:
        if self.ephemeris_cache is not None:
            sun_position = self.ephemeris_cache.position("sun", elapsed_s, epoch)
        else:
            at_time = epoch + timedelta(seconds=float(elapsed_s))
            sun_position = sun_position_ephemeris(at_time)
        satellite_position = state[:3]
        sun_to_satellite = satellite_position - sun_position
        distance = np.linalg.norm(sun_to_satellite)
        illumination = eclipse_fraction(satellite_position, sun_position)
        from ..constants import ASTRONOMICAL_UNIT

        return (
            illumination
            * SOLAR_PRESSURE_1_AU
            * (ASTRONOMICAL_UNIT / distance) ** 2
            * self.reflectivity_coefficient
            * self.area_to_mass_m2_kg
            * sun_to_satellite
            / distance
        )

    def prepare(self, epoch: datetime, duration_s: float) -> None:
        if self.ephemeris_cache is not None:
            self.ephemeris_cache.prepare("sun", epoch, duration_s)


@dataclass(frozen=True)
class SchwarzschildCorrection:
    mu_m3_s2: float = MU_EARTH

    def acceleration(self, elapsed_s: float, state: np.ndarray, epoch: datetime) -> np.ndarray:
        del elapsed_s, epoch
        speed_of_light = 299_792_458.0
        position = state[:3]
        velocity = state[3:]
        radius = np.linalg.norm(position)
        speed2 = np.dot(velocity, velocity)
        return self.mu_m3_s2 / (speed_of_light**2 * radius**3) * (
            (4.0 * self.mu_m3_s2 / radius - speed2) * position
            + 4.0 * np.dot(position, velocity) * velocity
        )
