"""Independent reference calculations of test case EN-001 (thermal design 5.3 and 6.1).

Written by hand for the test from textbook formulas. This file imports neither the thermal package, nor sdtwin_sim,
nor scipy.spatial.transform, so it cannot share a defect with the module under test.

Conventions of design 5.3: quaternions are scalar-last (x, y, z, w) and describe the active body-to-GCRS rotation,
so a body-frame normal n becomes R(q) n in GCRS. The satellite-to-Sun direction is the Earth-to-Sun vector minus the
satellite position, normalized; cos_incidence is the dot product of the rotated normal with that direction.
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np


def unit(vector) -> np.ndarray:
    """Vector divided by its Euclidean length."""

    v = np.asarray(vector, dtype=float)
    return v / math.sqrt(float(v @ v))


def sun_direction(position_m, sun_position_m) -> np.ndarray:
    """Satellite-to-Sun unit vector: (Earth-to-Sun vector minus satellite position) / its length."""

    return unit(np.asarray(sun_position_m, dtype=float) - np.asarray(position_m, dtype=float))


def quat_to_matrix(q) -> np.ndarray:
    """Active rotation matrix of a unit quaternion (x, y, z, w), the standard Hamilton formula."""

    x, y, z, w = (float(v) for v in q)
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ]
    )


def quat_multiply(p, q) -> np.ndarray:
    """Hamilton product p * q in scalar-last order, so that R(p * q) = R(p) R(q)."""

    px, py, pz, pw = (float(v) for v in p)
    qx, qy, qz, qw = (float(v) for v in q)
    return np.array(
        [
            pw * qx + qw * px + py * qz - pz * qy,
            pw * qy + qw * py + pz * qx - px * qz,
            pw * qz + qw * pz + px * qy - py * qx,
            pw * qw - px * qx - py * qy - pz * qz,
        ]
    )


def axis_angle_quat(axis, angle_rad: float) -> np.ndarray:
    """Unit quaternion (x, y, z, w) of a rotation by ``angle_rad`` about ``axis``."""

    a = unit(axis)
    half = 0.5 * float(angle_rad)
    s = math.sin(half)
    return np.array([a[0] * s, a[1] * s, a[2] * s, math.cos(half)])


def elementary_matrix(axis: str, angle_rad: float) -> np.ndarray:
    """Active rotation matrix about one coordinate axis, written out by hand."""

    c, s = math.cos(angle_rad), math.sin(angle_rad)
    if axis == "x":
        return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    if axis == "y":
        return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    if axis == "z":
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    raise ValueError(f"axis must be 'x', 'y' or 'z', got {axis!r}")


def rodrigues_rotate(q, vectors) -> np.ndarray:
    """Rotate each row of ``vectors`` by the axis and angle encoded in the unit quaternion q (Rodrigues' formula).

    v' = v cos(theta) + (k x v) sin(theta) + k (k . v) (1 - cos(theta)), with k = vector part / its length and
    theta = 2 atan2(|vector part|, w). No rotation matrix is formed.
    """

    x, y, z, w = (float(v) for v in q)
    vector_part = np.array([x, y, z])
    length = math.sqrt(float(vector_part @ vector_part))
    v = np.atleast_2d(np.asarray(vectors, dtype=float))
    if length == 0.0:
        return v.copy()
    k = vector_part / length
    theta = 2.0 * math.atan2(length, w)
    c, s = math.cos(theta), math.sin(theta)
    return v * c + np.cross(k, v) * s + np.outer(v @ k, k) * (1.0 - c)


def matrix_to_quat(m) -> np.ndarray:
    """Unit quaternion (x, y, z, w) of a proper rotation matrix by Shepperd's method.

    The columns of ``m`` are the body axes expressed in GCRS, so quat_to_matrix of the result reproduces ``m``.
    """

    m = np.asarray(m, dtype=float)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0.0:
        s = 2.0 * math.sqrt(trace + 1.0)
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = 2.0 * math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    return unit(q)


def sun_nadir_axes(position_m, sun_position_m) -> np.ndarray:
    """Body axes of the Sun-nadir attitude as matrix columns.

    Body +Z points to the local zenith (so the -Z face looks at nadir) and body +X is the satellite-to-Sun
    direction projected on the local horizontal plane, so the solar array front (+X) faces the Sun as far as the
    nadir constraint allows. Body +Y completes the right-handed set.
    """

    z_axis = unit(position_m)
    s_hat = sun_direction(position_m, sun_position_m)
    horizontal = s_hat - float(s_hat @ z_axis) * z_axis
    horizontal = horizontal - float(horizontal @ z_axis) * z_axis  # second Gram-Schmidt pass near the subsolar point
    x_axis = unit(horizontal)
    y_axis = np.cross(z_axis, x_axis)
    return np.column_stack([x_axis, y_axis, z_axis])


def sun_nadir_expected_cos(position_m, sun_position_m, normals_body) -> np.ndarray:
    """Hand-derived cos_incidence of the Sun-nadir attitude, without any rotation matrix or quaternion.

    With c = s . zenith and p = |s - c zenith| (the horizontal part of the Sun direction), the Sun direction is
    p X_body + c Z_body, so a body normal (nx, ny, nz) gives cos_incidence = p nx + c nz.
    """

    zenith = unit(position_m)
    s_hat = sun_direction(position_m, sun_position_m)
    c = float(s_hat @ zenith)
    horizontal = s_hat - c * zenith
    p = math.sqrt(float(horizontal @ horizontal))
    n = np.asarray(normals_body, dtype=float)
    return p * n[:, 0] + c * n[:, 2]


def conical_shadow(position_m, sun_position_m, earth_radius_m: float, sun_radius_m: float) -> str:
    """'sunlit', 'penumbra' or 'umbra' from the apparent radii of Earth and Sun seen from the satellite.

    Sunlit when the angular separation of the two disc centres is at least the sum of the apparent radii, umbra
    when the Earth disc covers the whole solar disc, penumbra otherwise.
    """

    r = np.asarray(position_m, dtype=float)
    to_sun = np.asarray(sun_position_m, dtype=float) - r
    to_earth = -r
    d_sun = math.sqrt(float(to_sun @ to_sun))
    d_earth = math.sqrt(float(to_earth @ to_earth))
    rho_sun = math.asin(sun_radius_m / d_sun)
    rho_earth = math.asin(earth_radius_m / d_earth)
    separation = math.acos(max(-1.0, min(1.0, float(to_sun @ to_earth) / (d_sun * d_earth))))
    if separation >= rho_earth + rho_sun:
        return "sunlit"
    if separation <= rho_earth - rho_sun:
        return "umbra"
    return "penumbra"


def parse_fraction(text) -> float:
    """Exact rational from a string such as '3/7' or '-0.6', returned as the nearest float."""

    return float(Fraction(str(text)))
