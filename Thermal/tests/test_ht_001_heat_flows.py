"""HT-001 组件传热计算: calculate_heat_flows against T2 of the SDTwin thermal design report.

Design basis: 4.2 (T2 q_ij = (T_i - T_j) / R_ij, signed flows, the five paths SR, JC, CR, BR, DR), 4.3 (battery
example T_B = 303 K, T_R = 300 K, R_BR = 0.5 K/W, q_BR = 6 W) and 5.5 (both end temperatures and the resistance read
in the fixed order SR, JC, CR, BR, DR, T2 evaluated once per path, positive from the first node of the path name to
the second, errors for missing nodes, wrong array order, non-positive resistance and non-finite inputs, no state
update, no zero resistance or clipping in place of a path).

The case (CASES['HT-001'] in test_report/build_test_report_cn.py) has one precondition (PA-001 passed, the five
resistances assembled), four steps, three inputs, three expected results and two acceptance criteria; each one is
recorded through case_record. References are the hand calculation table in tests/data/ht_001/ht001_inputs.json and the
exact rational T2 and T5 of tests/data/ht_001/t2_reference.py, which does not import the thermal package.

Array order. The parameter object declares its node and path order in provenance (node_order, path_order); a changed
declaration is the wrong array order the module can detect, and only such injections are recorded under 数组次序不符.
The state temperature array carries no order of its own: ThermalState defines it as S, J, C, B, D, R (design table 6).
Injections that change the shape or the type of an array (a mapping keyed by node name, whatever its key order, a
1 x 6 array, six resistances) are recorded under 数组形状或类型不符.

Chinese texts. summary_cn and anomalies_cn are built only from the evidence recorded by this module, and no value can
make their construction fail. They are written by test_acceptance_and_summary and written again when the module
finishes, so that failures conftest records after the last test and test functions that never ran or stopped early
are included.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import thermal
import thermal.model as thermal_model
from thermal import (
    ThermalConfigurationError,
    ThermalInputError,
    ThermalInputs,
    ThermalParameters,
    ThermalState,
    assemble_thermal_parameters,
    calculate_heat_flows,
    thermal_derivative,
)

pytestmark = pytest.mark.case("HT-001")

TESTS_DIR = Path(__file__).resolve().parent
DATA_DIR = TESTS_DIR / "data" / "ht_001"
INPUTS = json.loads((DATA_DIR / "ht001_inputs.json").read_text(encoding="utf-8"))


def _load_reference() -> Any:
    spec = importlib.util.spec_from_file_location("ht001_t2_reference", DATA_DIR / "t2_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REF = _load_reference()
DESIGN_NODES = REF.NODES  # S, J, C, B, D, R (design 1.4, table 6)
DESIGN_PATHS = REF.PATHS  # SR, JC, CR, BR, DR (design 4.2, table 6)
REL_TOL = 1e-12  # acceptance criterion of HT-001
RUN_ID = INPUTS["run_id"]
TIME_S = float(INPUTS["time_s"])
HAND = INPUTS["hand_calculation"]
BASE_T = HAND["states"]["base"]["temperature_K"]
# Hand T5 values (decimal) and the exact T5 values of the float inputs the module receives.
R_HAND = {path: Fraction(HAND["resistance_K_W"][path]["value"]) for path in DESIGN_PATHS}
R_EXACT = {item["path"]: REF.t5_resistance(item) for item in INPUTS["connections"]}
BR = DESIGN_PATHS.index("BR")
# Design 5.5: the two end temperatures of each path, first node then second as in T2, path by path in the fixed order.
EXPECTED_T_SEQUENCE = [node for path in DESIGN_PATHS for node in REF.ends(path)]

# Precondition PA-001: its evidence, which must not predate the thermal package sources it was produced from.
PRECONDITION_CASE = "PA-001"
PRECONDITION_FILE = TESTS_DIR / "results" / f"{PRECONDITION_CASE}.json"
THERMAL_SOURCES = tuple(sorted(Path(thermal.__file__).resolve().parent.glob("*.py")))
STATUS_CN = {"pass": "通过", "fail": "不通过", "partial": "部分执行", "not_run": "未执行"}

# Shared across the test functions of this module, read by the acceptance checks and by the Chinese texts.
CTX: dict[str, Any] = {
    "comparisons": [],
    "abnormal": [],
    "numbers": {},
    "flags": {},
    "completed": set(),
    "record": None,
    "current": None,
    "text_problems": set(),
}

# Every test function of the case in execution order, with the case item it executes (for the unexecuted list).
PLAN = {
    "test_precondition_pa001_passed": "前置条件 PA-001 已通过的核对",
    "test_precondition_five_resistances_assembled": "前置条件 五条连接热阻已装配的核对",
    "test_step1_five_paths_and_battery_example": "步骤1 五条连接热流与手算的比较",
    "test_step2_reversed_end_temperatures": "步骤2 对调两端温度的检查",
    "test_input2_equal_end_temperatures": "输入2 两端温度相等的检查",
    "test_step3_positive_from_first_to_second": "步骤3 正值方向的检查",
    "test_expect2_single_evaluation_and_no_state_update": "预期2 每条路径只求值一次与函数没有状态更新的检查",
    "test_step4_abnormal_inputs": "步骤4 逐项注入异常输入",
    "test_expect3_no_zero_resistance_or_clipping": "预期3 连接未装配与有效极端输入的检查",
    "test_acceptance_and_summary": "预期1、预期3 与两条验收判据的判定",
}
# Test functions whose flows enter acceptance 1, and those whose abnormal inputs enter acceptance 2.
COMPARING = (
    "test_step1_five_paths_and_battery_example",
    "test_step2_reversed_end_temperatures",
    "test_input2_equal_end_temperatures",
    "test_step3_positive_from_first_to_second",
    "test_expect2_single_evaluation_and_no_state_update",
    "test_expect3_no_zero_resistance_or_clipping",
)
INJECTING = ("test_step4_abnormal_inputs", "test_expect3_no_zero_resistance_or_clipping")
ORDER_CATEGORY = "数组次序不符"
FORM_CATEGORY = "数组形状或类型不符"


# --------------------------------------------------------------------------- helpers


class _Checks:
    """Records a check through case_record and remembers the failed names for the pytest assertion."""

    def __init__(self, case_record: Any) -> None:
        self._record = case_record
        self.failed: list[str] = []

    def __call__(self, name: str, expected: str, actual: str, passed: Any) -> bool:
        passed = bool(passed)
        self._record.check(name, expected, actual, passed)
        if not passed:
            self.failed.append(name)
        return passed


class _TaggedLog(list):
    """Read log of one array for REF.ReadCounter; every read is also appended, tagged, to a log shared by all arrays."""

    def __init__(self, tag: str, merged: list[tuple[str, int]]) -> None:
        super().__init__()
        self.tag = tag
        self.merged = merged

    def extend(self, indices: Iterable[Any]) -> None:
        items = [int(index) for index in indices]
        super().extend(items)
        self.merged.extend((self.tag, index) for index in items)


def _done() -> None:
    """Marks the running test function as completed: every check it plans has been recorded."""

    CTX["completed"].add(CTX["current"])


def _array(temperature_K: dict[str, Any]) -> np.ndarray:
    return np.array([float(temperature_K[node]) for node in DESIGN_NODES], dtype=float)


def _state(temperature_K: dict[str, Any]) -> ThermalState:
    return ThermalState(RUN_ID, TIME_S, _array(temperature_K))


def _flows(params: Any, temperature_K: dict[str, Any]) -> np.ndarray:
    result = calculate_heat_flows(_state(temperature_K), params)
    return np.array(result["q_W"], dtype=float)


def _fmt(values: Any) -> str:
    return "[" + ", ".join(repr(float(value)) for value in np.asarray(values, dtype=float).ravel()) + "]"


def _bits(values: Any) -> bytes:
    array = np.ascontiguousarray(np.asarray(values, dtype=float))
    return repr(array.shape).encode() + array.tobytes()


def _same_bits(first: Any, second: Any) -> bool:
    """Bitwise identity of two float arrays (NaN equals NaN, 0.0 differs from -0.0)."""

    return _bits(first) == _bits(second)


def _rel_diff(value: Any, reference: Any) -> float:
    value, reference = float(value), float(reference)
    if not (math.isfinite(value) and math.isfinite(reference)) or reference == 0.0:
        return math.inf
    return abs(value - reference) / abs(reference)


def _label(names: tuple[str, ...], index: int) -> str:
    return names[index] if 0 <= index < len(names) else f"index {index}"


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _compare(label: str, q_values: Any, temperature_K: dict[str, Any], resistance: dict[str, Fraction]) -> list[float]:
    """Relative errors of the five module flows against exact T2; every comparison is kept for acceptance 1."""

    reference = REF.t2_flows(temperature_K, resistance)
    errors = []
    for index, path in enumerate(DESIGN_PATHS):
        value = float(q_values[index])
        error = REF.relative_error(value, reference[path])
        errors.append(error)
        CTX["comparisons"].append(
            {
                "label": label,
                "path": path,
                "value_W": value,
                "reference_W": float(reference[path]),
                "zero_reference": reference[path] == 0,
                "relative_error": error,
            }
        )
    return errors


def _compare_hand(label: str, q_values: Any, state_key: str) -> list[float]:
    """Relative errors against the hand calculation table of one tabulated state."""

    table = HAND["states"][state_key]["q_W"]
    errors = []
    for index, path in enumerate(DESIGN_PATHS):
        value = float(q_values[index])
        reference = Fraction(table[path]["value"])
        error = REF.relative_error(value, reference)
        errors.append(error)
        CTX["comparisons"].append(
            {
                "label": f"{label} (hand table)",
                "path": path,
                "value_W": value,
                "reference_W": float(reference),
                "zero_reference": reference == 0,
                "relative_error": error,
            }
        )
    return errors


def _duck_state(temperature: Any = None, *, time_s: Any = TIME_S, drop_temperature: bool = False) -> SimpleNamespace:
    """A state-like object that skips the ThermalState construction checks, to reach the function's own checks."""

    fields: dict[str, Any] = {"run_id": RUN_ID, "time_s": time_s}
    if not drop_temperature:
        fields["temperature_K"] = temperature
    return SimpleNamespace(**fields)


def _param_fields(params: ThermalParameters, changes: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "C_J_K": params.C_J_K,
        "R_K_W": params.R_K_W,
        "surfaces": params.surfaces,
        "instance_map": params.instance_map,
        "provenance": dict(params.provenance),
    }
    changes = dict(changes)
    fields["provenance"].update(changes.pop("provenance", {}))
    fields.update(changes)
    return fields


def _duck_params(params: ThermalParameters, **changes: Any) -> SimpleNamespace:
    """A parameter-like object with one field changed that skips the ThermalParameters construction checks."""

    return SimpleNamespace(**_param_fields(params, changes))


def _rebuilt_params(params: ThermalParameters, **changes: Any) -> ThermalParameters:
    """The same fields passed through the ThermalParameters constructor (its construction guard)."""

    return ThermalParameters(**_param_fields(params, changes))


def _r_with(index: int, value: float, size: int = 5) -> np.ndarray:
    values = [float(R_EXACT[path]) for path in DESIGN_PATHS]
    values = (values + [1.0] * size)[:size]
    values[index] = value
    return np.array(values, dtype=float)


