"""Independent analytic references of test case HT-003 (解析解对比).

Closed-form solutions of the three analytic cases, written from the node balances of thermal design 4.3 T3 for one
node, for the chain J -> C -> R and for a radiator with a fixed input power and its own surface radiation. Nothing
here imports the thermal package or sdtwin_sim: only math, NumPy and SciPy's Brent root finder are used, so the
references are independent of the code under test.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import brentq

# ------------------------------------------------------------------------------------------------ single-node step


def step_response_K(
    time_s: ArrayLike,
    *,
    step_time_s: float,
    sink_temperature_K: float,
    power_W: float,
    resistance_K_W: float,
    capacitance_J_K: float,
) -> NDArray[np.float64]:
    """Temperature of a node with capacitance C joined by R to a sink held at T_sink, power stepping 0 -> P at t_s.

    C dT/dt = P H(t - t_s) - (T - T_sink) / R with T = T_sink before the step gives
    T(t) = T_sink for t < t_s and T(t) = T_sink + P R (1 - exp(-(t - t_s) / (R C))) for t >= t_s.
    ``-expm1`` keeps full precision of 1 - exp(-x) for small x.
    """

    t = np.asarray(time_s, dtype=float)
    tau = resistance_K_W * capacitance_J_K
    elapsed = np.clip(t - step_time_s, 0.0, None)
    return sink_temperature_K + power_W * resistance_K_W * (-np.expm1(-elapsed / tau))


def heat_sink_drift_bound_K(power_W: float, duration_s: float, capacitance_J_K: float) -> float:
    """Upper bound of the temperature change of a heat sink that receives at most ``power_W`` for ``duration_s``."""

    return power_W * duration_s / capacitance_J_K


def heat_sink_drift_step_K(
    *, power_W: float, resistance_K_W: float, capacitance_node_J_K: float, capacitance_sink_J_K: float, elapsed_s: float
) -> float:
    """Heat-sink change after a 0 -> P step when the sink takes q = P (1 - exp(-t / tau)) (first order in 1 / C_sink).

    Integral of q over [0, t] is P (t - tau (1 - exp(-t / tau))) with tau = R C_node.
    """

    tau = resistance_K_W * capacitance_node_J_K
    energy_J = power_W * (elapsed_s - tau * (-math.expm1(-elapsed_s / tau)))
    return energy_J / capacitance_sink_J_K


# ------------------------------------------------------------------------------------------------ two-node series


def series_constants(*, C_J: float, C_C: float, R_JC: float, R_CR: float, power_W: float) -> dict[str, Any]:
    """Matrix, eigenvalues, time constants and steady temperature differences of the chain J -> C -> R.

    With x = (T_J - T_R, T_C - T_R) and T_R constant:
    C_J dx_J/dt = P - (x_J - x_C) / R_JC and C_C dx_C/dt = (x_J - x_C) / R_JC - x_C / R_CR, i.e. dx/dt = A x + b.
    The steady state is x_ss = (P (R_JC + R_CR), P R_CR): the full power crosses both resistances in series.
    """

    a11 = -1.0 / (C_J * R_JC)
    a12 = 1.0 / (C_J * R_JC)
    a21 = 1.0 / (C_C * R_JC)
    a22 = -(1.0 / R_JC + 1.0 / R_CR) / C_C
    trace = a11 + a22
    determinant = a11 * a22 - a12 * a21
    discriminant = trace * trace - 4.0 * determinant
    if not discriminant > 0.0:
        raise ValueError(f"the chain must have two distinct real eigenvalues, discriminant {discriminant!r}")
    root = math.sqrt(discriminant)
    slow = 0.5 * (trace + root)
    fast = 0.5 * (trace - root)
    return {
        "A": np.array([[a11, a12], [a21, a22]]),
        "b": np.array([power_W / C_J, 0.0]),
        "eigenvalues_1_s": (slow, fast),
        "time_constants_s": (-1.0 / slow, -1.0 / fast),
        "steady_dT_JR_K": power_W * (R_JC + R_CR),
        "steady_dT_CR_K": power_W * R_CR,
    }


def series_response_K(
    time_s: ArrayLike,
    *,
    C_J: float,
    C_C: float,
    R_JC: float,
    R_CR: float,
    power_W: float,
    T_R_K: float,
    T_J0_K: float,
    T_C0_K: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """T_J(t) and T_C(t) of the chain with constant power P from t = 0 and the radiator held at T_R.

    x(t) = x_ss + exp(A t) (x(0) - x_ss); for the 2 x 2 matrix A with distinct eigenvalues l1, l2 Sylvester's formula
    gives exp(A t) = exp(l1 t) (A - l2 I) / (l1 - l2) + exp(l2 t) (A - l1 I) / (l2 - l1).
    """

    constants = series_constants(C_J=C_J, C_C=C_C, R_JC=R_JC, R_CR=R_CR, power_W=power_W)
    A = constants["A"]
    slow, fast = constants["eigenvalues_1_s"]
    identity = np.eye(2)
    E_slow = (A - fast * identity) / (slow - fast)
    E_fast = (A - slow * identity) / (fast - slow)
    x_ss = np.array([constants["steady_dT_JR_K"], constants["steady_dT_CR_K"]])
    x0 = np.array([T_J0_K - T_R_K, T_C0_K - T_R_K])
    deviation = x0 - x_ss
    t = np.asarray(time_s, dtype=float)
    x = (
        x_ss[None, :]
        + np.exp(slow * t)[:, None] * (E_slow @ deviation)[None, :]
        + np.exp(fast * t)[:, None] * (E_fast @ deviation)[None, :]
    )
    return T_R_K + x[:, 0], T_R_K + x[:, 1]


# ------------------------------------------------------------------------------------------------ radiation balance


def absorbed_direct_power_W(absorptivity: float, G_W_m2: float, area_m2: float, cos_incidence: float) -> float:
    """Direct sunlight absorbed by one surface: alpha G max(0, cos) A (hand calculation of the fixed input power)."""

    return absorptivity * G_W_m2 * max(0.0, cos_incidence) * area_m2


def radiation_equilibrium_K(power_W: float, emissivity: float, area_m2: float, sigma: float) -> float:
    """Steady temperature of a node with input P and emission eps sigma A T^4: T^4 = P / (eps sigma A)."""

    return (power_W / (emissivity * sigma * area_m2)) ** 0.25


def radiation_time_constant_s(capacitance_J_K: float, emissivity: float, area_m2: float, sigma: float,
                              temperature_K: float) -> float:
    """Linearised time constant C / (4 eps sigma A T^3) of the radiation balance at ``temperature_K``."""

    return capacitance_J_K / (4.0 * emissivity * sigma * area_m2 * temperature_K**3)


def _radiation_F(T: float, a: float) -> float:
    """Antiderivative of 1 / (a^4 - T^4): [ln|(a + T)/(a - T)| + 2 atan(T / a)] / (4 a^3)."""

    return (math.log(abs((a + T) / (a - T))) + 2.0 * math.atan(T / a)) / (4.0 * a**3)


def radiation_response_K(
    time_s: ArrayLike,
    *,
    capacitance_J_K: float,
    power_W: float,
    emissivity: float,
    area_m2: float,
    sigma: float,
    T0_K: float,
) -> NDArray[np.float64]:
    """T(t) of C dT/dt = P - k T^4, k = eps sigma A, from T(0) = T0.

    Separation of variables gives the implicit closed form F(T) - F(T0) = k t / C with the antiderivative F of
    1 / (a^4 - T^4), a^4 = P / k. Each time is solved for T with Brent's method on the side of the equilibrium a where
    T0 lies; when T is closer to a than 1e-13 a (beyond about 30 time constants) the value a is returned.
    """

    k = emissivity * sigma * area_m2
    a = (power_W / k) ** 0.25
    if T0_K == a:
        return np.full(np.shape(time_s), a)
    F0 = _radiation_F(T0_K, a)
    edge = a * (1.0 + 1e-13) if T0_K > a else a * (1.0 - 1e-13)
    values = []
    for moment in np.atleast_1d(np.asarray(time_s, dtype=float)):
        if moment <= 0.0:
            values.append(T0_K)
            continue
        target = F0 + k * moment / capacitance_J_K

        def residual(T: float, target: float = target) -> float:
            return _radiation_F(T, a) - target

        # F decreases with T above a and increases below a; on both sides F grows to +infinity towards a, while
        # residual(T0) = -k t / C < 0. A negative residual at the edge means T lies between the edge and a.
        near = residual(edge)
        if near < 0.0:
            values.append(a)
            continue
        low, high = (edge, T0_K) if T0_K > a else (T0_K, edge)
        values.append(brentq(residual, low, high, xtol=1e-12, rtol=4.0 * np.finfo(float).eps, maxiter=500))
    result = np.array(values, dtype=float)
    return result if np.ndim(time_s) else result[0]
