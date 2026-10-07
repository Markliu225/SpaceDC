"""HT-002 温度导数与整体热平衡: thermal_derivative against T3 row by row and the overall balance T1.

Implements the CASES entry HT-002 of Thermal/test_report/build_test_report_cn.py (design 4.1 T1, 4.3 T3, 5.6).
Inputs: the battery example of design 4.3 (C_B 1000 J/K, T_B 303 K, T_R 300 K, R_BR 0.5 K/W, Q_B 10 W) and 1000
random sets of temperatures, the four Power ports and environment inputs.
Steps: 1 battery temperature rate; 2 sum of C_i dT_i against the right side of T1; 3 every flow is subtracted at its
outgoing node and added at its incoming node; 4 ThermalEvaluation fields, T_B_K and T_J_K are the input temperatures
of the call and not new integrated states (every random set is evaluated a second time for the repeat, unchanged
input and read-only checks).
Acceptance: rate error <= 1e-12 K/s; |T1 residual| / total input power <= 1e-12.

Every reference value comes from tests/data/ht_002/ht002_reference.py, written from the design report without
importing the module under test. Parameters, temperatures, ports and environment are the inputs; capacitances and
resistances of the reference are the hand T5 values of tests/data/ht_002/ht002_parameters.json.

Maxima and minima over nodes, paths and evaluations go through _worst, _least and _argworst, which return NaN as soon
as one value is NaN. Python's max() and min() pass over a NaN that is not the first value, so a NaN in one evaluation
could otherwise leave a comparison with a limit passing.
"""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from thermal import ThermalEvaluation, ThermalInputs, ThermalRangeWarning, ThermalState, assemble_thermal_parameters, prepare_surface_environment, thermal_derivative
from thermal.types import EXPOSED_NODES, NODE_ORDER, PATH_ORDER

pytestmark = pytest.mark.case("HT-002")

DATA_DIR = Path(__file__).resolve().parent / "data" / "ht_002"


