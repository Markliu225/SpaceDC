"""EN-002 表面吸热与辐射: calculate_surface_heat evaluates T4 surface by surface (thermal design 4.4, 5.4).

Test case EN-002 of the Chinese test report (CASES in Thermal/test_report/build_test_report_cn.py).
Every reference is independent of the module under test:
- the design 4.4 example, absorbed power 2 x 1000 x 0.8 = 1600 W, taken from the design text;
- the analytic fourth-power ratio (400 / 200)^4 = 16;
- a hand calculation of T4 written in this file from the design text and evaluated in 40-digit decimal
  arithmetic on the decimal input values of tests/data/en_002/en002_inputs.json, with the Stefan-Boltzmann
  constant of design table 5. The module works in binary floating point, so agreement is a real check of the
  formula and not a repetition of the same floating-point operations.
The orientation cases take their environment from prepare_surface_environment (design 5.3), whose incidence
cosines are recomputed here from the vectors. Single-surface, exact-cosine and invalid inputs use an environment
mapping built directly in the format of design 5.3, because 5.3 itself rejects negative irradiance.
"""

from __future__ import annotations

import copy
import json
import math
import warnings
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from thermal import (
    ThermalError,
    ThermalInputError,
    ThermalRangeWarning,
    ThermalState,
    assemble_thermal_parameters,
    calculate_surface_heat,
    prepare_surface_environment,
)

pytestmark = pytest.mark.case("EN-002")

DATA_FILE = Path(__file__).resolve().parent / "data" / "en_002" / "en002_inputs.json"
DATA = json.loads(DATA_FILE.read_text(encoding="utf-8"))

REL_TOL = float(DATA["relative_tolerance"])  # EN-002 acceptance: relative error against the hand calculation
RUN_ID = str(DATA["run_id"])
TIME_S = float(DATA["time_s"])
EPOCH = datetime.fromisoformat(DATA["epoch_utc"])
TEMPERATURES = tuple(float(value) for value in DATA["temperatures_K"])
INTERNAL = {node: float(value) for node, value in DATA["internal_temperatures_K"].items()}
ORIENTATIONS = DATA["orientations"]
ENVIRONMENTS = DATA["environments"]
EXAMPLE = DATA["design_example"]
NARROW = DATA["material_temperature_range_K"]
RESULT_KEYS = frozenset({"run_id", "time_s", "Q_env_W", "Q_emit_W", "absorbed_solar_S_W", "range_warnings"})
OUTPUTS = ("Q_env_S", "Q_env_R", "Q_emit_S", "Q_emit_R", "absorbed_solar_S")
HAND_DIGITS = 40

# Shared by the test functions of this module and read by the acceptance function at the end.
RUN: dict = {"comparisons": [], "abnormal": [], "abnormal_planned": 0, "ratios": {}, "numbers": {}}


def D(value) -> Decimal:
    """Decimal value of an input as written in the data file (shortest repr of the float)."""

    if isinstance(value, Decimal):
        return value
    return Decimal(repr(float(value)))


SIGMA = D(DATA["stefan_boltzmann_W_m2_K4"])  # design table 5, 5.670374419e-8 W m^-2 K^-4


@pytest.fixture(autouse=True)
def hand_precision():
    """Hand calculations of this module run in 40-digit decimal arithmetic, local to each test."""

    with localcontext() as context:
        context.prec = HAND_DIGITS
        yield


# --------------------------------------------------------------------------- recording


class Recorder:
    """Records every check in the case evidence and fails the test function at its end if any check failed."""

    def __init__(self, record) -> None:
        self.record = record
        self.failed: list[str] = []

    def __call__(self, name: str, expected, actual, passed) -> bool:
        if not self.record.check(name, expected, actual, bool(passed)):
            self.failed.append(name)
        return bool(passed)

    def finish(self) -> None:
        assert not self.failed, "failed checks: " + " | ".join(self.failed)


def g(value) -> str:
    return f"{float(value):.12g}"


def e(value: float) -> str:
    if value == 0.0:
        return "0"
    return "inf" if math.isinf(value) else f"{value:.2e}"


def show(values: dict) -> str:
    return ", ".join(f"{key} {g(values[key])} W" for key in OUTPUTS)


def rel_err(actual, expected) -> float:
    """Relative error computed exactly from the binary module value; an expected zero needs an exact zero."""

    a = actual if isinstance(actual, Decimal) else Decimal(float(actual))
    x = expected if isinstance(expected, Decimal) else Decimal(float(expected))
    if a == x:
        return 0.0
    if x == 0 or not a.is_finite():
        return math.inf
    return float(abs(a - x) / abs(x))


# --------------------------------------------------------------------------- case data


def components(kind: str = "main") -> list[dict]:
    """Component records: 'main' (two-sided array, two radiator coatings, ranges 150 K to 420 K),
    'example' (the single surfaces of the design 4.4 example) or 'narrow' (declared material ranges)."""

    records = copy.deepcopy(DATA["components"])
    for record in records:
        if kind == "example" and record["instance_id"] in EXAMPLE["surfaces"]:
            record["surfaces"] = copy.deepcopy(EXAMPLE["surfaces"][record["instance_id"]])
        if kind == "narrow" and record["instance_id"] in ("SolarArray01", "Radiator01"):
            record["temperature_range_K"] = [float(value) for value in NARROW[record["instance_id"]]]
    return records


def assemble(kind: str):
    return assemble_thermal_parameters(components(kind), copy.deepcopy(DATA["connections"]), None)


def declared_range(kind: str, instance_id: str) -> tuple[float, float]:
    for record in components(kind):
        if record["instance_id"] == instance_id:
            low, high = record["temperature_range_K"]
            return float(low), float(high)
    raise KeyError(instance_id)


def surface_rows(kind: str = "main") -> list[dict]:
    """Surface data from the data file in asset surface order (component order, then surface order)."""

    rows = []
    for record in components(kind):
        for surface in record.get("surfaces", []):
            rows.append(
                {
                    "id": surface["surface_id"],
                    "node": record["node_id"],
                    "A": float(surface["area_m2"]),
                    "alpha": float(surface["absorptivity"]),
                    "eps": float(surface["emissivity"]),
                    "normal": [float(value) for value in surface["normal_body"]],
                }
            )
    return rows


def hand_surfaces(kind: str = "main") -> list[dict]:
    """The same surfaces with decimal values for the hand calculation."""

    return [
        {**row, "A": D(row["A"]), "alpha": D(row["alpha"]), "eps": D(row["eps"]), "normal": [D(v) for v in row["normal"]]}
        for row in surface_rows(kind)
    ]


def environment_values(spec: dict, surfaces: list[dict]) -> tuple[float, list[float], list[float]]:
    return (
        float(spec["G_W_m2"]),
        [float(spec["albedo_W_m2"][f["id"]]) for f in surfaces],
        [float(spec["infrared_W_m2"][f["id"]]) for f in surfaces],
    )


def geometry(orientation: str) -> tuple[list[float], list[float]]:
    """Satellite position and Earth-to-Sun vector on one line, so the Sun direction is the data direction."""

    direction = [float(value) for value in ORIENTATIONS[orientation]["sun_direction"]]
    radius = float(DATA["orbit_radius_m"])
    distance = float(DATA["sun_distance_m"])
    return [radius * c for c in direction], [distance * c for c in direction]


# --------------------------------------------------------------------------- independent hand calculation


