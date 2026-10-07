"""NI-001 support code: FE-001 mean environment geometry, Earth-flux input table and independent references.

Nothing in this file imports the module under test (``thermal``) or ``sdtwin_sim``. It provides:

* ``FEOrbit``: the FE orbit functions of ``iss_fem/out/<case>/summary.json`` (circular orbit from orbit noon), the
  parallel-ray Sun direction ``sun_ecs``, the cylindrical Earth shadow of the FE, the sun-pointing attitude of the
  FE-001 case (body +Z, the front normal of the solar array, points at the Sun) and the closed-form shadow windows.
  The formulas are those of ``tests/data/fe_001/fe001_support.py``, written out again so that NI-001 does not depend on
  another case's helper file.
* ``EarthFluxTable``: a cubic spline of Earth albedo and infrared surface irradiances sampled at a declared spacing
  (thermal design table 8: synchronized environment values, declared interpolation on continuous intervals). The
  samples are computed by the test; this class only interpolates them.
* ``ReferenceModel``: hand implementation of T2, T3, T4 and T5 of the thermal design for the NI-001 scenario, with the
  eclipse phase and the computing load held constant on each segment between closed-form boundaries.
* ``integrate_rk4``: integration of the reference model on the closed-form segments with a classical fixed-step
  fourth order Runge-Kutta method written here, independent of SciPy's integrators; step halving bounds its error.
* ``DP45``: the Dormand-Prince 5(4) tableau (J. R. Dormand and P. J. Prince, A family of embedded Runge-Kutta formulae,
  J. Comput. Appl. Math. 6 (1980) 19-26) and ``dp45_attempt``, which predicts the error norm of one RK45 attempt so
  that a step that must be rejected can be chosen before the run.
* Number formatting for the Chinese summary.
"""

from __future__ import annotations

import json
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.spatial.transform import Rotation

# Stefan-Boltzmann constant of thermal design table 5, for the hand reference only.
SIGMA_W_M2_K4 = 5.670374419e-8
# IAU 2012 astronomical unit in m; the FE uses parallel rays along sun_ecs, the Earth-to-Sun vector is sun_ecs * AU.
AU_M = 1.495978707e11
NODES = ("S", "J", "C", "B", "D", "R")
PATHS = ("SR", "JC", "CR", "BR", "DR")
PATH_ENDS = {"SR": ("S", "R"), "JC": ("J", "C"), "CR": ("C", "R"), "BR": ("B", "R"), "DR": ("D", "R")}
MINUS = "−"
_NUM = r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------- FE orbit


