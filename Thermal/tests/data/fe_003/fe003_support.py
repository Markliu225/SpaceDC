"""FE-003 support code: FE data readers, FE orbit and attitude, independent references and statistics.

Nothing in this file imports the module under test (``thermal``) or ``sdtwin_sim``. The references come from the FE
results (``iss_fem/out/<case>``), the FE model parameter table (``iss_fem/model/iss_spec.py``) and hand or closed-form
calculations:

* ``FEOrbit`` evaluates the FE orbit functions of ``summary.json`` (circular orbit, time from orbit noon), the FE Sun
  direction ``sun_ecs`` with parallel rays, the cylindrical Earth shadow of the FE and a sun-pointing attitude.
  ``eclipse_windows`` gives the shadow intervals in closed form.
* ``read_items``, ``read_breakdown`` and ``read_series`` read the FE item statistics, the loop heat breakdown and the
  time histories exactly as the FE post-processing wrote them.
* ``cold_plate_geometry`` turns a block size and its cold-plate face into the face area and the thickness normal to it.
* ``hand_r_jc`` is the second line of T5 written out by hand for a contact part ``1 / (h A)`` and a conduction part with
  length ``thickness / 3``; ``slab_mean_rise_per_watt`` solves steady one-dimensional conduction with uniform heat
  generation by finite volumes, an independent check that one third of the thickness is the conduction length whose
  resistance gives the mean temperature.
* ``exponential`` is the closed-form response of ``C dT/dt = P - (T - T_C) / R`` with constant ``T_C``.
* ``period_grid`` and ``trapezoid_stats`` give minimum, time-weighted mean and maximum over the exact last period.
* ``num``, ``sci`` and ``sci_exact`` write numbers for the Chinese summary: U+2212 for minus signs and powers of ten as
  ``1×10^{−12}``, the markup the report builder sets as a superscript.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import re
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.linalg import solve_banded
from scipy.spatial.transform import Rotation

# IAU 2012 astronomical unit in m. The FE treats sunlight as parallel rays along sun_ecs; the Earth-to-Sun vector of
# orbit_input is sun_ecs times this distance.
AU_M = 1.495978707e11
KELVIN_OFFSET = 273.15
MINUS = "−"
_NUM = r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_spec(path: Path) -> Any:
    """Import the FE model parameter table iss_spec.py from its file (pure data and the layout function)."""

    spec = importlib.util.spec_from_file_location("fe003_iss_spec", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------------------------------------- FE parameters


def parse_quantity(expression: str, unit: str) -> float:
    """Value of a COMSOL parameter string ``'<number>[<unit>]'`` with exactly the given unit."""

    match = re.fullmatch(rf"\s*{_NUM}\[{re.escape(unit)}\]\s*", expression)
    if not match:
        raise ValueError(f"parameter {expression!r} is not a number in [{unit}]")
    return float(match.group(1))


def parse_fahrenheit_set_point_K(expression: str) -> tuple[float, float]:
    """Kelvin value and Fahrenheit set point of a FE parameter ``'(<F>-32)/1.8[K]+273.15[K]'``."""

    match = re.fullmatch(rf"\s*\({_NUM}-32\)/1\.8\[K\]\+273\.15\[K\]\s*", expression)
    if not match:
        raise ValueError(f"set point {expression!r} is not of the form (F-32)/1.8[K]+273.15[K]")
    fahrenheit = float(match.group(1))
    return (fahrenheit - 32.0) / 1.8 + KELVIN_OFFSET, fahrenheit


def cold_plate_geometry(size: Any, face: str) -> tuple[float, float]:
    """Area of the cold-plate face and thickness normal to it for a block ``size = (x, y, z)`` and face ``'+z'`` etc."""

    if len(face) != 2 or face[0] not in "+-" or face[1] not in "xyz":
        raise ValueError(f"cold-plate face {face!r} is not one of +x, -x, +y, -y, +z, -z")
    axis = "xyz".index(face[1])
    others = [index for index in range(3) if index != axis]
    return float(size[others[0]]) * float(size[others[1]]), float(size[axis])


# ------------------------------------------------------------------------------------------------- hand references


def hand_r_jc(h_W_m2K: float, k_W_mK: float, area_m2: float, thickness_m: float) -> dict[str, float]:
    """Second line of T5 by hand: contact part 1 / (h A) plus conduction part (thickness / 3) / (k A)."""

    contact = 1.0 / (h_W_m2K * area_m2)
    length = thickness_m / 3.0
    conduction = length / (k_W_mK * area_m2)
    return {"contact_K_W": contact, "length_m": length, "conduction_K_W": conduction, "R_JC_K_W": contact + conduction}


def slab_mean_rise_per_watt(thickness_m: float, k_W_mK: float, area_m2: float, cells: int) -> dict[str, float]:
    """Steady 1-D conduction with uniform heat generation, heat leaving only through the cold face at x = 0.

    Finite volumes with ``cells`` equal cells: the face is held at 0, the opposite face is adiabatic and the total
    generation is 1 W. Returns the volume-mean temperature rise above the face per watt, which a uniform-generation
    device with a lumped temperature turns into its conduction resistance. The scheme does not assume the parabolic
    profile; it is second order, so the mean differs from the exact value by about 3 / (8 cells^2) relative.
    """

    n = int(cells)
    dx = thickness_m / n
    source = 1.0 / n  # W per cell
    g = k_W_mK * area_m2 / dx  # conductance between neighbouring cell centres, W/K
    g_face = k_W_mK * area_m2 / (0.5 * dx)  # first cell centre to the held face
    diagonal = np.full(n, 2.0 * g)
    diagonal[0] = g + g_face
    diagonal[-1] = g
    upper = np.full(n - 1, -g)
    lower = np.full(n - 1, -g)
    banded = np.zeros((3, n))
    banded[0, 1:] = upper
    banded[1, :] = diagonal
    banded[2, :-1] = lower
    temperature = solve_banded((1, 1), banded, np.full(n, source))
    mean = float(np.mean(temperature))
    face_flux = float(g_face * temperature[0])
    return {"mean_rise_K_per_W": mean, "face_heat_W": face_flux, "max_rise_K_per_W": float(temperature[-1])}


def exponential(t_s: np.ndarray, t0_s: float, T0_K: float, T_inf_K: float, tau_s: float) -> np.ndarray:
    """Closed form of C dT/dt = P - (T - T_C) / R with constant T_C: T_inf + (T0 - T_inf) exp(-(t - t0) / tau)."""

    return T_inf_K + (T0_K - T_inf_K) * np.exp(-(np.asarray(t_s, dtype=float) - t0_s) / tau_s)


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
            if tuple(float(value) for value in match.groups()[:3]) != (radius, period, phase):
                raise ValueError(f"FE orbit functions disagree on radius, period or phase: {funcs!r}")
        if float(my.group(4)) != float(mz.group(4)):
            raise ValueError(f"FE orbit functions disagree on the inclination: {funcs!r}")
        self.radius_m = radius
        self.function_period_s = period
        self.phase_rad = phase
        self.inclination_rad = float(my.group(4))
        self.period_s = float(orbit_record["period"])
        self.summary_radius_m = float(orbit_record["R"])
        self.eclipse_deg = float(orbit_record["eclipse_deg"])
        sun = np.array(orbit_record["sun_ecs"], dtype=float)
        self.sun_hat = sun / np.linalg.norm(sun)
        self.earth_radius_m = float(earth_radius_m)
        self.au_m = float(au_m)
        ci, si = math.cos(self.inclination_rad), math.sin(self.inclination_rad)
        self.p = np.array([1.0, 0.0, 0.0])
        self.q = np.array([0.0, ci, si])
        self.h = np.cross(self.p, self.q)

    def angle(self, t: float) -> float:
        return 2.0 * math.pi * t / self.function_period_s + self.phase_rad

    def position(self, t: float) -> np.ndarray:
        u = self.angle(t)
        return self.radius_m * (math.cos(u) * self.p + math.sin(u) * self.q)

    def sun_position(self, t: float) -> np.ndarray:
        return self.au_m * self.sun_hat

    def sun_direction(self, t: float) -> np.ndarray:
        vector = self.sun_position(t) - self.position(t)
        return vector / np.linalg.norm(vector)

    def beta_deg(self) -> float:
        return math.degrees(math.asin(float(np.clip(self.sun_hat @ self.h, -1.0, 1.0))))

    def in_shadow(self, t: float) -> bool:
        """Cylindrical shadow of the FE: behind the Earth and closer to the Sun line than the Earth radius."""

        r = self.position(t)
        along = float(r @ self.sun_hat)
        return along < 0.0 and float(r @ r) - along * along < self.earth_radius_m**2

    def irradiance(self, solar_constant: float) -> Callable[[float], float]:
        def G(t: float) -> float:
            return 0.0 if self.in_shadow(t) else float(solar_constant)

        G.__name__ = f"fe003_cylindrical_shadow_G_{solar_constant:g}"
        return G

    def eclipse_windows(self, t0: float, t1: float) -> list[tuple[float, float]]:
        """Closed-form shadow intervals (entry, exit) that intersect [t0, t1]."""

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


def read_items(path: Path) -> dict[str, dict[str, Any]]:
    """items.csv: per FE item the kind and the orbit 3 Tmin_C, Tmean_C and Tmax_C."""

    out: dict[str, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[row["name"]] = {"kind": row["kind"], "Tmin_C": float(row["Tmin_C"]),
                                "Tmean_C": float(row["Tmean_C"]), "Tmax_C": float(row["Tmax_C"])}
    return out


def read_breakdown(path: Path) -> dict[tuple[str, str], dict[str, float]]:
    """loop_breakdown.csv: per (loop, source) the orbit 3 W_mean, W_min and W_max of the heat into the loop."""

    out: dict[tuple[str, str], dict[str, float]] = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[(row["loop"], row["source"])] = {"W_mean": float(row["W_mean"]), "W_min": float(row["W_min"]),
                                                 "W_max": float(row["W_max"])}
    return out


def read_series(path: Path, columns: list[str]) -> dict[str, np.ndarray]:
    """Selected columns of series.csv in file order (event rows appear twice in the FE output)."""

    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {column: np.array([float(row[column]) for row in rows]) for column in columns}


def fe_sample_mean(t: np.ndarray, v: np.ndarray, period: float) -> float:
    """Mean of the output samples of the last period as the FE post-processing computes it (iss_solve.py)."""

    last = t >= t[-1] - period + 1e-6
    return float(np.mean(v[last]))


def fe_time_weighted_mean(t: np.ndarray, v: np.ndarray, period: float) -> float:
    """Trapezoidal time-weighted mean over the exact last period of unique output samples."""

    order = np.argsort(t, kind="stable")
    unique_t, first = np.unique(t[order], return_index=True)
    values = v[order][first]
    t0 = unique_t[-1] - period
    inside = unique_t > t0
    tt = np.concatenate([[t0], unique_t[inside]])
    vv = np.concatenate([[float(np.interp(t0, unique_t, values))], values[inside]])
    return float(np.trapezoid(vv, tt) / (tt[-1] - tt[0]))


# ------------------------------------------------------------------------------------------------- statistics


def period_grid(accepted_times: np.ndarray, t0: float, t1: float, step: float) -> np.ndarray:
    """Grid on [t0, t1]: a uniform step plus every accepted state inside, so step ends and boundaries appear."""

    accepted = np.asarray(accepted_times, dtype=float)
    grid = np.arange(t0, t1, step)
    return np.unique(np.concatenate([grid, accepted[(accepted > t0) & (accepted < t1)], [t0, t1]]))


def trapezoid_stats(grid: np.ndarray, values: np.ndarray) -> dict[str, float]:
    mean = float(np.trapezoid(values, grid) / (grid[-1] - grid[0]))
    return {"min": float(np.min(values)), "mean": mean, "max": float(np.max(values))}


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


def _exponent_text(exponent: int) -> str:
    """Exponent inside the ^{...} markup that the report builder sets as a superscript, U+2212 for the minus sign."""

    return "^{" + str(int(exponent)).replace("-", MINUS) + "}"


def sci(value: float, digits: int = 1) -> str:
    """a×10^{n} for the Chinese summary, e.g. 4.6×10^{−7}; U+2212 for every minus sign.

    The report builder renders ^{...} as a superscript; Unicode superscript characters are not used. Only finite
    values are formatted.
    """

    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"sci() formats finite values only, got {value!r}")
    if value == 0.0:
        return "0"
    exponent = int(math.floor(math.log10(abs(value))))
    mantissa = value / 10.0**exponent
    if round(abs(mantissa), digits) >= 10.0:
        exponent += 1
        mantissa = value / 10.0**exponent
    return f"{num(mantissa, digits)}×10{_exponent_text(exponent)}"


def sci_exact(value: float) -> str:
    """A configured value as a×10^{n} with the shortest mantissa that gives the value back, e.g. 1×10^{15}, 1×10^{−8}."""

    value = float(value)
    if not math.isfinite(value) or value == 0.0:
        raise ValueError(f"sci_exact() formats finite non-zero values only, got {value!r}")
    text = f"{value:.16e}"
    for digits in range(17):
        candidate = f"{value:.{digits}e}"
        if float(candidate) == value:
            text = candidate
            break
    mantissa, exponent = text.split("e")
    return f"{mantissa.replace('-', MINUS)}×10{_exponent_text(int(exponent))}"
