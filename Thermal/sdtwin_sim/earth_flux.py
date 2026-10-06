"""Earth albedo and infrared surface inputs for the thermal module (design section 5.3).

The design report treats Earth albedo and Earth infrared as environment data that must be supplied next to Orbit's
direct solar irradiance; they cannot be inferred from it. This provider computes them for each exposed surface of a
thermal parameter set from the satellite position, the Sun position and the attitude at one instant.

Earth is modelled as a sphere of radius ``earth_radius_m`` with a Lambertian surface. An Earth element ``dA`` that
faces both the satellite and the plate contributes ``cos(theta_plate) cos(theta_earth) dA / (pi d^2)`` to the view
factor ``F``. Because ``cos(theta_earth) dA / d^2`` is the solid angle ``dOmega`` that the element subtends at the
satellite, the integral over the visible spherical cap is evaluated on the satellite's sky: the cap seen from the
satellite is the cone of nadir angles ``eta <= eta_max`` with ``sin(eta_max) = R / r``, and every quadrature direction
is traced to its Earth element. This change of variables is exact and keeps the integrand smooth up to the limb.
The albedo factor ``F_alb`` additionally weights each element by ``max(0, cos(solar zenith angle))``.

Irradiances returned per surface: ``infrared = olr * F`` and ``albedo = albedo * solar_constant * F_alb``, in W/m^2.
No default device or environment values are assumed; albedo, OLR and solar constant are required inputs.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.spatial.transform import Rotation

__all__ = [
    "EarthFluxError",
    "earth_view_factor",
    "albedo_factor",
    "earth_flux_record",
]

_UNIT_TOLERANCE = 1e-9
_WGS84_EQUATORIAL_RADIUS_M = 6378137.0
_DEFAULT_RESOLUTION = (240, 360)


class EarthFluxError(ValueError):
    """Invalid input to the Earth albedo and infrared provider."""


# --------------------------------------------------------------------------------------------------------------------
# validation helpers


def _finite_scalar(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EarthFluxError(f"{name} must be a real number, got {value!r}") from exc
    if isinstance(value, bool) or not math.isfinite(number):
        raise EarthFluxError(f"{name} must be a finite real number, got {value!r}")
    return number


def _nonnegative_scalar(value: Any, name: str) -> float:
    number = _finite_scalar(value, name)
    if number < 0.0:
        raise EarthFluxError(f"{name} must be >= 0, got {number!r}")
    return number


def _vector(value: ArrayLike, name: str, length: int = 3) -> NDArray[np.float64]:
    try:
        array = np.array(value, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise EarthFluxError(f"{name} must be a numeric array of shape ({length},)") from exc
    if array.shape != (length,):
        raise EarthFluxError(f"{name} must have shape ({length},), got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise EarthFluxError(f"{name} must contain only finite values")
    return array


def _unit_vector(value: ArrayLike, name: str, length: int = 3) -> NDArray[np.float64]:
    array = _vector(value, name, length)
    norm = float(np.linalg.norm(array))
    if abs(norm - 1.0) > _UNIT_TOLERANCE:
        raise EarthFluxError(f"{name} must be a unit vector within {_UNIT_TOLERANCE:g}, got norm {norm!r}")
    return array


def _earth_radius(value: Any) -> float:
    radius = _finite_scalar(value, "earth_radius_m")
    if radius <= 0.0:
        raise EarthFluxError(f"earth_radius_m must be > 0, got {radius!r}")
    return radius


def _position(value: ArrayLike, earth_radius_m: float) -> NDArray[np.float64]:
    position = _vector(value, "position_m")
    distance = float(np.linalg.norm(position))
    if distance <= earth_radius_m:
        raise EarthFluxError(
            f"position_m must lie outside the Earth sphere: |position_m| = {distance!r} m "
            f"<= earth_radius_m = {earth_radius_m!r} m"
        )
    return position


def _resolution(value: Any) -> tuple[int, int]:
    try:
        items = tuple(value)
    except TypeError as exc:
        raise EarthFluxError(f"resolution must be a pair (n_nadir, n_azimuth), got {value!r}") from exc
    if len(items) != 2:
        raise EarthFluxError(f"resolution must be a pair (n_nadir, n_azimuth), got {value!r}")
    result = []
    for label, item in zip(("n_nadir", "n_azimuth"), items):
        if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
            raise EarthFluxError(f"resolution {label} must be an integer, got {item!r}")
        if int(item) < 4:
            raise EarthFluxError(f"resolution {label} must be >= 4, got {int(item)}")
        result.append(int(item))
    return result[0], result[1]


# --------------------------------------------------------------------------------------------------------------------
# quadrature over the visible spherical cap


def _cap_quadrature(
    position_m: NDArray[np.float64], earth_radius_m: float, resolution: tuple[int, int]
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Return directions (N, 3), solid-angle weights (N,) and Earth-element unit normals (N, 3).

    Midpoint rule in nadir angle ``eta`` and azimuth ``phi`` around the nadir direction. The weight of a cell is its
    exact solid angle ``(cos eta_lo - cos eta_hi) dphi``, which equals ``cos(theta_earth) dA / d^2`` of the Earth
    element the cell's central ray hits.
    """

    n_eta, n_phi = resolution
    r = float(np.linalg.norm(position_m))
    up = position_m / r
    nadir = -up
    # deterministic transverse basis
    helper = np.zeros(3)
    helper[int(np.argmin(np.abs(up)))] = 1.0
    e1 = np.cross(up, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)

    eta_max = math.asin(earth_radius_m / r)
    eta_edges = np.linspace(0.0, eta_max, n_eta + 1)
    eta = 0.5 * (eta_edges[:-1] + eta_edges[1:])
    ring_solid_angle = np.cos(eta_edges[:-1]) - np.cos(eta_edges[1:])  # per unit azimuth
    dphi = 2.0 * math.pi / n_phi
    phi = (np.arange(n_phi) + 0.5) * dphi

    sin_eta = np.sin(eta)[:, None]
    cos_eta = np.cos(eta)[:, None]
    cos_phi = np.cos(phi)[None, :]
    sin_phi = np.sin(phi)[None, :]
    directions = (
        cos_eta[..., None] * nadir
        + (sin_eta * cos_phi)[..., None] * e1
        + (sin_eta * sin_phi)[..., None] * e2
    ).reshape(-1, 3)
    weights = np.broadcast_to((ring_solid_angle * dphi)[:, None], (n_eta, n_phi)).reshape(-1)

    # distance to the near intersection of each ray with the sphere
    cos_e = np.repeat(np.cos(eta), n_phi)
    sin_e = np.repeat(np.sin(eta), n_phi)
    discriminant = np.clip(earth_radius_m**2 - (r * sin_e) ** 2, 0.0, None)
    distance = r * cos_e - np.sqrt(discriminant)
    hit_points = position_m[None, :] + distance[:, None] * directions
    element_normals = hit_points / earth_radius_m
    return directions, weights, element_normals


