"""Conversions between Cartesian state vectors and classical elements."""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import ArrayLike, NDArray

from ..constants import MU_EARTH, TWOPI
from ..types import ClassicalElements


def _rotation_3(angle: float) -> NDArray[np.float64]:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _rotation_1(angle: float) -> NDArray[np.float64]:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def oe_to_rv(
    elements: ClassicalElements, mu_m3_s2: float = MU_EARTH
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Convert elliptic osculating elements to an inertial Cartesian state.

    The element anomaly is interpreted as true anomaly.  Output units are m
    and m/s when ``mu_m3_s2`` is supplied in SI units.
    """

    if mu_m3_s2 <= 0.0:
        raise ValueError("mu_m3_s2 must be positive")
    a = elements.semi_major_axis_m
    e = elements.eccentricity
    nu = elements.anomaly_rad
    p = a * (1.0 - e * e)
    denominator = 1.0 + e * np.cos(nu)
    if denominator <= 0.0:
        raise ValueError("true anomaly produces an invalid elliptic radius")

    position_perifocal = (p / denominator) * np.array([np.cos(nu), np.sin(nu), 0.0])
    velocity_perifocal = np.sqrt(mu_m3_s2 / p) * np.array(
        [-np.sin(nu), e + np.cos(nu), 0.0]
    )
    rotation = (
        _rotation_3(elements.raan_rad)
        @ _rotation_1(elements.inclination_rad)
        @ _rotation_3(elements.argument_of_periapsis_rad)
    )
    return rotation @ position_perifocal, rotation @ velocity_perifocal


def _signed_angle(first: np.ndarray, second: np.ndarray, normal: np.ndarray) -> float:
    first_norm = np.linalg.norm(first)
    second_norm = np.linalg.norm(second)
    normal_norm = np.linalg.norm(normal)
    sine = np.dot(np.cross(first, second), normal) / (first_norm * second_norm * normal_norm)
    cosine = np.dot(first, second) / (first_norm * second_norm)
    return float(np.arctan2(sine, cosine) % TWOPI)


def rv_to_oe(
    position_m: ArrayLike,
    velocity_m_s: ArrayLike,
    *,
    epoch: datetime | None = None,
    mu_m3_s2: float = MU_EARTH,
    singularity_tolerance: float = 1e-10,
) -> ClassicalElements:
    """Convert an inertial Cartesian state to elliptic classical elements.

    Singularity conventions make the result deterministic:

    * circular inclined: argument of periapsis is zero and anomaly is argument of latitude;
    * eccentric equatorial: RAAN is zero and argument of periapsis is longitude of periapsis;
    * circular equatorial: RAAN and argument of periapsis are zero and anomaly is true longitude.
    """

    r_vec = np.asarray(position_m, dtype=float)
    v_vec = np.asarray(velocity_m_s, dtype=float)
    if r_vec.shape != (3,) or v_vec.shape != (3,):
        raise ValueError("position_m and velocity_m_s must have shape (3,)")
    if not np.all(np.isfinite(r_vec)) or not np.all(np.isfinite(v_vec)):
        raise ValueError("state must contain only finite values")
    if mu_m3_s2 <= 0.0:
        raise ValueError("mu_m3_s2 must be positive")

    radius = np.linalg.norm(r_vec)
    speed2 = float(np.dot(v_vec, v_vec))
    if radius == 0.0:
        raise ValueError("position vector must be non-zero")
    h_vec = np.cross(r_vec, v_vec)
    h = np.linalg.norm(h_vec)
    if h == 0.0:
        raise ValueError("radial states do not define classical elements")
    n_vec = np.cross(np.array([0.0, 0.0, 1.0]), h_vec)
    n = np.linalg.norm(n_vec)
    e_vec = np.cross(v_vec, h_vec) / mu_m3_s2 - r_vec / radius
    eccentricity = float(np.linalg.norm(e_vec))
    specific_energy = 0.5 * speed2 - mu_m3_s2 / radius
    if specific_energy >= 0.0 or eccentricity >= 1.0:
        raise ValueError("only elliptic states are currently supported")
    semi_major_axis = -mu_m3_s2 / (2.0 * specific_energy)
    inclination = float(np.arccos(np.clip(h_vec[2] / h, -1.0, 1.0)))

    circular = eccentricity <= singularity_tolerance
    equatorial = n / h <= singularity_tolerance
    if equatorial:
        raan = 0.0
    else:
        raan = float(np.arctan2(n_vec[1], n_vec[0]) % TWOPI)

    if circular and equatorial:
        argument_of_periapsis = 0.0
        direction = 1.0 if h_vec[2] >= 0.0 else -1.0
        anomaly = float((direction * np.arctan2(r_vec[1], r_vec[0])) % TWOPI)
    elif circular:
        argument_of_periapsis = 0.0
        anomaly = _signed_angle(n_vec, r_vec, h_vec)
    elif equatorial:
        direction = 1.0 if h_vec[2] >= 0.0 else -1.0
        argument_of_periapsis = float(
            (direction * np.arctan2(e_vec[1], e_vec[0])) % TWOPI
        )
        anomaly = _signed_angle(e_vec, r_vec, h_vec)
    else:
        argument_of_periapsis = _signed_angle(n_vec, e_vec, h_vec)
        anomaly = _signed_angle(e_vec, r_vec, h_vec)

    return ClassicalElements(
        semi_major_axis,
        eccentricity,
        inclination,
        raan,
        argument_of_periapsis,
        anomaly,
        epoch,
    )
