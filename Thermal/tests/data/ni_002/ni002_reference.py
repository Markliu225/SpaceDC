"""Independent references of test case NI-002, written without the code under test.

* ``circular_position``: analytic circular two-body orbit (Kepler, e = 0) from the classical elements; it does not use
  the Orbit propagator nor the interpolation of the coupled environment provider.
* ``SunTable``: Earth-to-Sun vectors from Orbit's ``sun_position_ephemeris`` (builtin) at fixed nodes, interpolated
  linearly by this module.
* ``shadow_crossings``: entry and exit times of the cylindrical Earth shadow, scanned and bisected by this module. The
  conical penumbra of Orbit's ``eclipse_fraction`` begins before and ends after the cylindrical shadow; the cylindrical
  boundary lies between the penumbra and umbra boundaries of the same crossing.
* ``DOPRI5_B``: the fifth-order weights of the Dormand-Prince pair (Dormand and Prince 1980, the method behind SciPy
  ``RK45``), written from the published table; ``rk45_update`` and ``rk45_dense`` rebuild a step result from the stage
  derivatives in the same arithmetic order as SciPy so that the comparison can be bit for bit.
* ``heat_flows`` and ``balance_terms``: T2 and the T3 terms of every node from temperatures, ports and absorbed and
  emitted powers, written from the design equations.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np

NODES = ("S", "J", "C", "B", "D", "R")  # design 1.4
PATHS = (("SR", "S", "R"), ("JC", "J", "C"), ("CR", "C", "R"), ("BR", "B", "R"), ("DR", "D", "R"))  # design 4.2

# Dormand-Prince 5(4) fifth-order weights b_i (Dormand and Prince 1980, table 2); b_2 = 0, b_7 = 0 (FSAL stage).
DOPRI5_B = np.array([35.0 / 384.0, 0.0, 500.0 / 1113.0, 125.0 / 192.0, -2187.0 / 6784.0, 11.0 / 84.0])
# Stage abscissae c_2 ... c_6 of the same table.
DOPRI5_C = (1.0 / 5.0, 3.0 / 10.0, 4.0 / 5.0, 8.0 / 9.0, 1.0)


def circular_position(time_s: float, *, radius_m: float, mu_m3_s2: float, inclination_deg: float, raan_deg: float,
                      argument_of_latitude0_deg: float) -> np.ndarray:
    """GCRS position of a circular orbit: r = R3(-raan) R1(-i) [a cos u, a sin u, 0], u = u0 + n t."""

    n = math.sqrt(mu_m3_s2 / radius_m ** 3)
    u = math.radians(argument_of_latitude0_deg) + n * time_s
    i = math.radians(inclination_deg)
    o = math.radians(raan_deg)
    x_p, y_p = radius_m * math.cos(u), radius_m * math.sin(u)
    # rotate by the inclination about x, then by the right ascension of the ascending node about z
    x1, y1, z1 = x_p, y_p * math.cos(i), y_p * math.sin(i)
    return np.array([x1 * math.cos(o) - y1 * math.sin(o), x1 * math.sin(o) + y1 * math.cos(o), z1])


class SunTable:
    """Earth-to-Sun vectors at fixed nodes, linearly interpolated; the nodes come from Orbit's ephemeris."""

    def __init__(self, times_s: Sequence[float], vectors_m: Sequence[Sequence[float]]) -> None:
        self.times = np.asarray(times_s, dtype=float)
        self.vectors = np.asarray(vectors_m, dtype=float)

    def __call__(self, time_s: float) -> np.ndarray:
        return np.array([np.interp(time_s, self.times, self.vectors[:, k]) for k in range(3)])


def in_cylindrical_shadow(position_m: np.ndarray, sun_m: np.ndarray, earth_radius_m: float) -> bool:
    """True behind the Earth inside the cylinder of radius R along the Sun direction."""

    s_hat = sun_m / np.linalg.norm(sun_m)
    along = float(position_m @ s_hat)
    if along >= 0.0:
        return False
    perpendicular = position_m - along * s_hat
    return float(np.linalg.norm(perpendicular)) < earth_radius_m


def shadow_crossings(shadow: Callable[[float], bool], t0_s: float, t1_s: float, *, scan_step_s: float,
                     resolution_s: float = 1e-6) -> tuple[list[float], list[float]]:
    """Entry and exit times of a boolean shadow function, scanned every ``scan_step_s`` and bisected."""

    entries: list[float] = []
    exits: list[float] = []
    times = np.arange(t0_s, t1_s, scan_step_s).tolist() + [t1_s]
    previous_t, previous = times[0], shadow(times[0])
    for moment in times[1:]:
        current = shadow(moment)
        if current != previous:
            low, high = previous_t, moment
            while high - low > resolution_s:
                middle = 0.5 * (low + high)
                if shadow(middle) == previous:
                    low = middle
                else:
                    high = middle
            (entries if current else exits).append(high)
        previous_t, previous = moment, current
    return entries, exits


def rk45_update(y_old: np.ndarray, h: float, stages: np.ndarray, weights: np.ndarray = DOPRI5_B) -> np.ndarray:
    """y_new = y_old + h * K^T b with the six stage derivatives K (rows), in SciPy's arithmetic order."""

    return y_old + h * np.dot(stages.T, weights)


def rk45_dense(time_s: float, t_old: float, t_new: float, y_old: np.ndarray, stages7: np.ndarray,
               dense_matrix: np.ndarray) -> np.ndarray:
    """Continuous extension of an accepted step: y_old + h Q p(x), Q = K^T P, p = (x, x^2, x^3, x^4)."""

    h = t_new - t_old
    q = stages7.T.dot(dense_matrix)
    x = (np.asarray(time_s) - t_old) / h
    p = np.cumprod(np.tile(x, q.shape[1]))
    y = h * np.dot(q, p)
    y += y_old
    return y


def heat_flows(temperature_K: Sequence[float], resistance_K_W: dict[str, float]) -> dict[str, float]:
    """T2: q_ij = (T_i - T_j) / R_ij for the five paths."""

    t = dict(zip(NODES, (float(v) for v in temperature_K), strict=True))
    return {path: (t[first] - t[second]) / resistance_K_W[path] for path, first, second in PATHS}


def balance_terms(q: dict[str, float], ports: dict[str, float], q_env: tuple[float, float],
                  q_emit: tuple[float, float]) -> dict[str, tuple[float, ...]]:
    """T3: the signed power terms of every node; their sum is C_i dT_i/dt."""

    return {
        "S": (q_env[0], -ports["P_pv_W"], -q["SR"], -q_emit[0]),
        "J": (ports["P_load_W"], -q["JC"]),
        "C": (q["JC"], -q["CR"]),
        "B": (ports["Q_B_W"], -q["BR"]),
        "D": (ports["Q_D_W"], -q["DR"]),
        "R": (q["SR"], q["CR"], q["BR"], q["DR"], q_env[1], -q_emit[1]),
    }