def _view_factors(
    normals_gcrs: NDArray[np.float64],
    directions: NDArray[np.float64],
    weights: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Earth view factor for each row of ``normals_gcrs``."""

    cos_plate = np.clip(normals_gcrs @ directions.T, 0.0, None)
    return (cos_plate @ weights) / math.pi


def _albedo_factors(
    normals_gcrs: NDArray[np.float64],
    directions: NDArray[np.float64],
    weights: NDArray[np.float64],
    element_normals: NDArray[np.float64],
    sun_dir: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Albedo factor for each row of ``normals_gcrs``."""

    cos_plate = np.clip(normals_gcrs @ directions.T, 0.0, None)
    cos_zenith = np.clip(element_normals @ sun_dir, 0.0, None)
    return (cos_plate @ (weights * cos_zenith)) / math.pi


# --------------------------------------------------------------------------------------------------------------------
# public helpers


def earth_view_factor(
    position_m: ArrayLike,
    normal_gcrs: ArrayLike,
    *,
    earth_radius_m: float = _WGS84_EQUATORIAL_RADIUS_M,
    resolution: Sequence[int] = _DEFAULT_RESOLUTION,
) -> float:
    """Return the view factor from a plate at ``position_m`` with unit normal ``normal_gcrs`` to a Lambertian Earth.

    ``position_m`` is the geocentric satellite position in m; ``normal_gcrs`` is the outward plate normal in the same
    frame. ``resolution = (n_nadir, n_azimuth)`` sets the quadrature grid. A nadir plate gives ``(R / r)^2``.
    """

    radius = _earth_radius(earth_radius_m)
    position = _position(position_m, radius)
    normal = _unit_vector(normal_gcrs, "normal_gcrs")
    grid = _resolution(resolution)
    directions, weights, _ = _cap_quadrature(position, radius, grid)
    return float(_view_factors(normal[None, :], directions, weights)[0])


def albedo_factor(
    position_m: ArrayLike,
    normal_gcrs: ArrayLike,
    sun_dir: ArrayLike,
    *,
    earth_radius_m: float = _WGS84_EQUATORIAL_RADIUS_M,
    resolution: Sequence[int] = _DEFAULT_RESOLUTION,
) -> float:
    """Return the albedo view factor: the Earth view factor weighted by ``max(0, cos solar zenith)`` per element.

    ``sun_dir`` is the unit direction from Earth to the Sun in the frame of ``position_m``; the Sun is treated as
    infinitely distant, so one direction serves every Earth element.
    """

    radius = _earth_radius(earth_radius_m)
    position = _position(position_m, radius)
    normal = _unit_vector(normal_gcrs, "normal_gcrs")
    sun = _unit_vector(sun_dir, "sun_dir")
    grid = _resolution(resolution)
    directions, weights, element_normals = _cap_quadrature(position, radius, grid)
    return float(_albedo_factors(normal[None, :], directions, weights, element_normals, sun)[0])


def _surface_records(surfaces: Any) -> tuple[Any, ...]:
    container = getattr(surfaces, "surfaces", surfaces)
    if isinstance(container, (str, bytes)) or not isinstance(container, Iterable):
        raise EarthFluxError("surfaces must be a ThermalParameters or a sequence of surface records")
    records = tuple(container)
    if not records:
        raise EarthFluxError("surfaces must contain at least one surface record")
    return records


def earth_flux_record(
    run_id: str,
    time_s: float,
    position_m: ArrayLike,
    sun_position_m: ArrayLike,
    quaternion_xyzw: ArrayLike,
    surfaces: Any,
    *,
    albedo: float,
    olr_W_m2: float,
    solar_constant_W_m2: float,
    earth_radius_m: float = _WGS84_EQUATORIAL_RADIUS_M,
    resolution: Sequence[int] = _DEFAULT_RESOLUTION,
) -> dict[str, Any]:
    """Return the ``earth_flux`` mapping of design section 5.3 for the surfaces of a thermal parameter set.

    ``position_m`` and ``sun_position_m`` (Earth to Sun) are GCRS vectors in m at the same instant;
    ``quaternion_xyzw`` is the active body-to-GCRS rotation in SciPy xyzw order. ``surfaces`` is a
    ``ThermalParameters`` (its ``surfaces`` are read) or a sequence of records with ``surface_id`` and
    ``normal_body``. ``albedo`` is the Bond albedo fraction, ``olr_W_m2`` the outgoing longwave radiation at the
    Earth's surface, ``solar_constant_W_m2`` the solar irradiance used for the reflected light.

    Returns ``{"run_id", "time_s", "surface_ids", "albedo_W_m2", "infrared_W_m2"}`` with read-only arrays in the
    given surface order.
    """

    if not isinstance(run_id, str) or not run_id:
        raise EarthFluxError(f"run_id must be a non-empty string, got {run_id!r}")
    time = _finite_scalar(time_s, "time_s")
    radius = _earth_radius(earth_radius_m)
    position = _position(position_m, radius)
    sun_position = _vector(sun_position_m, "sun_position_m")
    sun_norm = float(np.linalg.norm(sun_position))
    if sun_norm == 0.0:
        raise EarthFluxError("sun_position_m must be a nonzero Earth-to-Sun vector")
    sun_dir = sun_position / sun_norm
    quaternion = _unit_vector(quaternion_xyzw, "quaternion_xyzw", length=4)
    albedo_value = _nonnegative_scalar(albedo, "albedo")
    if albedo_value > 1.0:
        raise EarthFluxError(f"albedo must be a fraction in [0, 1], got {albedo_value!r}")
    olr = _nonnegative_scalar(olr_W_m2, "olr_W_m2")
    solar_constant = _nonnegative_scalar(solar_constant_W_m2, "solar_constant_W_m2")
    grid = _resolution(resolution)

    records = _surface_records(surfaces)
    surface_ids: list[str] = []
    normals_body = np.empty((len(records), 3))
    for index, record in enumerate(records):
        surface_id = getattr(record, "surface_id", None)
        if not isinstance(surface_id, str) or not surface_id:
            raise EarthFluxError(f"surfaces[{index}].surface_id must be a non-empty string, got {surface_id!r}")
        if surface_id in surface_ids:
            raise EarthFluxError(f"surfaces[{index}].surface_id {surface_id!r} is duplicated")
        if not hasattr(record, "normal_body"):
            raise EarthFluxError(f"surface {surface_id!r}: field normal_body is missing")
        normals_body[index] = _unit_vector(record.normal_body, f"surface {surface_id!r} normal_body")
        surface_ids.append(surface_id)

    normals_gcrs = Rotation.from_quat(quaternion).apply(normals_body)
    normals_gcrs /= np.linalg.norm(normals_gcrs, axis=1, keepdims=True)

    directions, weights, element_normals = _cap_quadrature(position, radius, grid)
    view = _view_factors(normals_gcrs, directions, weights)
    view_albedo = _albedo_factors(normals_gcrs, directions, weights, element_normals, sun_dir)

    infrared = olr * view
    reflected = albedo_value * solar_constant * view_albedo
    infrared.setflags(write=False)
    reflected.setflags(write=False)
    return {
        "run_id": run_id,
        "time_s": time,
        "surface_ids": tuple(surface_ids),
        "albedo_W_m2": reflected,
        "infrared_W_m2": infrared,
    }
