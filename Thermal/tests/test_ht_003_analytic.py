"""Test case HT-003 解析解对比 of the SDTwin thermal test report (thermal design 4.3 T3, chapter 8 table 8).

``thermal_derivative`` is integrated by the coupled procedure ``sdtwin_sim.coupled.run_coupled`` with the RK45 solver
of design chapter 8, as thermal-only runs with prescribed Power ports, on three cases that have analytic solutions:

1. single-node step: the cold plate is held at constant temperature, P_load steps from 0 W to 300 W, C_J = 500 J/K,
   R_JC = 0.1 K/W; the computing-node temperature is compared with the exponential solution over the whole run;
2. series steady state: computing node -> cold plate -> radiator held at constant temperature, P_load = 300 W;
   at steady state T_J - T_R must equal P (R_JC + R_CR);
3. radiation balance: the radiator has only a fixed input power and its own surface radiation; at steady state
   T_R^4 must equal P / (eps sigma A).

Acceptance: step response error <= 0.001 K over the whole run; both steady states within 0.001 K.

Preconditions of the case: HT-002 has passed, checked on the HT-002 record of the same pytest session when HT-002 ran
in it (the evidence files are written at the end of a session) and otherwise on ``tests/results/HT-002.json``, which
must be newer than every source file of the ``thermal`` package; RK45 with its tolerances and maximum step is
configured and recorded in every archive.

The configuration is ``tests/data/ht_003/cases.json``. The analytic references are ``tests/data/ht_003/analytic.py``,
which imports neither ``thermal`` nor ``sdtwin_sim``. Paths that take no part in a case have documented 1e12 K/W
resistances, except JC in the radiation case: it keeps 0.1 K/W and carries no flow because the computing node and the
cold plate stay at the same temperature, which step 3 measures. Unused port powers are zero, exposed surfaces that take
no part have zero absorptivity and emissivity, and a temperature the case holds constant is a 1e12 J/K heat sink whose
drift is checked against the hand-calculated bound. Earth albedo and infrared are switched off with a recorded reason
(design 9.4); the archived note and the provenance of every run are checked for it. The temperature derivatives are
checked against T3 by hand on the archived output samples at the initial time and the step time, after the runs.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy import constants as scipy_constants

from sdtwin_sim import coupled as cp
from thermal import ThermalState, assemble_thermal_parameters
from thermal.types import NODE_ORDER, PATH_ORDER

pytestmark = pytest.mark.case("HT-003")

TESTS_DIR = Path(__file__).resolve().parent
CASE_DIR = TESTS_DIR / "data" / "ht_003"
RESULTS_DIR = TESTS_DIR / "results"
SERIES_FILE = RESULTS_DIR / "HT-003_series.json"
# Precondition HT-002 已通过: evidence of HT-002 and the package that HT-002 tests (thermal_derivative and its helpers).
HT002_EVIDENCE = RESULTS_DIR / "HT-002.json"
THERMAL_PACKAGE = TESTS_DIR.parent / "thermal"
HT002_READ_ATTEMPTS = 5  # HT-002.json can be in the middle of being rewritten by a concurrent HT-002 run
# Note that sdtwin_sim.coupled writes into the archive when Earth albedo and infrared are switched off (design 9.4).
EARTH_FLUX_NOTE_PREFIX = "Earth albedo and infrared switched off: "

# Names of the checks that the Chinese summary refers to.
CHECK_HT002 = "前置条件 HT-002 已通过"
CHECK_SOLVER = "前置条件 积分方法与容限按第8章配置并记入归档"
CHECK_MAX_STEP = "前置条件 最大步长约束全部已接受步"
CHECK_ASSEMBLY = "输入 装配所得热容热阻与表面参数与用例输入一致"
CHECK_EARTH_FLUX = "配置 地球反照与红外按第9.4节记录后关闭"
CHECK_DERIVATIVE = "核对 归档中初始时刻与阶跃时刻的温度导数与式T3手算一致"
CHECK_SIGMA = "核对 斯忒藩玻尔兹曼常数与CODATA一致"
CHECK_STEP_SEGMENT = "步骤1 阶跃时刻为积分分段边界"
CHECK_RADIATOR_INPUT = "步骤3 散热板只有固定输入功率与自身表面辐射"
CHECK_JC = "步骤3 JC 热阻保持不变且没有热流"

# Acceptance thresholds of HT-003 (验收判据): 阶跃响应全程误差与两个稳态算例的误差均不超过 0.001 K.
ACCEPT_K = 0.001
# Stefan-Boltzmann constant of thermal design table 5 (hand-calculation value; cross-checked with CODATA below).
SIGMA_DESIGN = 5.670374419e-8
# Verification limits of the test configuration itself (not acceptance criteria of the case):
HELD_CONSTANT_LIMIT_K = 1e-5  # drift of a 1e12 J/K heat sink: one hundredth of the acceptance threshold
UNUSED_NODE_LIMIT_K = 1e-6  # nodes isolated from a case stay at their initial temperature
ISOLATION_FLOW_LIMIT_W = 1e-9  # total flow through the 1e12 K/W isolation paths into the radiator
RELATIVE_EXACT = 1e-12  # relative agreement of hand-calculated parameters, derivatives and powers

NODE_IX = {node: index for index, node in enumerate(NODE_ORDER)}
PATH_IX = {path: index for index, path in enumerate(PATH_ORDER)}

# Evidence collected by the step tests and written by the last test of the module.
_EVIDENCE: dict[str, Any] = {}


# ---------------------------------------------------------------------------------------------------------- helpers


def _load_analytic() -> Any:
    spec = importlib.util.spec_from_file_location("ht_003_analytic", CASE_DIR / "analytic.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _components(config: dict[str, Any], key: str, case: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Component and connection records of one analytic case for assemble_thermal_parameters (design 5.2)."""

    components = []
    for instance in config["instances"]:
        instance_id = instance["instance_id"]
        surfaces = []
        for surface in config["surfaces"].get(instance_id, []):
            optical = case["optical"][instance_id]
            surfaces.append(
                {
                    "surface_id": surface["surface_id"],
                    "area_m2": surface["area_m2"],
                    "normal_body": surface["normal_body"],
                    "absorptivity": optical["absorptivity"],
                    "emissivity": optical["emissivity"],
                    "source": case["optical_source"],
                }
            )
        components.append(
            {
                "instance_id": instance_id,
                "node_id": instance["node_id"],
                "asset_id": instance["asset_id"],
                "asset_version": config["asset_version"],
                "materials": [
                    {
                        "material_id": f"{instance_id}_{key}_body",
                        "mass_kg": case["mass_kg"][instance_id],
                        "cp_J_kgK": config["specific_heat_J_kgK"],
                        "source": f"{case['mass_source']}; {config['specific_heat_source']}",
                    }
                ],
                "surfaces": surfaces,
                "temperature_range_K": list(config["temperature_range_K"]),
                "ports": list(instance["ports"]),
            }
        )
    connections = [
        {
            "path": path,
            "equivalent_total_resistance_K_W": case["resistance_K_W"][path],
            "includes_contact": True,
            "source": case["resistance_source"],
        }
        for path in PATH_ORDER
    ]
    return components, connections


def _provider(config: dict[str, Any], case: dict[str, Any], parameters: Any) -> cp.EnvironmentProvider:
    geometry = config["environment"]
    position = np.array(geometry["position_m"], dtype=float)
    sun = np.array(geometry["sun_position_m"], dtype=float)
    quaternion = np.array(geometry["quaternion_xyzw"], dtype=float)
    irradiance = float(case["G_W_m2"])

    def fixed_position(time_s: float) -> np.ndarray:
        return position

    def fixed_sun_position(time_s: float) -> np.ndarray:
        return sun

    def identity_attitude(time_s: float) -> np.ndarray:
        return quaternion

    def constant_irradiance(time_s: float) -> float:
        return irradiance

    return cp.EnvironmentProvider.from_callables(
        run_id=case["run_id"],
        epoch=datetime.fromisoformat(config["epoch_utc"]),
        parameters=parameters,
        position=fixed_position,
        sun_position=fixed_sun_position,
        quaternion=identity_attitude,
        G=constant_irradiance,
        earth_flux=cp.EarthFluxModel.disabled(geometry["earth_flux_disabled_reason"]),
    )


def _ports(case: dict[str, Any]):
    base = {name: float(value) for name, value in case["ports_W"].items()}
    step = case.get("load_step")

    def ht003_prescribed_ports(time_s: float) -> dict[str, float]:
        values = dict(base)
        if step is not None:
            values["P_load_W"] = float(step["after_W"] if time_s >= step["time_s"] else step["before_W"])
        return values

    return ht003_prescribed_ports