def hand_cosines(surfaces: list[dict], orientation: str) -> list[Decimal]:
    """cos(theta_f) of design table 5: unit satellite-to-Sun direction dotted with the outward normal."""

    if DATA["attitude_quaternion_xyzw"] != [0.0, 0.0, 0.0, 1.0]:
        raise ValueError("the hand calculation assumes the identity attitude of the data file")
    direction = [D(value) for value in ORIENTATIONS[orientation]["sun_direction"]]
    radius, distance = D(DATA["orbit_radius_m"]), D(DATA["sun_distance_m"])
    difference = [distance * c - radius * c for c in direction]
    length = sum(c * c for c in difference).sqrt()
    unit = [c / length for c in difference]
    return [sum(D(n) * c for n, c in zip(f["normal"], unit)) for f in surfaces]


def hand_t4(surfaces, cosines, G, albedo, infrared, T_S, T_R) -> dict:
    """T4 written from design 4.4: g_sun = G max(0, cos); Q_env = sum A [alpha (g_sun + g_alb) + eps g_IR];
    Q_emit = sum eps sigma A T^4 with T of the owning node; absorbed_solar_S = sum over S of A alpha g_sun."""

    temperature = {"S": D(T_S), "R": D(T_R)}
    absorbed = {"S": Decimal(0), "R": Decimal(0)}
    emitted = {"S": Decimal(0), "R": Decimal(0)}
    direct_s = Decimal(0)
    for f, cos, g_alb, g_ir in zip(surfaces, cosines, albedo, infrared, strict=True):
        g_sun = D(G) * max(Decimal(0), D(cos))
        absorbed[f["node"]] += D(f["A"]) * (D(f["alpha"]) * (g_sun + D(g_alb)) + D(f["eps"]) * D(g_ir))
        emitted[f["node"]] += D(f["eps"]) * SIGMA * D(f["A"]) * temperature[f["node"]] ** 4
        if f["node"] == "S":
            direct_s += D(f["A"]) * D(f["alpha"]) * g_sun
    return {
        "Q_env_S": absorbed["S"],
        "Q_env_R": absorbed["R"],
        "Q_emit_S": emitted["S"],
        "Q_emit_R": emitted["R"],
        "absorbed_solar_S": direct_s,
    }


# --------------------------------------------------------------------------- module calls


def make_state(T_S: float, T_R: float, **internal: float) -> ThermalState:
    values = dict(INTERNAL)
    values.update(internal)
    return ThermalState(RUN_ID, TIME_S, [T_S, values["J"], values["C"], values["B"], values["D"], T_R])


def temperatures(**changes: float) -> list[float]:
    values = {"S": 300.0, "R": 300.0, **INTERNAL}
    values.update(changes)
    return [values[node] for node in ("S", "J", "C", "B", "D", "R")]


def orbit_input(orientation: str, G: float) -> dict:
    position, sun = geometry(orientation)
    return {
        "run_id": RUN_ID,
        "time_s": TIME_S,
        "epoch": EPOCH,
        "position_m": position,
        "sun_position_m": sun,
        "frame": "GCRS",
        "quaternion_xyzw": list(DATA["attitude_quaternion_xyzw"]),
        "G_W_m2": G,
    }


def earth_flux(surfaces: list[dict], albedo, infrared) -> dict:
    return {
        "run_id": RUN_ID,
        "time_s": TIME_S,
        "surface_ids": [f["id"] for f in surfaces],
        "albedo_W_m2": list(albedo),
        "infrared_W_m2": list(infrared),
    }


def env_from_orbit(params, surfaces, orientation, G, albedo, infrared) -> dict:
    return prepare_surface_environment(orbit_input(orientation, G), earth_flux(surfaces, albedo, infrared), params)


def env_direct(surfaces, G, cosines, albedo, infrared, *, run_id: str = RUN_ID, time_s: float = TIME_S) -> dict:
    """Environment mapping in the format returned by prepare_surface_environment (design 5.3)."""

    return {
        "run_id": run_id,
        "time_s": time_s,
        "surface_ids": tuple(f["id"] for f in surfaces),
        "G_W_m2": G,
        "cos_incidence": list(cosines),
        "albedo_W_m2": list(albedo),
        "infrared_W_m2": list(infrared),
    }


def heat(state, environment, params):
    """calculate_surface_heat with every ThermalRangeWarning captured."""

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = calculate_surface_heat(state, environment, params)
    return result, [item for item in caught if issubclass(item.category, ThermalRangeWarning)]


def outputs(result: dict) -> dict:
    return {
        "Q_env_S": float(result["Q_env_W"][0]),
        "Q_env_R": float(result["Q_env_W"][1]),
        "Q_emit_S": float(result["Q_emit_W"][0]),
        "Q_emit_R": float(result["Q_emit_W"][1]),
        "absorbed_solar_S": float(result["absorbed_solar_S_W"]),
    }


def compare(label: str, result: dict, expected: dict) -> tuple[dict, float]:
    """Largest relative error of the five T4 outputs against the hand calculation; kept for the acceptance."""

    got = outputs(result)
    worst = max(rel_err(got[key], expected[key]) for key in OUTPUTS)
    RUN["comparisons"].append((label, worst))
    return got, worst


def outcome(call) -> tuple:
    try:
        value = call()
    except Exception as exc:  # noqa: BLE001 - the class and message are what the check inspects
        return type(exc), str(exc)
    return None, f"returned {type(value).__name__} without an error"


@pytest.fixture(scope="module")
def params_main():
    return assemble("main")


@pytest.fixture(scope="module")
def params_example():
    return assemble("example")


@pytest.fixture(scope="module")
def params_narrow():
    return assemble("narrow")


# --------------------------------------------------------------------------- preconditions


def test_preconditions_surfaces_ranges_and_environment(case_record, params_main, params_example, params_narrow):
    check = Recorder(case_record)
    sets = {"main": params_main, "example": params_example, "narrow": params_narrow}
    for kind, params in sets.items():
        expected = [(f["id"], f["node"], f["A"], tuple(f["normal"]), f["alpha"], f["eps"]) for f in surface_rows(kind)]
        actual = [
            (s.surface_id, s.node_id, s.area_m2, tuple(float(v) for v in s.normal_body), s.absorptivity, s.emissivity)
            for s in params.surfaces
        ]
        check(
            f"前置条件 表面面积 吸收率与发射率已装配 参数组 {kind}",
            f"ThermalParameters.surfaces equal the data file in asset surface order: {expected}",
            f"{actual}",
            actual == expected,
        )
    for kind in ("main", "narrow"):
        expected_ranges = {"S": declared_range(kind, "SolarArray01"), "R": declared_range(kind, "Radiator01")}
        actual_ranges = {
            node: tuple(float(v) for v in sets[kind].provenance["temperature_range_K"][node]) for node in ("S", "R")
        }
        check(
            f"前置条件 材料参数适用温区已装配 参数组 {kind}",
            f"provenance temperature_range_K of S and R = {expected_ranges} K",
            f"{actual_ranges} K",
            actual_ranges == expected_ranges,
        )

    surfaces = surface_rows("main")
    zeros = [0.0] * len(surfaces)
    worst, g_same, order_same, rows = 0.0, True, True, []
    for orientation in ORIENTATIONS:
        env = env_from_orbit(params_main, surfaces, orientation, 1361.0, zeros, zeros)
        reference = hand_cosines(surfaces, orientation)
        difference = max(abs(Decimal(float(a)) - b) for a, b in zip(env["cos_incidence"], reference, strict=True))
        worst = max(worst, float(difference))
        g_same &= env["G_W_m2"] == 1361.0
        order_same &= tuple(env["surface_ids"]) == tuple(f["id"] for f in surfaces)
        rows.append(f"{orientation}: cos {[g(v) for v in env['cos_incidence']]}, hand {[g(v) for v in reference]}")
    check(
        "前置条件 第5.3节环境输入 本用例所用几何",
        "prepare_surface_environment gives cos_incidence equal to the independent vector calculation within 1e-12, "
        "G_W_m2 = 1361 W/m^2 unchanged and surface_ids in asset surface order; case EN-001 itself runs in its own "
        "test module",
        "; ".join(rows) + f"; max |difference| {e(worst)}; G unchanged {g_same}; order kept {order_same}",
        worst <= 1e-12 and g_same and order_same,
    )
    check.finish()


