"""PA-001 热容与热阻装配: assemble_thermal_parameters against the T5 hand calculation.

Design basis: thermal design report 4.5 (T5), 5.2 (assemble_thermal_parameters) and 9.4 (parameter configuration).
The steps follow CASES['PA-001'] of Thermal/test_report/build_test_report_cn.py:

1. assemble the baseline scene and compare C_J_K and R_K_W item by item with the hand calculation table;
2. re-assemble with one override set (one material mass, one contact resistance) and check that the override values
   take precedence over the asset parameter set;
3. check that heat-pipe and liquid-cooling equivalent paths read their total resistance directly and do not add an
   included contact resistance again;
4. inject every abnormal input of the case one at a time and record the error; design 5.2 adds missing data,
   non-finite values, surface area and optical properties checked as T4 requires (with the unit normal of design
   5.1) and a path defined twice;
5. check that ThermalParameters records the resolved values, units, asset versions and sources, and that the
   function creates or updates no operating temperature.

References never come from the thermal package: the reviewed hand calculation table
tests/data/pa_001/hand_calc_table.json, an exact rational evaluation of T5 in tests/data/pa_001/pa001_inputs.py, the
case input values and the ISS thermal FE parameter table Thermal/iss_fem/model/iss_spec.py.

The Chinese summary and anomaly texts are composed only from the recorded checks. Every step registers its
completion and the planned checks of every step are listed in PLANNED, so a step that crashed, did not run or did
not finish is reported together with the checks it did not execute, and the case status becomes fail or partial.
"""

from __future__ import annotations

import copy
import dataclasses
import decimal
import hashlib
import importlib.util
import inspect
import json
import math
import re
import types
from collections.abc import Callable, Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import thermal
from thermal import ThermalConfigurationError, ThermalParameters, ThermalState, assemble_thermal_parameters
from thermal.types import SurfaceRecord

pytestmark = pytest.mark.case("PA-001")

DATA_DIR = Path(__file__).resolve().parent / "data" / "pa_001"


def _load_inputs():
    spec = importlib.util.spec_from_file_location("pa001_inputs", DATA_DIR / "pa001_inputs.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


INP = _load_inputs()
TABLE = INP.load_hand_calc_table()
ACCEPTANCE = TABLE["acceptance"]
REL_LIMIT = float(ACCEPTANCE["relative_error_limit"])  # case acceptance: 1e-12
NODES = ("S", "J", "C", "B", "D", "R")  # design 1.4 temperature order
PATHS = ("SR", "JC", "CR", "BR", "DR")  # design 5.1 path order
UNITS = {"C_J_K": "J/K", "R_K_W": "K/W", "area_m2": "m^2", "temperature": "K"}
PARAMETER_FIELDS = ("C_J_K", "R_K_W", "surfaces", "instance_map", "provenance")  # design table 6
INSTANCE_NODES = {
    "SolarArray01": "S",
    "Compute01": "J",
    "ColdPlate01": "C",
    "Battery01": "B",
    "Controller01": "D",
    "PDU01": "D",
    "Radiator01": "R",
}
PORT_INSTANCES = {"P_pv_W": "SolarArray01", "P_load_W": "Compute01", "Q_B_W": "Battery01", "Q_D_W": "PDU01"}
EXPECTED_METHOD = {
    "SR": "conduction_plus_contact",
    "JC": "conduction_plus_contact",
    "CR": "equivalent_total",
    "BR": "conduction_plus_contact",
    "DR": "equivalent_total",
}
PORTION_KEYS = ("instance_id", "material_id", "mass_kg", "cp_J_kgK", "source")
# An error message may list every path name; that list is removed before looking for the path it names.
ALL_PATHS_TEXT = str(PATHS)

# The steps of the case, the test function that runs each of them, and their wording in the Chinese texts.
STEP_FUNCTIONS = {
    "前置条件": "test_preconditions_inputs_and_hand_calculation",
    "步骤1": "test_step1_capacitance_resistance_against_hand_table",
    "步骤2": "test_step2_overrides_take_precedence",
    "步骤3": "test_step3_equivalent_total_resistance",
    "步骤4": "test_step4_abnormal_inputs",
    "步骤5": "test_step5_provenance_and_no_operating_temperature",
}
STEP_WORDS = {
    "前置条件": "前置条件检查",
    "步骤1": "步骤 1",
    "步骤2": "步骤 2",
    "步骤3": "步骤 3",
    "步骤4": "步骤 4",
    "步骤5": "步骤 5",
}
RUNNER_PHASES = ("setup", "call", "teardown")  # conftest records a failed phase as "<test function> <phase>"


# --------------------------------------------------------------------------------------------- helpers


class Step:
    """Records every check of one step through case_record; one assertion at the end shows any failure."""

    def __init__(self, case_record, label: str) -> None:
        assert label in STEP_FUNCTIONS, label
        self.case_record = case_record
        self.label = label
        self.failed: list[str] = []

    def check(self, title: str, expected: Any, actual: Any, passed: bool) -> bool:
        full = f"{self.label} {title}"
        self.case_record.check(full, expected, actual, bool(passed))
        if not passed:
            self.failed.append(full)
        return bool(passed)

    def finish(self) -> None:
        """Register that the step ran to its end, then fail the test function if any of its checks failed."""

        completed = self.case_record.metrics.setdefault("steps_completed", [])
        if self.label not in completed:
            completed.append(self.label)
        assert not self.failed, "failed checks: " + "; ".join(self.failed)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))


def g(value: Any) -> str:
    return f"{float(value):.15g}"


def gv(value: Any) -> str:
    """g() for a value that may be missing."""

    return g(value) if is_number(value) else "未取得"


def rel_error(value: Any, reference: Fraction | None) -> float:
    """Exact relative difference between a float result and an exact rational reference (inf if not comparable)."""

    if reference is None or not is_number(value):
        return math.inf
    number = float(value)
    if not math.isfinite(number):
        return math.inf
    if reference == 0:
        return 0.0 if number == 0.0 else math.inf
    return float(abs(Fraction(number) - reference) / abs(reference))


