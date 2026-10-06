"""FE-001 support code: FE orbit and attitude, FE data readers, independent references and statistics.

Nothing in this file imports the module under test (``thermal``) or ``sdtwin_sim``. The references are built from the
FE data (``iss_fem/out/<case>``), the FE model parameter table (``iss_fem/model/iss_spec.py``) and closed-form
geometry:

* ``FEOrbit`` evaluates the FE orbit functions of ``summary.json`` (circular orbit from orbit noon), the FE Sun
  direction ``sun_ecs`` with parallel rays, the cylindrical Earth shadow of the FE and a sun-pointing attitude whose
  body +Z axis (front normal of the solar array) points at the Sun. ``eclipse_windows`` gives the shadow intervals in
  closed form, independent of any bisection.
* ``plate_factors`` integrates the Earth view factor and the albedo factor of a flat plate over the visible spherical
  cap with an Earth-centred parametrisation (Gauss-Legendre in the central angle, midpoint rule in azimuth). The
  provider under test integrates over the satellite sky instead, so the two are independent implementations.
* ``sampled_period_stats`` and ``dense_period_stats`` give minimum, time-weighted mean and maximum over the exact last
  orbital period, from FE output samples and from a dense evaluation of the module solution respectively.
* ``fe_function`` evaluates the FE orbit function text of ``summary.json`` directly (a restricted expression
  evaluator), independent of the regular-expression parse inside ``FEOrbit``.
* ``num``, ``sci``, ``gen`` and ``cn_clean`` write numbers and raw text in the form of the Chinese report rules: U+2212
  for negative numbers, powers of ten as ``1×10^{−12}``, no brackets, no dashes, no Unicode superscripts.
"""

from __future__ import annotations

import ast
import csv
import importlib.util
import json
import math
import operator
import re
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.spatial.transform import Rotation

