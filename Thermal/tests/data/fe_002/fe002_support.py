"""FE-002 support code: FE data, FE orbit and radiator pointing law, independent references and statistics.

Nothing in this file imports the module under test (``thermal``) or the support package ``sdtwin_sim``. The
references are built from the FE data (``iss_fem/out/<case>``), the FE model parameter table
(``iss_fem/model/iss_spec.py``) and closed-form geometry:

* ``FEOrbit`` evaluates the FE orbit functions of ``summary.json`` (circular orbit from orbit noon), the FE Sun
  direction ``sun_ecs`` with parallel rays and the cylindrical Earth shadow of the FE. ``eclipse_windows`` gives the
  shadow intervals in closed form, independent of any bisection. ``front_normal`` is the FE radiator pointing law of
  FE report table 6: in sunlight the TRRJ zero pose (normal along the orbit normal, edge to the Sun for beta 0) or a
  roll about the station X axis that keeps the Sun in the panel plane; in the Earth shadow the front face looks at
  nadir. ``quaternion`` is the active body-to-GCRS rotation whose body +Z axis is that front normal.
* ``plate_factors`` integrates the Earth view factor and the albedo factor of flat plates over the visible spherical
  cap with an Earth-centred parametrisation (Gauss-Legendre in the central angle, midpoint rule in azimuth). The
  provider ``sdtwin_sim.earth_flux`` integrates over the satellite sky instead, so the two are independent.
* ``radiator_environment`` evaluates T4 of the design report for the two radiator faces with these factors.
* ``IndependentRadiator`` integrates the sixth line of T3 for one radiator node, ``C_R dT/dt = Q_in(t) + Q_env(t) -
  sum eps sigma A T^4``, with SciPy ``solve_ivp`` on an environment table of one orbit, split at the closed-form
  shadow boundaries and at the FE heat-input samples.
* ``fe_period_stats`` and ``dense_stats`` give minimum, time-weighted mean and maximum over the exact last orbital
  period, from FE output samples and from a dense evaluation of a solution respectively.
"""

from __future__ import annotations

import bisect
import csv
import importlib.util
import json
import math
import re
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import CubicSpline
from scipy.spatial.transform import Rotation