def flatten_numbers(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [item for part in value.values() for item in flatten_numbers(part)]
    if isinstance(value, (list, tuple)):
        return [item for part in value for item in flatten_numbers(part)]
    return [value]


def plain(value: Any) -> Any:
    """Plain Python data for comparisons: mappings, sequences, arrays and records are unwrapped."""

    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return [plain(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    return value


def digest(value: Any) -> str:
    """Short SHA-256 of the canonical JSON form of a value, recorded as evidence of equality."""

    text = json.dumps(plain(value), sort_keys=True, ensure_ascii=False, default=repr)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def exact_text(value: Fraction) -> str:
    """An exact rational as a terminating decimal when it has one, otherwise as a ratio a/b."""

    rest = value.denominator
    for factor in (2, 5):
        while rest % factor == 0:
            rest //= factor
    if rest != 1:
        return f"{value.numerator}/{value.denominator}"
    with decimal.localcontext() as context:
        context.prec = 80
        quotient = decimal.Decimal(value.numerator) / decimal.Decimal(value.denominator)
        return format(quotient.normalize(), "f")


def component(components: list[dict], instance_id: str) -> dict:
    return next(item for item in components if item["instance_id"] == instance_id)


def material(components: list[dict], instance_id: str, material_id: str) -> dict:
    return next(item for item in component(components, instance_id)["materials"] if item["material_id"] == material_id)


def surface(components: list[dict], instance_id: str, surface_id: str) -> dict:
    return next(item for item in component(components, instance_id)["surfaces"] if item["surface_id"] == surface_id)


def connection(connections: list[dict], path: str) -> dict:
    return next(item for item in connections if item["path"] == path)


def table_references(section: str) -> tuple[dict[str, Fraction], dict[str, Fraction]]:
    """Capacitances and resistances of the reviewed hand calculation table (baseline, or with the overrides)."""

    capacitance = {node: INP.table_fraction(TABLE["baseline"]["C_J_K"][node]["value"]) for node in NODES}
    resistance = {path: INP.table_fraction(TABLE["baseline"]["R_K_W"][path]["value"]) for path in PATHS}
    if section == "override":
        for node, entry in TABLE["override"]["C_J_K"].items():
            capacitance[node] = INP.table_fraction(entry["value"])
        for path, entry in TABLE["override"]["R_K_W"].items():
            resistance[path] = INP.table_fraction(entry["value"])
    return capacitance, resistance


def table_entries(section: str) -> dict[str, str]:
    """The eleven table entries as written in hand_calc_table.json, keyed C_<node> and R_<path>."""

    entries = {f"C_{node}": TABLE["baseline"]["C_J_K"][node]["value"] for node in NODES}
    entries.update({f"R_{path}": TABLE["baseline"]["R_K_W"][path]["value"] for path in PATHS})
    if section == "override":
        entries.update({f"C_{node}": entry["value"] for node, entry in TABLE["override"]["C_J_K"].items()})
        entries.update({f"R_{path}": entry["value"] for path, entry in TABLE["override"]["R_K_W"].items()})
    return entries


# Facts of the case inputs used in the expected texts and the summary (read from the input records, not typed twice).
_BASE_COMPONENTS, _BASE_CONNECTIONS = INP.fresh_inputs()
_OVERRIDES = INP.override_set()
MASS_OLD = material(_BASE_COMPONENTS, "Battery01", "bt01_li_ion_cells")["mass_kg"]
MASS_NEW = _OVERRIDES["components"]["Battery01"]["materials"]["bt01_li_ion_cells"]["mass_kg"]
CONTACT_OLD = connection(_BASE_CONNECTIONS, "BR")["contact_resistance_K_W"]
CONTACT_NEW = _OVERRIDES["connections"]["BR"]["contact_resistance_K_W"]
DR_CONTACT = connection(_BASE_CONNECTIONS, "DR")["contact_resistance_K_W"]
SURFACE_COUNT = sum(len(item["surfaces"]) for item in _BASE_COMPONENTS)
EXPECTED_APPLIED = [
    {"target": "components/Battery01/materials/bt01_li_ion_cells", "field": "mass_kg", "old": MASS_OLD,
     "new": MASS_NEW, "source": INP.OVERRIDE_SOURCE},
    {"target": "connections/BR", "field": "contact_resistance_K_W", "old": CONTACT_OLD, "new": CONTACT_NEW,
     "source": INP.OVERRIDE_SOURCE},
]


# --------------------------------------------------------------------------------------------- check titles
# The recorded check name is "<step label> <title>"; the summary finds every check by these exact names.

T_PRE_COMPONENTS = "components 含实例与温度节点对应、材料质量、比热与表面记录"
T_PRE_CONNECTIONS = "connections 给出五条连接的固体路径参数或等效总热阻"
T_PRE_MBSU = "MBSU 方块尺寸、密度与比热取自国际空间站模型参数表"
T_PRE_PANEL = "散热器面板面密度、比热与面板尺寸取自国际空间站模型参数表"
T_PRE_ACCEPTANCE = "手算表验收值与案例给定值一致"
T_DIMS = "C_J_K 与 R_K_W 的维数和顺序"
T_EXAMPLE = "第 4.5 节算例热容"
T_MBSU = "MBSU 方块热容"
T_PANEL = "散热器面板单位面积热容"
T_SURFACES = "表面参数按资产表面顺序装配"
T_MASS_OVERRIDE = "材料质量覆盖值优先于资产参数集"
T_CONTACT_OVERRIDE = "接触热阻覆盖值优先于资产参数集"
T_OTHERS_KEPT = "未覆盖的热容与热阻保持资产参数集的值"
T_APPLIED = "provenance 记录已应用的覆盖值"
T_RESOLVED = "provenance 记录覆盖后的解析值"
T_INPUTS_KEPT = "装配不修改输入的 components、connections 与 overrides"
T_CR = "热管等效路径 CR 直接读取总热阻"
T_DR_ADDED = "液冷等效路径 DR 的总热阻不含接触部分时叠加安装接触热阻"
T_DR_INCLUDED = "液冷等效路径 DR 的总热阻已含接触部分时直接读取"
T_BOUNDARY = "吸收率与发射率取边界值 0 与 1 时正常装配"
T_ORDER_UNITS = "provenance 记录节点顺序、路径顺序与单位"
T_ASSETS = "provenance 记录七个实例的资产标识、资产版本与适用温区"
T_SURFACE_PROVENANCE = "provenance 记录表面所属实例、解析后的表面参数与数据来源"
T_INSTANCE_MAP = "instance_map 记录实例与温度节点对应及功率端口来源"
T_OVERRIDES_PROVENANCE = "provenance 记录覆盖值的目标、新旧值与来源"
T_NO_TEMPERATURE = "函数没有创建或更新运行温度"
T_REPEAT = "重复装配得到相同结果，函数不保留运行状态"


def t_pre_table(section: str) -> str:
    return f"手算表 {section} 与按同一组输入的精确有理数 T5 计算一致"


def t_compare(section_label: str, item: str) -> str:
    if item in NODES:
        return f"{section_label} 热容 C_{item} 与手算表比较"
    return f"{section_label} 热阻 R_{item} 与手算表比较"


def t_node_provenance(node: str) -> str:
    return f"provenance 记录节点 {node} 的热容、材料份额、解析后的质量与比热及数据来源"


def t_path_provenance(path: str) -> str:
    return f"provenance 记录路径 {path} 的热阻、计算方法、解析后的输入与数据来源"


def compare_with_table(step: Step, params: ThermalParameters, section: str, label: str) -> tuple[dict, dict]:
    """Step 1 and 2: every C_i and R_ij against the hand calculation table, relative error <= 1e-12."""

    ref_c, ref_r = table_references(section)
    errors_c: dict[str, float] = {}
    errors_r: dict[str, float] = {}
    for index, node in enumerate(NODES):
        value = float(params.C_J_K[index])
        errors_c[node] = rel_error(value, ref_c[node])
        step.check(
            t_compare(label, node),
            f"{g(ref_c[node])} J/K，相对误差不超过 {REL_LIMIT:g}",
            f"{g(value)} J/K，相对误差 {errors_c[node]:.2e}",
            errors_c[node] <= REL_LIMIT,
        )
    for index, path in enumerate(PATHS):
        value = float(params.R_K_W[index])
        errors_r[path] = rel_error(value, ref_r[path])
        step.check(
            t_compare(label, path),
            f"{g(ref_r[path])} K/W，相对误差不超过 {REL_LIMIT:g}",
            f"{g(value)} K/W，相对误差 {errors_r[path]:.2e}",
            errors_r[path] <= REL_LIMIT,
        )
    return errors_c, errors_r


# --------------------------------------------------------------------------------------------- abnormal inputs


def names_record(message: str, tokens: list[str], absent: list[str]) -> tuple[list[str], list[str]]:
    """Tokens missing from the message and forbidden tokens present, whole words only."""

    text = message.replace(ALL_PATHS_TEXT, "")

    def has(token: str) -> bool:
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", text) is not None

    return [token for token in tokens if not has(token)], [token for token in absent if has(token)]


@dataclasses.dataclass(frozen=True, eq=False)
class Rejection:
    """One abnormal input: the records and the fields its error must name, and how the input is built."""

    step: str
    group: str
    title: str
    records: tuple[str, ...]
    fields: tuple[str, ...] = ()
    mutate: Callable[[list[dict], list[dict]], None] | None = None
    overrides: Mapping[str, Any] | None = None
    absent: tuple[str, ...] = ()

    @property
    def check_name(self) -> str:
        return f"{self.step} {self.title}"


def expect_rejection(step: Step, spec: Rejection) -> bool:
    """Call the assembly twice on the same abnormal input; it must raise the same ThermalConfigurationError,
    whose message names the offending records and, for a field value or a missing field, the field."""

    assert spec.step == step.label, (spec.step, step.label)
    components, connections = INP.fresh_inputs()
    if spec.mutate is not None:
        spec.mutate(components, connections)
    outcomes = []
    for _ in range(2):
        try:
            result = assemble_thermal_parameters(
                copy.deepcopy(components), copy.deepcopy(connections), copy.deepcopy(spec.overrides)
            )
        except Exception as exc:  # noqa: BLE001 - the class is part of the check
            outcomes.append((type(exc), str(exc)))
        else:
            outcomes.append(
                (None, f"无报错，返回 ThermalParameters，C_J_K {result.C_J_K.tolist()}，R_K_W {result.R_K_W.tolist()}")
            )
    error_type, message = outcomes[0]
    repeatable = outcomes[0] == outcomes[1]
    right_class = error_type is not None and issubclass(error_type, ThermalConfigurationError)
    missing, present = names_record(message, list(spec.records) + list(spec.fields), list(spec.absent))
    passed = right_class and repeatable and not missing and not present
    actual = f"{error_type.__name__ if error_type else '无报错'}: {message}；两次调用报错相同 {repeatable}"
    if missing:
        actual += f"；报错没有指出 {missing}"
    if present:
        actual += f"；报错误指 {present}"
    expected = "ThermalConfigurationError，报错指出记录 " + "、".join(spec.records)
    if spec.fields:
        expected += " 与字段 " + "、".join(spec.fields)
    if spec.absent:
        expected += "，不指向 " + "、".join(spec.absent)
    expected += "，两次调用报错相同"
    step.check(spec.title, expected, actual, passed)
    return passed


def set_material(instance_id: str, material_id: str, field: str, value: Any):
    def mutate(components, connections):
        material(components, instance_id, material_id)[field] = value

    return mutate


def drop_material_field(instance_id: str, material_id: str, field: str):
    def mutate(components, connections):
        del material(components, instance_id, material_id)[field]

    return mutate


def set_surface(instance_id: str, surface_id: str, field: str, value: Any):
    def mutate(components, connections):
        surface(components, instance_id, surface_id)[field] = value

    return mutate


def drop_surface_field(instance_id: str, surface_id: str, field: str):
    def mutate(components, connections):
        del surface(components, instance_id, surface_id)[field]

    return mutate


def set_connection(path: str, field: str, value: Any):
    def mutate(components, connections):
        connection(connections, path)[field] = value

    return mutate


def drop_connection_field(path: str, field: str):
    def mutate(components, connections):
        del connection(connections, path)[field]

    return mutate


def _duplicate_material(components, connections):
    # the cold plate's aluminium portion listed again under the computing board (design 4.5 example of double count)
    component(components, "Compute01")["materials"].append(
        copy.deepcopy(material(components, "ColdPlate01", "cp01_al6061_plate"))
    )


def _duplicate_material_shared_node(components, connections):
    # Controller01 and PDU01 share node D; the chassis portion listed under both would count C_D twice
    component(components, "PDU01")["materials"].append(
        copy.deepcopy(material(components, "Controller01", "pc01_al_chassis"))
    )


def _duplicate_surface_same_component(components, connections):
    radiator = component(components, "Radiator01")
    radiator["surfaces"].append(copy.deepcopy(radiator["surfaces"][0]))


def _duplicate_surface_two_components(components, connections):
    component(components, "Radiator01")["surfaces"].append(
        copy.deepcopy(component(components, "SolarArray01")["surfaces"][1])
    )


def _drop_path(path: str):
    def mutate(components, connections):
        connections[:] = [item for item in connections if item["path"] != path]

    return mutate


def _unknown_path(components, connections):
    connections.append({"path": "SC", "length_m": 0.1, "conductivity_W_mK": 167.0, "area_m2": 1.0e-3,
                        "contact_resistance_K_W": 0.1, "source": "PA-001 test value: path not in the design"})


def _duplicate_path(components, connections):
    connections.append(copy.deepcopy(connection(connections, "BR")))


def _no_material(instance_id: str):
    def mutate(components, connections):
        component(components, instance_id)["materials"] = []

    return mutate


def _override(title: str, records: tuple[str, ...], fields: tuple[str, ...], overrides: Mapping[str, Any]) -> Rejection:
    return Rejection("步骤2", "override", title, records, fields, None, overrides)


def _listed(title: str, records: tuple[str, ...], fields: tuple[str, ...], mutate, absent: tuple[str, ...] = ()):
    return Rejection("步骤4", "case", f"异常输入 {title}", records, fields, mutate, None, absent)


def _added(group: str, title: str, records: tuple[str, ...], fields: tuple[str, ...], mutate) -> Rejection:
    return Rejection("步骤4", group, f"补充异常输入 {title}", records, fields, mutate)


BC, MB = "Battery01", "bt01_li_ion_cells"
REJECTIONS: tuple[Rejection, ...] = (
    # step 2: an override is checked like an asset value and must name an existing target and a source
    _override("覆盖值把材料质量改为负值", (BC, MB), ("mass_kg",),
              {"components": {BC: {"materials": {MB: {"mass_kg": -3.45}}}}, "source": INP.OVERRIDE_SOURCE}),
    _override("覆盖值指向不存在的实例", ("Battery02",), (),
              {"components": {"Battery02": {"materials": {MB: {"mass_kg": 3.45}}}}, "source": INP.OVERRIDE_SOURCE}),
    _override("覆盖值指向不存在的材料", (BC, "bt01_cells"), (),
              {"components": {BC: {"materials": {"bt01_cells": {"mass_kg": 3.45}}}}, "source": INP.OVERRIDE_SOURCE}),
    _override("覆盖值指向不存在的连接", ("BX",), (),
              {"connections": {"BX": {"contact_resistance_K_W": 0.08}}, "source": INP.OVERRIDE_SOURCE}),
    _override("覆盖值没有数据来源", ("overrides",), ("source",),
              {"connections": {"BR": {"contact_resistance_K_W": 0.08}}}),
    # step 3: a contact resistance added again to a total that already includes it, through an override
    Rejection("步骤3", "equivalent", "覆盖值给已含接触热阻的热管路径 CR 再加接触热阻", ("CR",), ("contact_resistance_K_W",),
              None, {"connections": {"CR": {"contact_resistance_K_W": 0.01}}, "source": INP.OVERRIDE_SOURCE}),
    # step 4: the abnormal inputs listed by the case
    _listed("质量为零", (BC, MB), ("mass_kg",), set_material(BC, MB, "mass_kg", 0.0)),
    _listed("质量为负", (BC, MB), ("mass_kg",), set_material(BC, MB, "mass_kg", -3.2)),
    _listed("比热为零", ("ColdPlate01", "cp01_al6061_plate"), ("cp_J_kgK",),
            set_material("ColdPlate01", "cp01_al6061_plate", "cp_J_kgK", 0.0)),
    _listed("比热为负", ("ColdPlate01", "cp01_al6061_plate"), ("cp_J_kgK",),
            set_material("ColdPlate01", "cp01_al6061_plate", "cp_J_kgK", -896.0)),
    _listed("长度为零", ("SR",), ("length_m",), set_connection("SR", "length_m", 0.0)),
    _listed("长度为负", ("SR",), ("length_m",), set_connection("SR", "length_m", -0.12)),
    _listed("导热系数为零", ("BR",), ("conductivity_W_mK",), set_connection("BR", "conductivity_W_mK", 0.0)),
    _listed("导热系数为负", ("BR",), ("conductivity_W_mK",), set_connection("BR", "conductivity_W_mK", -167.0)),
    _listed("截面积为零", ("JC",), ("area_m2",), set_connection("JC", "area_m2", 0.0)),
    _listed("截面积为负", ("JC",), ("area_m2",), set_connection("JC", "area_m2", -0.0064)),
    _listed("固体路径接触热阻为负", ("JC",), ("contact_resistance_K_W",),
            set_connection("JC", "contact_resistance_K_W", -0.05)),
    _listed("液冷等效路径接触热阻为负", ("DR",), ("contact_resistance_K_W",),
            set_connection("DR", "contact_resistance_K_W", -0.021)),
    _listed("同一份材料归入计算节点与冷板两个组件", ("cp01_al6061_plate", "Compute01", "ColdPlate01"), (),
            _duplicate_material),
    _listed("同一份材料归入共用节点 D 的 Controller01 与 PDU01", ("pc01_al_chassis", "Controller01", "PDU01"), (),
            _duplicate_material_shared_node),
    _listed("同一组件内重复表面", ("Radiator01", "rd01_front"), (), _duplicate_surface_same_component),
    _listed("太阳能板与散热板使用同一表面", ("Radiator01", "SolarArray01", "sa01_back"), (),
            _duplicate_surface_two_components),
    _listed("未定义连接 DR", ("DR",), (), _drop_path("DR"), ("SR", "JC", "CR", "BR")),
    _listed("连接使用设计之外的路径名称", ("SC",), (), _unknown_path),
    _listed("等效总热阻已含接触热阻又再给出接触热阻", ("CR",), ("contact_resistance_K_W",),
            set_connection("CR", "contact_resistance_K_W", 0.01)),
    # step 4, design 5.2: missing data is reported and never replaced by a default device value
    _added("missing", "材料缺少质量，不生成默认值", ("SolarArray01", "sa01_cfrp_substrate"), ("mass_kg",),
           drop_material_field("SolarArray01", "sa01_cfrp_substrate", "mass_kg")),
    _added("missing", "材料缺少比热，不生成默认值", (BC, "bt01_al_case"), ("cp_J_kgK",),
           drop_material_field(BC, "bt01_al_case", "cp_J_kgK")),
    _added("missing", "固体路径缺少接触热阻，不按零处理", ("SR",), ("contact_resistance_K_W",),
           drop_connection_field("SR", "contact_resistance_K_W")),
    _added("missing", "等效总热阻不含接触部分却缺少接触热阻，不按零处理", ("DR",), ("contact_resistance_K_W",),
           drop_connection_field("DR", "contact_resistance_K_W")),
    _added("missing", "等效路径缺少 includes_contact", ("CR",), ("includes_contact",),
           drop_connection_field("CR", "includes_contact")),
    _added("missing", "太阳能板表面缺少面积，不生成默认值", ("SolarArray01", "sa01_front"), ("area_m2",),
           drop_surface_field("SolarArray01", "sa01_front", "area_m2")),
    _added("missing", "太阳能板表面缺少吸收率，不生成默认值", ("SolarArray01", "sa01_back"), ("absorptivity",),
           drop_surface_field("SolarArray01", "sa01_back", "absorptivity")),
    _added("missing", "散热板表面缺少发射率，不生成默认值", ("Radiator01", "rd01_back"), ("emissivity",),
           drop_surface_field("Radiator01", "rd01_back", "emissivity")),
    _added("missing", "散热板表面缺少法向，不生成默认值", ("Radiator01", "rd01_front"), ("normal_body",),
           drop_surface_field("Radiator01", "rd01_front", "normal_body")),
    _added("missing", "计算节点没有任何材料", ("J", "Compute01"), (), _no_material("Compute01")),
    # step 4, design 5.2: mass, specific heat, length, conductivity and area finite, contact resistance a number >= 0
    _added("nonfinite", "质量为非有限值", (BC, MB), ("mass_kg",), set_material(BC, MB, "mass_kg", math.nan)),
    _added("nonfinite", "比热为无穷大", ("ColdPlate01", "cp01_coolant_water"), ("cp_J_kgK",),
           set_material("ColdPlate01", "cp01_coolant_water", "cp_J_kgK", math.inf)),
    _added("nonfinite", "长度为非有限值", ("SR",), ("length_m",), set_connection("SR", "length_m", math.nan)),
    _added("nonfinite", "导热系数为无穷大", ("BR",), ("conductivity_W_mK",),
           set_connection("BR", "conductivity_W_mK", math.inf)),
    _added("nonfinite", "截面积为无穷大", ("JC",), ("area_m2",), set_connection("JC", "area_m2", math.inf)),
    _added("nonfinite", "固体路径接触热阻为非有限值", ("BR",), ("contact_resistance_K_W",),
           set_connection("BR", "contact_resistance_K_W", math.nan)),
    # step 4, design 5.2 "面积和光学参数按 T4 检查": A_f > 0 and alpha, epsilon in [0, 1] (T4, table 5), unit normal (5.1)
    _added("surface", "表面面积为零", ("Radiator01", "rd01_front"), ("area_m2",),
           set_surface("Radiator01", "rd01_front", "area_m2", 0.0)),
    _added("surface", "表面面积为负", ("SolarArray01", "sa01_front"), ("area_m2",),
           set_surface("SolarArray01", "sa01_front", "area_m2", -1.2)),
    _added("surface", "表面面积为非有限值", ("SolarArray01", "sa01_back"), ("area_m2",),
           set_surface("SolarArray01", "sa01_back", "area_m2", math.nan)),
    _added("surface", "吸收率大于 1", ("SolarArray01", "sa01_front"), ("absorptivity",),
           set_surface("SolarArray01", "sa01_front", "absorptivity", 1.2)),
    _added("surface", "吸收率小于 0", ("Radiator01", "rd01_back"), ("absorptivity",),
           set_surface("Radiator01", "rd01_back", "absorptivity", -0.2)),
    _added("surface", "吸收率为非有限值", ("Radiator01", "rd01_front"), ("absorptivity",),
           set_surface("Radiator01", "rd01_front", "absorptivity", math.nan)),
    _added("surface", "发射率大于 1", ("Radiator01", "rd01_front"), ("emissivity",),
           set_surface("Radiator01", "rd01_front", "emissivity", 1.05)),
    _added("surface", "发射率小于 0", ("SolarArray01", "sa01_back"), ("emissivity",),
           set_surface("SolarArray01", "sa01_back", "emissivity", -0.8)),
    _added("surface", "法向长度不为 1", ("SolarArray01", "sa01_front"), ("normal_body",),
           set_surface("SolarArray01", "sa01_front", "normal_body", [1.2, 0.0, 1.6])),
    _added("surface", "法向为零向量", ("Radiator01", "rd01_back"), ("normal_body",),
           set_surface("Radiator01", "rd01_back", "normal_body", [0.0, 0.0, 0.0])),
    # step 4: every path defined exactly once
    _added("duplicate", "同一路径定义两次", ("BR",), (), _duplicate_path),
)
SUPPLEMENTARY_GROUPS = ("missing", "nonfinite", "surface", "duplicate")
# Boundary values of T4 (absorptivity and emissivity take values from 0 to 1): these must be accepted.
BOUNDARY_INPUTS = (
    ("SolarArray01", "sa01_back", "absorptivity", 0.0),
    ("SolarArray01", "sa01_front", "absorptivity", 1.0),
    ("Radiator01", "rd01_back", "emissivity", 0.0),
    ("Radiator01", "rd01_front", "emissivity", 1.0),
)


def group_specs(*groups: str) -> list[Rejection]:
    return [spec for spec in REJECTIONS if spec.group in groups]


# --------------------------------------------------------------------------------------------- planned checks


def _names(label: str, titles: list[str]) -> list[str]:
    return [f"{label} {title}" for title in titles]


def _compare_titles(section_label: str) -> list[str]:
    return [t_compare(section_label, item) for item in NODES + PATHS]


# Claims of the summary and the exact check names that support each of them.
CLAIM_NAMES: dict[str, list[str]] = {
    "pre": _names("前置条件", [T_PRE_COMPONENTS, T_PRE_CONNECTIONS, T_PRE_MBSU, T_PRE_PANEL, t_pre_table("baseline"),
                           t_pre_table("override"), T_PRE_ACCEPTANCE]),
    "s1_compare": _names("步骤1", _compare_titles("基准装配")),
    "s1_acceptance": _names("步骤1", [T_EXAMPLE, T_MBSU, T_PANEL]),
    "s1_layout": _names("步骤1", [T_DIMS, T_SURFACES]),
    "s2_override": _names("步骤2", _compare_titles("覆盖后装配") + [T_MASS_OVERRIDE, T_CONTACT_OVERRIDE, T_OTHERS_KEPT,
                                                                T_APPLIED, T_RESOLVED, T_INPUTS_KEPT]),
    "s2_rejections": [spec.check_name for spec in group_specs("override")],
    "s3": _names("步骤3", [T_CR, T_DR_ADDED, T_DR_INCLUDED]) + [spec.check_name for spec in group_specs("equivalent")],
    "s4_case": [spec.check_name for spec in group_specs("case")],
    "s4_supplementary": [spec.check_name for spec in group_specs(*SUPPLEMENTARY_GROUPS)],
    "s4_boundary": _names("步骤4", [T_BOUNDARY]),
    "s5_provenance": _names("步骤5", [T_ORDER_UNITS] + [t_node_provenance(node) for node in NODES]
                            + [t_path_provenance(path) for path in PATHS]
                            + [T_ASSETS, T_SURFACE_PROVENANCE, T_INSTANCE_MAP, T_OVERRIDES_PROVENANCE]),
    "s5_temperature": _names("步骤5", [T_NO_TEMPERATURE, T_REPEAT]),
}
PLANNED: dict[str, list[str]] = {
    label: [name for names in CLAIM_NAMES.values() for name in names if name.startswith(label + " ")]
    for label in STEP_FUNCTIONS
}
assert sum(len(names) for names in PLANNED.values()) == sum(len(names) for names in CLAIM_NAMES.values())
assert all(len(set(names)) == len(names) for names in PLANNED.values())


# --------------------------------------------------------------------------------------------- preconditions


def test_preconditions_inputs_and_hand_calculation(case_record):
    """Case preconditions: the input records, the ISS table values of the case and the reviewed hand table."""

    step = Step(case_record, "前置条件")
    components, connections = INP.fresh_inputs()

    # components carry instance to node assignment, material masses and specific heats, and surface records
    assignment = {item["instance_id"]: item["node_id"] for item in components}
    complete = all(
        item["materials"] and all("mass_kg" in m and "cp_J_kgK" in m for m in item["materials"]) for item in components
    )
    surfaces_on = sorted({item["node_id"] for item in components if item["surfaces"]})
    step.check(
        T_PRE_COMPONENTS,
        f"实例与节点 {INSTANCE_NODES}；每份材料有质量与比热；表面只在 S 与 R",
        f"实例与节点 {assignment}；材料完整 {complete}；表面所在节点 {surfaces_on}",
        assignment == INSTANCE_NODES and complete and surfaces_on == ["R", "S"],
    )
    forms = {}
    for item in connections:
        if "equivalent_total_resistance_K_W" in item:
            forms[item["path"]] = "equivalent_total"
        elif all(key in item for key in ("length_m", "conductivity_W_mK", "area_m2", "contact_resistance_K_W")):
            forms[item["path"]] = "solid"
    step.check(
        T_PRE_CONNECTIONS,
        "SR、JC、BR 为长度、导热系数、截面积与接触热阻；CR 为热管等效总热阻；DR 为液冷等效总热阻",
        f"{forms}",
        forms == {"SR": "solid", "JC": "solid", "CR": "equivalent_total", "BR": "solid", "DR": "equivalent_total"},
    )

    # the MBSU block and radiator panel values of the case equal the ISS thermal FE parameter table
    iss = INP.iss_table_values()
    case_size = tuple(float(v) for v in INP.CASE_MBSU["size_m"])
    sizes_ok = len(iss["mbsu_sizes_m"]) == 4 and all(size == case_size for size in iss["mbsu_sizes_m"])
    step.check(
        T_PRE_MBSU,
        "0.94 m×0.84 m×0.51 m，密度 300 kg/m³，比热 900 J/(kg K)",
        f"{iss['mbsu_names']} 尺寸 {iss['mbsu_sizes_m'][0]} m，材料类别 {iss['mbsu_material_classes']}，"
        f"密度 {g(iss['mbsu_density_kg_m3'])} kg/m³，比热 {g(iss['mbsu_cp_J_kgK'])} J/(kg K)",
        sizes_ok and iss["mbsu_density_kg_m3"] == 300.0 and iss["mbsu_cp_J_kgK"] == 900.0
        and iss["mbsu_material_classes"] == ["box"],
    )
    areal = iss["panel_areal_mass_kg_m2"]
    length = iss["panel_length_m"]
    step.check(
        T_PRE_PANEL,
        "面密度 8 kg/m²，比热 900 J/(kg K)，面板 3.4 m×2.705 m，相对误差不超过 1e-12",
        f"面密度 {g(iss['panel_density_kg_m3'])}×{g(iss['panel_thickness_m'])} = {g(areal)} kg/m²，比热 "
        f"{g(iss['panel_cp_J_kgK'])} J/(kg K)，面板 {g(iss['panel_width_m'])} m×{g(length)} m",
        abs(areal - 8.0) <= 8.0 * REL_LIMIT and iss["panel_cp_J_kgK"] == 900.0 and iss["panel_width_m"] == 3.4
        and abs(length - 2.705) <= 2.705 * REL_LIMIT,
    )

    # the reviewed hand calculation table agrees exactly with T5 evaluated again in rational arithmetic
    for section, overrides in (("baseline", None), ("override", INP.override_set())):
        exact = INP.exact_reference(components, connections, overrides)
        ref_c, ref_r = table_references(section)
        exact_values = {f"C_{n}": exact["C_J_K"][n] for n in NODES} | {f"R_{p}": exact["R_K_W"][p] for p in PATHS}
        table_values = {f"C_{n}": ref_c[n] for n in NODES} | {f"R_{p}": ref_r[p] for p in PATHS}
        mismatch = [name for name in table_values if exact_values[name] != table_values[name]]
        entries = table_entries(section)
        step.check(
            t_pre_table(section),
            "手算表 11 项：" + "、".join(f"{name} {text}" for name, text in entries.items()) + "，与精确计算逐项相等",
            "精确有理数 T5：" + "、".join(f"{name} {exact_text(value)}" for name, value in exact_values.items())
            + ("；逐项相等" if not mismatch else f"；不相等项 {mismatch}"),
            not mismatch,
        )
    mbsu = INP.mbsu_mass_exact() * Fraction(INP.CASE_MBSU["cp_J_kgK"])
    per_area = INP.panel_mass_exact() * Fraction(INP.CASE_PANEL["cp_J_kgK"]) / INP.panel_area_exact()
    example = Fraction(INP.CASE_DESIGN_EXAMPLE["mass_kg"]) * Fraction(INP.CASE_DESIGN_EXAMPLE["cp_J_kgK"])
    step.check(
        T_PRE_ACCEPTANCE,
        "第 4.5 节算例 1000 J/K，MBSU 方块 108727.92 J/K 约 108.7 kJ/K，散热器面板 7200 J/(m² K)",
        f"算例 {example} J/K，MBSU {float(mbsu)} J/K，面板 {per_area} J/(m² K)",
        example == INP.table_fraction(ACCEPTANCE["design_4_5_example_C_J_K"])
        and mbsu == INP.table_fraction(ACCEPTANCE["mbsu_block_C_J_K"])
        and per_area == INP.table_fraction(ACCEPTANCE["radiator_panel_C_per_area_J_m2K"])
        and f"{float(mbsu) / 1000:.1f}" == ACCEPTANCE["mbsu_block_C_kJ_K_one_decimal"]
        and f"{float(per_area) / 1000:.1f}" == ACCEPTANCE["radiator_panel_C_per_area_kJ_m2K_one_decimal"],
    )
    step.finish()


# --------------------------------------------------------------------------------------------- step 1


def test_step1_capacitance_resistance_against_hand_table(case_record):
    step = Step(case_record, "步骤1")
    components, connections = INP.fresh_inputs()
    params = assemble_thermal_parameters(components, connections, None)

    step.check(
        T_DIMS,
        f"C_J_K 形状 (6,) 按 {NODES}，R_K_W 形状 (5,) 按 {PATHS}",
        f"C_J_K 形状 {np.shape(params.C_J_K)}，R_K_W 形状 {np.shape(params.R_K_W)}，provenance 节点顺序 "
        f"{tuple(params.provenance['node_order'])}，路径顺序 {tuple(params.provenance['path_order'])}",
        np.shape(params.C_J_K) == (6,) and np.shape(params.R_K_W) == (5,)
        and tuple(params.provenance["node_order"]) == NODES and tuple(params.provenance["path_order"]) == PATHS
        and tuple(thermal.types.NODE_ORDER) == NODES and tuple(thermal.types.PATH_ORDER) == PATHS,
    )
    errors_c, errors_r = compare_with_table(step, params, "baseline", "基准装配")
    case_record.metric("C_J_K_baseline", [float(v) for v in params.C_J_K])
    case_record.metric("R_K_W_baseline", [float(v) for v in params.R_K_W])
    ref_c, ref_r = table_references("baseline")
    case_record.metric("C_J_K_hand_table", [float(ref_c[n]) for n in NODES])
    case_record.metric("R_K_W_hand_table", [float(ref_r[p]) for p in PATHS])
    case_record.metric("max_rel_error_C_baseline", max(errors_c.values()))
    case_record.metric("max_rel_error_R_baseline", max(errors_r.values()))

    # design 4.5 example: 1 kg at 1000 J/(kg K) is the only portion of node J
    c_j = float(params.C_J_K[NODES.index("J")])
    j_portions = params.provenance["capacitance"]["J"]["portions"]
    err = rel_error(c_j, INP.table_fraction(ACCEPTANCE["design_4_5_example_C_J_K"]))
    step.check(
        T_EXAMPLE,
        f"1000 J/K，相对误差不超过 {REL_LIMIT:g}",
        f"C_J {g(c_j)} J/K，相对误差 {err:.2e}，节点 J 材料 "
        f"{[(p['material_id'], p['mass_kg'], p['cp_J_kgK']) for p in j_portions]}",
        err <= REL_LIMIT and len(j_portions) == 1 and j_portions[0]["mass_kg"] == 1.0
        and j_portions[0]["cp_J_kgK"] == 1000.0,
    )
    case_record.metric("design_4_5_example_C_J_K", c_j)

    # MBSU block: the PDU01 material portion of node D, and node D as its sum with Controller01
    d_portions = params.provenance["capacitance"]["D"]["portions"]
    mbsu = [p for p in d_portions if p["instance_id"] == "PDU01"]
    mbsu_value = float(mbsu[0]["C_J_K"]) if len(mbsu) == 1 else None
    mbsu_kilo = f"{mbsu_value / 1000:.1f}" if mbsu_value is not None and math.isfinite(mbsu_value) else "未取得"
    err = rel_error(mbsu_value, INP.table_fraction(ACCEPTANCE["mbsu_block_C_J_K"]))
    step.check(
        T_MBSU,
        f"108727.92 J/K，即 108.7 kJ/K，相对误差不超过 {REL_LIMIT:g}",
        f"PDU01 材料 {[p['material_id'] for p in mbsu]} 热容 {gv(mbsu_value)} J/K，即 {mbsu_kilo} kJ/K，"
        f"相对误差 {err:.2e}；节点 D 由 {[p['instance_id'] + '/' + p['material_id'] for p in d_portions]} 组成，"
        f"C_D {g(params.C_J_K[NODES.index('D')])} J/K",
        err <= REL_LIMIT and mbsu_kilo == ACCEPTANCE["mbsu_block_C_kJ_K_one_decimal"],
    )
    case_record.metric("mbsu_block_C_J_K", mbsu_value)

    # radiator panel: areal heat capacity = C_R over the panel area of its front surface
    c_r = float(params.C_J_K[NODES.index("R")])
    front = next(s for s in params.surfaces if s.surface_id == "rd01_front")
    per_area = c_r / float(front.area_m2)
    err = rel_error(per_area, INP.table_fraction(ACCEPTANCE["radiator_panel_C_per_area_J_m2K"]))
    per_area_kilo = f"{per_area / 1000:.1f}" if math.isfinite(per_area) else "未取得"
    step.check(
        T_PANEL,
        f"7200 J/(m² K)，即 7.2 kJ/(m² K)，相对误差不超过 {REL_LIMIT:g}",
        f"C_R {g(c_r)} J/K，面板面积 {g(front.area_m2)} m²，单位面积热容 {g(per_area)} J/(m² K)，"
        f"即 {per_area_kilo} kJ/(m² K)，相对误差 {err:.2e}",
        err <= REL_LIMIT and per_area_kilo == ACCEPTANCE["radiator_panel_C_per_area_kJ_m2K_one_decimal"],
    )
    case_record.metric("radiator_panel_C_per_area_J_m2K", per_area)

    # surface parameters are assembled from the surface records in asset surface order
    expected = [
        (s["surface_id"], item["node_id"], s["area_m2"], tuple(s["normal_body"]), s["absorptivity"], s["emissivity"])
        for item in components
        for s in item["surfaces"]
    ]
    actual = [
        (s.surface_id, s.node_id, float(s.area_m2), tuple(float(v) for v in s.normal_body), float(s.absorptivity),
         float(s.emissivity))
        for s in params.surfaces
    ]
    step.check(
        T_SURFACES,
        f"{expected}",
        f"{actual}",
        actual == expected and all(isinstance(s, SurfaceRecord) for s in params.surfaces),
    )
    step.finish()


# --------------------------------------------------------------------------------------------- step 2


def test_step2_overrides_take_precedence(case_record):
    step = Step(case_record, "步骤2")
    components, connections = INP.fresh_inputs()
    overrides = INP.override_set()
    snapshot = copy.deepcopy((components, connections, overrides))
    digest_before = digest(snapshot)
    baseline = assemble_thermal_parameters(copy.deepcopy(components), copy.deepcopy(connections), None)
    params = assemble_thermal_parameters(components, connections, overrides)

    errors_c, errors_r = compare_with_table(step, params, "override", "覆盖后装配")
    case_record.metric("C_J_K_override", [float(v) for v in params.C_J_K])
    case_record.metric("R_K_W_override", [float(v) for v in params.R_K_W])
    case_record.metric("max_rel_error_C_override", max(errors_c.values()))
    case_record.metric("max_rel_error_R_override", max(errors_r.values()))

    ref_base_c, ref_base_r = table_references("baseline")
    ref_c, ref_r = table_references("override")
    b, br = NODES.index("B"), PATHS.index("BR")
    c_b0, c_b1 = float(baseline.C_J_K[b]), float(params.C_J_K[b])
    r_br0, r_br1 = float(baseline.R_K_W[br]), float(params.R_K_W[br])
    step.check(
        T_MASS_OVERRIDE,
        f"电池单体质量 {g(MASS_OLD)} kg 改为 {g(MASS_NEW)} kg，C_B 由 {g(ref_base_c['B'])} J/K 变为 {g(ref_c['B'])} J/K",
        f"C_B 由 {g(c_b0)} J/K 变为 {g(c_b1)} J/K，相对误差 {rel_error(c_b0, ref_base_c['B']):.2e} 与 "
        f"{rel_error(c_b1, ref_c['B']):.2e}",
        rel_error(c_b0, ref_base_c["B"]) <= REL_LIMIT and rel_error(c_b1, ref_c["B"]) <= REL_LIMIT,
    )
    step.check(
        T_CONTACT_OVERRIDE,
        f"BR 接触热阻 {g(CONTACT_OLD)} K/W 改为 {g(CONTACT_NEW)} K/W，R_BR 由 {g(ref_base_r['BR'])} K/W 变为 "
        f"{g(ref_r['BR'])} K/W",
        f"R_BR 由 {g(r_br0)} K/W 变为 {g(r_br1)} K/W，相对误差 {rel_error(r_br0, ref_base_r['BR']):.2e} 与 "
        f"{rel_error(r_br1, ref_r['BR']):.2e}",
        rel_error(r_br0, ref_base_r["BR"]) <= REL_LIMIT and rel_error(r_br1, ref_r["BR"]) <= REL_LIMIT,
    )
    case_record.metric("C_B_baseline_J_K", c_b0)
    case_record.metric("C_B_override_J_K", c_b1)
    case_record.metric("R_BR_baseline_K_W", r_br0)
    case_record.metric("R_BR_override_K_W", r_br1)

    others_c = [i for i, n in enumerate(NODES) if n != "B"]
    others_r = [i for i, p in enumerate(PATHS) if p != "BR"]
    same = bool(
        np.array_equal(params.C_J_K[others_c], baseline.C_J_K[others_c])
        and np.array_equal(params.R_K_W[others_r], baseline.R_K_W[others_r])
    )
    pairs = [f"C_{NODES[i]} {g(params.C_J_K[i])} 与 {g(baseline.C_J_K[i])} J/K" for i in others_c]
    pairs += [f"R_{PATHS[i]} {g(params.R_K_W[i])} 与 {g(baseline.R_K_W[i])} K/W" for i in others_r]
    step.check(
        T_OTHERS_KEPT,
        "C_S、C_J、C_C、C_D、C_R 与 R_SR、R_JC、R_CR、R_DR 与基准装配逐位相同",
        "覆盖后与基准装配：" + "、".join(pairs) + f"；逐位相同 {same}",
        same,
    )
    applied = plain(params.provenance["overrides_applied"])
    step.check(
        T_APPLIED,
        f"{EXPECTED_APPLIED}；基准装配没有覆盖记录",
        f"{applied}；基准装配覆盖记录 {plain(baseline.provenance['overrides_applied'])}",
        applied == EXPECTED_APPLIED and plain(baseline.provenance["overrides_applied"]) == [],
    )
    resolved_mass = [p["mass_kg"] for p in params.provenance["capacitance"]["B"]["portions"]
                     if p["material_id"] == "bt01_li_ion_cells"]
    resolved_contact = params.provenance["resistance"]["BR"]["inputs"]["contact_resistance_K_W"]
    step.check(
        T_RESOLVED,
        f"电池单体质量 {g(MASS_NEW)} kg，BR 接触热阻 {g(CONTACT_NEW)} K/W",
        f"电池单体质量 {resolved_mass} kg，BR 接触热阻 {resolved_contact} K/W",
        resolved_mass == [MASS_NEW] and resolved_contact == CONTACT_NEW,
    )
    unchanged = (components, connections, overrides) == snapshot
    digest_after = digest((components, connections, overrides))
    step.check(
        T_INPUTS_KEPT,
        f"调用后电池单体质量仍为 {g(MASS_OLD)} kg，BR 接触热阻仍为 {g(CONTACT_OLD)} K/W，overrides 不变，"
        "调用前后输入记录逐项相同",
        f"调用后 Battery01/bt01_li_ion_cells mass_kg {material(components, 'Battery01', 'bt01_li_ion_cells')['mass_kg']} kg，"
        f"BR contact_resistance_K_W {connection(connections, 'BR')['contact_resistance_K_W']} K/W，overrides {overrides}；"
        f"输入摘要 SHA-256 调用前 {digest_before}，调用后 {digest_after}；逐项相同 {unchanged}",
        unchanged and digest_before == digest_after,
    )

    # supplementary: an override is checked like an asset value and must name an existing target and a source
    rejected = sum(expect_rejection(step, spec) for spec in group_specs("override"))
    case_record.metric("override_abnormal_total", len(group_specs("override")))
    case_record.metric("override_abnormal_rejected", int(rejected))
    step.finish()


# --------------------------------------------------------------------------------------------- step 3


def test_step3_equivalent_total_resistance(case_record):
    step = Step(case_record, "步骤3")
    components, connections = INP.fresh_inputs()
    params = assemble_thermal_parameters(components, connections, None)
    cr, dr = PATHS.index("CR"), PATHS.index("DR")

    r_cr = float(params.R_K_W[cr])
    record = plain(params.provenance["resistance"]["CR"])
    err = rel_error(r_cr, Fraction("0.085"))
    step.check(
        T_CR,
        f"0.085 K/W，等效总热阻已含接触热阻，不再叠加，相对误差不超过 {REL_LIMIT:g}",
        f"R_CR {g(r_cr)} K/W，相对误差 {err:.2e}，方法 {record['method']}，输入 {record['inputs']}",
        err <= REL_LIMIT and record["method"] == "equivalent_total"
        and record["inputs"] == {"equivalent_total_resistance_K_W": 0.085, "includes_contact": True},
    )
    case_record.metric("R_CR_K_W", r_cr)

    r_dr = float(params.R_K_W[dr])
    record = plain(params.provenance["resistance"]["DR"])
    err = rel_error(r_dr, Fraction("0.045") + Fraction("0.021"))
    step.check(
        T_DR_ADDED,
        f"0.045 K/W 加 0.021 K/W 等于 0.066 K/W，相对误差不超过 {REL_LIMIT:g}",
        f"R_DR {g(r_dr)} K/W，相对误差 {err:.2e}，方法 {record['method']}，输入 {record['inputs']}",
        err <= REL_LIMIT and record["method"] == "equivalent_total"
        and record["inputs"] == {"equivalent_total_resistance_K_W": 0.045, "includes_contact": False,
                                 "contact_resistance_K_W": 0.021},
    )
    case_record.metric("R_DR_K_W", r_dr)

    # the liquid-cooling path supplied as a measured total that already includes the contact part
    components, connections = INP.fresh_inputs()
    connections = [item for item in connections if item["path"] != "DR"] + [{
        "path": "DR", "equivalent_total_resistance_K_W": 0.066, "includes_contact": True,
        "source": "PA-001 test value: liquid-cooling loop equivalent from a loop test, contact included",
    }]
    variant = assemble_thermal_parameters(components, connections, None)
    r_dr_total = float(variant.R_K_W[dr])
    record = plain(variant.provenance["resistance"]["DR"])
    err = rel_error(r_dr_total, Fraction("0.066"))
    step.check(
        T_DR_INCLUDED,
        f"0.066 K/W，不再叠加接触热阻，相对误差不超过 {REL_LIMIT:g}",
        f"R_DR {g(r_dr_total)} K/W，相对误差 {err:.2e}，方法 {record['method']}，输入 {record['inputs']}",
        err <= REL_LIMIT and record["method"] == "equivalent_total"
        and record["inputs"] == {"equivalent_total_resistance_K_W": 0.066, "includes_contact": True},
    )
    case_record.metric("R_DR_total_included_K_W", r_dr_total)

    # a contact resistance added again to a total that already includes it is refused, also through an override
    for spec in group_specs("equivalent"):
        expect_rejection(step, spec)
    step.finish()


# --------------------------------------------------------------------------------------------- step 4


def test_step4_abnormal_inputs(case_record):
    step = Step(case_record, "步骤4")
    counts: dict[str, list[int]] = {}
    for spec in REJECTIONS:
        if spec.step != step.label:
            continue
        passed = expect_rejection(step, spec)
        total_rejected = counts.setdefault(spec.group, [0, 0])
        total_rejected[0] += 1
        total_rejected[1] += int(passed)

    # T4 lets absorptivity and emissivity take the values 0 and 1 themselves; they are assembled as given
    results = []
    accepted = 0
    for instance_id, surface_id, field, value in BOUNDARY_INPUTS:
        components, connections = INP.fresh_inputs()
        surface(components, instance_id, surface_id)[field] = value
        try:
            params = assemble_thermal_parameters(components, connections, None)
        except Exception as exc:  # noqa: BLE001 - recorded as the outcome
            results.append(f"{instance_id}/{surface_id} {field} {g(value)}：{type(exc).__name__}: {exc}")
            continue
        stored = getattr(next(s for s in params.surfaces if s.surface_id == surface_id), field)
        recorded = params.provenance["surfaces"][surface_id][field]
        good = float(stored) == value and recorded == value
        accepted += int(good)
        results.append(f"{instance_id}/{surface_id} {field} {g(value)}：装配完成，SurfaceRecord {g(stored)}，"
                       f"provenance {gv(recorded)}")
    step.check(
        T_BOUNDARY,
        "四种输入均正常装配，SurfaceRecord 与 provenance 保存给定值；T4 规定吸收率与发射率取值为 0 至 1",
        "；".join(results),
        accepted == len(BOUNDARY_INPUTS),
    )

    case_record.metric("abnormal_case_listed_total", counts.get("case", [0, 0])[0])
    case_record.metric("abnormal_case_listed_rejected", counts.get("case", [0, 0])[1])
    case_record.metric("abnormal_supplementary_total", sum(counts.get(name, [0, 0])[0] for name in SUPPLEMENTARY_GROUPS))
    case_record.metric(
        "abnormal_supplementary_rejected", sum(counts.get(name, [0, 0])[1] for name in SUPPLEMENTARY_GROUPS)
    )
    case_record.metric(
        "abnormal_supplementary_groups",
        {name: {"total": counts.get(name, [0, 0])[0], "rejected": counts.get(name, [0, 0])[1]}
         for name in SUPPLEMENTARY_GROUPS},
    )
    case_record.metric("optical_boundary_inputs_accepted", accepted)
    step.finish()


# --------------------------------------------------------------------------------------------- step 5

# Names that would carry an operating temperature or a state record; only declared ranges are allowed.
STATE_KEYS = {"temperature_K", "initial_state", "initial_temperature_K", "T_K", "T_init_K", "time_s", "run_id", "state"}
STATE_KEY_PATTERN = re.compile(r"T_[A-Za-z0-9]+_K")


def _is_state_key(name: str) -> bool:
    return name in STATE_KEYS or STATE_KEY_PATTERN.fullmatch(name) is not None


def _is_temperature_name(name: str) -> bool:
    return "temperature" in name.lower() or _is_state_key(name)


def _named_items(value: Any) -> list[tuple[str, Any]] | None:
    """Named entries of a mapping, a NamedTuple, a dataclass (fields and other attributes) or an attribute record."""

    if isinstance(value, Mapping):
        return [(str(key), item) for key, item in value.items()]
    if isinstance(value, tuple) and hasattr(type(value), "_fields"):
        return [(str(name), getattr(value, name)) for name in type(value)._fields]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        items = {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
        for name, item in getattr(value, "__dict__", {}).items():
            items.setdefault(str(name), item)
        return list(items.items())
    if hasattr(value, "__dict__") and not isinstance(
        value, (type, types.ModuleType, types.FunctionType, types.BuiltinFunctionType, types.MethodType)
    ):
        return [(str(name), item) for name, item in vars(value).items()]
    return None


def _scan(value: Any, where: str, found: dict[str, list], seen: set[int]) -> None:
    """Walk every named and unnamed entry; collect ThermalState records, state-temperature names and every
    temperature-named entry with its plain value."""

    if isinstance(value, ThermalState):
        found["states"].append(where)
        return
    named = _named_items(value)
    unnamed = isinstance(value, (list, tuple, set, frozenset)) or (
        isinstance(value, np.ndarray) and value.dtype.hasobject
    )
    if named is None and not unnamed:
        return
    if id(value) in seen:
        return
    seen.add(id(value))
    if named is not None:
        for name, item in named:
            path = f"{where}.{name}"
            if _is_state_key(name):
                found["keys"].append(path)
            if _is_temperature_name(name):
                found["temperatures"].append((path, plain(item)))
            _scan(item, path, found, seen)
        return
    items = value.ravel().tolist() if isinstance(value, np.ndarray) else list(value)
    for index, item in enumerate(items):
        _scan(item, f"{where}[{index}]", found, seen)


def _portion_text(entry: Mapping[str, Any], capacitance: Any) -> str:
    return (f"{entry.get('instance_id')}/{entry.get('material_id')} {gv(entry.get('mass_kg'))} kg×"
            f"{gv(entry.get('cp_J_kgK'))} J/(kg K) = {gv(capacitance)} J/K，来源 {entry.get('source')!r}")


def test_step5_provenance_and_no_operating_temperature(case_record, monkeypatch):
    step = Step(case_record, "步骤5")
    components, connections = INP.fresh_inputs()
    overrides = INP.override_set()
    resolved_components, resolved_connections = INP.apply_overrides_exact(components, connections, overrides)
    ref_c, ref_r = table_references("override")

    constructed: list[Any] = []
    original = ThermalState.__post_init__

    def counting_post_init(self):
        constructed.append(self)
        original(self)

    monkeypatch.setattr(ThermalState, "__post_init__", counting_post_init)
    params = assemble_thermal_parameters(components, connections, overrides)
    repeat = assemble_thermal_parameters(*INP.fresh_inputs(), INP.override_set())
    monkeypatch.setattr(ThermalState, "__post_init__", original)
    provenance = params.provenance

    step.check(
        T_ORDER_UNITS,
        f"node_order {NODES}，path_order {PATHS}，units {UNITS}",
        f"node_order {tuple(provenance['node_order'])}，path_order {tuple(provenance['path_order'])}，"
        f"units {plain(provenance['units'])}",
        tuple(provenance["node_order"]) == NODES and tuple(provenance["path_order"]) == PATHS
        and plain(provenance["units"]) == UNITS,
    )

    # capacitance: per node the value, the resolved material portions with their sources, each portion m c_p
    for index, node in enumerate(NODES):
        entry = plain(provenance["capacitance"][node])
        expected = [
            {"instance_id": item["instance_id"], "material_id": m["material_id"], "mass_kg": m["mass_kg"],
             "cp_J_kgK": m["cp_J_kgK"], "source": m["source"]}
            for item in resolved_components if item["node_id"] == node for m in item["materials"]
        ]
        exact_portion = {(p["instance_id"], p["material_id"]): INP.q(p["mass_kg"]) * INP.q(p["cp_J_kgK"])
                         for p in expected}
        portions = entry.get("portions") or []
        recorded = [{key: p.get(key) for key in PORTION_KEYS} for p in portions]
        portion_errors = [rel_error(p.get("C_J_K"), exact_portion.get((p.get("instance_id"), p.get("material_id"))))
                          for p in portions]
        worst = max(portion_errors) if portion_errors else math.inf
        value = entry.get("value_J_K")
        value_error = rel_error(value, ref_c[node])
        step.check(
            t_node_provenance(node),
            f"value_J_K 等于 C_J_K[{index}]，与手算表 {g(ref_c[node])} J/K 的相对误差不超过 {REL_LIMIT:g}；材料份额 "
            + "；".join(_portion_text(p, float(exact_portion[(p["instance_id"], p["material_id"])])) for p in expected)
            + f"；每份热容等于质量乘比热，相对误差不超过 {REL_LIMIT:g}",
            f"value_J_K {gv(value)} J/K，C_J_K[{index}] {g(params.C_J_K[index])} J/K，相对误差 {value_error:.2e}；"
            "材料份额 " + "；".join(_portion_text(p, p.get("C_J_K")) for p in portions)
            + f"；每份热容最大相对误差 {worst:.2e}",
            recorded == expected and worst <= REL_LIMIT and value == float(params.C_J_K[index])
            and value_error <= REL_LIMIT,
        )

    # resistance: per path the value, the method, the resolved inputs with the conduction term, and the source
    for index, path in enumerate(PATHS):
        entry = plain(provenance["resistance"][path])
        given = connection(resolved_connections, path)
        expected_inputs = {key: value for key, value in given.items() if key not in ("path", "source")}
        inputs = dict(entry.get("inputs") or {})
        recorded_inputs = {key: value for key, value in inputs.items() if key != "conduction_K_W"}
        solid = EXPECTED_METHOD[path] == "conduction_plus_contact"
        if solid:
            conduction = INP.q(given["length_m"]) / (INP.q(given["conductivity_W_mK"]) * INP.q(given["area_m2"]))
            conduction_error = rel_error(inputs.get("conduction_K_W"), conduction)
            conduction_ok = conduction_error <= REL_LIMIT
            conduction_expected = f"；导热部分 conduction_K_W 等于 l/(κA) {g(conduction)} K/W"
            conduction_actual = f"；导热部分相对误差 {conduction_error:.2e}"
        else:
            conduction_ok = "conduction_K_W" not in inputs
            conduction_expected = "；等效路径不记录导热部分"
            conduction_actual = ""
        value = entry.get("value_K_W")
        value_error = rel_error(value, ref_r[path])
        step.check(
            t_path_provenance(path),
            f"value_K_W 等于 R_K_W[{index}]，与手算表 {g(ref_r[path])} K/W 的相对误差不超过 {REL_LIMIT:g}；"
            f"方法 {EXPECTED_METHOD[path]}；输入 {expected_inputs}{conduction_expected}；来源 {given['source']!r}",
            f"value_K_W {gv(value)} K/W，R_K_W[{index}] {g(params.R_K_W[index])} K/W，相对误差 {value_error:.2e}；"
            f"方法 {entry.get('method')}；输入 {inputs}{conduction_actual}；来源 {entry.get('source')!r}",
            value == float(params.R_K_W[index]) and value_error <= REL_LIMIT
            and entry.get("method") == EXPECTED_METHOD[path] and recorded_inputs == expected_inputs
            and entry.get("source") == given["source"] and conduction_ok,
        )

    # asset identifiers, versions and declared temperature ranges of every instance
    expected_assets = {item["instance_id"]: [item["asset_id"], item["asset_version"], item["node_id"],
                                             list(item["temperature_range_K"])] for item in resolved_components}
    actual_assets = {key: [value.get("asset_id"), value.get("asset_version"), value.get("node_id"),
                           value.get("temperature_range_K")] for key, value in plain(provenance["assets"]).items()}
    step.check(T_ASSETS, f"{expected_assets}", f"{actual_assets}", actual_assets == expected_assets)

    # surfaces: owning instance, resolved area, normal, optical properties and source
    expected_surfaces = {
        s["surface_id"]: {"instance_id": item["instance_id"], "node_id": item["node_id"], "area_m2": s["area_m2"],
                          "normal_body": list(s["normal_body"]), "absorptivity": s["absorptivity"],
                          "emissivity": s["emissivity"], "source": s["source"]}
        for item in resolved_components for s in item["surfaces"]
    }
    actual_surfaces = plain(provenance["surfaces"])
    step.check(T_SURFACE_PROVENANCE, f"{expected_surfaces}", f"{actual_surfaces}", actual_surfaces == expected_surfaces)

    instance_map = plain(params.instance_map)
    expected_map = {
        "nodes": {node: [iid for iid, n in INSTANCE_NODES.items() if n == node] for node in NODES},
        "ports": dict(PORT_INSTANCES),
    }
    step.check(T_INSTANCE_MAP, f"{expected_map}", f"{instance_map}", instance_map == expected_map)
    overrides_record = plain(provenance["overrides_applied"])
    step.check(T_OVERRIDES_PROVENANCE, f"{EXPECTED_APPLIED}", f"{overrides_record}", overrides_record == EXPECTED_APPLIED)

    # no operating temperature is created or updated: fields and every other attribute of the result are scanned
    field_names = tuple(field.name for field in dataclasses.fields(ThermalParameters))
    signature = tuple(inspect.signature(assemble_thermal_parameters).parameters)
    attributes = [name for name, _ in (_named_items(params) or [])]
    hidden = [name for name in attributes if name not in PARAMETER_FIELDS]
    found: dict[str, list] = {"states": [], "keys": [], "temperatures": []}
    _scan(params, "parameters", found, set())
    declared = {bound for item in components for bound in item["temperature_range_K"]}
    expected_ranges = {}
    for node in NODES:
        ranges = [item["temperature_range_K"] for item in components if item["node_id"] == node]
        expected_ranges[node] = [max(r[0] for r in ranges), min(r[1] for r in ranges)]
    # a temperature entry is either the unit label "K" of provenance units, or numbers that are declared bounds
    untraced = []
    bounds = 0
    for path, value in found["temperatures"]:
        if path.endswith(".units.temperature"):
            if value != "K":
                untraced.append(path)
            continue
        numbers = flatten_numbers(value)
        if numbers and all(is_number(item) and item in declared for item in numbers):
            bounds += len(numbers)
        else:
            untraced.append(path)
    ranges_ok = plain(provenance["temperature_range_K"]) == expected_ranges
    step.check(
        T_NO_TEMPERATURE,
        f"ThermalParameters 字段为 {PARAMETER_FIELDS}；函数参数只有 components、connections、overrides；装配期间创建 "
        "ThermalState 0 个；字段与其余内部属性中没有 ThermalState，也没有状态温度字段；与温度有关的条目只有温度单位 K "
        "与各实例声明的适用温区边界，节点温区为实例温区的交集",
        f"字段 {field_names}；参数 {signature}；扫描的属性 {attributes}，其中内部属性 {hidden}；创建 ThermalState "
        f"{len(constructed)} 个；状态记录 {found['states']}；状态字段 {found['keys']}；温度相关条目 "
        f"{[path for path, _ in found['temperatures']]}；其中可追溯到声明温区边界的数值 {bounds} 个，不可追溯的条目 "
        f"{untraced}；节点温区 {plain(provenance['temperature_range_K'])}",
        field_names == PARAMETER_FIELDS and signature == ("components", "connections", "overrides")
        and not constructed and not found["states"] and not found["keys"] and bounds > 0 and not untraced
        and ranges_ok,
    )
    case_record.metric("thermal_state_constructions_during_assembly", len(constructed))
    case_record.metric("scanned_parameter_attributes", attributes)

    same_c = bool(np.array_equal(params.C_J_K, repeat.C_J_K))
    same_r = bool(np.array_equal(params.R_K_W, repeat.R_K_W))
    surfaces_digests = (digest(params.surfaces), digest(repeat.surfaces))
    provenance_digests = (digest(params.provenance), digest(repeat.provenance))
    same = (same_c and same_r and plain(params.surfaces) == plain(repeat.surfaces)
            and plain(params.provenance) == plain(repeat.provenance))
    step.check(
        T_REPEAT,
        "两次装配的 C_J_K、R_K_W、表面与 provenance 逐项相同",
        f"C_J_K {[float(v) for v in params.C_J_K]} 与 {[float(v) for v in repeat.C_J_K]}，相同 {same_c}；"
        f"R_K_W {[float(v) for v in params.R_K_W]} 与 {[float(v) for v in repeat.R_K_W]}，相同 {same_r}；"
        f"表面摘要 SHA-256 {surfaces_digests[0]} 与 {surfaces_digests[1]}；provenance 摘要 SHA-256 "
        f"{provenance_digests[0]} 与 {provenance_digests[1]}；逐项相同 {same}",
        same,
    )
    step.finish()


# --------------------------------------------------------------------------------------------- summary

AREAL_UNIT = "J·m^{−2}·K^{−1}"
AREAL_KILO_UNIT = "kJ·m^{−2}·K^{−1}"
FALLBACK_SUMMARY = "汇总程序没有完成，实际结果以证据文件中的各项检查记录为准。"
FALLBACK_ANOMALY = "汇总程序没有完成。"
# CJK symbols and punctuation, CJK ideographs, compatibility ideographs and full-width forms
_CJK = "[" + "".join(f"{chr(low)}-{chr(high)}" for low, high in (
    (0x3000, 0x303F), (0x3400, 0x9FFF), (0xF900, 0xFAFF), (0xFF00, 0xFFEF))) + "]"
_SUPERSCRIPT_MARKUP = re.compile(r"\^\{([^{}]*)\}")
# brackets of any kind, dashes and hyphens, question marks, Unicode superscripts and a stray caret
_FORBIDDEN = re.compile(r"[()\[\]{}<>（）［］｛｝【】〔〕〈〉《》「」『』\-‐‑‒–—―－?？¹²³⁰⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾^]")


def num_text(value: Any, fmt: str, unit: str = "") -> str:
    """A number for the Chinese texts: U+2212 for a negative value, 非有限值 for nan or inf, 未取得 if missing."""

    if not is_number(value):
        return "未取得"
    number = float(value)
    if not math.isfinite(number):
        return "非有限值"
    text = format(int(number) if fmt.endswith("d") else number, fmt).replace("-", "−")
    return f"{text} {unit}" if unit else text


def sci_text(value: Any, digits: int = 1) -> str:
    """Scientific notation in the report markup, for example 8.8×10^{−17}."""

    if not is_number(value):
        return "未取得"
    number = float(value)
    if not math.isfinite(number):
        return "非有限值"
    if number == 0.0:
        return "0"
    mantissa, exponent = f"{number:.{digits}e}".split("e")
    return mantissa.replace("-", "−") + "×10^{" + str(int(exponent)).replace("-", "−") + "}"


def stated(label: str, text: str) -> str:
    """'<label>为 <value>', or '<label>未取得' when the value was not obtained."""

    space = " " if label[-1].isascii() else ""
    return f"{label}{space}未取得" if text == "未取得" else f"{label}{space}为 {text}"


def change(label: str, before: str, after: str) -> str:
    """'<label>由 <before> 变为 <after>', or a statement that the values were not obtained."""

    if "未取得" in (before, after):
        return f"{label}的覆盖前后值没有全部取得"
    return f"{label}由 {before} 变为 {after}"


def largest(*values: Any) -> Any:
    """Largest of several metrics: None if one is missing, inf if one is not finite."""

    if not all(is_number(value) for value in values):
        return None
    numbers = [float(value) for value in values]
    return math.inf if not all(math.isfinite(number) for number in numbers) else max(numbers)


def text_rule_violations(text: str) -> list[str]:
    """Report rules of summary_cn and anomalies_cn: no brackets, dashes or question marks, superscripts only as
    ^{...} markup holding an integer, and the minus sign U+2212 only in front of a digit."""

    problems = []
    for match in _SUPERSCRIPT_MARKUP.finditer(text):
        if re.fullmatch(r"−?[0-9]+", match.group(1)) is None:
            problems.append(f"superscript {match.group(1)!r}")
    inner = _SUPERSCRIPT_MARKUP.sub(lambda match: match.group(1), text)
    problems += [f"character {char!r}" for char in sorted(set(_FORBIDDEN.findall(inner)))]
    if re.search(r"−(?![0-9])", inner):
        problems.append("minus sign not followed by a digit")
    return problems


def compose_case_text(checks: list[dict], metrics: Mapping[str, Any]) -> tuple[str, str, str | None]:
    """Chinese summary, anomaly text and status override of the case, from the recorded checks and metrics only."""

    m = metrics
    present = {c["name"] for c in checks}
    failed_names = {c["name"] for c in checks if not c["passed"]}
    completed = set(m.get("steps_completed") or [])

    def state(names: list[str]) -> str:
        if any(name in failed_names for name in names):
            return "failed"
        recorded = sum(name in present for name in names)
        if recorded == 0:
            return "not_run"
        return "passed" if recorded == len(names) else "missing"

    def says(claim: str, passed: str, failed: str, missing: str, not_run: str) -> str:
        return {"passed": passed, "failed": failed, "missing": missing, "not_run": not_run}[state(CLAIM_NAMES[claim])]

    def counts(specs: list[Rejection]) -> tuple[int, int, int, int]:
        ok = sum(spec.check_name in present and spec.check_name not in failed_names for spec in specs)
        bad = sum(spec.check_name in failed_names for spec in specs)
        return len(specs), ok, bad, len(specs) - ok - bad

    def rejection_clause(specs: list[Rejection], subject: str) -> str:
        total, ok, bad, missing = counts(specs)
        if ok == total:
            return f"{subject}全部给出 ThermalConfigurationError"
        if missing == total:
            return f"{subject}的检查未执行"
        parts = [f"{subject}中 {ok} 项给出符合要求的 ThermalConfigurationError"]
        if bad:
            parts.append(f"{bad} 项没有给出符合要求的报错")
        if missing:
            parts.append(f"{missing} 项未执行")
        return "，".join(parts)

    runner = {label: {f"{function} {phase}" for phase in RUNNER_PHASES} for label, function in STEP_FUNCTIONS.items()}
    executed = {
        label: label in completed or any(c["name"].startswith(label + " ") or c["name"] in runner[label] for c in checks)
        for label in STEP_FUNCTIONS
    }
    unexecuted = {label: [name for name in PLANNED[label] if name not in present] for label in STEP_FUNCTIONS}

    sentences: list[str] = []
    if not any(executed.values()):
        sentences.append("本次运行没有执行前置条件检查与步骤 1 至步骤 5，没有取得装配结果。")
    else:
        sentences.append(
            "以七个组件实例与五条连接为输入调用 assemble_thermal_parameters，组件含第 4.5 节算例材料与国际空间站模型参数表中的"
            " MBSU 方块和散热器面板。"
        )
        sentences.append(says(
            "pre",
            "前置条件检查确认组件记录含实例与温度节点对应、材料质量、比热与表面记录，五条连接给出固体路径参数或等效总热阻，"
            "MBSU 方块与散热器面板参数取自国际空间站模型参数表，手算表与按同一组输入的精确有理数 T5 计算逐项相等。",
            "前置条件检查有未通过的项。", "前置条件检查没有全部执行。", "前置条件检查未执行。"))

        base = ("基准装配的六个热容与五个热阻与手算表逐项比较，"
                + stated("热容最大相对误差", sci_text(m.get("max_rel_error_C_baseline"))) + "，"
                + stated("热阻最大相对误差", sci_text(m.get("max_rel_error_R_baseline")))
                + f"，验收限值为 {sci_text(REL_LIMIT, 0)}")
        sentences.append(says("s1_compare", base + "，十一项全部满足。", base + "，有未满足的项。",
                              "基准装配与手算表的逐项比较没有全部执行。", "基准装配与手算表的逐项比较未执行。"))

        def with_kilo(key: str, fmt: str, unit: str, kilo_unit: str) -> str:
            value = m.get(key)
            text = num_text(value, fmt, unit)
            if is_number(value) and math.isfinite(float(value)):
                text += f"，即 {num_text(float(value) / 1000, '.1f', kilo_unit)}"
            return text

        targets = (f"{ACCEPTANCE['design_4_5_example_C_J_K']} J/K、{ACCEPTANCE['mbsu_block_C_kJ_K_one_decimal']} kJ/K "
                   f"与 {ACCEPTANCE['radiator_panel_C_per_area_kJ_m2K_one_decimal']} {AREAL_KILO_UNIT}")
        base = "，".join([
            stated("第 4.5 节算例热容", num_text(m.get("design_4_5_example_C_J_K"), ".0f", "J/K")),
            stated("MBSU 方块热容", with_kilo("mbsu_block_C_J_K", ".2f", "J/K", "kJ/K")),
            stated("散热器面板单位面积热容",
                   with_kilo("radiator_panel_C_per_area_J_m2K", ".0f", AREAL_UNIT, AREAL_KILO_UNIT)),
        ])
        sentences.append(says("s1_acceptance", base + f"，三项与验收值 {targets} 一致。",
                              base + f"，三项中有与验收值 {targets} 不一致的项。",
                              "第 4.5 节算例、MBSU 方块与散热器面板的热容检查没有全部执行。",
                              "第 4.5 节算例、MBSU 方块与散热器面板的热容检查未执行。"))
        sentences.append(says(
            "s1_layout",
            f"C_J_K 与 R_K_W 按 S、J、C、B、D、R 与 SR、JC、CR、BR、DR 的顺序保存，太阳能板与散热板的 {SURFACE_COUNT} "
            "个表面按资产表面顺序装配了面积、法向、吸收率与发射率。",
            "C_J_K 与 R_K_W 的维数和顺序或表面参数的装配检查有未通过的项。",
            "C_J_K 与 R_K_W 的维数和顺序或表面参数的装配检查没有全部执行。",
            "C_J_K 与 R_K_W 的维数和顺序以及表面参数的装配检查未执行。"))

        facts = (f"overrides 把电池单体质量由 {num_text(MASS_OLD, 'g', 'kg')} 改为 {num_text(MASS_NEW, 'g', 'kg')}，"
                 f"把 BR 接触热阻由 {num_text(CONTACT_OLD, 'g', 'K/W')} 改为 {num_text(CONTACT_NEW, 'g', 'K/W')}")
        base = (facts + "，重新装配后"
                + change("电池热容", num_text(m.get("C_B_baseline_J_K"), ".1f", "J/K"),
                         num_text(m.get("C_B_override_J_K"), ".1f", "J/K")) + "，"
                + change("BR 热阻", num_text(m.get("R_BR_baseline_K_W"), ".4f", "K/W"),
                         num_text(m.get("R_BR_override_K_W"), ".4f", "K/W")) + "，"
                + stated("覆盖后十一项与手算表的最大相对误差",
                         sci_text(largest(m.get("max_rel_error_C_override"), m.get("max_rel_error_R_override")))))
        sentences.append(says(
            "s2_override",
            base + "，满足验收限值，其余九项保持资产参数集的值，已应用的覆盖值及其新旧值与来源记入 provenance，"
            "调用前后输入记录逐项相同。",
            base + "，覆盖值检查有未通过的项。",
            facts + "，重新装配后的覆盖值检查没有全部执行。",
            "加入 overrides 后的重新装配未执行。"))
        sentences.append(rejection_clause(group_specs("override"), f"{len(group_specs('override'))} 项异常覆盖值") + "。")

        base = "，".join([
            stated("热管等效路径 CR 的热阻", num_text(m.get("R_CR_K_W"), ".3f", "K/W")),
            f"液冷等效路径 DR 的总热阻不含接触部分时叠加 {num_text(DR_CONTACT, 'g', 'K/W')} 接触热阻，"
            + stated("热阻", num_text(m.get("R_DR_K_W"), ".3f", "K/W")),
            "已含接触部分时直接取总热阻，" + stated("热阻", num_text(m.get("R_DR_total_included_K_W"), ".3f", "K/W")),
        ])
        sentences.append(says(
            "s3",
            base + "，三项均与手算值一致，没有重复叠加已包含的接触热阻，通过覆盖值给 CR 再加接触热阻时给出 "
            "ThermalConfigurationError。",
            base + "，等效路径检查有未通过的项。",
            "热管与液冷等效路径的检查没有全部执行。", "热管与液冷等效路径的检查未执行。"))

        listed = group_specs("case")
        sentences.append(rejection_clause(listed, f"案例列出的 {len(listed)} 项异常输入") + "。")
        sizes = {name: len(group_specs(name)) for name in SUPPLEMENTARY_GROUPS}
        subject = (f"按第 5.2 节补充的 {sizes['missing']} 项缺失数据、{sizes['nonfinite']} 项非有限值、"
                   f"{sizes['surface']} 项表面面积、光学参数或单位法向不符合 T4 与第 5.1 节要求的输入以及 "
                   f"{sizes['duplicate']} 项重复连接")
        sentences.append(rejection_clause(group_specs(*SUPPLEMENTARY_GROUPS), subject) + "。")
        sentences.append(says("s4_boundary", "吸收率与发射率取边界值 0 与 1 时正常装配，表面记录保存给定值。",
                              "吸收率与发射率取边界值 0 与 1 时的装配检查未通过。",
                              "吸收率与发射率取边界值 0 与 1 时的装配检查没有全部执行。",
                              "吸收率与发射率取边界值 0 与 1 时的装配检查未执行。"))

        good = [spec for spec in REJECTIONS if spec.check_name in present and spec.check_name not in failed_names]
        if good:
            with_fields = sum(bool(spec.fields) for spec in good)
            record_only = len(good) - with_fields
            lead = (f"上述 {len(REJECTIONS)} 项输入的报错" if len(good) == len(REJECTIONS)
                    else f"给出符合要求报错的 {len(good)} 项输入，其报错")
            text = (f"{lead}都指出出错的组件、材料、表面、连接或覆盖值记录，其中由字段取值、字段缺失或多余字段引起的 "
                    f"{with_fields} 项同时指出该字段")
            if record_only:
                text += f"，其余 {record_only} 项属于记录重复、记录缺失或名称无法对应，报错指出相应记录"
            text += "，同一输入两次调用的报错相同"
            total, ok, _, _ = counts(group_specs("missing"))
            if ok == total:
                text += "，缺失数据时没有生成默认器件参数"
            sentences.append(text + "。")

        sentences.append(says(
            "s5_provenance",
            "ThermalParameters 的 provenance 记录了单位与节点、路径顺序，逐节点记录了热容、材料份额、解析后的质量、比热与"
            "数据来源，逐路径记录了热阻、计算方法、解析后的输入与数据来源，并记录了七个实例的资产标识、资产版本与适用温区，"
            "表面所属实例、解析后的表面参数与来源，以及覆盖值的目标、新旧值与来源。",
            "provenance 中解析后的数值、单位、资产版本或数据来源的记录检查有未通过的项。",
            "provenance 记录检查没有全部执行。", "provenance 记录检查未执行。"))
        base = stated("装配期间创建的 ThermalState",
                      num_text(m.get("thermal_state_constructions_during_assembly"), "d", "个"))
        sentences.append(says(
            "s5_temperature",
            base + "，ThermalParameters 的字段与其余内部属性中与温度有关的数值只有各实例声明的适用温区边界，不含运行温度，"
            "重复装配得到相同结果。",
            base + "，运行温度或重复装配检查有未通过的项。",
            "运行温度与重复装配检查没有全部执行。", "运行温度与重复装配检查未执行。"))

    failed_list = [c["name"] for c in checks if not c["passed"]]
    missing_total = sum(len(names) for names in unexecuted.values())
    if checks:
        if not failed_list and not missing_total:
            sentences.append(f"共 {len(checks)} 项检查，全部通过，满足验收判据。")
        else:
            final = f"共 {len(checks)} 项检查，{len(checks) - len(failed_list)} 项通过"
            if failed_list:
                final += f"，{len(failed_list)} 项未通过"
            if missing_total:
                final += f"，另有 {missing_total} 项计划检查未执行"
            sentences.append(final + ("，未满足验收判据。" if failed_list else "，验收判据没有全部得到检验。"))
    summary = re.sub(rf"(?<={_CJK}) +(?={_CJK})", "", "".join(sentences))

    parts = []
    if failed_list:
        parts.append("以下检查未通过：" + "；".join(failed_list) + "。")
    not_run = [STEP_WORDS[label] for label in STEP_FUNCTIONS if not executed[label]]
    if not_run:
        parts.append("以下步骤未执行：" + "、".join(not_run) + "。")
    unfinished = [label for label in STEP_FUNCTIONS if executed[label] and unexecuted[label]]
    if unfinished:
        parts.append("以下步骤没有执行完成：" + "、".join(STEP_WORDS[label] for label in unfinished)
                     + "。其中未执行的检查为：" + "；".join(name for label in unfinished for name in unexecuted[label]) + "。")
    anomalies = "".join(parts) or "无"

    if not checks:
        status = "not_run"
    elif missing_total:
        status = "partial"
    else:
        status = None
    return summary, anomalies, status


def write_case_summary(case_record) -> None:
    """Write summary_cn, anomalies_cn and the status; a failure here leaves a fallback text, never a pass text."""

    checks = list(case_record.checks)
    failed = [c["name"] for c in checks if not c["passed"]]
    case_record.metric("planned_checks_per_step", {label: len(names) for label, names in PLANNED.items()})
    case_record.summary(FALLBACK_SUMMARY)
    case_record.anomalies(FALLBACK_ANOMALY + ("以下检查未通过：" + "；".join(failed) + "。" if failed else ""))
    summary, anomalies, status = compose_case_text(checks, case_record.metrics)
    problems = text_rule_violations(summary) + text_rule_violations(anomalies)
    assert not problems, f"the Chinese result text breaks the report rules: {problems}"
    case_record.summary(summary)
    case_record.anomalies(anomalies)
    if status is not None:
        case_record.status(status)


_SESSION: dict[str, Any] = {"record": None, "summary_attempted": False}


@pytest.fixture(autouse=True)
def _remember_case_record(case_record):
    _SESSION["record"] = case_record
    yield


@pytest.fixture(scope="module", autouse=True)
def _summary_when_summary_test_not_run():
    """If test_step6_summary was deselected, the summary is still written after the last test of this module."""

    yield
    if _SESSION["record"] is not None and not _SESSION["summary_attempted"]:
        write_case_summary(_SESSION["record"])


def test_step6_summary(case_record):
    """Chinese summary and anomaly record of the case from the checks and metrics recorded above."""

    _SESSION["summary_attempted"] = True
    write_case_summary(case_record)