def _load_reference():
    spec = importlib.util.spec_from_file_location("ht002_reference", DATA_DIR / "ht002_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ref = _load_reference()

EPOCH = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
SEED = 20261005
N_RANDOM = 1000
N_BATTERY_VARIANTS = 20
RATE_TOL_K_S = 1e-12  # acceptance 1: error of the battery example rate
T1_RATIO_TOL = 1e-12  # acceptance 2: |T1 residual| / total input power
REL_TOL = 1e-12  # row, path and field comparisons, at the precision of the acceptance
DESIGN_RATE_K_S = 0.004  # design 4.3: T_B dot = 4/1000 K/s
# ThermalEvaluation fields of design table 6, in that order.
EVALUATION_FIELDS = ("run_id", "time_s", "dT_dt_K_s", "q_W", "Q_env_W", "Q_emit_W", "T_B_K", "T_J_K")
ARRAY_FIELDS = ("dT_dt_K_s", "q_W", "Q_env_W", "Q_emit_W")
# Fields of the surface environment of design 5.3 that ThermalInputs keeps.
ENVIRONMENT_KEYS = ("run_id", "time_s", "surface_ids", "G_W_m2", "cos_incidence", "albedo_W_m2", "infrared_W_m2")
I_B = ref.NODES.index("B")
I_J = ref.NODES.index("J")
# Ranges of the random inputs of input 2.
ALTITUDE_M = (300e3, 1000e3)
G_SUNLIT_W_M2 = (1317.0, 1419.0)  # solar irradiance over the year; G = 0 marks an eclipse instant
ECLIPSE_SHARE = 0.3
ALBEDO_MAX_W_M2 = 450.0
INFRARED_W_M2 = (20.0, 260.0)
P_LOAD_MAX_W = 400.0
Q_B_ABS_MAX_W = 25.0
Q_D_MAX_W = 30.0

# Chinese text of summary_cn: negative numbers with U+2212 and powers of ten as a×10^{n}, which the report builder
# renders as a superscript. No Unicode superscript character is written.
MINUS = "−"
LIMIT_CN = f"1×10^{{{MINUS}12}}"  # 1e-12 as the report writes it
IRRADIANCE_UNIT_CN = "W/m^{2}"

# Check names, used by the checks and by the list of expected checks of the anomaly record.
CHECK_ORDERS = "前置条件 节点、路径与外露表面顺序"
CHECK_BATTERY_INPUT = "输入 1 电池算例参数"
CHECK_BATTERY_RATE = "步骤 1 电池算例温升速度，验收 1"
CHECK_BATTERY_FLOW = "步骤 1 电池算例传热与留存功率"
CHECK_BATTERY_VARIANTS = "步骤 1 其余节点、功率与环境任取时电池温升速度不变"
CHECK_RANDOM_COUNT = "输入 2 随机输入组数与覆盖"
CHECK_RANDOM_ENVIRONMENT = "输入 2 环境输入与温区"
CHECK_T1 = "步骤 2 各组件储热之和等于 T1 右侧，验收 2"
CHECK_T1_OTHER = "步骤 2 另两种输入总功率口径下的比值"
CHECK_T3_ROWS = "步骤 3 随机输入下六个节点的储热变化率等于 T3 各行"
CHECK_FIELDS = "步骤 4 ThermalEvaluation 字段与维数"
CHECK_CONTENT = "步骤 4 q_W、Q_env_W 与 Q_emit_W 的内容与顺序"
CHECK_COPIES = "步骤 4 T_B_K 与 T_J_K 是本次输入温度"
CHECK_NOT_STATE = "步骤 4 T_B_K 与 T_J_K 不是新的积分状态"
# Properties of the second call of step 4, counted over the random sets, with their Chinese wording.
NOT_STATE_ITEMS = {
    "no_state_field": "没有温度数组且温度导数只有六个分量",
    "repeat": "两次结果逐位相同",
    "state": "输入状态未被修改",
    "ports": "四个功率未被修改",
    "environment": "环境输入未被修改",
    "copies": "T_B_K 与 T_J_K 等于本次输入温度",
    "arrays": "四个数组拒绝写入且不能恢复为可写",
    "fields": "八个字段拒绝改写",
}


def _set_check(name: str) -> str:
    return f"前置条件 参数组 {name} 的热容与热阻等于 T5 手算值"


def _path_check(path: str, first: str, second: str) -> str:
    return f"步骤 3 热流 {path} 在 {first} 端减去、在 {second} 端加上"


def _expected_checks() -> list[str]:
    """Names of every check the case records when all test functions run to their end."""

    try:
        set_names = list(ref.load_parameter_sets())
    except Exception:  # noqa: BLE001  test_preconditions reports an unreadable parameter file
        set_names = []
    return [
        CHECK_ORDERS,
        *(_set_check(name) for name in set_names),
        CHECK_BATTERY_INPUT,
        CHECK_BATTERY_RATE,
        CHECK_BATTERY_FLOW,
        CHECK_BATTERY_VARIANTS,
        CHECK_RANDOM_COUNT,
        CHECK_RANDOM_ENVIRONMENT,
        CHECK_T1,
        CHECK_T1_OTHER,
        *(_path_check(path, first, second) for path, first, second in ref.PATHS),
        CHECK_T3_ROWS,
        CHECK_FIELDS,
        CHECK_CONTENT,
        CHECK_COPIES,
        CHECK_NOT_STATE,
    ]


# --------------------------------------------------------------------------- helpers


def _values(values) -> np.ndarray:
    return np.array([float(v) for v in values], dtype=float)


def _worst(values) -> float:
    """Largest value; NaN as soon as one value is NaN; inf for no values, so that a limit comparison fails."""

    array = _values(values)
    if array.size == 0:
        return math.inf
    if np.isnan(array).any():
        return math.nan
    return float(array.max())


def _least(values) -> float:
    """Smallest value; NaN as soon as one value is NaN or for no values."""

    array = _values(values)
    if array.size == 0 or np.isnan(array).any():
        return math.nan
    return float(array.min())


def _argworst(values) -> int:
    """Index of the first NaN, or of the largest value when no value is NaN."""

    array = _values(values)
    nan = np.flatnonzero(np.isnan(array))
    return int(nan[0]) if nan.size else int(np.argmax(array))


def _sci(value: float, digits: int = 1) -> str:
    """Number for the Chinese summary: 0, a plain decimal for ordinary magnitudes, or a×10^{n} in the report markup.

    The report builder renders ^{...} as a superscript; a negative mantissa or exponent carries U+2212. A NaN or an
    infinity is written as 非有限值.
    """

    value = float(value)
    if value == 0.0:
        return "0"
    if not math.isfinite(value):
        return "非有限值"
    sign = MINUS if value < 0 else ""
    if 1e-3 <= abs(value) < 1e4:  # ordinary magnitudes in plain decimals with the same significant digits
        decimals = max(0, digits - math.floor(math.log10(abs(value))))
        return sign + f"{abs(value):.{decimals}f}"
    mantissa, exponent = f"{abs(value):.{digits}e}".split("e")
    power = int(exponent)
    if power == 0:
        return sign + mantissa
    power_text = str(power).replace("-", MINUS)
    return f"{sign}{mantissa}×10^{{{power_text}}}"


def _num(value: float, nd: int) -> str:
    value = float(value)
    if not math.isfinite(value):
        return "非有限值"
    return f"{value:.{nd}f}".replace("-", MINUS)


def _g(value: float) -> str:
    """Up to six significant digits without exponent for ordinary magnitudes; negatives with U+2212."""

    value = float(value)
    if not math.isfinite(value) or (value != 0 and not 1e-4 <= abs(value) < 1e6):
        return _sci(value, 5)
    return f"{value:.6g}".replace("-", MINUS)


def _rel(actual: float, reference: float) -> float:
    diff = abs(float(actual) - float(reference))
    if reference != 0:
        return diff / abs(reference)
    return 0.0 if diff == 0 else math.inf


def _bitwise_equal(a, b) -> bool:
    """Same type and the same bits: arrays by dtype, shape and bytes, floats by their hex form."""

    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        if not (isinstance(a, np.ndarray) and isinstance(b, np.ndarray)):
            return False
        return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        return a.hex() == b.hex()
    return a == b


def _same_record(first, second) -> bool:
    return type(first) is type(second) and all(
        _bitwise_equal(getattr(first, name), getattr(second, name)) for name in EVALUATION_FIELDS
    )


def _same_environment(stored, prepared) -> bool:
    """The environment kept by ThermalInputs equals, bit for bit, the one prepare_surface_environment returned."""

    for key in ENVIRONMENT_KEYS:
        x, y = stored[key], prepared[key]
        if key == "run_id":
            same = x == y
        elif key == "surface_ids":
            same = tuple(x) == tuple(y)
        else:
            ax, ay = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
            same = ax.shape == ay.shape and ax.tobytes() == ay.tobytes()
        if not same:
            return False
    return True


def _array_locked(array) -> bool:
    """The array refuses item assignment and cannot be made writeable again, neither directly nor through a base."""

    if not isinstance(array, np.ndarray) or array.flags.writeable or array.size == 0:
        return False
    before = array.tobytes()
    try:
        array.flat[0] = array.flat[0] + 1.0
        return False
    except ValueError:
        pass
    base = array
    while isinstance(base, np.ndarray):
        try:
            base.setflags(write=True)
            return False
        except ValueError:
            pass
        base = base.base
    return array.tobytes() == before


def _field_locked(record, name: str) -> bool:
    """Assigning the field raises and leaves the value unchanged (frozen dataclass)."""

    value = getattr(record, name)
    if isinstance(value, str):
        replacement = value + "x"
    elif isinstance(value, np.ndarray):
        replacement = np.zeros_like(value)
    else:
        replacement = float(value) + 1.0
    try:
        setattr(record, name, replacement)
    except AttributeError:  # dataclasses.FrozenInstanceError is an AttributeError
        return _bitwise_equal(getattr(record, name), value)
    return False


def _unit(rng: np.random.Generator, n: int) -> np.ndarray:
    while True:
        v = rng.normal(size=n)
        norm = float(np.linalg.norm(v))
        if norm > 1e-6:
            return v / norm


def _assemble(parameter_set: dict, overrides: dict | None = None):
    return assemble_thermal_parameters(
        copy.deepcopy(parameter_set["components"]), copy.deepcopy(parameter_set["connections"]), overrides
    )


def _orbit_input(run_id, time_s, position_m, sun_position_m, quaternion_xyzw, G_W_m2) -> dict:
    return {
        "run_id": run_id,
        "time_s": float(time_s),
        "epoch": EPOCH,
        "position_m": [float(v) for v in position_m],
        "sun_position_m": [float(v) for v in sun_position_m],
        "frame": "GCRS",
        "quaternion_xyzw": [float(v) for v in quaternion_xyzw],
        "G_W_m2": float(G_W_m2),
    }


def _earth_flux(run_id, time_s, surface_ids, albedo, infrared) -> dict:
    return {
        "run_id": run_id,
        "time_s": float(time_s),
        "surface_ids": list(surface_ids),
        "albedo_W_m2": [float(v) for v in albedo],
        "infrared_W_m2": [float(v) for v in infrared],
    }


def _run_case(params, model, run_id, time_s, temperature, geometry, albedo, infrared, ports) -> dict:
    """Prepare the environment, build ThermalState and ThermalInputs, call thermal_derivative and the reference.

    ``ports`` is the dict of the four Power ports, or a function of the direct sunlight absorbed by S in the prepared
    environment that returns them (P_pv_W must not exceed that value, design 5.6).
    """

    position, sun, quaternion, G = geometry
    environment = prepare_surface_environment(
        _orbit_input(run_id, time_s, position, sun, quaternion, G),
        _earth_flux(run_id, time_s, model.surface_ids, albedo, infrared),
        params,
    )
    absorbed_env = model.absorbed_solar_S(environment["G_W_m2"], environment["cos_incidence"])
    ports = ports(absorbed_env) if callable(ports) else dict(ports)
    state = ThermalState(run_id, float(time_s), np.array([temperature[n] for n in ref.NODES], dtype=float))
    inputs = ThermalInputs(
        run_id, float(time_s), environment, ports["P_pv_W"], ports["P_load_W"], ports["Q_B_W"], ports["Q_D_W"]
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        evaluation = thermal_derivative(state, inputs, params)
    reference = model.evaluate(temperature, position, sun, quaternion, G, albedo, infrared, ports)
    return {
        "time_s": float(time_s),
        "temperature": dict(temperature),
        "state": state,
        "inputs": inputs,
        "environment": environment,
        "ports": ports,
        "evaluation": evaluation,
        "reference": reference,
        "range_warnings": [str(w.message) for w in caught if issubclass(w.category, ThermalRangeWarning)],
    }


def _analyse(case: dict, model) -> dict:
    """T1 residual, T3 rows and ThermalEvaluation fields of one evaluation against the independent reference."""

    ev = case["evaluation"]
    r = case["reference"]
    ports = case["ports"]
    dT = np.asarray(ev.dT_dt_K_s, dtype=float)
    stored = [model.C[n] * float(dT[i]) for i, n in enumerate(ref.NODES)]  # C_i dT_i, W
    lhs = math.fsum(stored)
    residual = lhs - r["t1_rhs_W"]
    Q_env, Q_emit = r["Q_env"], r["Q_emit"]
    # Total input power: heat entering the node set (environment absorption of S and R, P_load, Q_D, positive Q_B).
    p_in_heat = math.fsum([Q_env["S"], Q_env["R"], ports["P_load_W"], ports["Q_D_W"], max(ports["Q_B_W"], 0.0)])
    # Environment input plus the magnitudes of the four Power ports.
    p_in_ports = math.fsum(
        [Q_env["S"], Q_env["R"], ports["P_pv_W"], ports["P_load_W"], abs(ports["Q_B_W"]), ports["Q_D_W"]]
    )
    p_gross = math.fsum(abs(t) for t in r["t1_terms"])
    module_env = [float(v) for v in ev.Q_env_W]
    module_emit = [float(v) for v in ev.Q_emit_W]
    rhs_module = math.fsum(
        [module_env[0], module_env[1], -ports["P_pv_W"], ports["P_load_W"], ports["Q_B_W"], ports["Q_D_W"],
         -module_emit[0], -module_emit[1]]
    )
    row_rel = []
    for i, n in enumerate(ref.NODES):
        diff = abs(stored[i] - r["rows_W"][n])
        gross = r["gross_W"][n]
        row_rel.append(diff / gross if gross > 0 else (0.0 if diff == 0 else math.inf))
    q_module = [float(v) for v in ev.q_W]
    q_rel = [_rel(q_module[k], r["q"][path]) for k, (path, _, _) in enumerate(ref.PATHS)]
    env_rel = [_rel(module_env[k], Q_env[n]) for k, n in enumerate(ref.EXPOSED)]
    emit_rel = [_rel(module_emit[k], Q_emit[n]) for k, n in enumerate(ref.EXPOSED)]
    module_cos = [float(v) for v in case["environment"]["cos_incidence"]]
    if len(module_cos) == len(r["cos_incidence"]):
        cos_diff = _worst(abs(a - b) for a, b in zip(module_cos, r["cos_incidence"]))
    else:
        cos_diff = math.inf
    temperature = case["temperature"]
    return {
        "lhs_W": lhs,
        "rhs_W": r["t1_rhs_W"],
        "residual_W": residual,
        "p_in_heat_W": p_in_heat,
        "ratio_heat": abs(residual) / p_in_heat,
        "ratio_ports": abs(residual) / p_in_ports,
        "ratio_gross": abs(residual) / p_gross,
        "residual_module_W": lhs - rhs_module,
        "row_rel": row_rel,
        "q_rel_max": _worst(q_rel),
        "env_rel_max": _worst(env_rel),
        "emit_rel_max": _worst(emit_rel),
        "cos_diff": cos_diff,
        "shapes": tuple(np.shape(getattr(ev, name)) for name in ARRAY_FIELDS),
        "fields": tuple(f.name for f in dataclasses.fields(ev)),
        "is_evaluation": isinstance(ev, ThermalEvaluation),
        "run_time_equal": ev.run_id == case["state"].run_id and ev.time_s == case["time_s"],
        "T_B_equal": _bitwise_equal(ev.T_B_K, float(temperature["B"])),
        "T_J_equal": _bitwise_equal(ev.T_J_K, float(temperature["J"])),
        "dT_B": float(dT[I_B]),
        "dT_J": float(dT[I_J]),
    }


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def parameter_sets() -> dict:
    return ref.load_parameter_sets()


@pytest.fixture(scope="module")
def random_run(parameter_sets) -> dict:
    """Input 2: 1000 random sets of temperatures, the four Power ports and environment inputs, fixed seed."""

    parameter_set = parameter_sets["sat01_like"]
    model = ref.ReferenceModel(parameter_set)
    params = _assemble(parameter_set)
    rng = np.random.default_rng(SEED)
    run_id = "HT-002-random"
    cases, analyses, errors = [], [], []
    coverage = {"eclipse": 0, "Q_B_negative": 0, "Q_B_positive": 0, "P_pv_zero": 0, "P_pv_at_absorbed": 0,
                "P_pv_between": 0, "P_load_zero": 0, "Q_D_zero": 0, "range_warnings": 0}
    for k in range(N_RANDOM):
        time_s = 60.0 * k
        temperature = {n: float(rng.uniform(model.ranges[n][0] + 1.0, model.ranges[n][1] - 1.0)) for n in ref.NODES}
        position = _unit(rng, 3) * rng.uniform(6378137.0 + ALTITUDE_M[0], 6378137.0 + ALTITUDE_M[1])
        sun = _unit(rng, 3) * rng.uniform(1.47e11, 1.52e11)
        quaternion = _unit(rng, 4)
        G = 0.0 if rng.random() < ECLIPSE_SHARE else float(rng.uniform(*G_SUNLIT_W_M2))
        albedo = [0.0 if rng.random() < 0.2 else float(rng.uniform(0.0, ALBEDO_MAX_W_M2)) for _ in model.surfaces]
        infrared = [float(rng.uniform(*INFRARED_W_M2)) for _ in model.surfaces]
        pv_choice, pv_fraction = float(rng.random()), float(rng.random())
        load = 0.0 if rng.random() < 0.1 else float(rng.uniform(0.0, P_LOAD_MAX_W))
        q_b = float(rng.uniform(-Q_B_ABS_MAX_W, Q_B_ABS_MAX_W))
        q_d = 0.0 if rng.random() < 0.1 else float(rng.uniform(0.0, Q_D_MAX_W))

        def ports_for(absorbed, pv_choice=pv_choice, pv_fraction=pv_fraction, load=load, q_b=q_b, q_d=q_d):
            if pv_choice < 0.1:
                pv = 0.0
            elif pv_choice < 0.2:
                pv = absorbed  # at the limit absorbed_solar_S_W of design 5.6
            else:
                pv = pv_fraction * absorbed
            return {"P_pv_W": pv, "P_load_W": load, "Q_B_W": q_b, "Q_D_W": q_d}

        try:
            case = _run_case(params, model, run_id, time_s, temperature, (position, sun, quaternion, G), albedo,
                             infrared, ports_for)
        except Exception as exc:  # noqa: BLE001  recorded as a failed evaluation, never as a pass
            errors.append(f"case {k}: {type(exc).__name__}: {exc}")
            continue
        cases.append(case)
        analyses.append(_analyse(case, model))
        ports = case["ports"]
        absorbed = model.absorbed_solar_S(case["environment"]["G_W_m2"], case["environment"]["cos_incidence"])
        coverage["eclipse"] += G == 0.0
        coverage["Q_B_negative"] += ports["Q_B_W"] < 0.0
        coverage["Q_B_positive"] += ports["Q_B_W"] > 0.0
        coverage["P_pv_zero"] += ports["P_pv_W"] == 0.0
        coverage["P_pv_at_absorbed"] += ports["P_pv_W"] > 0.0 and ports["P_pv_W"] == absorbed
        coverage["P_pv_between"] += 0.0 < ports["P_pv_W"] < absorbed
        coverage["P_load_zero"] += ports["P_load_W"] == 0.0
        coverage["Q_D_zero"] += ports["Q_D_W"] == 0.0
        coverage["range_warnings"] += len(case["range_warnings"])
    return {"model": model, "params": params, "cases": cases, "analyses": analyses, "errors": errors,
            "coverage": coverage, "run_id": run_id}


# --------------------------------------------------------------------------- preconditions


def test_preconditions(case_record, parameter_sets):
    """Assembled C and R equal the hand T5 values and the module orders equal the design orders."""

    results = []
    orders_ok = (tuple(NODE_ORDER) == ref.NODES and tuple(PATH_ORDER) == tuple(p for p, _, _ in ref.PATHS)
                 and tuple(EXPOSED_NODES) == ref.EXPOSED)
    results.append(case_record.check(
        CHECK_ORDERS,
        "NODE_ORDER S J C B D R，PATH_ORDER SR JC CR BR DR，EXPOSED_NODES S R，与设计报告表 6 一致",
        f"NODE_ORDER {tuple(NODE_ORDER)}，PATH_ORDER {tuple(PATH_ORDER)}，EXPOSED_NODES {tuple(EXPOSED_NODES)}",
        orders_ok,
    ))
    for name, parameter_set in parameter_sets.items():
        model = ref.ReferenceModel(parameter_set)
        params = _assemble(parameter_set)
        c_rel = _worst(_rel(params.C_J_K[i], model.C[n]) for i, n in enumerate(ref.NODES))
        r_rel = _worst(_rel(params.R_K_W[k], model.R[p]) for k, (p, _, _) in enumerate(ref.PATHS))
        surfaces_ok = tuple(s.surface_id for s in params.surfaces) == model.surface_ids
        results.append(case_record.check(
            _set_check(name),
            "C_J_K 与 R_K_W 相对误差 ≤ 1e-12，表面顺序与资产一致",
            f"C 手算 {[round(model.C[n], 6) for n in ref.NODES]} J/K，装配 {[round(float(v), 6) for v in params.C_J_K]}，"
            f"最大相对误差 {c_rel:.3e}；R 手算 {[round(model.R[p], 6) for p, _, _ in ref.PATHS]} K/W，"
            f"装配 {[round(float(v), 6) for v in params.R_K_W]}，最大相对误差 {r_rel:.3e}；表面顺序一致 {surfaces_ok}",
            c_rel <= REL_TOL and r_rel <= REL_TOL and surfaces_ok,
        ))
        case_record.metric(f"C_hand_J_K_{name}", {n: model.C[n] for n in ref.NODES})
        case_record.metric(f"R_hand_K_W_{name}", {p: model.R[p] for p, _, _ in ref.PATHS})
    assert all(results)


# --------------------------------------------------------------------------- step 1


def test_step1_battery_example(case_record, parameter_sets):
    """Input 1 and step 1: battery example of design 4.3, expected rate 0.004 K/s."""

    parameter_set = parameter_sets["battery_example"]
    model = ref.ReferenceModel(parameter_set)
    params = _assemble(parameter_set)
    results = []
    C_B = float(params.C_J_K[I_B])
    R_BR = float(params.R_K_W[ref.PATHS.index(("BR", "B", "R"))])
    results.append(case_record.check(
        CHECK_BATTERY_INPUT,
        "C_B = 1000 J/K，由 1 kg 与 1000 J/(kg K) 的材料按 T5 装配；R_BR = 0.5 K/W",
        f"C_B = {C_B!r} J/K，R_BR = {R_BR!r} K/W",
        C_B == 1000.0 and R_BR == 0.5,
    ))

    run_id = "HT-002-battery"
    temperature = {"S": 300.0, "J": 300.0, "C": 300.0, "B": 303.0, "D": 300.0, "R": 300.0}
    # Eclipse instant, every other source zero: only Q_B and q_BR act on node B.
    geometry = ((6778137.0, 0.0, 0.0), (-1.496e11, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 0.0)
    ports = {"P_pv_W": 0.0, "P_load_W": 0.0, "Q_B_W": 10.0, "Q_D_W": 0.0}
    case = _run_case(params, model, run_id, 0.0, temperature, geometry, [0.0] * 4, [200.0] * 4, ports)
    ev = case["evaluation"]
    rate = float(ev.dT_dt_K_s[I_B])
    hand_rate = (10.0 - (303.0 - 300.0) / 0.5) / 1000.0  # T2 and the fourth line of T3 by hand
    rate_error = abs(rate - DESIGN_RATE_K_S)
    q_BR = float(ev.q_W[ref.PATHS.index(("BR", "B", "R"))])
    retained = model.C["B"] * rate
    results.append(case_record.check(
        CHECK_BATTERY_RATE,
        "dT_B/dt = 0.004 K/s，误差 ≤ 1e-12 K/s",
        f"dT_B/dt = {rate!r} K/s，与 0.004 K/s 之差 {rate_error:.3e} K/s，与手算 {hand_rate!r} K/s 之差 "
        f"{abs(rate - hand_rate):.3e} K/s",
        rate_error <= RATE_TOL_K_S and abs(rate - hand_rate) <= RATE_TOL_K_S,
    ))
    results.append(case_record.check(
        CHECK_BATTERY_FLOW,
        "q_BR = 3/0.5 = 6 W，C_B dT_B/dt = 10 − 6 = 4 W，相对误差 ≤ 1e-12",
        f"q_BR = {q_BR!r} W，C_B dT_B/dt = {retained!r} W",
        _rel(q_BR, 6.0) <= REL_TOL and _rel(retained, 4.0) <= REL_TOL,
    ))

    # The fourth line of T3 holds Q_B and q_BR only: other temperatures, ports and environment must not change it.
    rng = np.random.default_rng(SEED + 1)
    deviations = []
    variant_errors = []
    for k in range(N_BATTERY_VARIANTS):
        other = {n: float(rng.uniform(model.ranges[n][0] + 1.0, model.ranges[n][1] - 1.0)) for n in ref.NODES}
        other["B"], other["R"] = 303.0, 300.0
        geometry_k = (_unit(rng, 3) * 6778137.0, _unit(rng, 3) * 1.496e11, _unit(rng, 4),
                      float(rng.uniform(*G_SUNLIT_W_M2)))
        albedo = [float(rng.uniform(0.0, ALBEDO_MAX_W_M2)) for _ in model.surfaces]
        infrared = [float(rng.uniform(*INFRARED_W_M2)) for _ in model.surfaces]
        fraction = float(rng.random())
        load, q_d = float(rng.uniform(0.0, P_LOAD_MAX_W)), float(rng.uniform(0.0, Q_D_MAX_W))

        def ports_for(absorbed, fraction=fraction, load=load, q_d=q_d):
            return {"P_pv_W": fraction * absorbed, "P_load_W": load, "Q_B_W": 10.0, "Q_D_W": q_d}

        try:
            variant = _run_case(params, model, run_id, 60.0 * (k + 1), other, geometry_k, albedo, infrared, ports_for)
        except Exception as exc:  # noqa: BLE001
            variant_errors.append(f"variant {k}: {type(exc).__name__}: {exc}")
            continue
        deviations.append(abs(float(variant["evaluation"].dT_dt_K_s[I_B]) - DESIGN_RATE_K_S))
    max_dev = _worst(deviations)
    results.append(case_record.check(
        CHECK_BATTERY_VARIANTS,
        f"{N_BATTERY_VARIANTS} 组随机的其余输入，T_B 303 K、T_R 300 K、Q_B 10 W 不变，dT_B/dt 与 0.004 K/s 之差 ≤ 1e-12 K/s",
        f"完成 {len(deviations)} 组，最大差 {max_dev:.3e} K/s" + (f"；报错 {variant_errors}" if variant_errors else ""),
        len(deviations) == N_BATTERY_VARIANTS and max_dev <= RATE_TOL_K_S,
    ))
    case_record.metric("battery_example", {
        "C_B_J_K": C_B, "R_BR_K_W": R_BR, "T_B_K": 303.0, "T_R_K": 300.0, "Q_B_W": 10.0, "q_BR_W": q_BR,
        "retained_W": retained, "dT_B_dt_K_s": rate, "error_K_s": rate_error,
        "variants": len(deviations), "variants_max_error_K_s": max_dev,
        "T_B_K_returned": ev.T_B_K, "T_J_K_returned": ev.T_J_K,
    })
    assert all(results)


# --------------------------------------------------------------------------- step 2


def test_step2_t1_random_cases(case_record, random_run):
    """Input 2 and step 2: sum of C_i dT_i against the right side of T1 for 1000 random input sets."""

    analyses, errors, coverage = random_run["analyses"], random_run["errors"], random_run["coverage"]
    results = []
    covered = all(coverage[key] > 0 for key in ("eclipse", "Q_B_negative", "Q_B_positive", "P_pv_zero",
                                                  "P_pv_at_absorbed", "P_pv_between", "P_load_zero", "Q_D_zero"))
    results.append(case_record.check(
        CHECK_RANDOM_COUNT,
        "1000 组温度、四个功率与环境输入全部完成 thermal_derivative 计算；覆盖日食、Q_B 正负、P_pv 为零、介于零与 "
        "absorbed_solar_S_W 之间和等于 absorbed_solar_S_W、P_load 与 Q_D 为零",
        f"完成 {len(analyses)} 组，报错 {len(errors)} 组 {errors[:3]}；覆盖 {coverage}",
        len(analyses) == N_RANDOM and not errors and covered,
    ))
    if not analyses:
        assert all(results)
        return
    cos_max = _worst(a["cos_diff"] for a in analyses)
    results.append(case_record.check(
        CHECK_RANDOM_ENVIRONMENT,
        "prepare_surface_environment 的 cos_incidence 与独立四元数计算之差 ≤ 1e-12；随机温度均在声明温区内，无 ThermalRangeWarning",
        f"cos_incidence 最大差 {cos_max:.3e}；ThermalRangeWarning {coverage['range_warnings']} 次",
        cos_max <= REL_TOL and coverage["range_warnings"] == 0,
    ))

    ratios_heat = [a["ratio_heat"] for a in analyses]
    worst = _argworst(ratios_heat)  # first NaN if any, otherwise the largest ratio
    ratio_heat = _worst(ratios_heat)
    ratio_ports = _worst(a["ratio_ports"] for a in analyses)
    ratio_gross = _worst(a["ratio_gross"] for a in analyses)
    residual_max = _worst(abs(a["residual_W"]) for a in analyses)
    residual_module_max = _worst(abs(a["residual_module_W"]) for a in analyses)
    p_in_min = _least(a["p_in_heat_W"] for a in analyses)
    rhs_values = [a["rhs_W"] for a in analyses]
    rhs_range = (_least(rhs_values), _worst(rhs_values))
    results.append(case_record.check(
        CHECK_T1,
        "1000 组 |Σ C_i dT_i − T1 右侧| / 输入总功率 ≤ 1e-12；T1 右侧由独立 T4 与输入功率计算，输入总功率取 "
        "Q_env,S + Q_env,R + P_load + Q_D + max(Q_B, 0)",
        f"最大比值 {ratio_heat:.3e}，出现在第 {worst} 组：残差 {analyses[worst]['residual_W']:.3e} W，输入总功率 "
        f"{analyses[worst]['p_in_heat_W']:.3f} W；全部组最大残差 {residual_max:.3e} W，输入总功率最小 {p_in_min:.3f} W，"
        f"T1 右侧范围 {rhs_range[0]:.1f} 至 {rhs_range[1]:.1f} W；改用模块自身 Q_env_W 与 Q_emit_W 时最大残差 "
        f"{residual_module_max:.3e} W",
        ratio_heat <= T1_RATIO_TOL,
    ))
    results.append(case_record.check(
        CHECK_T1_OTHER,
        "以环境吸热与四个功率绝对值之和，或 T1 右侧八项绝对值之和为分母，比值同样 ≤ 1e-12",
        f"环境与四个功率口径最大比值 {ratio_ports:.3e}；八项口径最大比值 {ratio_gross:.3e}",
        ratio_ports <= T1_RATIO_TOL and ratio_gross <= T1_RATIO_TOL,
    ))
    case_record.metric("random_cases", {
        "seed": SEED, "n_requested": N_RANDOM, "n_evaluated": len(analyses), "errors": errors[:5], "coverage": coverage,
        "t1_ratio_max_heat_input": ratio_heat, "t1_ratio_max_ports_input": ratio_ports,
        "t1_ratio_max_gross": ratio_gross, "t1_residual_max_W": residual_max,
        "t1_residual_module_closure_max_W": residual_module_max, "p_in_heat_min_W": p_in_min,
        "t1_rhs_range_W": rhs_range, "cos_incidence_max_diff": cos_max, "worst_case_index": worst,
        "worst_case": {"time_s": random_run["cases"][worst]["time_s"],
                       "temperature_K": random_run["cases"][worst]["temperature"],
                       "ports_W": random_run["cases"][worst]["ports"],
                       "residual_W": analyses[worst]["residual_W"], "p_in_heat_W": analyses[worst]["p_in_heat_W"]},
    })
    assert all(results)


# --------------------------------------------------------------------------- step 3


def _doubling_override(parameter_set: dict, path: str) -> tuple[dict, float, float, str]:
    """Overrides that double the resistance of one path, with the hand values before and after."""

    record = next(c for c in parameter_set["connections"] if c["path"] == path)
    before = ref.path_resistance(record)
    if "equivalent_total_resistance_K_W" in record:
        field, value = "equivalent_total_resistance_K_W", 2.0 * float(record["equivalent_total_resistance_K_W"])
    else:
        field, value = "contact_resistance_K_W", float(record["contact_resistance_K_W"]) + before
    changed = dict(record)
    changed[field] = value
    overrides = {"connections": {path: {field: value}}, "source": "HT-002 sign bookkeeping: one path resistance doubled"}
    return overrides, before, ref.path_resistance(changed), field


def test_step3_sign_bookkeeping(case_record, parameter_sets, random_run):
    """Step 3: every flow is subtracted at its outgoing node and added at its incoming node.

    Each failed sub-condition of a path is recorded with its own Chinese wording in ``failed_conditions``, so the
    summary names the condition that failed and not only the bookkeeping deviation.
    """

    parameter_set = parameter_sets["sat01_like"]
    model = ref.ReferenceModel(parameter_set)
    params_a = _assemble(parameter_set)
    run_id = "HT-002-sign"
    q = np.array([0.1, -0.2, 0.3, 0.9])
    geometry = ((6778137.0, 0.0, 0.0), (1.2e11, 8.0e10, 3.0e10), q / np.linalg.norm(q), 1361.0)
    albedo, infrared = [120.0, 80.0, 60.0, 140.0], [210.0, 90.0, 150.0, 180.0]

    def ports_for(absorbed):
        return {"P_pv_W": 0.3 * absorbed, "P_load_W": 150.0, "Q_B_W": 4.0, "Q_D_W": 6.0}

    # First node hotter than the second on every path, then colder on every path.
    states = {
        "正向": {"S": 330.0, "J": 340.0, "C": 320.0, "B": 305.0, "D": 315.0, "R": 290.0},
        "反向": {"S": 200.0, "J": 300.0, "C": 310.0, "B": 280.0, "D": 270.0, "R": 320.0},
    }
    side_cn = {"正向": "两端温差为正时", "反向": "两端温差为负时"}
    results = []
    bookkeeping = {}
    failures: dict[str, list[str]] = {}
    ends_all, rest_all, sum_abs_all, sum_rel_all = [], [], [], []
    rest_exact_zero = True
    for p_index, (path, first, second) in enumerate(ref.PATHS):
        overrides, R_a, R_b, field = _doubling_override(parameter_set, path)
        params_b = _assemble(parameter_set, overrides)
        model_b = model.with_resistance(path, R_b)
        others = [k for k in range(len(ref.PATHS)) if k != p_index]
        rest_nodes = [n for n in ref.NODES if n not in (first, second)]
        R_assembled = float(params_b.R_K_W[p_index])
        reasons: list[str] = []
        if not _rel(R_assembled, R_b) <= REL_TOL:
            reasons.append(f"经 overrides 装配的 {path} 热阻为 {_g(R_assembled)} K/W，与加倍后的手算值 {_g(R_b)} K/W 不符")
        if not all(params_b.R_K_W[k] == params_a.R_K_W[k] for k in others):
            reasons.append(f"{path} 热阻加倍后其余四条路径的热阻发生变化")
        lines = []
        for direction, temperature in states.items():
            side = side_cn[direction]
            time_s = 10.0 * p_index + (0.0 if direction == "正向" else 5.0)
            case_a = _run_case(params_a, model, run_id, time_s, temperature, geometry, albedo, infrared, ports_for)
            case_b = _run_case(params_b, model_b, run_id, time_s, temperature, geometry, albedo, infrared, ports_for)
            ev_a, ev_b = case_a["evaluation"], case_b["evaluation"]
            dT_a = np.asarray(ev_a.dT_dt_K_s, dtype=float)
            dT_b = np.asarray(ev_b.dT_dt_K_s, dtype=float)
            delta = {n: model.C[n] * (float(dT_b[i]) - float(dT_a[i])) for i, n in enumerate(ref.NODES)}
            dT_path = temperature[first] - temperature[second]
            dq = dT_path / R_b - dT_path / R_a  # change of q on this path, independent T2
            expected = {n: 0.0 for n in ref.NODES}
            expected[first] -= dq
            expected[second] += dq
            gross = {n: _worst([case_a["reference"]["gross_W"][n], case_b["reference"]["gross_W"][n]]) for n in ref.NODES}
            rel = {n: abs(delta[n] - expected[n]) / gross[n] for n in ref.NODES}
            ends_rel = _worst(rel[n] for n in (first, second))
            rest_rel = _worst(rel[n] for n in rest_nodes)
            rest_zero = sum(1 for n in rest_nodes if delta[n] == 0.0)
            total = math.fsum(delta.values())
            total_rel = abs(total) / math.fsum(gross.values())
            q_a = float(ev_a.q_W[p_index])
            q_b = float(ev_b.q_W[p_index])
            rel_q_a, rel_q_b = _rel(q_a, dT_path / R_a), _rel(q_b, dT_path / R_b)
            sign_ok = all((v > 0.0) if direction == "正向" else (v < 0.0) for v in (q_a, q_b))
            others_q_ok = all(float(ev_b.q_W[k]) == float(ev_a.q_W[k]) for k in others)
            if not sign_ok:
                reasons.append(f"{side} $q_{path}$ 在热阻加倍前后为 {_g(q_a)} W 与 {_g(q_b)} W，符号与两端温差不一致")
            if not (rel_q_a <= REL_TOL and rel_q_b <= REL_TOL):
                reasons.append(f"{side} $q_{path}$ 与 T2 手算值不符，热阻加倍前后的相对偏差为 {_sci(rel_q_a)} 与 "
                               f"{_sci(rel_q_b)}")
            if not others_q_ok:
                reasons.append(f"{side}其余四条路径的热流在 {path} 热阻加倍后发生变化")
            if not ends_rel <= REL_TOL:
                reasons.append(f"{side}第一个节点 {first} 与第二个节点 {second} 储存热能的变化率改变量与该热流改变量不符，"
                               f"相对偏差最大为 {_sci(ends_rel)}")
            if not rest_rel <= REL_TOL:
                reasons.append(f"{side}其余四个节点储存热能的变化率发生改变，相对偏差最大为 {_sci(rest_rel)}")
            if not total_rel <= REL_TOL:
                reasons.append(f"{side}六个节点改变量之和为 {_sci(total)} W，与 T3 各项绝对值之和之比为 {_sci(total_rel)}")
            ends_all.append(ends_rel)
            rest_all.append(rest_rel)
            sum_abs_all.append(abs(total))
            sum_rel_all.append(total_rel)
            rest_exact_zero = rest_exact_zero and rest_zero == len(rest_nodes)
            lines.append(
                f"{direction} q = {q_a:.6g} W 变为 {q_b:.6g} W，Δq = {dq:.6g} W；{first} 端 C·ΔdT = {delta[first]:.6g} W，"
                f"{second} 端 {delta[second]:.6g} W；其余节点最大 |C·ΔdT| = "
                f"{_worst(abs(delta[n]) for n in rest_nodes):.3e} W，逐位为零 {rest_zero}/{len(rest_nodes)}；"
                f"六节点合计 {total:.3e} W；相对偏差 两端 {ends_rel:.3e}、其余节点 {rest_rel:.3e}、合计 {total_rel:.3e}；"
                f"q 与 T2 相对偏差 {rel_q_a:.3e}、{rel_q_b:.3e}"
            )
            bookkeeping[f"{path}_{'forward' if direction == '正向' else 'reverse'}"] = {
                "q_before_W": q_a, "q_after_W": q_b, "dq_hand_W": dq, "delta_first_W": delta[first],
                "delta_second_W": delta[second], "sum_delta_W": total, "ends_max_rel": ends_rel,
                "rest_max_rel": rest_rel, "rest_exact_zero": rest_zero, "sum_rel": total_rel,
                "q_rel_before": rel_q_a, "q_rel_after": rel_q_b, "sign_ok": sign_ok, "others_q_unchanged": others_q_ok,
                "max_rel": _worst([ends_rel, rest_rel, total_rel]),
            }
        failures[path] = reasons
        results.append(case_record.check(
            _path_check(path, first, second),
            f"{path} 热阻经 overrides 由 {R_a:.6g} K/W 加倍为 {R_b:.6g} K/W，其余热阻不变；两端温差为正与为负时，"
            f"C_{first}·ΔdT = −Δq，C_{second}·ΔdT = +Δq，其余四个节点不变，六节点合计为零，相对偏差 ≤ 1e-12；"
            f"q_{path} 在热阻加倍前后保留符号且等于 T2 手算值，其余热流不变",
            f"装配 {path} 热阻 {R_assembled!r} K/W，修改字段 {field}；" + "；".join(lines)
            + (f"；未满足：{'；'.join(reasons)}" if reasons else ""),
            not reasons,
        ))

    analyses = random_run["analyses"]
    row_rel = np.array([a["row_rel"] for a in analyses], dtype=float).reshape(len(analyses), len(ref.NODES))
    row_max = {n: _worst(row_rel[:, i]) for i, n in enumerate(ref.NODES)}
    rows_worst = _worst(row_max.values())
    results.append(case_record.check(
        CHECK_T3_ROWS,
        "1000 组中 C_i dT_i 与独立 T3 各行之差 ≤ 1e-12 倍该行各项绝对值之和；q 在第一个节点减去、在第二个节点加上",
        f"完成 {row_rel.shape[0]} 组，各节点最大相对偏差 { {n: f'{v:.3e}' for n, v in row_max.items()} }，"
        f"六个节点最大 {rows_worst:.3e}",
        row_rel.shape[0] == N_RANDOM and rows_worst <= REL_TOL,
    ))
    case_record.metric("sign_bookkeeping", bookkeeping)
    case_record.metric("sign_bookkeeping_max_rel", _worst(ends_all + rest_all + sum_rel_all))
    case_record.metric("sign_bookkeeping_detail", {
        "ends_max_rel": _worst(ends_all), "rest_max_rel": _worst(rest_all), "rest_exact_zero": rest_exact_zero,
        "sum_abs_max_W": _worst(sum_abs_all), "sum_max_rel": _worst(sum_rel_all), "failed_conditions": failures,
    })
    case_record.metric("t3_rows_max_rel", row_max)
    case_record.metric("t3_rows_evaluated", int(row_rel.shape[0]))
    assert all(results)


# --------------------------------------------------------------------------- step 4


def test_step4_evaluation_fields(case_record, random_run):
    """Step 4: ThermalEvaluation fields; T_B_K and T_J_K copy the input temperatures and are not new states."""

    analyses, cases, params = random_run["analyses"], random_run["cases"], random_run["params"]
    results = []
    n = len(analyses)
    fields_ok = n > 0 and all(a["is_evaluation"] and a["fields"] == EVALUATION_FIELDS for a in analyses)
    shapes_ok = n > 0 and all(a["shapes"] == ((6,), (5,), (2,), (2,)) for a in analyses)
    run_time_ok = n > 0 and all(a["run_time_equal"] for a in analyses)
    results.append(case_record.check(
        CHECK_FIELDS,
        "每次返回 ThermalEvaluation，字段依次为 run_id、time_s、dT_dt_K_s、q_W、Q_env_W、Q_emit_W、T_B_K、T_J_K，"
        "数组维数 6、5、2、2，run_id 与 time_s 等于输入状态",
        f"{n} 组：类型与字段一致 {fields_ok}，字段 {analyses[0]['fields'] if n else None}；维数一致 {shapes_ok}，"
        f"{analyses[0]['shapes'] if n else None}；run_id 与 time_s 一致 {run_time_ok}",
        n == N_RANDOM and fields_ok and shapes_ok and run_time_ok,
    ))
    q_max = _worst(a["q_rel_max"] for a in analyses)
    env_max = _worst(a["env_rel_max"] for a in analyses)
    emit_max = _worst(a["emit_rel_max"] for a in analyses)
    results.append(case_record.check(
        CHECK_CONTENT,
        "q_W 按 SR、JC、CR、BR、DR 等于独立 T2，Q_env_W 与 Q_emit_W 按 S、R 等于独立 T4，相对偏差 ≤ 1e-12",
        f"{n} 组最大相对偏差：q_W {q_max:.3e}，Q_env_W {env_max:.3e}，Q_emit_W {emit_max:.3e}",
        n == N_RANDOM and q_max <= REL_TOL and env_max <= REL_TOL and emit_max <= REL_TOL,
    ))
    copies_ok = n > 0 and all(a["T_B_equal"] and a["T_J_equal"] for a in analyses)
    moving_B = sum(1 for a in analyses if math.isfinite(a["dT_B"]) and a["dT_B"] != 0.0)
    moving_J = sum(1 for a in analyses if math.isfinite(a["dT_J"]) and a["dT_J"] != 0.0)
    results.append(case_record.check(
        CHECK_COPIES,
        "每组 T_B_K = temperature_K[3]、T_J_K = temperature_K[1]，为 float 且逐位相同；温度导数不为零时也未推进",
        f"{n} 组逐位相同 {copies_ok}；其中 dT_B/dt 不为零 {moving_B} 组，dT_J/dt 不为零 {moving_J} 组",
        n == N_RANDOM and copies_ok and moving_B > 0 and moving_J > 0,
    ))

    # Every random set a second time with the same state, inputs and parameters: the record is the same bit for bit,
    # the inputs are unchanged and the record cannot be written, so T_B_K and T_J_K cannot become integrated states.
    tally = dict.fromkeys(NOT_STATE_ITEMS, 0)
    repeat_errors: list[str] = []
    example = None
    for k, case in enumerate(cases):
        state, inputs, first = case["state"], case["inputs"], case["evaluation"]
        temperature_in = np.array([case["temperature"][node] for node in ref.NODES], dtype=float)
        T_B_in, T_J_in = float(temperature_in[I_B]), float(temperature_in[I_J])
        try:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                second = thermal_derivative(state, inputs, params)
        except Exception as exc:  # noqa: BLE001  recorded as a failed repeat, never as a pass
            repeat_errors.append(f"case {k}: {type(exc).__name__}: {exc}")
            continue
        tally["no_state_field"] += (not hasattr(second, "temperature_K")
                                    and np.shape(second.dT_dt_K_s) == (len(ref.NODES),))
        tally["repeat"] += _same_record(first, second)
        tally["state"] += (state.run_id == random_run["run_id"] and _bitwise_equal(state.time_s, case["time_s"])
                           and isinstance(state.temperature_K, np.ndarray)
                           and _bitwise_equal(state.temperature_K, temperature_in)
                           and not state.temperature_K.flags.writeable)
        tally["ports"] += all(_bitwise_equal(getattr(inputs, port), float(case["ports"][port])) for port in ref.PORTS)
        tally["environment"] += _same_environment(inputs.environment, case["environment"])
        tally["copies"] += _bitwise_equal(second.T_B_K, T_B_in) and _bitwise_equal(second.T_J_K, T_J_in)
        if example is None and case["environment"]["G_W_m2"] > 0.0:
            example = {"index": k, "dT_B_K_s": float(second.dT_dt_K_s[I_B]), "T_B_K": second.T_B_K, "T_B_in_K": T_B_in,
                       "dT_J_K_s": float(second.dT_dt_K_s[I_J]), "T_J_K": second.T_J_K, "T_J_in_K": T_J_in}
        # Write attempts last: a record that accepted a write is not used afterwards.
        tally["arrays"] += all(_array_locked(getattr(second, name)) for name in ARRAY_FIELDS)
        tally["fields"] += all(_field_locked(second, name) for name in EVALUATION_FIELDS)
    n_cases = len(cases)
    not_state_ok = (n_cases == N_RANDOM and not repeat_errors
                    and all(tally[key] == n_cases for key in NOT_STATE_ITEMS))
    actual = (f"{n_cases} 组逐组再调用一次，报错 {len(repeat_errors)} 组 {repeat_errors[:3]}；"
              + "；".join(f"{label} {tally[key]} 组" for key, label in NOT_STATE_ITEMS.items()))
    if example is not None:
        actual += (f"；示例第 {example['index']} 组日照输入 dT_B/dt = {example['dT_B_K_s']:.6g} K/s 时 T_B_K = "
                   f"{example['T_B_K']!r} K，输入 {example['T_B_in_K']!r} K；dT_J/dt = {example['dT_J_K_s']:.6g} K/s 时 "
                   f"T_J_K = {example['T_J_K']!r} K，输入 {example['T_J_in_K']!r} K")
    results.append(case_record.check(
        CHECK_NOT_STATE,
        "1000 组逐组再调用一次：ThermalEvaluation 没有温度数组，dT_dt_K_s 只有六个节点分量；重复调用结果逐位相同；"
        "输入状态、四个功率与环境输入不被修改；四个数组拒绝写入且不能恢复可写，八个字段拒绝改写；"
        "温度导数不为零时 T_B_K 与 T_J_K 仍等于输入温度",
        actual,
        not_state_ok,
    ))
    case_record.metric("evaluation_fields", {
        "fields": list(EVALUATION_FIELDS), "cases": n, "q_W_max_rel": q_max, "Q_env_W_max_rel": env_max,
        "Q_emit_W_max_rel": emit_max, "T_B_T_J_copies_bitwise": copies_ok, "dT_B_nonzero_cases": moving_B,
        "dT_J_nonzero_cases": moving_J,
        "repeat_call": {"cases": n_cases, "n_errors": len(repeat_errors), "errors": repeat_errors[:5], **tally,
                        "example": example},
    })
    assert all(results)


# --------------------------------------------------------------------------- summary


def _summary_battery(battery: dict | None) -> str:
    if not battery:
        return "电池算例未完成计算。"
    rate = _g(DESIGN_RATE_K_S)
    text = (
        f"按设计报告第 4.3 节电池算例装配参数，$C_B$ 为 {_g(battery['C_B_J_K'])} J/K，$R_BR$ 为 "
        f"{_g(battery['R_BR_K_W'])} K/W，$T_B$ 为 {_g(battery['T_B_K'])} K，$T_R$ 为 {_g(battery['T_R_K'])} K，$Q_B$ 为 "
        f"{_g(battery['Q_B_W'])} W。thermal_derivative 给出 $q_BR$ 为 {_g(battery['q_BR_W'])} W，$C_B$ 与电池温升速度之积为 "
        f"{_g(battery['retained_W'])} W，电池温升速度为 {_g(battery['dT_B_dt_K_s'])} K/s，与 {rate} K/s 之差为 "
        f"{_sci(battery['error_K_s'])} K/s，验收限值为 {LIMIT_CN} K/s。"
    )
    variants = battery["variants"]
    deviation = _sci(battery["variants_max_error_K_s"])
    if variants == N_BATTERY_VARIANTS:
        return text + (f"其余节点温度、功率与环境另取 {variants} 组随机值时，电池温升速度与 {rate} K/s 之差最大为 "
                       f"{deviation} K/s。")
    if variants:
        return text + (f"其余节点温度、功率与环境另取 {N_BATTERY_VARIANTS} 组随机值，完成计算 {variants} 组，电池温升速度与 "
                       f"{rate} K/s 之差最大为 {deviation} K/s。")
    return text + f"其余节点温度、功率与环境另取的 {N_BATTERY_VARIANTS} 组随机值均未完成计算。"


def _summary_random(rc: dict | None) -> str:
    if not rc:
        return "随机输入的整体热平衡未完成计算。"
    cov = rc["coverage"]
    low, high = rc["t1_rhs_range_W"]
    range_text = ("未出现 ThermalRangeWarning" if cov["range_warnings"] == 0
                  else f"出现 ThermalRangeWarning {cov['range_warnings']} 次")
    unit = IRRADIANCE_UNIT_CN
    return (
        f"用固定随机种子生成 {rc['n_requested']} 组输入。温度在各节点适用温度范围内均匀取值；卫星位置、太阳位置与姿态四元数"
        f"随机取值，日照时太阳辐照度取 {_g(G_SUNLIT_W_M2[0])} 至 {_g(G_SUNLIT_W_M2[1])} {unit}，各表面地球反照取 0 至 "
        f"{_g(ALBEDO_MAX_W_M2)} {unit}，地球红外取 {_g(INFRARED_W_M2[0])} 至 {_g(INFRARED_W_M2[1])} {unit}，由 "
        f"prepare_surface_environment 准备环境输入；$P_load$ 取 0 至 {_g(P_LOAD_MAX_W)} W，$Q_B$ 取 "
        f"{MINUS}{_g(Q_B_ABS_MAX_W)} W 至 {_g(Q_B_ABS_MAX_W)} W，$Q_D$ 取 0 至 {_g(Q_D_MAX_W)} W，$P_pv$ 取 0 至 "
        f"absorbed_solar_S_W。完成计算 {rc['n_evaluated']} 组，其中日食 {cov['eclipse']} 组，$Q_B$ 为负值 "
        f"{cov['Q_B_negative']} 组，$P_pv$ 为零 {cov['P_pv_zero']} 组，$P_pv$ 等于 absorbed_solar_S_W "
        f"{cov['P_pv_at_absorbed']} 组；prepare_surface_environment 给出的入射角余弦与独立的四元数旋转计算之差最大为 "
        f"{_sci(rc['cos_incidence_max_diff'])}，限值为 {LIMIT_CN}，{range_text}。按独立实现的 T4 与输入功率计算 T1 右侧，"
        f"T1 右侧在 {_num(low, 1)} W 至 {_num(high, 1)} W 之间，各组件热容与温度导数的乘积之和与 T1 右侧的残差最大为 "
        f"{_sci(rc['t1_residual_max_W'])} W，残差与输入总功率之比最大为 {_sci(rc['t1_ratio_max_heat_input'])}，验收限值为 "
        f"{LIMIT_CN}。输入总功率取太阳能板与散热板的环境吸热、$P_load$、$Q_D$ 与正值 $Q_B$ 之和，最小为 "
        f"{_num(rc['p_in_heat_min_W'], 1)} W；改取环境吸热与四个功率绝对值之和时比值最大为 "
        f"{_sci(rc['t1_ratio_max_ports_input'])}，改取 T1 右侧八项绝对值之和时比值最大为 {_sci(rc['t1_ratio_max_gross'])}。"
    )


def _summary_sign(m: dict, passed) -> str:
    detail = m.get("sign_bookkeeping_detail")
    lead = "逐条将 SR、JC、CR、BR、DR 的热阻经 overrides 加倍，并在两端温差为正与为负时各计算一次"
    if detail is None:
        text = "热流符号检查未完成。"
    else:
        failures = detail["failed_conditions"]
        paths = [path for path, _, _ in ref.PATHS]
        bad = [p for p in paths if failures.get(p) or not passed(f"步骤 3 热流 {p} ")]
        if not bad:
            rest = ("其余四个节点的改变量逐位为零" if detail["rest_exact_zero"]
                    else f"其余四个节点改变量的相对偏差最大为 {_sci(detail['rest_max_rel'])}")
            text = (
                f"{lead}。热阻加倍前后该热流均保留符号并等于 T2 手算值，其余四条热流不变；路径名称中第一个节点储存热能的变化率"
                f"改变量等于该热流改变量的相反数，第二个节点的改变量等于该热流改变量，相对偏差最大为 "
                f"{_sci(detail['ends_max_rel'])}，{rest}，六个节点改变量之和与 T3 各项绝对值之和之比最大为 "
                f"{_sci(detail['sum_max_rel'])}，限值均为 {LIMIT_CN}，每条热流在第一个节点减去、在第二个节点加上。"
            )
        else:
            good = [p for p in paths if p not in bad]
            clauses = []
            for p in bad:
                reasons = failures.get(p) or ["的检查未通过"]
                clauses.append(f"热流 {p} " + "，".join(reasons))
            text = (f"{lead}，" + (f"热流 {'、'.join(good)} 的各项检查均符合；" if good else "")
                    + "；".join(clauses) + "。")
    rows = m.get("t3_rows_max_rel")
    n_rows = m.get("t3_rows_evaluated", 0)
    if rows is None:
        return text + "随机输入下与 T3 各行的比较未完成。"
    if not n_rows:
        return text + "随机输入未完成计算，未与 T3 各行比较。"
    return text + (f"{n_rows} 组随机输入下，六个节点热容与温度导数的乘积与独立实现的 T3 各行之差，与该行各项绝对值之和之比"
                   f"最大为 {_sci(_worst(rows.values()))}，限值为 {LIMIT_CN}。")


def _summary_fields(fields: dict | None, passed) -> str:
    if not fields:
        return "ThermalEvaluation 字段检查未完成。"
    n = fields["cases"]
    if passed(CHECK_FIELDS):
        field_text = (f"{n} 组返回值均为 ThermalEvaluation，依次含 run_id、time_s、dT_dt_K_s、q_W、Q_env_W、Q_emit_W、"
                      "T_B_K 与 T_J_K，没有温度数组，数组维数为 6、5、2、2，run_id 与 time_s 等于输入状态")
    else:
        field_text = "ThermalEvaluation 的类型、字段、维数或运行标识与设计报告表 6 不符"
    content = _worst([fields["q_W_max_rel"], fields["Q_env_W_max_rel"], fields["Q_emit_W_max_rel"]])
    content_text = f"q_W、Q_env_W 与 Q_emit_W 与独立计算的相对偏差最大为 {_sci(content)}，限值为 {LIMIT_CN}"
    if fields["T_B_T_J_copies_bitwise"]:
        copy_text = (f"{n} 组的 T_B_K 与 T_J_K 均与本次输入的电池温度和计算节点温度逐位相同，其中电池温度导数不为零 "
                     f"{fields['dT_B_nonzero_cases']} 组，计算节点温度导数不为零 {fields['dT_J_nonzero_cases']} 组")
    else:
        copy_text = "部分组的 T_B_K 或 T_J_K 与本次输入温度不同"
    repeat = fields.get("repeat_call")
    if not repeat:
        state_text = "再调用检查未完成"
    elif passed(CHECK_NOT_STATE):
        state_text = (f"对这 {repeat['cases']} 组输入各再调用一次 thermal_derivative，两次结果逐位相同，输入状态、四个功率与"
                      "环境输入未被修改，返回记录的四个数组拒绝写入且不能恢复为可写，八个字段均拒绝改写")
    else:
        total = repeat["cases"]
        pieces = []
        if total != N_RANDOM:
            pieces.append(f"随机输入只完成 {total} 组，少于 {N_RANDOM} 组")
        if repeat["n_errors"]:
            pieces.append(f"再调用报错 {repeat['n_errors']} 组")
        for key, label in NOT_STATE_ITEMS.items():
            if repeat[key] != total:
                lead = "满足 " if label[0].isascii() else "满足"
                pieces.append(f"{lead}{label}的只有 {repeat[key]} 组")
        state_text = f"对 {total} 组输入各再调用一次 thermal_derivative，" + "，".join(pieces or ["该项检查未通过"])
    return f"{field_text}；{content_text}；{copy_text}。{state_text}。"


def _anomalies(checks: list[dict]) -> str:
    """Every failed check, every interrupted test function and every expected check that was not recorded."""

    failed, interrupted = [], []
    for c in checks:
        if c["passed"]:
            continue
        if c["name"].startswith("test_"):
            if "assert all(results)" in c["actual"]:
                continue  # the explicit failed checks of that test function are listed already
            function = c["name"].split(" ")[0]
            if function not in interrupted:
                interrupted.append(function)
        else:
            failed.append(c["name"])
    recorded = {c["name"] for c in checks}
    missing = [name for name in _expected_checks() if name not in recorded]
    pieces = []
    if failed:
        pieces.append("以下检查未通过：" + "；".join(failed) + "。")
    if interrupted:
        pieces.append("测试函数 " + "、".join(interrupted) + " 执行中断。")
    if missing:
        pieces.append("以下检查未执行：" + "；".join(missing) + "。")
    return "".join(pieces) or "无"


def test_summary(case_record):
    """Chinese summary and anomaly record of the case from the checks and metrics above."""

    m = case_record.metrics

    def passed(prefix: str) -> bool:
        outcomes = [c["passed"] for c in case_record.checks if c["name"].startswith(prefix)]
        return bool(outcomes) and all(outcomes)

    parts = [
        _summary_battery(m.get("battery_example")),
        _summary_random(m.get("random_cases")),
        _summary_sign(m, passed),
        _summary_fields(m.get("evaluation_fields"), passed),
    ]
    case_record.summary("".join(parts))
    case_record.anomalies(_anomalies(case_record.checks))
    assert case_record.summary_cn
