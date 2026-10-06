"""DM-001 公共数据对象.

Test case DM-001 of the SDTwin thermal test report. It checks the four common data objects of thermal design 5.1
table 6 (ThermalParameters, ThermalState, ThermalInputs, ThermalEvaluation): fields, array dimensions and orders
(design 1.4, table 6, 6.1), the sign of Q_B_W, the construction checks of 5.1 and 6.1, the read-only parameters and
the separation of trial and accepted states (5.1, 6.3, chapter 7; also through the coupled runner archive and its
trial hook), and the package exports of design 3.2 and appendix A.

References are independent of the code under test: ``tests/data/dm_001/reference.py`` evaluates T2 to T5 from the
report with scalar Python arithmetic and its own quaternion formula, and the coupled reference solution integrates
that right-hand side with SciPy DOP853 at rtol 1e-12. The battery parameters of the scenario are those of the design
4.3 battery example. That example has one worked value, Q_B = 10 W giving q_BR = 6 W and 0.004 K/s, which step 3
checks literally; the value for Q_B_W = -10 W is T3 evaluated with the same parameters and is not part of the example.

Step 6 compares the exports with appendix A as a set: the public names of the package (its ``__all__`` and every
public non-module name its namespace binds) must be the four data types and five functions of appendix A plus, at
most, the error and warning classes that Thermal/IMPLEMENTATION.md allows ``__init__.py`` to export.

The Chinese summary is built from the recorded checks. Each statement is written only when every check behind it
passed and the test function recording those checks ran to its end; otherwise the statement reports the failure.
The summary and the anomalies are checked against the report text rules before they are stored.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import importlib
import importlib.util
import inspect
import json
import math
import operator
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from scipy.integrate import solve_ivp

import thermal
from sdtwin_sim import coupled as cp
from sdtwin_sim import power_stand_in as ps
from thermal import (
    ThermalConfigurationError,
    ThermalEvaluation,
    ThermalInputError,
    ThermalInputs,
    ThermalParameters,
    ThermalState,
    assemble_thermal_parameters,
    calculate_heat_flows,
    calculate_surface_heat,
    prepare_surface_environment,
    thermal_derivative,
)

pytestmark = pytest.mark.case("DM-001")

DATA_DIR = Path(__file__).resolve().parent / "data" / "dm_001"
_SPEC = importlib.util.spec_from_file_location("dm001_reference", DATA_DIR / "reference.py")
ref = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ref)

SC = ref.load_scenario()
RUN_ID = SC["run_id"]
EPOCH = datetime.fromisoformat(SC["epoch_utc"])
T0_S = float(SC["time_s"])
T_BY_NODE = {node: float(SC["temperature_K"][node]) for node in ref.NODES}
T_LIST = [T_BY_NODE[node] for node in ref.NODES]
PORTS = {name: float(value) for name, value in SC["ports_W"].items()}
EXAMPLE = ref.DESIGN_43_BATTERY_EXAMPLE
BATTERY_RANGE_K = tuple(
    float(value)
    for component in SC["components"]
    if component["instance_id"] == "Battery01"
    for value in component["temperature_range_K"]
)
REL_TOL = 1e-12  # pure arithmetic of T2 to T5: only rounding separates the module from the reference
ACCEPTED_REF_TOL_K = 1e-5  # accepted states against the independent DOP853 solution (module rtol 1e-9, 1200 s)
RETRY_START_TOL_K = 1e-9  # stage-2 state of an RK45 attempt against y_start + (t2 - t_start) f(t_start, y_start)
EXAMPLE_TOL_K_S = 1e-15  # battery derivative against the design 4.3 example and the T3 hand values
N_STAGES_RK45 = 6  # SciPy RK45: 5 stage evaluations and the end-point derivative per attempt
C2_RK45 = 0.2  # SciPy RK45: second stage at t + h/5 with y + (h/5) f(t, y)
MINUS = "−"


# ------------------------------------------------------------------------------------------------- check ledger

# Topic of every check: the statement of the Chinese summary it supports, the test function that records it and the
# subject named when the statement cannot be made. test_summary writes a statement only when every check of its topic
# passed and that function reached its end (Checks.assert_all).
TOPICS: dict[str, tuple[str, str]] = {
    "fields": ("test_step1_fields_and_shapes", "表 6 字段名称、顺序与不可赋值的检查"),
    "shapes": ("test_step1_fields_and_shapes", "数组维数、正值、运行标识、时刻与功率字段的检查"),
    "records": ("test_step1_fields_and_shapes", "表面记录、实例对应与来源记录的检查"),
    "orders": ("test_step2_orders", "数组顺序与独立手算的检查"),
    "q_b_sign": ("test_step3_q_b_sign", "电池热源符号与第 4.3 节算例的检查"),
    "invalid": ("test_step4_invalid_constructions", "异常构造的检查"),
    "read_only": ("test_step5_parameters_read_only", "参数只读的检查"),
    "state_module": ("test_step5_trial_and_accepted_states_module", "函数调用中试算状态与已接受状态分离的检查"),
    "in_run_params": ("test_step5_coupled_trial_and_accepted_records", "运行开始后参数只读的检查"),
    "in_run_trial": ("test_step5_coupled_trial_and_accepted_records", "试算记录写入尝试的检查"),
    "trials": ("test_step5_coupled_trial_and_accepted_records", "仅含热模型的联合计算中试算状态与已接受状态分离的检查"),
    "power": ("test_step5_power_coupled_trial_states", "含 Power 的联合计算的检查"),
    "event": ("test_step5_event_search_trial_states", "事件定位联合计算的检查"),
    "package": ("test_step6_package_exports", "包文件与附录 A 名称导出的检查"),
    "namespace": ("test_step6_package_exports", "包命名空间与 __all__ 的检查"),
    "appendix_exact": ("test_step6_package_exports", "公共导出与附录 A 一致的检查"),
    "power_names": ("test_step6_package_exports", "热模块未重新实现 Power 接口的检查"),
    "text": ("test_summary", "结果说明文字规则的检查"),
}
_LEDGER: list[dict[str, Any]] = []  # one entry per check: label, topic, test function, passed, cause for the anomalies
_RUNS: dict[str, str] = {}  # test function -> "started" when its Checks is created, "completed" at assert_all


def _is_true(value: Any) -> bool:
    """Only a real boolean True passes; NaN, None or any other object is a failure (bool(nan) would be True)."""

    return isinstance(value, (bool, np.bool_)) and bool(value)


class Checks:
    """Records every check in the case evidence and in the ledger, and keeps the failures of one test function."""

    def __init__(self, record: Any, step: str, topic: str) -> None:
        if topic not in TOPICS:
            raise KeyError(f"unknown summary topic {topic!r}")
        self.record = record
        self.step = step
        self.topic = topic
        self.func = sys._getframe(1).f_code.co_name
        self.failed: list[str] = []
        self.count = 0
        _RUNS[self.func] = "started"

    def __call__(
        self, name: str, expected: Any, actual: Any, passed: Any, *, topic: str | None = None, cause: str | None = None
    ) -> bool:
        topic = topic or self.topic
        if topic not in TOPICS:
            raise KeyError(f"unknown summary topic {topic!r}")
        label = f"{self.step} {name}"
        ok = _is_true(passed)
        if not isinstance(passed, (bool, np.bool_)):
            actual = f"{actual}；判定值 {passed!r} 不是布尔值，按未通过处理"
        self.record.check(label, expected, actual, ok)
        _LEDGER.append({"label": label, "topic": topic, "func": self.func, "passed": ok, "cause": cause})
        self.count += 1
        if not ok:
            self.failed.append(label)
        return ok

    def assert_all(self) -> None:
        _RUNS[self.func] = "completed"
        assert not self.failed, "failed checks: " + " | ".join(self.failed)


# ---------------------------------------------------------------------------------------------- numbers and text


def describe(exc: BaseException | None) -> str:
    if exc is None:
        return "未报错"
    return f"{type(exc).__name__}: {exc}"[:600]


def rel_err(actual: Any, expected: Any) -> float:
    a = np.asarray(actual, dtype=float)
    e = np.asarray(expected, dtype=float)
    return float(np.max(np.abs(a - e) / np.maximum(np.abs(e), 1e-300)))


def worst(values: Any) -> float:
    """Largest value; NaN when there is none or any value is NaN (Python max() keeps an earlier value over a NaN)."""

    array = np.asarray(list(values), dtype=float)
    if array.size == 0 or bool(np.isnan(array).any()):
        return float("nan")
    return float(array.max())


def least(values: Any) -> float:
    """Smallest value; NaN when there is none or any value is NaN."""

    array = np.asarray(list(values), dtype=float)
    if array.size == 0 or bool(np.isnan(array).any()):
        return float("nan")
    return float(array.min())


def fixed(value: float, significant: int = 2) -> str:
    """Decimal text without exponent, with the U+2212 minus sign."""

    if not math.isfinite(value):
        return "非有限值"
    if value == 0.0:
        return "0"
    decimals = max(0, -math.floor(math.log10(abs(value))) + significant - 1)
    return f"{value:.{decimals}f}".replace("-", MINUS)


def magnitude(value: Any, significant: int = 2) -> str:
    """Number for the Chinese text: 0, a decimal, or a×10^{−n} below 1×10^{−4}; U+2212 for every minus sign."""

    if value is None:
        return "未记录"
    value = float(value)
    if not math.isfinite(value):
        return "非有限值"
    if value == 0.0:
        return "0"
    if abs(value) >= 1e-4:
        return fixed(value, significant)
    exponent = math.floor(math.log10(abs(value)))
    mantissa = round(value / 10.0**exponent, significant - 1)
    if abs(mantissa) >= 10.0:
        mantissa /= 10.0
        exponent += 1
    text = f"{mantissa:.{significant - 1}f}".rstrip("0").rstrip(".").replace("-", MINUS)
    return f"{text}×10^{{{MINUS}{-exponent}}}"


def number(value: Any) -> str:
    if value is None:
        return "未记录"
    value = float(value)
    if not math.isfinite(value):
        return "非有限值"
    text = f"{value:.10g}"
    if "e" in text:
        return magnitude(value, 3)
    return text.replace("-", MINUS)


def decimals(value: Any, places: int) -> str:
    if value is None:
        return "未记录"
    value = float(value)
    if not math.isfinite(value):
        return "非有限值"
    return f"{value:.{places}f}".replace("-", MINUS)


def join_cn(items: list[Any]) -> str:
    items = [str(item) for item in items]
    if not items:
        return "无"
    if len(items) == 1:
        return items[0]
    return "、".join(items[:-1]) + " 与 " + items[-1]


# Report text rules for summary_cn and anomalies_cn: no brackets of any kind, no dashes, no question marks, minus signs
# as U+2212 and powers of ten as 1×10^{−12}, where the builder renders ^{...} as a superscript (the only brace allowed).
_POWER_OF_TEN = re.compile(r"\^\{−?\d+\}")
_BRACKETS = (
    "()[]{}<>（）［］【】｛｝＜＞《》〈〉"
    "「」『』〔〕"
)
_DASHES = "-‐‑‒–—―﹣－"
_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"
_SCIENTIFIC = re.compile(r"(?<![\w.])([+\-−]?)(\d+(?:\.\d+)?)[eE]([+\-−]?)(\d+)(?![\w.])")


def text_rule_problems(text: str) -> list[str]:
    """Violations of the report text rules in ``text``."""

    rest = _POWER_OF_TEN.sub("", text)
    problems = []
    if any(ch in _BRACKETS for ch in rest):
        problems.append("括号")
    if any(ch in _DASHES for ch in rest):
        problems.append("破折号或连字符")
    if "?" in rest or "？" in rest:
        problems.append("问号")
    if re.search(r"\d[eE][+\-−]?\d", rest):
        problems.append("科学计数法")
    if any(ch in _SUPERSCRIPTS for ch in rest):
        problems.append("上标字符")
    if "^" in rest:
        problems.append("10 的幂以外的上标标记")
    if "$" in rest or "**" in rest:
        problems.append("排版标记")
    return problems


def _scientific_text(match: re.Match) -> str:
    sign, mantissa, exponent_sign, exponent = match.groups()
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".") or "0"
    if float(mantissa) == 0.0:
        return "0"
    prefix = MINUS if sign in ("-", MINUS) else ""
    power = int(exponent)
    if power == 0:
        return prefix + mantissa
    return f"{prefix}{mantissa}×10^{{{MINUS if exponent_sign in ('-', MINUS) else ''}{power}}}"


def _clean_fragment(text: str) -> str:
    s = text.replace("<=", " ≤ ").replace(">=", " ≥ ").replace("!=", " ≠ ").replace("==", " = ")
    s = s.replace("'", "").replace('"', "")
    for ch in _BRACKETS:
        s = s.replace(ch, " ")
    for ch in ("?", "？", "$", "^", "*"):
        s = s.replace(ch, " " if ch == "*" else "")
    s = s.translate(str.maketrans(_SUPERSCRIPTS, "0123456789" + MINUS + "+"))
    s = _SCIENTIFIC.sub(_scientific_text, s)
    s = re.sub(r"-(?=[\d.]|inf|nan)", MINUS, s)
    for ch in _DASHES:
        s = s.replace(ch, " ")
    return s


def clean_text(text: Any, limit: int | None = None) -> str:
    """``text`` rewritten to the report text rules; existing 1×10^{−n} markup is kept."""

    s = str(text)
    if limit is not None and len(s) > limit:
        s = s[:limit].rstrip() + " 等"
    pieces = _POWER_OF_TEN.split(s)
    tokens = _POWER_OF_TEN.findall(s)
    out = []
    for index, piece in enumerate(pieces):
        out.append(_clean_fragment(piece))
        if index < len(tokens):
            out.append(tokens[index])
    return re.sub(r"[ \t\r\n]+", " ", "".join(out)).strip()


# ---------------------------------------------------------------------------------------------- scenario helpers


def build_parameters() -> ThermalParameters:
    return assemble_thermal_parameters(copy.deepcopy(SC["components"]), copy.deepcopy(SC["connections"]), None)


def asset_surface_ids() -> list[str]:
    return [surface["surface_id"] for surface in ref.surfaces_in_asset_order(SC["components"])]


def orbit_input(run_id: str = RUN_ID, time_s: float = T0_S) -> dict[str, Any]:
    orbit = SC["orbit_input"]
    return {
        "run_id": run_id,
        "time_s": time_s,
        "epoch": EPOCH,
        "position_m": list(orbit["position_m"]),
        "sun_position_m": list(orbit["sun_position_m"]),
        "frame": orbit["frame"],
        "quaternion_xyzw": list(orbit["quaternion_xyzw"]),
        "G_W_m2": float(orbit["G_W_m2"]),
    }


def earth_flux(run_id: str = RUN_ID, time_s: float = T0_S) -> dict[str, Any]:
    ids = asset_surface_ids()
    flux = SC["earth_flux_W_m2"]
    return {
        "run_id": run_id,
        "time_s": time_s,
        "surface_ids": ids,
        "albedo_W_m2": [float(flux["albedo"][sid]) for sid in ids],
        "infrared_W_m2": [float(flux["infrared"][sid]) for sid in ids],
    }


def environment(params: ThermalParameters, run_id: str = RUN_ID, time_s: float = T0_S) -> dict[str, Any]:
    return prepare_surface_environment(orbit_input(run_id, time_s), earth_flux(run_id, time_s), params)


def hand_values(temperature: dict[str, float], ports: dict[str, float]) -> dict[str, Any]:
    """T2 to T5 for the scenario, from the independent reference."""

    components = SC["components"]
    capacitance = ref.capacitance_by_node(components)
    resistance = ref.resistance_by_path(SC["connections"])
    surfaces = ref.surfaces_in_asset_order(components)
    orbit = SC["orbit_input"]
    cosines = [ref.cos_incidence(orbit, surface["normal_body"]) for surface in surfaces]
    albedo = [SC["earth_flux_W_m2"]["albedo"][surface["surface_id"]] for surface in surfaces]
    infrared = [SC["earth_flux_W_m2"]["infrared"][surface["surface_id"]] for surface in surfaces]
    q_env, q_emit, direct_s = ref.surface_heat(temperature, surfaces, float(orbit["G_W_m2"]), cosines, albedo, infrared)
    flows = ref.heat_flows(temperature, resistance)
    rates = ref.derivatives(temperature, capacitance, resistance, q_env, q_emit, ports)
    scale = {
        "S": (q_env["S"] + ports["P_pv_W"] + abs(flows["SR"]) + q_emit["S"]) / capacitance["S"],
        "J": (ports["P_load_W"] + abs(flows["JC"])) / capacitance["J"],
        "C": (abs(flows["JC"]) + abs(flows["CR"])) / capacitance["C"],
        "B": (abs(ports["Q_B_W"]) + abs(flows["BR"])) / capacitance["B"],
        "D": (ports["Q_D_W"] + abs(flows["DR"])) / capacitance["D"],
        "R": (abs(flows["SR"]) + abs(flows["CR"]) + abs(flows["BR"]) + abs(flows["DR"]) + q_env["R"] + q_emit["R"])
        / capacitance["R"],
    }
    return {
        "C": capacitance, "R": resistance, "surfaces": surfaces, "cosines": cosines, "q_env": q_env,
        "q_emit": q_emit, "direct_s": direct_s, "q": flows, "rates": rates, "rate_scale": scale,
    }


def plain(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return [plain(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def snapshot(params: ThermalParameters) -> dict[str, Any]:
    """Bit-level copy of every field of a ThermalParameters for before/after comparisons."""

    return {
        "C_J_K": params.C_J_K.tobytes(),
        "R_K_W": params.R_K_W.tobytes(),
        "surfaces": json.dumps(
            [[s.surface_id, s.node_id, s.area_m2, s.normal_body.tobytes().hex(), s.absorptivity, s.emissivity]
             for s in params.surfaces]
        ),
        "instance_map": json.dumps(plain(params.instance_map), sort_keys=True),
        "provenance": json.dumps(plain(params.provenance), sort_keys=True, default=repr),
    }


def state_snapshot(obj: Any) -> str:
    """Bit-level text of every field of a ThermalState, ThermalInputs or ThermalEvaluation."""

    parts = {}
    for item in dataclasses.fields(obj):
        value = getattr(obj, item.name)
        if isinstance(value, np.ndarray):
            parts[item.name] = value.tobytes().hex()
        elif hasattr(value, "items"):
            parts[item.name] = {
                key: (val.tobytes().hex() if isinstance(val, np.ndarray) else repr(val)) for key, val in value.items()
            }
        else:
            parts[item.name] = repr(value)
    return json.dumps(parts, sort_keys=True)


def _write_through_base(array: np.ndarray) -> None:
    """Make ``array`` writeable through the last ndarray of its base chain, then write one element."""

    owner = array
    while isinstance(owner.base, np.ndarray):
        owner = owner.base
    owner.setflags(write=True)
    array.setflags(write=True)
    array.flat[0] = 1.0


def provider_for(params: ThermalParameters, run_id: str) -> cp.EnvironmentProvider:
    """Constant orbit, attitude, irradiance and Earth flux of the scenario as an analytic environment provider."""

    orbit = SC["orbit_input"]
    flux = SC["earth_flux_W_m2"]
    position = np.array(orbit["position_m"], dtype=float)
    sun = np.array(orbit["sun_position_m"], dtype=float)
    quaternion = np.array(orbit["quaternion_xyzw"], dtype=float)
    irradiance = float(orbit["G_W_m2"])

    def earth_flux_record(run, time_s, position_m, sun_position_m, quaternion_xyzw, parameters):
        ids = [surface.surface_id for surface in parameters.surfaces]
        return {
            "run_id": run,
            "time_s": time_s,
            "surface_ids": ids,
            "albedo_W_m2": [float(flux["albedo"][sid]) for sid in ids],
            "infrared_W_m2": [float(flux["infrared"][sid]) for sid in ids],
        }

    return cp.EnvironmentProvider.from_callables(
        run_id=run_id,
        epoch=EPOCH,
        parameters=params,
        position=lambda t: position,
        sun_position=lambda t: sun,
        quaternion=lambda t: quaternion,
        G=lambda t: irradiance,
        earth_flux=earth_flux_record,
    )


def thermal_only_run(params: ThermalParameters, hook: Any) -> tuple[cp.CoupledArchive, list[Any]]:
    cfg = SC["coupled_thermal_only"]
    settings = cp.SolverSettings(**cfg["solver"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        archive = cp.run_coupled(
            params,
            ThermalState(cfg["run_id"], 0.0, T_LIST),
            provider_for(params, cfg["run_id"]),
            float(cfg["t_end_s"]),
            settings=settings,
            prescribed_ports=lambda t: dict(PORTS),
            trial_hook=hook,
        )
    return archive, list(caught)


def column(values: Any, index: int, width: int) -> np.ndarray:
    """Column ``index`` of a two-dimensional float array with ``width`` columns, or an empty array."""

    array = np.asarray(values, dtype=float)
    if array.ndim != 2 or array.shape[1] != width:
        return np.array([], dtype=float)
    return array[:, index]


# ------------------------------------------------------------------------------------- step 1: fields and shapes


def test_step1_fields_and_shapes(case_record):
    chk = Checks(case_record, "步骤1", "fields")
    params = build_parameters()
    env = environment(params)
    state = ThermalState(RUN_ID, T0_S, T_LIST)
    inputs = ThermalInputs(RUN_ID, T0_S, env, **PORTS)
    evaluation = thermal_derivative(state, inputs, params)
    objects = {
        "ThermalParameters": params, "ThermalState": state, "ThermalInputs": inputs, "ThermalEvaluation": evaluation,
    }

    field_lists = {}
    for name, obj in objects.items():
        names = tuple(item.name for item in dataclasses.fields(obj))
        values = {field: getattr(obj, field) for field in names}  # read every field
        field_lists[name] = list(names)
        chk(
            f"{name} 字段名称与顺序符合表 6",
            "、".join(ref.TABLE6_FIELDS[name]),
            "、".join(names) + f"；读取 {len(values)} 个字段",
            names == ref.TABLE6_FIELDS[name] and len(values) == len(names),
        )
        chk(
            f"{name} 为构造后不可赋值的记录",
            "dataclass frozen=True",
            f"frozen={getattr(type(obj), '__dataclass_params__').frozen}",
            getattr(type(obj), "__dataclass_params__").frozen,
        )

    for owner, field in (
        ("ThermalParameters", "C_J_K"), ("ThermalParameters", "R_K_W"), ("ThermalState", "temperature_K"),
        ("ThermalEvaluation", "dT_dt_K_s"), ("ThermalEvaluation", "q_W"), ("ThermalEvaluation", "Q_env_W"),
        ("ThermalEvaluation", "Q_emit_W"),
    ):
        value = getattr(objects[owner], field)
        shape = ref.TABLE6_SHAPES[field]
        ok = (
            isinstance(value, np.ndarray) and value.shape == shape and value.dtype == np.float64
            and bool(np.all(np.isfinite(value)))
        )
        chk(
            f"{owner}.{field} 维数",
            f"float64 数组，形状 {shape}，全部有限",
            f"{type(value).__name__}，dtype {getattr(value, 'dtype', None)}，形状 {getattr(value, 'shape', None)}，"
            f"值 {np.asarray(value).tolist()}",
            ok,
            topic="shapes",
        )

    for field, unit in (("C_J_K", "J/K"), ("R_K_W", "K/W")):
        value = getattr(params, field)
        chk(f"ThermalParameters.{field} 全部为正", f"全部 > 0 {unit}", value.tolist(), bool(np.all(value > 0.0)),
            topic="shapes")
    chk("ThermalState.temperature_K 全部为正", "全部 > 0 K", state.temperature_K.tolist(),
        bool(np.all(state.temperature_K > 0.0)), topic="shapes")

    for name in ("ThermalState", "ThermalInputs", "ThermalEvaluation"):
        obj = objects[name]
        chk(
            f"{name} run_id 与 time_s",
            f"run_id {RUN_ID!r}，time_s {T0_S!r} s 浮点数",
            f"run_id {obj.run_id!r}，time_s {obj.time_s!r} {type(obj.time_s).__name__}",
            obj.run_id == RUN_ID and type(obj.time_s) is float and obj.time_s == T0_S,
            topic="shapes",
        )
    port_values = {name: getattr(inputs, name) for name in ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")}
    chk(
        "ThermalInputs 四个功率字段",
        f"浮点数 {PORTS}",
        {name: f"{value!r} {type(value).__name__}" for name, value in port_values.items()},
        all(type(value) is float and value == PORTS[name] for name, value in port_values.items()),
        topic="shapes",
    )
    env_in = inputs.environment
    n_surfaces = len(asset_surface_ids())
    env_ok = (
        env_in["run_id"] == inputs.run_id and env_in["time_s"] == inputs.time_s
        and all(len(env_in[key]) == n_surfaces for key in ("surface_ids", "cos_incidence", "albedo_W_m2", "infrared_W_m2"))
    )
    chk(
        "ThermalInputs 环境与四个功率取同一时刻",
        f"environment run_id {RUN_ID!r}、time_s {T0_S!r} s 与 ThermalInputs 相同，表面数组长度 {n_surfaces}",
        f"environment run_id {env_in['run_id']!r}，time_s {env_in['time_s']!r}，长度 "
        f"{[len(env_in[key]) for key in ('surface_ids', 'cos_incidence', 'albedo_W_m2', 'infrared_W_m2')]}",
        env_ok,
        topic="shapes",
    )
    chk(
        "ThermalEvaluation T_B_K 与 T_J_K 为温度标量",
        "浮点数，单位 K",
        f"T_B_K {evaluation.T_B_K!r} {type(evaluation.T_B_K).__name__}，T_J_K {evaluation.T_J_K!r} "
        f"{type(evaluation.T_J_K).__name__}",
        type(evaluation.T_B_K) is float and type(evaluation.T_J_K) is float,
        topic="shapes",
    )

    # surfaces records (design 5.1)
    surfaces = params.surfaces
    expected_surfaces = ref.surfaces_in_asset_order(SC["components"])
    chk("surfaces 为记录元组", f"tuple，{len(expected_surfaces)} 条记录", f"{type(surfaces).__name__}，{len(surfaces)} 条",
        isinstance(surfaces, tuple) and len(surfaces) == len(expected_surfaces), topic="records")
    for record, expected in zip(surfaces, expected_surfaces):
        names = tuple(item.name for item in dataclasses.fields(record))
        normal = record.normal_body
        ok = (
            names == ref.SURFACE_FIELDS and record.surface_id == expected["surface_id"]
            and record.node_id == expected["node_id"] and record.node_id in ref.EXPOSED
            and record.area_m2 == expected["area_m2"] and record.absorptivity == expected["absorptivity"]
            and record.emissivity == expected["emissivity"] and isinstance(normal, np.ndarray)
            and normal.shape == (3,) and np.array_equal(normal, np.array(expected["normal_body"], dtype=float))
            and abs(float(np.linalg.norm(normal)) - 1.0) <= 1e-12
        )
        chk(
            f"surfaces 记录 {expected['surface_id']}",
            f"字段 {'、'.join(ref.SURFACE_FIELDS)}；node_id {expected['node_id']}，area_m2 {expected['area_m2']}，"
            f"normal_body[3] {expected['normal_body']} 单位长度，absorptivity {expected['absorptivity']}，"
            f"emissivity {expected['emissivity']}",
            f"字段 {'、'.join(names)}；node_id {record.node_id}，area_m2 {record.area_m2}，normal_body "
            f"{normal.tolist()} 形状 {normal.shape}，absorptivity {record.absorptivity}，emissivity {record.emissivity}",
            bool(ok),
            topic="records",
        )
    s_normals = [s.normal_body for s in surfaces if s.node_id == "S"]
    chk(
        "太阳能板正反面分开登记",
        "节点 S 有两条记录，法向相反",
        f"节点 S 记录 {[s.surface_id for s in surfaces if s.node_id == 'S']}，法向 {[n.tolist() for n in s_normals]}",
        len(s_normals) == 2 and np.allclose(s_normals[0], -s_normals[1], rtol=0.0, atol=1e-15),
        topic="records",
    )

    nodes = {node: set(instances) for node, instances in params.instance_map["nodes"].items()}
    chk(
        "instance_map 节点对应",
        f"{ {node: sorted(items) for node, items in ref.NODE_INSTANCES.items()} }；D 对应两个设备实例",
        {node: sorted(items) for node, items in nodes.items()},
        nodes == ref.NODE_INSTANCES,
        topic="records",
    )
    ports_map = dict(params.instance_map["ports"])
    chk("instance_map 四个功率端口实例", ref.PORT_INSTANCES, ports_map, ports_map == ref.PORT_INSTANCES,
        topic="records")
    provenance = params.provenance
    prov_ok = (
        tuple(provenance["node_order"]) == ref.NODES and tuple(provenance["path_order"]) == ref.PATHS
        and provenance["units"]["C_J_K"] == "J/K" and provenance["units"]["R_K_W"] == "K/W"
    )
    chk(
        "provenance 记录顺序与单位",
        f"node_order {ref.NODES}，path_order {ref.PATHS}，C_J_K 单位 J/K，R_K_W 单位 K/W",
        f"node_order {tuple(provenance['node_order'])}，path_order {tuple(provenance['path_order'])}，"
        f"units {dict(provenance['units'])}",
        prov_ok,
        topic="records",
    )
    case_record.metric("table6_field_lists", field_lists)
    case_record.metric("C_J_K_J_per_K", params.C_J_K.tolist())
    case_record.metric("R_K_W_K_per_W", params.R_K_W.tolist())
    case_record.metric("surface_records", len(surfaces))
    case_record.metric("step1_checks", chk.count)
    chk.assert_all()


# -------------------------------------------------------------------------------------------- step 2: orders


def test_step2_orders(case_record):
    chk = Checks(case_record, "步骤2", "orders")
    params = build_parameters()
    hand = hand_values(T_BY_NODE, PORTS)
    component_order = [component["instance_id"] for component in SC["components"]]
    connection_order = [connection["path"] for connection in SC["connections"]]

    expected_c = [hand["C"][node] for node in ref.NODES]
    err_c = rel_err(params.C_J_K, expected_c)
    chk(
        "C_J_K 按 S、J、C、B、D、R 保存 T5 热容",
        f"手算 {expected_c} J/K，相对误差 <= {REL_TOL:g}；组件输入顺序 {component_order}",
        f"{params.C_J_K.tolist()}，相对误差 {err_c:.3e}",
        err_c <= REL_TOL,
    )
    expected_r = [hand["R"][path] for path in ref.PATHS]
    err_r = rel_err(params.R_K_W, expected_r)
    chk(
        "R_K_W 按 SR、JC、CR、BR、DR 保存 T5 热阻",
        f"手算 {expected_r} K/W，相对误差 <= {REL_TOL:g}；连接输入顺序 {connection_order}",
        f"{params.R_K_W.tolist()}，相对误差 {err_r:.3e}",
        err_r <= REL_TOL,
    )

    state = ThermalState(RUN_ID, T0_S, T_LIST)
    chk(
        "temperature_K 按 S、J、C、B、D、R 保存",
        f"{T_LIST} K",
        state.temperature_K.tolist(),
        state.temperature_K.tolist() == T_LIST,
    )
    flows = calculate_heat_flows(state, params)
    expected_q = [hand["q"][path] for path in ref.PATHS]
    err_q = rel_err(flows["q_W"], expected_q)
    chk(
        "calculate_heat_flows 按 S、J、C、B、D、R 读取温度并按路径顺序给出 q_W",
        f"T2 手算 {expected_q} W，相对误差 <= {REL_TOL:g}",
        f"{flows['q_W'].tolist()}，相对误差 {err_q:.3e}",
        err_q <= REL_TOL,
    )

    env = environment(params)
    ids = tuple(asset_surface_ids())
    chk("环境数组按资产表面顺序", ids, tuple(env["surface_ids"]), tuple(env["surface_ids"]) == ids)
    cos_err = float(np.max(np.abs(np.asarray(env["cos_incidence"]) - np.asarray(hand["cosines"]))))
    chk(
        "cos_incidence 按资产表面顺序与独立计算一致",
        f"{hand['cosines']}，绝对误差 <= 1e-12",
        f"{np.asarray(env['cos_incidence']).tolist()}，绝对误差 {cos_err:.3e}",
        cos_err <= 1e-12,
    )

    inputs = ThermalInputs(RUN_ID, T0_S, env, **PORTS)
    surface = calculate_surface_heat(state, env, params)
    evaluation = thermal_derivative(state, inputs, params)
    expected_env = [hand["q_env"][node] for node in ref.EXPOSED]
    expected_emit = [hand["q_emit"][node] for node in ref.EXPOSED]
    gap_env = abs(expected_env[0] - expected_env[1])
    gap_emit = abs(expected_emit[0] - expected_emit[1])
    chk(
        "S 与 R 的吸热和辐射功率可区分",
        "两节点相差 > 1 W，顺序互换可被发现",
        f"Q_env 相差 {gap_env:.3f} W，Q_emit 相差 {gap_emit:.3f} W",
        gap_env > 1.0 and gap_emit > 1.0,
    )
    surface_errors: dict[str, list[float]] = {"Q_env_W": [], "Q_emit_W": []}
    for field, expected in (("Q_env_W", expected_env), ("Q_emit_W", expected_emit)):
        for source, value in (("ThermalEvaluation", getattr(evaluation, field)), ("calculate_surface_heat", surface[field])):
            err = rel_err(value, expected)
            surface_errors[field].append(err)
            chk(
                f"{source} {field} 按 S、R 排列",
                f"T4 手算 S {expected[0]!r} W，R {expected[1]!r} W，相对误差 <= {REL_TOL:g}",
                f"{np.asarray(value).tolist()}，相对误差 {err:.3e}",
                err <= REL_TOL,
            )
    err_eq = rel_err(evaluation.q_W, expected_q)
    chk(
        "ThermalEvaluation.q_W 按 SR、JC、CR、BR、DR 排列",
        f"T2 手算 {expected_q} W，相对误差 <= {REL_TOL:g}",
        f"{evaluation.q_W.tolist()}，相对误差 {err_eq:.3e}",
        err_eq <= REL_TOL,
    )
    expected_rates = np.array([hand["rates"][node] for node in ref.NODES])
    scales = np.array([hand["rate_scale"][node] for node in ref.NODES])
    scaled = float(np.max(np.abs(evaluation.dT_dt_K_s - expected_rates) / scales))
    chk(
        "dT_dt_K_s 按 S、J、C、B、D、R 给出 T3 导数",
        f"T3 手算 {expected_rates.tolist()} K/s，误差除以各节点功率项绝对值之和与热容之比 <= {REL_TOL:g}",
        f"{evaluation.dT_dt_K_s.tolist()}，归一误差 {scaled:.3e}",
        scaled <= REL_TOL,
    )
    chk(
        "T_B_K 等于 temperature_K 中节点 B 的温度",
        f"{T_BY_NODE['B']} K",
        f"{evaluation.T_B_K!r} K",
        evaluation.T_B_K == state.temperature_K[3] == T_BY_NODE["B"],
    )
    chk(
        "T_J_K 等于 temperature_K 中节点 J 的温度",
        f"{T_BY_NODE['J']} K",
        f"{evaluation.T_J_K!r} K",
        evaluation.T_J_K == state.temperature_K[1] == T_BY_NODE["J"],
    )
    # Three kinds of error against the independent hand values, each compared with REL_TOL by its own check.
    case_record.metric("order_max_errors", {
        "relative": {
            "C_J_K": err_c, "R_K_W": err_r, "q_W": worst([err_q, err_eq]),
            "Q_env_W": worst(surface_errors["Q_env_W"]), "Q_emit_W": worst(surface_errors["Q_emit_W"]),
        },
        "dT_dt_scaled": scaled,
        "cos_incidence_abs": cos_err,
    })
    case_record.metric("hand_Q_env_W_S_R", expected_env)
    case_record.metric("hand_Q_emit_W_S_R", expected_emit)
    case_record.metric("hand_dT_dt_K_s", expected_rates.tolist())
    case_record.metric("input_orders", {"components": component_order, "connections": connection_order})
    case_record.metric("step2_checks", chk.count)
    chk.assert_all()


# ------------------------------------------------------------------------------------------ step 3: Q_B_W sign


def test_step3_q_b_sign(case_record):
    chk = Checks(case_record, "步骤3", "q_b_sign")
    params = build_parameters()
    env = environment(params)
    state = ThermalState(RUN_ID, T0_S, T_LIST)
    c_b = ref.capacitance_by_node(SC["components"])["B"]
    r_br = ref.resistance_by_path(SC["connections"])["BR"]
    chk(
        "电池参数取第 4.3 节算例",
        f"C_B {EXAMPLE['C_B_J_K']} J/K，R_BR {EXAMPLE['R_BR_K_W']} K/W，T_B {EXAMPLE['T_B_K']} K，T_R {EXAMPLE['T_R_K']} K",
        f"C_B {params.C_J_K[3]!r} J/K，R_BR {params.R_K_W[3]!r} K/W，T_B {T_BY_NODE['B']} K，T_R {T_BY_NODE['R']} K",
        bool(
            params.C_J_K[3] == EXAMPLE["C_B_J_K"] and params.R_K_W[3] == EXAMPLE["R_BR_K_W"]
            and T_BY_NODE["B"] == EXAMPLE["T_B_K"] and T_BY_NODE["R"] == EXAMPLE["T_R_K"]
        ),
    )
    # The worked value of the design 4.3 example, compared with the numbers printed in the report.
    example_inputs = ThermalInputs(RUN_ID, T0_S, env, **dict(PORTS, Q_B_W=EXAMPLE["Q_B_W"]))
    example = thermal_derivative(state, example_inputs, params)
    example_rate = float(example.dT_dt_K_s[3])
    example_q = float(example.q_W[3])
    chk(
        f"Q_B_W 取 {number(EXAMPLE['Q_B_W'])} W 时与第 4.3 节电池算例一致",
        f"第 4.3 节算例 q_BR = 3/0.5 = {EXAMPLE['q_BR_W']} W，电池温度导数 = 4/1000 = {EXAMPLE['dT_B_dt_K_s']} K/s，"
        f"误差 <= {EXAMPLE_TOL_K_S:g} K/s",
        f"q_BR {example_q!r} W，电池温度导数 {example_rate!r} K/s",
        example_q == EXAMPLE["q_BR_W"] and abs(example_rate - EXAMPLE["dT_B_dt_K_s"]) <= EXAMPLE_TOL_K_S,
    )
    evaluations = {}
    for q_b in SC["Q_B_W_signs"]:
        q_b = float(q_b)
        ports = dict(PORTS, Q_B_W=q_b)
        inputs = ThermalInputs(RUN_ID, T0_S, env, **ports)
        chk(
            f"Q_B_W 取 {number(q_b)} W 时保留符号",
            f"{q_b!r} W 浮点数",
            f"{inputs.Q_B_W!r} {type(inputs.Q_B_W).__name__}",
            type(inputs.Q_B_W) is float and inputs.Q_B_W == q_b
            and math.copysign(1.0, inputs.Q_B_W) == math.copysign(1.0, q_b),
        )
        evaluation = thermal_derivative(state, inputs, params)
        q_br = (T_BY_NODE["B"] - T_BY_NODE["R"]) / r_br
        design = (q_b - q_br) / c_b
        rate = float(evaluation.dT_dt_K_s[3])
        chk(
            f"Q_B_W 取 {number(q_b)} W 时电池温度导数",
            f"式 T3 (Q_B − q_BR)/C_B = ({number(q_b)} − {number(q_br)})/{number(c_b)} = {design!r} K/s，"
            f"误差 <= {EXAMPLE_TOL_K_S:g} K/s",
            f"{rate!r} K/s，q_BR {float(evaluation.q_W[3])!r} W",
            abs(rate - design) <= EXAMPLE_TOL_K_S and float(evaluation.q_W[3]) == q_br,
        )
        evaluations[q_b] = evaluation
    positive, negative = (evaluations[float(value)] for value in SC["Q_B_W_signs"])
    difference = negative.dT_dt_K_s - positive.dT_dt_K_s
    expected_difference = (float(SC["Q_B_W_signs"][1]) - float(SC["Q_B_W_signs"][0])) / c_b
    others = [index for index in range(6) if index != 3]
    chk(
        "Q_B_W 只进入电池节点",
        f"两次导数之差 B 为 {expected_difference!r} K/s，其余节点为 0",
        difference.tolist(),
        bool(np.all(difference[others] == 0.0)) and abs(float(difference[3]) - expected_difference) <= EXAMPLE_TOL_K_S,
    )
    case_record.metric("dT_B_dt_K_s_by_Q_B_W", {f"{float(k):+g}": float(v.dT_dt_K_s[3]) for k, v in evaluations.items()})
    case_record.metric("design_4_3_example", {"q_BR_W": example_q, "dT_B_dt_K_s": example_rate})
    case_record.metric("dT_dt_difference_K_s", difference.tolist())
    case_record.metric("step3_checks", chk.count)
    chk.assert_all()


# ------------------------------------------------------------------------------- step 4: invalid constructions


def _inject(chk: Checks, label: str, error_class: type, keywords: list[str], factory: Any) -> bool:
    """Run one invalid construction twice: the exact error class, the field named and the same message twice."""

    outcomes = []
    for _ in range(2):
        try:
            produced = factory()
        except Exception as exc:  # noqa: BLE001  (any outcome is recorded)
            outcomes.append((type(exc), str(exc), exc))
        else:
            outcomes.append((None, f"未报错，返回 {type(produced).__name__}", None))
    (cls_1, msg_1, exc_1), (cls_2, msg_2, _) = outcomes
    named = all(keyword in msg_1 for keyword in keywords)
    same = cls_1 is cls_2 and msg_1 == msg_2
    passed = cls_1 is error_class and named and same
    actual = describe(exc_1) if exc_1 is not None else msg_1
    actual += "；重复注入报错相同" if same else f"；重复注入不同：{msg_2[:200]}"
    return chk(
        f"异常构造被拒绝：{label}",
        f"{error_class.__name__}，报错含 {'、'.join(keywords)}，重复注入报错相同",
        actual,
        passed,
    )


def _with(values: Any, index: int, value: float) -> np.ndarray:
    array = np.array(values, dtype=float)
    array[index] = value
    return array


def test_step4_invalid_constructions(case_record):
    chk = Checks(case_record, "步骤4", "invalid")
    params = build_parameters()
    env = environment(params)
    state = ThermalState(RUN_ID, T0_S, T_LIST)
    inputs = ThermalInputs(RUN_ID, T0_S, env, **PORTS)
    evaluation = thermal_derivative(state, inputs, params)
    eval_kwargs = {
        "run_id": RUN_ID, "time_s": T0_S, "dT_dt_K_s": np.array(evaluation.dT_dt_K_s), "q_W": np.array(evaluation.q_W),
        "Q_env_W": np.array(evaluation.Q_env_W), "Q_emit_W": np.array(evaluation.Q_emit_W),
        "T_B_K": evaluation.T_B_K, "T_J_K": evaluation.T_J_K,
    }
    C = np.array(params.C_J_K)
    R = np.array(params.R_K_W)
    nan, inf = float("nan"), float("inf")
    TPE, TCE = ThermalInputError, ThermalConfigurationError

    controls = {
        "ThermalParameters": lambda: dataclasses.replace(params),
        "ThermalState": lambda: ThermalState(RUN_ID, T0_S, T_LIST),
        "ThermalInputs": lambda: ThermalInputs(RUN_ID, T0_S, dict(env), **PORTS),
        "ThermalEvaluation": lambda: ThermalEvaluation(**eval_kwargs),
    }
    for name, factory in controls.items():
        try:
            built = factory()
            ok, actual = isinstance(built, getattr(thermal, name)), f"构造成功 {type(built).__name__}"
        except Exception as exc:  # noqa: BLE001
            ok, actual = False, describe(exc)
        chk(f"对照：{name} 正常构造成功", "构造成功，异常只由注入的字段引起", actual, ok)

    def replace(**changes):
        return lambda: dataclasses.replace(params, **changes)

    def state_of(temperature=None, run_id=RUN_ID, time_s=T0_S):
        temperature = T_LIST if temperature is None else temperature
        return lambda: ThermalState(run_id, time_s, temperature)

    def inputs_of(run_id=RUN_ID, time_s=T0_S, environment_map=None, **ports):
        values = dict(PORTS, **ports)
        mapping = env if environment_map is None else environment_map
        return lambda: ThermalInputs(run_id, time_s, mapping, **values)

    def evaluation_of(**changes):
        return lambda: ThermalEvaluation(**dict(eval_kwargs, **changes))

    provenance = dict(params.provenance)
    swapped_paths = ("JC", "SR", "CR", "BR", "DR")
    bad_surface = SimpleNamespace(surface_id="B_top", node_id="B", area_m2=0.1, normal_body=[0.0, 0.0, 1.0],
                                  absorptivity=0.5, emissivity=0.5)
    env_short_cos = dict(env, cos_incidence=np.asarray(env["cos_incidence"])[:3])
    env_no_ir = {key: value for key, value in env.items() if key != "infrared_W_m2"}
    env_nan_albedo = dict(env, albedo_W_m2=_with(env["albedo_W_m2"], 0, nan))

    cases = [
        # ThermalParameters: dimensions, non-finite, non-positive, orders, units, ports, surfaces
        ("参数", "ThermalParameters.C_J_K 5 个值", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=C[:5])),
        ("参数", "ThermalParameters.C_J_K 7 个值", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=np.append(C, 1.0))),
        ("参数", "ThermalParameters.C_J_K 形状 2×3", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=C.reshape(2, 3))),
        ("参数", "ThermalParameters.C_J_K 为标量", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=1000.0)),
        ("参数", "ThermalParameters.R_K_W 4 个值", TCE, ["ThermalParameters", "R_K_W"], replace(R_K_W=R[:4])),
        ("参数", "ThermalParameters.R_K_W 6 个值", TCE, ["ThermalParameters", "R_K_W"], replace(R_K_W=np.append(R, 1.0))),
        ("参数", "ThermalParameters.R_K_W 形状 5×1", TCE, ["ThermalParameters", "R_K_W"], replace(R_K_W=R.reshape(5, 1))),
        ("参数", "ThermalParameters.C_J_K 含 NaN", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=_with(C, 2, nan))),
        ("参数", "ThermalParameters.C_J_K 含 +inf", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=_with(C, 0, inf))),
        ("参数", "ThermalParameters.C_J_K 为非数值", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=["a"] * 6)),
        ("参数", "ThermalParameters.R_K_W 含 NaN", TCE, ["ThermalParameters", "R_K_W"], replace(R_K_W=_with(R, 1, nan))),
        ("参数", "ThermalParameters.R_K_W 含 −inf", TCE, ["ThermalParameters", "R_K_W"], replace(R_K_W=_with(R, 4, -inf))),
        ("参数", "ThermalParameters.C_J_K 节点 C 热容为 0", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=_with(C, 2, 0.0))),
        ("参数", "ThermalParameters.C_J_K 节点 B 热容为负", TCE, ["ThermalParameters", "C_J_K"], replace(C_J_K=_with(C, 3, -1000.0))),
        ("参数", "ThermalParameters.R_K_W 路径 BR 热阻为 0", TCE, ["ThermalParameters", "R_K_W"], replace(R_K_W=_with(R, 3, 0.0))),
        ("参数", "ThermalParameters.R_K_W 路径 DR 热阻为负", TCE, ["ThermalParameters", "R_K_W"], replace(R_K_W=_with(R, 4, -0.75))),
        ("参数", "provenance 节点顺序颠倒", TCE, ["provenance", "node_order"],
         replace(provenance=dict(provenance, node_order=tuple(reversed(ref.NODES))))),
        ("参数", "provenance 路径顺序错位", TCE, ["provenance", "path_order"],
         replace(provenance=dict(provenance, path_order=swapped_paths))),
        ("参数", "provenance 热容单位写成 kJ/K", TCE, ["provenance", "units"],
         replace(provenance=dict(provenance, units=dict(provenance["units"], C_J_K="kJ/K")))),
        ("参数", "instance_map 把 Q_B_W 连到 PDU01", TCE, ["instance_map", "Q_B_W"],
         replace(instance_map={"nodes": params.instance_map["nodes"],
                               "ports": dict(params.instance_map["ports"], Q_B_W="PDU01")})),
        ("参数", "surfaces 在电池节点登记外露表面", TCE, ["B_top", "node_id"],
         replace(surfaces=params.surfaces + (bad_surface,))),
        ("参数", "surfaces 重复登记 R_space", TCE, ["surfaces", "R_space"],
         replace(surfaces=params.surfaces + (params.surfaces[0],))),
        ("参数", "instance_map 节点 D 缺少 Controller01", TCE, ["instance_map", "Controller01"],
         replace(instance_map={"nodes": dict(params.instance_map["nodes"], D=("PDU01",)),
                               "ports": params.instance_map["ports"]})),
        # ThermalState
        ("状态", "ThermalState.temperature_K 5 个值", TPE, ["ThermalState", "temperature_K"], state_of(T_LIST[:5])),
        ("状态", "ThermalState.temperature_K 7 个值", TPE, ["ThermalState", "temperature_K"], state_of(T_LIST + [300.0])),
        ("状态", "ThermalState.temperature_K 形状 6×1", TPE, ["ThermalState", "temperature_K"],
         state_of(np.array(T_LIST).reshape(6, 1))),
        ("状态", "ThermalState.temperature_K 含 NaN", TPE, ["ThermalState", "temperature_K"], state_of(_with(T_LIST, 2, nan))),
        ("状态", "ThermalState.temperature_K 含 +inf", TPE, ["ThermalState", "temperature_K"], state_of(_with(T_LIST, 5, inf))),
        ("状态", "ThermalState.temperature_K 节点 D 为 0 K", TPE, ["ThermalState", "temperature_K"], state_of(_with(T_LIST, 4, 0.0))),
        ("状态", "ThermalState.temperature_K 节点 S 为负", TPE, ["ThermalState", "temperature_K"], state_of(_with(T_LIST, 0, -5.0))),
        ("状态", "ThermalState.run_id 为空串", TPE, ["ThermalState", "run_id"], state_of(run_id="")),
        ("状态", "ThermalState.run_id 为 None", TPE, ["ThermalState", "run_id"], state_of(run_id=None)),
        ("状态", "ThermalState.time_s 为 NaN", TPE, ["ThermalState", "time_s"], state_of(time_s=nan)),
        ("状态", "ThermalState.time_s 为 +inf", TPE, ["ThermalState", "time_s"], state_of(time_s=inf)),
        # ThermalInputs
        ("输入", "ThermalInputs 与环境运行标识不一致", TPE, ["ThermalInputs", "run_id"], inputs_of(run_id="dm001_other")),
        ("输入", "ThermalInputs 与环境时刻不一致", TPE, ["ThermalInputs", "time_s"], inputs_of(time_s=T0_S + 0.5)),
        ("输入", "ThermalInputs.P_pv_W 为 NaN", TPE, ["ThermalInputs", "P_pv_W"], inputs_of(P_pv_W=nan)),
        ("输入", "ThermalInputs.P_load_W 为 +inf", TPE, ["ThermalInputs", "P_load_W"], inputs_of(P_load_W=inf)),
        ("输入", "ThermalInputs.Q_B_W 为 NaN", TPE, ["ThermalInputs", "Q_B_W"], inputs_of(Q_B_W=nan)),
        ("输入", "ThermalInputs.Q_D_W 为 −inf", TPE, ["ThermalInputs", "Q_D_W"], inputs_of(Q_D_W=-inf)),
        ("输入", "ThermalInputs.Q_B_W 缺失为 None", TPE, ["ThermalInputs", "Q_B_W"], inputs_of(Q_B_W=None)),
        ("输入", "ThermalInputs 环境 cos_incidence 3 个值对 4 个表面", TPE, ["environment", "cos_incidence"],
         inputs_of(environment_map=env_short_cos)),
        ("输入", "ThermalInputs 环境缺少 infrared_W_m2", TPE, ["environment", "infrared_W_m2"],
         inputs_of(environment_map=env_no_ir)),
        ("输入", "ThermalInputs 环境 albedo_W_m2 含 NaN", TPE, ["environment", "albedo_W_m2"],
         inputs_of(environment_map=env_nan_albedo)),
        ("输入", "ThermalInputs.run_id 为空串", TPE, ["ThermalInputs", "run_id"], inputs_of(run_id="")),
        ("输入", "ThermalInputs.time_s 为 NaN", TPE, ["ThermalInputs", "time_s"], inputs_of(time_s=nan)),
        # ThermalEvaluation
        ("结果", "ThermalEvaluation.dT_dt_K_s 5 个值", TPE, ["ThermalEvaluation", "dT_dt_K_s"], evaluation_of(dT_dt_K_s=np.zeros(5))),
        ("结果", "ThermalEvaluation.q_W 4 个值", TPE, ["ThermalEvaluation", "q_W"], evaluation_of(q_W=np.zeros(4))),
        ("结果", "ThermalEvaluation.q_W 6 个值", TPE, ["ThermalEvaluation", "q_W"], evaluation_of(q_W=np.zeros(6))),
        ("结果", "ThermalEvaluation.Q_env_W 3 个值", TPE, ["ThermalEvaluation", "Q_env_W"], evaluation_of(Q_env_W=np.zeros(3))),
        ("结果", "ThermalEvaluation.Q_emit_W 1 个值", TPE, ["ThermalEvaluation", "Q_emit_W"], evaluation_of(Q_emit_W=np.zeros(1))),
        ("结果", "ThermalEvaluation.dT_dt_K_s 含 NaN", TPE, ["ThermalEvaluation", "dT_dt_K_s"],
         evaluation_of(dT_dt_K_s=_with(eval_kwargs["dT_dt_K_s"], 1, nan))),
        ("结果", "ThermalEvaluation.q_W 含 +inf", TPE, ["ThermalEvaluation", "q_W"], evaluation_of(q_W=_with(eval_kwargs["q_W"], 2, inf))),
        ("结果", "ThermalEvaluation.Q_env_W 含 NaN", TPE, ["ThermalEvaluation", "Q_env_W"],
         evaluation_of(Q_env_W=_with(eval_kwargs["Q_env_W"], 0, nan))),
        ("结果", "ThermalEvaluation.Q_emit_W 含 −inf", TPE, ["ThermalEvaluation", "Q_emit_W"],
         evaluation_of(Q_emit_W=_with(eval_kwargs["Q_emit_W"], 1, -inf))),
        ("结果", "ThermalEvaluation.T_B_K 为 NaN", TPE, ["ThermalEvaluation", "T_B_K"], evaluation_of(T_B_K=nan)),
        ("结果", "ThermalEvaluation.T_J_K 为 0 K", TPE, ["ThermalEvaluation", "T_J_K"], evaluation_of(T_J_K=0.0)),
        ("结果", "ThermalEvaluation.run_id 为空串", TPE, ["ThermalEvaluation", "run_id"], evaluation_of(run_id="")),
        ("结果", "ThermalEvaluation.time_s 为 +inf", TPE, ["ThermalEvaluation", "time_s"], evaluation_of(time_s=inf)),
        # functions that combine the objects: run and time agreement, dimensions of a received state
        ("函数", "thermal_derivative 状态与输入运行标识不一致", TPE, ["run_id"],
         lambda: thermal_derivative(ThermalState("dm001_other", T0_S, T_LIST), inputs, params)),
        ("函数", "thermal_derivative 状态与输入时刻不一致", TPE, ["time_s"],
         lambda: thermal_derivative(ThermalState(RUN_ID, T0_S + 1.0, T_LIST), inputs, params)),
        ("函数", "thermal_derivative 收到 5 个温度的状态", TPE, ["state", "temperature_K"],
         lambda: thermal_derivative(SimpleNamespace(run_id=RUN_ID, time_s=T0_S, temperature_K=np.array(T_LIST[:5])),
                                    inputs, params)),
        ("函数", "calculate_heat_flows 收到含 NaN 的状态", TPE, ["state", "temperature_K"],
         lambda: calculate_heat_flows(SimpleNamespace(run_id=RUN_ID, time_s=T0_S, temperature_K=_with(T_LIST, 1, nan)),
                                      params)),
    ]
    by_group: dict[str, list[int]] = {}
    for group, label, error_class, keywords, factory in cases:
        ok = _inject(chk, label, error_class, keywords, factory)
        counts = by_group.setdefault(group, [0, 0])
        counts[0] += 1
        counts[1] += int(ok)
    total = sum(counts[0] for counts in by_group.values())
    rejected = sum(counts[1] for counts in by_group.values())
    case_record.metric("invalid_constructions", {"total": total, "rejected_as_specified": rejected,
                                                  "by_object": {key: {"total": v[0], "rejected": v[1]}
                                                                for key, v in by_group.items()}})
    case_record.metric("step4_checks", chk.count)
    chk.assert_all()


# ------------------------------------------------------------------- step 5: read-only parameters, state separation


def _parameter_attempts(params: ThermalParameters) -> list[tuple[str, Any]]:
    surface = params.surfaces[0]
    return [
        ("给 C_J_K 赋新数组", lambda: setattr(params, "C_J_K", np.ones(6))),
        ("删除 R_K_W 字段", lambda: delattr(params, "R_K_W")),
        ("新增属性", lambda: setattr(params, "extra_field", 1)),
        ("C_J_K 元素赋值", lambda: operator.setitem(params.C_J_K, 0, 1.0)),
        ("R_K_W 切片赋值", lambda: operator.setitem(params.R_K_W, slice(None), 1.0)),
        ("C_J_K 就地乘 2", lambda: operator.imul(params.C_J_K, 2.0)),
        ("np.copyto 写入 R_K_W", lambda: np.copyto(params.R_K_W, 1.0)),
        ("C_J_K.fill", lambda: params.C_J_K.fill(1.0)),
        ("C_J_K 设为可写", lambda: params.C_J_K.setflags(write=True)),
        ("R_K_W 视图设为可写", lambda: params.R_K_W.view().setflags(write=True)),
        ("C_J_K 经底层数组设为可写后写入", lambda: _write_through_base(params.C_J_K)),
        ("instance_map 端口改连", lambda: operator.setitem(params.instance_map["ports"], "Q_B_W", "PDU01")),
        ("instance_map 新增节点", lambda: operator.setitem(params.instance_map["nodes"], "X", ("Battery02",))),
        ("instance_map 节点 D 追加实例", lambda: params.instance_map["nodes"]["D"].append("PDU02")),
        ("provenance 单位改写", lambda: operator.setitem(params.provenance["units"], "C_J_K", "kJ/K")),
        ("provenance 热容值改写", lambda: operator.setitem(params.provenance["capacitance"]["B"], "value_J_K", 1.0)),
        ("provenance 材料质量改写",
         lambda: operator.setitem(params.provenance["capacitance"]["B"]["portions"][0], "mass_kg", 2.0)),
        ("provenance 覆盖记录追加", lambda: params.provenance["overrides_applied"].append({})),
        ("provenance 删除单位", lambda: operator.delitem(params.provenance, "units")),
        ("surfaces 元素替换", lambda: operator.setitem(params.surfaces, 0, surface)),
        ("表面面积改写", lambda: setattr(surface, "area_m2", 9.0)),
        ("表面法向元素赋值", lambda: operator.setitem(surface.normal_body, 0, 0.5)),
        ("表面法向设为可写", lambda: surface.normal_body.setflags(write=True)),
        ("表面法向经底层数组设为可写后写入", lambda: _write_through_base(surface.normal_body)),
    ]


def test_step5_parameters_read_only(case_record):
    chk = Checks(case_record, "步骤5", "read_only")
    params = build_parameters()
    env = environment(params)
    state = ThermalState(RUN_ID, T0_S, T_LIST)
    inputs = ThermalInputs(RUN_ID, T0_S, env, **PORTS)
    before = snapshot(params)
    evaluation_before = thermal_derivative(state, inputs, params)
    attempts = _parameter_attempts(params)
    refused = 0
    for label, attempt in attempts:
        try:
            attempt()
            outcome = None
        except Exception as exc:  # noqa: BLE001
            outcome = exc
        ok = isinstance(outcome, (AttributeError, TypeError, ValueError))
        refused += int(ok)
        chk(f"参数修改尝试被拒绝：{label}", "抛出 AttributeError、TypeError 或 ValueError", describe(outcome), ok)
    after = snapshot(params)
    changed = [key for key in before if before[key] != after[key]]
    chk("修改尝试后参数逐位不变", "C_J_K、R_K_W、surfaces、instance_map、provenance 全部不变", f"变化字段 {changed}",
        not changed)
    evaluation_after = thermal_derivative(state, inputs, params)
    chk(
        "修改尝试后温度导数逐位不变",
        f"{evaluation_before.dT_dt_K_s.tolist()} K/s",
        evaluation_after.dT_dt_K_s.tolist(),
        state_snapshot(evaluation_before) == state_snapshot(evaluation_after),
    )

    copied = params.provenance_as_dict()
    copied["units"]["C_J_K"] = "kJ/K"
    copied["capacitance"]["B"]["value_J_K"] = 1.0
    chk(
        "provenance_as_dict 返回独立副本",
        "改写副本后 provenance 单位仍为 J/K，电池热容仍为 1000 J/K",
        f"单位 {params.provenance['units']['C_J_K']}，电池热容 {params.provenance['capacitance']['B']['value_J_K']}",
        params.provenance["units"]["C_J_K"] == "J/K" and params.provenance["capacitance"]["B"]["value_J_K"] == 1000.0,
    )

    source_c = np.array(params.C_J_K)
    source_r = np.array(params.R_K_W)
    direct = ThermalParameters(source_c, source_r, params.surfaces, params.instance_map, params.provenance)
    expected_c, expected_r = source_c.copy(), source_r.copy()
    source_c[:] = 1.0
    source_r[:] = 1.0
    chk(
        "构造后改写来源数组不影响参数",
        f"C_J_K {expected_c.tolist()}，R_K_W {expected_r.tolist()}",
        f"C_J_K {direct.C_J_K.tolist()}，R_K_W {direct.R_K_W.tolist()}，共享内存 "
        f"{np.shares_memory(direct.C_J_K, source_c) or np.shares_memory(direct.R_K_W, source_r)}",
        np.array_equal(direct.C_J_K, expected_c) and np.array_equal(direct.R_K_W, expected_r)
        and not np.shares_memory(direct.C_J_K, source_c) and not np.shares_memory(direct.R_K_W, source_r),
    )
    components = copy.deepcopy(SC["components"])
    connections = copy.deepcopy(SC["connections"])
    assembled = assemble_thermal_parameters(components, connections, None)
    reference = snapshot(assembled)
    for component in components:
        for material in component["materials"]:
            material["mass_kg"] = 100.0
        for surface in component["surfaces"]:
            surface["normal_body"][0] = 0.5
            surface["area_m2"] = 99.0
    for connection in connections:
        connection["source"] = "changed"
        if "contact_resistance_K_W" in connection:
            connection["contact_resistance_K_W"] = 9.0
    unchanged = snapshot(assembled) == reference
    chk("装配后改写输入记录不影响参数", "质量、表面与接触热阻改写后参数逐位不变", f"参数不变 {unchanged}", unchanged)
    case_record.metric("parameter_modification_attempts", {"total": len(attempts), "refused": refused})
    case_record.metric("step5_read_only_checks", chk.count)
    chk.assert_all()


def test_step5_trial_and_accepted_states_module(case_record):
    chk = Checks(case_record, "步骤5", "state_module")
    params = build_parameters()
    env0 = environment(params)
    accepted = ThermalState(RUN_ID, T0_S, T_LIST)
    accepted_bits = state_snapshot(accepted)
    inputs0 = ThermalInputs(RUN_ID, T0_S, env0, **PORTS)
    inputs_bits = state_snapshot(inputs0)
    params_bits = snapshot(params)
    orbit0, flux0 = orbit_input(), earth_flux()
    orbit_bits = json.dumps(plain({k: v for k, v in orbit0.items() if k != "epoch"}), sort_keys=True)
    flux_bits = json.dumps(plain(flux0), sort_keys=True)
    prepare_surface_environment(orbit0, flux0, params)
    calculate_surface_heat(accepted, env0, params)
    calculate_heat_flows(accepted, params)
    evaluation0 = thermal_derivative(accepted, inputs0, params)

    step_s = 10.0
    trial_temperature = accepted.temperature_K + step_s * evaluation0.dT_dt_K_s
    trial = ThermalState(RUN_ID, T0_S + step_s, trial_temperature)
    env1 = environment(params, time_s=T0_S + step_s)
    inputs1 = ThermalInputs(RUN_ID, T0_S + step_s, env1, **PORTS)
    evaluation1 = thermal_derivative(trial, inputs1, params)
    same_values = ThermalState(RUN_ID, T0_S + step_s, accepted.temperature_K)

    chk(
        "函数不修改输入状态、输入与参数",
        "调用 prepare_surface_environment、calculate_surface_heat、calculate_heat_flows、thermal_derivative 后逐位不变",
        f"已接受状态不变 {state_snapshot(accepted) == accepted_bits}，ThermalInputs 不变 "
        f"{state_snapshot(inputs0) == inputs_bits}，参数不变 {snapshot(params) == params_bits}，orbit_input 不变 "
        f"{json.dumps(plain({k: v for k, v in orbit0.items() if k != 'epoch'}), sort_keys=True) == orbit_bits}，"
        f"earth_flux 不变 {json.dumps(plain(flux0), sort_keys=True) == flux_bits}",
        state_snapshot(accepted) == accepted_bits and state_snapshot(inputs0) == inputs_bits
        and snapshot(params) == params_bits
        and json.dumps(plain({k: v for k, v in orbit0.items() if k != "epoch"}), sort_keys=True) == orbit_bits
        and json.dumps(plain(flux0), sort_keys=True) == flux_bits,
    )
    chk(
        "试算状态是独立记录",
        "试算状态与已接受状态为不同对象，不共享温度数组",
        f"同一对象 {trial is accepted}，共享内存 {np.shares_memory(trial.temperature_K, accepted.temperature_K)}，"
        f"同值新状态共享内存 {np.shares_memory(same_values.temperature_K, accepted.temperature_K)}",
        trial is not accepted and not np.shares_memory(trial.temperature_K, accepted.temperature_K)
        and not np.shares_memory(same_values.temperature_K, accepted.temperature_K),
    )
    chk(
        "建立并计算试算状态后已接受状态不变",
        f"time_s {T0_S} s，temperature_K {T_LIST} K",
        f"time_s {accepted.time_s} s，temperature_K {accepted.temperature_K.tolist()} K；试算 time_s {trial.time_s} s，"
        f"T_B_K {evaluation1.T_B_K!r} K",
        state_snapshot(accepted) == accepted_bits and evaluation1.T_B_K == float(trial_temperature[3]),
    )
    source = np.array(T_LIST)
    copied_state = ThermalState(RUN_ID, T0_S, source)
    source[:] = 1.0
    chk(
        "构造后改写来源数组不影响状态",
        f"{T_LIST} K",
        copied_state.temperature_K.tolist(),
        copied_state.temperature_K.tolist() == T_LIST and not np.shares_memory(copied_state.temperature_K, source),
    )
    caller_env = {key: (list(value) if isinstance(value, (np.ndarray, tuple)) else value) for key, value in env0.items()}
    inputs_from_caller = ThermalInputs(RUN_ID, T0_S, caller_env, **PORTS)
    inputs_from_caller_bits = state_snapshot(inputs_from_caller)
    caller_env["cos_incidence"][0] = 0.0
    caller_env["albedo_W_m2"][0] = 999.0
    caller_env["G_W_m2"] = 0.0
    chk(
        "构造后改写来源环境不影响 ThermalInputs",
        "改写调用方环境字典中的 cos_incidence、albedo_W_m2 与 G_W_m2 后 ThermalInputs.environment 逐位不变",
        f"不变 {state_snapshot(inputs_from_caller) == inputs_from_caller_bits}，G_W_m2 "
        f"{inputs_from_caller.environment['G_W_m2']!r} W/m²",
        state_snapshot(inputs_from_caller) == inputs_from_caller_bits
        and inputs_from_caller.environment["G_W_m2"] == float(SC["orbit_input"]["G_W_m2"]),
    )
    attempts = [
        ("已接受状态温度元素赋值", lambda: operator.setitem(accepted.temperature_K, 3, float(trial_temperature[3]))),
        ("已接受状态温度整体写入试算值", lambda: np.copyto(accepted.temperature_K, trial_temperature)),
        ("已接受状态温度设为可写", lambda: accepted.temperature_K.setflags(write=True)),
        ("已接受状态温度经底层数组设为可写后写入", lambda: _write_through_base(accepted.temperature_K)),
        ("已接受状态字段替换为试算数组", lambda: setattr(accepted, "temperature_K", trial_temperature)),
        ("已接受状态时刻改写", lambda: setattr(accepted, "time_s", T0_S + step_s)),
        ("ThermalEvaluation 导数元素赋值", lambda: operator.setitem(evaluation0.dT_dt_K_s, 0, 0.0)),
        ("ThermalEvaluation T_B_K 改写", lambda: setattr(evaluation0, "T_B_K", 1.0)),
        ("ThermalInputs 环境数组元素赋值", lambda: operator.setitem(inputs0.environment["cos_incidence"], 0, 0.0)),
        ("ThermalInputs 环境键改写", lambda: operator.setitem(inputs0.environment, "G_W_m2", 0.0)),
    ]
    refused = 0
    for label, attempt in attempts:
        try:
            attempt()
            outcome = None
        except Exception as exc:  # noqa: BLE001
            outcome = exc
        ok = isinstance(outcome, (AttributeError, TypeError, ValueError))
        refused += int(ok)
        chk(f"记录写入尝试被拒绝：{label}", "抛出 AttributeError、TypeError 或 ValueError", describe(outcome), ok)
    chk(
        "多次写入尝试后已接受状态与输入逐位不变",
        "不变",
        f"已接受状态不变 {state_snapshot(accepted) == accepted_bits}，ThermalInputs 不变 {state_snapshot(inputs0) == inputs_bits}",
        state_snapshot(accepted) == accepted_bits and state_snapshot(inputs0) == inputs_bits,
    )
    chk(
        "T_B_K 与 T_J_K 是输入温度的数值副本",
        "浮点数，等于 temperature_K 中节点 B 与节点 J 的温度，ThermalEvaluation 不含 temperature_K 状态字段",
        f"T_B_K {evaluation0.T_B_K!r} {type(evaluation0.T_B_K).__name__}，T_J_K {evaluation0.T_J_K!r}，含 temperature_K "
        f"{hasattr(evaluation0, 'temperature_K')}",
        bool(
            type(evaluation0.T_B_K) is float and type(evaluation0.T_J_K) is float
            and evaluation0.T_B_K == accepted.temperature_K[3] and evaluation0.T_J_K == accepted.temperature_K[1]
            and not hasattr(evaluation0, "temperature_K")
        ),
    )
    case_record.metric("module_write_attempts", {"total": len(attempts), "refused": refused})
    case_record.metric("step5_module_state_checks", chk.count)
    chk.assert_all()


# Attempts made from trial_hook once the coupled run has started: (label, target, attempt(parameters, trial record)).
IN_RUN_ATTEMPTS: tuple[tuple[str, str, Any], ...] = (
    ("运行中 C_J_K 元素赋值", "parameters", lambda p, r: operator.setitem(p.C_J_K, 0, 1.0)),
    ("运行中 R_K_W 设为可写", "parameters", lambda p, r: p.R_K_W.setflags(write=True)),
    ("运行中 R_K_W 经底层数组设为可写后写入", "parameters", lambda p, r: _write_through_base(p.R_K_W)),
    ("运行中给 R_K_W 赋新数组", "parameters", lambda p, r: setattr(p, "R_K_W", np.ones(5))),
    ("运行中 provenance 单位改写", "parameters", lambda p, r: operator.setitem(p.provenance["units"], "R_K_W", "W/K")),
    ("运行中 instance_map 端口改连", "parameters",
     lambda p, r: operator.setitem(p.instance_map["ports"], "P_pv_W", "Radiator01")),
    ("运行中表面吸收率改写", "parameters", lambda p, r: setattr(p.surfaces[2], "absorptivity", 0.0)),
    ("trial_hook 改写试算状态数组", "trial", lambda p, r: operator.setitem(r.state, 0, 1.0)),
    ("trial_hook 改写试算 ThermalState 温度", "trial", lambda p, r: operator.setitem(r.thermal_state.temperature_K, 0, 1.0)),
    ("trial_hook 替换试算 ThermalState 温度", "trial", lambda p, r: setattr(r.thermal_state, "temperature_K", np.ones(6))),
    ("trial_hook 替换 TrialRecord 状态", "trial", lambda p, r: setattr(r, "state", np.ones(6))),
)


def _analyse_trials(records: list[Any], archive: cp.CoupledArchive, rhs: Any) -> dict[str, Any]:
    """Classify every RK45 attempt of the integration trials from the trial log alone, then compare with the archive.

    SciPy RK45 evaluates the model once when a solver is built (at the accepted start state) and six times per attempt:
    stages 2 to 6 at t + c h and the end derivative at (t + h, y_new). The start time of an attempt follows from its
    second stage (c = 1/5) and its end time: t = (t_2 - t_end / 5) / (4 / 5). An attempt whose successor starts at the
    same time was rejected; one whose successor starts at its end time was accepted. Every comparison is written so
    that a NaN fails it, and the largest mismatches keep a NaN.
    """

    accepted_t = np.asarray(archive.accepted["time_s"], dtype=float)
    accepted_y = np.asarray(archive.accepted["state"], dtype=float)
    kinds = tuple(archive.accepted["kind"])
    integration = [record for record in records if record.context == "integration"]
    solver_ids = list(dict.fromkeys(record.solver_id for record in integration))
    out: dict[str, Any] = {
        "grouping_ok": True, "notes": [], "attempts": 0, "accepted_attempts": [], "rejected_attempts": [],
        "start_mismatch_K": float("nan"), "start_time_mismatch_s": float("nan"), "retries": [],
    }
    if not integration:
        out["grouping_ok"] = False
        out["notes"].append("no integration trials")
        return out
    start_t, start_y = float(accepted_t[0]), accepted_y[0].copy()
    time_gaps: list[float] = []
    stage2_gaps: list[float] = []
    for solver_id in solver_ids:
        recs = [record for record in integration if record.solver_id == solver_id]
        if (len(recs) - 1) % N_STAGES_RK45 != 0:
            out["grouping_ok"] = False
            out["notes"].append(f"solver {solver_id}: {len(recs)} evaluations is not 1 + 6 k")
            continue
        first = recs[0]
        if not (first.time_s == start_t and np.array_equal(first.state, start_y)):
            out["grouping_ok"] = False
            out["notes"].append(f"solver {solver_id}: construction state is not the last accepted state")
        groups = [recs[1 + N_STAGES_RK45 * k: 1 + N_STAGES_RK45 * (k + 1)] for k in range((len(recs) - 1) // N_STAGES_RK45)]
        starts = []
        for group in groups:
            t2, t_end = group[0].time_s, group[-1].time_s
            if not group[-2].time_s == t_end:
                out["grouping_ok"] = False
                out["notes"].append(f"solver {solver_id}: stage 6 and end derivative at different times")
            starts.append((t2 - C2_RK45 * t_end) / (1.0 - C2_RK45))
        previous_rejected = None
        for index, group in enumerate(groups):
            out["attempts"] += 1
            stage2, candidate = group[0], group[-1]
            implied = starts[index]
            tolerance = 1e-9 * max(1.0, abs(start_t), abs(candidate.time_s))
            gap = abs(implied - start_t)
            time_gaps.append(gap)
            if not gap <= tolerance:
                out["grouping_ok"] = False
                out["notes"].append(f"attempt {index}: implied start {implied!r} s differs from {start_t!r} s")
            derivative = np.asarray(rhs(start_t, start_y), dtype=float)
            predicted = start_y + (stage2.time_s - start_t) * derivative
            mismatch = float(np.max(np.abs(np.asarray(stage2.state) - predicted)))
            stage2_gaps.append(mismatch)
            if previous_rejected is not None:
                out["retries"].append({
                    "start_time_s": start_t, "stage2_mismatch_K": mismatch,
                    "distance_to_rejected_candidate_K": float(np.max(np.abs(start_y - previous_rejected["state"]))),
                })
            if index + 1 < len(groups):
                next_start = starts[index + 1]
                accepted_attempt = abs(next_start - candidate.time_s) <= tolerance
                rejected_attempt = abs(next_start - start_t) <= tolerance
                if accepted_attempt == rejected_attempt:
                    out["grouping_ok"] = False
                    out["notes"].append(f"attempt {index}: successor start {next_start!r} s is neither")
            else:
                accepted_attempt = True  # the last attempt of a solver ends its segment
            entry = {"time_s": float(candidate.time_s), "state": np.array(candidate.state, dtype=float),
                     "start_time_s": start_t}
            if accepted_attempt:
                out["accepted_attempts"].append(entry)
                start_t, start_y = float(candidate.time_s), np.array(candidate.state, dtype=float)
                previous_rejected = None
            else:
                out["rejected_attempts"].append(entry)
                previous_rejected = entry
    out["start_time_mismatch_s"] = worst(time_gaps)
    out["start_mismatch_K"] = worst(stage2_gaps)

    # The end derivative is evaluated at t + h, the solver stores t_new; allow a few ulp between the two times.
    def same_time(a: float, b: float) -> bool:
        return abs(a - b) <= 4.0 * math.ulp(max(abs(a), abs(b), 1.0))

    archived = [(float(t), y) for t, y, kind in zip(accepted_t, accepted_y, kinds) if kind == "integration"]
    out["archived_integration_states"] = len(archived)
    out["archive_matches_accepted_attempts"] = len(archived) == len(out["accepted_attempts"]) and all(
        same_time(t, entry["time_s"]) and np.array_equal(y, entry["state"])
        for (t, y), entry in zip(archived, out["accepted_attempts"])
    )
    stored_states = {np.asarray(y).tobytes() for y in accepted_y}
    out["rejected_in_archive"] = sum(1 for entry in out["rejected_attempts"] if entry["state"].tobytes() in stored_states)
    out["integration_trial_records"] = len(integration)
    out["integration_trial_states_not_stored"] = sum(
        1 for record in integration if np.asarray(record.state).tobytes() not in stored_states
    )
    return out


def test_step5_coupled_trial_and_accepted_records(case_record):
    chk = Checks(case_record, "步骤5", "trials")
    params = build_parameters()
    before = snapshot(params)
    cfg = SC["coupled_thermal_only"]
    records: list[Any] = []
    in_run: list[tuple[str, str, BaseException | None]] = []
    attempt_record: dict[str, Any] = {}

    def hook(record):
        # First trial of the running integration that carries a trial ThermalState, so every target below exists.
        if not in_run and record.thermal_state is not None:
            attempt_record.update(time_s=float(record.time_s), context=record.context, solver_id=record.solver_id)
            for label, target, attempt in IN_RUN_ATTEMPTS:
                try:
                    attempt(params, record)
                    in_run.append((label, target, None))
                except Exception as exc:  # noqa: BLE001
                    in_run.append((label, target, exc))
        records.append(record)

    archive, caught = thermal_only_run(params, hook)
    plain_archive, _ = thermal_only_run(params, None)
    statistics = archive.statistics

    n_param = sum(1 for _, target, _ in IN_RUN_ATTEMPTS if target == "parameters")
    n_trial = len(IN_RUN_ATTEMPTS) - n_param
    chk(
        "运行开始后的修改尝试全部执行",
        f"第一个带试算 ThermalState 的试算记录上执行 {len(IN_RUN_ATTEMPTS)} 种尝试：ThermalParameters {n_param} 种，"
        f"TrialRecord 与试算 ThermalState {n_trial} 种",
        f"执行 {len(in_run)} 种，所在试算记录 {attempt_record}",
        len(in_run) == len(IN_RUN_ATTEMPTS),
        topic="in_run_params",
    )
    for label, target, outcome in in_run:
        chk(f"运行开始后修改尝试被拒绝：{label}", "抛出 AttributeError、TypeError 或 ValueError", describe(outcome),
            isinstance(outcome, (AttributeError, TypeError, ValueError)),
            topic="in_run_params" if target == "parameters" else "in_run_trial")
    after = snapshot(params)
    changed = [key for key in before if before[key] != after[key]]
    chk("联合计算后参数逐位不变", "C_J_K、R_K_W、surfaces、instance_map、provenance 全部不变", f"变化字段 {changed}",
        not changed, topic="in_run_params")
    archived_provenance = json.dumps(plain(archive.provenance["thermal_parameters"]), sort_keys=True, default=repr)
    chk(
        "归档的参数记录与运行开始前一致",
        "archive.provenance['thermal_parameters'] 等于运行前的 provenance",
        f"一致 {archived_provenance == json.dumps(params.provenance_as_dict(), sort_keys=True, default=repr)}",
        archived_provenance == json.dumps(params.provenance_as_dict(), sort_keys=True, default=repr),
        topic="in_run_params",
    )
    fields_compared = []
    identical = True
    for name in ("time_s", "temperature_K", "dT_dt_K_s", "q_W", "Q_env_W", "Q_emit_W"):
        fields_compared.append(name)
        identical &= np.array_equal(getattr(archive, name), getattr(plain_archive, name))
    for name in ("time_s", "state"):
        fields_compared.append(f"accepted.{name}")
        identical &= np.array_equal(archive.accepted[name], plain_archive.accepted[name])
    for name in ("t_old_s", "t_new_s"):
        fields_compared.append(f"steps.{name}")
        identical &= np.array_equal(archive.steps[name], plain_archive.steps[name])
    identical &= archive.accepted["kind"] == plain_archive.accepted["kind"]
    identical &= all(np.array_equal(archive.ports_W[k], plain_archive.ports_W[k]) for k in archive.ports_W)
    chk(
        "带修改尝试的计算与未设置 trial_hook 的计算逐位相同",
        "已接受状态、步长与输出全部相同",
        f"比较 {fields_compared}、accepted.kind、ports_W；相同 {bool(identical)}",
        bool(identical),
        topic="in_run_params",
    )

    rejected_stat = int(statistics["rejected_steps"])
    chk(
        "联合计算出现被拒绝的积分步",
        f"first_step_s {cfg['solver']['first_step_s']} s 大于计算节点时间常数 40 s，rejected_steps >= 1",
        f"rejected_steps {rejected_stat}，accepted_steps {statistics['accepted_steps']}，函数计算 "
        f"{statistics['function_evaluations']} 次",
        rejected_stat >= 1,
    )
    rhs = ref.make_rhs(SC)
    analysis = _analyse_trials(records, archive, rhs)
    chk(
        "试算记录可按 RK45 尝试分组",
        "每个求解器 1 次初始计算加每次尝试 6 次计算，初始计算取上一已接受状态",
        f"分组成立 {analysis['grouping_ok']}，尝试 {analysis['attempts']} 次，起点时刻最大偏差 "
        f"{analysis['start_time_mismatch_s']!r} s，说明 {analysis['notes'][:3]}",
        analysis["grouping_ok"],
    )
    n_acc, n_rej = len(analysis["accepted_attempts"]), len(analysis["rejected_attempts"])
    chk(
        "由试算记录判定的被拒绝积分步数等于归档统计",
        f"rejected_steps {rejected_stat}，accepted_steps {statistics['accepted_steps']}",
        f"被拒绝 {n_rej}，被接受 {n_acc}",
        n_rej == rejected_stat and n_acc == int(statistics["accepted_steps"]),
    )
    chk(
        "归档的已接受状态只含被接受积分步的终点状态",
        f"accepted 中 {n_acc} 个积分状态依次逐位等于被接受积分步的终点试算状态",
        f"归档积分状态 {analysis.get('archived_integration_states')} 个，逐位一致 "
        f"{analysis.get('archive_matches_accepted_attempts')}",
        bool(analysis.get("archive_matches_accepted_attempts")),
    )
    chk(
        "被拒绝积分步的终点试算状态未进入归档的已接受状态",
        "0 个被拒绝积分步的终点试算状态出现在 accepted 中，且至少有 1 个被拒绝积分步",
        f"{analysis.get('rejected_in_archive')} 个，终点时刻 {[e['time_s'] for e in analysis['rejected_attempts']]} s",
        analysis.get("rejected_in_archive") == 0 and n_rej >= 1,
    )
    retries = analysis["retries"]
    worst_retry = worst(entry["stage2_mismatch_K"] for entry in retries)
    chk(
        "重试从上一已接受状态出发",
        f"每次重试的第 2 级状态等于 y_start + Δt f(t_start, y_start)，偏差 <= {RETRY_START_TOL_K:g} K",
        f"重试 {len(retries)} 次，起点时刻 {[entry['start_time_s'] for entry in retries]} s，最大偏差 {worst_retry!r} K，"
        f"起点与被拒绝积分步终点状态相距 {[round(entry['distance_to_rejected_candidate_K'], 6) for entry in retries]} K；"
        f"全部尝试最大偏差 {analysis['start_mismatch_K']!r} K",
        len(retries) == n_rej and len(retries) >= 1 and worst_retry <= RETRY_START_TOL_K
        and analysis["start_mismatch_K"] <= RETRY_START_TOL_K,
    )

    solution = solve_ivp(rhs, (0.0, float(cfg["t_end_s"])), T_LIST, method="DOP853", rtol=1e-12, atol=1e-10,
                         dense_output=True)
    accepted_t = np.asarray(archive.accepted["time_s"], dtype=float)
    accepted_y = np.asarray(archive.accepted["state"], dtype=float)
    deviation_accepted = worst(float(np.max(np.abs(y - solution.sol(t)))) for t, y in zip(accepted_t, accepted_y))
    deviation_outputs = float(np.max(np.abs(archive.temperature_K - solution.sol(archive.time_s).T)))
    chk(
        "已接受状态与独立参考解一致",
        f"{len(accepted_t)} 个已接受状态与 DOP853 参考解最大偏差 <= {ACCEPTED_REF_TOL_K:g} K",
        f"最大偏差 {deviation_accepted:.3e} K，输出采样最大偏差 {deviation_outputs:.3e} K，参考解状态 {solution.status}",
        bool(solution.success) and deviation_accepted <= ACCEPTED_REF_TOL_K and deviation_outputs <= ACCEPTED_REF_TOL_K,
    )
    local_tolerance = cfg["solver"]["atol_T_K"] + cfg["solver"]["rtol"] * worst(np.abs(accepted_y).ravel())
    deviation_rejected = [
        float(np.max(np.abs(entry["state"] - solution.sol(entry["time_s"])))) for entry in analysis["rejected_attempts"]
    ]
    chk(
        "被拒绝积分步的终点试算状态可与参考解区分",
        f"每个终点试算状态偏离参考解超过局部容限 atol + rtol max|T| = {local_tolerance:.3e} K",
        f"偏离 {[f'{value:.3e}' for value in deviation_rejected]} K，最小 {least(deviation_rejected)!r} K",
        bool(deviation_rejected) and all(value > local_tolerance for value in deviation_rejected),
    )
    final = archive.final_thermal_state
    readonly = (
        not archive.accepted["state"].flags.writeable and not archive.accepted["time_s"].flags.writeable
        and not archive.temperature_K.flags.writeable and all(not r.state.flags.writeable for r in records)
        and all(r.thermal_state is None or not r.thermal_state.temperature_K.flags.writeable for r in records)
    )
    chk(
        "试算记录与归档的已接受状态只读且分开保存",
        "TrialRecord.state、试算 ThermalState 与归档 accepted 数组均只读；final_thermal_state 等于最后已接受状态",
        f"只读 {readonly}；final_thermal_state 为 ThermalState {isinstance(final, ThermalState)}，time_s "
        f"{final.time_s if final is not None else None} s，等于最后已接受状态 "
        f"{final is not None and np.array_equal(final.temperature_K, accepted_y[-1])}",
        bool(
            readonly and isinstance(final, ThermalState) and final.time_s == float(accepted_t[-1])
            and np.array_equal(final.temperature_K, accepted_y[-1])
        ),
    )
    range_warnings = [item for item in caught if issubclass(item.category, thermal.ThermalRangeWarning)]
    refused = {target: sum(1 for _, kind, outcome in in_run
                           if kind == target and isinstance(outcome, (AttributeError, TypeError, ValueError)))
               for target in ("parameters", "trial")}
    case_record.metric("coupled_thermal_only_run", {
        "run_id": cfg["run_id"], "t_end_s": cfg["t_end_s"], "solver": cfg["solver"],
        "accepted_states": int(len(accepted_t)), "accepted_steps": int(statistics["accepted_steps"]),
        "archived_integration_states": analysis.get("archived_integration_states"),
        "rejected_steps_archive": rejected_stat, "rejected_attempts_trial_log": n_rej,
        "accepted_attempts_trial_log": n_acc, "trial_records_all_contexts": len(records),
        "integration_trial_records": analysis.get("integration_trial_records"),
        "integration_trial_states_not_stored": analysis.get("integration_trial_states_not_stored"),
        "function_evaluations": int(statistics["function_evaluations"]),
        "max_deviation_accepted_K": deviation_accepted, "max_deviation_outputs_K": deviation_outputs,
        "rejected_candidate_times_s": [entry["time_s"] for entry in analysis["rejected_attempts"]],
        "rejected_candidate_deviation_K": deviation_rejected, "local_tolerance_K": local_tolerance,
        "retries": len(retries), "retry_stage2_max_mismatch_K": worst_retry,
        "all_attempts_stage2_max_mismatch_K": analysis["start_mismatch_K"],
        "attempt_start_time_max_mismatch_s": analysis["start_time_mismatch_s"],
        "retry_distance_to_rejected_candidate_K": [entry["distance_to_rejected_candidate_K"] for entry in retries],
        "in_run_attempt_record": dict(attempt_record),
        "in_run_parameter_attempts": sum(1 for _, kind, _ in in_run if kind == "parameters"),
        "in_run_parameter_refused": refused["parameters"],
        "in_run_trial_record_attempts": sum(1 for _, kind, _ in in_run if kind == "trial"),
        "in_run_trial_record_refused": refused["trial"],
        "range_warnings_emitted": len(range_warnings), "status": archive.status,
    })
    case_record.metric("step5_coupled_checks", chk.count)
    chk.assert_all()


def test_step5_power_coupled_trial_states(case_record):
    chk = Checks(case_record, "步骤5", "power")
    params = build_parameters()
    cfg = SC["coupled_power"]
    run_id = cfg["run_id"]
    asset_record, scene_record = ps.example_power_records()
    power_parameters = ps.load_power_parameters(asset_record, scene_record)
    power_state = ps.power_state_from_scene(scene_record, run_id)
    power_record_T_B = float(scene_record["initial_state"]["T_B_K"])
    log: list[tuple] = []

    def solve(inputs, state, parameters):
        log.append(("solve", float(inputs.time_s), float(inputs.T_B_K), float(state.x_n), float(state.x_p)))
        return ps.solve_power_allocation(inputs, state, parameters)

    def hook(record):
        log.append(("hook", record))

    coupling = cp.PowerCoupling(parameters=power_parameters, initial_state=power_state, request_W=float(cfg["request_W"]),
                                solve=solve)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            archive = cp.run_coupled(params, ThermalState(run_id, 0.0, T_LIST), provider_for(params, run_id),
                                     float(cfg["t_end_s"]), power=coupling, trial_hook=hook)
            stop = None
        except cp.CoupledRunError as exc:
            archive, stop = exc.archive, exc
    chk("含 Power 的联合计算完成", "status completed",
        f"status {archive.status}，{describe(stop) if stop else '无报错'}", archive.status == "completed")

    accepted_y = np.asarray(archive.accepted["state"], dtype=float)
    accepted_T_B = column(accepted_y, 3, 8)
    output_T_B = column(archive.temperature_K, 3, 6)
    all_T_B = np.concatenate([accepted_T_B, output_T_B])
    nonfinite = int(np.count_nonzero(~np.isfinite(all_T_B)))
    low_K, high_K = BATTERY_RANGE_K
    T_B_min, T_B_max = least(all_T_B), worst(all_T_B)
    chk(
        "含 Power 的联合计算中电池温度在 Battery01 声明温区内",
        f"全部已接受状态与输出采样的电池温度为有限值，并在 {low_K} K 至 {high_K} K 内",
        f"已接受状态 {accepted_T_B.size} 个，输出采样 {output_T_B.size} 个，非有限值 {nonfinite} 个，"
        f"电池温度 {T_B_min!r} K 至 {T_B_max!r} K",
        accepted_T_B.size >= 1 and output_T_B.size >= 1 and nonfinite == 0
        and bool(np.all((all_T_B >= low_K) & (all_T_B <= high_K))),
    )

    pairs, mismatched, order_ok, contexts = 0, 0, True, {}
    first_T_B = None
    for index in range(0, len(log) - 1, 2):
        solve_entry, hook_entry = log[index], log[index + 1]
        if solve_entry[0] != "solve" or hook_entry[0] != "hook":
            order_ok = False
            break
        record = hook_entry[1]
        pairs += 1
        contexts[record.context] = contexts.get(record.context, 0) + 1
        if first_T_B is None:
            first_T_B = solve_entry[2]
        same = (record.time_s == solve_entry[1] and record.state[3] == solve_entry[2]
                and record.state[6] == solve_entry[3] and record.state[7] == solve_entry[4])
        if record.thermal_state is not None:
            same = same and record.thermal_state.temperature_K[3] == solve_entry[2]
        mismatched += int(not same)
    order_ok = order_ok and len(log) % 2 == 0
    power_calls = int(archive.statistics["power_calls"])
    chk(
        "Power 读取的电池温度来自同次试算的 ThermalState",
        "每次 solve_power_allocation 的 T_B_K 等于同一次计算的试算温度 temperature_K 中节点 B 的温度，锂占比等于同次试算状态",
        f"配对 {pairs} 次，不一致 {mismatched} 次，调用与记录交替 {order_ok}，归档 power_calls {power_calls}，"
        f"按计算场合 {contexts}",
        order_ok and pairs >= 1 and mismatched == 0 and pairs == power_calls,
    )
    chk(
        "电池初始温度只由 ThermalState 提供",
        f"第一次 Power 调用的 T_B_K 等于 ThermalState 初值 {T_BY_NODE['B']} K，不取 Power 场景记录的 {power_record_T_B} K",
        f"第一次 T_B_K {first_T_B!r} K",
        first_T_B == T_BY_NODE["B"] and first_T_B != power_record_T_B,
    )
    final_thermal, final_power = archive.final_thermal_state, archive.final_power_state
    shape_ok = accepted_y.ndim == 2 and accepted_y.shape[0] >= 1 and accepted_y.shape[1] == 8
    chk(
        "已接受状态含六个温度与两个锂占比",
        "accepted.state 每行 8 个值；final_thermal_state 与 final_power_state 取最后已接受状态",
        f"形状 {accepted_y.shape}；温度一致 "
        f"{shape_ok and final_thermal is not None and np.array_equal(final_thermal.temperature_K, accepted_y[-1, :6])}，"
        f"x_n 一致 {shape_ok and final_power is not None and final_power.x_n == accepted_y[-1, 6]}，"
        f"x_p 一致 {shape_ok and final_power is not None and final_power.x_p == accepted_y[-1, 7]}",
        bool(
            shape_ok and final_thermal is not None and final_power is not None
            and np.array_equal(final_thermal.temperature_K, accepted_y[-1, :6])
            and final_power.x_n == accepted_y[-1, 6] and final_power.x_p == accepted_y[-1, 7]
        ),
    )
    trial_records = [entry[1] for entry in log if entry[0] == "hook"]
    trial_keys = {np.asarray(r.state).tobytes() for r in trial_records if r.context == "integration"}
    integration_stored = [np.asarray(y).tobytes()
                          for y, kind in zip(accepted_y, archive.accepted["kind"]) if kind == "integration"]
    stored_keys = {np.asarray(y).tobytes() for y in accepted_y}
    not_stored = sum(1 for key in trial_keys if key not in stored_keys)
    chk(
        "已接受状态取自试算后被接受的状态，其余试算状态不归档",
        "每个积分已接受状态都曾作为试算状态被计算，且存在未归档的试算状态",
        f"积分已接受状态 {len(integration_stored)} 个，全部出现在试算记录中 "
        f"{all(key in trial_keys for key in integration_stored)}；不同的积分试算状态 {len(trial_keys)} 个，"
        f"未归档 {not_stored} 个",
        len(integration_stored) >= 1 and all(key in trial_keys for key in integration_stored) and not_stored >= 1,
    )
    range_warnings = [item for item in caught if issubclass(item.category, thermal.ThermalRangeWarning)]
    lithium = archive.lithium or {}
    x_n = np.asarray(lithium.get("x_n", []), dtype=float)
    q_b = np.asarray(archive.ports_W.get("Q_B_W", []), dtype=float)
    case_record.metric("coupled_power_run", {
        "run_id": run_id, "t_end_s": cfg["t_end_s"], "request_W": cfg["request_W"], "status": archive.status,
        "power_calls": power_calls, "paired_calls": pairs, "T_B_K_mismatches": mismatched,
        "first_T_B_K": first_T_B, "power_scene_record_T_B_K": power_record_T_B,
        "accepted_states": int(accepted_y.shape[0]) if accepted_y.ndim == 2 else 0,
        "integration_trial_states": len(trial_keys), "integration_trial_states_not_stored": not_stored,
        "T_B_range_K": [T_B_min, T_B_max],
        "T_B_samples": {"accepted_states": int(accepted_T_B.size), "output_samples": int(output_T_B.size),
                        "nonfinite": nonfinite},
        "battery_declared_range_K": list(BATTERY_RANGE_K),
        "x_n_range": [least(x_n), worst(x_n)], "x_n_nonfinite": int(np.count_nonzero(~np.isfinite(x_n))),
        "Q_B_W_range": [least(q_b), worst(q_b)], "Q_B_W_nonfinite": int(np.count_nonzero(~np.isfinite(q_b))),
        "range_warnings_emitted": len(range_warnings),
    })
    case_record.metric("step5_power_checks", chk.count)
    chk.assert_all()


def test_step5_event_search_trial_states(case_record):
    """Trial states of a located Power event: discarded integrations never reach the accepted record."""

    chk = Checks(case_record, "步骤5", "event")
    params = build_parameters()
    cfg = SC["coupled_power_event"]
    run_id = cfg["run_id"]
    t_force = float(cfg["forced_shortfall_from_s"])
    asset_record, scene_record = ps.example_power_records()
    power_parameters = ps.load_power_parameters(asset_record, scene_record)
    power_state = ps.power_state_from_scene(scene_record, run_id)
    tolerance_s = float(power_parameters.numerics.event_time_tol_s)
    injected: list[float] = []

    def solve(inputs, state, parameters):
        result = ps.solve_power_allocation(inputs, state, parameters)
        if result.valid and not result.event_required and state.load_connected and inputs.time_s >= t_force:
            injected.append(float(inputs.time_s))
            return ps.PowerResult(
                run_id=inputs.run_id, instance_id=inputs.instance_id, time_s=inputs.time_s,
                P_pv_W=None, P_load_W=None, Q_B_W=None, Q_D_W=None, dx_n_dt=None, dx_p_dt=None, battery=None,
                valid=True, event_required=True, can_supply_request=False,
                reason=f"supply_shortfall: injected by test case DM-001 for t >= {t_force} s",
                solar=result.solar, P_bus_W=None, diagnostics={"injected_by": "DM-001"},
            )
        return result

    records: list[Any] = []
    coupling = cp.PowerCoupling(parameters=power_parameters, initial_state=power_state, request_W=float(cfg["request_W"]),
                                solve=solve)
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        try:
            archive = cp.run_coupled(params, ThermalState(run_id, 0.0, T_LIST), provider_for(params, run_id),
                                     float(cfg["t_end_s"]), power=coupling, trial_hook=records.append)
            stop = None
        except cp.CoupledRunError as exc:
            archive, stop = exc.archive, exc
    statistics = archive.statistics
    events = list(archive.events)
    event_time = float(events[0]["time_s"]) if len(events) == 1 else float("nan")
    chk(
        "注入已确认的供电能力不足判定后事件被定位并应用",
        f"status completed，恰有 1 个 supply_loss 事件，时刻在 {t_force} s 至 {t_force + tolerance_s} s 内",
        f"status {archive.status}，{describe(stop) if stop else '无报错'}，事件 "
        f"{[(round(float(e['time_s']), 6), e['kind'], e['source']) for e in events]}，event_searches "
        f"{statistics['event_searches']}，bisection_iterations {statistics['bisection_iterations']}",
        archive.status == "completed" and len(events) == 1 and events[0]["kind"] == "supply_loss"
        and t_force <= event_time <= t_force + tolerance_s,
    )
    accepted_t = np.asarray(archive.accepted["time_s"], dtype=float)
    accepted_y = np.asarray(archive.accepted["state"], dtype=float)
    kinds = tuple(archive.accepted["kind"])
    connected = np.asarray(archive.accepted["load_connected"], dtype=bool)
    same_length = connected.shape == accepted_t.shape
    if same_length and math.isfinite(event_time):
        before_mask, after_mask = accepted_t <= event_time, accepted_t > event_time
        n_before, n_after = int(np.count_nonzero(before_mask)), int(np.count_nonzero(after_mask))
        on_before = n_before >= 1 and bool(np.all(connected[before_mask]))
        off_after = n_after >= 1 and not bool(np.any(connected[after_mask]))
    else:
        n_before = n_after = 0
        on_before = off_after = False
    switch = (
        len(events) == 1 and bool(events[0]["before"]["load_connected"])
        and not bool(events[0]["after"]["load_connected"])
    )
    chk(
        "保护状态只在已接受的事件边界改变",
        "恰有 1 个事件，事件记录中负载由接通变为断开；事件时刻及之前至少 1 个已接受状态且全部接通，"
        "之后至少 1 个已接受状态且全部断开",
        f"事件 {len(events)} 个，事件记录中负载由接通变为断开 {switch}；事件时刻及之前 {n_before} 个，全部接通 {on_before}；"
        f"之后 {n_after} 个，全部断开 {off_after}；load_connected 与 accepted 长度一致 {same_length}",
        same_length and switch and on_before and off_after,
    )
    stored = {np.asarray(y).tobytes() for y in accepted_y}
    inner = [r for r in records if r.outcome == "event_required" and r.context in ("integration", "event_location")]
    inner_stored = sum(1 for r in inner if np.asarray(r.state).tobytes() in stored)
    chk(
        "要求事件的试算状态未进入归档的已接受状态",
        "integration 与 event_location 场合中 Power 要求事件的试算状态均不在 accepted 中，且至少有 1 个",
        f"要求事件的试算状态 {len(inner)} 个，其中写入 {inner_stored} 个，时刻 "
        f"{sorted(round(float(r.time_s), 6) for r in inner)} s",
        len(inner) >= 1 and inner_stored == 0,
    )
    search = [r for r in records if r.context == "event_location" and r.solver_id >= 0]
    solver_ids = list(dict.fromkeys(r.solver_id for r in search))
    discarded = [sid for sid in solver_ids if any(r.outcome == "event_required" for r in search if r.solver_id == sid)]
    kept = [sid for sid in solver_ids if sid not in discarded]
    leaked = 0
    for sid in discarded:
        trial_states = [r for r in search if r.solver_id == sid][1:]  # the first evaluation is the accepted start
        leaked += sum(1 for r in trial_states if np.asarray(r.state).tobytes() in stored)
    kept_states = {np.asarray(r.state).tobytes() for r in search if r.solver_id in kept}
    located_accepted = [np.asarray(y).tobytes() for y, kind in zip(accepted_y, kinds) if kind == "event_location"]
    chk(
        "定位事件时被舍弃的积分未进入归档的已接受状态",
        "遇到事件的积分除起点外的试算状态均不在 accepted 中，accepted 中的 event_location 状态全部来自未遇到事件的积分",
        f"定位积分 {len(solver_ids)} 段，舍弃 {len(discarded)} 段，其试算状态写入 {leaked} 个；accepted 中 event_location "
        f"状态 {len(located_accepted)} 个，来自保留的积分 {all(key in kept_states for key in located_accepted)}",
        len(discarded) >= 1 and leaked == 0 and all(key in kept_states for key in located_accepted),
    )
    bridge = [(t, y) for t, y, kind in zip(accepted_t, accepted_y, kinds) if kind == "event_bridge"]
    decisions = [r for r in records if r.context == "boundary" and r.outcome == "event_required"]
    boundary_ok = (
        len(bridge) == 1 and bridge[0][0] == event_time and len(decisions) >= 1
        and all(r.time_s == event_time and np.array_equal(r.state, bridge[0][1]) for r in decisions)
    )
    chk(
        "事件判定使用已接受的边界状态",
        "确认事件的 boundary 判定与 accepted 中的 event_bridge 状态时刻相同、状态逐位相同",
        f"event_bridge {[round(float(t), 6) for t, _ in bridge]} s，boundary 判定 "
        f"{[(round(float(r.time_s), 6), bool(np.array_equal(r.state, bridge[0][1]) if bridge else False)) for r in decisions]}",
        bool(boundary_ok),
    )
    case_record.metric("coupled_power_event_run", {
        "run_id": run_id, "forced_shortfall_from_s": t_force, "event_time_tol_s": tolerance_s,
        "status": archive.status, "event_time_s": event_time, "events": len(events),
        "accepted_states": int(len(accepted_t)), "accepted_before_event": n_before, "accepted_after_event": n_after,
        "event_searches": int(statistics["event_searches"]), "bisection_iterations": int(statistics["bisection_iterations"]),
        "event_aborted_attempts": int(statistics["event_aborted_attempts"]),
        "discarded_event_search_steps": int(statistics["discarded_event_search_steps"]),
        "search_sub_integrations": len(solver_ids), "discarded_sub_integrations": len(discarded),
        "event_required_trial_states": len(inner), "event_required_trial_states_stored": inner_stored,
        "discarded_trial_states_stored": leaked, "injected_decisions": len(injected),
    })
    case_record.metric("step5_event_checks", chk.count)
    chk.assert_all()


# ------------------------------------------------------------------------------------------ step 6: exports


def _power_module(name: str) -> bool:
    return name.split(".")[0] == "sdtwin_sim" or "power" in name.lower()


def _kind_of(name: str) -> str:
    """Short description of a public name of the thermal package for the evidence text."""

    if name not in vars(thermal):
        return "未绑定"
    obj = getattr(thermal, name)
    if inspect.isclass(obj) and issubclass(obj, (Exception, Warning)):
        return "错误或警告类"
    if inspect.isclass(obj) and dataclasses.is_dataclass(obj):
        return "数据类"
    if inspect.isclass(obj):
        return "类"
    if inspect.isfunction(obj):
        return "函数"
    return f"常量 {type(obj).__name__}"


def test_step6_package_exports(case_record):
    chk = Checks(case_record, "步骤6", "package")
    declared = list(getattr(thermal, "__all__", []))
    package_dir = Path(thermal.__file__).resolve().parent
    files = sorted(path.name for path in package_dir.glob("*.py"))
    chk("thermal 包文件符合第 3.2 节", "、".join(sorted(ref.PACKAGE_FILES)), "、".join(files),
        files == sorted(ref.PACKAGE_FILES))
    types_module = importlib.import_module("thermal.types")
    for name in ref.APPENDIX_A_TYPES:
        obj = getattr(thermal, name, None)
        ok = (
            name in declared and inspect.isclass(obj) and dataclasses.is_dataclass(obj)
            and obj.__module__ == "thermal.types" and getattr(types_module, name, None) is obj
        )
        chk(f"导出数据类型 {name}", "在 __all__ 中，为 types.py 定义的数据类",
            f"在 __all__ {name in declared}，类 {inspect.isclass(obj)}，数据类 {dataclasses.is_dataclass(obj)}，"
            f"模块 {getattr(obj, '__module__', None)}", bool(ok))
    signatures = {
        "assemble_thermal_parameters": ("components", "connections", "overrides"),
        "prepare_surface_environment": ("orbit_input", "earth_flux", "parameters"),
        "calculate_surface_heat": ("state", "environment", "parameters"),
        "calculate_heat_flows": ("state", "parameters"),
        "thermal_derivative": ("state", "inputs", "parameters"),
    }
    for name, module_name in ref.APPENDIX_A_FUNCTIONS.items():
        obj = getattr(thermal, name, None)
        module = importlib.import_module(f"thermal.{module_name}")
        parameters = tuple(inspect.signature(obj).parameters) if callable(obj) else ()
        ok = (
            name in declared and inspect.isfunction(obj) and obj.__module__ == f"thermal.{module_name}"
            and getattr(module, name, None) is obj and parameters == signatures[name]
        )
        chk(f"导出函数 {name}", f"在 __all__ 中，定义于 {module_name}.py，参数 {signatures[name]}",
            f"在 __all__ {name in declared}，函数 {inspect.isfunction(obj)}，模块 {getattr(obj, '__module__', None)}，"
            f"参数 {parameters}", bool(ok))

    # The declared export list against what the package namespace binds. Module objects (the submodules of design
    # 3.2) are not API names; every other public name bound by __init__.py counts as exported.
    namespace = {key: value for key, value in vars(thermal).items() if not key.startswith("_")}
    module_objects = sorted(key for key, value in namespace.items() if inspect.ismodule(value))
    public = sorted(
        key for key, value in namespace.items()
        if not inspect.ismodule(value) and type(value).__module__ != "__future__"
    )
    unbound = [name for name in declared if name not in vars(thermal)]
    duplicates = sorted({name for name in declared if declared.count(name) > 1})
    undeclared = [name for name in public if name not in declared]
    chk(
        "包命名空间的公共名称与 __all__ 一致",
        "__all__ 中的名称均已绑定且不重复；命名空间中除模块对象外的公共名称均列入 __all__",
        f"__all__ {len(declared)} 个，未绑定 {unbound}，重复 {duplicates}；命名空间公共名称 {len(public)} 个，"
        f"未列入 __all__ 的 {undeclared}；模块对象 {module_objects}",
        not unbound and not duplicates and not undeclared,
        topic="namespace",
    )

    appendix = list(ref.APPENDIX_A_TYPES) + list(ref.APPENDIX_A_FUNCTIONS)
    allowed = list(ref.CONTRACT_ERROR_CLASSES)
    exported = sorted(set(declared) | set(public))
    errors_exported = [name for name in exported if name in allowed]
    bad_errors = [
        name for name in errors_exported
        if not (inspect.isclass(getattr(thermal, name, None)) and issubclass(getattr(thermal, name), (Exception, Warning))
                and getattr(thermal, name).__module__ == "thermal.types")
    ]
    missing = [name for name in appendix if name not in exported]
    extras = [name for name in exported if name not in appendix and name not in allowed]
    cause_parts = [f"thermal 包的公共名称共 {len(exported)} 个"]
    if missing:
        cause_parts.append(f"缺少附录 A 的 {join_cn(missing)}")
    if duplicates:
        cause_parts.append(f"__all__ 重复列出 {join_cn(duplicates)}")
    if bad_errors:
        cause_parts.append(f"{join_cn(bad_errors)} 不是 thermal.types 定义的错误或警告类")
    if extras:
        cause_parts.append(
            f"除附录 A 的 {len(appendix)} 个名称与 IMPLEMENTATION.md 允许的 {len(errors_exported)} 个错误与警告类外，"
            f"另含 {join_cn(extras)}，这 {len(extras)} 个名称不在附录 A 中，也不在 IMPLEMENTATION.md 允许的附加导出之内"
        )
    chk(
        "公共导出与附录 A 一致",
        f"__all__ 与命名空间的公共名称为附录 A 的 {len(appendix)} 个名称 {appendix}，另外只允许 IMPLEMENTATION.md "
        f"约定 __init__.py 在附录 A 之外导出的错误与警告类 {allowed}",
        f"公共名称 {len(exported)} 个；附录 A 缺少 {missing}；错误与警告类 {errors_exported}，不合要求 {bad_errors}；"
        f"附录 A 与约定之外 {len(extras)} 个 { {name: _kind_of(name) for name in extras} }",
        not missing and not extras and not bad_errors and not duplicates,
        topic="appendix_exact",
        cause="，".join(cause_parts),
    )

    # The Power interface is referenced, never defined (design 5.6 and appendix A): a scan of the five source files and
    # the attributes of the package and its submodules for the 13 public names of the Power design report appendix A.
    power_names = set(ref.POWER_APPENDIX_A_NAMES)
    findings: list[str] = []
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in power_names:
                findings.append(f"{path.name} 第 {node.lineno} 行定义 {node.name}")
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in power_names:
                findings.append(f"{path.name} 第 {node.lineno} 行赋值 {node.id}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _power_module(alias.name) or (alias.asname or "") in power_names:
                        findings.append(f"{path.name} 第 {node.lineno} 行导入 {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if _power_module(node.module or ""):
                    findings.append(f"{path.name} 第 {node.lineno} 行从 {node.module} 导入")
                for alias in node.names:
                    if alias.name in power_names or (alias.asname or "") in power_names:
                        findings.append(f"{path.name} 第 {node.lineno} 行导入 {alias.name}")
    submodules = [importlib.import_module(f"thermal.{Path(name).stem}") for name in sorted(ref.PACKAGE_FILES)
                  if name != "__init__.py"]
    holders = [thermal, *submodules]
    attributes = [f"{module.__name__}.{name}" for module in holders for name in sorted(power_names) if hasattr(module, name)]
    chk(
        "热模块未重新实现 Power 接口",
        f"thermal 的 {len(files)} 个源文件不定义、不赋值、不导入 Power 报告附录 A 的 {len(power_names)} 个公共名称，"
        f"也不导入 sdtwin_sim 或名称含 power 的模块；包与 {len(submodules)} 个子模块均无这些属性",
        f"源文件发现 {findings}；属性 {attributes}；扫描文件 {files}",
        not findings and not attributes,
        topic="power_names",
    )
    case_record.metric("exports", {
        "__all__": declared, "public_names": exported, "namespace_public_names": public,
        "module_objects": module_objects, "appendix_A": appendix, "contract_error_classes": allowed,
        "contract_error_classes_exported": errors_exported,
        "beyond_appendix_A_and_contract": {name: _kind_of(name) for name in extras},
        "missing_from_exports": missing, "package_files": files,
    })
    case_record.metric("power_interface_scan", {
        "names": sorted(power_names), "files_scanned": files, "modules_checked": [m.__name__ for m in holders],
        "source_findings": findings, "attributes": attributes,
    })
    case_record.metric("step6_checks", chk.count)
    chk.assert_all()


# ------------------------------------------------------------------------------------------ summary

PHASE_CN = {"setup": "准备", "call": "执行", "teardown": "清理"}


def _topic_states() -> dict[str, dict[str, Any]]:
    """State of every summary statement: ok, failed, incomplete or not_run."""

    table: dict[str, dict[str, Any]] = {}
    for topic, (func, subject) in TOPICS.items():
        if topic == "text":
            continue
        entries = [entry for entry in _LEDGER if entry["topic"] == topic]
        failed = [entry["label"] for entry in entries if not entry["passed"]]
        run = _RUNS.get(func)
        if run is None:
            state = "not_run"
        elif failed:
            state = "failed"
        elif run != "completed" or not entries:
            state = "incomplete"
        else:
            state = "ok"
        table[topic] = {"function": func, "subject": subject, "checks": len(entries), "failed": len(failed),
                        "function_completed": run == "completed", "state": state}
    return table


def _failure(info: dict[str, Any]) -> str:
    func, subject = info["function"], info["subject"]
    if info["state"] == "not_run":
        return f"{subject}所在的测试函数 {func} 未执行"
    if info["state"] == "failed":
        text = f"{subject}共记录 {info['checks']} 项，其中 {info['failed']} 项未通过"
        if not info["function_completed"]:
            text += f"，测试函数 {func} 未执行完毕"
        return text + "，见异常记录"
    return f"{subject}所在的测试函数 {func} 未执行完毕，已记录 {info['checks']} 项检查，见异常记录"


def _summary_sentences(m: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Sentences of summary_cn; each claim is gated by the state of its topic."""

    table = _topic_states()

    def ok(topic: str) -> bool:
        return table[topic]["state"] == "ok"

    def ran(topic: str) -> bool:
        return table[topic]["state"] != "not_run"

    def say(topic: str, text: str, fail_prefix: str = "") -> str:
        return text if ok(topic) else fail_prefix + _failure(table[topic])

    def skipped(what: str, topic: str) -> str:
        return f"{what}的测试函数 {table[topic]['function']} 未执行。"

    out = ["本用例按设计报告第 3.2 节、第 5.1 节表 6、第 6.1 节与附录 A 执行六个步骤。"]

    # step 1
    if not ran("fields"):
        out.append(skipped("第 1 步", "fields"))
    else:
        out.append(
            "第 1 步用正常输入构造 ThermalParameters、ThermalState、ThermalInputs 与 ThermalEvaluation 并读取全部字段，"
            + say("fields", "四个对象的字段名称与顺序与表 6 一致，均为构造后不能赋值的记录")
            + "；"
            + say("shapes",
                  "C_J_K、R_K_W、temperature_K、dT_dt_K_s、q_W、Q_env_W 与 Q_emit_W 依次为含 6、5、6、6、5、2、2 个有限值的"
                  "数组，热容、热阻与温度均为正值，ThermalState、ThermalInputs 与 ThermalEvaluation 带本次的运行标识与时刻，"
                  "ThermalInputs 的环境与四个功率取同一时刻，四个功率字段为浮点数，T_B_K 与 T_J_K 为温度标量")
            + "；"
            + say("records",
                  f"surfaces 只为太阳能板与散热板登记 {number(m.get('surface_records'))} 条外露表面记录，太阳能板正反面分开"
                  "登记，instance_map 中电源设备节点 D 对应 Controller01 与 PDU01，四个功率端口依次对应 SolarArray01、"
                  "Compute01、Battery01 与 PDU01，provenance 记录节点顺序、路径顺序与单位")
            + "。"
        )

    # step 2
    errors = m.get("order_max_errors") or {}
    relative = errors.get("relative") or {}
    if not ran("orders"):
        out.append(skipped("第 2 步", "orders"))
    else:
        out.append(
            "第 2 步组件与连接按打乱的顺序输入，"
            + say("orders",
                  f"C_J_K 仍按 S、J、C、B、D、R 依次为 {'、'.join(number(v) for v in m.get('C_J_K_J_per_K') or [])} J/K，"
                  f"R_K_W 按 SR、JC、CR、BR、DR 依次为 {'、'.join(number(v) for v in m.get('R_K_W_K_per_W') or [])} K/W，"
                  "temperature_K 与 dT_dt_K_s 按 S、J、C、B、D、R 排列，q_W 按路径顺序排列，Q_env_W 与 Q_emit_W 按 S、R "
                  "排列，环境数组按资产表面顺序排列；热容与热阻按式 T5、热流按式 T2、吸热与辐射功率按式 T4 与独立手算相比，"
                  f"最大相对误差为 {magnitude(worst(relative.values()) if relative else None)}，温度导数与按式 T3 的手算值"
                  f"相比，以该节点各功率项绝对值之和除以热容为尺度的最大误差为 {magnitude(errors.get('dT_dt_scaled'))}，"
                  f"cos_incidence 的最大绝对误差为 {magnitude(errors.get('cos_incidence_abs'))}，判据均为不超过 "
                  f"{magnitude(REL_TOL)}；T_B_K 与 T_J_K 分别等于本次输入的电池温度 {number(T_BY_NODE['B'])} K 与计算节点"
                  f"温度 {number(T_BY_NODE['J'])} K")
            + "。"
        )

    # step 3
    rates = m.get("dT_B_dt_K_s_by_Q_B_W") or {}
    signs = [float(value) for value in SC["Q_B_W_signs"]]
    values = [rates.get(f"{sign:+g}") for sign in signs]
    difference = m.get("dT_dt_difference_K_s") or []
    example = m.get("design_4_3_example") or {}
    if not ran("q_b_sign"):
        out.append(skipped("第 3 步", "q_b_sign"))
    else:
        out.append(
            "第 3 步"
            + say("q_b_sign",
                  f"电池参数取第 4.3 节算例的 C_B {number(EXAMPLE['C_B_J_K'])} J/K、R_BR {number(EXAMPLE['R_BR_K_W'])} K/W、"
                  f"T_B {number(EXAMPLE['T_B_K'])} K 与 T_R {number(EXAMPLE['T_R_K'])} K，Q_B_W 取 {number(signs[0])} W "
                  f"与 {number(signs[1])} W 时 ThermalInputs 保留数值与符号，电池温度导数分别为 {number(values[0])} K/s 与 "
                  f"{number(values[1])} K/s，与按式 T3 由 Q_B 减 q_BR 再除以 C_B 的手算值之差不超过 "
                  f"{magnitude(EXAMPLE_TOL_K_S)} K/s；第 4.3 节算例只给出 Q_B 为 {number(EXAMPLE['Q_B_W'])} W 的情形，"
                  f"本次该情形的 q_BR 为 {number(example.get('q_BR_W'))} W，电池温度导数为 "
                  f"{number(example.get('dT_B_dt_K_s'))} K/s，与算例相同，{number(signs[1])} W 的结果由同一组参数按式 "
                  "T3 得到；两次计算只有电池节点的导数不同，差值为 "
                  f"{number(difference[3] if len(difference) == 6 else None)} K/s")
            + "。"
        )

    # step 4
    invalid = m.get("invalid_constructions") or {}
    if not ran("invalid"):
        out.append(skipped("第 4 步", "invalid"))
    else:
        out.append(
            "第 4 步"
            + say("invalid",
                  f"四个对象的正常构造作为对照均成功，随后逐项注入 {number(invalid.get('total'))} 项异常构造，涵盖数组维数"
                  "不符、非有限值、热容或热阻非正、运行标识或时刻不一致，以及顺序、单位、端口实例、节点实例与表面记录错误，"
                  f"{number(invalid.get('rejected_as_specified'))} 项均以规定的 ThermalConfigurationError 或 "
                  "ThermalInputError 被拒绝，报错均含出错字段的名称，重复注入的报错相同",
                  f"逐项注入 {number(invalid.get('total'))} 项异常构造，其中 {number(invalid.get('rejected_as_specified'))}"
                  " 项以规定的错误类型被拒绝，" if invalid else "")
            + "。"
        )

    # step 5: read-only parameters after assembly
    modify = m.get("parameter_modification_attempts") or {}
    if not ran("read_only"):
        out.append(skipped("第 5 步参数只读检查", "read_only"))
    else:
        out.append(
            (f"第 5 步参数装配后对 ThermalParameters 进行 {number(modify.get('total'))} 种修改尝试，" if modify else "第 5 步")
            + say("read_only",
                  "均被拒绝，参数与温度导数逐位不变，provenance_as_dict 返回独立副本，构造后改写来源数组或装配后改写输入"
                  "记录均不影响参数")
            + "。"
        )

    # step 5: trial and accepted states in direct function calls
    writes = m.get("module_write_attempts") or {}
    if not ran("state_module"):
        out.append(skipped("函数调用中试算状态与已接受状态分离检查", "state_module"))
    else:
        out.append(
            "在模块层面，"
            + say("state_module",
                  "prepare_surface_environment、calculate_surface_heat、calculate_heat_flows 与 thermal_derivative 不修改"
                  "输入状态、输入与参数，试算状态是不与已接受状态共享温度数组的独立记录，建立并计算试算状态后已接受状态不变，"
                  "构造后改写来源数组或来源环境不影响状态与输入，对已接受状态、ThermalEvaluation 与 ThermalInputs 的 "
                  f"{number(writes.get('total'))} 种写入尝试均被拒绝，已接受状态与输入逐位不变，T_B_K 与 T_J_K 是输入温度"
                  "的数值副本")
            + "。"
        )

    # step 5: thermal-only coupled run, attempts from trial_hook after the start and the trial log
    run_a = m.get("coupled_thermal_only_run") or {}
    if not ran("trials"):
        out.append(skipped("仅含热模型的联合计算", "trials"))
    else:
        p_before, p_in = modify.get("total"), run_a.get("in_run_parameter_attempts")
        both = p_before + p_in if p_before is not None and p_in is not None else None
        in_run_ok = "均被拒绝"
        if ok("read_only") and both is not None:
            in_run_ok += f"，与装配后的尝试合计 {number(both)} 种"
        in_run_ok += "，运行后参数逐位不变，归档的参数记录与运行前一致，带修改尝试的计算与未设置 trial_hook 的计算逐位相同"
        if run_a:
            lead = (f"在仅含热模型的 {number(run_a.get('t_end_s'))} s 联合计算中，运行开始后在 trial_hook 中再对 "
                    f"ThermalParameters 进行 {number(p_in)} 种修改尝试，")
            trial_lead = (f"trial_hook 中另对 TrialRecord 的状态与试算 ThermalState 的温度进行 "
                          f"{number(run_a.get('in_run_trial_record_attempts'))} 种写入尝试，")
        else:
            lead, trial_lead = "在仅含热模型的联合计算中，", ""
        out.append(lead + say("in_run_params", in_run_ok) + "；" + trial_lead + say("in_run_trial", "均被拒绝") + "。")
        rejected_dev = run_a.get("rejected_candidate_deviation_K") or []
        out.append(
            (f"该联合计算出现 {number(run_a.get('rejected_steps_archive'))} 次被拒绝的积分步，trial_hook 收到积分过程中的 "
             f"{number(run_a.get('integration_trial_records'))} 个试算状态，其中 "
             f"{number(run_a.get('integration_trial_states_not_stored'))} 个未进入归档的已接受状态；" if run_a else "")
            + say("trials",
                  "由试算记录判定的被拒绝与被接受积分步数等于归档统计，归档中由积分得到的 "
                  f"{number(run_a.get('archived_integration_states'))} 个已接受状态依次逐位等于被接受积分步的终点试算状态，"
                  f"被拒绝积分步的终点试算状态偏离独立参考解 {join_cn([magnitude(v, 3) + ' K' for v in rejected_dev])}，"
                  f"均超过局部容限 {magnitude(run_a.get('local_tolerance_K'))} K，且未进入归档，"
                  f"{number(run_a.get('retries'))} 次重试均从上一已接受状态出发，第 2 级试算状态与按该状态推算的值最大相差 "
                  f"{magnitude(run_a.get('retry_stage2_max_mismatch_K'))} K，判据为 {magnitude(RETRY_START_TOL_K)} K；"
                  f"{number(run_a.get('accepted_states'))} 个已接受状态与按同一组方程用 SciPy DOP853 求得的独立参考解最大"
                  f"偏差为 {magnitude(run_a.get('max_deviation_accepted_K'))} K，判据为 {magnitude(ACCEPTED_REF_TOL_K)} K")
            + "。"
        )

    # step 5: coupled run with Power
    run_b = m.get("coupled_power_run") or {}
    t_b_range = run_b.get("T_B_range_K") or [None, None]
    samples = run_b.get("T_B_samples") or {}
    if not ran("power"):
        out.append(skipped("含 Power 的联合计算", "power"))
    else:
        out.append(
            (f"含 Power 的 {number(run_b.get('t_end_s'))} s 联合计算状态为 {clean_text(run_b.get('status', '未记录'))}，"
             if run_b else "")
            + say("power",
                  f"{number(run_b.get('power_calls'))} 次 Power 调用读取的电池温度均等于同次试算状态的电池温度，锂占比也取自"
                  f"同次试算状态，首次读取的电池温度为 ThermalState 初值 {number(run_b.get('first_T_B_K'))} K，不取 Power 场景"
                  f"记录中的 {number(run_b.get('power_scene_record_T_B_K'))} K，已接受状态含 6 个温度与 2 个锂占比，"
                  f"{number(run_b.get('integration_trial_states'))} 个不同的积分试算状态中 "
                  f"{number(run_b.get('integration_trial_states_not_stored'))} 个未归档，"
                  f"{number(samples.get('accepted_states'))} 个已接受状态与 {number(samples.get('output_samples'))} 个输出"
                  f"采样的电池温度在 {decimals(t_b_range[0], 3)} K 至 {decimals(t_b_range[1], 3)} K 之间，处于 Battery01 "
                  f"资产给出的适用温区 {number(BATTERY_RANGE_K[0])} K 至 {number(BATTERY_RANGE_K[1])} K 内")
            + "。"
        )

    # step 5: located Power event
    run_e = m.get("coupled_power_event_run") or {}
    event_time, forced = run_e.get("event_time_s"), run_e.get("forced_shortfall_from_s")
    delay = event_time - forced if event_time is not None and forced is not None else None
    if not ran("event"):
        out.append(skipped("事件定位联合计算", "event"))
    else:
        out.append(
            (f"另一次联合计算从 {number(forced)} s 起把 Power 结果替换为已确认供电能力不足的判定，计算状态为 "
             f"{clean_text(run_e.get('status', '未记录'))}，" if run_e else "")
            + say("event",
                  f"事件定位于 {decimals(event_time, 4)} s，比 {number(forced)} s 晚 {magnitude(delay)} s，在 "
                  f"event_time_tol_s 规定的 {number(run_e.get('event_time_tol_s'))} s 内，"
                  f"{number(run_e.get('event_required_trial_states'))} 个要求事件的试算状态与定位事件时被舍弃的 "
                  f"{number(run_e.get('discarded_sub_integrations'))} 段积分的试算状态均未进入归档的已接受状态，事件判定使用"
                  f"归档的边界状态，事件时刻及之前的 {number(run_e.get('accepted_before_event'))} 个已接受状态负载接通，"
                  f"之后的 {number(run_e.get('accepted_after_event'))} 个已接受状态负载断开")
            + "。"
        )

    # step 6
    exports = m.get("exports") or {}
    scan = m.get("power_interface_scan") or {}
    extras = list((exports.get("beyond_appendix_A_and_contract") or {}).keys())
    missing = exports.get("missing_from_exports") or []
    n_errors = len(exports.get("contract_error_classes_exported") or [])
    n_appendix = len(exports.get("appendix_A") or [])
    if ok("appendix_exact"):
        exact = (f"公共名称在附录 A 之外只增加 IMPLEMENTATION.md 允许的 {n_errors} 个错误与警告类，"
                 "公共导出与附录 A 一致")
    elif table["appendix_exact"]["state"] == "failed" and (extras or missing):
        exact = f"公共名称共 {len(exports.get('public_names') or [])} 个"
        if missing:
            exact += f"，缺少附录 A 的 {join_cn(missing)}"
        if extras:
            exact += (f"，除附录 A 的 {n_appendix} 个名称与 IMPLEMENTATION.md 允许的 {n_errors} 个错误与警告类外，另含 "
                      f"{join_cn(extras)}，共 {len(extras)} 个附录 A 未列出的名称")
        exact += "，公共导出与附录 A 不一致，见异常记录"
    else:
        exact = _failure(table["appendix_exact"])
    files = exports.get("package_files") or []
    out.append(
        "第 6 步检查包文件与公共导出，"
        + say("package",
              f"thermal 包由第 3.2 节的 {len(files)} 个源文件组成，附录 A 的 4 个数据类型由 types.py 定义并由 __init__.py "
              "导出，5 个函数由第 3.2 节所列文件定义并导出，参数与第 5 章一致")
        + "，"
        + say("namespace", "包命名空间中除模块对象外的公共名称与 __all__ 一致")
        + "；"
        + exact
        + "；"
        + say("power_names",
              f"thermal 包的 {len(scan.get('files_scanned') or [])} 个源文件与 "
              f"{max(len(scan.get('modules_checked') or []) - 1, 0)} 个子模块均未定义、赋值或导入 Power 报告附录 A 的 "
              f"{len(scan.get('names') or [])} 个公共名称，也未导入 Power 模块")
        + "。"
    )
    return out, table