# IAU 2012 astronomical unit in m. The FE treats sunlight as parallel rays along sun_ecs; the Earth-to-Sun vector of
# orbit_input is sun_ecs times this distance, which changes the satellite-to-Sun direction by at most r/AU = 5e-5 rad.
AU_M = 1.495978707e11
# Stefan-Boltzmann constant of design table 5, for hand calculations of the reference only.
SIGMA_W_M2_K4 = 5.670374419e-8
MINUS = "−"
_NUM = r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_spec(path: Path) -> Any:
    """Import the FE model parameter table iss_spec.py from its file (pure data, no side effects)."""

    spec = importlib.util.spec_from_file_location("fe001_iss_spec", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------------------------------------- FE orbit


class FEOrbit:
    """Orbit, Sun, eclipse and sun-pointing attitude of one FE case, from the orbit record of ``summary.json``.

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
        self.period_s = period
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

        G.__name__ = f"fe001_cylindrical_shadow_G_{solar_constant:g}"
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

    # attitude -------------------------------------------------------------------------------------------
    def rotation(self, t: float) -> Rotation:
        """Active body-to-GCRS rotation: body +Z to the Sun, body +X along the orbit normal component across it."""

        z_axis = self.sun_direction(t)
        x_axis = self.h - (self.h @ z_axis) * z_axis
        x_axis /= np.linalg.norm(x_axis)
        y_axis = np.cross(z_axis, x_axis)
        return Rotation.from_matrix(np.column_stack([x_axis, y_axis, z_axis]))

    def quaternion(self, t: float) -> np.ndarray:
        return self.rotation(t).as_quat()


# ------------------------------------------------------------------------------------------------- FE data


def read_fe_series(path: Path, time_column: str, value_column: str,
                   extra_columns: tuple[str, ...] = ()) -> dict[str, Any]:
    """FE time history of one column: unique times (event rows appear twice in the FE output) and values.

    ``extra_columns`` are read at the same unique times (first row of a repeated time) into ``extra``. A missing column
    gives NaN values, so a check on it fails instead of raising here.
    """

    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    columns = list(rows[0].keys()) if rows else []

    def column(name: str) -> np.ndarray:
        if name not in columns:
            return np.full(len(rows), np.nan)
        return np.array([float(row[name]) for row in rows])

    t = column(time_column)
    v = column(value_column)
    order = np.argsort(t, kind="stable")
    t, v = t[order], v[order]
    unique_t, first, counts = np.unique(t, return_index=True, return_counts=True)
    spread = 0.0
    for moment, count in zip(unique_t, counts):
        if count > 1:
            values = v[t == moment]
            difference = float(values.max() - values.min())
            if math.isnan(difference) or math.isnan(spread):
                spread = math.nan  # a NaN value is kept, so the precondition check fails
            elif difference > spread:
                spread = difference
    regular = np.isclose(np.mod(unique_t, 120.0), 0.0) | np.isclose(np.mod(unique_t, 120.0), 120.0)
    extra = {name: column(name)[order][first] for name in extra_columns}
    return {
        "t_s": unique_t,
        "value": v[first],
        "extra": extra,
        "rows": int(t.size),
        "event_times_s": unique_t[(counts > 1)],
        "off_grid_times_s": unique_t[~regular],
        "duplicate_value_spread": spread,
        "columns": columns,
    }


def sampled_period_stats(t: np.ndarray, v: np.ndarray, t_end: float, period: float) -> dict[str, Any]:
    """Minimum, time-weighted mean and maximum of output samples over [t_end - period, t_end].

    The start of the period is interpolated linearly between the neighbouring samples; the mean uses the trapezoidal
    rule on the samples, so it is weighted by time, not by sample count.
    """

    t0 = t_end - period
    inside = (t > t0) & (t <= t_end)
    tt = np.concatenate([[t0], t[inside]])
    vv = np.concatenate([[float(np.interp(t0, t, v))], v[inside]])
    mean = float(np.trapezoid(vv, tt) / (tt[-1] - tt[0]))
    return {"min": float(vv.min()), "mean": mean, "max": float(vv.max()), "t_s": tt, "value": vv, "t0_s": t0,
            "t1_s": float(tt[-1])}


def dense_period_grid(accepted_times: np.ndarray, t0: float, t1: float, step: float) -> np.ndarray:
    """Grid on [t0, t1]: a uniform step plus every accepted state inside, so step ends and eclipse instants appear."""

    accepted = np.asarray(accepted_times, dtype=float)
    grid = np.arange(t0, t1, step)
    return np.unique(np.concatenate([grid, accepted[(accepted > t0) & (accepted < t1)], [t0, t1]]))


def dense_period_stats(grid: np.ndarray, values: np.ndarray) -> dict[str, float]:
    mean = float(np.trapezoid(values, grid) / (grid[-1] - grid[0]))
    return {"min": float(values.min()), "mean": mean, "max": float(values.max()),
            "argmin_s": float(grid[int(np.argmin(values))]), "argmax_s": float(grid[int(np.argmax(values))])}


# ------------------------------------------------------------------------------------------------- FE function text

_FE_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_FE_CALLS = {"cos": math.cos, "sin": math.sin}
_FE_CONSTANTS = {"pi": math.pi}


def fe_function(text: str) -> Callable[[float], float]:
    """Callable ``f(t)`` that evaluates one FE orbit function exactly as written in ``summary.json``.

    Only numbers, ``t``, ``pi``, ``cos``, ``sin``, unary signs and the four arithmetic operators are accepted, so the
    text is evaluated without ``eval`` and without the regular-expression parse of ``FEOrbit``.
    """

    def build(node: ast.AST) -> Callable[[float], float]:
        if isinstance(node, ast.Expression):
            return build(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            constant = float(node.value)
            return lambda t: constant
        if isinstance(node, ast.Name) and node.id == "t":
            return lambda t: t
        if isinstance(node, ast.Name) and node.id in _FE_CONSTANTS:
            constant = _FE_CONSTANTS[node.id]
            return lambda t: constant
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            inner = build(node.operand)
            return (lambda t: -inner(t)) if isinstance(node.op, ast.USub) else inner
        if isinstance(node, ast.BinOp) and type(node.op) in _FE_BINARY:
            left, right, combine = build(node.left), build(node.right), _FE_BINARY[type(node.op)]
            return lambda t: combine(left(t), right(t))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FE_CALLS
                and len(node.args) == 1 and not node.keywords):
            function, argument = _FE_CALLS[node.func.id], build(node.args[0])
            return lambda t: function(argument(t))
        raise ValueError(f"FE orbit function {text!r} contains an unsupported element {ast.dump(node)[:80]}")

    return build(ast.parse(text.strip(), mode="eval"))


def fe_position_function(funcs: dict[str, str]) -> Callable[[float], np.ndarray]:
    """Satellite position ``(rx, ry, rz)`` in m from the FE function texts ``funcs['rx']``, ``['ry']`` and ``['rz']``."""

    parts = [fe_function(funcs[key]) for key in ("rx", "ry", "rz")]

    def position(t: float) -> np.ndarray:
        return np.array([part(float(t)) for part in parts])

    return position


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
    area = (earth_radius_m**2 * np.sin(psi) * w_psi * dphi)[:, None] * np.ones((1, n_phi))
    area = area.reshape(-1)
    to_element = earth_radius_m * element_normals - position[None, :]
    distance = np.linalg.norm(to_element, axis=1)
    direction = to_element / distance[:, None]
    cos_earth = np.clip(-(element_normals * direction).sum(axis=1), 0.0, None)
    kernel = cos_earth * area / (math.pi * distance**2)
    lit = np.clip(element_normals @ np.asarray(sun_hat, dtype=float), 0.0, None)
    cos_plate = np.clip(direction @ np.atleast_2d(normals).T, 0.0, None)
    view = kernel @ cos_plate
    albedo = (kernel * lit) @ cos_plate
    return view, albedo


def radiative_plate_reference(times: np.ndarray, t_start: float, T_start: float,
                              windows: list[tuple[float, float]], absorbed_W_m2: float, b_W_m2K4: float,
                              c_J_m2K: float) -> np.ndarray:
    """Closed-form temperature of a plate with c dT/dt = q - b T^4 (no Earth flux, no conduction).

    q is ``absorbed_W_m2`` in sunlight and zero inside the shadow ``windows``. In the shadow
    T(t) = (T0^-3 + 3 b (t - t0) / c)^(-1/3). In sunlight, with T_eq = (q / b)^(1/4),
    b (t - t0) / c = F(T) - F(T0) and F(T) = [ln|(T_eq + T) / (T_eq - T)| + 2 atan(T / T_eq)] / (4 T_eq^3), solved for T
    by bracketing between T0 and T_eq.
    """

    from scipy.optimize import brentq

    def in_shadow(moment: float) -> bool:
        return any(entry < moment < exit_ for entry, exit_ in windows)

    def advance(T0: float, dt: float, lit: bool) -> float:
        if dt <= 0.0:
            return T0
        if not lit:
            return (T0**-3 + 3.0 * b_W_m2K4 * dt / c_J_m2K) ** (-1.0 / 3.0)
        T_eq = (absorbed_W_m2 / b_W_m2K4) ** 0.25
        if T0 == T_eq:
            return T0

        def F(T: float) -> float:
            return (math.log(abs((T_eq + T) / (T_eq - T))) + 2.0 * math.atan(T / T_eq)) / (4.0 * T_eq**3)

        target = F(T0) + b_W_m2K4 * dt / c_J_m2K
        limit = T_eq * (1.0 - 1e-15) if T0 < T_eq else T_eq * (1.0 + 1e-15)
        if (F(limit) - target) * (F(T0) - target) > 0.0:
            return limit  # closer to T_eq than the bracket resolves
        low, high = sorted((T0, limit))
        return brentq(lambda T: F(T) - target, low, high, xtol=1e-13, rtol=4.0 * np.finfo(float).eps, maxiter=500)

    times = np.asarray(times, dtype=float)
    stop = float(times.max())
    edges = sorted({t_start, stop, *(x for window in windows for x in window if t_start < x < stop)})
    result = np.full(times.shape, np.nan)
    T, t = float(T_start), float(t_start)
    for left, right in zip(edges[:-1], edges[1:]):
        lit = not in_shadow(0.5 * (left + right))
        selected = np.flatnonzero((times >= left) & (times <= right))
        for index in selected:
            result[index] = advance(T, float(times[index]) - left, lit)
        T = advance(T, right - left, lit)
        t = right
    return result


def vertical_plate_view_factor(radius_m: float, earth_radius_m: float) -> float:
    """Closed form view factor of a plate whose normal is perpendicular to the local vertical."""

    h = radius_m / earth_radius_m
    x = math.sqrt(h * h - 1.0)
    return (math.atan(1.0 / x) - x / (h * h)) / math.pi


def nadir_plate_factors_1d(radius_m: float, earth_radius_m: float) -> tuple[float, float]:
    """View factor and albedo factor of a nadir plate above the subsolar point by 1-D adaptive quadrature over the
    Earth central angle; the view factor must equal (R / r)^2."""

    from scipy.integrate import quad

    r, R = float(radius_m), float(earth_radius_m)

    def integrand(psi: float, albedo: bool) -> float:
        d2 = R * R + r * r - 2.0 * R * r * math.cos(psi)
        d = math.sqrt(d2)
        cos_earth = (r * math.cos(psi) - R) / d
        cos_plate = (r - R * math.cos(psi)) / d
        weight = math.cos(psi) if albedo else 1.0
        return cos_plate * cos_earth * weight * 2.0 * R * R * math.sin(psi) / d2

    psi_max = math.acos(R / r)
    view = quad(integrand, 0.0, psi_max, args=(False,), epsabs=0.0, epsrel=1e-13, limit=200)[0]
    albedo = quad(integrand, 0.0, psi_max, args=(True,), epsabs=0.0, epsrel=1e-13, limit=200)[0]
    return view, albedo


# ------------------------------------------------------------------------------------------------- Chinese numbers


MISSING_CN = "未得到"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def num(value: float, digits: int = 2) -> str:
    """Fixed-point number for the Chinese text with the U+2212 minus sign; a rounded zero carries no sign.

    A missing or non-finite value gives ``未得到`` instead of raising, so a failed run still gets a summary.
    """

    number = _finite(value)
    if number is None:
        return MISSING_CN
    text = f"{number:.{digits}f}"
    if text.startswith("-"):
        body = text[1:]
        if float(body) == 0.0:
            return body
        return MINUS + body
    return text


def sci(value: float, digits: int = 1) -> str:
    """Power of ten for the Chinese text in the report markup: ``1.6×10^{−10}``, ``1×10^{12}``.

    The exponent is written inside ``^{...}`` with U+2212 (the report builder renders it as a superscript); trailing
    zeros of the mantissa are dropped, so 1.0 is written 1; exponent zero gives the plain number. A missing or
    non-finite value gives ``未得到``.
    """

    number = _finite(value)
    if number is None:
        return MISSING_CN
    if number == 0.0:
        return "0"
    exponent = int(math.floor(math.log10(abs(number))))
    mantissa = number / 10.0**exponent
    if round(abs(mantissa), digits) >= 10.0:
        exponent += 1
        mantissa = number / 10.0**exponent
    text = num(mantissa, digits)
    if "." in text:
        text = text.rstrip("0").rstrip(".")  # 1.0 is written 1, 1.2340 is written 1.234
    if exponent == 0:
        return text
    return f"{text}×10^{{{MINUS if exponent < 0 else ''}{abs(exponent)}}}"


def gen(value: float, significant: int = 6) -> str:
    """Number with ``significant`` digits for the Chinese text: plain notation from 1×10^{−3} up to 10^significant,
    otherwise the power of ten of :func:`sci`; U+2212 for negative values."""

    number = _finite(value)
    if number is None:
        return MISSING_CN
    if number == 0.0:
        return "0"
    if 1e-3 <= abs(number) < 10.0**significant:
        text = f"{number:.{significant}g}"
        return MINUS + text[1:] if text.startswith("-") else text
    return sci(number, max(significant - 1, 0))


_SUPERSCRIPT_RUN = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+")
_SUPERSCRIPT_PLAIN = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789" + MINUS + "+")
_E_NUMBER = re.compile(r"(?<![\w.])([-+]?\d+(?:\.\d+)?)[eE]([-+]?)0*(\d+)(?![\w.])")
_MARKUP = re.compile(r"\^\{[^{}]*\}")
_BRACKETS = str.maketrans("", "", "()[]{}<>（）【】《》「」『』〔〕'\"‘’“”")
_LITERALS = (("True", "是"), ("False", "否"), ("None", "无"), ("nan", MISSING_CN), ("inf", "无穷大"))


def cn_clean(text: Any, limit: int | None = None) -> str:
    """Raw check text in the form of the Chinese report rules.

    Unicode superscripts and e notation become the ``^{...}`` markup with U+2212, Python literals become Chinese words,
    brackets and quotes are removed (the markup itself is kept), negative numbers get U+2212, dash punctuation and
    question marks are removed. With ``limit`` the text is cut at the last ``；`` or ``，`` before the limit, never
    inside a number, and a pointer to the evidence file is added.
    """

    text = str(text)
    text = _SUPERSCRIPT_RUN.sub(lambda m: "^{" + m.group(0).translate(_SUPERSCRIPT_PLAIN) + "}", text)

    def power(match: re.Match) -> str:
        mantissa = match.group(1).replace("+", "")
        if mantissa.startswith("-"):
            mantissa = MINUS + mantissa[1:]
        exponent = (MINUS if match.group(2) == "-" else "") + match.group(3)
        return f"{mantissa}×10^{{{exponent}}}"

    text = _E_NUMBER.sub(power, text)
    for word, replacement in _LITERALS:
        text = re.sub(rf"(?<![\w.]){word}(?![\w.])", replacement, text)
    kept: list[str] = []

    def protect(match: re.Match) -> str:
        kept.append(match.group(0))
        return f"\x00{len(kept) - 1}\x00"

    text = _MARKUP.sub(protect, text)
    text = text.translate(_BRACKETS)
    text = re.sub(r"(?<![\w.])-(?=\d)", MINUS, text)
    text = re.sub(r"\s+[-–—]+\s+", "，", text)
    text = text.replace("—", "，").replace("–", "至").replace("|", "；").replace("?", "").replace("？", "")
    text = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if limit is not None and len(text) > limit:
        cut = max(text.rfind("；", 0, limit), text.rfind("，", 0, limit))
        if cut <= 0:
            cut = limit
            while cut > 0 and (text[cut - 1] in _NUMBER_CHARS or text[cut] in _NUMBER_CHARS):
                cut -= 1  # never split a number or its power of ten
        text = text[:cut].rstrip("，；、 ") + "，其余内容见证据文件"
    return text


_NUMBER_CHARS = set("0123456789.×^{}+" + MINUS)