# IAU 2012 astronomical unit in m. The FE treats sunlight as parallel rays along sun_ecs; the Earth-to-Sun vector of
# orbit_input is sun_ecs times this distance, which turns the satellite-to-Sun direction by at most r/AU = 5e-5 rad.
AU_M = 1.495978707e11
# Stefan-Boltzmann constant of design table 5, used here only for hand calculations of the references.
SIGMA_W_M2_K4 = 5.670374419e-8
MINUS = "−"
_NUM = r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_spec(path: Path) -> Any:
    """Import the FE model parameter table iss_spec.py from its file (pure data, no side effects)."""

    spec = importlib.util.spec_from_file_location("fe002_iss_spec", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------------------------------------- FE orbit and attitude


class FEOrbit:
    """Orbit, Sun, eclipse and radiator pointing law of one FE case, from the orbit record of ``summary.json``.

    The FE position functions are ``rx = R cos(2 pi t / P + phi)``, ``ry = R sin(.) cos(i)``, ``rz = R sin(.) sin(i)``
    with time from orbit noon; they are parsed from their text so the test uses exactly the FE values.
    """

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
        self.function_period_s = period
        self.phase_rad = phase
        self.inclination_rad = float(my.group(4))
        self.summary_radius_m = float(orbit_record["R"])
        self.summary_period_s = float(orbit_record["period"])
        self.eclipse_deg = float(orbit_record["eclipse_deg"])
        sun = np.array(orbit_record["sun_ecs"], dtype=float)
        self.sun_hat = sun / np.linalg.norm(sun)
        self.earth_radius_m = float(earth_radius_m)
        self.au_m = float(au_m)
        ci, si = math.cos(self.inclination_rad), math.sin(self.inclination_rad)
        self.p = np.array([1.0, 0.0, 0.0])
        self.q = np.array([0.0, ci, si])
        self.h = np.cross(self.p, self.q)  # orbit normal, direction of r x v

    # geometry ---------------------------------------------------------------------------------------------
    def angle(self, t: float) -> float:
        return 2.0 * math.pi * t / self.function_period_s + self.phase_rad

    def position(self, t: float) -> np.ndarray:
        u = self.angle(t)
        return self.radius_m * (math.cos(u) * self.p + math.sin(u) * self.q)

    def velocity_hat(self, t: float) -> np.ndarray:
        u = self.angle(t)
        return -math.sin(u) * self.p + math.cos(u) * self.q

    def sun_position(self, t: float) -> np.ndarray:
        return self.au_m * self.sun_hat

    def sun_direction(self, t: float) -> np.ndarray:
        """Unit vector from the satellite to the Sun (the direction the thermal module uses for incidence)."""

        vector = self.sun_position(t) - self.position(t)
        return vector / np.linalg.norm(vector)

    def beta_deg(self) -> float:
        return math.degrees(math.asin(float(np.clip(self.sun_hat @ self.h, -1.0, 1.0))))

    # eclipse --------------------------------------------------------------------------------------------
    def in_shadow(self, t: float) -> bool:
        """Cylindrical shadow of the FE: behind the Earth and closer to the Sun line than the Earth radius."""

        r = self.position(t)
        along = float(r @ self.sun_hat)
        perpendicular2 = float(r @ r) - along * along
        return along < 0.0 and perpendicular2 < self.earth_radius_m**2

    def irradiance(self, solar_constant: float) -> Callable[[float], float]:
        """G(t) in W/m^2 including the eclipse: the solar constant in sunlight, zero in the shadow."""

        def G(t: float) -> float:
            return 0.0 if self.in_shadow(t) else float(solar_constant)

        G.__name__ = f"fe002_cylindrical_shadow_G_{solar_constant:g}"
        return G

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
        scale = self.function_period_s / (2.0 * math.pi)
        windows = []
        k_low = math.floor((t0 / scale + self.phase_rad - u0 - math.pi - w) / (2.0 * math.pi)) - 1
        k_high = math.ceil((t1 / scale + self.phase_rad - u0 - math.pi + w) / (2.0 * math.pi)) + 1
        for k in range(k_low, k_high + 1):
            entry = (u0 + math.pi - w + 2.0 * math.pi * k - self.phase_rad) * scale
            exit_ = (u0 + math.pi + w + 2.0 * math.pi * k - self.phase_rad) * scale
            if exit_ > t0 and entry < t1:
                windows.append((entry, exit_))
        return windows

    # radiator pointing law --------------------------------------------------------------------------------
    def front_normal(self, t: float, law: str, lit: bool | None = None) -> np.ndarray:
        """Front-face normal of the radiator in GCRS under the FE pointing law (FE report table 6).

        ``lit`` forces the phase (used at boundary instants by the references); by default the cylindrical shadow
        decides. Sunlit, law ``zero``: TRRJ zero pose, normal along the orbit normal, so for beta 0 the Sun lies in the
        panel plane at every orbit angle. Sunlit, law ``track``: roll about the station X axis (the velocity in the
        +XVV attitude) so that the satellite-to-Sun direction lies in the panel plane, normal = v x s / |v x s|.
        Shadow: the front face looks at nadir.
        """

        if lit is None:
            lit = not self.in_shadow(t)
        if not lit:
            r = self.position(t)
            return -r / np.linalg.norm(r)
        if law == "zero":
            return self.h.copy()
        if law == "track":
            n = np.cross(self.velocity_hat(t), self.sun_direction(t))
            return n / np.linalg.norm(n)
        raise ValueError(f"unknown radiator pointing law {law!r}")

    def rotation_matrix(self, t: float, law: str, lit: bool | None = None) -> np.ndarray:
        """Columns: body X, Y, Z in GCRS. Body +Z is the front normal, body +X the velocity component across it."""

        z = self.front_normal(t, law, lit)
        v = self.velocity_hat(t)
        x = v - (v @ z) * z
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        return np.column_stack([x, y, z])

    def quaternion(self, law: str) -> Callable[[float], np.ndarray]:
        """Active body-to-GCRS quaternion (SciPy xyzw order) of the pointing law, as a function of time."""

        def quaternion(t: float) -> np.ndarray:
            return Rotation.from_matrix(self.rotation_matrix(t, law)).as_quat()

        quaternion.__name__ = f"fe002_radiator_attitude_{law}"
        return quaternion


def quaternion_to_matrix(q_xyzw: np.ndarray) -> np.ndarray:
    """Rotation matrix of a unit quaternion in xyzw order (closed form, written out here)."""

    x, y, z, w = (float(value) for value in q_xyzw)
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ]
    )


# ------------------------------------------------------------------------------------------------- FE data