def _anomaly_items(checks: list[dict[str, Any]], not_run: list[str]) -> list[str]:
    """One Chinese item per failed check, per test function that raised and per test function not executed."""

    causes = {entry["label"]: entry.get("cause") for entry in _LEDGER}
    items: list[str] = []
    for check in checks:
        if check["passed"]:
            continue
        crash = re.fullmatch(r"(test_\w+) (setup|call|teardown)", check["name"])
        if crash:
            func, phase = crash.groups()
            if phase == "call" and _RUNS.get(func) == "completed":
                items.append(f"测试函数 {func} 因本函数的检查未通过而报错，pytest 将其记为 1 项未通过的检查")
            else:
                found = re.findall(r"\b([A-Za-z_]\w*(?:Error|Exception|Exit|Interrupt))\b", check["actual"])
                kind = found[-1] if found else "异常"
                items.append(f"测试函数 {func} 在{PHASE_CN[phase]}阶段报错 {kind}，该函数其后的检查未执行")
            continue
        name = clean_text(check["name"])
        cause = causes.get(check["name"])
        if cause:
            items.append(f"检查 {name} 未通过，{clean_text(cause)}")
        else:
            items.append(f"检查 {name} 未通过，期望 {clean_text(check['expected'], 160)}，"
                         f"实际 {clean_text(check['actual'], 220)}")
    items.extend(f"测试函数 {func} 未执行" for func in not_run)
    return items