# --------------------------------------------------------------------------- step 1


def test_step1_design_example_section_4_4(case_record, params_example):
    """Design 4.4 example: A_f = 2 m^2, g_sun = 1000 W/m^2, alpha_f = 0.8 absorbs 1600 W when facing the Sun."""

    check = Recorder(case_record)
    surfaces = hand_surfaces("example")
    G = float(EXAMPLE["G_W_m2"])
    zeros = [0.0] * len(surfaces)
    found: dict[str, dict[float, dict]] = {}
    cosines: dict[str, list[float]] = {}
    for orientation, spec in ORIENTATIONS.items():
        env = env_from_orbit(params_example, surfaces, orientation, G, zeros, zeros)
        cosines[orientation] = [float(v) for v in env["cos_incidence"]]
        reference = hand_cosines(surfaces, orientation)
        found[orientation], hands, worst, warned = {}, {}, 0.0, 0
        for T in TEMPERATURES:
            result, caught = heat(make_state(T, T), env, params_example)
            hands[T] = hand_t4(surfaces, reference, G, zeros, zeros, T, T)
            found[orientation][T], err = compare(f"design example {orientation} {T:g} K", result, hands[T])
            worst = max(worst, err)
            warned += len(caught)
        check(
            f"步骤1 第4.4节算例 {spec['label_cn']} 温度 200 K 300 K 400 K",
            f"hand T4, relative error <= {REL_TOL:g}: "
            + "; ".join(f"{g(T)} K {show(hands[T])}" for T in TEMPERATURES),
            f"cos_incidence {cosines[orientation]}; "
            + "; ".join(f"{g(T)} K {show(found[orientation][T])}" for T in TEMPERATURES)
            + f"; max relative error {e(worst)}; range warnings {warned}",
            worst <= REL_TOL and warned == 0,
        )

    literal = D(EXAMPLE["expected_absorbed_W"])  # 2 x 1000 x 0.8 from the design text
    facing = found["facing"][TEMPERATURES[0]]
    err_env = rel_err(facing["Q_env_S"], literal)
    err_abs = rel_err(facing["absorbed_solar_S"], literal)
    check(
        "预期 第4.4节算例的吸热功率为 1600 W",
        f"Q_env_W[S] = absorbed_solar_S_W = 2 x 1000 x 0.8 = {g(literal)} W, relative error <= {REL_TOL:g}",
        f"Q_env_W[S] {g(facing['Q_env_S'])} W, absorbed_solar_S_W {g(facing['absorbed_solar_S'])} W, "
        f"relative errors {e(err_env)} and {e(err_abs)}",
        err_env <= REL_TOL and err_abs <= REL_TOL,
    )
    away = found["away"][TEMPERATURES[0]]
    edge = found["edge_on"][TEMPERATURES[0]]
    check(
        "预期 背对太阳时直射吸热为零",
        "S_example facing away from the Sun, G = 1000 W/m^2, no albedo or infrared: Q_env_W[S] = 0 W and "
        "absorbed_solar_S_W = 0 W exactly; edge-on also 0 W",
        f"away: cos_incidence {cosines['away']}, Q_env_W[S] {g(away['Q_env_S'])} W, absorbed_solar_S_W "
        f"{g(away['absorbed_solar_S'])} W; edge-on: cos_incidence {cosines['edge_on']}, Q_env_W[S] "
        f"{g(edge['Q_env_S'])} W",
        away["Q_env_S"] == 0.0 and away["absorbed_solar_S"] == 0.0 and edge["Q_env_S"] == 0.0,
    )
    for node in ("S", "R"):
        RUN["ratios"][f"{node} design example"] = (
            found["facing"][400.0][f"Q_emit_{node}"] / found["facing"][200.0][f"Q_emit_{node}"]
        )
    RUN["numbers"]["example"] = {orientation: found[orientation][TEMPERATURES[0]]["Q_env_S"] for orientation in found}
    case_record.metric(
        "design_example_4_4",
        {
            "G_W_m2": G,
            "surfaces": surface_rows("example"),
            "cos_incidence": cosines,
            "results": {o: {f"{T:g} K": found[o][T] for T in TEMPERATURES} for o in found},
        },
    )
    check.finish()


def test_step1_orientation_and_environment_matrix(case_record, params_main):
    """Facing, side and away orientations; direct only, albedo only, infrared only, combined and no irradiance."""

    check = Recorder(case_record)
    surfaces = hand_surfaces("main")
    table, warned_total, evaluations = [], 0, 0
    for env_key, spec in ENVIRONMENTS.items():
        G, albedo, infrared = environment_values(spec, surfaces)
        for orientation in spec["orientations"]:
            env = env_from_orbit(params_main, surfaces, orientation, G, albedo, infrared)
            reference = hand_cosines(surfaces, orientation)
            worst, got, hands = 0.0, {}, {}
            for T in TEMPERATURES:
                result, caught = heat(make_state(T, T), env, params_main)
                hands[T] = hand_t4(surfaces, reference, G, albedo, infrared, T, T)
                got[T], err = compare(f"{env_key} {orientation} {T:g} K", result, hands[T])
                worst = max(worst, err)
                warned_total += len(caught)
                evaluations += 1
            label = f"{spec['label_cn']} {ORIENTATIONS[orientation]['label_cn']}"
            check(
                f"步骤1 {label} 温度 200 K 300 K 400 K",
                f"G {g(G)} W/m^2, albedo {albedo} W/m^2, infrared {infrared} W/m^2; hand T4, relative error <= "
                f"{REL_TOL:g}: " + "; ".join(f"{g(T)} K {show(hands[T])}" for T in TEMPERATURES),
                f"cos_incidence {[g(v) for v in env['cos_incidence']]}; "
                + "; ".join(f"{g(T)} K {show(got[T])}" for T in TEMPERATURES)
                + f"; max relative error {e(worst)}",
                worst <= REL_TOL,
            )
            table.append(
                {
                    "environment": env_key,
                    "orientation": orientation,
                    "G_W_m2": G,
                    "cos_incidence": [float(v) for v in env["cos_incidence"]],
                    "results": {f"{T:g} K": got[T] for T in TEMPERATURES},
                    "max_relative_error": worst,
                }
            )
    RUN["numbers"]["matrix_evaluations"] = evaluations
    case_record.metric("orientation_environment_matrix", table)
    check(
        "步骤1 组件温度在适用温区内时不报告温区限制",
        "no ThermalRangeWarning while T_S and T_R are 200 K, 300 K or 400 K inside the declared 150 K to 420 K",
        f"{warned_total} warnings in {evaluations} evaluations",
        warned_total == 0,
    )
    check.finish()


# --------------------------------------------------------------------------- step 2


