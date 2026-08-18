"""Static high-degree Earth gravity fields in ICGEM ``.gfc`` format.

The implementation evaluates fully-normalized spherical harmonics in ITRS and
rotates the resulting perturbing acceleration back to GCRS.  Degree zero is
deliberately omitted from :class:`SphericalHarmonicGravity` because the orbit
propagators already include :class:`~ntu_space_dynamics.orbits.forces.PointMassGravity`.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from importlib.resources import as_file, files
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import GCRS, ITRS, CartesianRepresentation
from astropy.time import Time
from astropy.utils import iers
from numpy.typing import ArrayLike, NDArray
from scipy.spatial.transform import Rotation, Slerp

from .time import ensure_utc, ensure_utc_sequence


def _parse_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


@dataclass(frozen=True)
class GravityFieldCoefficients:
    """Fully-normalized static spherical-harmonic coefficients."""

    model_name: str
    mu_m3_s2: float
    reference_radius_m: float
    cosine: NDArray[np.float64]
    sine: NDArray[np.float64]
    tide_system: str = "unknown"
    source: str | None = None

    def __post_init__(self) -> None:
        cosine = np.asarray(self.cosine, dtype=float)
        sine = np.asarray(self.sine, dtype=float)
        if cosine.ndim != 2 or cosine.shape[0] != cosine.shape[1] or sine.shape != cosine.shape:
            raise ValueError("cosine and sine coefficients must be equally sized square arrays")
        if cosine.shape[0] < 3:
            raise ValueError("gravity coefficients must include at least degree 2")
        if self.mu_m3_s2 <= 0.0 or self.reference_radius_m <= 0.0:
            raise ValueError("gravity constant and reference radius must be positive")
        if not np.all(np.isfinite(cosine)) or not np.all(np.isfinite(sine)):
            raise ValueError("gravity coefficients must be finite")
        if not np.isclose(cosine[0, 0], 1.0, rtol=0.0, atol=1e-14):
            raise ValueError("a normalized gravity field must contain C00 = 1")
        cosine = cosine.copy()
        sine = sine.copy()
        cosine.setflags(write=False)
        sine.setflags(write=False)
        object.__setattr__(self, "cosine", cosine)
        object.__setattr__(self, "sine", sine)

    @property
    def max_degree(self) -> int:
        return self.cosine.shape[0] - 1

    @classmethod
    def from_icgem(
        cls,
        path: str | Path,
        *,
        max_degree: int | None = None,
        max_order: int | None = None,
    ) -> "GravityFieldCoefficients":
        """Read a static, fully-normalized ICGEM gravity field.

        Static ``gfc`` records are supported.  Time-variable ``gfct/trnd/asin/acos``
        records must first be reduced to a gravity field at a selected epoch.
        """

        source_path = Path(path)
        header: dict[str, str] = {}
        with source_path.open("r", encoding="utf-8", errors="strict") as stream:
            for raw_line in stream:
                line = raw_line.strip()
                if not line or line.startswith(('#', '%')):
                    continue
                parts = line.split()
                if parts[0] == "end_of_head":
                    break
                if len(parts) >= 2:
                    header[parts[0].lower()] = " ".join(parts[1:])
            else:
                raise ValueError(f"{source_path} has no ICGEM end_of_head marker")

            required = {"modelname", "earth_gravity_constant", "radius", "max_degree"}
            missing = sorted(required - header.keys())
            if missing:
                raise ValueError(f"missing ICGEM header fields: {', '.join(missing)}")
            normalization = header.get("norm", "fully_normalized").lower()
            if normalization != "fully_normalized":
                raise ValueError(
                    f"only fully_normalized ICGEM coefficients are supported, got {normalization!r}"
                )
            file_degree = int(header["max_degree"])
            degree = file_degree if max_degree is None else min(int(max_degree), file_degree)
            if degree < 2:
                raise ValueError("max_degree must be at least 2")
            order = degree if max_order is None else min(int(max_order), degree)
            if order < 0:
                raise ValueError("max_order must be non-negative")
            cosine = np.zeros((degree + 1, degree + 1), dtype=float)
            sine = np.zeros_like(cosine)
            found_c00 = False

            for raw_line in stream:
                line = raw_line.strip()
                if not line or line.startswith(('#', '%')):
                    continue
                parts = line.split()
                record = parts[0].lower()
                if record in {"gfct", "trnd", "asin", "acos"}:
                    raise ValueError(
                        "time-variable ICGEM records are not supported by the static loader"
                    )
                if record != "gfc" or len(parts) < 5:
                    continue
                n, m = int(parts[1]), int(parts[2])
                if n > degree or m > order:
                    continue
                cosine[n, m] = _parse_float(parts[3])
                sine[n, m] = _parse_float(parts[4])
                if n == 0 and m == 0:
                    found_c00 = True
            if not found_c00:
                raise ValueError("ICGEM coefficient section does not contain C00")

        return cls(
            header["modelname"],
            _parse_float(header["earth_gravity_constant"]),
            _parse_float(header["radius"]),
            cosine,
            sine,
            header.get("tide_system", "unknown"),
            str(source_path.resolve()),
        )


def _legendre_fully_normalized(
    latitude_rad: float, max_degree: int
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return fully-normalized Pnm(sin(latitude)) and dPnm/d(latitude)."""

    sine_latitude = float(np.sin(latitude_rad))
    cosine_latitude = float(np.cos(latitude_rad))
    values = np.zeros((max_degree + 1, max_degree + 1), dtype=float)
    derivatives = np.zeros_like(values)
    values[0, 0] = 1.0

    for order in range(max_degree + 1):
        if order > 0:
            diagonal_factor = (
                np.sqrt(3.0)
                if order == 1
                else np.sqrt((2.0 * order + 1.0) / (2.0 * order))
            )
            values[order, order] = (
                diagonal_factor * cosine_latitude * values[order - 1, order - 1]
            )
            derivatives[order, order] = diagonal_factor * (
                -sine_latitude * values[order - 1, order - 1]
                + cosine_latitude * derivatives[order - 1, order - 1]
            )

        if order < max_degree:
            subdiagonal_factor = np.sqrt(2.0 * order + 3.0)
            values[order + 1, order] = (
                subdiagonal_factor * sine_latitude * values[order, order]
            )
            derivatives[order + 1, order] = subdiagonal_factor * (
                cosine_latitude * values[order, order]
                + sine_latitude * derivatives[order, order]
            )

        for degree in range(order + 2, max_degree + 1):
            first = np.sqrt(
                (2.0 * degree + 1.0)
                * (2.0 * degree - 1.0)
                / ((degree - order) * (degree + order))
            )
            second = np.sqrt(
                (2.0 * degree + 1.0)
                * (degree + order - 1.0)
                * (degree - order - 1.0)
                / (
                    (2.0 * degree - 3.0)
                    * (degree - order)
                    * (degree + order)
                )
            )
            values[degree, order] = (
                first * sine_latitude * values[degree - 1, order]
                - second * values[degree - 2, order]
            )
            derivatives[degree, order] = first * (
                cosine_latitude * values[degree - 1, order]
                + sine_latitude * derivatives[degree - 1, order]
            ) - second * derivatives[degree - 2, order]
    return values, derivatives