class FEOrbit:
    """Orbit, Sun, cylindrical shadow and sun-pointing attitude of one FE case (orbit record of ``summary.json``)."""

    def __init__(self, orbit_record: dict, earth_radius_m: float, au_m: float = AU_M) -> None:
        funcs = orbit_record["funcs"]
        rx = funcs["rx"].replace(" ", "")
        ry = funcs["ry"].replace(" ", "")
        rz = funcs["rz"].replace(" ", "")
        mx = re.fullmatch(rf"{_NUM}\*cos\(\(2\*pi\*t/{_NUM}\+{_NUM}\)\)", rx)
        my = re.fullmatch(rf"{_NUM}\*sin\(\(2\*pi\*t/{_NUM}\+{_NUM}\)\)\*cos\({_NUM}\)", ry)
        mz = re.fullmatch(rf"{_NUM}\*sin\(\(2\*pi\*t/{_NUM}\+{_NUM}\)\)\*sin\({_NUM}\)", rz)
        if not (mx and my and mz):
            raise ValueError(f"FE orbit functions have an unexpected form: {funcs!r}")
        radius, period, phase = (float(value) for value in mx.groups())
        for match in (my, mz):
            values = tuple(float(value) for value in match.groups())
            if values[:3] != (radius, period, phase):
                raise ValueError(f"FE orbit functions disagree on radius, period or phase: {funcs!r}")
        if float(my.group(4)) != float(mz.group(4)):
            raise ValueError(f"FE orbit functions disagree on the inclination: {funcs!r}")
        self.radius_m = radius
        self.period_s = period
        self.phase_rad = phase
        self.inclination_rad = float(my.group(4))
        self.summary_radius_m = float(orbit_record["R"])
        self.summary_period_s = float(orbit_record["period"])
        sun = np.array(orbit_record["sun_ecs"], dtype=float)
        self.sun_hat = sun / np.linalg.norm(sun)
        self.earth_radius_m = float(earth_radius_m)
        self.au_m = float(au_m)
        ci, si = math.cos(self.inclination_rad), math.sin(self.inclination_rad)
        self.p = np.array([1.0, 0.0, 0.0])
        self.q = np.array([0.0, ci, si])
        self.h = np.cross(self.p, self.q)  # orbit normal, direction of r x v

    def angle(self, t: float) -> float:
        return 2.0 * math.pi * t / self.period_s + self.phase_rad

    def position(self, t: float) -> np.ndarray:
        u = self.angle(t)
        return self.radius_m * (math.cos(u) * self.p + math.sin(u) * self.q)

    def sun_position(self, t: float) -> np.ndarray:
        return self.au_m * self.sun_hat

    def sun_direction(self, t: float) -> np.ndarray:
        """Unit vector from the satellite to the Sun."""

        vector = self.sun_position(t) - self.position(t)
        return vector / np.linalg.norm(vector)

    def beta_deg(self) -> float:
        return math.degrees(math.asin(float(np.clip(self.sun_hat @ self.h, -1.0, 1.0))))

    def in_shadow(self, t: float) -> bool:
        """Cylindrical shadow of the FE: behind the Earth and closer to the Sun line than the Earth radius."""

        r = self.position(t)
        along = float(r @ self.sun_hat)
        perpendicular2 = float(r @ r) - along * along
        return along < 0.0 and perpendicular2 < self.earth_radius_m**2

    def eclipse_windows(self, t0: float, t1: float) -> list[tuple[float, float]]:
        """Closed-form shadow intervals (entry, exit) that intersect [t0, t1].

        r.s = R A cos(u - u0) with A = |(p.s, q.s)| = cos(beta); the shadow is cos(u - u0) < -c with
        c = sqrt(1 - (R_E / R)^2) / A, so u - u0 lies in (pi - w, pi + w) with w = acos(c).
        """

        a, b = float(self.sun_hat @ self.p), float(self.sun_hat @ self.q)
        amplitude = math.hypot(a, b)
        u0 = math.atan2(b, a)
        c = math.sqrt(1.0 - (self.earth_radius_m / self.radius_m) ** 2) / amplitude
        if c >= 1.0:
            return []
        w = math.acos(c)
        scale = self.period_s / (2.0 * math.pi)
        windows = []
        k_low = math.floor((t0 / scale + self.phase_rad - u0 - math.pi - w) / (2.0 * math.pi)) - 1
        k_high = math.ceil((t1 / scale + self.phase_rad - u0 - math.pi + w) / (2.0 * math.pi)) + 1
        for k in range(k_low, k_high + 1):
            entry = (u0 + math.pi - w + 2.0 * math.pi * k - self.phase_rad) * scale
            exit_ = (u0 + math.pi + w + 2.0 * math.pi * k - self.phase_rad) * scale
            if exit_ > t0 and entry < t1:
                windows.append((entry, exit_))
        return windows

    def boundaries(self, t0: float, t1: float) -> list[tuple[float, str]]:
        """Closed-form eclipse entry and exit times strictly inside (t0, t1), in time order, with their kinds."""

        items = []
        for entry, exit_ in self.eclipse_windows(t0, t1):
            if t0 < entry < t1:
                items.append((entry, "sunlit_to_umbra"))
            if t0 < exit_ < t1:
                items.append((exit_, "umbra_to_sunlit"))
        return sorted(items)

    def axes(self, t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Body axes in GCRS: +Z to the Sun, +X along the orbit normal component across the Sun line, +Y = Z x X."""

        z_axis = self.sun_direction(t)
        x_axis = self.h - (self.h @ z_axis) * z_axis
        x_axis = x_axis / np.linalg.norm(x_axis)
        y_axis = np.cross(z_axis, x_axis)
        return x_axis, y_axis, z_axis

    def rotation(self, t: float) -> Rotation:
        """Active body-to-GCRS rotation of the sun-pointing attitude."""

        return Rotation.from_matrix(np.column_stack(self.axes(t)))

    def quaternion(self, t: float) -> np.ndarray:
        return self.rotation(t).as_quat()


# ------------------------------------------------------------------------------------------------- Earth flux table


class EarthFluxTable:
    """Cubic spline of Earth albedo and infrared irradiances per surface, sampled at a fixed spacing.

    ``times`` (n,) in s, ``albedo`` and ``infrared`` (n, m) in W/m^2 for the surfaces ``surface_ids`` in that order.
    Values are interpolated with a not-a-knot cubic spline and clipped at zero, because the irradiances are
    nonnegative and a cubic can undershoot next to an interval where a face sees no Earth.
    """

    def __init__(self, times: Sequence[float], surface_ids: Sequence[str], albedo: np.ndarray,
                 infrared: np.ndarray) -> None:
        self.times = np.asarray(times, dtype=float)
        self.surface_ids = tuple(surface_ids)
        self.albedo_samples = np.asarray(albedo, dtype=float)
        self.infrared_samples = np.asarray(infrared, dtype=float)
        m = len(self.surface_ids)
        if self.albedo_samples.shape != (self.times.size, m) or self.infrared_samples.shape != (self.times.size, m):
            raise ValueError("albedo and infrared samples must have shape (len(times), len(surface_ids))")
        self._spline = CubicSpline(self.times, np.hstack([self.albedo_samples, self.infrared_samples]), axis=0)
        self.m = m
        self.calls = 0

    @property
    def spacing_s(self) -> float:
        return float(np.max(np.diff(self.times)))

    def values(self, t: float) -> tuple[np.ndarray, np.ndarray]:
        if not self.times[0] <= t <= self.times[-1]:
            raise ValueError(f"time {t!r} s lies outside the Earth-flux table [{self.times[0]}, {self.times[-1]}] s")
        self.calls += 1
        both = np.maximum(self._spline(t), 0.0)
        return both[: self.m], both[self.m:]

    def provider_callable(self, name: str = "ni001_earth_flux_table") -> Callable[..., dict]:
        """``earth_flux`` callable for the coupled environment provider (run, time and surface ids passed through)."""

        surface_ids = self.surface_ids

        def earth_flux(run_id, time_s, position_m, sun_position_m, quaternion_xyzw, parameters) -> dict:
            albedo, infrared = self.values(float(time_s))
            albedo.setflags(write=False)
            infrared.setflags(write=False)
            return {"run_id": run_id, "time_s": float(time_s), "surface_ids": surface_ids,
                    "albedo_W_m2": albedo, "infrared_W_m2": infrared}

        earth_flux.__name__ = name
        earth_flux.__qualname__ = name
        return earth_flux


# ------------------------------------------------------------------------------------------------- reference model


class ReferenceModel:
    """Hand T2, T3, T4 and T5 of the NI-001 scenario (thermal design 4.2 to 4.5).

    ``capacitance_J_K`` and ``resistance_K_W`` map node and path names to values computed by hand from the scenario
    data; ``surfaces`` is a list of mappings with ``surface_id``, ``node``, ``area_m2``, ``normal_body``,
    ``absorptivity`` and ``emissivity``. The eclipse phase ``lit`` and the computing load ``load_W`` are segment
    constants, so the right-hand side never sees both sides of a discontinuity.
    """

    def __init__(self, *, capacitance_J_K: dict, resistance_K_W: dict, surfaces: list[dict], orbit: FEOrbit,
                 solar_constant_W_m2: float, pv_fraction: float, pv_area_m2: float, pv_surface_id: str,
                 earth: EarthFluxTable) -> None:
        self.C = np.array([float(capacitance_J_K[node]) for node in NODES])
        self.R = {path: float(resistance_K_W[path]) for path in PATHS}
        self.orbit = orbit
        self.S0 = float(solar_constant_W_m2)
        self.pv_fraction = float(pv_fraction)
        self.pv_area = float(pv_area_m2)
        self.earth = earth
        order = {surface_id: index for index, surface_id in enumerate(earth.surface_ids)}
        self.surface_index = np.array([order[surface["surface_id"]] for surface in surfaces], dtype=int)
        self.node_index = np.array([NODES.index(surface["node"]) for surface in surfaces], dtype=int)
        self.area = np.array([float(surface["area_m2"]) for surface in surfaces])
        self.normal = np.array([surface["normal_body"] for surface in surfaces], dtype=float)
        self.alpha = np.array([float(surface["absorptivity"]) for surface in surfaces])
        self.eps = np.array([float(surface["emissivity"]) for surface in surfaces])
        self.pv_row = [surface["surface_id"] for surface in surfaces].index(pv_surface_id)
        self.is_S = self.node_index == NODES.index("S")
        self.is_R = self.node_index == NODES.index("R")
        self.evaluations = 0

    def terms(self, t: float, T: np.ndarray, lit: bool, load_W: float) -> dict:
        """All T3 and T4 terms at one instant."""

        G = self.S0 if lit else 0.0
        x_axis, y_axis, z_axis = self.orbit.axes(t)
        sun = self.orbit.sun_direction(t)
        normals = (self.normal[:, 0:1] * x_axis + self.normal[:, 1:2] * y_axis + self.normal[:, 2:3] * z_axis)
        cosine = normals @ sun
        g_sun = G * np.maximum(cosine, 0.0)
        albedo, infrared = self.earth.values(t)
        albedo = albedo[self.surface_index]
        infrared = infrared[self.surface_index]
        T_owner = T[self.node_index]
        absorbed = self.area * (self.alpha * (g_sun + albedo) + self.eps * infrared)
        emitted = self.eps * SIGMA_W_M2_K4 * self.area * T_owner**4
        Q_env = np.array([absorbed[self.is_S].sum(), absorbed[self.is_R].sum()])
        Q_emit = np.array([emitted[self.is_S].sum(), emitted[self.is_R].sum()])
        P_pv = self.pv_fraction * self.pv_area * G * max(0.0, float(cosine[self.pv_row]))
        q = {path: (T[NODES.index(a)] - T[NODES.index(b)]) / self.R[path] for path, (a, b) in PATH_ENDS.items()}
        return {"G": G, "cos": cosine, "Q_env": Q_env, "Q_emit": Q_emit, "P_pv": P_pv, "P_load": float(load_W),
                "q": q}

    def rhs(self, t: float, T: np.ndarray, lit: bool, load_W: float) -> np.ndarray:
        self.evaluations += 1
        return self.rates(self.terms(t, T, lit, load_W))

    def rates(self, k: dict) -> np.ndarray:
        """T3: temperature derivatives in K/s from the terms of one instant."""

        q = k["q"]
        net = np.array([
            k["Q_env"][0] - k["P_pv"] - q["SR"] - k["Q_emit"][0],
            k["P_load"] - q["JC"],
            q["JC"] - q["CR"],
            0.0 - q["BR"],
            0.0 - q["DR"],
            q["SR"] + q["CR"] + q["BR"] + q["DR"] + k["Q_env"][1] - k["Q_emit"][1],
        ])
        return net / self.C


def reference_segments(orbit: FEOrbit, t0: float, t1: float, load_times: tuple[float, float],
                       load_W: float) -> list[dict]:
    """Segments between the closed-form eclipse boundaries and the load start and stop, with constant inputs."""

    cuts = sorted([time for time, _ in orbit.boundaries(t0, t1)] + [t for t in load_times if t0 < t < t1])
    edges = [t0] + cuts + [t1]
    on, off = load_times
    segments = []
    for a, b in zip(edges[:-1], edges[1:]):
        middle = 0.5 * (a + b)
        segments.append({"start": a, "end": b, "lit": not orbit.in_shadow(middle),
                         "load_W": float(load_W) if on <= middle < off else 0.0})
    return segments


def _targets(segment: dict, t_eval: np.ndarray) -> np.ndarray:
    inside = t_eval[(t_eval >= segment["start"]) & (t_eval <= segment["end"])]
    return inside


def integrate_rk4(model: ReferenceModel, segments: list[dict], y0: np.ndarray, t_eval: np.ndarray, *,
                  step_s: float) -> dict:
    """Classical fourth order Runge-Kutta method with steps of at most ``step_s`` that land on every requested
    time and on every segment end; written here, independent of SciPy's integrators.

    With requested times on whole seconds the steps also land on the 10 s knots of the Earth-flux spline, so each
    step sees a polynomial input; step halving measures the remaining error. A boundary instant takes the state at the
    end of the segment before it, which is the start state of the next one."""

    t_eval = np.asarray(t_eval, dtype=float)
    out = np.full((t_eval.size, len(NODES)), np.nan)
    y = np.array(y0, dtype=float)
    steps = 0
    for segment in segments:
        lit, load = segment["lit"], segment["load_W"]
        f = lambda t, T: model.rhs(t, T, lit, load)  # noqa: E731
        t = segment["start"]
        targets = np.unique(np.concatenate([_targets(segment, t_eval), [segment["end"]]]))
        for target in targets:
            if target > t:
                n = max(1, math.ceil((target - t) / step_s - 1e-9))
                h = (target - t) / n
                for _ in range(n):
                    k1 = f(t, y)
                    k2 = f(t + 0.5 * h, y + 0.5 * h * k1)
                    k3 = f(t + 0.5 * h, y + 0.5 * h * k2)
                    k4 = f(t + h, y + h * k3)
                    y = y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
                    t = t + h
                    steps += 1
                t = float(target)
            out[t_eval == target] = y
    return {"t": t_eval, "T": out, "final": y, "steps": steps}


# ------------------------------------------------------------------------------------------------- Dormand-Prince 5(4)


class DP45:
    """Dormand-Prince 5(4) tableau with the error weights E = b_hat - b of the embedded fourth order formula, in the
    FSAL form used by SciPy's RK45 (seven derivative rows, the last at t + h with the new state)."""

    C = [Fraction(0), Fraction(1, 5), Fraction(3, 10), Fraction(4, 5), Fraction(8, 9), Fraction(1)]
    A = [
        [],
        [Fraction(1, 5)],
        [Fraction(3, 40), Fraction(9, 40)],
        [Fraction(44, 45), Fraction(-56, 15), Fraction(32, 9)],
        [Fraction(19372, 6561), Fraction(-25360, 2187), Fraction(64448, 6561), Fraction(-212, 729)],
        [Fraction(9017, 3168), Fraction(-355, 33), Fraction(46732, 5247), Fraction(49, 176), Fraction(-5103, 18656)],
    ]
    B = [Fraction(35, 384), Fraction(0), Fraction(500, 1113), Fraction(125, 192), Fraction(-2187, 6784),
         Fraction(11, 84)]
    E = [Fraction(-71, 57600), Fraction(0), Fraction(71, 16695), Fraction(-71, 1920), Fraction(17253, 339200),
         Fraction(-22, 525), Fraction(1, 40)]

    @classmethod
    def consistency(cls) -> dict:
        """Exact rational checks: row sums equal C, the weights sum to one, the error weights sum to zero."""

        rows = all(sum(row, Fraction(0)) == c for row, c in zip(cls.A, cls.C))
        return {"row_sums_equal_c": rows, "sum_b": sum(cls.B, Fraction(0)), "sum_e": sum(cls.E, Fraction(0)),
                "stages": len(cls.C)}


def dp45_attempt(f: Callable[[float, np.ndarray], np.ndarray], t: float, y: np.ndarray, h: float, *, rtol: float,
                 atol: float) -> dict:
    """One RK45 attempt from (t, y) with step h: new state, error norm and the times at which f is evaluated.

    The error norm is the root mean square of err / (atol + max(|y|, |y_new|) rtol) with err = h sum E_i K_i; an
    attempt with norm >= 1 is rejected by the error control of the method.
    """

    C = [float(value) for value in DP45.C]
    A = [[float(value) for value in row] for row in DP45.A]
    B = np.array([float(value) for value in DP45.B])
    E = np.array([float(value) for value in DP45.E])
    y = np.asarray(y, dtype=float)
    K = [f(t, y)]
    times = []
    for stage in range(1, 6):
        dy = sum(A[stage][j] * K[j] for j in range(stage)) * h
        times.append(t + C[stage] * h)
        K.append(f(t + C[stage] * h, y + dy))
    y_new = y + h * np.dot(np.array(K).T, B)
    times.append(t + h)
    K.append(f(t + h, y_new))
    error = h * np.dot(np.array(K).T, E)
    scale = atol + np.maximum(np.abs(y), np.abs(y_new)) * rtol
    norm = float(np.linalg.norm(error / scale) / math.sqrt(y.size))
    return {"y_new": y_new, "error_K": error, "error_norm": norm, "stage_times": times}


# ------------------------------------------------------------------------------------------------- Chinese numbers


def num(value: float, digits: int = 2) -> str:
    """Number for the Chinese summary with the U+2212 minus sign; a rounded zero carries no sign."""

    text = f"{value:.{digits}f}"
    if text.startswith("-"):
        body = text[1:]
        if float(body) == 0.0:
            return body
        return MINUS + body
    return text


def sci(value: float, digits: int = 1) -> str:
    """a×10 with a superscript exponent for the Chinese summary, U+2212 for a negative mantissa."""

    if value == 0.0 or not math.isfinite(value):
        return "0" if value == 0.0 else str(value)
    exponent = int(math.floor(math.log10(abs(value))))
    mantissa = value / 10.0**exponent
    if round(abs(mantissa), digits) >= 10.0:
        exponent += 1
        mantissa = value / 10.0**exponent
    sup = str(exponent).translate(str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻"))
    return f"{num(mantissa, digits)}×10{sup}"