def test_step2_cosine_absorptivity_emissivity_and_projection(case_record, params_main):
    check = Recorder(case_record)
    surfaces = hand_surfaces("main")
    at = {f["id"]: index for index, f in enumerate(surfaces)}
    zeros = [0.0] * len(surfaces)
    G = float(ENVIRONMENTS["direct_only"]["G_W_m2"])
    T = TEMPERATURES[1]
    state = make_state(T, T)
    front, back, aux = surfaces[at["S_front"]], surfaces[at["S_back"]], surfaces[at["R_aux"]]

    # G multiplied by the nonnegative incidence cosine; the back face is opposite to the front face.
    lines, worst, negative, zero_exact = [], 0.0, False, False
    for c in DATA["cosine_sweep_front"]:
        cos = list(zeros)
        cos[at["S_front"]], cos[at["S_back"]] = float(c), -float(c)
        result, _ = heat(state, env_direct(surfaces, G, cos, zeros, zeros), params_main)
        expected = hand_t4(surfaces, cos, G, zeros, zeros, T, T)
        got, err = compare(f"cosine sweep {c:g}", result, expected)
        worst = max(worst, err)
        negative |= min(got["Q_env_S"], got["absorbed_solar_S"]) < 0.0
        if c == 0.0:
            zero_exact = got["Q_env_S"] == 0.0 and got["absorbed_solar_S"] == 0.0
        lines.append(f"cos {c:g}: Q_env_W[S] {g(got['Q_env_S'])} W, hand {g(expected['Q_env_S'])} W")
    check(
        "步骤2 直射辐照取 G 乘非负入射余弦",
        f"Q_env_W[S] = A_front alpha_front G max(0, c) + A_back alpha_back G max(0, -c), G = {g(G)} W/m^2: "
        f"{g(front['A'] * front['alpha'] * D(G))} W at c = 1, half of it at c = 0.5, 0 W at c = 0, back face only for "
        f"c < 0, never negative; relative error <= {REL_TOL:g}",
        "; ".join(lines) + f"; max relative error {e(worst)}; negative value {negative}; exact zero at c = 0 {zero_exact}",
        worst <= REL_TOL and not negative and zero_exact,
    )

    # Each term surface by surface: direct and albedo with absorptivity, infrared with emissivity.
    albedo_spec = ENVIRONMENTS["albedo_only"]["albedo_W_m2"]
    infrared_spec = ENVIRONMENTS["infrared_only"]["infrared_W_m2"]
    opposite = {"S_front": "S_back", "S_back": "S_front"}
    names = {
        "direct": ("步骤2 直射吸热逐表面乘面积与吸收率", "A_f alpha_f G with only surface f facing the Sun"),
        "albedo": ("步骤2 反照吸热逐表面乘面积与吸收率", "A_f alpha_f g_alb with albedo on surface f only"),
        "infrared": ("步骤2 红外吸热逐表面乘面积与发射率", "A_f eps_f g_IR with infrared on surface f only"),
    }
    for term, (name, rule) in names.items():
        lines, passed = [], True
        for f in surfaces:
            index = at[f["id"]]
            cos, albedo, infrared, G_term = list(zeros), list(zeros), list(zeros), 0.0
            if term == "direct":
                G_term = G
                cos[index] = 1.0
                if f["id"] in opposite:
                    cos[at[opposite[f["id"]]]] = -1.0
                single, other_property = f["A"] * f["alpha"] * D(G), f["A"] * f["eps"] * D(G)
            elif term == "albedo":
                albedo[index] = float(albedo_spec[f["id"]])
                single = f["A"] * f["alpha"] * D(albedo[index])
                other_property = f["A"] * f["eps"] * D(albedo[index])
            else:
                infrared[index] = float(infrared_spec[f["id"]])
                single = f["A"] * f["eps"] * D(infrared[index])
                other_property = f["A"] * f["alpha"] * D(infrared[index])
            result, _ = heat(state, env_direct(surfaces, G_term, cos, albedo, infrared), params_main)
            expected = hand_t4(surfaces, cos, G_term, albedo, infrared, T, T)
            got, err = compare(f"single surface {term} {f['id']}", result, expected)
            own, other = ("Q_env_S", "Q_env_R") if f["node"] == "S" else ("Q_env_R", "Q_env_S")
            passed &= err <= REL_TOL and rel_err(got[own], single) <= REL_TOL and got[other] == 0.0
            lines.append(
                f"{f['id']} on {f['node']}: Q_env {g(got[own])} W, formula {g(single)} W, the other optical "
                f"property would give {g(other_property)} W, other node {g(got[other])} W, relative error {e(err)}"
            )
        check(name, f"{rule}, other node 0 W, relative error <= {REL_TOL:g}", "; ".join(lines), passed)

    # Area is not projected again: the cosine enters once for direct sunlight and never for albedo or infrared.
    env = env_from_orbit(params_main, surfaces, "oblique", G, zeros, zeros)
    reference = hand_cosines(surfaces, "oblique")
    result, _ = heat(state, env, params_main)
    got, err = compare("projection oblique direct", result, hand_t4(surfaces, reference, G, zeros, zeros, T, T))
    once_s = front["A"] * front["alpha"] * D(G) * reference[at["S_front"]]
    once_r = aux["A"] * aux["alpha"] * D(G) * reference[at["R_aux"]]
    twice_s, twice_r = once_s * reference[at["S_front"]], once_r * reference[at["R_aux"]]
    direct_ok = err <= REL_TOL and rel_err(got["Q_env_S"], once_s) <= REL_TOL and rel_err(got["Q_env_R"], once_r) <= REL_TOL
    lines = [
        f"oblique direct: Q_env_W [{g(got['Q_env_S'])}, {g(got['Q_env_R'])}] W against A alpha G cos "
        f"[{g(once_s)}, {g(once_r)}] W; a second projection would give [{g(twice_s)}, {g(twice_r)}] W"
    ]
    diffuse_ok = True
    for key in ("albedo_only", "infrared_only"):
        G0, albedo, infrared = environment_values(ENVIRONMENTS[key], surfaces)
        expected = hand_t4(surfaces, zeros, G0, albedo, infrared, T, T)
        values = []
        for orientation in ("facing", "oblique"):
            result, _ = heat(state, env_from_orbit(params_main, surfaces, orientation, G0, albedo, infrared), params_main)
            values.append(compare(f"projection {key} {orientation}", result, expected))
        (first, err_1), (second, err_2) = values
        diffuse_ok &= (
            err_1 <= REL_TOL and err_2 <= REL_TOL and first["Q_env_S"] == second["Q_env_S"]
            and first["Q_env_R"] == second["Q_env_R"]
        )
        lines.append(
            f"{key}: Q_env_W facing [{g(first['Q_env_S'])}, {g(first['Q_env_R'])}] W, oblique "
            f"[{g(second['Q_env_S'])}, {g(second['Q_env_R'])}] W, hand without cosine "
            f"[{g(expected['Q_env_S'])}, {g(expected['Q_env_R'])}] W"
        )
    check(
        "步骤2 面积不再重复投影",
        "direct sunlight A alpha G cos once, not cos squared; albedo and infrared independent of the incidence "
        f"cosine and equal to A alpha g_alb and A eps g_IR; relative error <= {REL_TOL:g}",
        "; ".join(lines),
        direct_ok and diffuse_ok,
    )
    check.finish()


# --------------------------------------------------------------------------- step 3