def test_summary(case_record):
    """Chinese summary and anomalies from the recorded checks and metrics (runs last)."""

    chk = Checks(case_record, "汇总", "text")
    try:
        sentences, table = _summary_sentences(case_record.metrics)
        failed_checks = [check for check in case_record.checks if not check["passed"]]
        functions = [name for name, value in globals().items()
                     if name.startswith("test_") and name != "test_summary" and inspect.isfunction(value)]
        not_run = [name for name in functions if name not in _RUNS]
        items = _anomaly_items(case_record.checks, not_run)
    except Exception as exc:
        case_record.summary(f"结果说明在生成时报错 {type(exc).__name__}，本用例不满足验收判据，未通过项见异常记录。")
        case_record.anomalies(f"测试函数 test_summary 生成结果说明时报错 {type(exc).__name__}，"
                              "pytest 将其记为 1 项未通过的检查。")
        raise
    body = "".join(sentences)

    def verdict(extra_failed: int) -> str:
        # extra_failed: checks that become failed after this point, so the count matches the evidence file
        count = len(failed_checks) + extra_failed
        if count:
            return f"结果文件中共有 {count} 项检查未通过，不满足验收判据，未通过项见异常记录。"
        if not_run:
            return f"有 {len(not_run)} 个测试函数未执行，本次执行不完整，不作满足验收判据的结论。"
        return "全部检查通过，满足验收判据。"

    summary = body + verdict(0)
    anomalies = "；".join(items) + "。" if items else "无"
    summary_problems, anomaly_problems = text_rule_problems(summary), text_rule_problems(anomalies)
    text_ok = chk(
        "summary_cn 与 anomalies_cn 符合报告文字规则",
        "不含括号、破折号、问号、科学计数法、上标字符与排版标记；负号为 U+2212；10 的幂写作 1×10^{−n}",
        f"summary_cn 问题 {summary_problems or '无'}，anomalies_cn 问题 {anomaly_problems or '无'}",
        not summary_problems and not anomaly_problems,
    )
    if not text_ok:
        # The rule check just failed and the assertion below makes pytest record test_summary as a failed check too.
        items.append(
            "summary_cn 或 anomalies_cn 含" + "、".join(sorted(set(summary_problems) | set(anomaly_problems)))
            + "，已按报告文字规则替换后写入，测试函数 test_summary 因此报错，pytest 将其记为 1 项未通过的检查"
        )
        summary = clean_text(body) + verdict(2)
        anomalies = clean_text("；".join(items) + "。")
    case_record.summary(summary)
    case_record.anomalies(anomalies)
    if not_run and not failed_checks and text_ok:
        case_record.status("partial")
    case_record.metric("summary_support", table)
    chk.assert_all()