def _gcrs_to_itrs_matrices(times: tuple[datetime, ...]) -> NDArray[np.float64]:
    times = ensure_utc_sequence(times)
    repeated_times = tuple(time for time in times for _ in range(3))
    basis_rows = np.tile(np.eye(3), (len(times), 1))
    astropy_time = Time(list(repeated_times), scale="utc")
    source = GCRS(
        CartesianRepresentation(basis_rows.T * u.m),
        obstime=astropy_time,
    )
    with ExitStack() as stack:
        stack.enter_context(iers.conf.set_temp("auto_download", False))
        stack.enter_context(iers.conf.set_temp("auto_max_age", None))
        converted = source.transform_to(ITRS(obstime=astropy_time))
    images = converted.cartesian.xyz.to_value(u.m).T.reshape(len(times), 3, 3)
    matrices = np.transpose(images, (0, 2, 1))
    return matrices


@dataclass
class EarthOrientationCache:
    """SLERP cache of GCRS-to-ITRS rotations used by a propagation arc."""

    sample_step_s: float = 300.0
    _epoch: datetime | None = field(default=None, init=False, repr=False)
    _duration_s: float = field(default=0.0, init=False, repr=False)
    _slerp: Slerp | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not np.isfinite(self.sample_step_s) or self.sample_step_s <= 0.0:
            raise ValueError("sample_step_s must be a finite positive number")

    def prepare(self, epoch: datetime, duration_s: float) -> None:
        epoch = ensure_utc(epoch)
        duration_s = float(duration_s)
        if duration_s <= 0.0:
            return
        if self._epoch == epoch and self._slerp is not None and duration_s <= self._duration_s:
            return
        seconds = np.arange(0.0, duration_s, self.sample_step_s)
        if len(seconds) == 0 or seconds[-1] != duration_s:
            seconds = np.append(seconds, duration_s)
        if len(seconds) == 1:
            seconds = np.array([0.0, duration_s])
        times = tuple(epoch + timedelta(seconds=float(value)) for value in seconds)
        matrices = _gcrs_to_itrs_matrices(times)
        self._epoch = epoch
        self._duration_s = duration_s
        self._slerp = Slerp(seconds, Rotation.from_matrix(matrices))

    def rotation(self, elapsed_s: float, epoch: datetime) -> Rotation:
        epoch = ensure_utc(epoch)
        elapsed_s = float(elapsed_s)
        if (
            self._slerp is not None
            and self._epoch == epoch
            and 0.0 <= elapsed_s <= self._duration_s
        ):
            return self._slerp([elapsed_s])[0]
        matrix = _gcrs_to_itrs_matrices((epoch + timedelta(seconds=elapsed_s),))[0]
        return Rotation.from_matrix(matrix)