def test_step3_emission_fourth_power_of_owning_node(case_record, params_main):
    check = Recorder(case_record)
    surfaces = hand_surfaces("main")
    G, albedo, infrared = environment_values(ENVIRONMENTS["combined"], surfaces)
    env = env_from_orbit(params_main, surfaces, "facing", G, albedo, infrared)
    reference = hand_cosines(surfaces, "facing")
    pairs = [(200.0, 200.0), (300.0, 300.0), (400.0, 400.0), (400.0, 200.0), (200.0, 400.0), (250.0, 350.0)]
    got, hands, worst = {}, {}, 0.0
    for T_S, T_R in pairs:
        result, _ = heat(make_state(T_S, T_R), env, params_main)
        hands[(T_S, T_R)] = hand_t4(surfaces, reference, G, albedo, infrared, T_S, T_R)
        got[(T_S, T_R)], err = compare(f"emission T_S {T_S:g} K T_R {T_R:g} K", result, hands[(T_S, T_R)])
        worst = max(worst, err)
    check(
        "步骤3 表面辐射按发射率 面积与所属组件温度四次方逐表面求和",
        f"Q_emit = sum eps sigma A T^4, sigma = {SIGMA} W m^-2 K^-4, relative error <= {REL_TOL:g}: "
        + "; ".join(
            f"T_S {g(a)} K T_R {g(b)} K [{g(hands[(a, b)]['Q_emit_S'])}, {g(hands[(a, b)]['Q_emit_R'])}] W"
            for a, b in pairs
        ),
        "; ".join(f"T_S {g(a)} K T_R {g(b)} K [{g(got[(a, b)]['Q_emit_S'])}, {g(got[(a, b)]['Q_emit_R'])}] W" for a, b in pairs)
        + f"; max relative error {e(worst)}",
        worst <= REL_TOL,
    )

    base, s_hot, r_hot = got[(200.0, 200.0)], got[(400.0, 200.0)], got[(200.0, 400.0)]
    env_constant = all(got[p]["Q_env_S"] == base["Q_env_S"] and got[p]["Q_env_R"] == base["Q_env_R"] for p in pairs)
    plain, _ = heat(make_state(300.0, 300.0), env, params_main)
    shifted, _ = heat(make_state(300.0, 300.0, J=360.0, C=350.0, B=330.0, D=340.0), env, params_main)
    internal_free = outputs(plain) == outputs(shifted)
    owner_ok = (
        s_hot["Q_emit_R"] == base["Q_emit_R"]
        and r_hot["Q_emit_S"] == base["Q_emit_S"]
        and rel_err(s_hot["Q_emit_S"], 16 * Decimal(base["Q_emit_S"])) <= REL_TOL
        and rel_err(r_hot["Q_emit_R"], 16 * Decimal(base["Q_emit_R"])) <= REL_TOL
    )
    check(
        "步骤3 太阳能板与散热板分别取本节点温度",
        "raising T_S from 200 K to 400 K multiplies Q_emit_W[S] by 16 and leaves Q_emit_W[R]; raising T_R does the "
        "reverse; Q_env does not depend on temperature; J, C, B and D temperatures do not enter T4",
        f"T_S 400 K: Q_emit_W [{g(s_hot['Q_emit_S'])}, {g(s_hot['Q_emit_R'])}] W; T_R 400 K: "
        f"[{g(r_hot['Q_emit_S'])}, {g(r_hot['Q_emit_R'])}] W; both 200 K: [{g(base['Q_emit_S'])}, "
        f"{g(base['Q_emit_R'])}] W; Q_env unchanged {env_constant}; J, C, B and D raised by 36.85 K to 41.85 K give "
        f"identical outputs {internal_free}",
        owner_ok and env_constant and internal_free,
    )

    kelvin = hands[(300.0, 300.0)]["Q_emit_S"]
    celsius = sum(f["eps"] * SIGMA * f["A"] * (D(300.0) - D(273.15)) ** 4 for f in surfaces if f["node"] == "S")
    value = got[(300.0, 300.0)]["Q_emit_S"]
    check(
        "步骤3 辐射使用开尔文绝对温度",
        f"Q_emit_W[S] at 300 K = sum eps sigma A 300^4 = {g(kelvin)} W; the Celsius value 26.85 would give {g(celsius)} W",
        f"Q_emit_W[S] {g(value)} W, relative error {e(rel_err(value, kelvin))}",
        rel_err(value, kelvin) <= REL_TOL,
    )

    ratio_400 = {node: got[(400.0, 400.0)][f"Q_emit_{node}"] / base[f"Q_emit_{node}"] for node in ("S", "R")}
    ratio_300 = {node: got[(300.0, 300.0)][f"Q_emit_{node}"] / base[f"Q_emit_{node}"] for node in ("S", "R")}
    RUN["ratios"].update({"S": ratio_400["S"], "R": ratio_400["R"]})
    check(
        "步骤3 辐射功率与温度四次方成正比",
        f"Q_emit 400 K / 200 K = 2^4 = 16 and 300 K / 200 K = 1.5^4 = 5.0625 for S and R, relative deviation <= {REL_TOL:g}",
        f"400/200: S {ratio_400['S']!r}, R {ratio_400['R']!r}; 300/200: S {ratio_300['S']!r}, R {ratio_300['R']!r}",
        all(rel_err(ratio_400[n], 16) <= REL_TOL and rel_err(ratio_300[n], D(5.0625)) <= REL_TOL for n in ("S", "R")),
    )
    case_record.metric("emission", {f"T_S {a:g} K T_R {b:g} K": got[(a, b)] for a, b in pairs})
    check.finish()


# --------------------------------------------------------------------------- step 4