def _connections_with(path: str, replacement: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Copy of the five connections with one path replaced, or removed when replacement is None."""

    out = []
    for item in INPUTS["connections"]:
        if item["path"] != path:
            out.append(dict(item))
        elif replacement is not None:
            out.append(dict(replacement, path=path))
    return out


def _describe(value: Any) -> str:
    if isinstance(value, dict) and "q_W" in value:
        return f"dict with q_W = {_fmt(value['q_W'])} W"
    return f"{type(value).__name__} {value!r}"[:300]


def _inject(
    check: _Checks,
    prefix: str,
    category: str,
    label: str,
    call: Callable[[], Any],
    expected_class: type,
    tokens: list[str],
    tag: str | None = None,
) -> bool:
    """Inject one abnormal input twice; it must raise the contract error naming the field, identically both times."""

    outcomes = []
    for _ in range(2):
        try:
            value = call()
        except Exception as exc:  # noqa: BLE001  any exception is evidence, the class is checked below
            outcomes.append((type(exc), str(exc), None))
        else:
            outcomes.append((None, "", value))
    (cls1, msg1, val1), (cls2, msg2, _) = outcomes
    raised = cls1 is not None
    right_class = raised and issubclass(cls1, expected_class)
    names_field = raised and all(token in msg1 for token in tokens)
    repeatable = (cls1, msg1) == (cls2, msg2)
    if raised:
        second = "identical on the second injection" if repeatable else f"second injection differs: {cls2}: {msg2}"
        actual = f"{cls1.__name__}: {msg1} | {second}"
    else:
        actual = f"no error, returned {_describe(val1)}"
    passed = check(
        f"{prefix} {category} {label}",
        f"{expected_class.__name__} whose message names {tokens}; the same error on a second injection; no heat flow "
        "returned and no zero resistance or clipped flow used",
        actual[:900],
        raised and right_class and names_field and repeatable,
    )
    CTX["abnormal"].append(
        {
            "prefix": prefix,
            "category": category,
            "label": label,
            "tag": tag,
            "passed": passed,
            "raised": raised,
            "error": cls1.__name__ if raised else None,
            "message": msg1[:400],
        }
    )
    return passed


# --------------------------------------------------------------------------- number text for the Chinese report


def _nonfinite_cn(number: float) -> str:
    if math.isnan(number):
        return "NaN"
    return "无穷大" if number > 0 else "负无穷大"


def _sci_cn(value: Any, digits: int = 2) -> str:
    """Scientific notation in the report markup, for example 1.1×10^{−16}; never fails on inf or NaN."""

    number = float(value)
    if not math.isfinite(number):
        return _nonfinite_cn(number)
    if number == 0.0:
        return "0"
    mantissa, exponent = f"{number:.{digits - 1}e}".split("e")
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".")
    power = int(exponent)
    return mantissa.replace("-", "−") + "×10^{" + ("−" if power < 0 else "") + str(abs(power)) + "}"


def _num_cn(value: Any) -> str:
    """Plain decimal between 1e-3 and 1e7, scientific notation otherwise; U+2212 for the minus sign."""

    number = float(value)
    if not math.isfinite(number):
        return _nonfinite_cn(number)
    if number == 0.0:
        return "0"
    if 1e-3 <= abs(number) < 1e7:
        text = f"{number:.10g}"
        if "e" not in text:
            return text.replace("-", "−")
    return _sci_cn(number)


def _qty_cn(value: Any, unit: str) -> str:
    number = float(value)
    return f"{_num_cn(number)} {unit}" if math.isfinite(number) else _nonfinite_cn(number)


def _short_cn(value: Any) -> str:
    """Four significant digits between 0.01 and 1e4, two-digit scientific notation otherwise."""

    number = float(value)
    if not math.isfinite(number):
        return _nonfinite_cn(number)
    if number == 0.0:
        return "0"
    if 1e-2 <= abs(number) < 1e4:
        text = f"{number:.4g}"
        if "e" not in text:  # 9999.5 rounds to 1e+04
            return text.replace("-", "−")
    return _sci_cn(number)


def _qty_short_cn(value: Any, unit: str) -> str:
    number = float(value)
    return f"{_short_cn(number)} {unit}" if math.isfinite(number) else _nonfinite_cn(number)


def _pow2_cn(value: Any) -> str:
    """2^{−20} for an exact power of two, otherwise the plain number."""

    number = float(value)
    if math.isfinite(number) and number > 0.0:
        mantissa, exponent = math.frexp(number)
        if mantissa == 0.5:
            power = exponent - 1
            return "2^{" + ("−" if power < 0 else "") + str(abs(power)) + "}"
    return _num_cn(number)


def _list_cn(items: Iterable[str]) -> str:
    return "、".join(items)


# --------------------------------------------------------------------------- precondition evidence


def _precondition_evidence(case_record: Any) -> dict[str, Any]:
    """Status of PA-001: its record in this pytest session when it ran earlier in the session, else its evidence file."""

    newest = max(THERMAL_SOURCES, key=lambda path: path.stat().st_mtime)
    newest_time = newest.stat().st_mtime
    info: dict[str, Any] = {
        "case": PRECONDITION_CASE,
        "newest_thermal_source": f"thermal/{newest.name}",
        "newest_thermal_source_modified": _iso(newest_time),
    }
    conftest_module = sys.modules.get(type(case_record).__module__)
    records = getattr(conftest_module, "_RECORDS", None)
    record = records.get(PRECONDITION_CASE) if isinstance(records, dict) else None
    if record is not None:
        checks = list(record.checks)
        info.update(
            source="session",
            case_id=record.case_id,
            status=record.resolved_status(),
            checks=len(checks),
            failed=sum(1 for item in checks if not item["passed"]),
            current=True,
        )
        return info
    if not PRECONDITION_FILE.is_file():
        info.update(source="missing", path=f"tests/results/{PRECONDITION_FILE.name}")
        return info
    data, written, problem = None, None, None
    for _ in range(3):  # another process may be rewriting the file
        try:
            written = PRECONDITION_FILE.stat().st_mtime
            data = json.loads(PRECONDITION_FILE.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError) as exc:
            problem = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)
    if not isinstance(data, dict):
        info.update(source="unreadable", path=f"tests/results/{PRECONDITION_FILE.name}", problem=problem)
        return info
    checks = data.get("checks") if isinstance(data.get("checks"), list) else []
    info.update(
        source="file",
        path=f"tests/results/{PRECONDITION_FILE.name}",
        case_id=data.get("case_id"),
        status=data.get("status"),
        checks=len(checks),
        failed=sum(1 for item in checks if not (isinstance(item, dict) and item.get("passed") is True)),
        written=_iso(written),
        current=written >= newest_time,
    )
    return info


def _precondition_met(info: dict[str, Any]) -> bool:
    return (
        info.get("source") in ("session", "file")
        and info.get("case_id") == PRECONDITION_CASE
        and info.get("status") == "pass"
        and info.get("checks", 0) > 0
        and info.get("failed") == 0
        and bool(info.get("current"))
    )


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def params() -> ThermalParameters:
    """Precondition of the case: the five path resistances assembled by assemble_thermal_parameters (T5)."""

    return assemble_thermal_parameters(INPUTS["components"], INPUTS["connections"], None)


@pytest.fixture(autouse=True)
def _track(request: pytest.FixtureRequest, case_record: Any) -> None:
    CTX["record"] = case_record
    CTX["current"] = request.node.name


@pytest.fixture(scope="module", autouse=True)
def _texts_at_module_end() -> Any:
    """Rewrites the Chinese texts after the last test, when every failure entry of conftest is in the record."""

    yield
    if CTX["record"] is not None:
        _write_texts(CTX["record"], final=True)


# --------------------------------------------------------------------------- precondition


def test_precondition_pa001_passed(case_record: Any) -> None:
    check = _Checks(case_record)
    info = _precondition_evidence(case_record)
    if info["source"] == "session":
        where = "PA-001 record of this pytest session (PA-001 ran before HT-001)"
    elif info["source"] == "file":
        where = f"{info['path']} written {info['written']}"
    else:
        where = f"{info.get('path')} {info['source']} {info.get('problem') or ''}".strip()
    check(
        "前置条件 PA-001 已通过",
        "the PA-001 record of this pytest session, or else tests/results/PA-001.json, has case_id PA-001, status pass, "
        "at least one check and no failed check; an evidence file must be written after the last change of the thermal "
        "package sources, so that it applies to the module under test",
        f"{where}; case_id {info.get('case_id')!r}, status {info.get('status')!r}, {info.get('checks')} checks, "
        f"{info.get('failed')} failed; newest thermal source {info['newest_thermal_source']} modified "
        f"{info['newest_thermal_source_modified']}, evidence current {info.get('current')}",
        _precondition_met(info),
    )
    case_record.metric("precondition_PA-001", info)
    CTX["numbers"]["pa001"] = info
    CTX["flags"]["pa001"] = _precondition_met(info)
    _done()
    assert not check.failed, check.failed


def test_precondition_five_resistances_assembled(case_record: Any, params: ThermalParameters) -> None:
    check = _Checks(case_record)
    module_r = [float(value) for value in np.asarray(params.R_K_W, dtype=float).ravel()]
    complete = len(module_r) == len(DESIGN_PATHS)
    errors_hand, errors_exact = [math.inf], [math.inf]
    if complete:
        errors_hand = [REF.relative_error(module_r[i], R_HAND[path]) for i, path in enumerate(DESIGN_PATHS)]
        errors_exact = [REF.relative_error(module_r[i], R_EXACT[path]) for i, path in enumerate(DESIGN_PATHS)]
    assembled = check(
        "前置条件 五条连接的热阻已按式 T5 装配并与手算一致",
        "R_K_W in SR, JC, CR, BR, DR = 0.8, 0.09, 0.12, 0.5, 1.5 K/W from the hand T5 table, relative error <= 1e-12; "
        "R_BR = 0.5 K/W as in design 4.3",
        f"R_K_W = {module_r} K/W; max relative error {max(errors_hand):.3e} against the hand table and "
        f"{max(errors_exact):.3e} against exact T5 of the float inputs",
        complete and max(errors_hand) <= REL_TOL and max(errors_exact) <= REL_TOL,
    )
    if complete:
        case_record.metric("R_K_W_assembled", dict(zip(DESIGN_PATHS, module_r, strict=True)))
    case_record.metric("R_K_W_hand", {path: HAND["resistance_K_W"][path]["value"] for path in DESIGN_PATHS})
    CTX["numbers"]["R_K_W"] = module_r
    CTX["flags"]["resistances_assembled"] = assembled

    # Self-check of the references: the exact T2 program reproduces every tabulated hand value.
    worst = Fraction(0)
    for state in HAND["states"].values():
        computed = REF.t2_flows(state["temperature_K"], R_HAND)
        for path in DESIGN_PATHS:
            worst = max(worst, abs(computed[path] - Fraction(state["q_W"][path]["value"])))
    CTX["flags"]["reference_selfcheck"] = check(
        "参考 手算表与独立精确计算一致",
        "exact rational T2 with the hand T5 resistances reproduces every hand table value of the four tabulated states",
        f"largest absolute difference {float(worst)!r} W over {len(HAND['states'])} states x 5 paths",
        worst == 0,
    )
    _done()
    assert not check.failed, check.failed


# --------------------------------------------------------------------------- step 1


def test_step1_five_paths_and_battery_example(case_record: Any, params: ThermalParameters) -> None:
    check = _Checks(case_record)
    state = _state(BASE_T)
    result = calculate_heat_flows(state, params)
    is_dict = isinstance(result, dict)
    keys = sorted(result) if is_dict else type(result).__name__
    shape_ok = is_dict and "q_W" in result and np.shape(result["q_W"]) == (5,)
    q = np.array(result["q_W"], dtype=float) if shape_ok else np.full(5, np.nan)
    check(
        "步骤1 返回字典含 run_id、time_s 与 q_W",
        f"dict with run_id = {RUN_ID!r}, time_s = {TIME_S!r} and q_W of shape (5,)",
        f"type {type(result).__name__}, keys {keys}, run_id {result.get('run_id') if is_dict else None!r}, "
        f"time_s {result.get('time_s') if is_dict else None!r}, q_W shape {np.shape(result.get('q_W')) if is_dict else None}",
        is_dict
        and {"run_id", "time_s", "q_W"} <= set(result)
        and result["run_id"] == RUN_ID
        and result["time_s"] == TIME_S
        and shape_ok,
    )

    table = HAND["states"]["base"]["q_W"]
    errors = _compare_hand("base", q, "base")
    for index, path in enumerate(DESIGN_PATHS):
        check(
            f"步骤1 {path} 热流与手算一致",
            f"q_{path} = {table[path]['formula']} = {table[path]['value']} W, relative error <= 1e-12",
            f"q_{path} = {float(q[index])!r} W, relative error {errors[index]:.3e}",
            errors[index] <= REL_TOL,
        )

    hand_values = {path: Fraction(table[path]["value"]) for path in DESIGN_PATHS}
    identified = []
    for index in range(5):
        hits = [path for path in DESIGN_PATHS if REF.relative_error(q[index], hand_values[path]) <= REL_TOL]
        identified.append(hits[0] if len(hits) == 1 else "unidentified")
    check(
        "步骤1 q_W 按 SR、JC、CR、BR、DR 的固定顺序排列",
        "PATH_ORDER = ('SR', 'JC', 'CR', 'BR', 'DR') and q_W[k] equals the hand value of the k-th path "
        "(the five hand values are distinct, so a permutation would be detected)",
        f"PATH_ORDER = {tuple(thermal.types.PATH_ORDER)}; paths identified from the q_W values: {identified}",
        tuple(thermal.types.PATH_ORDER) == DESIGN_PATHS and tuple(identified) == DESIGN_PATHS,
    )

    example = INPUTS["battery_example"]
    error = REF.relative_error(q[BR], Fraction(example["q_BR_W"]))
    example_ok = check(
        "步骤1 电池算例 q_BR 为 6 W",
        "T_B = 303 K, T_R = 300 K, R_BR = 0.5 K/W: q_BR = 3 / 0.5 = 6 W (design 4.3), relative error <= 1e-12",
        f"q_BR = {float(q[BR])!r} W, relative error {error:.3e}",
        error <= REL_TOL,
    )
    CTX["numbers"]["q_base_W"] = q.tolist()
    CTX["numbers"]["q_BR_example_W"] = float(q[BR])
    CTX["flags"]["q_BR_example"] = example_ok
    case_record.metric("q_W_base_W", dict(zip(DESIGN_PATHS, q.tolist(), strict=True)))
    case_record.metric("q_BR_battery_example_W", float(q[BR]))
    _done()
    assert not check.failed, check.failed


# --------------------------------------------------------------------------- step 2


def test_step2_reversed_end_temperatures(case_record: Any, params: ThermalParameters) -> None:
    check = _Checks(case_record)
    q_base = _flows(params, BASE_T)

    reversed_state = HAND["states"]["battery_reversed"]
    q_rev = _flows(params, reversed_state["temperature_K"])
    errors = _compare_hand("battery reversed", q_rev, "battery_reversed")
    check(
        "步骤2 电池算例对调两端温度后五条连接热流与手算一致",
        "T_B = 300 K, T_R = 303 K: q_W = [-41.25, 300, 125, -6, 6] W from the hand table, relative error <= 1e-12",
        f"q_W = {_fmt(q_rev)} W, max relative error {max(errors):.3e}",
        max(errors) <= REL_TOL,
    )
    error = REF.relative_error(q_rev[BR], Fraction(INPUTS["battery_example"]["q_BR_reversed_W"]))
    magnitude = _rel_diff(abs(q_rev[BR]), abs(q_base[BR]))
    flipped = bool(np.sign(q_rev[BR]) == -np.sign(q_base[BR]) and np.sign(q_base[BR]) != 0)
    rev_ok = check(
        "步骤2 电池算例对调两端温度后 q_BR 为 −6 W",
        "q_BR = (300 - 303) / 0.5 = -6 W: sign opposite to the 6 W of the example, same magnitude, relative error <= 1e-12",
        f"q_BR = {float(q_rev[BR])!r} W against {float(q_base[BR])!r} W before the exchange; relative error {error:.3e}; "
        f"relative magnitude difference {magnitude:.3e}",
        error <= REL_TOL and flipped and magnitude <= REL_TOL,
    )
    CTX["numbers"]["q_BR_reversed_W"] = float(q_rev[BR])
    CTX["flags"]["q_BR_reversed"] = rev_ok
    case_record.metric("q_BR_reversed_W", float(q_rev[BR]))

    swap_rows = {}
    flip_ok = {}
    for index, path in enumerate(DESIGN_PATHS):
        first, second = REF.ends(path)
        temperatures = dict(BASE_T)
        temperatures[first], temperatures[second] = BASE_T[second], BASE_T[first]
        q_swap = _flows(params, temperatures)
        errors = _compare(f"swap {path}", q_swap, temperatures, R_EXACT)
        magnitude = _rel_diff(abs(q_swap[index]), abs(q_base[index]))
        flipped = bool(np.sign(q_swap[index]) == -np.sign(q_base[index]) and np.sign(q_base[index]) != 0)
        flip_ok[path] = flipped and magnitude <= REL_TOL
        swap_rows[path] = {"before_W": float(q_base[index]), "after_W": float(q_swap[index])}
        check(
            f"步骤2 {path} 对调两端温度后热流变号且大小不变",
            f"T_{first} = {BASE_T[first]} K and T_{second} = {BASE_T[second]} K exchanged: q_{path} changes sign and keeps "
            "its magnitude; all five flows equal exact T2 within 1e-12",
            f"q_{path} {float(q_base[index])!r} W -> {float(q_swap[index])!r} W, relative magnitude difference {magnitude:.3e}; "
            f"max relative error of the five flows {max(errors):.3e}",
            flip_ok[path] and max(errors) <= REL_TOL,
        )
    CTX["numbers"]["swap_flip"] = flip_ok
    case_record.metric("q_W_end_temperatures_exchanged_W", swap_rows)
    _done()
    assert not check.failed, check.failed


# --------------------------------------------------------------------------- input 2, equal end temperatures


def test_input2_equal_end_temperatures(case_record: Any, params: ThermalParameters) -> None:
    check = _Checks(case_record)
    equal_values = {}
    battery_checks = []
    battery_zero = []
    for key, level in (("battery_equal_300", 300), ("battery_equal_303", 303)):
        state = HAND["states"][key]
        q = _flows(params, state["temperature_K"])
        errors = _compare_hand(f"battery equal {level} K", q, key)
        equal_values[level] = float(q[BR])
        battery_zero.append(bool(q[BR] == 0.0))
        battery_checks.append(
            check(
                f"输入2 电池算例两端温度均为 {level} K 时 q_BR 为零",
                "q_BR = 0 W exactly; the other four flows equal the hand table within 1e-12",
                f"q_W = {_fmt(q)} W, q_BR = {float(q[BR])!r} W, max relative error {max(errors):.3e}",
                q[BR] == 0.0 and max(errors) <= REL_TOL,
            )
        )
    CTX["numbers"]["q_BR_equal_W"] = equal_values
    # Expected result 1 uses the two checks above as a whole; the summary speaks only of the q_BR values.
    CTX["flags"]["q_BR_equal"] = all(battery_checks)
    CTX["flags"]["q_BR_equal_zero"] = all(battery_zero)
    case_record.metric("q_BR_equal_end_temperatures_W", {f"{level} K": value for level, value in equal_values.items()})

    path_values = {}
    for index, path in enumerate(DESIGN_PATHS):
        first, second = REF.ends(path)
        temperatures = dict(BASE_T)
        temperatures[first] = BASE_T[second]
        q = _flows(params, temperatures)
        errors = _compare(f"equal {path}", q, temperatures, R_EXACT)
        path_values[path] = float(q[index])
        check(
            f"输入2 {path} 两端温度相等时热流为零",
            f"T_{first} = T_{second} = {BASE_T[second]} K: q_{path} = 0 W exactly; the other flows equal exact T2 within 1e-12",
            f"q_W = {_fmt(q)} W, max relative error {max(errors):.3e}",
            q[index] == 0.0 and max(errors) <= REL_TOL,
        )
    CTX["numbers"]["equal_each_W"] = path_values
    case_record.metric("q_W_equal_end_temperatures_per_path_W", path_values)

    level = float(INPUTS["all_equal_temperature_K"])
    temperatures = {node: level for node in DESIGN_NODES}
    q = _flows(params, temperatures)
    _compare("all equal", q, temperatures, R_EXACT)
    check(
        f"输入2 六个节点温度均为 {_num_cn(level)} K 时五条连接热流全为零",
        "q_W = [0, 0, 0, 0, 0] W exactly",
        f"q_W = {_fmt(q)} W",
        all(value == 0.0 for value in q),
    )
    CTX["numbers"]["equal_all"] = {"level_K": level, "q_W": [float(value) for value in q]}
    _done()
    assert not check.failed, check.failed


# --------------------------------------------------------------------------- step 3


def test_step3_positive_from_first_to_second(case_record: Any, params: ThermalParameters) -> None:
    check = _Checks(case_record)
    expected_ends = {path: REF.ends(path) for path in DESIGN_PATHS}
    module_ends = {path: tuple(thermal.types.PATH_NODES.get(path, ())) for path in DESIGN_PATHS}
    CTX["flags"]["path_nodes"] = check(
        "步骤3 每条路径的第一个与第二个节点取自路径名称",
        f"first and second node of each path from its name: {expected_ends}",
        f"PATH_NODES = {module_ends}",
        module_ends == expected_ends,
    )
    offset = float(INPUTS["sign_offset_K"])
    rows = {}
    for index, path in enumerate(DESIGN_PATHS):
        first, second = REF.ends(path)
        hot = dict(BASE_T)
        hot[first] = BASE_T[second] + offset
        cold = dict(BASE_T)
        cold[first] = BASE_T[second] - offset
        q_hot = _flows(params, hot)
        q_cold = _flows(params, cold)
        errors = _compare(f"first hotter {path}", q_hot, hot, R_EXACT) + _compare(f"first colder {path}", q_cold, cold, R_EXACT)
        magnitude = float(Fraction(offset) / R_EXACT[path])
        rows[path] = {"first_hotter_W": float(q_hot[index]), "first_colder_W": float(q_cold[index])}
        check(
            f"步骤3 {path} 第一个节点较热时热流为正 较冷时热流为负",
            f"T_{first} = T_{second} + {offset} K: q_{path} = +{magnitude:.6g} W > 0, heat flows from {first} to {second}; "
            f"T_{first} = T_{second} - {offset} K: q_{path} = -{magnitude:.6g} W < 0; flows equal exact T2 within 1e-12",
            f"q_{path} = {float(q_hot[index])!r} W and {float(q_cold[index])!r} W; max relative error of the ten flows "
            f"{max(errors):.3e}",
            q_hot[index] > 0.0 and q_cold[index] < 0.0 and max(errors) <= REL_TOL,
        )
    case_record.metric("q_W_sign_convention_W", rows)
    CTX["numbers"]["sign_W"] = rows
    _done()
    assert not check.failed, check.failed


# --------------------------------------------------------------------------- expected result 2


def test_expect2_single_evaluation_and_no_state_update(
    case_record: Any, params: ThermalParameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = _Checks(case_record)
    state = _state(BASE_T)
    q_plain = np.array(calculate_heat_flows(state, params)["q_W"], dtype=float)

    # Each path evaluated once, end temperatures and resistances read in the fixed order: log every element read of
    # R_K_W and of the temperatures during one call, separately and merged in the order the reads happen.
    hooks = all(hasattr(thermal_model, name) for name in ("_resolve_parameters", "_state_fields"))
    reads: dict[str, Any] = {"measured": hooks}
    unmeasured = "thermal.model has no _resolve_parameters or _state_fields hook, so the reads could not be logged"
    if hooks:
        merged: list[tuple[str, int]] = []
        r_log = _TaggedLog("R", merged)
        t_log = _TaggedLog("T", merged)
        resolve = thermal_model._resolve_parameters
        state_fields = thermal_model._state_fields

        def counting_resolve(parameters: Any) -> Any:
            resolved = resolve(parameters)
            return resolved._replace(R_K_W=REF.ReadCounter(resolved.R_K_W, r_log))

        def counting_state_fields(record: Any, where: str) -> Any:
            run_id, time_s, temperature = state_fields(record, where)
            return run_id, time_s, REF.ReadCounter(temperature, t_log)

        with monkeypatch.context() as patch:
            patch.setattr(thermal_model, "_resolve_parameters", counting_resolve)
            patch.setattr(thermal_model, "_state_fields", counting_state_fields)
            counted = calculate_heat_flows(state, params)
        q_counted = np.array(counted["q_W"], dtype=float)
        r_counts = Counter(r_log)
        t_counts = Counter(t_log)
        evaluations = {path: r_counts.get(index, 0) for index, path in enumerate(DESIGN_PATHS)}
        node_reads = {node: t_counts.get(index, 0) for index, node in enumerate(DESIGN_NODES)}
        expected_reads = REF.degree()
        same = _same_bits(q_counted, q_plain)
        counts_ok = all(count == 1 for count in evaluations.values()) and len(r_log) == 5 and node_reads == expected_reads
        once = check(
            "预期2 一次调用中每条路径只求值一次",
            f"R_ij read once per path {dict.fromkeys(DESIGN_PATHS, 1)}; end temperatures read once per path, so node "
            f"reads equal the number of paths at the node {expected_reads}; instrumented q_W bitwise identical to the "
            "plain call",
            f"R_K_W reads per path {evaluations} ({len(r_log)} in all); temperature reads per node {node_reads}; "
            f"instrumented q_W {_fmt(q_counted)} W, bitwise identical {same}",
            counts_ok and same,
        )
        # Design 5.5: the end temperatures and resistances are read in the fixed order SR, JC, CR, BR, DR.
        r_sequence = [_label(DESIGN_PATHS, index) for index in r_log]
        r_first = list(dict.fromkeys(r_sequence))
        r_ok = check(
            "步骤1 热阻按 SR、JC、CR、BR、DR 的固定顺序读取",
            f"order of the first R_K_W read of each path during one call = {list(DESIGN_PATHS)} (repeated reads are "
            "the count check above)",
            f"order of first reads = {r_first}; full read sequence = {r_sequence}",
            r_first == list(DESIGN_PATHS),
        )
        t_sequence = [_label(DESIGN_NODES, index) for index in t_log]
        t_ok = check(
            "步骤1 两端温度按 SR、JC、CR、BR、DR 的固定顺序读取",
            "end temperatures read path by path in the order SR, JC, CR, BR, DR, first node then second node as in "
            f"T2 q_ij = (T_i - T_j) / R_ij: {EXPECTED_T_SEQUENCE}",
            f"temperature read sequence = {t_sequence}",
            t_sequence == EXPECTED_T_SEQUENCE,
        )
        merged_labels = [
            f"T_{_label(DESIGN_NODES, index)}" if tag == "T" else f"R_{_label(DESIGN_PATHS, index)}" for tag, index in merged
        ]
        expected_groups = [
            sorted([("T", DESIGN_NODES.index(REF.ends(path)[0])), ("T", DESIGN_NODES.index(REF.ends(path)[1])), ("R", k)])
            for k, path in enumerate(DESIGN_PATHS)
        ]
        groups = [sorted(merged[3 * k: 3 * k + 3]) for k in range(len(DESIGN_PATHS))]
        grouped = len(merged) == 3 * len(DESIGN_PATHS) and groups == expected_groups
        g_ok = check(
            "步骤1 按 SR、JC、CR、BR、DR 的固定顺序逐条执行 T2",
            "the reads of each path, its two end temperatures and its resistance, are complete before any read of the "
            "next path, in the order SR, JC, CR, BR, DR (15 reads in all)",
            f"merged read sequence = {merged_labels}",
            grouped,
        )
        reads.update(
            r_counts=evaluations,
            node_reads=node_reads,
            r_total=len(r_log),
            counts_ok=counts_ok,
            same=same,
            r_first=r_first,
            t_sequence=t_sequence,
            merged=merged_labels,
            once=once,
            r_order=r_ok,
            t_order=t_ok,
            grouped=g_ok,
        )
        case_record.metric("evaluations_per_path_in_one_call", evaluations)
        case_record.metric("temperature_reads_per_node_in_one_call", node_reads)
        case_record.metric("resistance_read_sequence_in_one_call", r_sequence)
        case_record.metric("temperature_read_sequence_in_one_call", t_sequence)
        case_record.metric("merged_read_sequence_in_one_call", merged_labels)
    else:
        for name, expected in (
            ("预期2 一次调用中每条路径只求值一次", "per-path evaluation count measured by instrumentation"),
            ("步骤1 热阻按 SR、JC、CR、BR、DR 的固定顺序读取", "resistance read sequence measured by instrumentation"),
            ("步骤1 两端温度按 SR、JC、CR、BR、DR 的固定顺序读取", "temperature read sequence measured by instrumentation"),
            ("步骤1 按 SR、JC、CR、BR、DR 的固定顺序逐条执行 T2", "merged read sequence measured by instrumentation"),
        ):
            check(name, expected, unmeasured, False)
    CTX["numbers"]["reads"] = reads

    # Each flow depends only on its own two end temperatures: a 1 K change at one node changes only its paths.
    delta = float(INPUTS["perturbation_K"])
    locality = {}
    for node in DESIGN_NODES:
        temperatures = dict(BASE_T)
        temperatures[node] = BASE_T[node] + delta
        q = _flows(params, temperatures)
        errors = _compare(f"perturb {node}", q, temperatures, R_EXACT)
        touched = [path for path in DESIGN_PATHS if node in REF.ends(path)]
        changed = [path for index, path in enumerate(DESIGN_PATHS) if _bits(q[index]) != _bits(q_plain[index])]
        locality[node] = changed == touched
        check(
            f"预期2 节点 {node} 温度升高 1 K 只改变与其相连路径的热流",
            f"changed paths {touched}; other flows bitwise unchanged; all flows equal exact T2 within 1e-12",
            f"changed paths {changed}; q_W = {_fmt(q)} W; max relative error {max(errors):.3e}",
            locality[node] and max(errors) <= REL_TOL,
        )
    CTX["numbers"]["locality"] = locality

    # thermal_derivative uses one evaluation of the flows for both end equations.
    calls: list[dict[str, Any]] = []
    original = thermal_model.calculate_heat_flows

    def spy(record: Any, parameters: Any) -> dict[str, Any]:
        out = original(record, parameters)
        calls.append(out)
        return out

    surface_ids = tuple(item["surface_id"] for component in INPUTS["components"] for item in component.get("surfaces", []))
    zeros = np.zeros(len(surface_ids))
    environment = {
        "run_id": RUN_ID,
        "time_s": TIME_S,
        "surface_ids": surface_ids,
        "G_W_m2": 0.0,
        "cos_incidence": zeros,
        "albedo_W_m2": zeros,
        "infrared_W_m2": zeros,
    }
    ports = INPUTS["derivative_ports_W"]
    inputs = ThermalInputs(
        run_id=RUN_ID,
        time_s=TIME_S,
        environment=environment,
        P_pv_W=ports["P_pv_W"],
        P_load_W=ports["P_load_W"],
        Q_B_W=ports["Q_B_W"],
        Q_D_W=ports["Q_D_W"],
    )
    derivative: dict[str, Any] = {"calls": None, "same": False, "error": None}
    try:
        with monkeypatch.context() as patch:
            patch.setattr(thermal_model, "calculate_heat_flows", spy)
            evaluation = thermal_derivative(state, inputs, params)
        q_eval = np.array(evaluation.q_W, dtype=float)
        same = len(calls) == 1 and _same_bits(q_eval, np.asarray(calls[0]["q_W"], dtype=float))
        derivative.update(calls=len(calls), same=same)
        actual = (
            f"calculate_heat_flows called {len(calls)} time(s); ThermalEvaluation.q_W {_fmt(q_eval)} W, bitwise "
            f"identical to the single call {bool(same)}"
        )
    except Exception as exc:  # noqa: BLE001
        same = False
        derivative.update(calls=len(calls), error=type(exc).__name__)
        actual = f"thermal_derivative raised {type(exc).__name__}: {exc}; calculate_heat_flows called {len(calls)} time(s)"
    check(
        "预期2 thermal_derivative 一次求值只调用一次 calculate_heat_flows 并沿用其热流",
        "one call of calculate_heat_flows per thermal_derivative evaluation; ThermalEvaluation.q_W equals that single "
        "result, so the same value serves the outflow and inflow ends",
        actual,
        same,
    )
    CTX["numbers"]["derivative"] = derivative
    case_record.metric("calculate_heat_flows_calls_per_thermal_derivative", derivative["calls"])

    # No state update: inputs bitwise unchanged, nothing new returned besides the flows.
    no_state: dict[str, bool] = {}
    temperature_before = np.array(state.temperature_K, copy=True)
    writeable_before = bool(state.temperature_K.flags.writeable)
    r_before = np.array(params.R_K_W, copy=True)
    c_before = np.array(params.C_J_K, copy=True)
    provenance_before = params.provenance_as_dict()
    first = calculate_heat_flows(state, params)
    second = calculate_heat_flows(state, params)
    no_state["state"] = check(
        "预期2 函数没有状态更新 状态对象调用前后逐位相同",
        "ThermalState run_id, time_s, temperature_K and its read-only flag unchanged by the call",
        f"run_id {state.run_id!r}, time_s {state.time_s!r}, temperature_K {_fmt(state.temperature_K)} K, "
        f"bitwise equal {_same_bits(state.temperature_K, temperature_before)}, writeable "
        f"{state.temperature_K.flags.writeable} before {writeable_before}",
        state.run_id == RUN_ID
        and state.time_s == TIME_S
        and _same_bits(state.temperature_K, temperature_before)
        and bool(state.temperature_K.flags.writeable) == writeable_before,
    )
    caller_array = _array(BASE_T)
    caller_copy = caller_array.copy()
    duck_result = calculate_heat_flows(_duck_state(caller_array), params)
    no_state["caller"] = check(
        "预期2 函数没有状态更新 调用方可写温度数组未被修改",
        "a caller-owned writeable temperature array keeps its values and stays writeable",
        f"values bitwise equal {_same_bits(caller_array, caller_copy)}, writeable {bool(caller_array.flags.writeable)}, "
        f"shares memory with q_W {bool(np.shares_memory(caller_array, duck_result['q_W']))}",
        _same_bits(caller_array, caller_copy)
        and bool(caller_array.flags.writeable)
        and not np.shares_memory(caller_array, duck_result["q_W"]),
    )
    no_state["params"] = check(
        "预期2 函数没有状态更新 参数对象调用前后相同",
        "R_K_W, C_J_K and provenance of ThermalParameters unchanged by the calls",
        f"R_K_W bitwise equal {_same_bits(params.R_K_W, r_before)}, C_J_K bitwise equal "
        f"{_same_bits(params.C_J_K, c_before)}, provenance equal {params.provenance_as_dict() == provenance_before}",
        _same_bits(params.R_K_W, r_before)
        and _same_bits(params.C_J_K, c_before)
        and params.provenance_as_dict() == provenance_before,
    )
    no_new_state = not any(isinstance(value, ThermalState) for value in first.values()) and "temperature_K" not in first
    shares = bool(np.shares_memory(first["q_W"], state.temperature_K) or np.shares_memory(first["q_W"], params.R_K_W))
    no_state["result"] = check(
        "预期2 函数没有状态更新 返回结果只含热流且不与输入共享内存",
        "result holds run_id, time_s equal to the input and q_W; no ThermalState or temperature field; q_W shares no "
        "memory with the state or the resistances",
        f"keys {sorted(first)}, run_id {first.get('run_id')!r}, time_s {first.get('time_s')!r}, ThermalState or "
        f"temperature present {not no_new_state}, q_W shares memory with inputs {shares}",
        no_new_state and first.get("run_id") == RUN_ID and first.get("time_s") == TIME_S and not shares,
    )
    no_state["repeat"] = check(
        "预期2 重复调用结果逐位相同",
        "two calls on the same state and parameters return bitwise identical q_W",
        f"{_fmt(first['q_W'])} W and {_fmt(second['q_W'])} W",
        _same_bits(first["q_W"], second["q_W"]),
    )
    CTX["numbers"]["no_state"] = no_state
    _done()
    assert not check.failed, check.failed


# --------------------------------------------------------------------------- step 4


def test_step4_abnormal_inputs(case_record: Any, params: ThermalParameters) -> None:
    check = _Checks(case_record)
    state = _state(BASE_T)
    base_array = _array(BASE_T)
    q_reference = np.array(calculate_heat_flows(state, params)["q_W"], dtype=float)

    # Controls: the same objects without the injected fault are accepted and give the same flows, so each rejection
    # below comes from the injected fault (for 数组次序不符, from the changed node_order or path_order declaration).
    controls = {
        "state object without constructor checks": lambda: calculate_heat_flows(_duck_state(base_array.copy()), params),
        "parameter object without constructor checks": lambda: calculate_heat_flows(state, _duck_params(params)),
        "parameters rebuilt through ThermalParameters": lambda: calculate_heat_flows(state, _rebuilt_params(params)),
    }
    control_results = {}
    for label, call in controls.items():
        try:
            control_results[label] = _same_bits(np.asarray(call()["q_W"], dtype=float), q_reference)
        except Exception as exc:  # noqa: BLE001
            control_results[label] = f"{type(exc).__name__}: {exc}"
    CTX["flags"]["controls"] = check(
        "步骤4 对照 未注入异常的同类输入正常返回相同热流",
        "each control returns q_W bitwise identical to the base call, so each rejection below comes from the injected fault",
        f"{control_results}",
        all(value is True for value in control_results.values()),
    )

    def r_k_w(index: int, value: float, size: int = 5) -> np.ndarray:
        return _r_with(index, value, size)

    t_nan_b = base_array.copy()
    t_nan_b[3] = np.nan
    t_inf_r = base_array.copy()
    t_inf_r[5] = np.inf
    t_ninf_s = base_array.copy()
    t_ninf_s[0] = -np.inf
    missing_d = np.delete(base_array, 4)
    nodes_without_d = {
        "nodes": {node: ids for node, ids in params.instance_map["nodes"].items() if node != "D"},
        "ports": dict(params.instance_map["ports"]),
    }
    keyed_wrong = {node: BASE_T[node] for node in ("R", "S", "J", "C", "B", "D")}
    keyed_design = {node: BASE_T[node] for node in DESIGN_NODES}

    def replaced_after_assembly() -> Any:
        fresh = assemble_thermal_parameters(INPUTS["components"], INPUTS["connections"], None)
        object.__setattr__(fresh, "R_K_W", r_k_w(BR, 0.0))
        return calculate_heat_flows(state, fresh)

    def assemble_br(replacement: dict[str, Any]) -> Any:
        return assemble_thermal_parameters(INPUTS["components"], _connections_with("BR", replacement), None)

    def declared(**provenance: Any) -> SimpleNamespace:
        return _duck_params(params, provenance=provenance)

    source = "HT-001 abnormal input"
    prefix = "步骤4 异常输入"
    cases = [
        # 缺少节点
        ("缺少节点", "状态温度数组缺少节点 D 只有五个值",
         lambda: calculate_heat_flows(_duck_state(missing_d.copy()), params), ThermalInputError,
         ["state.temperature_K"], None),
        ("缺少节点", "ThermalState 构造时温度数组只有五个值",
         lambda: ThermalState(RUN_ID, TIME_S, missing_d.copy()), ThermalInputError,
         ["ThermalState.temperature_K"], None),
        ("缺少节点", "状态对象缺少温度字段",
         lambda: calculate_heat_flows(_duck_state(drop_temperature=True), params), ThermalInputError,
         ["temperature_K"], None),
        ("缺少节点", "参数节点次序缺少节点 D",
         lambda: calculate_heat_flows(state, declared(node_order=("S", "J", "C", "B", "R"))),
         ThermalConfigurationError, ["node_order"], None),
        ("缺少节点", "参数实例映射缺少节点 D",
         lambda: calculate_heat_flows(state, _duck_params(params, instance_map=nodes_without_d)),
         ThermalConfigurationError, ["instance_map", "'D'"], None),
        # 数组次序不符: only the node or path order declared by the parameter object differs from the design order
        (ORDER_CATEGORY, "参数节点次序为 R J C B D S",
         lambda: calculate_heat_flows(state, declared(node_order=("R", "J", "C", "B", "D", "S"))),
         ThermalConfigurationError, ["node_order"], "declared_order"),
        (ORDER_CATEGORY, "参数节点次序为 S J C B R D",
         lambda: calculate_heat_flows(state, declared(node_order=("S", "J", "C", "B", "R", "D"))),
         ThermalConfigurationError, ["node_order"], "declared_order"),
        (ORDER_CATEGORY, "参数路径次序为 BR JC CR SR DR",
         lambda: calculate_heat_flows(state, declared(path_order=("BR", "JC", "CR", "SR", "DR"))),
         ThermalConfigurationError, ["path_order"], "declared_order"),
        (ORDER_CATEGORY, "参数路径次序为 SR JC CR DR BR",
         lambda: calculate_heat_flows(state, declared(path_order=("SR", "JC", "CR", "DR", "BR"))),
         ThermalConfigurationError, ["path_order"], "declared_order"),
        (ORDER_CATEGORY, "ThermalParameters 构造时节点次序为 R J C B D S",
         lambda: _rebuilt_params(params, provenance={"node_order": ("R", "J", "C", "B", "D", "S")}),
         ThermalConfigurationError, ["ThermalParameters.provenance", "node_order"], "declared_order"),
        (ORDER_CATEGORY, "ThermalParameters 构造时路径次序为 BR JC CR SR DR",
         lambda: _rebuilt_params(params, provenance={"path_order": ("BR", "JC", "CR", "SR", "DR")}),
         ThermalConfigurationError, ["ThermalParameters.provenance", "path_order"], "declared_order"),
        # 数组形状或类型不符: rejected for the form of the array; a keyed mapping is rejected whatever its key order
        (FORM_CATEGORY, "状态温度为以节点名为键的映射 键序为 R S J C B D",
         lambda: calculate_heat_flows(_duck_state(dict(keyed_wrong)), params), ThermalInputError,
         ["state.temperature_K"], "keyed_state"),
        (FORM_CATEGORY, "状态温度为以节点名为键的映射 键序为 S J C B D R",
         lambda: calculate_heat_flows(_duck_state(dict(keyed_design)), params), ThermalInputError,
         ["state.temperature_K"], "keyed_state"),
        (FORM_CATEGORY, "状态温度为一行六列的二维数组",
         lambda: calculate_heat_flows(_duck_state(base_array.reshape(1, 6).copy()), params), ThermalInputError,
         ["state.temperature_K"], None),
        (FORM_CATEGORY, "参数热阻数组按节点给出六个值",
         lambda: calculate_heat_flows(state, _duck_params(params, R_K_W=r_k_w(5, 1.0, 6))), ThermalConfigurationError,
         ["R_K_W"], None),
        # 热阻为零或负值
        ("热阻为零或负值", "参数 R_BR 为零",
         lambda: calculate_heat_flows(state, _duck_params(params, R_K_W=r_k_w(BR, 0.0))), ThermalConfigurationError,
         ["R_K_W", "BR"], None),
        ("热阻为零或负值", "参数 R_BR 为负零",
         lambda: calculate_heat_flows(state, _duck_params(params, R_K_W=r_k_w(BR, -0.0))), ThermalConfigurationError,
         ["R_K_W", "BR"], None),
        ("热阻为零或负值", "参数 R_BR 为 −0.5 K/W",
         lambda: calculate_heat_flows(state, _duck_params(params, R_K_W=r_k_w(BR, -0.5))), ThermalConfigurationError,
         ["R_K_W", "BR"], None),
        ("热阻为零或负值", "ThermalParameters 构造时 R_BR 为零",
         lambda: _rebuilt_params(params, R_K_W=r_k_w(BR, 0.0)), ThermalConfigurationError,
         ["ThermalParameters.R_K_W", "BR"], None),
        ("热阻为零或负值", "ThermalParameters 构造时 R_BR 为 −0.5 K/W",
         lambda: _rebuilt_params(params, R_K_W=r_k_w(BR, -0.5)), ThermalConfigurationError,
         ["ThermalParameters.R_K_W", "BR"], None),
        ("热阻为零或负值", "装配完成后改写 R_K_W 字段使 R_BR 为零",
         replaced_after_assembly, ThermalConfigurationError, ["R_K_W", "BR"], None),
        ("热阻为零或负值", "装配时 BR 等效总热阻为零",
         lambda: assemble_br({"equivalent_total_resistance_K_W": 0.0, "includes_contact": True, "source": source}),
         ThermalConfigurationError, ["connection 'BR'", "equivalent_total_resistance_K_W"], None),
        ("热阻为零或负值", "装配时 BR 等效总热阻为 −0.5 K/W",
         lambda: assemble_br({"equivalent_total_resistance_K_W": -0.5, "includes_contact": True, "source": source}),
         ThermalConfigurationError, ["connection 'BR'", "equivalent_total_resistance_K_W"], None),
        ("热阻为零或负值", "装配时 BR 实心路径长度为零且接触热阻为零",
         lambda: assemble_br({"length_m": 0.0, "conductivity_W_mK": 200.0, "area_m2": 0.0025,
                              "contact_resistance_K_W": 0.0, "source": source}),
         ThermalConfigurationError, ["connection 'BR'", "length_m"], None),
        ("热阻为零或负值", "装配时 BR 接触热阻为负使总热阻为负",
         lambda: assemble_br({"length_m": 0.125, "conductivity_W_mK": 200.0, "area_m2": 0.0025,
                              "contact_resistance_K_W": -0.3, "source": source}),
         ThermalConfigurationError, ["connection 'BR'", "contact_resistance_K_W"], None),
        # 输入为非有限值
        ("输入为非有限值", "状态 T_B 为 NaN",
         lambda: calculate_heat_flows(_duck_state(t_nan_b.copy()), params), ThermalInputError,
         ["state.temperature_K", "index 3"], None),
        ("输入为非有限值", "状态 T_R 为正无穷",
         lambda: calculate_heat_flows(_duck_state(t_inf_r.copy()), params), ThermalInputError,
         ["state.temperature_K", "index 5"], None),
        ("输入为非有限值", "状态 T_S 为负无穷",
         lambda: calculate_heat_flows(_duck_state(t_ninf_s.copy()), params), ThermalInputError,
         ["state.temperature_K", "index 0"], None),
        ("输入为非有限值", "状态 time_s 为 NaN",
         lambda: calculate_heat_flows(_duck_state(base_array.copy(), time_s=float("nan")), params), ThermalInputError,
         ["state.time_s"], None),
        ("输入为非有限值", "状态 time_s 为正无穷",
         lambda: calculate_heat_flows(_duck_state(base_array.copy(), time_s=float("inf")), params), ThermalInputError,
         ["state.time_s"], None),
        ("输入为非有限值", "参数 R_BR 为 NaN",
         lambda: calculate_heat_flows(state, _duck_params(params, R_K_W=r_k_w(BR, np.nan))), ThermalConfigurationError,
         ["R_K_W", "index 3"], None),
        ("输入为非有限值", "参数 R_BR 为正无穷",
         lambda: calculate_heat_flows(state, _duck_params(params, R_K_W=r_k_w(BR, np.inf))), ThermalConfigurationError,
         ["R_K_W", "index 3"], None),
        ("输入为非有限值", "ThermalState 构造时 T_B 为 NaN",
         lambda: ThermalState(RUN_ID, TIME_S, t_nan_b.copy()), ThermalInputError,
         ["ThermalState.temperature_K", "index 3"], None),
        ("输入为非有限值", "ThermalParameters 构造时 R_BR 为正无穷",
         lambda: _rebuilt_params(params, R_K_W=r_k_w(BR, np.inf)), ThermalConfigurationError,
         ["ThermalParameters.R_K_W", "index 3"], None),
    ]
    by_category: dict[str, list[bool]] = {}
    for category, label, call, expected_class, tokens, tag in cases:
        passed = _inject(check, prefix, category, label, call, expected_class, tokens, tag)
        by_category.setdefault(category, []).append(passed)
    case_record.metric(
        "abnormal_inputs_step4",
        {category: f"{sum(flags)}/{len(flags)} rejected as required" for category, flags in by_category.items()},
    )
    case_record.metric(
        "abnormal_inputs_array_order_basis",
        "The 数组次序不符 injections change only the node_order or path_order that the parameter object declares in its "
        "provenance; the controls with the declared orders unchanged are accepted, so these rejections come from the "
        "declared order. The state temperature array has no order field (ThermalState, design table 6): it is read in "
        "the order S, J, C, B, D, R, and a permutation of its six values cannot be told from other temperatures. A "
        "mapping keyed by node name is rejected for its type whatever its key order; it is recorded, with the 1 x 6 "
        "array and the six-value R_K_W, under 数组形状或类型不符.",
    )
    _done()
    assert not check.failed, check.failed


# --------------------------------------------------------------------------- expected result 3


def test_expect3_no_zero_resistance_or_clipping(case_record: Any, params: ThermalParameters) -> None:
    check = _Checks(case_record)
    state = _state(BASE_T)
    prefix = "预期3"
    _inject(
        check, prefix, "连接未装配", "装配时缺少 DR 连接",
        lambda: assemble_thermal_parameters(INPUTS["components"], _connections_with("DR", None), None),
        ThermalConfigurationError, ["['DR']"],
    )
    _inject(
        check, prefix, "连接未装配", "参数热阻数组缺少 DR 只有四个值",
        lambda: calculate_heat_flows(state, _duck_params(params, R_K_W=_r_with(0, float(R_EXACT["SR"]), 4))),
        ThermalConfigurationError, ["R_K_W"],
    )

    # Valid extreme inputs: the overrides must reach R_K_W through T5, and the flows must be the exact T2 values.
    extreme = INPUTS["extreme_valid"]
    overrides = extreme["overrides"]
    p_extreme = assemble_thermal_parameters(INPUTS["components"], INPUTS["connections"], overrides)
    connections = []
    for item in INPUTS["connections"]:
        record = dict(item)
        record.update(overrides["connections"].get(item["path"], {}))
        connections.append(record)
    r_extreme = {item["path"]: REF.t5_resistance(item) for item in connections}
    r_module = [float(value) for value in np.asarray(p_extreme.R_K_W, dtype=float).ravel()]
    r_complete = len(r_module) == len(DESIGN_PATHS)
    r_errors = {
        path: (REF.relative_error(r_module[index], r_extreme[path]) if r_complete else math.inf)
        for index, path in enumerate(DESIGN_PATHS)
    }
    r_ok = check(
        "预期3 有效极端输入的热阻按覆盖值与式 T5 装配",
        f"overrides {overrides['connections']} applied: R_K_W = {[float(r_extreme[p]) for p in DESIGN_PATHS]} K/W from "
        "T5 of the overridden connections, relative error <= 1e-12",
        f"R_K_W = {_fmt(r_module)} K/W; relative errors {{{', '.join(f'{p}: {e:.3e}' for p, e in r_errors.items())}}}",
        r_complete and max(r_errors.values()) <= REL_TOL,
    )

    temperatures = dict(extreme["temperature_K"])
    temperatures["B"] = float(temperatures["B"]) + float(extreme["B_offset_K"])
    q = np.array(calculate_heat_flows(_state(temperatures), p_extreme)["q_W"], dtype=float)
    errors = _compare("extreme valid", q, temperatures, r_extreme)
    reference = REF.t2_flows(temperatures, r_extreme)
    special = ("CR", "BR", "DR")
    zeroed = [path for path in special if q[DESIGN_PATHS.index(path)] == 0.0]
    formulas = "; ".join(
        f"q_{path} = ({REF.exact(temperatures[REF.ends(path)[0]]) - REF.exact(temperatures[REF.ends(path)[1]])}) / "
        f"{float(r_extreme[path])!r} = {float(reference[path])!r} W"
        for path in special
    )
    no_clip = check(
        "预期3 有效极端输入下热流按式 T2 计算 不截断",
        f"T2 with the T5 resistances of the overridden connections: {formulas}; every flow equal to exact T2 within "
        "1e-12, none set to zero or capped",
        f"R_K_W = {_fmt(r_module)} K/W; q_W = {_fmt(q)} W; references {[float(reference[p]) for p in DESIGN_PATHS]} W; "
        f"relative errors {[f'{error:.3e}' for error in errors]}; zero flows among {list(special)}: {zeroed}",
        max(errors) <= REL_TOL and not zeroed,
    )
    dT_BR = REF.exact(temperatures["B"]) - REF.exact(temperatures["R"])
    CTX["numbers"]["extreme"] = {
        "overridden_paths": [path for path in DESIGN_PATHS if path in overrides["connections"]],
        "R_K_W": dict(zip(DESIGN_PATHS, r_module, strict=False)),
        "R_T5_K_W": {path: float(r_extreme[path]) for path in DESIGN_PATHS},
        "R_relative_error": r_errors,
        "q_W": dict(zip(DESIGN_PATHS, (float(value) for value in q), strict=True)),
        "reference_W": {path: float(reference[path]) for path in DESIGN_PATHS},
        "relative_error": dict(zip(DESIGN_PATHS, errors, strict=True)),
        "zeroed": zeroed,
        "dT_BR_K": float(dT_BR),
    }
    CTX["flags"]["extreme_resistances"] = r_ok
    CTX["flags"]["no_clipping"] = no_clip
    case_record.metric("R_K_W_extreme_valid_K_W", dict(zip(DESIGN_PATHS, r_module, strict=False)))
    case_record.metric("q_W_extreme_valid_W", dict(zip(DESIGN_PATHS, q.tolist(), strict=True)))
    _done()
    assert not check.failed, check.failed


# --------------------------------------------------------------------------- acceptance and summary


def test_acceptance_and_summary(case_record: Any) -> None:
    check = _Checks(case_record)
    numbers = CTX["numbers"]
    flags = CTX["flags"]
    completed = CTX["completed"]

    # Expected result 1: q_BR = 6 W, -6 W reversed, zero at equal temperatures.
    q_ex = numbers.get("q_BR_example_W")
    q_rev = numbers.get("q_BR_reversed_W")
    q_eq = numbers.get("q_BR_equal_W", {})
    expect1 = bool(flags.get("q_BR_example") and flags.get("q_BR_reversed") and flags.get("q_BR_equal"))
    check(
        "预期1 算例热流 q_BR 为 6 W 对调后为 −6 W 等温时为零",
        "q_BR = 6 W, -6 W after exchanging T_B and T_R, 0 W at T_B = T_R = 300 K and 303 K; the step 1, step 2 and "
        "input 2 battery checks passed (the input 2 checks include the other four flows of those states)",
        f"q_BR = {q_ex!r} W, reversed {q_rev!r} W, equal {q_eq} W; checks passed: example {flags.get('q_BR_example')}, "
        f"reversed {flags.get('q_BR_reversed')}, equal temperatures {flags.get('q_BR_equal')}",
        expect1,
    )

    # Expected result 3: every abnormal input raised, no flow returned; extreme valid flows not clipped.
    abnormal = CTX["abnormal"]
    returned = [item["label"] for item in abnormal if not item["raised"]]
    not_injected = [name for name in INJECTING if name not in completed]
    expect3 = (
        bool(abnormal)
        and not returned
        and all(item["passed"] for item in abnormal)
        and bool(flags.get("no_clipping"))
        and bool(flags.get("extreme_resistances"))
        and not not_injected
    )
    check(
        "预期3 异常输入报告错误 不用零热阻或临时截断热流代替实际路径",
        "every abnormal input and unassembled connection raises a definite error and returns no flow; valid extreme "
        "inputs assembled with their overrides give exact T2 flows; both test functions completed",
        f"{sum(item['raised'] for item in abnormal)}/{len(abnormal)} abnormal inputs raised; returned a result: {returned}; "
        f"extreme resistances as T5 {flags.get('extreme_resistances')}; extreme valid flows exact {flags.get('no_clipping')}; "
        f"test functions not completed: {not_injected}",
        expect3,
    )

    # Acceptance 1: relative error against the hand calculation <= 1e-12 (zero references need an exact zero).
    comparisons = CTX["comparisons"]
    nonzero = [item for item in comparisons if not item["zero_reference"]]
    zero = [item for item in comparisons if item["zero_reference"]]
    max_error = max((item["relative_error"] for item in nonzero), default=math.inf)
    zero_exact = all(item["relative_error"] == 0.0 for item in zero)
    worst = max(nonzero, key=lambda item: item["relative_error"]) if nonzero else {}
    not_compared = [name for name in COMPARING if name not in completed]
    accept1 = check(
        "验收判据1 热流与手算的相对误差不超过限值",
        "relative error <= 1e-12 for every compared flow; flows with a zero reference exactly 0 W; every test function "
        "that compares flows completed",
        f"{len(comparisons)} flows compared, {len(nonzero)} with a non-zero reference: max relative error {max_error:.3e} "
        f"at {worst.get('label')} {worst.get('path')}; {len(zero)} zero references, all exactly zero {zero_exact}; "
        f"test functions not completed: {not_compared}",
        bool(comparisons) and max_error <= REL_TOL and zero_exact and not not_compared,
    )

    # Acceptance 2: every abnormal input gives a definite error.
    passed_abnormal = sum(item["passed"] for item in abnormal)
    accept2 = check(
        "验收判据2 全部异常输入给出确定的报错",
        "every injected abnormal input raises the contract error class with a message naming the field, identically "
        "on repetition; every test function that injects abnormal inputs completed",
        f"{passed_abnormal}/{len(abnormal)} abnormal inputs met the requirement; categories "
        f"{sorted({item['category'] for item in abnormal})}; test functions not completed: {not_injected}",
        bool(abnormal) and passed_abnormal == len(abnormal) and not not_injected,
    )
    case_record.metric("max_relative_error", max_error if nonzero else None)
    case_record.metric("flows_compared", len(comparisons))
    case_record.metric("zero_reference_flows", len(zero))
    case_record.metric("non_finite_flows", sum(1 for item in comparisons if not math.isfinite(item["value_W"])))
    case_record.metric("abnormal_inputs_rejected", f"{passed_abnormal}/{len(abnormal)}")
    _done()
    _write_texts(case_record, final=False)
    assert accept1 and accept2 and not check.failed, check.failed


# --------------------------------------------------------------------------- Chinese summary and anomalies


def _text_problem(where: str, exc: BaseException) -> None:
    """A text that cannot be built is itself a failed check, recorded once."""

    key = f"{where}: {type(exc).__name__}: {exc}"
    if key in CTX["text_problems"] or CTX["record"] is None:
        return
    CTX["text_problems"].add(key)
    CTX["record"].check(
        "证据 中文结果说明生成完成",
        "summary_cn and anomalies_cn built from the recorded evidence",
        key[:900],
        False,
    )


def _pa001_cn(info: dict[str, Any]) -> str:
    source = info.get("source")
    if source == "missing":
        return "未找到前置条件 PA-001 的证据，PA-001 已通过无法确认"
    if source == "unreadable":
        return "前置条件 PA-001 的证据文件无法读取，PA-001 已通过无法确认"
    if info.get("case_id") != PRECONDITION_CASE:
        return "证据文件 PA-001.json 记录的用例编号与 PA-001 不符，PA-001 已通过无法确认"
    total, failed = int(info.get("checks") or 0), int(info.get("failed") or 0)
    if total == 0:
        return "前置条件 PA-001 的证据没有检查记录，PA-001 已通过无法确认"
    where = "已在本次测试会话中先于本用例执行，记录为" if source == "session" else "的证据文件记录为"
    status = info.get("status")
    if status == "pass" and failed == 0:
        text = f"前置条件 PA-001 {where}通过，{total} 项检查全部通过"
        if source == "file":
            if info.get("current"):
                text += "，写出时间晚于热模块源文件的最后修改时间"
            else:
                text += "，但写出时间早于热模块源文件的最后修改时间，不能证明当前模块已通过 PA-001"
        return text
    status_text = STATUS_CN.get(status, "未知状态")
    return f"前置条件 PA-001 {where}{status_text}，{total} 项检查中 {failed} 项未通过，前置条件不满足"


def _text_precondition() -> str:
    numbers, flags = CTX["numbers"], CTX["flags"]
    clauses = []
    info = numbers.get("pa001")
    clauses.append(_pa001_cn(info) if info is not None else "前置条件 PA-001 已通过的核对未完成")
    r_values = numbers.get("R_K_W")
    if r_values is None:
        clauses.append("五条连接热阻的装配核对未完成")
    else:
        verdict = "与手算一致" if flags.get("resistances_assembled") else "与手算不一致"
        if len(r_values) == len(DESIGN_PATHS):
            clauses.append(
                f"五条连接热阻在本用例内由 assemble_thermal_parameters 按式 T5 装配，SR、JC、CR、BR、DR 依次为 "
                f"{_list_cn(_num_cn(value) for value in r_values)} K/W，{verdict}"
            )
        else:
            clauses.append(f"assemble_thermal_parameters 给出 {len(r_values)} 个热阻，不是五条连接各一个，{verdict}")
    if flags.get("reference_selfcheck") is False:
        clauses.append("手算表与独立精确计算不一致")
    return "；".join(clauses) + "。"


def _text_battery() -> str:
    numbers, flags = CTX["numbers"], CTX["flags"]
    example = INPUTS["battery_example"]
    head = (
        f"电池算例取电池温度 $T_B$ 为 {_num_cn(float(example['T_B_K']))} K，散热板温度 $T_R$ 为 "
        f"{_num_cn(float(example['T_R_K']))} K，$R_BR$ 为 {_num_cn(float(example['R_BR_K_W']))} K/W"
    )
    clauses = []
    verdicts = []
    q_ex = numbers.get("q_BR_example_W")
    if q_ex is None:
        clauses.append("算例热流的计算未完成")
    else:
        ok = bool(flags.get("q_BR_example"))
        verdicts.append(ok)
        expected = _qty_cn(float(example["q_BR_W"]), "W")
        clauses.append(f"计算得到 $q_BR$ 为 {_qty_cn(q_ex, 'W')}" + ("" if ok else f"，与手算的 {expected} 不符"))
    q_rev = numbers.get("q_BR_reversed_W")
    if q_rev is None:
        clauses.append("两端温度对调的计算未完成")
    else:
        ok = bool(flags.get("q_BR_reversed"))
        verdicts.append(ok)
        expected = _qty_cn(float(example["q_BR_reversed_W"]), "W")
        clauses.append(f"两端温度对调后为 {_qty_cn(q_rev, 'W')}" + ("" if ok else f"，与预期的 {expected} 不符"))
    q_eq = numbers.get("q_BR_equal_W")
    if not q_eq:
        clauses.append("两端温度相等时的计算未完成")
    else:
        ok = bool(flags.get("q_BR_equal_zero"))
        verdicts.append(ok)
        levels = " 与".join(f"均为 {_num_cn(level)} K" for level in q_eq)
        values = " 与 ".join(_qty_cn(value, "W") for value in q_eq.values())
        clauses.append(f"两端温度{levels} 时分别为 {values}" + ("" if ok else "，未全部严格为零"))
    text = head + "，" + "，".join(clauses)
    if len(verdicts) == 3 and all(verdicts):
        text += "，$q_BR$ 的三项结果均与预期一致"
    return text + "。"


def _text_paths() -> str:
    numbers = CTX["numbers"]
    clauses = []
    flip = numbers.get("swap_flip")
    if flip is None:
        clauses.append("逐条对调两端温度的检查未完成")
    elif all(flip.values()):
        clauses.append("五条连接逐条对调两端温度后热流变号且大小不变")
    else:
        bad = [path for path, ok in flip.items() if not ok]
        clauses.append(f"逐条对调两端温度后 {_list_cn(bad)} 的热流未满足变号且大小不变")
    equal_each = numbers.get("equal_each_W")
    if equal_each is None:
        clauses.append("逐条两端等温的检查未完成")
    elif all(value == 0.0 for value in equal_each.values()):
        clauses.append("逐条两端等温时该条连接热流严格为零")
    else:
        bad = [f"{path} 的热流为 {_qty_cn(value, 'W')}" for path, value in equal_each.items() if value != 0.0]
        clauses.append("两端等温时 " + "，".join(bad) + "，未严格为零")
    equal_all = numbers.get("equal_all")
    if equal_all is None:
        clauses.append("六个节点等温的检查未完成")
    else:
        level = _num_cn(equal_all["level_K"])
        bad = [path for path, value in zip(DESIGN_PATHS, equal_all["q_W"], strict=False) if value != 0.0]
        if not bad and len(equal_all["q_W"]) == len(DESIGN_PATHS):
            clauses.append(f"六个节点温度均为 {level} K 时五条连接热流全为零")
        else:
            clauses.append(f"六个节点温度均为 {level} K 时 {_list_cn(bad)} 的热流不为零")
    sign = numbers.get("sign_W")
    if sign is None:
        clauses.append("流向的检查未完成")
    else:
        bad = [path for path, row in sign.items() if not (row["first_hotter_W"] > 0.0 and row["first_colder_W"] < 0.0)]
        if not bad:
            clauses.append("第一个节点较热时热流为正，较冷时热流为负，正值表示由路径名称第一个节点流向第二个节点")
        else:
            clauses.append(f"{_list_cn(bad)} 的热流符号不符合第一个节点较热时为正、较冷时为负的约定")
    if CTX["flags"].get("path_nodes") is False:
        clauses.append("模块的路径端点与路径名称不一致")
    return "，".join(clauses) + "。"


def _text_comparisons() -> str:
    comparisons = CTX["comparisons"]
    tolerance = _sci_cn(REL_TOL)
    if not comparisons:
        return f"本次没有得到可与手算或独立精确计算比较的热流值，验收限 {tolerance} 无法核对。"
    nonzero = [item for item in comparisons if not item["zero_reference"]]
    zero = [item for item in comparisons if item["zero_reference"]]
    nonfinite = [item for item in comparisons if not math.isfinite(item["value_W"])]
    text = f"共 {len(comparisons)} 个热流值与手算或独立精确计算比较"
    if nonzero:
        worst = max(nonzero, key=lambda item: item["relative_error"])
        error = worst["relative_error"]
        text += f"，非零参考值的最大相对误差为 {_short_cn(error)}"
        if error <= REL_TOL:
            text += f"，不超过验收限 {tolerance}"
        else:
            text += f"，超过验收限 {tolerance}，出现在 {worst['path']} 连接"
    if nonfinite:
        paths = list(dict.fromkeys(item["path"] for item in nonfinite))
        text += f"，其中 {len(nonfinite)} 个热流值不是有限数，相对误差记为无穷大，涉及 {_list_cn(paths)} 连接"
    if zero:
        wrong = [item for item in zero if item["relative_error"] != 0.0]
        text += f"；参考值为零的 {len(zero)} 个热流值" + ("全部严格为零" if not wrong else f"中有 {len(wrong)} 个不为零")
    return text + "。"


def _text_reads() -> str:
    reads = CTX["numbers"].get("reads")
    if reads is None:
        return "每条路径只求值一次与读取次序的插桩检查未完成。"
    if not reads["measured"]:
        return "thermal.model 中没有可插桩的 _resolve_parameters 或 _state_fields，每条路径的求值次数与读取次序未能测得。"
    clauses = []
    if reads["counts_ok"]:
        clauses.append("一次调用中五条路径各求值一次，每条路径的热阻读取 1 次，各节点温度的读取次数等于与其相连的路径数")
    else:
        r_counts = _list_cn(str(reads["r_counts"][path]) for path in DESIGN_PATHS)
        t_counts = _list_cn(str(reads["node_reads"][node]) for node in DESIGN_NODES)
        clauses.append(
            f"一次调用中 SR、JC、CR、BR、DR 的热阻读取次数依次为 {r_counts}，S、J、C、B、D、R 的温度读取次数依次为 "
            f"{t_counts}，与每条路径只求值一次不符"
        )
    if not reads["same"]:
        clauses.append("插桩后的热流与未插桩时不逐位相同")
    expected_t = _list_cn(EXPECTED_T_SEQUENCE)
    if reads["t_order"]:
        clauses.append(f"两端温度按 {expected_t} 的次序读取")
    elif reads["t_sequence"]:
        clauses.append(f"两端温度的读取次序为 {_list_cn(reads['t_sequence'])}，与 {expected_t} 不一致")
    else:
        clauses.append("没有记录到两端温度的读取")
    if reads["r_order"]:
        clauses.append("热阻按 SR、JC、CR、BR、DR 的次序读取")
    elif reads["r_first"]:
        clauses.append(f"热阻首次读取的次序为 {_list_cn(reads['r_first'])}，与 SR、JC、CR、BR、DR 不一致")
    else:
        clauses.append("没有记录到热阻的读取")
    if reads["grouped"]:
        clauses.append("每条路径的两端温度与热阻读取完毕后才读取下一条路径")
    else:
        clauses.append("两端温度与热阻没有按路径逐条读取")
    return "插桩计数显示" + "，".join(clauses) + "。"


def _text_expect2_other() -> str:
    numbers = CTX["numbers"]
    clauses = []
    locality = numbers.get("locality")
    if locality is None:
        clauses.append("节点温度扰动的检查未完成")
    elif all(locality.values()):
        clauses.append("任一节点温度升高 1 K 只改变与其相连路径的热流")
    else:
        bad = [node for node, ok in locality.items() if not ok]
        clauses.append(f"节点 {_list_cn(bad)} 温度升高 1 K 时发生变化的热流与其相连路径不符")
    derivative = numbers.get("derivative")
    if derivative is None:
        clauses.append("thermal_derivative 调用次数的检查未完成")
    elif derivative["error"]:
        clauses.append(
            f"thermal_derivative 求值时报错 {derivative['error']}，此前调用 calculate_heat_flows {derivative['calls']} 次"
        )
    else:
        text = f"thermal_derivative 一次求值调用 calculate_heat_flows {derivative['calls']} 次"
        if derivative["same"]:
            text += "并沿用其热流"
        elif derivative["calls"] == 1:
            text += "，返回的热流与该次结果不逐位相同"
        clauses.append(text)
    no_state = numbers.get("no_state")
    if no_state is None:
        clauses.append("函数没有状态更新的检查未完成")
    elif all(no_state.values()):
        clauses.append("调用前后状态与参数逐位相同，返回结果只含热流且不与输入共享内存，重复调用结果逐位相同")
    else:
        names = {"state": "状态对象", "caller": "调用方温度数组", "params": "参数对象", "result": "返回结果", "repeat": "重复调用"}
        bad = [names[key] for key, ok in no_state.items() if not ok]
        clauses.append(f"函数没有状态更新的检查中，{_list_cn(bad)}的检查未通过")
    return "，".join(clauses) + "。"


def _text_abnormal() -> str:
    abnormal = CTX["abnormal"]
    if not abnormal:
        return "异常输入的注入未完成。"
    categories = list(dict.fromkeys(item["category"] for item in abnormal))
    names = categories[0] if len(categories) == 1 else "、".join(categories[:-1]) + "与" + categories[-1]
    passed = sum(item["passed"] for item in abnormal)
    returned = [item for item in abnormal if not item["raised"]]
    text = f"{names}共 {len(abnormal)} 项异常输入中 {passed} 项给出确定的报错并指出具体字段"
    text += f"，{len(returned)} 项没有报错而返回了结果" if returned else "，没有任何一项返回结果"
    order = [item for item in abnormal if item["tag"] == "declared_order"]
    if order and all(item["passed"] for item in order) and CTX["flags"].get("controls"):
        text += f"；{ORDER_CATEGORY}的 {len(order)} 项只改动参数对象声明的 node_order 或 path_order，均由该声明检出"
    keyed = [item for item in abnormal if item["tag"] == "keyed_state"]
    if len(keyed) >= 2 and all(item["passed"] for item in keyed):
        text += "，状态温度以节点名为键给出时不论键序均被拒绝"
    return text + "。"


def _text_extreme() -> str:
    extreme = CTX["numbers"].get("extreme")
    if extreme is None:
        return "有效极端输入的检查未完成。"
    flags = CTX["flags"]
    overridden = extreme["overridden_paths"]
    r_module, r_t5 = extreme["R_K_W"], extreme["R_T5_K_W"]
    clauses = []
    if flags.get("extreme_resistances"):
        values = "，".join(f"$R_{path}$ 为 {_qty_cn(r_module[path], 'K/W')}" for path in overridden)
        clauses.append(f"有效极端输入下覆盖后的 {values}，与按覆盖值和式 T5 的计算一致")
    else:
        bad = []
        for path in DESIGN_PATHS:
            if extreme["R_relative_error"][path] <= REL_TOL:
                continue
            value = f"为 {_qty_cn(r_module[path], 'K/W')}" if path in r_module else "缺失"
            bad.append(f"$R_{path}$ {value}，按式 T5 应为 {_qty_cn(r_t5[path], 'K/W')}")
        clauses.append("有效极端输入下装配所得热阻与按覆盖值和式 T5 的计算不一致，" + "，".join(bad))
    q, reference, errors = extreme["q_W"], extreme["reference_W"], extreme["relative_error"]
    clauses.append(
        f"$q_CR$ 为 {_qty_short_cn(q['CR'], 'W')}，$q_DR$ 为 {_qty_short_cn(q['DR'], 'W')}，$T_B$ 比 $T_R$ 高 "
        f"{_pow2_cn(extreme['dT_BR_K'])} K 时 $q_BR$ 为 {_qty_short_cn(q['BR'], 'W')}"
    )
    worst = max(errors.values())
    if flags.get("no_clipping"):
        clauses.append(f"五条连接热流与式 T2 的最大相对误差为 {_short_cn(worst)}，没有被置零或截断")
    else:
        for path in DESIGN_PATHS:
            if not math.isfinite(q[path]):
                clauses.append(f"$q_{path}$ 不是有限数，不符合式 T2")
            elif path in extreme["zeroed"]:
                clauses.append(f"$q_{path}$ 为零，式 T2 的值为 {_qty_short_cn(reference[path], 'W')}")
            elif errors[path] > REL_TOL:
                clauses.append(
                    f"$q_{path}$ 为 {_qty_short_cn(q[path], 'W')}，与式 T2 的 {_qty_short_cn(reference[path], 'W')} "
                    f"相对误差为 {_short_cn(errors[path])}，超过验收限 {_sci_cn(REL_TOL)}"
                )
    return "；".join(clauses) + "。"


def _summary_cn() -> str:
    sentences = ["本用例按设计报告第 4.2 节式 T2、第 4.3 节电池算例与第 5.5 节检验 calculate_heat_flows。"]
    for build in (
        _text_precondition,
        _text_battery,
        _text_paths,
        _text_comparisons,
        _text_reads,
        _text_expect2_other,
        _text_abnormal,
        _text_extreme,
    ):
        try:
            sentences.append(build())
        except Exception as exc:  # noqa: BLE001  one sentence that cannot be built must not hide the others
            _text_problem(build.__name__, exc)
            sentences.append("一项结果说明生成出错，相应实际值见证据文件的检查记录。")
    # A word such as 无穷大 in place of a number keeps no space after the preceding Chinese character.
    cjk = f"[{chr(0x4E00)}-{chr(0x9FFF)}]"
    return re.sub(f"(?<={cjk}) (?={cjk})", "", "".join(sentences))


def _unexecuted(record: Any) -> list[str]:
    """Planned test functions whose body did not complete, with the reason taken from the conftest failure entries."""

    phases: dict[str, set[str]] = {}
    for item in record.checks:
        words = item["name"].split(" ")
        if not item["passed"] and len(words) == 2 and words[0] in PLAN:
            phases.setdefault(words[0], set()).add(words[1])
    out = []
    for name, label in PLAN.items():
        if name in CTX["completed"]:
            continue
        seen = phases.get(name, set())
        if "setup" in seen:
            out.append(f"{label}在准备阶段出错，未执行")
        elif "call" in seen:
            out.append(f"{label}执行中断")
        else:
            out.append(f"{label}未执行")
    return out


def _anomalies_cn(record: Any, missing: list[str]) -> str:
    phase_cn = {"setup": "准备阶段出错", "call": "未通过", "teardown": "收尾阶段出错"}
    explicit, harness = [], []
    for item in record.checks:
        if item["passed"]:
            continue
        words = item["name"].split(" ")
        if len(words) == 2 and words[0].startswith("test_") and words[1] in phase_cn:
            name, phase = words
            if name not in PLAN:
                harness.append(f"测试函数 {name} {phase_cn[phase]}")
            elif phase == "teardown":
                harness.append(f"测试函数 {name} 收尾阶段出错")
            # A planned function that failed in setup or stopped in its call is listed with the unexecuted items;
            # one that completed failed only its final assertion over the explicit checks listed here.
            continue
        explicit.append(item["name"])
    parts = []
    if explicit:
        parts.append("下列检查未通过：" + "；".join(explicit) + "。")
    if harness:
        parts.append("；".join(harness) + "。")
    if missing:
        parts.append("下列项目未执行完毕：" + "；".join(missing) + "。")
    if not parts:
        return "无"
    if explicit or harness:
        parts.append("各项检查的期望值与实际值记录在证据文件中。")
    return "".join(parts)


def _write_texts(record: Any, *, final: bool) -> None:
    """Writes summary_cn and anomalies_cn; at the end of the module, unexecuted items make the status partial."""

    try:
        summary = _summary_cn()
        missing = _unexecuted(record)
        if final and missing and all(item["passed"] for item in record.checks):
            record.status("partial")
        record.summary(summary)
        record.anomalies(_anomalies_cn(record, missing))
    except Exception as exc:  # noqa: BLE001  the texts must never stay empty or read as a pass
        _text_problem("_write_texts", exc)
        failed = [item["name"] for item in record.checks if not item["passed"]]
        record.summary("本用例的结果说明生成出错，各项检查的期望值与实际值记录在证据文件中。")
        record.anomalies("下列检查未通过：" + "；".join(failed) + "。")