@dataclass
class SphericalHarmonicGravity:
    """Static non-central gravity perturbation from a spherical-harmonic field."""

    coefficients: GravityFieldCoefficients
    max_degree: int | None = None
    max_order: int | None = None
    orientation_cache: EarthOrientationCache = field(default_factory=EarthOrientationCache)

    def __post_init__(self) -> None:
        degree = self.coefficients.max_degree if self.max_degree is None else int(self.max_degree)
        if not 2 <= degree <= self.coefficients.max_degree:
            raise ValueError(
                f"max_degree must lie in [2, {self.coefficients.max_degree}]"
            )
        order = degree if self.max_order is None else int(self.max_order)
        if not 0 <= order <= degree:
            raise ValueError("max_order must lie in [0, max_degree]")
        self.max_degree = degree
        self.max_order = order

    def prepare(self, epoch: datetime, duration_s: float) -> None:
        self.orientation_cache.prepare(epoch, duration_s)

    def potential_fixed(self, position_itrs_m: ArrayLike) -> float:
        """Non-central geopotential in m²/s² at an ITRS position."""

        position = np.asarray(position_itrs_m, dtype=float)
        if position.shape != (3,) or not np.all(np.isfinite(position)):
            raise ValueError("position_itrs_m must be a finite 3-vector")
        radius = float(np.linalg.norm(position))
        if radius <= self.coefficients.reference_radius_m:
            raise ValueError("spherical harmonics require a point outside the reference sphere")
        longitude = float(np.arctan2(position[1], position[0]))
        latitude = float(np.arctan2(position[2], np.hypot(position[0], position[1])))
        legendre, _ = _legendre_fully_normalized(latitude, self.max_degree)
        orders = np.arange(self.max_order + 1)
        cosines = np.cos(orders * longitude)
        sines = np.sin(orders * longitude)
        ratio = self.coefficients.reference_radius_m / radius
        radial_power = ratio * ratio
        total = 0.0
        for degree in range(2, self.max_degree + 1):
            upper_order = min(degree, self.max_order)
            harmonic = (
                self.coefficients.cosine[degree, : upper_order + 1]
                * cosines[: upper_order + 1]
                + self.coefficients.sine[degree, : upper_order + 1]
                * sines[: upper_order + 1]
            )
            total += radial_power * float(
                np.dot(legendre[degree, : upper_order + 1], harmonic)
            )
            radial_power *= ratio
        return self.coefficients.mu_m3_s2 / radius * total

    def acceleration_fixed(self, position_itrs_m: ArrayLike) -> NDArray[np.float64]:
        """Non-central acceleration in ITRS, excluding point-mass gravity."""

        position = np.asarray(position_itrs_m, dtype=float)
        if position.shape != (3,) or not np.all(np.isfinite(position)):
            raise ValueError("position_itrs_m must be a finite 3-vector")
        x, y, z = position
        radius = float(np.linalg.norm(position))
        if radius <= self.coefficients.reference_radius_m:
            raise ValueError("spherical harmonics require a point outside the reference sphere")
        horizontal = float(np.hypot(x, y))
        longitude = float(np.arctan2(y, x))
        latitude = float(np.arctan2(z, horizontal))
        cosine_latitude = horizontal / radius
        if cosine_latitude < 1e-10:
            # Longitude derivatives are singular at an exact pole.  The Cartesian
            # gradient of the same potential provides a robust rare-case fallback.
            step_m = 0.5
            result = np.empty(3)
            for axis in range(3):
                delta = np.zeros(3)
                delta[axis] = step_m
                result[axis] = (
                    self.potential_fixed(position + delta)
                    - self.potential_fixed(position - delta)
                ) / (2.0 * step_m)
            return result

        sine_latitude = z / radius
        legendre, derivative = _legendre_fully_normalized(latitude, self.max_degree)
        orders = np.arange(self.max_order + 1)
        cosines = np.cos(orders * longitude)
        sines = np.sin(orders * longitude)
        ratio = self.coefficients.reference_radius_m / radius
        radial_power = ratio * ratio
        radial_sum = 0.0
        latitude_sum = 0.0
        longitude_sum = 0.0

        for degree in range(2, self.max_degree + 1):
            upper_order = min(degree, self.max_order)
            selected_orders = orders[: upper_order + 1]
            c = self.coefficients.cosine[degree, : upper_order + 1]
            s = self.coefficients.sine[degree, : upper_order + 1]
            harmonic = c * cosines[: upper_order + 1] + s * sines[: upper_order + 1]
            longitude_harmonic = selected_orders * (
                -c * sines[: upper_order + 1] + s * cosines[: upper_order + 1]
            )
            p = legendre[degree, : upper_order + 1]
            radial_sum += (degree + 1.0) * radial_power * float(np.dot(p, harmonic))
            latitude_sum += radial_power * float(
                np.dot(derivative[degree, : upper_order + 1], harmonic)
            )
            longitude_sum += radial_power * float(np.dot(p, longitude_harmonic))
            radial_power *= ratio

        scale = self.coefficients.mu_m3_s2 / radius**2
        acceleration_radial = -scale * radial_sum
        acceleration_latitude = scale * latitude_sum
        acceleration_longitude = scale * longitude_sum / cosine_latitude
        cosine_longitude, sine_longitude = np.cos(longitude), np.sin(longitude)
        radial_unit = np.array(
            [cosine_latitude * cosine_longitude, cosine_latitude * sine_longitude, sine_latitude]
        )
        latitude_unit = np.array(
            [-sine_latitude * cosine_longitude, -sine_latitude * sine_longitude, cosine_latitude]
        )
        longitude_unit = np.array([-sine_longitude, cosine_longitude, 0.0])
        return (
            acceleration_radial * radial_unit
            + acceleration_latitude * latitude_unit
            + acceleration_longitude * longitude_unit
        )

    def acceleration(self, elapsed_s: float, state: np.ndarray, epoch: datetime) -> np.ndarray:
        rotation = self.orientation_cache.rotation(elapsed_s, epoch)
        position_itrs = rotation.apply(state[:3])
        acceleration_itrs = self.acceleration_fixed(position_itrs)
        return rotation.inv().apply(acceleration_itrs)


@lru_cache(maxsize=4)
def load_builtin_egm2008(max_degree: int = 70) -> GravityFieldCoefficients:
    """Load the packaged EGM2008 coefficients (available through degree 120)."""

    if not 2 <= max_degree <= 120:
        raise ValueError("the packaged EGM2008 model supports degrees 2 through 120")
    resource = files("ntu_space_dynamics").joinpath("data/gravity/EGM2008_120.gfc")
    with as_file(resource) as path:
        return GravityFieldCoefficients.from_icgem(path, max_degree=max_degree)