def test_step4_front_back_and_absorbed_solar(case_record, params_main):
    check = Recorder(case_record)
    surfaces = hand_surfaces("main")
    at = {f["id"]: index for index, f in enumerate(surfaces)}
    front, back, aux = surfaces[at["S_front"]], surfaces[at["S_back"]], surfaces[at["R_aux"]]
    T = TEMPERATURES[1]
    state = make_state(T, T)

    def run(env_key: str, orientation: str) -> tuple[dict, list[float], list[float], float]:
        G, albedo, infrared = environment_values(ENVIRONMENTS[env_key], surfaces)
        reference = hand_cosines(surfaces, orientation)
        result, _ = heat(state, env_from_orbit(params_main, surfaces, orientation, G, albedo, infrared), params_main)
        got, err = compare(f"step 4 {env_key} {orientation}", result, hand_t4(surfaces, reference, G, albedo, infrared, T, T))
        return got, albedo, infrared, err

    G = D(ENVIRONMENTS["direct_only"]["G_W_m2"])
    d_face, _, _, err_1 = run("direct_only", "facing")
    d_away, _, _, err_2 = run("direct_only", "away")
    c_face, albedo, infrared, err_3 = run("combined", "facing")
    front_part = front["A"] * (
        front["alpha"] * (G + D(albedo[at["S_front"]])) + front["eps"] * D(infrared[at["S_front"]])
    )
    back_part = back["A"] * (back["alpha"] * D(albedo[at["S_back"]]) + back["eps"] * D(infrared[at["S_back"]]))
    emission = SIGMA * D(T) ** 4 * (front["eps"] * front["A"] + back["eps"] * back["A"])
    front_record_for_back = back["A"] * front["alpha"] * G
    passed = (
        max(err_1, err_2, err_3) <= REL_TOL
        and rel_err(d_face["Q_env_S"], front["A"] * front["alpha"] * G) <= REL_TOL
        and rel_err(d_away["Q_env_S"], back["A"] * back["alpha"] * G) <= REL_TOL
        and rel_err(c_face["Q_env_S"], front_part + back_part) <= REL_TOL
        and rel_err(c_face["Q_emit_S"], emission) <= REL_TOL
    )
    RUN["numbers"]["front_back"] = {"away_direct_S": d_away["Q_env_S"], "facing_direct_S": d_face["Q_env_S"]}
    check(
        "步骤4 太阳能板正面与背面分别计算后再汇总",
        f"direct only facing: front A alpha G = {g(front['A'] * front['alpha'] * G)} W, back 0 W; direct only away: "
        f"back A alpha G = {g(back['A'] * back['alpha'] * G)} W, front 0 W, a front-only model gives 0 W and the front "
        f"record used for the back gives {g(front_record_for_back)} W; combined facing: front {g(front_part)} W + back "
        f"{g(back_part)} W = {g(front_part + back_part)} W; both faces radiate: Q_emit_W[S] at {g(T)} K = {g(emission)} W",
        f"Q_env_W[S] direct facing {g(d_face['Q_env_S'])} W, direct away {g(d_away['Q_env_S'])} W, combined facing "
        f"{g(c_face['Q_env_S'])} W, Q_emit_W[S] {g(c_face['Q_emit_S'])} W; max relative error {e(max(err_1, err_2, err_3))}",
        passed,
    )

    a_face, _, _, err_4 = run("albedo_only", "facing")
    i_face, _, _, err_5 = run("infrared_only", "facing")
    d_edge, _, _, err_6 = run("direct_only", "edge_on")
    c_obl, _, _, err_7 = run("combined", "oblique")
    c_away, _, _, err_8 = run("combined", "away")
    oblique_cos = hand_cosines(surfaces, "oblique")
    expected = {
        "albedo only": (a_face, Decimal(0)),
        "infrared only": (i_face, Decimal(0)),
        "direct only, radiator facing the Sun": (d_edge, Decimal(0)),
        "combined facing": (c_face, front["A"] * front["alpha"] * G),
        "combined oblique": (c_obl, front["A"] * front["alpha"] * G * oblique_cos[at["S_front"]]),
        "combined away": (c_away, back["A"] * back["alpha"] * G),
    }
    passed = (
        max(err_3, err_4, err_5, err_6, err_7, err_8) <= REL_TOL
        and all(rel_err(values["absorbed_solar_S"], reference) <= REL_TOL for values, reference in expected.values())
        and a_face["Q_env_S"] > 0.0
        and i_face["Q_env_S"] > 0.0
        and rel_err(d_edge["Q_env_R"], aux["A"] * aux["alpha"] * G) <= REL_TOL
        and c_face["absorbed_solar_S"] < c_face["Q_env_S"]
    )
    check(
        "步骤4 absorbed_solar_S_W 只含太阳能板吸收的直射太阳功率",
        "sum over S surfaces of A alpha G max(0, cos): "
        + "; ".join(f"{label} {g(reference)} W" for label, (_, reference) in expected.items())
        + "; albedo, infrared and radiator direct sunlight excluded",
        "; ".join(
            f"{label} absorbed_solar_S_W {g(values['absorbed_solar_S'])} W with Q_env_W [{g(values['Q_env_S'])}, "
            f"{g(values['Q_env_R'])}] W"
            for label, (values, _) in expected.items()
        ),
        passed,
    )
    RUN["numbers"]["absorbed"] = {label: values["absorbed_solar_S"] for label, (values, _) in expected.items()}
    RUN["numbers"]["radiator_direct_edge_on"] = d_edge["Q_env_R"]
    check.finish()


# --------------------------------------------------------------------------- step 5


def test_step5_abnormal_inputs(case_record, params_main):
    check = Recorder(case_record)
    surfaces = surface_rows("main")
    at = {f["id"]: index for index, f in enumerate(surfaces)}
    G, albedo, infrared = environment_values(ENVIRONMENTS["combined"], surfaces)
    good_env = env_direct(surfaces, G, [float(c) for c in hand_cosines(surfaces, "facing")], albedo, infrared)
    good_state = make_state(300.0, 300.0)

    def duck(**changes: float) -> SimpleNamespace:
        return SimpleNamespace(run_id=RUN_ID, time_s=TIME_S, temperature_K=np.array(temperatures(**changes)))

    def env_with(**changes) -> dict:
        changed = dict(good_env)
        changed.update(changes)
        return changed

    def replaced(values: list[float], surface_id: str, value: float) -> list[float]:
        out = list(values)
        out[at[surface_id]] = value
        return out

    def flux_with(**changes) -> dict:
        flux = earth_flux(surfaces, albedo, infrared)
        flux.update(changes)
        return flux

    cases = [
        ("温度为零 构造 ThermalState 太阳能板 0 K", lambda: ThermalState(RUN_ID, TIME_S, temperatures(S=0.0)),
         ("ThermalState.temperature_K", "node S")),
        ("温度为负 构造 ThermalState 散热板 −20 K", lambda: ThermalState(RUN_ID, TIME_S, temperatures(R=-20.0)),
         ("ThermalState.temperature_K", "node R")),
        ("温度为零 calculate_surface_heat 太阳能板 0 K", lambda: calculate_surface_heat(duck(S=0.0), good_env, params_main),
         ("state.temperature_K", "node S")),
        ("温度为负 calculate_surface_heat 散热板 −20 K", lambda: calculate_surface_heat(duck(R=-20.0), good_env, params_main),
         ("state.temperature_K", "node R")),
        ("温度为负 calculate_surface_heat 计算节点 −1 K", lambda: calculate_surface_heat(duck(J=-1.0), good_env, params_main),
         ("state.temperature_K", "node J")),
        ("温度非有限 calculate_surface_heat 太阳能板 NaN",
         lambda: calculate_surface_heat(duck(S=float("nan")), good_env, params_main), ("state.temperature_K", "finite")),
        ("温度非有限 calculate_surface_heat 散热板 正无穷",
         lambda: calculate_surface_heat(duck(R=float("inf")), good_env, params_main), ("state.temperature_K", "finite")),
        ("辐照度为负 environment G_W_m2 −1361 W/m²",
         lambda: calculate_surface_heat(good_state, env_with(G_W_m2=-1361.0), params_main), ("G_W_m2", ">= 0")),
        ("辐照度为负 environment albedo_W_m2 S_back −5 W/m²",
         lambda: calculate_surface_heat(good_state, env_with(albedo_W_m2=replaced(albedo, "S_back", -5.0)), params_main),
         ("albedo_W_m2", "S_back", ">= 0")),
        ("辐照度为负 environment infrared_W_m2 R_out −1 W/m²",
         lambda: calculate_surface_heat(good_state, env_with(infrared_W_m2=replaced(infrared, "R_out", -1.0)), params_main),
         ("infrared_W_m2", "R_out", ">= 0")),
        ("辐照度为负 经第5.3节 orbit_input G_W_m2 −1361 W/m²",
         lambda: prepare_surface_environment(orbit_input("facing", -1361.0), flux_with(), params_main),
         ("G_W_m2", ">= 0")),
        ("辐照度为负 经第5.3节 earth_flux albedo_W_m2 S_back −5 W/m²",
         lambda: prepare_surface_environment(
             orbit_input("facing", G), flux_with(albedo_W_m2=replaced(albedo, "S_back", -5.0)), params_main),
         ("albedo_W_m2", "S_back", ">= 0")),
        ("辐照度为负 经第5.3节 earth_flux infrared_W_m2 R_out −1 W/m²",
         lambda: prepare_surface_environment(
             orbit_input("facing", G), flux_with(infrared_W_m2=replaced(infrared, "R_out", -1.0)), params_main),
         ("infrared_W_m2", "R_out", ">= 0")),
        ("运行标识不一致", lambda: calculate_surface_heat(good_state, env_with(run_id=RUN_ID + "B"), params_main),
         ("run_id",)),
        ("时刻不一致 相差 0.001 s", lambda: calculate_surface_heat(good_state, env_with(time_s=TIME_S + 0.001), params_main),
         ("time_s",)),
    ]
    RUN["abnormal_planned"] += len(cases)
    log = []
    for name, call, needles in cases:
        first, second = outcome(call), outcome(call)
        error_class, message = first
        passed = (
            error_class is not None
            and issubclass(error_class, ThermalInputError)
            and issubclass(error_class, ThermalError)
            and all(needle in message for needle in needles)
            and first == second
        )
        RUN["abnormal"].append((name, passed))
        log.append({"input": name, "error": error_class.__name__ if error_class else None, "message": message})
        check(
            f"步骤5 异常输入 {name}",
            f"ThermalInputError whose message names {list(needles)}; the repeated call gives the same error",
            f"{error_class.__name__ if error_class else 'no error'}: {message}; repeated call identical {first == second}",
            passed,
        )
    case_record.metric("abnormal_inputs", log)
    check.finish()