def _run_case(config: dict[str, Any], key: str, case: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {"key": key, "case": case, "parameters": None, "archive": None, "error": None,
                              "wall_s": None}
    try:
        components, connections = _components(config, key, case)
        parameters = assemble_thermal_parameters(components, connections, None)
        record["parameters"] = parameters
        settings = cp.SolverSettings(**config["solver_settings"])
        initial = ThermalState(case["run_id"], 0.0, [case["initial_temperature_K"][node] for node in NODE_ORDER])
        boundaries = []
        step = case.get("load_step")
        if step is not None:
            boundaries.append((float(step["time_s"]), step["label"]))
        started = time.perf_counter()
        try:
            archive = cp.run_coupled(
                parameters,
                initial,
                _provider(config, case, parameters),
                float(case["t_end_s"]),
                settings=settings,
                prescribed_ports=_ports(case),
                boundaries_s=boundaries,
                provenance={"case_id": "HT-003", "analytic_case": key, "configuration": "tests/data/ht_003/cases.json"},
            )
        except cp.CoupledRunError as exc:
            archive = exc.archive
            record["error"] = f"CoupledRunError: {exc}"
        record["wall_s"] = time.perf_counter() - started
        record["archive"] = archive
    except Exception as exc:  # noqa: BLE001  (reported as a failed check of the step that needs the run)
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def _status_text(run: dict[str, Any]) -> str:
    archive = run["archive"]
    status = archive.status if archive is not None else "no archive"
    return f"status {status}; error {run['error']}; wall {run['wall_s'] or 0.0:.2f} s"


def _completed(run: dict[str, Any]) -> bool:
    archive = run["archive"]
    return archive is not None and archive.status == "completed" and archive.error is None and run["error"] is None


def _relative(actual: float, expected: float) -> float:
    return abs(actual - expected) / abs(expected) if expected != 0.0 else abs(actual)


def _not_executed(case_record, names: list[tuple[str, str]], reason: str) -> list[bool]:
    return [case_record.check(name, expected, f"未执行: {reason}", False) for name, expected in names]


def _record_run_metrics(case_record, key: str, run: dict[str, Any]) -> None:
    archive = run["archive"]
    case_record.metric(f"{key}_status", archive.status if archive is not None else "no archive")
    case_record.metric(f"{key}_error", run["error"])
    if archive is None:
        return
    stats = archive.statistics
    case_record.metric(f"{key}_accepted_steps", int(stats["accepted_steps"]))
    case_record.metric(f"{key}_rejected_steps", int(stats["rejected_steps"]))
    case_record.metric(f"{key}_function_evaluations", int(stats["function_evaluations"]))
    case_record.metric(f"{key}_output_samples", int(stats["output_samples"]))
    case_record.metric(f"{key}_wall_time_s", float(run["wall_s"] or 0.0))


def _decimate(values: np.ndarray, every: int) -> list[float]:
    selected = np.asarray(values, dtype=float)[::every]
    return [float(item) for item in selected]


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _ht002_status(case_record) -> dict[str, Any]:
    """Outcome of case HT-002 for the precondition 'HT-002 已通过'.

    When HT-002 ran earlier in the same pytest session, its record in the conftest registry is used, because the
    evidence files are written only at the end of a session. Otherwise ``tests/results/HT-002.json`` is read; it must
    be newer than every source file of the thermal package, so that the pass it records refers to the code under test.
    """

    sources = sorted(THERMAL_PACKAGE.rglob("*.py"))
    newest = max(sources, key=lambda path: path.stat().st_mtime) if sources else None
    info: dict[str, Any] = {
        "newest_thermal_source": newest.relative_to(TESTS_DIR.parent).as_posix() if newest else None,
        "newest_thermal_source_time": _iso(newest.stat().st_mtime) if newest else None,
        "error": None,
    }
    plumbing = sys.modules.get(type(case_record).__module__)
    live = getattr(plumbing, "_RECORDS", {}).get("HT-002")
    if live is not None and live.checks:
        checks = list(live.checks)
        info.update(source="this pytest session", case_id=live.case_id, status=live.resolved_status(),
                    evidence_time=None, newer_than_sources=True)
    else:
        data = None
        for _ in range(HT002_READ_ATTEMPTS):
            try:
                data = json.loads(HT002_EVIDENCE.read_text(encoding="utf-8"))
                break
            except FileNotFoundError:
                info["error"] = "missing"
                break
            except (OSError, ValueError) as exc:  # a file that is being rewritten; read again
                info["error"] = f"{type(exc).__name__}: {exc}"
                time.sleep(0.5)
        info["source"] = "tests/results/HT-002.json"
        if data is None:
            info.update(case_id=None, status=None, evidence_time=None, newer_than_sources=False, n_checks=0,
                        failed=[], passed=False)
            return info
        info["error"] = None
        written = HT002_EVIDENCE.stat().st_mtime
        checks = list(data.get("checks") or [])
        info.update(case_id=data.get("case_id"), status=data.get("status"), evidence_time=_iso(written),
                    newer_than_sources=newest is None or written >= newest.stat().st_mtime)
    failed = [str(check.get("name")) for check in checks if not check.get("passed")]
    info.update(n_checks=len(checks), failed=failed)
    info["passed"] = bool(info["case_id"] == "HT-002" and info["status"] == "pass" and checks and not failed
                          and info["newer_than_sources"])
    return info


# Index of the first check recorded by each test function of this module.
_TEST_STARTS: dict[str, int] = {}


def _current_test() -> str:
    return os.environ.get("PYTEST_CURRENT_TEST", "").split("::")[-1].split(" ")[0]


def _own_failures(case_record) -> list[str]:
    """Names of the failed checks recorded by the running test function only."""

    start = _TEST_STARTS.get(_current_test(), len(case_record.checks))
    return [check["name"] for check in case_record.checks[start:] if not check["passed"]]


# ---------------------------------------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _mark_test_start(request, case_record):
    _TEST_STARTS[request.node.name] = len(case_record.checks)
    yield


@pytest.fixture(scope="module")
def setup() -> tuple[dict[str, Any], Any]:
    config = json.loads((CASE_DIR / "cases.json").read_text(encoding="utf-8"))
    return config, _load_analytic()


@pytest.fixture(scope="module")
def runs(setup) -> dict[str, dict[str, Any]]:
    config, _ = setup
    return {key: _run_case(config, key, case) for key, case in config["cases"].items()}


# ---------------------------------------------------------------------------------------------------------- tests


def test_precondition_ht_002_passed(case_record):
    """前置条件: HT-002 已通过. 取本次会话的 HT-002 记录, 否则取晚于热模块源代码的 tests/results/HT-002.json."""

    info = _ht002_status(case_record)
    if info["source"] == "this pytest session":
        actual = (f"本次 pytest 会话中的 HT-002 记录: status {info['status']}, 检查 {info['n_checks']} 项, "
                  f"未通过 {info['failed'] or '无'}")
    else:
        actual = (f"tests/results/HT-002.json: 读取 {info['error'] or '成功'}; case_id {info['case_id']}, "
                  f"status {info['status']}, 检查 {info['n_checks']} 项, 未通过 {info['failed'] or '无'}; "
                  f"写入时间 {info['evidence_time']}, 热模块源代码最近修改 {info['newest_thermal_source']} "
                  f"{info['newest_thermal_source_time']}, 证据晚于源代码 {info['newer_than_sources']}")
    passed = case_record.check(
        CHECK_HT002,
        "HT-002 的状态为 pass 且全部检查通过; 取本次 pytest 会话中的 HT-002 记录, 本次会话未运行 HT-002 时取 "
        "tests/results/HT-002.json, 该文件须晚于热模块 thermal 全部源代码的最近修改",
        actual, info["passed"])
    case_record.metric("precondition_HT-002", info)
    assert passed, _own_failures(case_record)


def test_preconditions_inputs_and_configuration(setup, runs, case_record):
    """前置条件: RK45 与容限、最大步长已配置并记入归档. 输入: 装配参数与用例输入一致. 配置: 地球反照与红外按第 9.4 节
    记录后关闭. 核对: 运行结束后, 归档中初始时刻与阶跃时刻的温度导数与式 T3 手算一致; 斯忒藩玻尔兹曼常数与 CODATA 一致."""

    config, analytic = setup
    settings = config["solver_settings"]
    results: list[bool] = []

    # 1. integration method, tolerances and maximum step of design table 8, as recorded in every archive
    names = ("method", "rtol", "atol_T_K", "max_step_s", "output_step_s")
    recorded = {}
    ok = True
    for key, run in runs.items():
        archive = run["archive"]
        if archive is None:
            recorded[key] = f"no archive: {run['error']}"
            ok = False
            continue
        values = {name: archive.solver_settings.get(name) for name in names}
        recorded[key] = values
        ok = ok and all(values[name] == settings[name] for name in names)
    results.append(case_record.check(
        CHECK_SOLVER,
        f"三次运行均为 RK45, rtol {settings['rtol']}, atol_T_K {settings['atol_T_K']} K, "
        f"max_step_s {settings['max_step_s']} s, output_step_s {settings['output_step_s']} s",
        recorded, ok))
    for name in names:
        case_record.metric(f"solver_{name}", settings[name])

    # 2. the maximum step bounds every accepted step
    widths = {}
    ok = True
    for key, run in runs.items():
        archive = run["archive"]
        if archive is None or len(archive.steps["t_old_s"]) == 0:
            widths[key] = None
            ok = False
            continue
        width = float(np.max(np.asarray(archive.steps["t_new_s"]) - np.asarray(archive.steps["t_old_s"])))
        widths[key] = width
        ok = ok and width <= settings["max_step_s"] * (1.0 + RELATIVE_EXACT)
    results.append(case_record.check(
        CHECK_MAX_STEP,
        f"每个已接受步长度不超过 {settings['max_step_s']} s, 相对舍入 {RELATIVE_EXACT}",
        {key: (f"{value:.15g} s" if value is not None else "no steps") for key, value in widths.items()}, ok))
    case_record.metric("max_accepted_step_s", widths)

    # 3. assembled capacitances, resistances and exposed surfaces equal the case inputs (hand calculation of T5)
    cp_value = config["specific_heat_J_kgK"]
    node_of = {instance["instance_id"]: instance["node_id"] for instance in config["instances"]}
    expected_surfaces = {surface["surface_id"]: (instance_id, surface)
                         for instance_id, items in config["surfaces"].items() for surface in items}
    details = {}
    ok = True
    for key, run in runs.items():
        case = run["case"]
        parameters = run["parameters"]
        if parameters is None:
            details[key] = f"not assembled: {run['error']}"
            ok = False
            continue
        capacitance = {node: 0.0 for node in NODE_ORDER}
        for instance in config["instances"]:
            capacitance[instance["node_id"]] += case["mass_kg"][instance["instance_id"]] * cp_value
        worst_c = max(_relative(float(parameters.C_J_K[NODE_IX[node]]), capacitance[node]) for node in NODE_ORDER)
        worst_r = max(_relative(float(parameters.R_K_W[PATH_IX[path]]), float(case["resistance_K_W"][path]))
                      for path in PATH_ORDER)
        inputs = case["analytic_inputs"]
        ties = {
            "step": [(capacitance["J"], inputs.get("C_J_J_K")), (case["resistance_K_W"]["JC"], inputs.get("R_JC_K_W"))],
            "series": [(capacitance["J"], inputs.get("C_J_J_K")), (capacitance["C"], inputs.get("C_C_J_K")),
                       (case["resistance_K_W"]["JC"], inputs.get("R_JC_K_W")),
                       (case["resistance_K_W"]["CR"], inputs.get("R_CR_K_W"))],
            "radiation": [(capacitance["R"], inputs.get("C_R_J_K"))],
        }[key]
        tie_ok = all(expected is not None and _relative(value, expected) <= RELATIVE_EXACT for value, expected in ties)
        # every exposed surface carries the node, area, absorptivity and emissivity of the case input
        assembled = {surface.surface_id: surface for surface in parameters.surfaces}
        optics_ok = (
            len(parameters.surfaces) == len(expected_surfaces) and set(assembled) == set(expected_surfaces)
            and all(assembled[surface_id].node_id == node_of[instance_id]
                    and assembled[surface_id].area_m2 == surface["area_m2"]
                    and assembled[surface_id].absorptivity == case["optical"][instance_id]["absorptivity"]
                    and assembled[surface_id].emissivity == case["optical"][instance_id]["emissivity"]
                    for surface_id, (instance_id, surface) in expected_surfaces.items())
        )
        radiator = [surface for surface in parameters.surfaces if surface.node_id == "R"]
        surface_ok = True
        if key == "radiation":
            optical = case["optical"]["Radiator01"]
            front = [surface for surface in radiator if surface.surface_id == "Radiator01_front"]
            surface_ok = (
                abs(sum(surface.area_m2 for surface in radiator) - inputs["radiating_area_m2"]) <= RELATIVE_EXACT
                and len(front) == 1 and abs(front[0].area_m2 - inputs["sunlit_area_m2"]) <= RELATIVE_EXACT
                and all(surface.emissivity == inputs["emissivity"] == optical["emissivity"] for surface in radiator)
                and all(surface.absorptivity == inputs["absorptivity"] for surface in radiator)
            )
        details[key] = {
            "C_J_K": [float(value) for value in parameters.C_J_K],
            "R_K_W": [float(value) for value in parameters.R_K_W],
            "worst_relative_C": worst_c,
            "worst_relative_R": worst_r,
            "analytic_inputs_tied": tie_ok,
            "surface_absorptivity_emissivity": {
                surface_id: [float(surface.absorptivity), float(surface.emissivity)]
                for surface_id, surface in assembled.items()
            },
            "surfaces_equal_case_input": optics_ok,
            "radiator_surfaces_ok": surface_ok,
        }
        ok = (ok and worst_c <= RELATIVE_EXACT and worst_r <= RELATIVE_EXACT and tie_ok and optics_ok and surface_ok)
    results.append(case_record.check(
        CHECK_ASSEMBLY,
        f"C_J_K 与 R_K_W 与质量乘比热及给定热阻的相对误差不超过 {RELATIVE_EXACT}; 四个外露表面的节点、面积、吸收率与"
        "发射率等于用例输入, 太阳能板全部算例与散热板前两个算例为零; 解析参照所用 C_J 500 J/K, R_JC 0.1 K/W 等与"
        "装配记录一致",
        details, ok))
    case_record.metric("assembled_parameters", details)

    # 4. Earth albedo and infrared switched off with the recorded reason of design 9.4, in every archive
    reason = config["environment"]["earth_flux_disabled_reason"]
    expected_note = EARTH_FLUX_NOTE_PREFIX + reason
    recorded_flux = {}
    ok = True
    for key, run in runs.items():
        archive = run["archive"]
        if archive is None:
            recorded_flux[key] = f"no archive: {run['error']}"
            ok = False
            continue
        notes = [note for note in archive.notes if note.startswith(EARTH_FLUX_NOTE_PREFIX)]
        earth = dict(archive.provenance.get("environment", {}).get("earth_flux", {}))
        values_absent = all(earth.get(name) is None for name in ("albedo", "olr_W_m2", "solar_constant_W_m2"))
        run_ok = notes == [expected_note] and earth.get("disabled_reason") == reason and values_absent
        recorded_flux[key] = {"notes": notes, "provenance_earth_flux": earth, "ok": run_ok}
        ok = ok and run_ok
    results.append(case_record.check(
        CHECK_EARTH_FLUX,
        f"三次运行的归档 notes 各含一条 '{expected_note}'; 归档 provenance 的 earth_flux 记录同一关闭原因, "
        "albedo、olr_W_m2 与 solar_constant_W_m2 均无数值",
        recorded_flux, ok))
    case_record.metric("earth_flux_disabled_reason", reason)

    # 5. temperature derivatives against the hand calculation of T3. This runs after the three integrations and reads
    # archive.dT_dt_K_s at the output samples of the initial time and, in the step case, of the step time.
    expected_rates = {}
    actual_rates = {}
    ok = True
    step_run = runs["step"]
    series_run = runs["series"]
    radiation_run = runs["radiation"]
    probes = []
    if step_run["archive"] is not None:
        case = step_run["case"]
        inputs = case["analytic_inputs"]
        T_start = case["initial_temperature_K"]
        # before the step: P_load 0 W and T_J = T_C, so the second line of T3 gives zero
        before = (float(case["load_step"]["before_W"]) - (T_start["J"] - T_start["C"]) / inputs["R_JC_K_W"])
        probes.append(("step 0 s", step_run["archive"], 0.0, "J", before / inputs["C_J_J_K"]))
        probes.append(("step at the step time", step_run["archive"], float(inputs["step_time_s"]), "J",
                       inputs["P_load_W"] / inputs["C_J_J_K"]))
    if series_run["archive"] is not None:
        inputs = series_run["case"]["analytic_inputs"]
        probes.append(("series 0 s", series_run["archive"], 0.0, "J", inputs["P_load_W"] / inputs["C_J_J_K"]))
    if radiation_run["archive"] is not None:
        case = radiation_run["case"]
        inputs = case["analytic_inputs"]
        power = analytic.absorbed_direct_power_W(inputs["absorptivity"], inputs["G_W_m2"], inputs["sunlit_area_m2"],
                                                 inputs["cos_incidence"])
        emitted = inputs["emissivity"] * SIGMA_DESIGN * inputs["radiating_area_m2"] * inputs["T_R0_K"] ** 4
        # T3 last line at t = 0, including the 1e12 K/W isolation paths (about 1e-10 W in total)
        T_start = case["initial_temperature_K"]
        isolation = sum((T_start[path[0]] - T_start["R"]) / case["resistance_K_W"][path]
                        for path in ("SR", "CR", "BR", "DR"))
        probes.append(("radiation 0 s", radiation_run["archive"], 0.0, "R",
                       (isolation + power - emitted) / inputs["C_R_J_K"]))
    if len(probes) != 4:
        ok = False
    for label, archive, moment, node, rate in probes:
        index = int(np.argmin(np.abs(np.asarray(archive.time_s) - moment)))
        sample_time = float(archive.time_s[index])
        derivative = np.asarray(archive.dT_dt_K_s[index], dtype=float)
        others = [derivative[NODE_IX[other]] for other in NODE_ORDER if other != node]
        expected_rates[label] = (f"dT_{node}/dt {rate!r} K/s at {moment} s, relative {RELATIVE_EXACT}; "
                                 "other nodes |dT/dt| <= 1e-12 K/s")
        actual_rates[label] = {"time_s": sample_time, "dT_dt_K_s": [float(value) for value in derivative]}
        ok = (ok and sample_time == moment and _relative(float(derivative[NODE_IX[node]]), rate) <= RELATIVE_EXACT
              and max(abs(value) for value in others) <= 1e-12)
    results.append(case_record.check(
        CHECK_DERIVATIVE,
        expected_rates or "four probes on the archived output samples", actual_rates, ok))

    # 6. Stefan-Boltzmann constant of design table 5 against CODATA (scipy.constants), external cross-check
    sigma_codata = float(scipy_constants.Stefan_Boltzmann)
    results.append(case_record.check(
        CHECK_SIGMA,
        f"设计表5 {SIGMA_DESIGN} W/(m2 K4) 与 scipy.constants 相对差不超过 1e-9",
        f"CODATA {sigma_codata!r}, relative {_relative(SIGMA_DESIGN, sigma_codata):.3e}",
        _relative(SIGMA_DESIGN, sigma_codata) <= 1e-9))
    case_record.metric("sigma_design_W_m2K4", SIGMA_DESIGN)
    case_record.metric("sigma_codata_W_m2K4", sigma_codata)
    case_record.metric("isolation_resistance_K_W", config["large_resistance_K_W"])
    case_record.metric("heat_sink_capacitance_J_K", config["large_capacitance_J_K"])

    assert all(results), _own_failures(case_record)


def test_step1_single_node_step(setup, runs, case_record):
    """测试步骤 1: 积分单节点阶跃, 与指数解比较; 判据: 阶跃响应全程误差不超过 0.001 K."""

    config, analytic = setup
    run = runs["step"]
    case = run["case"]
    inputs = case["analytic_inputs"]
    archive = run["archive"]
    _record_run_metrics(case_record, "step", run)
    results = [case_record.check("步骤1 单节点阶跃运行完成", "status completed, 无错误记录", _status_text(run),
                                 _completed(run))]
    later = [
        ("步骤1 冷板温度保持不变", f"冷板温度变化不超过 {HELD_CONSTANT_LIMIT_K} K"),
        ("步骤1 其余节点保持初值", f"S B D R 温度变化不超过 {UNUSED_NODE_LIMIT_K} K"),
        ("步骤1 负载功率阶跃按设定施加", "100 s 前 P_load 0 W, 100 s 起 300 W, 其余端口 0 W"),
        (CHECK_STEP_SEGMENT, "积分在 100 s 前后分段, 没有已接受步跨越 100 s"),
        ("步骤1 阶跃响应全程误差", f"输出点 已接受状态 加密点上与指数解之差均不超过 {ACCEPT_K} K"),
    ]
    if archive is None:
        results += _not_executed(case_record, later, f"运行未产生归档 {run['error']}")
        assert all(results), run["error"]
        return

    t_step = float(inputs["step_time_s"])
    T_sink = float(inputs["T_C_K"])
    power = float(inputs["P_load_W"])
    resistance = float(inputs["R_JC_K_W"])
    capacitance = float(inputs["C_J_J_K"])

    def reference(times: np.ndarray) -> np.ndarray:
        return analytic.step_response_K(times, step_time_s=t_step, sink_temperature_K=T_sink, power_W=power,
                                        resistance_K_W=resistance, capacitance_J_K=capacitance)

    t_out = np.asarray(archive.time_s, dtype=float)
    T_out = np.asarray(archive.temperature_K, dtype=float)
    t_acc = np.asarray(archive.accepted["time_s"], dtype=float)
    T_acc = np.asarray(archive.accepted["state"], dtype=float)[:, : len(NODE_ORDER)]

    # cold plate held constant: drift against the hand bound P (t_end - t_step) / C_C
    C_sink = case["mass_kg"]["ColdPlate01"] * config["specific_heat_J_kgK"]
    duration = float(case["t_end_s"]) - t_step
    bound = analytic.heat_sink_drift_bound_K(power, duration, C_sink)
    expected_drift = analytic.heat_sink_drift_step_K(power_W=power, resistance_K_W=resistance,
                                                     capacitance_node_J_K=capacitance, capacitance_sink_J_K=C_sink,
                                                     elapsed_s=duration)
    drift_C = max(float(np.max(np.abs(T_out[:, NODE_IX["C"]] - T_sink))),
                  float(np.max(np.abs(T_acc[:, NODE_IX["C"]] - T_sink))))
    results.append(case_record.check(
        later[0][0], f"{later[0][1]}; 手算上界 {bound:.3e} K, 手算终值 {expected_drift:.3e} K",
        f"最大变化 {drift_C:.3e} K", drift_C <= HELD_CONSTANT_LIMIT_K))
    case_record.metric("step_cold_plate_drift_K", drift_C)
    case_record.metric("step_cold_plate_drift_hand_bound_K", bound)
    case_record.metric("step_cold_plate_drift_hand_end_K", expected_drift)

    # nodes that take no part in the case
    initial = np.array([case["initial_temperature_K"][node] for node in NODE_ORDER])
    unused = {node: float(np.max(np.abs(T_out[:, NODE_IX[node]] - initial[NODE_IX[node]])))
              for node in ("S", "B", "D", "R")}
    results.append(case_record.check(later[1][0], later[1][1], {k: f"{v:.3e} K" for k, v in unused.items()},
                                     max(unused.values()) <= UNUSED_NODE_LIMIT_K))

    # the prescribed load step as seen by the thermal model at the output samples
    load = np.asarray(archive.ports_W["P_load_W"], dtype=float)
    before = t_out < t_step
    load_ok = bool(np.all(load[before] == float(case["load_step"]["before_W"])) and np.all(load[~before] == power)
                   and float(case["load_step"]["after_W"]) == power)
    others_zero = all(bool(np.all(np.asarray(archive.ports_W[name]) == 0.0)) for name in ("P_pv_W", "Q_B_W", "Q_D_W"))
    results.append(case_record.check(
        later[2][0], later[2][1],
        f"P_load before {np.unique(load[before]).tolist()} W, from {t_step} s {np.unique(load[~before]).tolist()} W; "
        f"other ports zero {others_zero}", load_ok and others_zero and bool(np.all(archive.sample_valid))))

    # the step is a segment boundary: no accepted step spans it, integration stops and restarts next to it
    t_old = np.asarray(archive.steps["t_old_s"], dtype=float)
    t_new = np.asarray(archive.steps["t_new_s"], dtype=float)
    spanning = int(np.count_nonzero((t_old < t_step) & (t_new > t_step)))
    last_before = float(np.max(t_acc[t_acc < t_step])) if np.any(t_acc < t_step) else float("nan")
    first_after = float(np.min(t_acc[t_acc > t_step])) if np.any(t_acc > t_step) else float("nan")
    gap_ok = (t_step - last_before) <= 1e-9 and (first_after - t_step) <= 1e-9
    results.append(case_record.check(
        later[3][0], later[3][1],
        f"spanning steps {spanning}; last accepted before {last_before!r} s, first after {first_after!r} s; "
        f"segments {[(s['start_s'], s['end_s']) for s in archive.segments]}",
        spanning == 0 and gap_ok))

    # acceptance: error against the exponential solution over the whole run
    error_out = np.abs(T_out[:, NODE_IX["J"]] - reference(t_out))
    error_acc = np.abs(T_acc[:, NODE_IX["J"]] - reference(t_acc))
    grid_step = float(case["dense_grid_step_s"])
    t_grid = np.arange(0.0, float(case["t_end_s"]) + 0.5 * grid_step, grid_step)
    t_grid = t_grid[t_grid <= float(case["t_end_s"])]
    T_grid = np.asarray(archive.state_at(t_grid), dtype=float)[:, NODE_IX["J"]]
    error_grid = np.abs(T_grid - reference(t_grid))
    worst = max(float(error_out.max()), float(error_acc.max()), float(error_grid.max()))
    worst_time = float(t_grid[int(np.argmax(error_grid))])
    results.append(case_record.check(
        later[4][0], later[4][1],
        f"max {worst:.3e} K; output {error_out.max():.3e} K at {t_out.size} samples, accepted {error_acc.max():.3e} K "
        f"at {t_acc.size} states, grid {error_grid.max():.3e} K at {t_grid.size} points, worst at {worst_time} s",
        worst <= ACCEPT_K))
    tau = resistance * capacitance
    case_record.metric("step_time_constant_s", tau)
    case_record.metric("step_steady_rise_K", power * resistance)
    case_record.metric("step_error_max_K", worst)
    case_record.metric("step_error_output_samples_K", float(error_out.max()))
    case_record.metric("step_error_accepted_states_K", float(error_acc.max()))
    case_record.metric("step_error_dense_grid_K", float(error_grid.max()))
    case_record.metric("step_dense_grid_points", int(t_grid.size))
    case_record.metric("step_T_J_end_K", float(T_out[-1, NODE_IX["J"]]))
    case_record.metric("step_T_J_end_analytic_K", float(reference(t_out[-1:])[0]))

    _EVIDENCE["step"] = {
        "description": "single-node step: T_J against T_C + P R_JC (1 - exp(-(t - t_step)/(R_JC C_J)))",
        "analytic_inputs": inputs,
        "time_s": _decimate(t_out, case["series_decimation"]),
        "T_J_numerical_K": _decimate(T_out[:, NODE_IX["J"]], case["series_decimation"]),
        "T_J_analytic_K": _decimate(reference(t_out), case["series_decimation"]),
        "T_C_numerical_K": _decimate(T_out[:, NODE_IX["C"]], case["series_decimation"]),
        "P_load_W": _decimate(load, case["series_decimation"]),
        "error_K": _decimate(error_out, case["series_decimation"]),
        "statistics": dict(archive.statistics),
    }
    assert all(results), _own_failures(case_record)


def test_step2_series_steady_state(setup, runs, case_record):
    """测试步骤 2: 积分串联算例到稳态, T_J - T_R 应等于 P (R_JC + R_CR); 判据: 稳态误差不超过 0.001 K."""

    config, analytic = setup
    run = runs["series"]
    case = run["case"]
    inputs = case["analytic_inputs"]
    archive = run["archive"]
    _record_run_metrics(case_record, "series", run)
    results = [case_record.check("步骤2 串联算例运行完成", "status completed, 无错误记录", _status_text(run),
                                 _completed(run))]
    constants = analytic.series_constants(C_J=inputs["C_J_J_K"], C_C=inputs["C_C_J_K"], R_JC=inputs["R_JC_K_W"],
                                          R_CR=inputs["R_CR_K_W"], power_W=inputs["P_load_W"])
    slow_tau = max(constants["time_constants_s"])
    later = [
        ("步骤2 散热板温度保持不变", f"散热板温度变化不超过 {HELD_CONSTANT_LIMIT_K} K"),
        ("步骤2 其余节点保持初值", f"S B D 温度变化不超过 {UNUSED_NODE_LIMIT_K} K"),
        ("步骤2 积分到稳态", f"终点 J 与 C 的温度变化率乘最慢时间常数 {slow_tau:.6g} s 不超过 {ACCEPT_K} K"),
        ("步骤2 计算节点与散热板稳态温差",
         f"T_J - T_R = P (R_JC + R_CR) = {constants['steady_dT_JR_K']!r} K, 误差不超过 {ACCEPT_K} K"),
        ("步骤2 冷板与散热板稳态温差",
         f"T_C - T_R = P R_CR = {constants['steady_dT_CR_K']!r} K, 误差不超过 {ACCEPT_K} K"),
        ("步骤2 过渡过程与双节点解析解一致", f"输出点与已接受状态上 T_J T_C 与解析解之差不超过 {ACCEPT_K} K"),
    ]
    if archive is None:
        results += _not_executed(case_record, later, f"运行未产生归档 {run['error']}")
        assert all(results), run["error"]
        return

    t_out = np.asarray(archive.time_s, dtype=float)
    T_out = np.asarray(archive.temperature_K, dtype=float)
    t_acc = np.asarray(archive.accepted["time_s"], dtype=float)
    T_acc = np.asarray(archive.accepted["state"], dtype=float)[:, : len(NODE_ORDER)]
    T_R0 = float(inputs["T_R_K"])

    # radiator held constant
    C_sink = case["mass_kg"]["Radiator01"] * config["specific_heat_J_kgK"]
    bound = analytic.heat_sink_drift_bound_K(inputs["P_load_W"], float(case["t_end_s"]), C_sink)
    drift_R = max(float(np.max(np.abs(T_out[:, NODE_IX["R"]] - T_R0))),
                  float(np.max(np.abs(T_acc[:, NODE_IX["R"]] - T_R0))))
    results.append(case_record.check(later[0][0], f"{later[0][1]}; 手算上界 {bound:.3e} K", f"最大变化 {drift_R:.3e} K",
                                     drift_R <= HELD_CONSTANT_LIMIT_K))
    case_record.metric("series_radiator_drift_K", drift_R)
    case_record.metric("series_radiator_drift_hand_bound_K", bound)

    initial = np.array([case["initial_temperature_K"][node] for node in NODE_ORDER])
    unused = {node: float(np.max(np.abs(T_out[:, NODE_IX[node]] - initial[NODE_IX[node]])))
              for node in ("S", "B", "D")}
    results.append(case_record.check(later[1][0], later[1][1], {k: f"{v:.3e} K" for k, v in unused.items()},
                                     max(unused.values()) <= UNUSED_NODE_LIMIT_K))

    # steady state reached at the end of the run
    final_rate = np.asarray(archive.dT_dt_K_s[-1], dtype=float)
    remaining = slow_tau * max(abs(float(final_rate[NODE_IX["J"]])), abs(float(final_rate[NODE_IX["C"]])))
    results.append(case_record.check(
        later[2][0], later[2][1],
        f"t_end {t_out[-1]} s = {t_out[-1] / slow_tau:.1f} 个最慢时间常数; dT_J/dt {final_rate[NODE_IX['J']]:.3e} K/s, "
        f"dT_C/dt {final_rate[NODE_IX['C']]:.3e} K/s; 乘积 {remaining:.3e} K",
        remaining <= ACCEPT_K))
    case_record.metric("series_time_constants_s", list(constants["time_constants_s"]))
    case_record.metric("series_remaining_change_K", remaining)

    # acceptance: T_J - T_R at steady state equals P (R_JC + R_CR)
    dT_JR = float(T_out[-1, NODE_IX["J"]] - T_out[-1, NODE_IX["R"]])
    dT_CR = float(T_out[-1, NODE_IX["C"]] - T_out[-1, NODE_IX["R"]])
    error_JR = abs(dT_JR - constants["steady_dT_JR_K"])
    error_CR = abs(dT_CR - constants["steady_dT_CR_K"])
    results.append(case_record.check(later[3][0], later[3][1], f"数值解 {dT_JR!r} K, 误差 {error_JR:.3e} K",
                                     error_JR <= ACCEPT_K))
    results.append(case_record.check(later[4][0], later[4][1], f"数值解 {dT_CR!r} K, 误差 {error_CR:.3e} K",
                                     error_CR <= ACCEPT_K))
    case_record.metric("series_dT_JR_numerical_K", dT_JR)
    case_record.metric("series_dT_JR_analytic_K", constants["steady_dT_JR_K"])
    case_record.metric("series_dT_JR_error_K", error_JR)
    case_record.metric("series_dT_CR_numerical_K", dT_CR)
    case_record.metric("series_dT_CR_error_K", error_CR)

    # whole transient against the two-node closed form with the radiator at its initial temperature
    def reference(times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return analytic.series_response_K(times, C_J=inputs["C_J_J_K"], C_C=inputs["C_C_J_K"],
                                          R_JC=inputs["R_JC_K_W"], R_CR=inputs["R_CR_K_W"],
                                          power_W=inputs["P_load_W"], T_R_K=T_R0, T_J0_K=inputs["T_J0_K"],
                                          T_C0_K=inputs["T_C0_K"])

    ref_J, ref_C = reference(t_out)
    acc_J, acc_C = reference(t_acc)
    transient = max(float(np.max(np.abs(T_out[:, NODE_IX["J"]] - ref_J))),
                    float(np.max(np.abs(T_out[:, NODE_IX["C"]] - ref_C))),
                    float(np.max(np.abs(T_acc[:, NODE_IX["J"]] - acc_J))),
                    float(np.max(np.abs(T_acc[:, NODE_IX["C"]] - acc_C))))
    results.append(case_record.check(later[5][0], later[5][1],
                                     f"最大差 {transient:.3e} K, {t_out.size} 个输出点, {t_acc.size} 个已接受状态",
                                     transient <= ACCEPT_K))
    case_record.metric("series_transient_error_K", transient)

    every = int(case["series_decimation"])
    _EVIDENCE["series"] = {
        "description": "series J -> C -> R with R held constant: transient against the two-node closed form",
        "analytic_inputs": inputs,
        "time_constants_s": list(constants["time_constants_s"]),
        "time_s": _decimate(t_out, every),
        "T_J_numerical_K": _decimate(T_out[:, NODE_IX["J"]], every),
        "T_C_numerical_K": _decimate(T_out[:, NODE_IX["C"]], every),
        "T_R_numerical_K": _decimate(T_out[:, NODE_IX["R"]], every),
        "T_J_analytic_K": _decimate(ref_J, every),
        "T_C_analytic_K": _decimate(ref_C, every),
        "statistics": dict(archive.statistics),
    }
    assert all(results), _own_failures(case_record)


def test_step3_radiation_balance(setup, runs, case_record):
    """测试步骤 3: 积分辐射平衡算例到稳态, T^4 应等于 P / (eps sigma A); 判据: 稳态误差不超过 0.001 K."""

    _, analytic = setup
    run = runs["radiation"]
    case = run["case"]
    inputs = case["analytic_inputs"]
    archive = run["archive"]
    _record_run_metrics(case_record, "radiation", run)
    results = [case_record.check("步骤3 辐射平衡运行完成", "status completed, 无错误记录", _status_text(run),
                                 _completed(run))]
    power = analytic.absorbed_direct_power_W(inputs["absorptivity"], inputs["G_W_m2"], inputs["sunlit_area_m2"],
                                             inputs["cos_incidence"])
    emissivity = float(inputs["emissivity"])
    area = float(inputs["radiating_area_m2"])
    T_eq = analytic.radiation_equilibrium_K(power, emissivity, area, SIGMA_DESIGN)
    tau = analytic.radiation_time_constant_s(inputs["C_R_J_K"], emissivity, area, SIGMA_DESIGN, T_eq)
    later = [
        (CHECK_RADIATOR_INPUT,
         f"Q_env_R 全程等于手算 {power!r} W, 四条连接流入散热板的热流之和不超过 {ISOLATION_FLOW_LIMIT_W} W"),
        ("步骤3 其余节点保持初值", f"S J C B D 温度变化不超过 {UNUSED_NODE_LIMIT_K} K"),
        (CHECK_JC,
         f"JC 不参与本算例, 装配热阻保持用例值 {case['resistance_K_W']['JC']} K/W; 计算节点与冷板温度相同, "
         f"输出点上 |q_JC| 不超过 {ISOLATION_FLOW_LIMIT_W} W"),
        ("步骤3 积分到稳态", f"终点散热板温度变化率乘线性化时间常数 {tau:.6g} s 不超过 {ACCEPT_K} K"),
        ("步骤3 稳态温度满足辐射平衡",
         f"T_R^4 = P / (eps sigma A), T_R = {T_eq!r} K, 误差不超过 {ACCEPT_K} K"),
        ("步骤3 过渡过程与辐射冷却解析解一致", f"输出点与已接受状态上与隐式解析解之差不超过 {ACCEPT_K} K"),
    ]
    case_record.metric("radiation_input_power_hand_W", power)
    case_record.metric("radiation_T_eq_analytic_K", T_eq)
    case_record.metric("radiation_time_constant_s", tau)
    if archive is None:
        results += _not_executed(case_record, later, f"运行未产生归档 {run['error']}")
        assert all(results), run["error"]
        return

    t_out = np.asarray(archive.time_s, dtype=float)
    T_out = np.asarray(archive.temperature_K, dtype=float)
    t_acc = np.asarray(archive.accepted["time_s"], dtype=float)
    T_acc = np.asarray(archive.accepted["state"], dtype=float)[:, : len(NODE_ORDER)]

    # the radiator has only the fixed input power and its own surface radiation
    Q_env_R = np.asarray(archive.Q_env_W, dtype=float)[:, 1]
    flows = np.asarray(archive.q_W, dtype=float)
    inflow = sum(np.abs(flows[:, PATH_IX[path]]) for path in ("SR", "CR", "BR", "DR"))
    input_error = float(np.max(np.abs(Q_env_R - power))) / power
    results.append(case_record.check(
        later[0][0], later[0][1],
        f"Q_env_R {float(Q_env_R.min())!r} 至 {float(Q_env_R.max())!r} W, 相对差 {input_error:.3e}; "
        f"最大连接热流之和 {float(inflow.max()):.3e} W",
        input_error <= RELATIVE_EXACT and float(inflow.max()) <= ISOLATION_FLOW_LIMIT_W
        and bool(np.all(archive.sample_valid))))
    case_record.metric("radiation_Q_env_R_relative_error", input_error)
    case_record.metric("radiation_max_isolation_inflow_W", float(inflow.max()))

    initial = np.array([case["initial_temperature_K"][node] for node in NODE_ORDER])
    unused = {node: float(np.max(np.abs(T_out[:, NODE_IX[node]] - initial[NODE_IX[node]])))
              for node in ("S", "J", "C", "B", "D")}
    results.append(case_record.check(later[1][0], later[1][1], {k: f"{v:.3e} K" for k, v in unused.items()},
                                     max(unused.values()) <= UNUSED_NODE_LIMIT_K))

    # JC takes no part in this case but keeps its 0.1 K/W: the computing node and the cold plate stay at the same
    # temperature (both see only the 1e12 K/W path CR to the radiator), so JC carries no flow
    R_JC = float(run["parameters"].R_K_W[PATH_IX["JC"]])
    q_JC = float(np.max(np.abs(flows[:, PATH_IX["JC"]])))
    split_out = float(np.max(np.abs(T_out[:, NODE_IX["J"]] - T_out[:, NODE_IX["C"]])))
    split_acc = float(np.max(np.abs(T_acc[:, NODE_IX["J"]] - T_acc[:, NODE_IX["C"]])))
    results.append(case_record.check(
        later[2][0], later[2][1],
        f"装配 R_JC {R_JC!r} K/W; 最大 |q_JC| {q_JC:.3e} W; 最大 |T_J - T_C| 输出点 {split_out:.3e} K, "
        f"已接受状态 {split_acc:.3e} K",
        R_JC == float(case["resistance_K_W"]["JC"]) and q_JC <= ISOLATION_FLOW_LIMIT_W))
    case_record.metric("radiation_R_JC_K_W", R_JC)
    case_record.metric("radiation_max_abs_q_JC_W", q_JC)
    case_record.metric("radiation_max_abs_T_J_minus_T_C_K", max(split_out, split_acc))

    final_rate = float(archive.dT_dt_K_s[-1][NODE_IX["R"]])
    remaining = tau * abs(final_rate)
    results.append(case_record.check(
        later[3][0], later[3][1],
        f"t_end {t_out[-1]} s = {t_out[-1] / tau:.1f} 个时间常数; dT_R/dt {final_rate:.3e} K/s; 乘积 {remaining:.3e} K",
        remaining <= ACCEPT_K))
    case_record.metric("radiation_remaining_change_K", remaining)

    # acceptance: steady temperature against T^4 = P / (eps sigma A)
    T_end = float(T_out[-1, NODE_IX["R"]])
    error_T = abs(T_end - T_eq)
    fourth_power = emissivity * SIGMA_DESIGN * area * T_end**4
    relative_fourth = abs(fourth_power - power) / power
    results.append(case_record.check(
        later[4][0], later[4][1],
        f"数值解 {T_end!r} K, 误差 {error_T:.3e} K; eps sigma A T^4 = {fourth_power!r} W, 与输入功率相对差 "
        f"{relative_fourth:.3e}", error_T <= ACCEPT_K))
    case_record.metric("radiation_T_end_numerical_K", T_end)
    case_record.metric("radiation_T_error_K", error_T)
    case_record.metric("radiation_fourth_power_relative_error", relative_fourth)
    case_record.metric("radiation_Q_emit_R_end_W", float(np.asarray(archive.Q_emit_W)[-1, 1]))

    # whole transient against the implicit closed form of C dT/dt = P - eps sigma A T^4
    def reference(times: np.ndarray) -> np.ndarray:
        return analytic.radiation_response_K(times, capacitance_J_K=inputs["C_R_J_K"], power_W=power,
                                             emissivity=emissivity, area_m2=area, sigma=SIGMA_DESIGN,
                                             T0_K=inputs["T_R0_K"])

    ref_out = reference(t_out)
    ref_acc = reference(t_acc)
    transient = max(float(np.max(np.abs(T_out[:, NODE_IX["R"]] - ref_out))),
                    float(np.max(np.abs(T_acc[:, NODE_IX["R"]] - ref_acc))))
    results.append(case_record.check(later[5][0], later[5][1],
                                     f"最大差 {transient:.3e} K, {t_out.size} 个输出点, {t_acc.size} 个已接受状态",
                                     transient <= ACCEPT_K))
    case_record.metric("radiation_transient_error_K", transient)

    every = int(case["series_decimation"])
    _EVIDENCE["radiation"] = {
        "description": "radiator with a fixed 600 W input and its own emission: transient against the implicit "
                       "closed form",
        "analytic_inputs": inputs,
        "input_power_hand_W": power,
        "T_eq_analytic_K": T_eq,
        "time_s": _decimate(t_out, every),
        "T_R_numerical_K": _decimate(T_out[:, NODE_IX["R"]], every),
        "T_R_analytic_K": _decimate(ref_out, every),
        "Q_env_R_W": _decimate(Q_env_R, every),
        "Q_emit_R_W": _decimate(np.asarray(archive.Q_emit_W, dtype=float)[:, 1], every),
        "statistics": dict(archive.statistics),
    }
    assert all(results), _own_failures(case_record)


# ---------------------------------------------------------------------------------------------------------- summary


_SMALLEST_REPORTED_K = 1e-9
# Characters the Chinese report text must not contain: brackets of any kind, dashes, hyphen-minus, question marks, a
# caret outside the superscript markup and Unicode superscript characters. Powers of ten and unit exponents are written
# 1×10^{−12} and m^{2}: the report builder renders ^{...} as a superscript, so that markup and case identifiers such as
# HT-002 are removed before the scan.
_UNICODE_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"
_FORBIDDEN_TEXT = "()（）[]【】{}<>《》〈〉「」『』—–‐‑‒―-－?？^" + _UNICODE_SUPERSCRIPTS
_SUPERSCRIPT_MARKUP = re.compile(r"\^\{−?[0-9]+\}")
_CASE_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}-[0-9]{3}(?![0-9])")
_UNICODE_POWER_OF_TEN = re.compile(f"10[{_UNICODE_SUPERSCRIPTS}]")
# Status words of the Chinese test report (test_report/build_test_report_cn.py STATUS_CN).
_STATUS_CN = {"pass": "通过", "fail": "不通过", "partial": "部分执行", "not_run": "未执行"}


def _text_problems(text: str) -> list[str]:
    """Breaches of the report text rules in ``text``."""

    stripped = _CASE_IDENTIFIER.sub("", _SUPERSCRIPT_MARKUP.sub("", text))
    problems = sorted({char for char in stripped if char in _FORBIDDEN_TEXT})
    if _UNICODE_POWER_OF_TEN.search(text):
        problems.append("power of ten written with Unicode superscript digits")
    return problems


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _exponent(exponent: int) -> str:
    return f"−{-exponent}" if exponent < 0 else str(exponent)


def _sci(value: Any, significant: int = 2) -> str:
    """'1.8×10^{−6}' with ``significant`` digits and U+2212 signs; the report builder renders ^{...} as superscript."""

    if not _finite(value):
        return "没有数值"
    magnitude = abs(float(value))
    if magnitude == 0.0:
        return "0"
    exponent = math.floor(math.log10(magnitude))
    mantissa = round(magnitude / 10.0**exponent, significant - 1)
    if mantissa >= 10.0:
        exponent += 1
        mantissa = round(magnitude / 10.0**exponent, significant - 1)
    return ("−" if value < 0 else "") + f"{mantissa:.{significant - 1}f}×10^{{{_exponent(exponent)}}}"


def _value(value: Any) -> str:
    """A configured input as the case writes it: shortest decimal, very small or large values as 1×10^{−8}."""

    if not _finite(value):
        return "没有数值"
    text = f"{abs(float(value)):.12g}"
    if "e" in text:
        mantissa, exponent = text.split("e")
        text = f"{mantissa}×10^{{{_exponent(int(exponent))}}}"
    return ("−" if value < 0 else "") + text


def _measured(value: Any) -> str:
    """A measured value with two significant digits: a plain decimal from 0.01 upwards, below that a power of ten."""

    if not _finite(value):
        return "没有数值"
    magnitude = abs(float(value))
    if magnitude == 0.0:
        return "0"
    if magnitude < 0.01:
        return _sci(value)
    digits = max(0, 1 - math.floor(math.log10(magnitude)))
    return ("−" if value < 0 else "") + f"{magnitude:.{digits}f}"


def _phrase_K(value: Any) -> str:
    """'为 1.8×10^{−6} K', or '低于 1×10^{−9} K' below the smallest reported temperature difference."""

    if not _finite(value):
        return "没有数值"
    if abs(float(value)) < _SMALLEST_REPORTED_K:
        return f"低于 {_sci(_SMALLEST_REPORTED_K, 1)} K"
    return f"为 {_measured(value)} K"


def _plain(value: Any, digits: int) -> str:
    if not _finite(value):
        return "没有数值"
    text = f"{abs(float(value)):.{digits}f}"
    return ("−" if value < 0 else "") + text


def _join_paths(paths: tuple[str, ...]) -> str:
    """'SR、CR、BR 与 DR'."""

    items = list(paths)
    return items[0] if len(items) == 1 else "、".join(items[:-1]) + " 与 " + items[-1]


def _ht002_sentence(info: dict[str, Any] | None) -> str:
    """Chinese sentence on the precondition HT-002 已通过, from the metric of test_precondition_ht_002_passed."""

    if not info:
        return "前置条件要求 HT-002 已通过，本次运行没有完成该项核对。"
    if info.get("passed"):
        if info.get("source") == "this pytest session":
            return f"前置条件要求 HT-002 已通过，本次测试会话中 HT-002 的 {info['n_checks']} 项检查全部通过。"
        return (f"前置条件要求 HT-002 已通过，证据文件 tests/results/HT-002.json 记录该用例状态为通过，"
                f"{info['n_checks']} 项检查全部通过，文件写入时间晚于热模块源代码的最近一次修改。")
    error = info.get("error")
    if error == "missing":
        reasons = ["未找到 tests/results/HT-002.json"]
    elif error:
        reasons = ["tests/results/HT-002.json 无法读取"]
    else:
        reasons = []
        if info.get("case_id") != "HT-002":
            reasons.append("证据中的用例编号不是 HT-002")
        if info.get("status") != "pass":
            reasons.append(f"HT-002 的状态为{_STATUS_CN.get(info.get('status'), '未知')}")
        if info.get("failed"):
            reasons.append(f"HT-002 有 {len(info['failed'])} 项检查未通过")
        if not info.get("n_checks"):
            reasons.append("HT-002 没有记录检查")
        if not info.get("newer_than_sources"):
            reasons.append("tests/results/HT-002.json 早于热模块源代码的最近一次修改")
    return "前置条件要求 HT-002 已通过，" + "，".join(reasons or ["该项核对未通过"]) + "，该前置条件未满足。"


_TEST_LABELS = {
    "test_precondition_ht_002_passed": "前置条件 HT-002 核对的测试函数",
    "test_preconditions_inputs_and_configuration": "前置条件、输入与配置核对的测试函数",
    "test_step1_single_node_step": "测试步骤 1 的测试函数",
    "test_step2_series_steady_state": "测试步骤 2 的测试函数",
    "test_step3_radiation_balance": "测试步骤 3 的测试函数",
    "test_summary_and_evidence": "结果说明的测试函数",
}
_WHEN_TEXT = {"setup": "未能开始执行", "call": "未正常结束", "teardown": "在清理阶段出错"}


def _not_run_items(checks: list[dict[str, Any]]) -> list[str]:
    """Names of the checks recorded as not executed because the run they need produced no archive."""

    return [check["name"] for check in checks if not check["passed"] and str(check["actual"]).startswith("未执行")]


def _failed_items(checks: list[dict[str, Any]]) -> list[str]:
    """Chinese names of the failed checks, without those recorded as not executed.

    conftest adds an entry ``"<test function> <phase>"`` for every failed test function. Such an entry is listed in
    Chinese, except when it only repeats the final assertion of a test whose failed checks are already listed.
    """

    items = []
    for index, check in enumerate(checks):
        if check["passed"] or str(check["actual"]).startswith("未执行"):
            continue
        parts = check["name"].split(" ")
        if len(parts) == 2 and parts[0].startswith("test_") and parts[1] in _WHEN_TEXT:
            function, when = parts
            start = _TEST_STARTS.get(function)
            repeated = when == "call" and start is not None and any(
                not other["passed"] and not other["name"].startswith("test_") for other in checks[start:index]
            )
            if not repeated:
                items.append(f"{_TEST_LABELS.get(function, '测试函数')}{_WHEN_TEXT[when]}")
        else:
            items.append(check["name"])
    return items


def test_summary_and_evidence(setup, case_record):
    """结果说明与异常记录 (中文), 以及时程证据文件 tests/results/HT-003_series.json."""

    config, analytic = setup
    step = config["cases"]["step"]
    series = config["cases"]["series"]
    radiation = config["cases"]["radiation"]
    m = case_record.metrics
    if _EVIDENCE:
        RESULTS_DIR.mkdir(exist_ok=True)
        payload = {
            "case_id": "HT-003",
            "description": "Time histories of the three analytic cases of HT-003: numerical solution of "
                           "sdtwin_sim.coupled with RK45 against the analytic references of tests/data/ht_003",
            "solver_settings": config["solver_settings"],
            "cases": _EVIDENCE,
        }
        SERIES_FILE.write_text(json.dumps(payload, ensure_ascii=False, default=float), encoding="utf-8")

    executed = all(key in _EVIDENCE for key in ("step", "series", "radiation"))
    failed = _failed_items(case_record.checks)
    not_run = _not_run_items(case_record.checks)
    # True, False, or "not_run" for a check recorded as not executed; a missing name was not reached either
    outcome = {check["name"]: "not_run" if check["name"] in not_run else check["passed"]
               for check in case_record.checks}

    def claim(names: tuple[str, ...], holds: str, subject: str) -> str:
        """``holds`` when every named check passed, otherwise a sentence that the check failed or was not run."""

        states = [outcome.get(name) for name in names]
        if all(state is True for state in states):
            return holds
        return f"{subject}的核对{'未通过' if any(state is False for state in states) else '未执行'}。"

    settings = config["solver_settings"]
    step_inputs = step["analytic_inputs"]
    series_inputs = series["analytic_inputs"]
    radiation_inputs = radiation["analytic_inputs"]
    # analytic expectations from the inputs, independent of whether the runs completed
    step_tau = step_inputs["R_JC_K_W"] * step_inputs["C_J_J_K"]
    series_constants = analytic.series_constants(C_J=series_inputs["C_J_J_K"], C_C=series_inputs["C_C_J_K"],
                                                 R_JC=series_inputs["R_JC_K_W"], R_CR=series_inputs["R_CR_K_W"],
                                                 power_W=series_inputs["P_load_W"])
    slow_tau = max(series_constants["time_constants_s"])
    rad_power = analytic.absorbed_direct_power_W(radiation_inputs["absorptivity"], radiation_inputs["G_W_m2"],
                                                 radiation_inputs["sunlit_area_m2"], radiation_inputs["cos_incidence"])
    rad_T_eq = analytic.radiation_equilibrium_K(rad_power, radiation_inputs["emissivity"],
                                                radiation_inputs["radiating_area_m2"], SIGMA_DESIGN)
    rad_tau = analytic.radiation_time_constant_s(radiation_inputs["C_R_J_K"], radiation_inputs["emissivity"],
                                                 radiation_inputs["radiating_area_m2"], SIGMA_DESIGN, rad_T_eq)

    # paths that take no part in a case: the 1e12 K/W paths of each case, then JC of the radiation case
    big_R = config["large_resistance_K_W"]
    labels = {"step": "单节点阶跃", "series": "串联", "radiation": "辐射平衡"}
    groups: dict[tuple[str, ...], list[str]] = {}
    for key in ("step", "series", "radiation"):
        isolated = tuple(path for path in PATH_ORDER if config["cases"][key]["resistance_K_W"][path] == big_R)
        if isolated:
            groups.setdefault(isolated, []).append(labels[key])
    isolation = ("不参与算例的连接中，"
                 + " 以及".join(f"{'与'.join(names)}算例的 {_join_paths(paths)}" for paths, names in groups.items())
                 + f" 取 {_value(big_R)} K/W。")
    jc_R = radiation["resistance_K_W"]["JC"]
    if jc_R != big_R:
        isolation += claim(
            (CHECK_JC,),
            f"辐射平衡算例中 JC 也不参与算例，热阻保持 {_value(jc_R)} K/W，两端的计算节点与冷板温度保持相同，"
            f"JC 不传热，实测温差最大为 {_measured(m.get('radiation_max_abs_T_J_minus_T_C_K'))} K，"
            f"热流最大为 {_measured(m.get('radiation_max_abs_q_JC_W'))} W。",
            f"辐射平衡算例中 JC 热阻保持 {_value(jc_R)} K/W，JC 没有热流",
        )

    summary = (
        "本用例按第 8 章表 8 的数值设置，经 sdtwin_sim.coupled 单独运行热模块，积分三个解析算例，四个功率端口取设定值。"
        + _ht002_sentence(m.get("precondition_HT-002"))
        + f"积分方法为 {settings['method']}，相对容限 {_value(settings['rtol'])}，"
        f"温度绝对容限 {_value(settings['atol_T_K'])} K，最大步长 {_value(settings['max_step_s'])} s，"
        f"输出间隔 {_value(settings['output_step_s'])} s，"
        + claim((CHECK_SOLVER, CHECK_MAX_STEP),
                "归档记录了这些设置，全部已接受步的长度在舍入误差内不超过最大步长。",
                "这些设置的归档记录与最大步长")
        + isolation
        + "不参与算例的功率端口取 0 W，太阳能板以及前两个算例中散热板的外露表面吸收率与发射率取零。"
        f"单节点阶跃算例的冷板与串联算例的散热板需要保持温度不变，热容取 {_value(config['large_capacitance_J_K'])} J/K。"
        + claim((CHECK_ASSEMBLY,), "装配所得的热容、热阻与外露表面参数与这些输入一致。", "装配所得参数与这些输入")
        + claim((CHECK_EARTH_FLUX,), "地球反照与红外按第 9.4 节记录后关闭，三次运行的归档均记有关闭原因。",
                "地球反照与红外按第 9.4 节关闭，归档中关闭原因")
        + claim((CHECK_DERIVATIVE,), "核对了归档中初始时刻与阶跃时刻的温度导数，与式 T3 手算一致。",
                "归档中初始时刻与阶跃时刻的温度导数与式 T3 手算")
        + f"单节点阶跃算例中计算节点热容 {_value(step_inputs['C_J_J_K'])} J/K，"
        f"JC 热阻 {_value(step_inputs['R_JC_K_W'])} K/W，计算节点功率在 {_value(step_inputs['step_time_s'])} s 时"
        f"由 {_value(step['load_step']['before_W'])} W 阶跃到 {_value(step_inputs['P_load_W'])} W，"
        f"时间常数为 {_value(step_tau)} s，积分到 {_value(step['t_end_s'])} s，"
        + claim((CHECK_STEP_SEGMENT,), "积分在阶跃时刻分段。", "积分在阶跃时刻分段")
        + f"在 {_value(settings['output_step_s'])} s 输出点、全部已接受状态以及按 {_value(step['dense_grid_step_s'])} s "
        f"间隔加密的时刻上与指数解比较，全程最大误差{_phrase_K(m.get('step_error_max_K'))}，"
        f"判据为 {_value(ACCEPT_K)} K，冷板温度变化{_phrase_K(m.get('step_cold_plate_drift_K'))}。"
        f"串联算例中计算节点热容 {_value(series_inputs['C_J_J_K'])} J/K，JC 热阻 {_value(series_inputs['R_JC_K_W'])} K/W，"
        f"计算节点功率 {_value(series_inputs['P_load_W'])} W，冷板热容 {_value(series_inputs['C_C_J_K'])} J/K，"
        f"CR 热阻 {_value(series_inputs['R_CR_K_W'])} K/W，积分 {_value(series['t_end_s'])} s，"
        f"约为 {_plain(series['t_end_s'] / slow_tau, 0)} 个最慢时间常数，"
        f"散热板温度变化{_phrase_K(m.get('series_radiator_drift_K'))}。"
        f"计算节点与散热板温差为 {_plain(m.get('series_dT_JR_numerical_K'), 8)} K，"
        f"解析值为 {_value(series_constants['steady_dT_JR_K'])} K，误差{_phrase_K(m.get('series_dT_JR_error_K'))}，"
        f"判据为 {_value(ACCEPT_K)} K，冷板与散热板温差的误差{_phrase_K(m.get('series_dT_CR_error_K'))}，"
        f"过渡过程与双节点解析解之差{_phrase_K(m.get('series_transient_error_K'))}。"
        f"辐射平衡算例中散热板正面吸收率 {_value(radiation_inputs['absorptivity'])}，正面面积 "
        f"{_value(radiation_inputs['sunlit_area_m2'])} m^{{2}}，正面朝向太阳，受 {_value(radiation_inputs['G_W_m2'])} W/m^{{2}} "
        f"太阳直射，吸收固定功率 {_value(rad_power)} W，"
        f"两面发射率 {_value(radiation_inputs['emissivity'])}，辐射面积 {_value(radiation_inputs['radiating_area_m2'])} m^{{2}}。"
        + claim((CHECK_RADIATOR_INPUT,),
                "散热板全程只有这一固定输入功率与自身表面辐射，SR、CR、BR 与 DR 流入散热板的热流绝对值之和最大为 "
                f"{_measured(m.get('radiation_max_isolation_inflow_W'))} W。",
                "散热板只有固定输入功率与自身表面辐射")
        + claim((CHECK_SIGMA,),
                f"斯忒藩玻尔兹曼常数取第 4.4 节表 5 的值 {_value(SIGMA_DESIGN)} W·m^{{−2}}·K^{{−4}}，与 CODATA 推荐值一致。",
                "斯忒藩玻尔兹曼常数与 CODATA 推荐值")
        + f"散热板由 {_value(radiation_inputs['T_R0_K'])} K 积分 {_value(radiation['t_end_s'])} s，"
        f"约为 {_plain(radiation['t_end_s'] / rad_tau, 0)} 个线性化时间常数，稳态温度为 "
        f"{_plain(m.get('radiation_T_end_numerical_K'), 6)} K，解析值为 {_plain(rad_T_eq, 6)} K，"
        f"误差{_phrase_K(m.get('radiation_T_error_K'))}，判据为 {_value(ACCEPT_K)} K，"
        f"过渡过程与隐式解析解之差{_phrase_K(m.get('radiation_transient_error_K'))}。"
        + ("三个算例的数值解与解析解一致。" if executed and not failed and not not_run
           else "部分检查未通过或未执行，见异常记录。")
    )
    case_record.summary(summary)
    if failed or not_run or not executed:
        parts = []
        if failed:
            parts.append("以下检查未通过：" + "；".join(failed) + "。")
        if not_run:
            parts.append("以下检查因运行没有产生归档而未执行：" + "；".join(not_run) + "。")
        if not executed:
            labels = (("step", "单节点阶跃"), ("series", "串联稳态"), ("radiation", "辐射平衡"))
            missing = [label for key, label in labels if key not in _EVIDENCE]
            parts.append("以下算例未完成与解析解的比较：" + "、".join(missing) + "。")
        anomalies = "".join(parts)
    else:
        anomalies = "无"
    case_record.anomalies(anomalies)
    # Report text rules: no brackets, dashes, hyphen-minus, question marks or Unicode superscript powers of ten.
    problems = _text_problems(summary) + _text_problems(anomalies)
    assert not problems, f"summary or anomalies break the report text rules: {problems}"
    # The step tests assert their own checks; this test also fails when the evidence could not be written.
    assert not _EVIDENCE or SERIES_FILE.exists()
