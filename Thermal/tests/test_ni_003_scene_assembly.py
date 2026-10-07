"""NI-003 资产与场景装配: SimReady assets and the Sat01 scene against hand calculation and thermal design 9.3, 9.4.

Design basis: thermal design report 9.3 (table 9 and the Sat01 instances), 9.4 (parameter configuration), 3.2 and
table 1 (node extents), 4.5 (T5), 5.1 (instance_map and ports); Power design 9.3 (shared instance identifiers, two
battery instances keep separate state). The steps follow CASES['NI-003'] of Thermal/test_report/build_test_report_cn.py:

1. assemble the scene, read areas, masses and capacitances and compare them with the hand calculation from the
   physical sizes of the assets;
2. check that a display-scaled bounding box is not taken as the physical size;
3. check that parameter_overrides take precedence over the asset parameter sets and that a material, geometry or
   installation change recalculates the affected capacitances, areas and resistances;
4. check that Controller01 and PDU01 share D, that the battery's BR path leads to the radiator, that Power and Thermal
   use the same instance identifiers and that material mass is counted once;
5. check that two instances keep independent temperatures and battery states, that an unregistered model_id is
   rejected, that nothing is executed from USD and that the PV efficiency does not exceed the absorptivity of the
   same surface.

Acceptance: area and mass relative error at most 0.1 %; every check of steps 2 to 5 passes.

References never come from the code under test: the hand calculation table tests/data/ni_003/hand_calc.json (part
sizes documented in the USD doc strings and asset descriptions, cross-checked against an independent regular
expression parse of the .usda text), the asset and scene JSON files read directly, the design report rules, an
independent quaternion rotation, file hashes, fresh-interpreter reruns and a Python audit hook probe.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import math
import subprocess
import sys
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sdtwin_sim import coupled as cp
from sdtwin_sim import scene as sc
from thermal import ThermalState, assemble_thermal_parameters
from thermal.types import NODE_ORDER, PATH_ORDER

pytestmark = pytest.mark.case("NI-003")

TESTS_DIR = Path(__file__).resolve().parent
DATA = TESTS_DIR / "data" / "ni_003"
SIMREADY = TESTS_DIR / "data" / "simready"
SCENES = DATA / "scenes"
SAT01 = SIMREADY / "sat01_scene.json"
SCENE_SOURCE = TESTS_DIR.parent / "sdtwin_sim" / "scene.py"


def _load_support():
    spec = importlib.util.spec_from_file_location("ni003_support", DATA / "ni003_support.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SUP = _load_support()
TABLE = SUP.load_hand_calc()
LIMIT = float(TABLE["acceptance"]["relative_error_limit"])  # case acceptance: 0.1 %
DESIGN = TABLE["design"]
REF = SUP.reference_values(TABLE)
NORMAL_TOL = 1e-12
BBOX_TOL = 1e-6  # USD extents are float32; the display box is compared at this relative level
RUN_TIMEOUT_S = 600


# --------------------------------------------------------------------------------------------- helpers


class Step:
    """Records every check of one step through case_record; one assertion at the end shows any failure."""

    def __init__(self, case_record, label: str) -> None:
        self.case_record = case_record
        self.label = label
        self.failed: list[str] = []

    def check(self, name: str, expected: Any, actual: Any, passed: bool) -> bool:
        full = f"{self.label} {name}"
        self.case_record.check(full, text(expected), text(actual), bool(passed))
        if not passed:
            self.failed.append(full)
        return bool(passed)

    def finish(self) -> None:
        assert not self.failed, "failed checks: " + "; ".join(self.failed)


def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return [plain(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    return value


def text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(plain(value), ensure_ascii=False, default=str)


def g(value: Any) -> str:
    return f"{float(value):.10g}"


def sci(value: float) -> str:
    return f"{float(value):.2e}"


def attempt(function: Callable[[], Any]) -> tuple[bool, str, str, Any]:
    """(accepted, error type, message, result) of one call."""

    try:
        return True, "", "", function()
    except Exception as exc:  # noqa: BLE001  (the error type is checked by the caller)
        return False, type(exc).__name__, str(exc), None


@lru_cache(maxsize=None)
def assembled(scene_path: str):
    assembly = sc.assemble_scene(scene_path)
    return assembly, assemble_thermal_parameters(*assembly.thermal_inputs())


def baseline():
    return assembled(str(SAT01))


def module_values(params) -> dict[str, float]:
    """Flat values of a ThermalParameters: C, R, areas, normals, optics and every material portion mass."""

    values: dict[str, float] = {}
    for node, value in zip(NODE_ORDER, params.C_J_K):
        values[f"C {node}"] = float(value)
    for path, value in zip(PATH_ORDER, params.R_K_W):
        values[f"R {path}"] = float(value)
    for surface in params.surfaces:
        sid = surface.surface_id
        values[f"A {sid}"] = float(surface.area_m2)
        values[f"alpha {sid}"] = float(surface.absorptivity)
        values[f"eps {sid}"] = float(surface.emissivity)
        for k in range(3):
            values[f"n{k} {sid}"] = float(surface.normal_body[k])
    capacitance = params.provenance["capacitance"]
    for node in NODE_ORDER:
        for portion in capacitance[node]["portions"]:
            values[f"m {portion['material_id']}"] = float(portion["mass_kg"])
    return values


def reference_flat(ref: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    for node in NODE_ORDER:
        values[f"C {node}"] = ref["capacitance"][node]
    for path in PATH_ORDER:
        values[f"R {path}"] = ref["resistance"][path]
    for sid, area in ref["areas"].items():
        values[f"A {sid}"] = area
        values[f"alpha {sid}"], values[f"eps {sid}"] = ref["optics"][sid]
        for k in range(3):
            values[f"n{k} {sid}"] = ref["normals"][sid][k]
    for key, mass in ref["masses"].items():
        values[f"m {key}"] = mass
    return values


def value_error(key: str, value: float, reference: float) -> float:
    if key.startswith("n"):
        return abs(value - reference)
    return SUP.rel_err(value, reference)


def value_limit(key: str) -> float:
    return NORMAL_TOL if key.startswith("n") else LIMIT


BASE_REF_FLAT = reference_flat(REF)


def variant_report(params, ref: dict, base_params) -> dict:
    """Compare a variant with its hand reference and with the baseline module values.

    Affected items are those whose hand reference differs from the baseline hand reference; they must match the new
    reference and differ from the baseline result. Every other item must keep the baseline result bit for bit.
    """

    values = module_values(params)
    base_values = module_values(base_params)
    expected = reference_flat(ref)
    missing = sorted(set(expected) ^ set(values))
    common = sorted(set(expected) & set(values))
    affected = [k for k in common if expected[k] != BASE_REF_FLAT.get(k)]
    errors = {k: value_error(k, values[k], expected[k]) for k in common}
    bad = {k: errors[k] for k in common if errors[k] > value_limit(k)}
    unaffected_changed = [k for k in common if k not in affected and values[k] != base_values.get(k)]
    affected_unchanged = [k for k in affected if values[k] == base_values.get(k)]
    max_affected = max((errors[k] for k in affected if not k.startswith("n")), default=0.0)
    return {"missing": missing, "affected": affected, "bad": bad, "unaffected_changed": unaffected_changed,
            "affected_unchanged": affected_unchanged, "max_affected_rel_error": max_affected,
            "values": {k: values[k] for k in affected}, "reference": {k: expected[k] for k in affected},
            "baseline": {k: base_values.get(k) for k in affected}}


def report_ok(report: dict) -> bool:
    return not (report["missing"] or report["bad"] or report["unaffected_changed"] or report["affected_unchanged"])


def report_actual(report: dict) -> dict:
    return {"重算项": {k: f"{g(report['baseline'][k])} 变为 {g(report['values'][k])} 手算 {g(report['reference'][k])}"
                      for k in report["affected"]},
            "重算项最大相对误差": sci(report["max_affected_rel_error"]),
            "超限项": report["bad"], "缺失项": report["missing"],
            "未受影响却改变的项": report["unaffected_changed"], "应重算却未变的项": report["affected_unchanged"]}


def instance_record(scene_json: dict, instance_id: str) -> dict:
    return next(x for x in scene_json["instances"] if x["instance_id"] == instance_id)


def asset_json_of(scene_path: Path, instance_id: str) -> tuple[Path, dict]:
    scene_json = SUP.read_json(scene_path)
    path = (scene_path.parent / instance_record(scene_json, instance_id)["asset_ref"]).resolve()
    return path, SUP.read_json(path)


def usd_of(asset_path: Path, asset: dict) -> dict:
    return SUP.parse_usda((asset_path.parent / asset["geometry_uri"]).resolve())


def table_material(table: dict, instance_id: str, material_id: str) -> dict:
    return next(m for m in table["instances"][instance_id]["materials"] if m["material_id"] == material_id)


def table_surface(table: dict, instance_id: str, surface_id: str) -> dict:
    return next(s for s in table["instances"][instance_id]["surfaces"] if s["surface_id"] == surface_id)


def rejection_check(step: Step, name: str, scene_path: Path, error_type: type, words: tuple[str, ...],
                    call: Callable[[Path], Any] | None = None) -> tuple[bool, str]:
    """Expect the scene to be rejected with ``error_type`` and a message that names every word in ``words``."""

    function = call or (lambda p: sc.assemble_scene(p))
    accepted, kind, message, _ = attempt(lambda: function(scene_path))
    named = [w for w in words if w not in message]
    allowed = {error_type.__name__} | {sub.__name__ for sub in _subclasses(error_type)}
    passed = (not accepted) and kind in allowed and not named
    step.check(name, f"拒绝，{error_type.__name__}，报错指出 {', '.join(words)}",
               "接受" if accepted else f"{kind}: {message[:600]}" + (f"；未指出 {named}" if named else ""), passed)
    return passed, message


def _subclasses(cls: type) -> list[type]:
    found = []
    for sub in cls.__subclasses__():
        found.append(sub)
        found.extend(_subclasses(sub))
    return found


# --------------------------------------------------------------------------------------------- preconditions


def test_preconditions_table9_records_and_paths(case_record):
    """前提与输入: the seven Sat01 assets carry the table 9 fields, the loader reads them, paths are /World/Sat01/<id>."""

    from pxr import Usd, UsdGeom

    step = Step(case_record, "前提")
    scene_json = SUP.read_json(SAT01)
    ids = [x["instance_id"] for x in scene_json["instances"]]
    step.check("Sat01 下七个实例", DESIGN["instances"], ids,
               len(ids) == 7 and sorted(ids) == sorted(DESIGN["instances"]))

    required = ("asset_id", "asset_version", "geometry_uri", "capabilities", "ports", "provenance")
    missing: dict[str, list[str]] = {}
    for item in scene_json["instances"]:
        _, asset = asset_json_of(SAT01, item["instance_id"])
        gaps = [field for field in required if field not in asset]
        for capability in asset.get("capabilities", []):
            gaps += [f"capabilities.{f}" for f in ("domain", "model_id", "parameter_set") if f not in capability]
        if not any(c.get("domain") == "thermal" for c in asset.get("capabilities", [])):
            gaps.append("thermal capability")
        if not asset.get("ports"):
            gaps.append("ports")
        if not all(k in asset.get("provenance", {}) for k in ("status", "note")):
            gaps.append("provenance.status note")
        if gaps:
            missing[item["instance_id"]] = gaps
    step.check("七个资产登记表 9 的八个字段",
               "asset_id、asset_version、geometry_uri、domain、model_id、parameter_set、ports、provenance 齐全",
               missing or "七个资产全部齐全", not missing)

    scene = sc.load_scene(SAT01)
    assembly, _ = baseline()
    prov = assembly.provenance
    mismatches: list[str] = []
    for item in scene_json["instances"]:
        iid = item["instance_id"]
        asset_path, asset = asset_json_of(SAT01, iid)
        geometry_path = (asset_path.parent / asset["geometry_uri"]).resolve()
        record = prov["assets"].get(asset["asset_id"])
        models = {c["domain"]: c["model_id"] for c in asset["capabilities"]}
        if record is None:
            mismatches.append(f"{iid}: asset {asset['asset_id']} not in provenance")
            continue
        for label, got, want in (("asset_version", record["asset_version"], asset["asset_version"]),
                                 ("geometry_uri", record["geometry_uri"], asset["geometry_uri"]),
                                 ("sha256", record["sha256"], SUP.sha256(asset_path)),
                                 ("geometry_sha256", record["geometry_sha256"], SUP.sha256(geometry_path)),
                                 ("models", plain(record["models"]), models),
                                 ("asset_ref", prov["instances"][iid]["asset_ref"], item["asset_ref"]),
                                 ("asset_id", prov["instances"][iid]["asset_id"], asset["asset_id"])):
            if got != want:
                mismatches.append(f"{iid} {label}: {got} != {want}")
        loaded = scene.asset_of(iid)
        for capability in asset["capabilities"]:
            got = loaded.capability(capability["domain"])
            if got is None or got.model_id != capability["model_id"] or plain(got.parameter_set) != capability[
                    "parameter_set"]:
                mismatches.append(f"{iid} capability {capability['domain']} differs from the asset file")
        if [(p.name, p.kind, p.unit) for p in loaded.ports] != [(p["name"], p["kind"], p["unit"]) for p in
                                                                  asset["ports"]]:
            mismatches.append(f"{iid} ports differ from the asset file")
        if plain(loaded.provenance) != asset["provenance"]:
            mismatches.append(f"{iid} provenance differs from the asset file")
    for field in ("parameter_overrides", "initial_state", "connections"):
        if plain(getattr(scene, field)) != scene_json[field]:
            mismatches.append(f"scene {field} differs from the scene file")
    if prov["scene"]["sha256"] != SUP.sha256(SAT01):
        mismatches.append("scene sha256 differs")
    step.check("装配读取表 9 的资产记录与场景实例和场景配置",
               "provenance 的版本、几何、文件哈希、模型标识、端口与场景配置等于文件内容",
               mismatches or "七个资产、七个实例与三项场景配置全部一致", not mismatches)

    paths = dict(assembly.instance_paths)
    expected_paths = {iid: f"{DESIGN['root_prim_path']}/{iid}" for iid in DESIGN["instances"]}
    step.check("七个实例几何路径为 /World/Sat01/实例标识", expected_paths, paths, paths == expected_paths)

    stage = sc.compose_stage(SAT01)
    problems: list[str] = []
    for item in scene_json["instances"]:
        iid = item["instance_id"]
        prim = stage.GetPrimAtPath(f"{DESIGN['root_prim_path']}/{iid}")
        if not prim or not prim.IsValid():
            problems.append(f"{iid}: no prim")
            continue
        asset_path, asset = asset_json_of(SAT01, iid)
        meshes = sorted(p.GetName() for p in Usd.PrimRange(prim) if p.IsA(UsdGeom.Mesh))
        expected_meshes = sorted(usd_of(asset_path, asset)["meshes"])
        if prim.GetName() != iid or str(prim.GetParent().GetPath()) != DESIGN["root_prim_path"]:
            problems.append(f"{iid}: name or parent differs")
        if meshes != expected_meshes:
            problems.append(f"{iid}: meshes {meshes} != {expected_meshes}")
        if prim.GetCustomDataByKey("sdtwin:asset_id") != asset["asset_id"]:
            problems.append(f"{iid}: asset_id custom data differs")
    step.check("合成舞台七个实例 prim 的名称、父路径、引用几何与资产标识",
               "名称等于实例标识，父路径为 /World/Sat01，网格与资产 USD 一致",
               problems or "七个实例全部符合", not problems)

    worst = 0.0
    details = {}
    for key, part in TABLE["parts"].items():
        geometry, mesh = key.split("/")
        usd = SUP.parse_usda(SIMREADY / "geometry" / geometry)
        extent = np.array(usd["meshes"][mesh]["extent"], dtype=float)
        size = (extent[1] - extent[0]) * usd["meters_per_unit"]  # authored axes, before any rotation op
        error = max(SUP.rel_err(a, b) for a, b in zip(size, part["size_m"]))
        error = max(error, SUP.rel_err(usd["meters_per_unit"], part["meters_per_unit"]))
        worst = max(worst, error)
        details[key] = f"{[g(v) for v in size]} m, metersPerUnit {g(usd['meters_per_unit'])}"
    case_record.metric("usd_documented_size_max_rel_diff", worst)
    step.check("八个部件的 USD 包围尺寸乘 metersPerUnit 等于文档物理尺寸", "相对差不超过 1×10⁻⁹",
               {"最大相对差": sci(worst), **details}, worst <= 1e-9)
    step.finish()


# --------------------------------------------------------------------------------------------- step 1


def test_step1_areas_masses_capacitances(case_record):
    """Areas, material masses, node masses and capacitances of Sat01 against the hand calculation."""

    step = Step(case_record, "步骤1")
    assembly, params = baseline()

    area_errors = {}
    area_text = {}
    for surface in params.surfaces:
        reference = REF["areas"].get(surface.surface_id)
        area_errors[surface.surface_id] = SUP.rel_err(surface.area_m2, reference) if reference else math.inf
        area_text[surface.surface_id] = f"{g(surface.area_m2)} m² 手算 {g(reference)} m²"
    max_area = max(area_errors.values())
    step.check("四个外露表面面积与手算比较", f"面积相对误差不超过 {LIMIT:.1%}",
               {**area_text, "最大相对误差": sci(max_area)},
               set(area_errors) == set(REF["areas"]) and max_area <= LIMIT)

    capacitance = params.provenance["capacitance"]
    portions = {p["material_id"]: p for node in NODE_ORDER for p in capacitance[node]["portions"]}
    mass_errors = {k: SUP.rel_err(portions[k]["mass_kg"], REF["masses"][k]) for k in REF["masses"] if k in portions}
    missing = sorted(set(REF["masses"]) ^ set(portions))
    geometric = {k: f"{g(portions[k]['mass_kg'])} kg 手算 {g(REF['masses'][k])} kg" for k in portions
                 if k in REF["masses"] and "mass_kg" not in table_material(TABLE, *k.split("/"))}
    max_mass = max(mass_errors.values())
    step.check("十四个材料部分质量与手算比较", f"质量相对误差不超过 {LIMIT:.1%}",
               {"最大相对误差": sci(max_mass), "由几何尺寸与密度得到的质量": geometric, "缺失或多余": missing},
               not missing and max_mass <= LIMIT)

    node_mass = {n: math.fsum(p["mass_kg"] for p in capacitance[n]["portions"]) for n in NODE_ORDER}
    node_mass_errors = {n: SUP.rel_err(node_mass[n], REF["node_mass"][n]) for n in NODE_ORDER}
    step.check("六个节点质量与手算比较", f"质量相对误差不超过 {LIMIT:.1%}",
               {n: f"{g(node_mass[n])} kg 手算 {g(REF['node_mass'][n])} kg" for n in NODE_ORDER},
               max(node_mass_errors.values()) <= LIMIT)

    c_errors = {n: SUP.rel_err(params.C_J_K[i], REF["capacitance"][n]) for i, n in enumerate(NODE_ORDER)}
    step.check("六个节点热容与手算比较", f"热容相对误差不超过 {LIMIT:.1%}",
               {n: f"{g(params.C_J_K[i])} J/K 手算 {g(REF['capacitance'][n])} J/K"
                for i, n in enumerate(NODE_ORDER)} | {"最大相对误差": sci(max(c_errors.values()))},
               max(c_errors.values()) <= LIMIT)

    r_errors = {p: SUP.rel_err(params.R_K_W[i], REF["resistance"][p]) for i, p in enumerate(PATH_ORDER)}
    step.check("五条连接热阻与手算比较", f"热阻相对误差不超过 {LIMIT:.1%}",
               {p: f"{g(params.R_K_W[i])} K/W 手算 {g(REF['resistance'][p])} K/W"
                for i, p in enumerate(PATH_ORDER)} | {"最大相对误差": sci(max(r_errors.values()))},
               max(r_errors.values()) <= LIMIT)

    normal_errors = {}
    optics_ok = True
    for surface in params.surfaces:
        normal_errors[surface.surface_id] = float(np.max(np.abs(np.asarray(surface.normal_body)
                                                                - np.asarray(REF["normals"][surface.surface_id]))))
        optics_ok &= (surface.absorptivity, surface.emissivity) == REF["optics"][surface.surface_id]
    rotated = {}
    for iid in ("SolarArray01", "Radiator01"):
        q = instance_record(SUP.read_json(SAT01), iid)["mounting"]["body_from_asset_xyzw"]
        matrix = SUP.quaternion_matrix(q)
        rotated[iid] = {"+Z": ((matrix @ [0.0, 0.0, 1.0]).round(12) + 0.0).tolist(),
                        "-Z": ((matrix @ [0.0, 0.0, -1.0]).round(12) + 0.0).tolist()}
    independent = {f"{iid}/{'front' if face == '+Z' else 'back'}": vec for iid, faces in rotated.items()
                   for face, vec in faces.items()}
    independent_ok = all(np.max(np.abs(np.asarray(independent[k]) - np.asarray(REF["normals"][k]))) <= NORMAL_TOL
                         for k in independent)
    step.check("外露表面法线与光学参数", "法线等于场景说明的 +X、−X、−Y、+Y，与独立四元数旋转一致，吸收率与发射率等于资产值",
               {"法线最大偏差": sci(max(normal_errors.values())), "独立旋转": independent,
                "光学参数一致": optics_ok},
               max(normal_errors.values()) <= NORMAL_TOL and optics_ok and independent_ok)

    max_area_mass = max(max_area, max_mass, max(node_mass_errors.values()))
    case_record.metric("step1_max_rel_error_area", max_area)
    case_record.metric("step1_max_rel_error_mass", max(max_mass, max(node_mass_errors.values())))
    case_record.metric("step1_max_rel_error_C", max(c_errors.values()))
    case_record.metric("step1_max_rel_error_R", max(r_errors.values()))
    case_record.metric("step1_C_J_K", {n: float(params.C_J_K[i]) for i, n in enumerate(NODE_ORDER)})
    case_record.metric("step1_R_K_W", {p: float(params.R_K_W[i]) for i, p in enumerate(PATH_ORDER)})
    case_record.metric("step1_node_mass_kg", node_mass)
    case_record.metric("step1_total_mass_kg", math.fsum(node_mass.values()))
    case_record.metric("step1_areas_m2", {s.surface_id: float(s.area_m2) for s in params.surfaces})
    step.check("验收 面积与质量相对误差", f"不超过 {LIMIT:.1%}", f"最大相对误差 {sci(max_area_mass)}",
               max_area_mass <= LIMIT)
    step.finish()


# --------------------------------------------------------------------------------------------- step 2


def _bbox_report(scene_path: Path) -> dict:
    """Display boxes of every instance from the assembly provenance against the independent display-box reference."""

    assembly, _ = assembled(str(scene_path))
    scene_json = SUP.read_json(scene_path)
    report = {}
    for item in scene_json["instances"]:
        iid = item["instance_id"]
        asset_path, asset = asset_json_of(scene_path, iid)
        usd = usd_of(asset_path, asset)
        scale = item.get("display_transform", {}).get("scale", [1.0, 1.0, 1.0])
        q = item["mounting"]["body_from_asset_xyzw"]
        reference = SUP.reference_display_bbox(usd, q, scale)
        physical = np.abs(SUP.quaternion_matrix(q)) @ SUP.asset_box_m(usd)
        module = np.asarray(assembly.provenance["instances"][iid]["display_bbox_size_world"], dtype=float)
        report[iid] = {"scale": scale, "module": module, "reference": reference, "physical": physical,
                       "error": float(np.max(np.abs(module - reference) / reference))}
    return report


def test_step2_display_scale_not_physical(case_record):
    """A display-scaled bounding box is never taken as the physical size."""

    step = Step(case_record, "步骤2")
    _, base_params = baseline()
    base_values = module_values(base_params)

    for label, scene_path in (("示例显示缩放场景", SIMREADY / "sat01_scene_display_scaled.json"),
                              ("七个实例全部显示缩放场景", SCENES / "sat01_display_scaled_all.json")):
        _, params = assembled(str(scene_path))
        values = module_values(params)
        differing = sorted(k for k in set(values) | set(base_values) if values.get(k) != base_values.get(k))
        scales = {x["instance_id"]: x["display_transform"].get("scale") for x in SUP.read_json(scene_path)["instances"]
                  if "scale" in x.get("display_transform", {})}
        step.check(f"{label} 物理参数与 Sat01 逐位相同", "热容、热阻、面积、法线、光学参数与各材料质量逐位不变",
                   {"显示缩放": scales, "改变的量": differing, "比较项数": len(values)}, not differing)

    unscaled = _bbox_report(SAT01)
    worst_unscaled = max(r["error"] for r in unscaled.values())
    step.check("无显示缩放时显示包围盒等于物理尺寸", f"相对差不超过 {BBOX_TOL:g}",
               {iid: [g(v) for v in r["module"]] for iid, r in unscaled.items()} | {"最大相对差": sci(worst_unscaled)},
               worst_unscaled <= BBOX_TOL)

    scaled = _bbox_report(SCENES / "sat01_display_scaled_all.json")
    worst_scaled = max(r["error"] for r in scaled.values())
    step.check("显示缩放后显示包围盒按缩放比例改变", f"等于物理尺寸乘显示缩放后的独立计算值，相对差不超过 {BBOX_TOL:g}",
               {iid: f"显示 {[g(v) for v in r['module']]} m 物理 {[g(v) for v in r['physical']]} m"
                for iid, r in scaled.items()} | {"最大相对差": sci(worst_scaled)},
               worst_scaled <= BBOX_TOL)

    _, scaled_params = assembled(str(SCENES / "sat01_display_scaled_all.json"))
    counterfactual = {}
    ratios = []
    discriminating = True
    for surface in scaled_params.surfaces:
        iid = surface.surface_id.split("/")[0]
        box = scaled[iid]["module"]
        axis = int(np.argmax(np.abs(np.asarray(surface.normal_body))))
        box_area = float(np.prod([box[k] for k in range(3) if k != axis]))
        ratio = box_area / REF["areas"][surface.surface_id]
        ratios.append(ratio)
        counterfactual[surface.surface_id] = (f"装配面积 {g(surface.area_m2)} m² 手算 {g(REF['areas'][surface.surface_id])} "
                                              f"m²，按显示包围盒为 {g(box_area)} m²，比值 {g(ratio)}")
        discriminating &= abs(ratio - 1.0) > LIMIT and SUP.rel_err(surface.area_m2, REF["areas"][surface.surface_id]) <= LIMIT
    capacitance = scaled_params.provenance["capacitance"]
    mass_ratio = {}
    for key in ("Compute01/pcb_laminate", "Compute01/copper_spreader", "ColdPlate01/plate_al6061",
                "Radiator01/facesheet_al6061"):
        iid = key.split("/")[0]
        scale = np.asarray(scaled[iid]["scale"], dtype=float)
        portion = next(p for n in NODE_ORDER for p in capacitance[n]["portions"] if p["material_id"] == key)
        mass_ratio[key] = (f"装配质量 {g(portion['mass_kg'])} kg 手算 {g(REF['masses'][key])} kg，"
                           f"按显示缩放体积为 {g(REF['masses'][key] * float(np.prod(scale)))} kg")
        discriminating &= SUP.rel_err(portion["mass_kg"], REF["masses"][key]) <= LIMIT and abs(np.prod(scale) - 1.0) > LIMIT
    case_record.metric("step2_display_scaled_area_ratio", {k: v for k, v in counterfactual.items()})
    case_record.metric("step2_max_bbox_area_ratio", max(ratios))
    step.check("显示包围盒推得的面积与质量和装配值不同，装配值等于手算", "缩放后包围盒推得的值偏离手算，装配值的相对误差不超过 0.1%",
               {"面积": counterfactual, "质量": mass_ratio}, discriminating)

    usd = SUP.parse_usda(DATA / "geometry" / "radiator_panel_display_scaled.usda")
    root_scale = usd["root_ops"].get("scale")
    step.check("显示缩放资产的默认 prim 带缩放", "独立解析得到默认 prim 缩放 2、2、2", root_scale,
               root_scale == [2.0, 2.0, 2.0])
    rejection_check(step, "显示缩放资产被拒绝", SCENES / "sat01_display_scaled_asset.json", sc.SceneError,
                    ("radiator_panel_display_scaled", "scale"), lambda p: sc.load_scene(p))
    rejection_check(step, "部件带缩放的示例资产被拒绝", SIMREADY / "sat01_scene_invalid_scaled_geometry.json",
                    sc.SceneError, ("invalid_scaled_panel", "scale"), lambda p: sc.load_scene(p))

    mm_scene = SCENES / "sat01_radiator_mm.json"
    _, mm_params = assembled(str(mm_scene))
    mm_values = module_values(mm_params)
    mm_errors = {k: value_error(k, mm_values[k], base_values[k]) for k in base_values if k in mm_values}
    mm_missing = sorted(set(base_values) ^ set(mm_values))
    mm_usd = SUP.parse_usda(DATA / "geometry" / "radiator_panel_mm.usda")
    mm_box = _bbox_report(mm_scene)["Radiator01"]
    worst_mm = max(v for k, v in mm_errors.items() if not k.startswith("n"))
    step.check("毫米单位资产的物理参数等于米单位资产", "metersPerUnit 0.001，面积、质量与热容相对差不超过 1×10⁻¹²，显示包围盒为米制物理尺寸",
               {"metersPerUnit": mm_usd["meters_per_unit"], "包围尺寸": mm_usd["meshes"]["Panel"]["extent"],
                "最大相对差": sci(worst_mm), "显示包围盒": [g(v) for v in mm_box["module"]], "缺失项": mm_missing},
               not mm_missing and worst_mm <= 1e-12 and mm_box["error"] <= BBOX_TOL
               and max(v for k, v in mm_errors.items() if k.startswith("n")) <= NORMAL_TOL)
    case_record.metric("step2_mm_asset_max_rel_diff", worst_mm)
    case_record.metric("step2_display_bbox_max_rel_diff", max(worst_scaled, worst_unscaled, mm_box["error"]))
    step.finish()


# --------------------------------------------------------------------------------------------- step 3


def test_step3_overrides_and_recalculation(case_record):
    """parameter_overrides take precedence; material, geometry and installation changes recalculate C, A and R."""

    step = Step(case_record, "步骤3")
    _, base_params = baseline()
    hashes_before = {str(p): SUP.sha256(p) for p in SUP.referenced_files(SIMREADY / "sat01_scene_overrides.json")}

    scene_path = SIMREADY / "sat01_scene_overrides.json"
    scene_json = SUP.read_json(scene_path)
    assembly, params = assembled(str(scene_path))
    table = copy.deepcopy(TABLE)
    table_material(table, "Battery01", "li_ion_cells")["mass_kg"] = 0.80
    facesheet = table_material(table, "Radiator01", "facesheet_al6061")
    facesheet["density_kg_m3"], facesheet["cp_J_kgK"] = 2810.0, 960.0
    table_surface(table, "Radiator01", "front")["absorptivity"] = 0.25
    table_material(table, "ColdPlate01", "plate_al6061")["solid_fraction"] = 0.7
    table["connections"]["BR"]["contact_resistance_K_W"] = 0.5
    table["connections"]["CR"]["equivalent_total_resistance_K_W"] = 0.15
    report = variant_report(params, SUP.reference_values(table), base_params)
    step.check("示例覆盖值优先于资产参数集并重算受影响量",
               "受影响的热容、质量、吸收率与热阻等于手算，相对误差不超过 0.1%，其余量逐位不变",
               report_actual(report), report_ok(report))
    case_record.metric("step3_overrides_max_rel_error", report["max_affected_rel_error"])

    source = scene_json["parameter_overrides"]["source"]
    applied = plain(params.provenance["overrides_applied"])
    expected_applied = [
        ("components/Battery01/materials/Battery01/li_ion_cells", "mass_kg", 0.76, 0.80),
        ("components/Radiator01/materials/Radiator01/facesheet_al6061", "cp_J_kgK", 896.0, 960.0),
        ("components/Radiator01/materials/Radiator01/facesheet_al6061", "mass_kg", 2.592, 2810.0 * 0.8 * 0.6 * 0.002),
        ("components/Radiator01/surfaces/Radiator01/front", "absorptivity", 0.20, 0.25),
        ("components/ColdPlate01/materials/ColdPlate01/plate_al6061", "mass_kg", 0.7776, 2700.0 * 0.2 * 0.15 * 0.012 * 0.7),
        ("connections/BR", "contact_resistance_K_W", 0.3, 0.5),
        ("connections/CR", "equivalent_total_resistance_K_W", 0.12, 0.15),
    ]
    absent = []
    for target, field, old, new in expected_applied:
        entry = next((a for a in applied if a["target"] == target and a["field"] == field), None)
        if (entry is None or SUP.rel_err(entry["old"], old) > 1e-9 or SUP.rel_err(entry["new"], new) > 1e-9
                or entry["source"] != source):
            absent.append(f"{target} {field}")
    step.check("覆盖记录写入 provenance", "七项覆盖逐项记录目标、字段、原值、新值与来源",
               {"记录项数": len(applied), "缺失或不符": absent}, not absent and len(applied) == len(expected_applied))

    # Observation outside the case steps: how a geometric-mass override (density, solid fraction) is recorded.
    facesheet = next(p for p in params.provenance["capacitance"]["R"]["portions"]
                     if p["material_id"] == "Radiator01/facesheet_al6061")
    records = [plain(params.provenance), plain(assembly.as_dict())]
    density_recorded = any(2810.0 in _numbers(r) or "density 2810" in json.dumps(r, default=str) for r in records)
    step.check("密度覆盖后的材料来源记录有效密度", "ThermalParameters 的材料来源记录 density 2810",
               facesheet['source'], "density 2810" in facesheet['source'])
    case_record.metric("observation_density_override_provenance", {
        "scene_override": scene_json["parameter_overrides"]["instances"]["Radiator01"]["thermal"]["materials"],
        "portion_mass_kg": float(facesheet["mass_kg"]),
        "portion_source": facesheet["source"],
        "overrides_applied_fields": sorted({a["field"] for a in applied
                                            if a["target"].endswith("Radiator01/facesheet_al6061")}),
        "density_2810_recorded_in_assembly_or_parameters": density_recorded,
    })

    efficiency = assembly.power["instances"]["SolarArray01"]["parameter_set"]["efficiency"]
    _, solar_asset = asset_json_of(scene_path, "SolarArray01")
    asset_efficiency = next(c for c in solar_asset["capabilities"] if c["domain"] == "power")["parameter_set"]["efficiency"]
    step.check("Power 参数覆盖值优先", "SolarArray01 光电效率取覆盖值 0.28，资产值 0.295 保持在资产文件中",
               f"装配值 {g(efficiency)}，资产文件值 {g(asset_efficiency)}", efficiency == 0.28 and asset_efficiency == 0.295)

    table = copy.deepcopy(TABLE)
    table["parts"]["radiator_panel_large.usda/Panel"] = {"size_m": [1.0, 0.6, 0.002], "meters_per_unit": 1.0}
    table["instances"]["Radiator01"]["geometry"] = "radiator_panel_large.usda"
    large_usd = SUP.parse_usda(DATA / "geometry" / "radiator_panel_large.usda")
    large_extent = np.array(large_usd["meshes"]["Panel"]["extent"])
    large_size = ((large_extent[1] - large_extent[0]) * large_usd["meters_per_unit"]).tolist()
    assembly_g, params_g = assembled(str(SCENES / "sat01_geometry_change.json"))
    report = variant_report(params_g, SUP.reference_values(table), base_params)
    version = assembly_g.provenance["instances"]["Radiator01"]["asset_version"]
    step.check("几何改变后重算面积、质量与热容",
               "散热板 0.2.0 版 1.0 m×0.6 m 面板的两面面积、面板质量与 C_R 等于手算，其余量逐位不变",
               {**report_actual(report), "独立解析尺寸": [g(v) for v in large_size], "资产版本": version},
               report_ok(report) and version == "0.2.0"
               and max(SUP.rel_err(a, b) for a, b in zip(large_size, [1.0, 0.6, 0.002])) <= 1e-9)
    case_record.metric("step3_geometry_change_C_R_J_K", float(params_g.C_J_K[NODE_ORDER.index("R")]))
    case_record.metric("step3_geometry_change_radiator_area_m2",
                       [float(s.area_m2) for s in params_g.surfaces if s.node_id == "R"])

    table = copy.deepcopy(TABLE)
    table_surface(table, "Radiator01", "front")["normal_body"] = [0.0, 0.0, 1.0]
    table_surface(table, "Radiator01", "back")["normal_body"] = [0.0, 0.0, -1.0]
    table["connections"]["BR"]["length_m"] = 0.08
    table["connections"]["SR"]["area_m2"] = 4.0e-4
    table["connections"]["DR"]["contact_resistance_K_W"] = 0.4
    _, params_i = assembled(str(SCENES / "sat01_installation_change.json"))
    report = variant_report(params_i, SUP.reference_values(table), base_params)
    step.check("安装方式改变后重算法线与热阻",
               "散热板改为正面朝 +Z 后法线改变而面积不变，BR、SR、DR 热阻等于手算，其余量逐位不变",
               report_actual(report), report_ok(report))
    case_record.metric("step3_installation_R_K_W", {p: float(params_i.R_K_W[i]) for i, p in enumerate(PATH_ORDER)})

    table = copy.deepcopy(TABLE)
    table_material(table, "Compute01", "copper_spreader")["cp_J_kgK"] = 390.0
    table_material(table, "Controller01", "electronics_pcb")["mass_kg"] = 0.20
    table_material(table, "ColdPlate01", "plate_al6061")["density_kg_m3"] = 2810.0
    table_surface(table, "SolarArray01", "back")["emissivity"] = 0.80
    table_material(table, "Radiator01", "embedded_heat_pipes")["mass_kg"] = 0.40
    _, params_m = assembled(str(SCENES / "sat01_material_change.json"))
    report = variant_report(params_m, SUP.reference_values(table), base_params)
    step.check("材料改变后重算热容", "C_J、C_D、C_C、C_R 与发射率等于手算，其余量逐位不变",
               report_actual(report), report_ok(report))
    case_record.metric("step3_material_C_J_K", {n: float(params_m.C_J_K[i]) for i, n in enumerate(NODE_ORDER)})

    hashes_after = {str(p): SUP.sha256(p) for p in SUP.referenced_files(scene_path)}
    step.check("覆盖值不写回资产文件", "装配前后七个资产文件、七个几何文件与场景文件哈希不变",
               f"{sum(hashes_before[k] == hashes_after.get(k) for k in hashes_before)} 个文件中哈希不变",
               hashes_before == hashes_after)
    step.finish()


# --------------------------------------------------------------------------------------------- step 4


def test_step4_shared_node_battery_path_ids_and_mass(case_record):
    """Controller01 and PDU01 share D, BR leads to the radiator, shared instance ids and mass counted once."""

    step = Step(case_record, "步骤4")
    assembly, params = baseline()
    nodes = {n: list(v) for n, v in params.instance_map["nodes"].items()}
    step.check("Controller01 与 PDU01 共用 D，其余节点各一个实例", DESIGN["nodes"], nodes, nodes == DESIGN["nodes"])
    capacitance = params.provenance["capacitance"]
    owners_d = sorted({p["instance_id"] for p in capacitance["D"]["portions"]})
    c_d = float(params.C_J_K[NODE_ORDER.index("D")])
    step.check("D 的热容为两台设备材料之和", f"C_D 手算 {g(REF['capacitance']['D'])} J/K，材料来自 Controller01 与 PDU01",
               f"C_D {g(c_d)} J/K，材料所属 {owners_d}",
               SUP.rel_err(c_d, REF["capacitance"]["D"]) <= LIMIT and owners_d == ["Controller01", "PDU01"])
    ranges = plain(params.provenance["temperature_range_K"])
    step.check("D 的适用温区为两台设备温区的交集", "243.15 K 至 343.15 K", ranges["D"], ranges["D"] == [243.15, 343.15])

    br = assembly.provenance["connections"]["BR"]
    electrical = plain(assembly.power["electrical_connections"])
    battery_link = [c for c in electrical if c["from"]["instance_id"] == "Battery01"]
    step.check("电池热连接 BR 通往散热板，电连接接控制器",
               "BR 由 Battery01 到 Radiator01，节点 B 到 R；Battery01 的电连接终点为 Controller01",
               {"BR": plain(br), "电连接": battery_link},
               br["from_instance"] == "Battery01" and br["to_instance"] == "Radiator01" and list(br["nodes"]) == ["B", "R"]
               and len(battery_link) == 1 and battery_link[0]["to"]["instance_id"] == "Controller01")
    rejection_check(step, "BR 终点改为控制器的场景被拒绝", SCENES / "sat01_br_to_controller.json", sc.SceneError,
                    ("BR", "Controller01", "to_instance"), lambda p: sc.load_scene(p))

    ports = dict(params.instance_map["ports"])
    _, _, _, info = SUP.power_setup(assembly, SAT01, "ni003-ids", "Sat01")
    component_ids = {c["instance_id"] for c in assembly.components}
    power_ids = set(assembly.power["instances"])
    endpoints = {c[end]["instance_id"] for c in electrical for end in ("from", "to")}
    step.check("Power 与 Thermal 使用相同的组件实例标识",
               f"热端口映射与 Power 链接均为 {DESIGN['ports']}，Power 实例与电连接端点均为热组件实例",
               {"热端口映射": ports, "Power 角色得到的链接": info["links"], "Power 实例": sorted(power_ids),
                "电连接端点": sorted(endpoints)},
               ports == DESIGN["ports"] and info["links"] == DESIGN["ports"] and power_ids <= component_ids
               and endpoints <= component_ids)

    _, params_run = baseline()
    run_id = "ni003-links"
    provider = SUP.environment_provider(run_id, params_run, 120.0)
    initial = ThermalState(run_id, 0.0, assembly.initial_temperature_K)
    pp_ok, st_ok, request, _ = SUP.power_setup(assembly, SAT01, run_id, "Sat01")
    accepted, kind, message, archive = attempt(lambda: cp.run_coupled(
        params_run, initial, provider, 120.0, power=cp.PowerCoupling(parameters=pp_ok, initial_state=st_ok,
                                                                      request_W=request)))
    wrong = dict(DESIGN["ports"], Q_D_W="Controller01")
    pp_bad, st_bad, _, _ = SUP.power_setup(assembly, SAT01, run_id, "Sat01", links_override=wrong)
    rejected_ok, kind_bad, message_bad, _ = attempt(lambda: cp.run_coupled(
        params_run, initial, provider, 120.0, power=cp.PowerCoupling(parameters=pp_bad, initial_state=st_bad,
                                                                      request_W=request)))
    step.check("联合运行核对 Power 链接与热实例映射",
               "链接一致时运行完成；Q_D_W 链接到 Controller01 时在配置阶段给出 CoupledConfigurationError",
               {"一致链接": "完成" if accepted and archive.status == "completed" else f"{kind}: {message[:300]}",
                "错误链接": "接受" if rejected_ok else f"{kind_bad}: {message_bad[:300]}"},
               accepted and archive.status == "completed" and not rejected_ok
               and kind_bad == "CoupledConfigurationError" and "Q_D_W" in message_bad)

    all_ids = [p["material_id"] for n in NODE_ORDER for p in capacitance[n]["portions"]]
    total = math.fsum(p["mass_kg"] for n in NODE_ORDER for p in capacitance[n]["portions"])
    heat_pipe_nodes = sorted({n for n in NODE_ORDER for p in capacitance[n]["portions"] if "heat_pipe" in p["material_id"]})
    step.check("材料质量只计一次",
               f"十四个材料部分各出现一次，总质量等于手算 {g(REF['total_mass'])} kg，热管质量只在 R",
               {"材料部分": len(all_ids), "重复": sorted({i for i in all_ids if all_ids.count(i) > 1}),
                "总质量": f"{g(total)} kg", "热管所在节点": heat_pipe_nodes},
               len(all_ids) == len(set(all_ids)) == len(REF["masses"]) and set(all_ids) == set(REF["masses"])
               and SUP.rel_err(total, REF["total_mass"]) <= LIMIT and heat_pipe_nodes == ["R"])
    case_record.metric("step4_total_mass_kg", total)
    rejection_check(step, "同一资产重复列出材料部分被拒绝", SCENES / "sat01_duplicate_material.json", sc.SceneError,
                    ("li_ion_cells", "duplicate"), lambda p: sc.load_scene(p))
    step.finish()


# --------------------------------------------------------------------------------------------- step 5


def test_step5_second_instance_in_one_scene(case_record):
    """One scene holds one satellite: a second instance on a node of the same scene is rejected."""

    step = Step(case_record, "步骤5")
    rejection_check(step, "同一场景第二块散热板被拒绝", SIMREADY / "sat01_scene_two_radiators.json", sc.SceneError,
                    ("Radiator02", "node R"), lambda p: sc.load_scene(p))
    rejection_check(step, "同一场景第二个电池被拒绝", SCENES / "sat01_second_battery.json", sc.SceneError,
                    ("Battery02", "node B"), lambda p: sc.load_scene(p))
    rejection_check(step, "同一资产在共用节点 D 上的第二个实例被拒绝", SCENES / "sat01_second_pdu.json", sc.SceneError,
                    ("PDU02", "node D", "PDU01"), lambda p: sc.load_scene(p))
    rejection_check(step, "电池初温写入 Power 初始状态被拒绝", SCENES / "sat01_battery_temperature_in_power_state.json",
                    sc.SceneError, ("Battery01", "T_B_K", "Thermal"), lambda p: sc.load_scene(p))
    accepted, kind, message, _ = attempt(lambda: sc.load_scene(SCENES / "sat02_root_sat02.json"))
    case_record.metric("observation_second_satellite_root_World_Sat02",
                       "accepted" if accepted else f"{kind}: {message[:300]}")
    step.finish()


def _run_alone(key: str, out_dir: Path) -> dict:
    completed = subprocess.run([sys.executable, str(DATA / "run_alone.py"), key, str(out_dir)], capture_output=True,
                               text=True, timeout=RUN_TIMEOUT_S, cwd=str(TESTS_DIR.parent))
    result = {"returncode": completed.returncode, "stderr": completed.stderr[-2000:]}
    if completed.returncode == 0:
        result["fingerprint"] = json.loads((out_dir / f"{key}_fingerprint.json").read_text(encoding="utf-8"))
        with np.load(out_dir / f"{key}_arrays.npz") as data:
            result["arrays"] = {name: data[name] for name in data.files}
        result["info"] = json.loads((out_dir / f"{key}_info.json").read_text(encoding="utf-8"))
    return result


def _compare(a_fp: dict, a_arrays: dict, b_fp: dict, b_arrays: dict) -> dict:
    differing_fields = sorted(k for k in set(a_fp) | set(b_fp) if a_fp.get(k) != b_fp.get(k))
    differing_arrays = sorted(k for k in set(a_arrays) | set(b_arrays)
                              if k not in a_arrays or k not in b_arrays or a_arrays[k].dtype != b_arrays[k].dtype
                              or a_arrays[k].shape != b_arrays[k].shape or a_arrays[k].tobytes() != b_arrays[k].tobytes())
    max_diff = 0.0
    for k in differing_arrays:
        if k in a_arrays and k in b_arrays and a_arrays[k].shape == b_arrays[k].shape:
            max_diff = max(max_diff, float(np.nanmax(np.abs(a_arrays[k] - b_arrays[k]))))
    return {"fields": len(set(a_fp) | set(b_fp)), "differing_fields": differing_fields,
            "arrays": len(set(a_arrays) | set(b_arrays)), "differing_arrays": differing_arrays,
            "max_abs_diff": max_diff, "identical": not differing_fields and not differing_arrays}


def _numbers(value: Any) -> set[float]:
    """Every numeric value of a plain record at any depth."""

    if isinstance(value, Mapping):
        return {n for v in value.values() for n in _numbers(v)}
    if isinstance(value, list):
        return {n for v in value for n in _numbers(v)}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {float(value)}
    return set()


def _field_names(value: Any) -> set[str]:
    """Every mapping key of a JSON record at any depth (port names and other values are not keys)."""

    if isinstance(value, Mapping):
        return set(value) | {k for v in value.values() for k in _field_names(v)}
    if isinstance(value, list):
        return {k for v in value for k in _field_names(v)}
    return set()


def _scene_initial(scene_path: Path) -> tuple[list[float], float, float]:
    scene_json = SUP.read_json(scene_path)
    temps = scene_json["initial_state"]["thermal"]["temperature_K"]
    nodes = DESIGN["nodes"]
    return ([float(temps[nodes[n][0]]) for n in NODE_ORDER],
            float(scene_json["initial_state"]["power"]["Battery01"]["x_n"]),
            float(scene_json["initial_state"]["power"]["Battery01"]["x_p"]))


def test_step5_two_satellites_independent(case_record, tmp_path):
    """Two satellites from the same asset files keep their own temperatures and battery states; nothing is written back."""

    step = Step(case_record, "步骤5")
    keys = ("Sat01", "Sat02")
    specs = SUP.RUNS
    files = sorted({p for key in keys for p in SUP.referenced_files(specs[key]["scene"])})
    hashes_before = {str(p): SUP.sha256(p) for p in files}
    folders = (SIMREADY, SIMREADY / "assets", SIMREADY / "geometry", SCENES)
    listing_before = {str(f): SUP.folder_listing(f) for f in folders}

    assets_1 = {p for p in SUP.referenced_files(specs["Sat01"]["scene"])[1:]}
    assets_2 = {p for p in SUP.referenced_files(specs["Sat02"]["scene"])[1:]}
    snapshot = {}
    for key in keys:
        assembly = sc.assemble_scene(specs[key]["scene"])
        snapshot[key] = (assembly, json.dumps(assembly.as_dict(), sort_keys=True, default=str))
    params_1 = assemble_thermal_parameters(*snapshot["Sat01"][0].thermal_inputs())
    params_2 = assemble_thermal_parameters(*snapshot["Sat02"][0].thermal_inputs())
    same_assets = assets_1 == assets_2 and module_values(params_1) == module_values(params_2)
    step.check("两颗卫星由同一组资产文件装配", "两场景引用相同的七个资产与七个几何文件，热参数逐位相同",
               {"资产与几何文件数": len(assets_1), "文件相同": assets_1 == assets_2,
                "热参数相同": module_values(params_1) == module_values(params_2)}, same_assets)

    initial = {key: _scene_initial(specs[key]["scene"]) for key in keys}
    own_initial = all(snapshot[key][0].initial_temperature_K.tolist() == initial[key][0] for key in keys)
    step.check("各自装配出本场景的初始温度", {k: initial[k][0] for k in keys},
               {k: snapshot[k][0].initial_temperature_K.tolist() for k in keys},
               own_initial and initial["Sat01"][0] != initial["Sat02"][0])

    runs: dict[str, dict] = {}
    at_finish: dict[str, tuple[dict, dict]] = {}
    for label, key in (("Sat01 第一次", "Sat01"), ("Sat02 第一次", "Sat02"), ("Sat01 第二次", "Sat01"),
                       ("Sat02 第二次", "Sat02")):
        runs[label] = SUP.run_satellite(specs[key]["scene"], specs[key]["run_id"], specs[key]["instance_id"])
        archive = runs[label]["archive"]
        at_finish[label] = (SUP.fingerprint(archive), SUP.main_arrays(archive))
    first = {"Sat01": runs["Sat01 第一次"], "Sat02": runs["Sat02 第一次"]}
    statuses = {label: (r["archive"].status, r["error"]) for label, r in runs.items()}
    step.check("四次联合运行全部完成", "status 为 completed，无错误记录", statuses,
               all(s == ("completed", None) for s in statuses.values()))

    starts = {}
    start_ok = True
    for key in keys:
        archive = first[key]["archive"]
        log = SUP.analyse_log(first[key]["log"], specs[key]["run_id"], specs[key]["instance_id"])
        power_info = first[key]["power_info"]
        starts[key] = {"首个样本温度": archive.temperature_K[0].tolist(), "首个 x_n": float(archive.lithium["x_n"][0]),
                       "首个 x_p": float(archive.lithium["x_p"][0]), "首次 Power 调用 T_B_K": log["first_T_B_K"],
                       "首次 Power 调用 x_n": log["first_x_n"], "首次 Power 调用 x_p": log["first_x_p"],
                       "场景 x_p 是否按锂量守恒替换": power_info["x_p_replaced"]}
        start_ok &= (archive.temperature_K[0].tolist() == initial[key][0]
                     and float(archive.lithium["x_n"][0]) == initial[key][1]
                     and float(archive.lithium["x_p"][0]) == power_info["x_p_used"] == log["first_x_p"]
                     and not power_info["x_p_replaced"] and power_info["x_p_used"] == initial[key][2]
                     and log["first_T_B_K"] == initial[key][0][NODE_ORDER.index("B")]
                     and log["first_x_n"] == initial[key][1])
    step.check("每颗卫星从本场景的温度与电池状态起算",
               {k: {"温度": initial[k][0], "x_n": initial[k][1], "场景 x_p": initial[k][2]} for k in keys},
               starts, start_ok)

    id_report = {}
    ids_ok = True
    for key in keys:
        log = SUP.analyse_log(first[key]["log"], specs[key]["run_id"], specs[key]["instance_id"])
        archive = first[key]["archive"]
        id_report[key] = {"run_id": archive.run_id, "Power 调用": log["power_calls"], "标识不符": log["wrong_ids"],
                          "与试算状态配对": log["paired"], "未配对": log["unpaired"], "B 温度不符": log["mismatched"],
                          "最终 Power 状态": [archive.final_power_state.run_id, archive.final_power_state.instance_id]}
        ids_ok &= (archive.run_id == specs[key]["run_id"] and log["power_calls"] > 0 and log["wrong_ids"] == 0
                   and log["wrong_trial_ids"] == 0 and log["paired"] == log["power_calls"] and log["unpaired"] == 0
                   and log["mismatched"] == 0
                   and archive.final_power_state.run_id == specs[key]["run_id"]
                   and archive.final_power_state.instance_id == specs[key]["instance_id"]
                   and dict(archive.provenance["caller"])["scene_id"] == snapshot[key][0].scene_id)
        case_record.metric(f"step5_{key}_power_calls", log["power_calls"])
    step.check("每次 Power 调用使用本卫星的运行标识、实例标识与本卫星试算 B 温度",
               "Sat01 与 Sat02 各自的 run_id 与 instance_id，T_B_K 等于同一试算状态的 B 温度", id_report, ids_ok)

    a1, a2 = first["Sat01"]["archive"], first["Sat02"]["archive"]
    max_dt = float(np.max(np.abs(a1.temperature_K - a2.temperature_K)))
    b_index = NODE_ORDER.index("B")
    max_dt_b = float(np.max(np.abs(a1.temperature_K[:, b_index] - a2.temperature_K[:, b_index])))
    final_dt_b = float(abs(a1.temperature_K[-1, b_index] - a2.temperature_K[-1, b_index]))
    max_dx = float(np.max(np.abs(a1.lithium["x_n"] - a2.lithium["x_n"])))
    final_t = {"Sat01": a1.final_thermal_state.temperature_K.tolist(),
               "Sat02": a2.final_thermal_state.temperature_K.tolist()}
    final_x = {"Sat01": [a1.final_power_state.x_n, a1.final_power_state.x_p],
               "Sat02": [a2.final_power_state.x_n, a2.final_power_state.x_p]}
    step.check("两颗卫星的温度与电池状态各自变化", "两组温度与锂状态时程不同，终值不同，结果数组不共用内存",
               {"同一时刻温度最大差": f"{g(max_dt)} K", "电池温度同一时刻最大差": f"{g(max_dt_b)} K",
                "电池终止温度差": f"{g(final_dt_b)} K", "x_n 同一时刻最大差": g(max_dx),
                "终止温度": final_t, "终止锂状态": final_x},
               max_dt > 0.0 and max_dt_b > 0.0 and max_dx > 0.0 and final_t["Sat01"] != final_t["Sat02"]
               and final_x["Sat01"] != final_x["Sat02"]
               and all(np.any(a.temperature_K[-1] != a.temperature_K[0])
                       and a.lithium['x_n'][-1] != a.lithium['x_n'][0] for a in (a1, a2))
               and not np.shares_memory(a1.temperature_K, a2.temperature_K)
               and not np.shares_memory(a1.lithium["x_n"], a2.lithium["x_n"]))
    case_record.metric("step5_max_battery_temperature_difference_K", max_dt_b)
    case_record.metric("step5_final_battery_temperature_difference_K", final_dt_b)
    case_record.metric("step5_max_x_n_difference", max_dx)
    for key, archive in (("Sat01", a1), ("Sat02", a2)):
        acc = archive.accepted["state"]
        case_record.metric(f"step5_{key}_initial_T_K", initial[key][0])
        case_record.metric(f"step5_{key}_final_T_K", archive.final_thermal_state.temperature_K.tolist())
        case_record.metric(f"step5_{key}_T_B_range_K", [float(acc[:, 3].min()), float(acc[:, 3].max())])
        case_record.metric(f"step5_{key}_x_n_range", [float(acc[:, 6].min()), float(acc[:, 6].max())])
        case_record.metric(f"step5_{key}_final_lithium", [float(archive.final_power_state.x_n),
                                                          float(archive.final_power_state.x_p)])
        case_record.metric(f"step5_{key}_range_warnings", len(archive.range_warnings))
        case_record.metric(f"step5_{key}_eclipse_boundaries", [[round(b.time_s, 3), b.kind]
                                                               for b in archive.eclipse_boundaries])
    case_record.metric("step5_max_temperature_difference_K", max_dt)
    case_record.metric("step5_power_info", {k: {n: v for n, v in first[k]["power_info"].items() if n != "links"}
                                           for k in keys})

    comparisons = {}
    for key in keys:
        a = runs[f"{key} 第一次"]["archive"]
        b = runs[f"{key} 第二次"]["archive"]
        comparisons[key] = _compare(SUP.fingerprint(a), SUP.main_arrays(a), SUP.fingerprint(b), SUP.main_arrays(b))
    kept = {label: _compare(*at_finish[label], SUP.fingerprint(r["archive"]), SUP.main_arrays(r["archive"]))["identical"]
            for label, r in runs.items()}
    step.check("另一颗卫星运行后重算结果逐位相同",
               "Sat01 在 Sat02 运行后重算、Sat02 在 Sat01 重算后重算，归档全部字段与状态数组逐位相同；"
               "每份归档在其后的运行结束时仍与刚完成时逐位相同",
               {**{k: {"字段": v["fields"], "不同字段": v["differing_fields"], "数组": v["arrays"],
                       "不同数组": v["differing_arrays"], "最大差": v["max_abs_diff"]} for k, v in comparisons.items()},
                "归档未被其后运行改变": kept},
               all(v["identical"] for v in comparisons.values()) and all(kept.values()))

    alone = {key: _run_alone(key, tmp_path / key) for key in keys}
    alone_report = {}
    alone_ok = True
    for key in keys:
        result = alone[key]
        if result["returncode"] != 0:
            alone_report[key] = f"独立进程失败: {result['stderr'][-600:]}"
            alone_ok = False
            continue
        a = first[key]["archive"]
        comparison = _compare(SUP.fingerprint(a), SUP.main_arrays(a), result["fingerprint"], result["arrays"])
        info = result["info"]
        alone_report[key] = {"状态": info["status"], "不同字段": comparison["differing_fields"],
                             "不同数组": comparison["differing_arrays"], "最大差": comparison["max_abs_diff"],
                             "独立进程已载入的被测模块": info["modules_loaded"]}
        alone_ok &= comparison["identical"] and info["status"] == "completed" and info["hash_before"] == info["hash_after"]
    step.check("单独进程中只运行一颗卫星的结果与同进程结果逐位相同",
               "新解释器只装配并运行该卫星，归档全部字段与状态数组逐位相同", alone_report, alone_ok)

    hashes_after = {str(p): SUP.sha256(p) for p in files}
    listing_after = {str(f): SUP.folder_listing(f) for f in folders}
    changed = sorted(k for k in hashes_before if hashes_before[k] != hashes_after.get(k))
    step.check("运行后资产、几何与场景文件哈希不变", f"{len(files)} 个文件哈希不变，资产、几何与场景目录没有新增或改变的文件",
               {"改变的文件": changed, "目录列表不变": listing_before == listing_after},
               not changed and listing_before == listing_after)

    stale = []
    for key in keys:
        assembly, before = snapshot[key]
        after = json.dumps(assembly.as_dict(), sort_keys=True, default=str)
        fresh = json.dumps(sc.assemble_scene(specs[key]["scene"]).as_dict(), sort_keys=True, default=str)
        if after != before:
            stale.append(f"{key} 装配对象在运行后改变")
        if fresh != before:
            stale.append(f"{key} 运行后重新装配的结果不同")
        if assembly.initial_temperature_K.tolist() != initial[key][0]:
            stale.append(f"{key} 初始温度被改写")
    runtime_keys = {"temperature_K", "T_B_K", "x_n", "x_p", "initial_state", "time_s", "run_id"}
    found = []
    for path in sorted(assets_1 | assets_2):
        if path.suffix == ".json":
            found += [f"{path.name}: {k}" for k in sorted(_field_names(SUP.read_json(path)) & runtime_keys)]
    step.check("运行温度与锂状态不写回资产记录",
               "装配对象与重新装配结果不变，初始温度仍为场景初值，资产文件不含温度、锂状态或运行标识字段",
               {"改变": stale, "资产文件中的运行字段": found}, not stale and not found)
    step.finish()


def test_step5_unregistered_model_id(case_record):
    """An unregistered model_id is rejected in either domain; the registry holds plain data only."""

    step = Step(case_record, "步骤5")
    for label, scene_path, words in (
        ("示例未登记热模型被拒绝", SIMREADY / "sat01_scene_invalid_unregistered_model.json",
         ("user.plugins.thermal:exec_python", "model_id", "not a registered thermal model")),
        ("未登记的 Power 模型版本被拒绝", SCENES / "sat01_unregistered_power_model.json",
         ("sdtwin.power.controller.ideal_mppt/2", "model_id", "not a registered power model")),
        ("其他领域登记的模型标识被拒绝", SCENES / "sat01_cross_domain_model.json",
         ("sdtwin.power.controller.ideal_mppt/1", "model_id", "not a registered thermal model")),
        ("导入路径形式的模型标识被拒绝", SCENES / "sat01_payload_model.json",
         ("ni003_payload:execute", "model_id", "not a registered thermal model")),
    ):
        rejection_check(step, label, scene_path, sc.UnregisteredModelError, words, lambda p: sc.load_scene(p))

    plain_data = []
    for registry in (sc.THERMAL_MODEL_REGISTRY, sc.POWER_MODEL_REGISTRY):
        for model_id, spec in registry.items():
            for name, value in vars(spec).items():
                values = list(value.values()) if isinstance(value, Mapping) else (
                    list(value) if isinstance(value, tuple) else [value])
                if any(callable(v) for v in values):
                    plain_data.append(f"{model_id}.{name}")
    step.check("模型登记表只含数据记录", "登记项的字段均为文本、布尔值或其组合，没有可调用对象",
               {"热模型": sorted(sc.THERMAL_MODEL_REGISTRY), "Power 模型": sorted(sc.POWER_MODEL_REGISTRY),
                "可调用字段": plain_data}, not plain_data)
    step.finish()


def _static_scan(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {"eval", "exec", "compile", "__import__", "execfile", "breakpoint"}
    attributes = {"import_module", "system", "popen", "Popen", "run_path", "run_module", "load_module", "exec_module",
                  "spawn", "startfile", "loads"}
    modules = {"importlib", "pickle", "marshal", "subprocess", "ctypes", "runpy", "code", "codeop", "shelve", "dill"}
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in calls:
                findings.append(f"call {func.id} line {node.lineno}")
            if isinstance(func, ast.Attribute) and func.attr in attributes:
                owner = func.value.id if isinstance(func.value, ast.Name) else ""
                if not (func.attr == "loads" and owner == "json"):
                    findings.append(f"call {owner}.{func.attr} line {node.lineno}")
        elif isinstance(node, ast.Import):
            findings += [f"import {a.name} line {node.lineno}" for a in node.names if a.name.split(".")[0] in modules]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in modules:
            findings.append(f"from {node.module} line {node.lineno}")
    return findings


def test_step5_no_code_execution_from_usd(case_record, tmp_path):
    """Nothing read from USD or from a model_id is imported, compiled or executed."""

    step = Step(case_record, "步骤5")
    sentinel = tmp_path / "ni003_sentinel.txt"
    completed = subprocess.run([sys.executable, str(DATA / "probe_no_exec.py"), str(sentinel)], capture_output=True,
                               text=True, timeout=RUN_TIMEOUT_S, cwd=str(TESTS_DIR.parent))
    if completed.returncode != 0:
        step.check("审计钩子探针运行", "探针正常结束", completed.stderr[-1500:], False)
        step.finish()
        return
    probe = json.loads(completed.stdout.strip().splitlines()[-1])
    case_record.metric("step5_probe", probe)

    model = probe["payload_model"]
    step.check("导入路径模型标识既不导入也不执行",
               "UnregisteredModelError；载入窗口内无带标记的 import、compile、exec 事件，哨兵文件不存在，模块未载入",
               {"错误": model["error_type"], "事件": model["events"], "哨兵": model["sentinel_exists"],
                "模块已载入": model["module_loaded"]},
               model["rejected"] and model["error_type"] == "UnregisteredModelError"
               and model["events"]["with_marker"] == 0 and model["events"]["exec"] == 0
               and model["events"]["compile"] == 0 and model["events"]["spawn_or_load"] == 0
               and not model["sentinel_exists"] and not model["module_loaded"] and not probe["sentinel_before"])

    usd = probe["payload_usd"]
    step.check("USD 中的 Python 文本不被执行",
               "含代码文本的资产正常装配且热参数与 Sat01 逐位相同；窗口内无 exec、compile 与进程事件，哨兵文件不存在",
               {"接受": usd["accepted"], "参数相同": usd["same_parameters_as_sat01"], "事件": usd["events"],
                "哨兵": usd["sentinel_exists"], "错误": usd["error"]},
               usd["accepted"] and usd["same_parameters_as_sat01"] and usd["events"]["with_marker"] == 0
               and usd["events"]["exec"] == 0 and usd["events"]["compile"] == 0
               and usd["events"]["spawn_or_load"] == 0 and not usd["sentinel_exists"])

    control_import, control_exec = probe["control_import"], probe["control_exec"]
    step.check("探针能发现执行", "主动导入载荷模块与主动执行 USD 文本时哨兵文件写入且审计事件带标记",
               {"导入": [control_import["sentinel_text"], control_import["events"]["with_marker"]],
                "执行": [control_exec["sentinel_text"], control_exec["events"]["with_marker"]]},
               control_import["sentinel_text"] == "NI003-MODEL-ID-PAYLOAD-IMPORTED"
               and control_import["events"]["with_marker"] > 0
               and control_exec["sentinel_text"] == "NI003-USD-PAYLOAD-EXECUTED"
               and control_exec["events"]["with_marker"] > 0)

    findings = _static_scan(SCENE_SOURCE)
    step.check("场景装配源码不含动态执行调用", "scene.py 不调用 eval、exec、compile、动态导入、序列化载入或子进程",
               findings or "未发现", not findings)
    step.finish()


def _pv_numbers(scene_path: Path) -> tuple[float, float, str]:
    """PV efficiency and the absorptivity of the surface it is bound to, from the asset and scene files."""

    scene_json = SUP.read_json(scene_path)
    _, asset = asset_json_of(scene_path, "SolarArray01")
    power = next(c for c in asset["capabilities"] if c["domain"] == "power")["parameter_set"]
    thermal = next(c for c in asset["capabilities"] if c["domain"] == "thermal")["parameter_set"]
    surface_id = power["surface_id"]
    efficiency = float(power["efficiency"])
    absorptivity = float(next(s for s in thermal["surfaces"] if s["surface_id"] == surface_id)["absorptivity"])
    block = scene_json["parameter_overrides"]["instances"].get("SolarArray01", {})
    efficiency = float(block.get("power", {}).get("efficiency", efficiency))
    absorptivity = float(block.get("thermal", {}).get("surfaces", {}).get(surface_id, {}).get("absorptivity",
                                                                                               absorptivity))
    return efficiency, absorptivity, surface_id


def test_step5_pv_efficiency_not_above_absorptivity(case_record):
    """Design 9.4: the PV efficiency does not exceed the absorptivity of the same surface."""

    step = Step(case_record, "步骤5")
    cases = (
        ("Sat01 基准", SAT01),
        ("示例效率 0.95", SIMREADY / "sat01_scene_invalid_pv_efficiency.json"),
        ("正面吸收率覆盖为 0.25", SCENES / "sat01_pv_absorptivity_override.json"),
        ("效率等于吸收率 0.91", SCENES / "sat01_pv_equal.json"),
        ("效率 0.9101 略高于吸收率", SCENES / "sat01_pv_slightly_above.json"),
        ("背面电池效率 0.89 对背面吸收率 0.88", SCENES / "sat01_pv_back_cells.json"),
        ("背面电池效率覆盖为 0.87", SCENES / "sat01_pv_back_cells_override.json"),
    )
    rows = {}
    all_ok = True
    for label, scene_path in cases:
        efficiency, absorptivity, surface_id = _pv_numbers(scene_path)
        expected = efficiency <= absorptivity
        accepted, kind, message, assembly = attempt(lambda p=scene_path: sc.assemble_scene(p))
        ok = accepted == expected
        if accepted:
            bound = assembly.power["instances"]["SolarArray01"]["surface"]
            ok &= bound["surface_id"] == f"SolarArray01/{surface_id}" and bound["absorptivity"] == absorptivity
        else:
            ok &= kind == "SceneError" and "efficiency" in message and "absorptivity" in message \
                and f"SolarArray01/{surface_id}" in message
        rows[label] = (f"效率 {g(efficiency)} 表面 {surface_id} 吸收率 {g(absorptivity)}，应"
                       f"{'接受' if expected else '拒绝'}，实际{'接受' if accepted else '拒绝 ' + message[:200]}")
        all_ok &= ok
    step.check("光电效率不超过同一表面的吸收率",
               "效率不超过所绑定表面吸收率时接受，超过时拒绝并指出该表面；判据按覆盖后的值与所绑定的表面", rows, all_ok)
    case_record.metric("step5_pv_cases", rows)
    step.finish()


# --------------------------------------------------------------------------------------------- summary


def test_step6_summary(case_record):
    """Chinese summary and anomaly record of the case from the checks and metrics recorded above."""

    m = case_record.metrics
    checks = case_record.checks
    failed = [c["name"] for c in checks if not c["passed"]]

    def num(key: str, fmt: str) -> str:
        value = m.get(key)
        return format(value, fmt) if isinstance(value, (int, float)) else "未取得"

    def sci_cn(value: Any) -> str:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return "未取得"
        if value == 0.0:
            return "0"
        exponent = int(math.floor(math.log10(abs(value))))
        mantissa = value / 10 ** exponent
        return f"{mantissa:.1f}×10{str(exponent).translate(str.maketrans('0123456789-', '⁰¹²³⁴⁵⁶⁷⁸⁹⁻'))}"

    def step_ok(label: str) -> bool:
        own = [c for c in checks if c["name"].startswith(label + " ")]
        return bool(own) and all(c["passed"] for c in own)

    def named_ok(*names: str) -> bool:
        return all(any(c["name"] == "步骤5 " + name and c["passed"] for c in checks) for name in names)

    second_ok = named_ok("同一场景第二块散热板被拒绝", "同一场景第二个电池被拒绝", "同一资产在共用节点 D 上的第二个实例被拒绝",
                         "电池初温写入 Power 初始状态被拒绝")
    twin_ok = named_ok("两颗卫星由同一组资产文件装配", "各自装配出本场景的初始温度", "四次联合运行全部完成",
                       "每颗卫星从本场景的温度与电池状态起算",
                       "每次 Power 调用使用本卫星的运行标识、实例标识与本卫星试算 B 温度",
                       "两颗卫星的温度与电池状态各自变化", "另一颗卫星运行后重算结果逐位相同",
                       "单独进程中只运行一颗卫星的结果与同进程结果逐位相同", "运行后资产、几何与场景文件哈希不变",
                       "运行温度与锂状态不写回资产记录")
    registry_ok = named_ok("示例未登记热模型被拒绝", "未登记的 Power 模型版本被拒绝", "其他领域登记的模型标识被拒绝",
                           "导入路径形式的模型标识被拒绝", "模型登记表只含数据记录")
    exec_ok = named_ok("导入路径模型标识既不导入也不执行", "USD 中的 Python 文本不被执行", "探针能发现执行",
                       "场景装配源码不含动态执行调用")
    pv_ok = named_ok("光电效率不超过同一表面的吸收率")

    info = m.get("step5_power_info", {})
    sat01_info = info.get("Sat01", {})
    density_note = m.get("observation_density_override_provenance") or {}
    t_b_1 = m.get("step5_Sat01_T_B_range_K", [math.nan, math.nan])
    t_b_2 = m.get("step5_Sat02_T_B_range_K", [math.nan, math.nan])
    x_1 = m.get("step5_Sat01_final_lithium", [math.nan, math.nan])
    x_2 = m.get("step5_Sat02_final_lithium", [math.nan, math.nan])
    boundaries = m.get("step5_Sat01_eclipse_boundaries", [])
    exits = [t for t, kind in boundaries if kind.endswith("_to_sunlit")]
    entries = [t for t, kind in boundaries if kind.startswith("sunlit_to")]
    eclipse_text = (f"于 {exits[0]:.1f} s 出日食、于 {entries[0]:.1f} s 进日食" if exits and entries
                    else "日食边界未取得")
    sentences = [
        "用 sdtwin_sim.scene 装配示例 Sat01 场景的七个实例，并用本用例自建的显示缩放资产、毫米单位资产、0.2.0 版散热板、"
        "覆盖值场景、同一资产的第二颗卫星、未登记 model_id 与带代码文本的 USD 资产逐项检查第 9.3 节与第 9.4 节的要求。",
        f"四个外露表面面积与十四个材料部分质量按资产物理尺寸手算比较，面积最大相对误差为 {sci_cn(m.get('step1_max_rel_error_area'))}，"
        f"质量最大相对误差为 {sci_cn(m.get('step1_max_rel_error_mass'))}，验收值为 0.1%"
        + ("，满足；" if step_ok("步骤1") else "，有未满足的项；")
        + f"六个节点热容与五条热阻的最大相对误差为 {sci_cn(m.get('step1_max_rel_error_C'))} 与 "
          f"{sci_cn(m.get('step1_max_rel_error_R'))}，总质量为 {num('step1_total_mass_kg', '.5f')} kg。",
        ("示例显示缩放场景与七个实例全部加显示缩放的场景，热容、热阻、面积、法线与质量和 Sat01 逐位相同，"
         f"显示包围盒按缩放比例改变，按包围盒推得的面积可达实际值的 {num('step2_max_bbox_area_ratio', '.3g')} 倍，"
         "默认 prim 带缩放的资产与部件带缩放的资产均被拒绝，毫米单位资产得到与米单位相同的物理参数。" if step_ok("步骤2")
         else "显示缩放检查有未通过的项。"),
        ("示例覆盖值优先于资产参数集，七项覆盖记入 provenance；材料、几何与安装方式改变后，受影响的热容、面积与热阻等于手算，"
         f"其余量逐位不变，0.2.0 版散热板的热容为 {num('step3_geometry_change_C_R_J_K', '.2f')} J/K。" if step_ok("步骤3")
         else "覆盖值与重算检查有未通过的项。"),
        ("Controller01 与 PDU01 共用 D，BR 由 Battery01 通往 Radiator01，热端口映射与 Power 链接使用同一组实例标识，"
         "链接不一致时联合运行在配置阶段报错，十四个材料部分各计一次。" if step_ok("步骤4") else "共用节点、实例标识或质量计数检查有未通过的项。"),
        ("同一场景的第二块散热板、第二个电池与共用节点 D 上同一资产的第二个实例均被拒绝；场景记录中的电池初温只能写在热初始状态中，"
         "写入 Power 初始状态的电池初温被拒绝。" if second_ok
         else "同一场景第二个实例或电池初温归属的检查有未通过的项。"),
        f"Sat01 与第二颗卫星 Sat02 由同一组资产文件装配，按各自初值联合运行 5600 s，{eclipse_text}；"
        f"电池温度分别在 {t_b_1[0]:.2f} K 至 {t_b_1[1]:.2f} K 与 {t_b_2[0]:.2f} K 至 {t_b_2[1]:.2f} K 之间，"
        f"终止 x_n 分别为 {x_1[0]:.4f} 与 {x_2[0]:.4f}，"
        f"两颗卫星电池温度在同一时刻最大相差 {num('step5_max_battery_temperature_difference_K', '.2f')} K，"
        f"x_n 最大相差 {num('step5_max_x_n_difference', '.4f')}。"
        + ("每次 Power 调用都使用本卫星的运行标识、实例标识与本卫星的试算电池温度；另一颗卫星运行后重算以及在新解释器中单独运行，"
           "归档逐位相同；运行前后资产、几何与场景文件哈希不变，运行温度与锂状态没有写回资产记录。" if twin_ok
           else "两颗卫星独立温度与电池状态的检查有未通过的项。"),
        f"Sat01 示例场景给出的初始 x_p 为 {sat01_info.get('x_p_scene', math.nan):.2f}，与测试用供电程序电池参数在 x_n 为 "
        f"{sat01_info.get('x_n', math.nan):.2f} 时的锂量相差 {sat01_info.get('inventory_rel_diff_scene', math.nan) * 100:.1f}%，"
        f"联合运行原样使用场景中已声明的 x_p 为 {sat01_info.get('x_p_used', math.nan):.4f}，没有在运行时修正初值。",
        ("第二颗卫星的场景记录仍写根路径 /World/Sat01，场景装配只接受这一根路径，以 /World/Sat02 为根的记录被拒绝。"
         if str(m.get("observation_second_satellite_root_World_Sat02", "")).startswith("SceneError") else ""),
        (f"覆盖值检查中还看到，散热板面板密度覆盖为 2810 kg/m³ 后质量按 "
         f"{density_note.get('portion_mass_kg', math.nan):.4f} kg 重算，ThermalParameters 的材料来源同时保存资产原始密度与覆盖后有效密度，"
         "覆盖记录保留质量原值、新值与来源。"
         if density_note and not density_note.get("density_2810_recorded_in_assembly_or_parameters", True) else ""),
        ("未登记的热模型、未登记的 Power 模型版本、其他领域的模型标识与导入路径形式的 model_id 均被拒绝，模型登记表只含数据记录。"
         if registry_ok else "未登记 model_id 的检查有未通过的项。"),
        ("审计钩子、哨兵文件与已载入模块列表显示载入过程中没有导入、编译或执行注入代码，USD 中的代码文本未被执行，"
         "主动导入与主动执行的对照均被探针发现。" if exec_ok else "不从 USD 执行代码的检查有未通过的项。"),
        ("七种光电效率工况按覆盖后的效率与所绑定表面的吸收率判定，效率不超过吸收率时接受，超过时拒绝。" if pv_ok
         else "光电效率与吸收率的检查有未通过的项。"),
        f"共 {len(checks)} 项检查，{len(checks) - len(failed)} 项通过。",
    ]
    case_record.summary("".join(sentences))
    if failed:
        case_record.anomalies("以下检查未通过：" + "；".join(failed) + "。")
    else:
        case_record.anomalies("无")