def test_step5_temperature_outside_material_range(case_record, params_main, params_narrow):
    check = Recorder(case_record)
    surfaces = hand_surfaces("main")
    G, albedo, infrared = environment_values(ENVIRONMENTS["combined"], surfaces)
    env_narrow = env_from_orbit(params_narrow, surfaces, "facing", G, albedo, infrared)
    env_wide = env_from_orbit(params_main, surfaces, "facing", G, albedo, infrared)
    reference = hand_cosines(surfaces, "facing")
    bounds = {"S": declared_range("narrow", "SolarArray01"), "R": declared_range("narrow", "Radiator01")}
    cases = [
        ("太阳能板 200 K 低于适用温区", 200.0, 300.0, ("S",)),
        ("散热板 400 K 高于适用温区", 300.0, 400.0, ("R",)),
        ("太阳能板 400 K 与散热板 160 K 同时超出适用温区", 400.0, 160.0, ("S", "R")),
    ]
    RUN["abnormal_planned"] += len(cases)
    reported = []
    for name, T_S, T_R, nodes in cases:
        state = make_state(T_S, T_R)
        first, warned_1 = heat(state, env_narrow, params_narrow)
        second, warned_2 = heat(state, env_narrow, params_narrow)
        wide, warned_wide = heat(state, env_wide, params_main)
        got, err = compare(f"range {name}", first, hand_t4(surfaces, reference, G, albedo, infrared, T_S, T_R))
        listed = tuple(first["range_warnings"])
        value = {"S": T_S, "R": T_R}
        names_ok = len(listed) == len(nodes) and all(
            any(
                message.startswith(f"node {node} ")
                and repr(value[node]) in message
                and repr(bounds[node][0]) in message
                and repr(bounds[node][1]) in message
                for message in listed
            )
            for node in nodes
        )
        warned_ok = [str(item.message) for item in warned_1] == list(listed)
        repeat_ok = (
            outputs(second) == got
            and tuple(second["range_warnings"]) == listed
            and [str(item.message) for item in warned_2] == list(listed)
        )
        constant_ok = outputs(wide) == got and not warned_wide and err <= REL_TOL
        passed = names_ok and warned_ok and repeat_ok and constant_ok
        RUN["abnormal"].append((f"温度超出材料参数适用温区 {name}", passed))
        reported.append((name, listed, passed))
        check(
            f"步骤5 异常输入 温度超出材料参数适用温区 {name}",
            f"range_warnings and ThermalRangeWarning name node(s) {list(nodes)} with the temperature and the declared "
            f"range {[bounds[n] for n in nodes]} K; Q_env, Q_emit and absorbed_solar_S_W stay the T4 values with the "
            f"constant optical properties, equal to a run whose range covers the temperature; same result when repeated",
            f"range_warnings {listed}; warnings emitted {len(warned_1)}; {show(got)}; relative error {e(err)}; equal to "
            f"the covering range run {outputs(wide) == got}; warnings there {len(warned_wide)}; repeated identical {repeat_ok}",
            passed,
        )

    for name, T_S, T_R in (
        ("边界温度 太阳能板 373.15 K 散热板 173.15 K", bounds["S"][1], bounds["R"][0]),
        ("适用温区内 太阳能板与散热板 300 K", 300.0, 300.0),
    ):
        result, warned = heat(make_state(T_S, T_R), env_narrow, params_narrow)
        check(
            f"步骤5 {name} 不报告温区限制",
            "range_warnings empty and no ThermalRangeWarning, since the temperatures do not leave the declared range",
            f"range_warnings {tuple(result['range_warnings'])}; warnings emitted {len(warned)}",
            tuple(result["range_warnings"]) == () and not warned,
        )

    check(
        "预期 温度超出材料适用温区时报告该限制",
        "every case with T_S or T_R outside the declared range is reported in range_warnings and as ThermalRangeWarning",
        "; ".join(f"{name}: {len(listed)} report(s) {'ok' if passed else 'not ok'}" for name, listed, passed in reported),
        all(passed for _, _, passed in reported),
    )
    RUN["numbers"]["range"] = {"S": bounds["S"], "R": bounds["R"], "reported": [list(listed) for _, listed, _ in reported]}
    check.finish()


# --------------------------------------------------------------------------- expected result: no state change


def test_expected_function_does_not_modify_state(case_record, params_main):
    check = Recorder(case_record)
    surfaces = surface_rows("main")
    G, albedo, infrared = environment_values(ENVIRONMENTS["combined"], surfaces)
    state = make_state(300.0, 300.0)
    state_before = (state.run_id, state.time_s, state.temperature_K.copy())
    env = env_direct(surfaces, G, [float(c) for c in hand_cosines(surfaces, "facing")], albedo, infrared)
    env_before = copy.deepcopy(env)
    params_before = copy.deepcopy(params_main)
    result, _ = heat(state, env, params_main)

    writable = SimpleNamespace(run_id=RUN_ID, time_s=TIME_S, temperature_K=np.array(state_before[2]))
    writable_before = writable.temperature_K.copy()
    result_writable, _ = heat(writable, env, params_main)

    state_same = (
        state.run_id == state_before[0]
        and state.time_s == state_before[1]
        and np.array_equal(state.temperature_K, state_before[2])
        and state == make_state(300.0, 300.0)
    )
    writable_same = (
        np.array_equal(writable.temperature_K, writable_before)
        and bool(writable.temperature_K.flags.writeable)
        and writable.run_id == RUN_ID
        and writable.time_s == TIME_S
    )
    env_same = env == env_before
    params_same = params_main == params_before
    keys_ok = set(result) == RESULT_KEYS
    carries = result["run_id"] == state.run_id and result["time_s"] == state.time_s
    no_alias = not any(
        np.shares_memory(result[key], state.temperature_K) or np.shares_memory(result_writable[key], writable.temperature_K)
        for key in ("Q_env_W", "Q_emit_W")
    )
    same_outputs = outputs(result) == outputs(result_writable)
    passed = state_same and writable_same and env_same and params_same and keys_ok and carries and no_alias and same_outputs
    RUN["numbers"]["no_modification"] = passed
    check(
        "预期 函数不修改状态",
        "ThermalState, a writable state array, the environment mapping and ThermalParameters are unchanged after the "
        f"call; the result holds only {sorted(RESULT_KEYS)} with run_id and time_s of the state and no array shared "
        "with the state",
        f"ThermalState unchanged {state_same}; writable array unchanged and still writable {writable_same} "
        f"{writable.temperature_K.tolist()} K; environment unchanged {env_same}; parameters unchanged {params_same}; "
        f"keys {sorted(result)}; run_id {result['run_id']} time_s {result['time_s']!r}; no shared memory {no_alias}; "
        f"same outputs for both state objects {same_outputs}",
        passed,
    )
    check.finish()