def read_fe_series(path: Path, columns: list[str], time_column: str = "t_s") -> dict[str, Any]:
    """FE time histories of the given columns on unique times.

    The FE output repeats a row at each eclipse event; the repeated rows must carry identical values, which is
    checked and reported as ``duplicate_value_spread``.
    """

    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    header = list(rows[0].keys()) if rows else []
    missing = [name for name in [time_column, *columns] if name not in header]
    t = np.array([float(row[time_column]) for row in rows])
    order = np.argsort(t, kind="stable")
    t = t[order]
    unique_t, first, counts = np.unique(t, return_index=True, return_counts=True)
    out: dict[str, Any] = {"t_s": unique_t, "rows": int(t.size), "columns": header, "missing": missing,
                           "event_times_s": unique_t[counts > 1]}
    spread = 0.0
    for name in columns:
        if name in missing:
            continue
        values = np.array([float(row[name]) for row in rows])[order]
        for moment, count in zip(unique_t, counts):
            if count > 1:
                same = values[t == moment]
                spread = max(spread, float(same.max() - same.min()))
        out[name] = values[first]
    out["duplicate_value_spread"] = spread
    return out


def read_fe_items(path: Path) -> dict[str, dict[str, float]]:
    with open(path, encoding="utf-8") as handle:
        return {row["name"]: {"kind": row["kind"], "Tmin_C": float(row["Tmin_C"]), "Tmean_C": float(row["Tmean_C"]),
                              "Tmax_C": float(row["Tmax_C"])} for row in csv.DictReader(handle)}


def fe_period_stats(t: np.ndarray, v: np.ndarray, t_end: float, period: float) -> dict[str, Any]:
    """Minimum, time-weighted mean and maximum of output samples over [t_end - period, t_end].

    The start of the period is interpolated linearly between the neighbouring samples; the mean uses the trapezoidal
    rule on the samples, so it is weighted by time, not by sample count.
    """

    t0 = t_end - period
    inside = (t > t0) & (t <= t_end)
    tt = np.concatenate([[t0], t[inside]])
    vv = np.concatenate([[float(np.interp(t0, t, v))], v[inside]])
    mean = float(np.trapezoid(vv, tt) / (tt[-1] - tt[0]))
    return {"min": float(vv.min()), "mean": mean, "max": float(vv.max()), "t0_s": t0, "t1_s": float(tt[-1]),
            "samples": int(tt.size)}


def dense_grid(accepted_times: np.ndarray, t0: float, t1: float, step: float) -> np.ndarray:
    """Grid on [t0, t1]: a uniform step plus every accepted state inside, so step ends and eclipse instants appear."""

    accepted = np.asarray(accepted_times, dtype=float)
    grid = np.arange(t0, t1, step)
    return np.unique(np.concatenate([grid, accepted[(accepted > t0) & (accepted < t1)], [t0, t1]]))


def dense_stats(grid: np.ndarray, values: np.ndarray) -> dict[str, float]:
    mean = float(np.trapezoid(values, grid) / (grid[-1] - grid[0]))
    return {"min": float(values.min()), "mean": mean, "max": float(values.max()),
            "argmin_s": float(grid[int(np.argmin(values))]), "argmax_s": float(grid[int(np.argmax(values))])}


def interval_integral(t: np.ndarray, v: np.ndarray, t0: float, t1: float) -> float:
    """Trapezoidal integral of samples (t, v) over [t0, t1]; the end values are interpolated linearly."""

    inside = (t > t0) & (t < t1)
    tt = np.concatenate([[t0], t[inside], [t1]])
    vv = np.concatenate([[float(np.interp(t0, t, v))], v[inside], [float(np.interp(t1, t, v))]])
    return float(np.trapezoid(vv, tt))


# ------------------------------------------------------------------------------------------------- independent Earth flux


