"""Classical orbital elements <-> Cartesian state (the NTU orbit-dynamics
module's OE/RV layer, ported km-native and dependency-free).

Conventions follow `Orbit/src/ntu_space_dynamics/orbits/elements.py` (the
module the SDCTwin test report CV-001/CV-002 verifies):

* anomaly is the TRUE anomaly;
* angles are radians in [0, 2*pi) internally (degree helpers at the edges);
* singular cases are resolved deterministically, never left NaN:
    - circular (e <= tol):            argp = 0, anomaly = argument of latitude
    - equatorial (|n|/|h| <= tol):    raan = 0, argp = longitude of periapsis
                                      (measured with direction = sign(h_z),
                                      so retrograde equatorial stays exact)
    - circular equatorial:            raan = argp = 0, anomaly = true longitude
* only bound elliptical orbits are supported (0 <= e < 1, specific energy < 0);
  radial (|h| ~ 0) states are rejected.

Validated by tools/validate_elements.py at the NTU acceptance tolerances
(round-trip position 1e-9 km / velocity 1e-12 km/s incl. singular cases).
"""

from __future__ import annotations

import math

MU_EARTH_KM3_S2 = 398600.4418
_SING_TOL = 1e-10
_TWO_PI = 2.0 * math.pi


def _wrap(angle: float) -> float:
    a = angle % _TWO_PI
    return a + _TWO_PI if a < 0.0 else a


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _angle_about(axis_unit, v_from, v_to) -> float:
    """Signed angle from v_from to v_to around axis_unit, wrapped [0, 2pi).
    atan2 of the (sin, cos) pair — stable where arccos is not."""
    s = _dot(_cross(v_from, v_to), axis_unit)
    c = _dot(v_from, v_to)
    return _wrap(math.atan2(s, c))


def oe_to_rv(a_km: float, e: float, inc_rad: float, raan_rad: float,
             argp_rad: float, nu_rad: float,
             mu: float = MU_EARTH_KM3_S2):
    """Classical elements -> (r_km, v_km_s) tuples in the inertial frame."""
    if a_km <= 0.0:
        raise ValueError("semi-major axis must be positive (elliptic only)")
    if not 0.0 <= e < 1.0:
        raise ValueError("eccentricity must be in [0, 1)")
    p = a_km * (1.0 - e * e)
    denom = 1.0 + e * math.cos(nu_rad)
    if denom <= 0.0:
        raise ValueError("true anomaly outside the elliptic branch")
    r_mag = p / denom
    cos_nu, sin_nu = math.cos(nu_rad), math.sin(nu_rad)
    # perifocal
    r_pf = (r_mag * cos_nu, r_mag * sin_nu, 0.0)
    vf = math.sqrt(mu / p)
    v_pf = (-vf * sin_nu, vf * (e + cos_nu), 0.0)
    # R3(-raan) R1(-i) R3(-argp)
    cO, sO = math.cos(raan_rad), math.sin(raan_rad)
    ci, si = math.cos(inc_rad), math.sin(inc_rad)
    cw, sw = math.cos(argp_rad), math.sin(argp_rad)
    row1 = (cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si)
    row2 = (sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si)
    row3 = (sw * si, cw * si, ci)
    def rot(v):
        return (_dot(row1, v), _dot(row2, v), _dot(row3, v))
    return rot(r_pf), rot(v_pf)


def rv_to_oe(r_km, v_km_s, mu: float = MU_EARTH_KM3_S2) -> dict:
    """Cartesian state -> classical elements dict (radians).

    Keys: a_km, e, inc_rad, raan_rad, argp_rad, nu_rad. Raises on radial or
    non-elliptic states."""
    r_mag = _norm(r_km)
    v_mag = _norm(v_km_s)
    if r_mag <= 0.0:
        raise ValueError("zero position vector")
    h = _cross(r_km, v_km_s)
    h_mag = _norm(h)
    if h_mag <= 1e-12 * r_mag * max(v_mag, 1e-12):
        raise ValueError("radial trajectory: angular momentum ~ 0")
    energy = 0.5 * v_mag * v_mag - mu / r_mag
    if energy >= 0.0:
        raise ValueError("state is not a bound elliptic orbit")
    a_km = -mu / (2.0 * energy)

    rv = _dot(r_km, v_km_s)
    e_vec = tuple(((v_mag * v_mag - mu / r_mag) * r_km[k] - rv * v_km_s[k]) / mu
                  for k in range(3))
    e = _norm(e_vec)
    if e >= 1.0:
        raise ValueError("eccentricity >= 1 despite negative energy")

    h_unit = tuple(c / h_mag for c in h)
    inc = math.acos(max(-1.0, min(1.0, h[2] / h_mag)))
    n = (-h[1], h[0], 0.0)                 # node vector = z_hat x h
    n_mag = _norm(n)

    circular = e <= _SING_TOL
    equatorial = (n_mag / h_mag) <= _SING_TOL
    # retrograde equatorial orbits measure in-plane angles the opposite way
    direction = 1.0 if h[2] >= 0.0 else -1.0

    if circular and equatorial:
        raan = 0.0
        argp = 0.0
        nu = _wrap(direction * math.atan2(r_km[1], r_km[0]))
    elif circular:
        raan = _wrap(math.atan2(n[1], n[0]))
        argp = 0.0
        nu = _angle_about(h_unit, n, r_km)          # argument of latitude
    elif equatorial:
        raan = 0.0
        argp = _wrap(direction * math.atan2(e_vec[1], e_vec[0]))
        nu = _angle_about(h_unit, e_vec, r_km)
    else:
        raan = _wrap(math.atan2(n[1], n[0]))
        argp = _angle_about(h_unit, n, e_vec)
        nu = _angle_about(h_unit, e_vec, r_km)

    return {"a_km": a_km, "e": e, "inc_rad": inc,
            "raan_rad": raan, "argp_rad": argp, "nu_rad": nu}


def period_s(a_km: float, mu: float = MU_EARTH_KM3_S2) -> float:
    return _TWO_PI * math.sqrt(a_km ** 3 / mu)