# --------------------------------------------------------------------------- acceptance and summary


def cn_sci(value: float) -> str:
    """Number for the Chinese summary, U+2212 for negative exponents, report markup for the superscript."""

    if value == 0.0:
        return "0"
    if math.isinf(value):
        return "无穷大"
    mantissa, exponent = f"{value:.1e}".split("e")
    return f"{mantissa}×10^{{{int(exponent)}}}".replace("-", "−")


def cn_power(value: float) -> str:
    return g(value).replace("-", "−")


def test_acceptance_and_summary(case_record):
    check = Recorder(case_record)
    comparisons = RUN["comparisons"]
    worst = max((err for _, err in comparisons), default=math.inf)
    worst_label = max(comparisons, key=lambda item: item[1])[0] if comparisons else "none"
    n_outputs = len(comparisons) * len(OUTPUTS)
    check(
        "验收 与手算的相对误差不超过限值",
        f"largest relative error of Q_env_W, Q_emit_W and absorbed_solar_S_W against the {HAND_DIGITS}-digit decimal "
        f"hand calculation <= {REL_TOL:g}",
        f"{len(comparisons)} evaluations, {n_outputs} output values, largest relative error {e(worst)} at {worst_label}",
        bool(comparisons) and worst <= REL_TOL,
    )
    ratios = RUN["ratios"]
    needed = {"S", "R", "S design example", "R design example"}
    ratio_ok = needed <= set(ratios) and all(rel_err(ratios[key], 16) <= REL_TOL for key in needed)
    deviation = max((rel_err(ratios[key], 16) for key in needed if key in ratios), default=math.inf)
    check(
        "验收 400 K 与 200 K 的辐射功率之比为 16",
        f"Q_emit(400 K) / Q_emit(200 K) = 16 for S and R of both parameter sets, relative deviation <= {REL_TOL:g}",
        "; ".join(f"{key} {value!r}" for key, value in sorted(ratios.items())) + f"; largest deviation {e(deviation)}"
        if ratios
        else "not evaluated",
        ratio_ok,
    )
    abnormal = RUN["abnormal"]
    handled = sum(1 for _, ok in abnormal if ok)
    abnormal_ok = RUN["abnormal_planned"] > 0 and len(abnormal) == RUN["abnormal_planned"] and handled == len(abnormal)
    check(
        "验收 全部异常输入给出确定的处理结果",
        f"all {RUN['abnormal_planned']} abnormal inputs: ThermalInputError naming the field, or range report with T4 "
        "values, identical when repeated",
        f"{handled} of {len(abnormal)} handled as required" + "".join(f"; failed {name}" for name, ok in abnormal if not ok),
        abnormal_ok,
    )
    case_record.metric("hand_calculation", f"{HAND_DIGITS}-digit decimal arithmetic on the decimal input values")
    case_record.metric("max_relative_error", worst)
    case_record.metric("evaluations_compared", len(comparisons))
    case_record.metric("output_values_compared", n_outputs)
    case_record.metric("emission_ratio_400K_200K", dict(ratios))
    case_record.metric("abnormal_inputs_handled", [handled, len(abnormal)])

    numbers = RUN["numbers"]
    example = numbers.get("example", {})
    front_back = numbers.get("front_back", {})
    s_low, s_high = declared_range("narrow", "SolarArray01")
    r_low, r_high = declared_range("narrow", "Radiator01")
    edge_away = (example.get("edge_on", math.nan), example.get("away", math.nan))
    edge_away_text = (
        "均为 0 W"
        if edge_away == (0.0, 0.0)
        else f"分别为 {cn_power(edge_away[0])} W 与 {cn_power(edge_away[1])} W"
    )
    ratio_text = (
        f"均为 16，与 16 的最大相对偏差为 {cn_sci(deviation)}"
        if ratio_ok
        else "分别为 " + "、".join(cn_power(ratios.get(key, math.nan)) for key in ("S", "R"))
        + f"，与 16 的最大相对偏差为 {cn_sci(deviation)}"
    )
    abnormal_text = (
        f"{len(abnormal)} 项异常输入均给出确定的处理结果"
        if abnormal_ok
        else f"{len(abnormal)} 项异常输入中 {handled} 项给出确定的处理结果"
    )
    summary = (
        "本用例检验 calculate_surface_heat 按式 T4 逐表面计算吸热与表面辐射。参数由 assemble_thermal_parameters 装配，"
        "包括第 4.4 节算例表面，以及正面与背面分别记录的太阳能板和两个涂层区域的散热板。环境由 "
        "prepare_surface_environment 生成，第 4.4 节算例、只有直射以及直射、反照与红外同时存在的环境各取正对太阳、"
        "侧对太阳 60°、侧对太阳 90° 与背对太阳四种朝向，只有反照与只有红外的环境各取正对太阳与侧对太阳 60°，"
        "无外部辐照的环境取正对太阳，组件温度取 200 K、300 K 与 400 K，另用直接构造的环境逐表面检查入射余弦、"
        f"吸收率与发射率的作用。共 {len(comparisons)} 次调用的 {n_outputs} 个输出值与独立手算比较，手算按设计公式以 "
        f"{HAND_DIGITS} 位有效数字的十进制运算完成，最大相对误差为 {cn_sci(worst)}，验收限值为 1×10^{{−12}}。"
        f"第 4.4 节算例吸热功率为 {cn_power(example.get('facing', math.nan))} W，侧对太阳 60° 时为 "
        f"{cn_power(example.get('oblique', math.nan))} W，侧对太阳 90° 与背对太阳时直射吸热{edge_away_text}。"
        f"太阳能板与散热板在 400 K 与 200 K 的辐射功率之比{ratio_text}。"
        f"背对太阳时太阳能板直射吸热 {cn_power(front_back.get('away_direct_S', math.nan))} W 全部来自背面，"
        "absorbed_solar_S_W 在只有反照、只有红外以及只有散热板受直射时均为 0 W。"
        f"{abnormal_text}，温度为零、负值或非有限值，辐照度为负，运行标识或时刻不一致时报 ThermalInputError 并指出字段，"
        "重复调用结果相同。"
        f"太阳能板 200 K 低于其适用温区 {g(s_low)} K 至 {g(s_high)} K，散热板 400 K 高于其适用温区 {g(r_low)} K 至 "
        f"{g(r_high)} K 时，range_warnings 列出对应节点并发出 ThermalRangeWarning，吸热与辐射仍按常数光学属性计算。"
        + ("调用前后状态、环境与参数均未改变。" if numbers.get("no_modification") else "调用前后状态不变的检查未通过。")
    )
    case_record.summary(summary)

    failed = [item["name"] for item in case_record.checks if not item["passed"]]
    if failed:
        parts = []
        for name in failed:
            if name.endswith((" setup", " call", " teardown")):
                parts.append(f"测试函数 {name.rsplit(' ', 1)[0]} 运行中断")
            else:
                parts.append(f"检查项 {name} 未通过")
        case_record.anomalies("；".join(parts) + "。")
    else:
        case_record.anomalies("无")
    check.finish()
