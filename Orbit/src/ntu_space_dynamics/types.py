"""Validated value objects shared by orbit, attitude, and access modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .time import ensure_utc, ensure_utc_sequence, seconds_since

Frame = Literal["GCRS", "ITRS", "TEME", "MOD"]


def _vector3(value: ArrayLike, name: str) -> NDArray[np.float64]:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,):
        raise ValueError(f"{name} must have shape (3,), got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array.copy()


@dataclass(frozen=True)
class OrbitState:
    """Position/velocity state in SI units at an aware UTC epoch."""

    epoch: datetime
    position_m: ArrayLike
    velocity_m_s: ArrayLike
    frame: Frame = "GCRS"

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch", ensure_utc(self.epoch))
        object.__setattr__(self, "position_m", _vector3(self.position_m, "position_m"))
        object.__setattr__(self, "velocity_m_s", _vector3(self.velocity_m_s, "velocity_m_s"))
        if self.frame not in {"GCRS", "ITRS", "TEME", "MOD"}:
            raise ValueError(f"unsupported frame: {self.frame}")

    @property
    def vector(self) -> NDArray[np.float64]:
        return np.concatenate((self.position_m, self.velocity_m_s))


@dataclass(frozen=True)
class Ephemeris:
    """A sampled orbit with positions in m and velocities in m/s."""

    times: tuple[datetime, ...]
    positions_m: ArrayLike
    velocities_m_s: ArrayLike
    frame: Frame = "GCRS"

    def __post_init__(self) -> None:
        times = ensure_utc_sequence(self.times)
        positions = np.asarray(self.positions_m, dtype=float)
        velocities = np.asarray(self.velocities_m_s, dtype=float)
        expected = (len(times), 3)
        if positions.shape != expected or velocities.shape != expected:
            raise ValueError(
                f"positions and velocities must both have shape {expected}; "
                f"got {positions.shape} and {velocities.shape}"
            )
        if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(velocities)):
            raise ValueError("ephemeris values must be finite")
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "positions_m", positions.copy())
        object.__setattr__(self, "velocities_m_s", velocities.copy())
        if self.frame not in {"GCRS", "ITRS", "TEME", "MOD"}:
            raise ValueError(f"unsupported frame: {self.frame}")

    def __len__(self) -> int:
        return len(self.times)

    @property
    def epoch(self) -> datetime:
        return self.times[0]

    @property
    def elapsed_seconds(self) -> NDArray[np.float64]:
        return seconds_since(self.times, self.epoch)

    def state(self, index: int) -> OrbitState:
        return OrbitState(
            self.times[index], self.positions_m[index], self.velocities_m_s[index], self.frame
        )


@dataclass(frozen=True)
class ClassicalElements:
    """Osculating classical elements, with angles in radians and length in m.

    ``anomaly_rad`` is a true anomaly.  Circular/equatorial conventions are
    described in :func:`ntu_space_dynamics.rv_to_oe`.
    """

    semi_major_axis_m: float
    eccentricity: float
    inclination_rad: float
    raan_rad: float
    argument_of_periapsis_rad: float
    anomaly_rad: float
    epoch: datetime | None = None

    def __post_init__(self) -> None:
        numbers = np.asarray(
            [
                self.semi_major_axis_m,
                self.eccentricity,
                self.inclination_rad,
                self.raan_rad,
                self.argument_of_periapsis_rad,
                self.anomaly_rad,
            ],
            dtype=float,
        )
        if not np.all(np.isfinite(numbers)):
            raise ValueError("orbital elements must be finite")
        if self.semi_major_axis_m <= 0.0:
            raise ValueError("only positive semi-major axes are currently supported")
        if not 0.0 <= self.eccentricity < 1.0:
            raise ValueError("only elliptic elements with 0 <= eccentricity < 1 are supported")
        if not 0.0 <= self.inclination_rad <= np.pi:
            raise ValueError("inclination must lie in [0, pi]")
        if self.epoch is not None:
            object.__setattr__(self, "epoch", ensure_utc(self.epoch))

    @classmethod
    def from_degrees(
        cls,
        semi_major_axis_m: float,
        eccentricity: float,
        inclination_deg: float,
        raan_deg: float,
        argument_of_periapsis_deg: float,
        anomaly_deg: float,
        epoch: datetime | None = None,
    ) -> "ClassicalElements":
        return cls(
            semi_major_axis_m,
            eccentricity,
            np.deg2rad(inclination_deg),
            np.deg2rad(raan_deg),
            np.deg2rad(argument_of_periapsis_deg),
            np.deg2rad(anomaly_deg),
            epoch,
        )

    @property
    def angles_deg(self) -> NDArray[np.float64]:
        return np.rad2deg(
            [
                self.inclination_rad,
                self.raan_rad,
                self.argument_of_periapsis_rad,
                self.anomaly_rad,
            ]
        )


@dataclass(frozen=True)
class AttitudeEphemeris:
    """Body-to-inertial quaternions (SciPy xyzw convention) and body rates."""

    times_s: ArrayLike
    quaternions_xyzw: ArrayLike
    angular_velocity_body_rad_s: ArrayLike

    def __post_init__(self) -> None:
        times = np.asarray(self.times_s, dtype=float)
        quaternions = np.asarray(self.quaternions_xyzw, dtype=float)
        rates = np.asarray(self.angular_velocity_body_rad_s, dtype=float)
        if times.ndim != 1 or len(times) == 0:
            raise ValueError("times_s must be a non-empty one-dimensional array")
        if quaternions.shape != (len(times), 4) or rates.shape != (len(times), 3):
            raise ValueError("attitude arrays have incompatible shapes")
        object.__setattr__(self, "times_s", times.copy())
        object.__setattr__(self, "quaternions_xyzw", quaternions.copy())
        object.__setattr__(self, "angular_velocity_body_rad_s", rates.copy())

