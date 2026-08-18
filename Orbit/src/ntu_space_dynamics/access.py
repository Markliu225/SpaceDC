"""Ground-target access by propagated samples and Hermite interpolation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.interpolate import CubicHermiteSpline
from scipy.optimize import brentq

from .coordinates import ecef_to_eci, eci_to_ecef, geodetic_to_ecef, transform_ephemeris
from .time import ensure_utc, time_grid
from .types import Ephemeris, OrbitState


@dataclass(frozen=True)
class GroundTarget:
    latitude_rad: float
    longitude_rad: float
    altitude_m: float = 0.0
    name: str = "target"

    def __post_init__(self) -> None:
        if not -np.pi / 2.0 <= self.latitude_rad <= np.pi / 2.0:
            raise ValueError("latitude must lie in [-pi/2, pi/2]")
        if not np.isfinite(self.longitude_rad) or not np.isfinite(self.altitude_m):
            raise ValueError("target coordinates must be finite")

    @classmethod
    def from_degrees(
        cls, latitude_deg: float, longitude_deg: float, altitude_m: float = 0.0, name: str = "target"
    ) -> "GroundTarget":
        return cls(np.deg2rad(latitude_deg), np.deg2rad(longitude_deg), altitude_m, name)

    @property
    def ecef_position_m(self) -> NDArray[np.float64]:
        return geodetic_to_ecef(self.latitude_rad, self.longitude_rad, self.altitude_m)


@dataclass(frozen=True)
class NadirSensor:
    """Fixed boresight in the supplied reference code's VVLH convention.

    VVLH +Z is nadir, +Y is orbit normal, and +X completes the right-handed
    frame (approximately anti-velocity for a circular prograde orbit).  Pitch
    is applied about +Y, then roll about +X.
    """

    half_angle_rad: float
    pitch_rad: float = 0.0
    roll_rad: float = 0.0
    minimum_elevation_rad: float = 0.0
    maximum_range_m: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 < self.half_angle_rad <= np.pi:
            raise ValueError("half_angle_rad must lie in (0, pi]")
        if not -np.pi / 2.0 <= self.minimum_elevation_rad <= np.pi / 2.0:
            raise ValueError("minimum_elevation_rad must lie in [-pi/2, pi/2]")
        if self.maximum_range_m is not None and self.maximum_range_m <= 0.0:
            raise ValueError("maximum_range_m must be positive")

    @classmethod
    def from_degrees(
        cls,
        half_angle_deg: float,
        *,
        pitch_deg: float = 0.0,
        roll_deg: float = 0.0,
        minimum_elevation_deg: float = 0.0,
        maximum_range_m: float | None = None,
    ) -> "NadirSensor":
        return cls(
            np.deg2rad(half_angle_deg),
            np.deg2rad(pitch_deg),
            np.deg2rad(roll_deg),
            np.deg2rad(minimum_elevation_deg),
            maximum_range_m,
        )

    @property
    def boresight_vvlh(self) -> NDArray[np.float64]:
        cp, sp = np.cos(self.pitch_rad), np.sin(self.pitch_rad)
        cr, sr = np.cos(self.roll_rad), np.sin(self.roll_rad)
        rotation_y = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
        rotation_x = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]])
        return rotation_x @ rotation_y @ np.array([0.0, 0.0, 1.0])


@dataclass(frozen=True)
class AccessWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = ensure_utc(self.start)
        end = ensure_utc(self.end)
        if end < start:
            raise ValueError("access window end precedes start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass(frozen=True)
class AccessResult:
    target: GroundTarget
    windows: tuple[AccessWindow, ...]
    sample_times: tuple[datetime, ...]
    combined_margin_rad: NDArray[np.float64]
    elevation_rad: NDArray[np.float64]
    off_boresight_rad: NDArray[np.float64]
    slant_range_m: NDArray[np.float64]


class OrbitPropagator(Protocol):
    def propagate(self, initial_state: OrbitState, times: tuple[datetime, ...]) -> Ephemeris: ...


class EphemerisInterpolator:
    """Cubic Hermite interpolation constrained by sampled position and velocity."""

    def __init__(self, ephemeris: Ephemeris) -> None:
        if ephemeris.frame != "GCRS":
            raise ValueError("access interpolation requires a GCRS ephemeris")
        if len(ephemeris) < 2:
            raise ValueError("at least two ephemeris samples are required")
        self.ephemeris = ephemeris
        self.epoch = ephemeris.times[0]
        self.seconds = ephemeris.elapsed_seconds
        if np.any(np.diff(self.seconds) <= 0.0):
            raise ValueError("ephemeris times must be strictly increasing")
        self._spline = CubicHermiteSpline(
            self.seconds, ephemeris.positions_m, ephemeris.velocities_m_s, axis=0
        )

    def evaluate_seconds(self, elapsed_s: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
        values = np.asarray(elapsed_s, dtype=float)
        if np.any(values < self.seconds[0]) or np.any(values > self.seconds[-1]):
            raise ValueError("interpolation time lies outside the ephemeris")
        return np.asarray(self._spline(values)), np.asarray(self._spline(values, 1))

    def state_at_seconds(self, elapsed_s: float) -> OrbitState:
        position, velocity = self.evaluate_seconds(float(elapsed_s))
        return OrbitState(
            self.epoch + timedelta(seconds=float(elapsed_s)), position, velocity, "GCRS"
        )


def _dense_ephemeris(interpolator: EphemerisInterpolator, scan_step_s: float) -> Ephemeris:
    if scan_step_s <= 0.0:
        raise ValueError("scan_step_s must be positive")
    stop = interpolator.seconds[-1]
    seconds = np.arange(0.0, stop, scan_step_s)
    if len(seconds) == 0 or seconds[-1] != stop:
        seconds = np.append(seconds, stop)
    positions, velocities = interpolator.evaluate_seconds(seconds)
    times = tuple(interpolator.epoch + timedelta(seconds=float(value)) for value in seconds)
    return Ephemeris(times, positions, velocities, "GCRS")


def _sample_metrics(
    ephemeris: Ephemeris, target: GroundTarget, sensor: NadirSensor
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    satellite_itrs = transform_ephemeris(ephemeris, "ITRS")
    target_ecef = target.ecef_position_m
    target_itrs = Ephemeris(
        ephemeris.times,
        np.repeat(target_ecef[None, :], len(ephemeris), axis=0),
        np.zeros((len(ephemeris), 3)),
        "ITRS",
    )
    target_gcrs = transform_ephemeris(target_itrs, "GCRS")

    line_itrs = target_ecef[None, :] - satellite_itrs.positions_m
    target_to_satellite_itrs = -line_itrs
    ranges = np.linalg.norm(line_itrs, axis=1)
    up = np.array(
        [
            np.cos(target.latitude_rad) * np.cos(target.longitude_rad),
            np.cos(target.latitude_rad) * np.sin(target.longitude_rad),
            np.sin(target.latitude_rad),
        ]
    )
    elevation = np.arcsin(
        np.clip((target_to_satellite_itrs @ up) / ranges, -1.0, 1.0)
    )

    positions = ephemeris.positions_m
    velocities = ephemeris.velocities_m_s
    radial = positions / np.linalg.norm(positions, axis=1)[:, None]
    orbit_normal = np.cross(positions, velocities)
    orbit_normal /= np.linalg.norm(orbit_normal, axis=1)[:, None]
    ez = -radial
    ey = orbit_normal
    ex = np.cross(ey, ez)
    local = sensor.boresight_vvlh
    boresight = ex * local[0] + ey * local[1] + ez * local[2]
    line_gcrs = target_gcrs.positions_m - positions
    line_gcrs /= np.linalg.norm(line_gcrs, axis=1)[:, None]
    off_boresight = np.arccos(np.clip(np.sum(line_gcrs * boresight, axis=1), -1.0, 1.0))

    margins = np.minimum(
        elevation - sensor.minimum_elevation_rad,
        sensor.half_angle_rad - off_boresight,
    )
    if sensor.maximum_range_m is not None:
        # Map the length constraint to an angular-like margin while preserving
        # its zero crossing, so combined_margin_rad keeps consistent units.
        range_margin = np.arctan((sensor.maximum_range_m - ranges) / sensor.maximum_range_m)
        margins = np.minimum(margins, range_margin)
    return margins, elevation, off_boresight, ranges


def _single_margin(
    elapsed_s: float,
    interpolator: EphemerisInterpolator,
    target: GroundTarget,
    sensor: NadirSensor,
) -> float:
    satellite = interpolator.state_at_seconds(elapsed_s)
    target_itrs = OrbitState(
        satellite.epoch, target.ecef_position_m, np.zeros(3), "ITRS"
    )
    target_gcrs = ecef_to_eci(target_itrs)
    satellite_itrs = eci_to_ecef(satellite)
    target_to_satellite = satellite_itrs.position_m - target.ecef_position_m
    slant_range = np.linalg.norm(target_to_satellite)
    up = np.array(
        [
            np.cos(target.latitude_rad) * np.cos(target.longitude_rad),
            np.cos(target.latitude_rad) * np.sin(target.longitude_rad),
            np.sin(target.latitude_rad),
        ]
    )
    elevation = np.arcsin(np.clip(np.dot(target_to_satellite, up) / slant_range, -1.0, 1.0))

    radial = satellite.position_m / np.linalg.norm(satellite.position_m)
    normal = np.cross(satellite.position_m, satellite.velocity_m_s)
    normal /= np.linalg.norm(normal)
    ez = -radial
    ey = normal
    ex = np.cross(ey, ez)
    local = sensor.boresight_vvlh
    boresight = ex * local[0] + ey * local[1] + ez * local[2]
    line = target_gcrs.position_m - satellite.position_m
    off_boresight = np.arccos(
        np.clip(np.dot(line, boresight) / np.linalg.norm(line), -1.0, 1.0)
    )
    margin = min(
        float(elevation - sensor.minimum_elevation_rad),
        float(sensor.half_angle_rad - off_boresight),
    )
    if sensor.maximum_range_m is not None:
        margin = min(
            margin,
            float(np.arctan((sensor.maximum_range_m - slant_range) / sensor.maximum_range_m)),
        )
    return margin


def _windows_from_samples(
    seconds: np.ndarray,
    margins: np.ndarray,
    interpolator: EphemerisInterpolator,
    target: GroundTarget,
    sensor: NadirSensor,
    boundary_tolerance_s: float,
) -> tuple[AccessWindow, ...]:
    roots: list[float] = []
    for index in range(len(seconds) - 1):
        left, right = margins[index], margins[index + 1]
        if left == 0.0:
            roots.append(float(seconds[index]))
        if left * right < 0.0:
            root = brentq(
                _single_margin,
                float(seconds[index]),
                float(seconds[index + 1]),
                args=(interpolator, target, sensor),
                xtol=boundary_tolerance_s,
            )
            roots.append(float(root))
    if margins[-1] == 0.0:
        roots.append(float(seconds[-1]))
    roots = sorted(set(roots))
    boundaries = [float(seconds[0]), *roots, float(seconds[-1])]
    windows: list[AccessWindow] = []
    for left, right in zip(boundaries, boundaries[1:]):
        if right <= left:
            continue
        midpoint = 0.5 * (left + right)
        if _single_margin(midpoint, interpolator, target, sensor) >= 0.0:
            windows.append(
                AccessWindow(
                    interpolator.epoch + timedelta(seconds=left),
                    interpolator.epoch + timedelta(seconds=right),
                )
            )
    return tuple(windows)


def access_interpolation(
    ephemeris: Ephemeris,
    target: GroundTarget,
    sensor: NadirSensor,
    *,
    scan_step_s: float = 20.0,
    boundary_tolerance_s: float = 0.01,
) -> AccessResult:
    """Find access windows from sampled GCRS states using Hermite interpolation.

    The scan interval controls the shortest event that can be discovered; the
    boundary tolerance controls bisection/root-refinement accuracy.
    """

    if boundary_tolerance_s <= 0.0:
        raise ValueError("boundary_tolerance_s must be positive")
    interpolator = EphemerisInterpolator(ephemeris)
    dense = _dense_ephemeris(interpolator, scan_step_s)
    margins, elevations, off_boresight, ranges = _sample_metrics(dense, target, sensor)
    windows = _windows_from_samples(
        dense.elapsed_seconds,
        margins,
        interpolator,
        target,
        sensor,
        boundary_tolerance_s,
    )
    return AccessResult(
        target,
        windows,
        dense.times,
        margins,
        elevations,
        off_boresight,
        ranges,
    )


def access_propagation(
    propagator: OrbitPropagator,
    initial_state: OrbitState,
    target: GroundTarget,
    sensor: NadirSensor,
    *,
    start: datetime,
    stop: datetime,
    propagation_step_s: float = 60.0,
    scan_step_s: float = 20.0,
    boundary_tolerance_s: float = 0.01,
) -> AccessResult:
    """Propagate an orbit, then compute target access with refined boundaries."""

    ephemeris = propagator.propagate(
        initial_state, time_grid(start, stop, propagation_step_s)
    )
    return access_interpolation(
        ephemeris,
        target,
        sensor,
        scan_step_s=scan_step_s,
        boundary_tolerance_s=boundary_tolerance_s,
    )