def plate_factors(position: np.ndarray, normals: np.ndarray, sun_hat: np.ndarray, earth_radius_m: float,
                  n_psi: int, n_phi: int) -> tuple[np.ndarray, np.ndarray]:
    """Earth view factor F and albedo factor F_alb of flat plates at ``position`` (Lambertian sphere).

    F = integral over the visible cap of max(0, cos theta_plate) cos theta_earth dA / (pi d^2); F_alb weights each
    element by max(0, cos of its solar zenith angle). Earth-centred parametrisation: central angle psi from the
    sub-satellite point (Gauss-Legendre, n_psi nodes on [0, acos(R/r)]) and azimuth (midpoint rule, n_phi nodes).
    """

    position = np.asarray(position, dtype=float)
    r = float(np.linalg.norm(position))
    up = position / r
    helper = np.array([1.0, 0.0, 0.0]) if abs(up[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(helper, up)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    psi_max = math.acos(earth_radius_m / r)
    nodes, weights = np.polynomial.legendre.leggauss(n_psi)
    psi = 0.5 * psi_max * (nodes + 1.0)
    w_psi = 0.5 * psi_max * weights
    dphi = 2.0 * math.pi / n_phi
    phi = (np.arange(n_phi) + 0.5) * dphi
    sin_psi, cos_psi = np.sin(psi)[:, None], np.cos(psi)[:, None]
    element_normals = ((sin_psi * np.cos(phi)[None, :])[..., None] * e1
                       + (sin_psi * np.sin(phi)[None, :])[..., None] * e2
                       + np.broadcast_to(cos_psi, (n_psi, n_phi))[..., None] * up).reshape(-1, 3)
    area = ((earth_radius_m**2 * np.sin(psi) * w_psi * dphi)[:, None] * np.ones((1, n_phi))).reshape(-1)
    to_element = earth_radius_m * element_normals - position[None, :]
    distance = np.linalg.norm(to_element, axis=1)
    direction = to_element / distance[:, None]
    cos_earth = np.clip(-(element_normals * direction).sum(axis=1), 0.0, None)
    kernel = cos_earth * area / (math.pi * distance**2)
    lit = np.clip(element_normals @ np.asarray(sun_hat, dtype=float), 0.0, None)
    cos_plate = np.clip(direction @ np.atleast_2d(normals).T, 0.0, None)
    return kernel @ cos_plate, (kernel * lit) @ cos_plate


def vertical_plate_view_factor(radius_m: float, earth_radius_m: float) -> float:
    """Closed-form view factor of a plate whose normal is perpendicular to the local vertical."""

    h = radius_m / earth_radius_m
    x = math.sqrt(h * h - 1.0)
    return (math.atan(1.0 / x) - x / (h * h)) / math.pi


def radiator_environment(orbit: FEOrbit, t: float, law: str, lit: bool, env: dict, optics: dict, area_m2: float,
                         quadrature: tuple[int, int]) -> dict[str, Any]:
    """T4 of the design report for the two radiator faces, written out independently of the module.

    Faces: front normal n(t) of the pointing law and back -n(t), equal area and optics. Per face g_sun = G max(0,
    cos), g_alb = albedo S F_alb, g_IR = OLR F; Q_env = sum A [alpha (g_sun + g_alb) + eps g_IR].
    """

    n = orbit.front_normal(t, law, lit)
    normals = np.array([n, -n])
    G = float(env["solar_constant_W_m2"]) if lit else 0.0
    s_sat = orbit.sun_direction(t)
    cos_inc = normals @ s_sat
    view, alb = plate_factors(orbit.position(t), normals, orbit.sun_hat, orbit.earth_radius_m, *quadrature)
    g_sun = G * np.maximum(0.0, cos_inc)
    g_alb = float(env["albedo"]) * float(env["solar_constant_W_m2"]) * alb
    g_ir = float(env["olr_W_m2"]) * view
    alpha, eps = float(optics["absorptivity"]), float(optics["emissivity"])
    per_face = area_m2 * (alpha * (g_sun + g_alb) + eps * g_ir)
    return {"Q_env_W": float(per_face.sum()), "per_face_W": per_face, "cos_incidence": cos_inc,
            "view_factor": view, "albedo_factor": alb, "g_sun_W_m2": g_sun}


# ------------------------------------------------------------------------------------------------- independent radiator node


class IndependentRadiator:
    """Independent integration of the sixth line of T3 for one radiator node with the FE heat input.

    C_R dT/dt = Q_in(t) + Q_env(t) - sum_f eps sigma A_f T^4, with Q_in the linear interpolation of the FE samples and
    Q_env from ``radiator_environment`` tabulated over one orbit on a uniform grid inside each illumination phase
    (the environment of the FE orbit repeats every orbital period because the Sun direction is fixed) and
    interpolated with cubic splines inside each phase. Integration with SciPy ``solve_ivp`` (DOP853), split at the
    closed-form shadow boundaries and at every FE heat-input sample.
    """

    def __init__(self, orbit: FEOrbit, law: str, env: dict, optics: dict, area_m2: float, capacity_J_K: float,
                 table_step_s: float, quadrature: tuple[int, int]) -> None:
        self.orbit = orbit
        self.law = law
        self.env = env
        self.optics = optics
        self.area_m2 = float(area_m2)
        self.capacity = float(capacity_J_K)
        self.period = orbit.function_period_s
        windows = orbit.eclipse_windows(0.0, self.period)
        cuts = [0.0]
        phases = []
        if windows:
            # the shadow window inside one period from orbit noon (beta 0 cases: noon is at the orbit angle 0)
            entry, exit_ = min(windows, key=lambda item: abs(item[0] - 0.3 * self.period))
            if not (0.0 < entry < exit_ < self.period):
                raise ValueError(f"shadow window {entry, exit_} does not lie inside one period from noon")
            cuts += [entry, exit_]
            phases = [True, False, True]
        else:
            phases = [True]
        cuts.append(self.period)
        self.phase_cuts = cuts
        self.phase_lit = phases
        self.tables = []
        for (a, b), lit in zip(zip(cuts[:-1], cuts[1:]), phases):
            grid = np.unique(np.concatenate([np.arange(a, b, table_step_s), [b]]))
            values = np.array([radiator_environment(orbit, float(x), law, lit, env, optics, self.area_m2,
                                                    quadrature)["Q_env_W"] for x in grid])
            self.tables.append((a, b, lit, grid, CubicSpline(grid, values)))

    def environment(self, t: float, lit: bool) -> float:
        phase = t % self.period
        for a, b, table_lit, grid, spline in self.tables:
            if table_lit == lit and a - 1e-9 <= phase <= b + 1e-9:
                return float(spline(min(max(phase, a), b)))
        # phase exactly at a period end belongs to the last sunlit table
        a, b, table_lit, grid, spline = self.tables[-1] if lit else self.tables[1]
        return float(spline(min(max(phase, a), b)))

    def solve(self, T0_K: float, t_end: float, q_times: np.ndarray, q_values: np.ndarray, *, rtol: float = 1e-11,
              atol: float = 1e-9, max_step: float = 30.0) -> Callable[[np.ndarray], np.ndarray]:
        emission = float(self.optics["emissivity"]) * SIGMA_W_M2_K4 * 2.0 * self.area_m2
        breaks = {0.0, float(t_end)}
        for entry, exit_ in self.orbit.eclipse_windows(0.0, t_end):
            for moment in (entry, exit_):
                if 0.0 < moment < t_end:
                    breaks.add(float(moment))
        for moment in q_times:
            if 0.0 < moment < t_end:
                breaks.add(float(moment))
        edges = sorted(breaks)
        pieces = []
        y = float(T0_K)
        for a, b in zip(edges[:-1], edges[1:]):
            lit = not self.orbit.in_shadow(0.5 * (a + b))

            def rhs(t, T, lit=lit):
                q_in = float(np.interp(t, q_times, q_values))
                return [(q_in + self.environment(t, lit) - emission * T[0] ** 4) / self.capacity]

            sol = solve_ivp(rhs, (a, b), [y], method="DOP853", rtol=rtol, atol=atol, max_step=max_step,
                            dense_output=True)
            if not sol.success:
                raise RuntimeError(f"independent integration failed on [{a}, {b}]: {sol.message}")
            pieces.append((a, b, sol.sol))
            y = float(sol.y[0, -1])
        starts = [piece[0] for piece in pieces]

        def evaluate(times: np.ndarray) -> np.ndarray:
            times = np.atleast_1d(np.asarray(times, dtype=float))
            out = np.empty(times.size)
            for index, moment in enumerate(times):
                k = max(0, min(len(pieces) - 1, bisect.bisect_right(starts, moment) - 1))
                a, b, dense = pieces[k]
                out[index] = float(dense(min(max(moment, a), b))[0])
            return out

        return evaluate


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
    """a×10 with a superscript exponent for the Chinese summary, U+2212 for a negative mantissa.

    ``digits`` decimals of the mantissa: 1 for measured values, 0 for thresholds such as 1×10⁻³.
    """

    if value == 0.0:
        return "0"
    exponent = int(math.floor(math.log10(abs(value))))
    mantissa = value / 10.0**exponent
    if round(abs(mantissa), digits) >= 10.0:
        exponent += 1
        mantissa = value / 10.0**exponent
    sup = str(exponent).translate(str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻"))
    return f"{num(mantissa, digits)}×10{sup}"
