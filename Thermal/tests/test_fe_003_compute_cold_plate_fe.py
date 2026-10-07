"""FE-003 计算节点与冷板有限元对标: computing node J and cold plate C against the ISS FE cold-plate equipment.

Implements the CASES entry FE-003 of Thermal/test_report/build_test_report_cn.py (thermal design 4.3 T3 second and
third lines, 4.5 T5, chapter 10; requirements TH-01 and TH-04).

Preconditions: the FE component statistics and loop heat breakdown of the mean environment case (nom0) are available;
the cold plate takes a very large capacitance and starts at the coolant temperature and CR takes a very large
resistance, so the cold-plate temperature stays at the coolant temperature like the FE cold-plate boundary. Per thermal
design 9.4 this test configuration is recorded with every run; a check reads the resolved values, their source, the
cold-plate asset and the initial state back from each run archive.
Inputs: MBSU 495 W with a 0.79 m2 cold plate, DDCU 694 W with 0.56 m2, IEA 6000 W with 13.5 m2; cold-plate
conductance 60 W/m2K, equivalent conductivity 150 W/mK, coolant 2.8 C; P_load is the heat that leaves through the cold
plate in the FE. The FE writes that heat per cooling loop: each IEA has a loop of its own, while the MBSU and DDCU of a
loop take their block heat times one loop share, an approximation. The case text says about 5.4 percent of the block
heat leaves through the MLI; the test compares the loop remainder with that number and does not split it. In the FE the
remainder is the radiation of the MLI outer faces plus the heat still stored in blocks that warm through the third orbit
(the hottest DDCU point still rises over that orbit), so the test does not describe it as MLI radiation alone.
Steps: 1 R_JC from the second line of T5, contact part 1 / (h A) and conduction part with one third of the device
thickness as length (the equivalent length of the mean temperature for uniform heat generation); 2 integrate to steady
state, where T_J = T_C + P_load R_JC; 3 compare with the FE third-orbit mean temperature.
Expected: the mean temperatures of the three device classes agree with the FE. Acceptance: within 1 K.

The real module runs: assemble_thermal_parameters builds the six-node parameters (J is the FE device, C the cold-plate
boundary), and sdtwin_sim.coupled.run_coupled integrates them with thermal_derivative in every trial (thermal-only run
with prescribed ports) in the FE orbit environment, whose Earth albedo and infrared for the auxiliary S and R surfaces
come from sdtwin_sim.earth_flux. Statistics are time weighted over the exact last orbital period. Every reference is
independent of the module: FE results (iss_fem/out/nom0), the FE parameter table (iss_fem/model/iss_spec.py), hand T5
values, a finite-volume conduction solution and the closed-form exponential response (tests/data/fe_003/fe003_support.py).

A NaN never passes: aggregates use _worst, which propagates NaN, and every limit comparison needs a finite value. The
Chinese summary states only what the recorded checks support, with limits read from the configuration, and the record
test writes summary and anomalies after every check of the case, also when a part of the evidence fails.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from sdtwin_sim import coupled as cp
from sdtwin_sim.earth_flux import earth_flux_record
from thermal import ThermalState, assemble_thermal_parameters
from thermal.types import NODE_ORDER, PATH_ORDER

pytestmark = pytest.mark.case("FE-003")

THERMAL_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data" / "fe_003"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load_support():
    spec = importlib.util.spec_from_file_location("fe003_support", DATA_DIR / "fe003_support.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load_support()
CFG = sup.load_json(DATA_DIR / "fe003_config.json")
CRIT = CFG["criteria"]
SOLVER = CFG["solver"]
SOLVER_KEYS = ("method", "rtol", "atol_T_K", "max_step_s", "output_step_s", "environment_step_s", "event_time_tol_s")
DEVICES = tuple(CFG["device_order"])
I_S, I_J, I_C, I_R = (NODE_ORDER.index(node) for node in ("S", "J", "C", "R"))
I_JC, I_CR = PATH_ORDER.index("JC"), PATH_ORDER.index("CR")
K0 = sup.KELVIN_OFFSET
ACCEPT_K = float(CRIT["acceptance_K"])
# unit markup of the CASES text; the report builder sets ^{...} as a superscript
UNIT_H = "W·m^{−2}·K^{−1}"
UNIT_K = "W·m^{−1}·K^{−1}"
# test functions of this module with their Chinese labels for the summary and the anomaly record
STEP_FUNCTIONS = {
    "test_fe003_preconditions_and_inputs": "前置条件与输入",
    "test_fe003_step1_r_jc": "步骤1",
    "test_fe003_step2_steady_state": "步骤2",
    "test_fe003_step3_fe_comparison": "步骤3",
    "test_fe003_record": "证据记录",
}
PHASES_CN = {"setup": "准备阶段", "call": "执行阶段", "teardown": "清理阶段"}
OUTCOME: dict = {"inputs": {}, "step1": {}, "step2": {}, "step3": {}, "eclipse": {}, "started": set(), "counts": {}}


# ------------------------------------------------------------------------------------------------ helpers


def _worst(values) -> float:
    """Largest value with NaN propagated and +inf for no values, so a comparison with a limit then fails.

    The built-in max drops a NaN unless it comes first (max(0.2, nan) is 0.2); it must not aggregate values that are
    compared with a limit.
    """

    array = np.asarray([float(value) for value in values], dtype=float)
    if array.size == 0:
        return float("inf")
    if np.isnan(array).any():
        return float("nan")
    return float(np.max(array))


def _within(value: float, limit: float) -> bool:
    """value <= limit for a finite value only."""

    value = float(value)
    return math.isfinite(value) and value <= limit


def _finite_row(row: dict) -> bool:
    """A step 3 row with a module result and finite module mean, FE mean and difference."""

    return "diff_K" in row and all(math.isfinite(float(row[name])) for name in ("module_mean_C", "fe_Tmean_C", "diff_K"))


def _start(name: str) -> None:
    OUTCOME["started"].add(name)


def _require_setup(fe003) -> None:
    if fe003.get("setup_error"):
        pytest.fail(f"FE-003 set-up did not complete: {fe003['setup_error']}", pytrace=False)


def _count(name: str, results: list[bool]) -> None:
    OUTCOME["counts"][name] = [len(results), int(sum(1 for result in results if result))]


# Chinese text: design symbols as $...$ like the CASES text, U+2212 minus signs, powers of ten as 1×10^{−12}

_SYMBOLS = re.compile(r"(?<![\w$])(R_JC|R_CR|P_load|T_J|T_C|C_J|C_C|q_JC|q_CR)(?![\w$])")


def _markup(text: str) -> str:
    return _SYMBOLS.sub(lambda match: f"${match.group(1)}$", text)


def _num(value: float, digits: int) -> str:
    return sup.num(value, digits) if math.isfinite(float(value)) else "非有限值"


def _sci(value: float) -> str:
    return sup.sci(value) if math.isfinite(float(value)) else "非有限值"


def _limit(value: float) -> str:
    """A configured limit: plain from 0.001 to below 10000, otherwise a×10^{n}."""

    value = float(value)
    return f"{value:g}" if 1e-3 <= abs(value) < 1e4 else sup.sci_exact(value)


def _class_range(values: list[float], digits: int, unit: str) -> str:
    if not values or not all(math.isfinite(float(value)) for value in values):
        return "非有限值"
    low, high = min(values), max(values)
    gap = "" if unit in ("", "%") else " "
    if sup.num(low, digits) == sup.num(high, digits):
        return f"{sup.num(low, digits)}{gap}{unit}"
    return f"{sup.num(low, digits)} 至 {sup.num(high, digits)}{gap}{unit}"


def _count_text(name: str) -> str:
    label = STEP_FUNCTIONS[name]
    total, good = OUTCOME["counts"].get(name, (0, 0))
    if total and good == total:
        return f"{label}的 {total} 项检查全部通过"
    if total:
        return f"{label}有 {total - good} 项检查未通过，见异常记录"
    return _missing_text(name)


def _missing_text(name: str) -> str:
    label = STEP_FUNCTIONS[name]
    return f"{label}未执行" if name not in OUTCOME["started"] else f"{label}没有完成，见异常记录"


# ------------------------------------------------------------------------------------------------ FE data and inputs


def _fe_inputs(spec, blocks, breakdown) -> dict:
    """Device blocks, FE parameters and P_load of every FE item of the three device classes."""

    names = CFG["fe_parameter_names"]
    devices = {cls: [b for b in blocks if b["name"].startswith(CFG["devices"][cls]["item_prefix"])] for cls in DEVICES}
    h = sup.parse_quantity(spec.PARAMS[names["h_cold_plate"]][0], "W/(m^2*K)")
    material = dict(spec.MATERIALS[names["material"]])
    set_points = {}
    for cls in DEVICES:
        for block in devices[cls]:
            set_points[block["name"]] = sup.parse_fahrenheit_set_point_K(spec.PARAMS[block["cool"]["T"]][0])
    # loop group 'oru' of the FE breakdown: cooled blocks of class box that are not IEA (iss_fem/model/iss_layout.py)
    oru_members: dict[str, list[dict]] = {}
    for block in blocks:
        cool = block.get("cool")
        if cool and block["cls"] == "box" and not block["name"].startswith("IEA"):
            oru_members.setdefault(cool["loop"], []).append(block)
    shares = {}
    for loop, members in oru_members.items():
        total = math.fsum(float(member["Q"]) for member in members)
        heat = breakdown[(loop, "oru")]["W_mean"]
        shares[loop] = {"members": [member["name"] for member in members], "Q_total_W": total,
                        "cold_plate_W": heat, "share": heat / total}
    iea_members: dict[str, list[str]] = {}
    for block in blocks:
        cool = block.get("cool")
        if cool and block["name"].startswith("IEA"):
            iea_members.setdefault(cool["loop"], []).append(block["name"])
    loads = {}
    for cls in DEVICES:
        for block in devices[cls]:
            loop = block["cool"]["loop"]
            if CFG["devices"][cls]["breakdown_source"] == "oru":
                share = shares[loop]["share"]
                loads[block["name"]] = {
                    "P_load_W": float(block["Q"]) * share, "loop": loop, "share": share,
                    "rule": f"block heat {block['Q']} W times the loop {loop} cold-plate share {share:.6f}",
                }
            else:
                heat = breakdown[(loop, "iea")]["W_mean"]
                loads[block["name"]] = {
                    "P_load_W": heat, "loop": loop, "share": heat / float(block["Q"]),
                    "rule": f"cold-plate heat of loop {loop} group iea, {heat:.3f} W",
                }
    return {"devices": devices, "h_W_m2K": h, "material": material, "set_points": set_points, "shares": shares,
            "iea_members": iea_members, "loads": loads}


def _run_groups(inputs: dict) -> dict:
    """One run per device class and cooling loop: items of a group share size, power, face, set point and P_load."""

    groups: dict[str, dict] = {}
    for cls in DEVICES:
        for block in inputs["devices"][cls]:
            load = inputs["loads"][block["name"]]
            key = f"{cls}_{load['loop']}"
            group = groups.setdefault(key, {"device": cls, "loop": load["loop"], "block": block, "items": [],
                                            "P_load_W": load["P_load_W"]})
            group["items"].append(block["name"])
            reference = group["block"]
            same = (list(block["size"]) == list(reference["size"]) and block["Q"] == reference["Q"]
                    and block["cool"] == reference["cool"] and load["P_load_W"] == group["P_load_W"])
            if not same:
                raise AssertionError(f"FE item {block['name']} differs from {reference['name']} inside group {key}")
    return groups


# ------------------------------------------------------------------------------------------------ model set-up


def _components_and_connections(group: dict, inputs: dict, T_cool_K: float) -> tuple[list, list, dict]:
    block = group["block"]
    material = inputs["material"]
    area, thickness = sup.cold_plate_geometry(block["size"], block["cool"]["face"])
    hand = sup.hand_r_jc(inputs["h_W_m2K"], material["k"], area, thickness)
    volume = float(np.prod(np.array(block["size"], dtype=float)))
    mass = volume * material["rho"]
    node = CFG["compute_node"]
    spec_source = (f"iss_fem/model/iss_spec.py: {group['device']} block {block['name']} size {block['size']} m, "
                   f"heat {block['Q']} W, cold-plate face {block['cool']['face']}; MATERIALS oru_eq rho "
                   f"{material['rho']} kg/m3, cp {material['cp']} J/kgK, k {material['k']} W/mK")
    components = [
        {
            "instance_id": node["instance_id"], "node_id": "J",
            "asset_id": f"fe003_iss_{group['device'].lower()}", "asset_version": node["asset_version"],
            "materials": [{"material_id": f"{node['instance_id']}_{group['device']}_oru_eq", "mass_kg": mass,
                           "cp_J_kgK": material["cp"], "source": spec_source}],
            "surfaces": [], "temperature_range_K": node["temperature_range_K"], "ports": ["P_load_W"],
        },
    ]
    plate = CFG["cold_plate"]
    components.append({
        "instance_id": plate["instance_id"], "node_id": "C", "asset_id": plate["asset_id"],
        "asset_version": plate["asset_version"],
        "materials": [{"material_id": plate["material_id"], "mass_kg": plate["mass_kg"], "cp_J_kgK": plate["cp_J_kgK"],
                       "source": plate["source"]}],
        "surfaces": [], "temperature_range_K": plate["temperature_range_K"], "ports": [],
    })
    aux = CFG["auxiliary_nodes"]
    for item in aux["components"]:
        components.append({
            "instance_id": item["instance_id"], "node_id": item["node_id"],
            "asset_id": f"fe003_aux_{item['instance_id'].lower()}", "asset_version": "1",
            "materials": [{"material_id": f"{item['instance_id']}_aux_material", "mass_kg": item["mass_kg"],
                           "cp_J_kgK": item["cp_J_kgK"], "source": aux["source"]}],
            "surfaces": [dict(surface, source=aux["source"]) for surface in item.get("surfaces", [])],
            "temperature_range_K": aux["temperature_range_K"], "ports": item["ports"],
        })
    connections = [
        {"path": "JC", "length_m": hand["length_m"], "conductivity_W_mK": material["k"], "area_m2": area,
         "contact_resistance_K_W": hand["contact_K_W"],
         "source": (f"FE-003 step 1, T5 second line: contact part 1/(h A) with h_cp_oru {inputs['h_W_m2K']} W/m2K and "
                    f"the cold-plate face {area:.4f} m2; conduction length one third of the thickness "
                    f"{thickness} m with oru_eq k {material['k']} W/mK")},
        {"path": "CR", "equivalent_total_resistance_K_W": plate["CR_equivalent_total_resistance_K_W"],
         "includes_contact": True, "source": plate["source"]},
    ]
    for path, value in aux["resistances_K_W"].items():
        connections.append({"path": path, "equivalent_total_resistance_K_W": value, "includes_contact": True,
                            "source": aux["source"]})
    geometry = {"area_m2": area, "thickness_m": thickness, "volume_m3": volume, "mass_kg": mass,
                "C_J_hand_J_K": mass * material["cp"], **hand}
    return components, connections, geometry


def _settings() -> cp.SolverSettings:
    return cp.SolverSettings(method=SOLVER["method"], rtol=SOLVER["rtol"], atol_T_K=SOLVER["atol_T_K"],
                             max_step_s=SOLVER["max_step_s"], output_step_s=SOLVER["output_step_s"],
                             environment_step_s=SOLVER["environment_step_s"],
                             event_time_tol_s=SOLVER["event_time_tol_s"])


def _run(key: str, group: dict, params, orbit, env: dict, T_cool_K: float, T_J0_K: float, t_end: float) -> dict:
    run_id = f"FE-003-{CFG['fe']['case']}-{key}"
    G = orbit.irradiance(env["S_sun"])
    earth = cp.EarthFluxModel(albedo=env["albedo"], olr_W_m2=env["olr"], solar_constant_W_m2=env["S_sun"],
                              earth_radius_m=orbit.earth_radius_m,
                              resolution=tuple(CFG["environment"]["earth_flux_resolution"]))
    provider = cp.EnvironmentProvider.from_callables(
        run_id=run_id, epoch=datetime.fromisoformat(CFG["environment"]["epoch_utc"]), parameters=params,
        position=orbit.position, sun_position=orbit.sun_position, quaternion=orbit.quaternion, G=G, earth_flux=earth)
    aux_T = float(CFG["auxiliary_nodes"]["initial_temperature_K"])
    initial = ThermalState(run_id, 0.0, [aux_T, T_J0_K, T_cool_K, aux_T, aux_T, aux_T])
    load = float(group["P_load_W"])

    def prescribed_ports(t: float) -> dict:
        return {"P_pv_W": 0.0, "P_load_W": load, "Q_B_W": 0.0, "Q_D_W": 0.0}

    prescribed_ports.__name__ = f"fe003_ports_{key}"
    provenance = {
        "case_id": "FE-003", "fe_case": CFG["fe"]["case"], "fe_label_cn": CFG["fe"]["label_cn"],
        "device": group["device"], "loop": group["loop"], "fe_items": list(group["items"]),
        "P_load_rule": "P_load_W is the FE orbit 3 heat leaving through the cold plate (loop_breakdown.csv): the loop "
                       "iea heat for an IEA, the block heat times the loop oru share for an MBSU or DDCU (the FE writes "
                       "the cold-plate heat per loop); P_pv_W = Q_B_W = Q_D_W = 0",
        "cold_plate": CFG["cold_plate"]["source"], "auxiliary_nodes": CFG["auxiliary_nodes"]["note"],
        "environment": f"FE orbit functions of summary.json, cylindrical shadow along sun_ecs, {CFG['environment']['attitude']}; "
                       f"{CFG['environment']['resolution_note']}",
        "initial_temperature_J": CFG["compute_node"]["initial_temperature_source"],
        "epoch_note": CFG["environment"]["epoch_note"],
    }
    started = time.perf_counter()
    error = None
    try:
        archive = cp.run_coupled(params, initial, provider, t_end, settings=_settings(),
                                 prescribed_ports=prescribed_ports, provenance=provenance)
    except cp.CoupledRunError as exc:
        archive, error = exc.archive, f"{type(exc).__name__}: {exc}"
    return {"run_id": run_id, "archive": archive, "error": error, "wall_s": time.perf_counter() - started,
            "t_end": t_end, "T_cool_K": T_cool_K, "T_J0_K": T_J0_K, "P_load_W": load, "G": G}


def _prepare(started: float) -> dict:
    fe = CFG["fe"]
    spec = sup.load_spec(THERMAL_DIR / fe["spec_file"])
    fe_dir = THERMAL_DIR / fe["out_dir"] / fe["case"]
    items = sup.read_items(fe_dir / fe["items_file"])
    breakdown = sup.read_breakdown(fe_dir / fe["breakdown_file"])
    summary = sup.load_json(fe_dir / fe["summary_file"])
    series = sup.read_series(fe_dir / fe["series_file"], [fe["time_column"], fe["box_class_column"], "box_Tmax_C"])
    orbit = sup.FEOrbit(summary["orbit"], spec.ORBIT["R_earth_m"])
    blocks = spec.layout(fe["case"])["blocks"]
    inputs = _fe_inputs(spec, blocks, breakdown)
    groups = _run_groups(inputs)
    set_points = {value[0] for value in inputs["set_points"].values()}
    T_cool = min(set_points)
    T_J0 = float(spec.T_INIT[CFG["fe_parameter_names"]["initial_temperature_class"]])
    t_end = int(CFG["run"]["orbits"]) * orbit.period_s
    env = dict(spec.CASES[fe["case"]])
    runs = {}
    for key, group in groups.items():
        components, connections, geometry = _components_and_connections(group, inputs, T_cool)
        entry = {"group": group, "geometry": geometry, "components": components, "connections": connections}
        try:
            entry["params"] = assemble_thermal_parameters(components, connections, None)
        except Exception as exc:  # noqa: BLE001  (recorded as a failed check by the tests)
            entry["params"] = None
            entry["assembly_error"] = f"{type(exc).__name__}: {exc}"
            runs[key] = entry
            continue
        try:
            entry["result"] = _run(key, group, entry["params"], orbit, env, T_cool, T_J0, t_end)
        except Exception as exc:  # noqa: BLE001
            entry["result"] = None
            entry["run_error"] = f"{type(exc).__name__}: {exc}"
        runs[key] = entry
    return {"spec": spec, "items": items, "breakdown": breakdown, "summary": summary, "series": series,
            "orbit": orbit, "blocks": blocks, "inputs": inputs, "groups": groups, "runs": runs,
            "set_points": inputs["set_points"], "T_cool_K": T_cool, "T_J0_K": T_J0, "t_end": t_end, "env": env,
            "setup_wall_s": time.perf_counter() - started}


@pytest.fixture(scope="module")
def fe003():
    """FE data, inputs and the runs of every group. It never raises: a failure is returned as setup_error, every test
    then fails with it and the record test still writes the summary and the anomaly record."""

    started = time.perf_counter()
    try:
        return _prepare(started)
    except Exception as exc:  # noqa: BLE001
        return {"setup_error": f"{type(exc).__name__}: {exc}", "setup_error_type": type(exc).__name__, "runs": {},
                "setup_wall_s": time.perf_counter() - started}


# ------------------------------------------------------------------------------------------------ preconditions and inputs


def _plate_record(archive, T_cool: float) -> dict:
    """What a run archive holds about the cold-plate test configuration (thermal design 9.4).

    9.4: the resolved parameters, their sources, the initial values and the environment are saved before the start,
    and example, measured and fitted values are marked apart; the very large C_C and R_CR are test values, not device
    data. The archive provenance carries the assembled parameter record and the caller record of the run, and the
    first accepted state is the initial state.
    """

    plate = CFG["cold_plate"]
    C_plate = plate["mass_kg"] * plate["cp_J_kgK"]
    R_plate = plate["CR_equivalent_total_resistance_K_W"]
    provenance = archive.provenance
    parameters = provenance["thermal_parameters"]
    capacitance = parameters["capacitance"]["C"]
    portions = list(capacitance["portions"])
    portion = dict(portions[0]) if len(portions) == 1 else {}
    resistance = parameters["resistance"]["CR"]
    asset = dict(parameters["assets"].get(plate["instance_id"], {}))
    values = provenance["thermal_values"]
    t0 = float(archive.accepted["time_s"][0])
    T_C0 = float(archive.accepted["state"][0][I_C])
    flags = {
        "C_C_value": capacitance["value_J_K"] == C_plate and values["C_J_K"]["C"] == C_plate,
        "C_C_portion": (portion.get("instance_id") == plate["instance_id"]
                        and portion.get("material_id") == plate["material_id"]
                        and portion.get("mass_kg") == plate["mass_kg"] and portion.get("cp_J_kgK") == plate["cp_J_kgK"]),
        "C_C_source": portion.get("source") == plate["source"],
        "R_CR_value": (resistance["value_K_W"] == R_plate and values["R_K_W"]["CR"] == R_plate
                       and resistance["method"] == "equivalent_total"
                       and dict(resistance["inputs"]) == {"equivalent_total_resistance_K_W": R_plate,
                                                          "includes_contact": True}),
        "R_CR_source": resistance["source"] == plate["source"],
        "asset": asset.get("asset_id") == plate["asset_id"] and asset.get("asset_version") == plate["asset_version"],
        "no_override": len(parameters["overrides_applied"]) == 0,
        "initial_T_C": t0 == float(archive.t_start_s) and T_C0 == T_cool,
        "caller_record": provenance["caller"].get("cold_plate") == plate["source"],
    }
    lead = plate["source"].split(":")[0]
    text = (f"run_id {archive.run_id}，UTC 起点 {archive.epoch.isoformat()}；归档 C_C {float(values['C_J_K']['C']):.3e} J/K，"
            f"材料 {portion.get('material_id')} 属于 {portion.get('instance_id')}，质量 {portion.get('mass_kg')} kg，"
            f"比热 {portion.get('cp_J_kgK')} J/(kg·K)；R_CR {float(values['R_K_W']['CR']):.3e} K/W，方法 "
            f"{resistance['method']}，输入 {dict(resistance['inputs'])}；冷板材料来源与配置一致 {flags['C_C_source']}，"
            f"CR 来源与配置一致 {flags['R_CR_source']}，来源开头 '{lead}'；冷板资产 {asset.get('asset_id')} 版本 "
            f"{asset.get('asset_version')}；参数覆盖 {len(parameters['overrides_applied'])} 项；t = {t0:g} s 的已接受状态 "
            f"T_C {T_C0:.6f} K；调用方记录 cold_plate 与配置一致 {flags['caller_record']}")
    return {"flags": flags, "text": text}


def test_fe003_preconditions_and_inputs(fe003, case_record):
    _start("test_fe003_preconditions_and_inputs")
    _require_setup(fe003)
    results = []
    passed: dict = {"devices": {}}
    items, breakdown, summary = fe003["items"], fe003["breakdown"], fe003["summary"]
    inputs = fe003["inputs"]
    case = CFG["case_inputs"]
    rounding = CFG["rounding"]

    # precondition 1: FE component statistics and loop heat breakdown of the mean environment case
    counts = {}
    finite = True
    missing = []
    for cls in DEVICES:
        names = [block["name"] for block in inputs["devices"][cls]]
        counts[cls] = len(names)
        for name in names:
            if name not in items:
                missing.append(name)
                continue
            values = (items[name]["Tmin_C"], items[name]["Tmean_C"], items[name]["Tmax_C"])
            finite = finite and all(math.isfinite(v) for v in values) and values[0] <= values[1] <= values[2]
    needed_rows = sorted({(load["loop"], CFG["devices"][cls]["breakdown_source"])
                          for cls in DEVICES for load in (inputs["loads"][b["name"]] for b in inputs["devices"][cls])})
    absent_rows = [row for row in needed_rows if row not in breakdown]
    heats_finite = all(math.isfinite(breakdown[row]["W_mean"]) for row in needed_rows if row in breakdown)
    ok = (counts == {"MBSU": 4, "DDCU": 6, "IEA": 4} and not missing and finite and not absent_rows and heats_finite
          and summary.get("case") == CFG["fe"]["case"] and math.isfinite(float(summary["orbit"]["period"])))
    passed["fe_data"] = ok
    results.append(case_record.check(
        "前置条件 有限元平均环境工况的部件统计与回路热量分解可用",
        "nom0 的 items.csv 含 MBSU 4 台、DDCU 6 台、IEA 4 台的第三圈 Tmin_C、Tmean_C、Tmax_C，均为有限值；"
        "loop_breakdown.csv 含各设备所在回路的冷板热量，均为有限值；summary.json 为 nom0 并给出轨道周期",
        f"设备数 {counts}，缺少条目 {missing}，统计量有限且有序 {finite}；需要的回路热量行 {needed_rows}，缺少 {absent_rows}，"
        f"有限 {heats_finite}；summary 工况 {summary.get('case')}，周期 {float(summary['orbit']['period']):.6f} s",
        ok))

    # inputs: power and cold-plate face of each device class
    geometry = {}
    for cls in DEVICES:
        blocks = inputs["devices"][cls]
        faces = {(tuple(b["size"]), b["cool"]["face"]) for b in blocks}
        powers = {float(b["Q"]) for b in blocks}
        area, thickness = sup.cold_plate_geometry(blocks[0]["size"], blocks[0]["cool"]["face"])
        geometry[cls] = {"area_m2": area, "thickness_m": thickness, "size_m": list(blocks[0]["size"]),
                         "face": blocks[0]["cool"]["face"], "Q_W": float(blocks[0]["Q"])}
        expected = case["devices"][cls]
        ok = (len(faces) == 1 and powers == {float(expected["Q_W"])}
              and _within(abs(area - float(expected["cold_plate_area_m2"])), rounding["area_m2"]))
        passed["devices"][cls] = ok
        results.append(case_record.check(
            f"输入 {cls} {expected['Q_W']:g} W，冷板面 {expected['cold_plate_area_m2']:g} m²",
            f"iss_spec 中全部 {cls} 方块发热 {expected['Q_W']:g} W，尺寸与冷板面相同，冷板面面积按用例位数取舍后为 "
            f"{expected['cold_plate_area_m2']:g} m²，差不超过 {rounding['area_m2']} m²",
            f"{len(blocks)} 台，发热 {sorted(powers)} W，尺寸 {blocks[0]['size']} m，冷板面 {blocks[0]['cool']['face']}，"
            f"面积 {area:.4f} m²，垂直冷板面的厚度 {thickness} m，尺寸与冷板面组合 {len(faces)} 种",
            ok))
    OUTCOME["inputs"]["geometry"] = geometry

    # cold-plate conductance and equivalent conductivity
    h = inputs["h_W_m2K"]
    h_names = {b["cool"]["h"] for cls in DEVICES for b in inputs["devices"][cls]}
    ok = h == float(case["h_cold_plate_W_m2K"]) and h_names == {CFG["fe_parameter_names"]["h_cold_plate"]}
    passed["h"] = ok
    results.append(case_record.check(
        f"输入 冷板换热系数 {float(case['h_cold_plate_W_m2K']):g} {UNIT_H}",
        f"三类设备的冷板边界都用 iss_spec PARAMS h_cp_oru，值为 {float(case['h_cold_plate_W_m2K']):g} W/(m²·K)",
        f"冷板边界换热系数参数 {sorted(h_names)}，h_cp_oru = {fe003['spec'].PARAMS['h_cp_oru'][0]}，解析为 {h} W/(m²·K)",
        ok))
    material = inputs["material"]
    classes = {b["cls"] for cls in DEVICES for b in inputs["devices"][cls]}
    ok = float(material["k"]) == float(case["conductivity_W_mK"]) and classes <= set(material["classes"])
    passed["k"] = ok
    results.append(case_record.check(
        f"输入 设备等效导热系数 {float(case['conductivity_W_mK']):g} {UNIT_K}",
        f"三类设备属于 iss_spec MATERIALS oru_eq 的类别，导热系数 {float(case['conductivity_W_mK']):g} W/(m·K)",
        f"设备类别 {sorted(classes)}，oru_eq 类别 {material['classes']}，导热系数 {material['k']} W/(m·K)，"
        f"密度 {material['rho']} kg/m³，比热 {material['cp']} J/(kg·K)",
        ok))

    # coolant temperature
    set_points = fe003["set_points"]
    kelvins = sorted({value[0] for value in set_points.values()})
    fahrenheit = sorted({value[1] for value in set_points.values()})
    T_cool = fe003["T_cool_K"]
    ok = len(kelvins) == 1 and _within(abs((T_cool - K0) - float(case["coolant_C"])), rounding["coolant_K"])
    passed["coolant"] = ok
    results.append(case_record.check(
        f"输入 冷却液 {float(case['coolant_C']):g} °C",
        f"三类设备冷板边界的冷却液设定点相同，按用例位数取舍后为 {float(case['coolant_C']):g} °C，差不超过 "
        f"{rounding['coolant_K']} K；运行取有限元参数表的精确值",
        f"设定点参数 {sorted({b['cool']['T'] for cls in DEVICES for b in inputs['devices'][cls]})}，"
        f"均为 ({fahrenheit} °F − 32)/1.8，即 {T_cool:.6f} K，{T_cool - K0:.4f} °C",
        ok))
    OUTCOME["inputs"].update({"T_cool_K": T_cool, "fahrenheit": fahrenheit, "h_W_m2K": float(h),
                              "k_W_mK": float(material["k"])})

    # P_load is the heat that leaves through the cold plate in the FE; the FE writes it per loop
    shares = inputs["shares"]
    loads = inputs["loads"]
    percents = {loop: (1.0 - value["share"]) * 100.0 for loop, value in shares.items()}
    iea_single = all(len(members) == 1 for members in inputs["iea_members"].values())
    below = all(0.0 < loads[name]["P_load_W"] < float(b["Q"]) for cls in DEVICES for b in inputs["devices"][cls]
                for name in [b["name"]])
    ok = (set(shares) == {"A", "B"} and iea_single and below
          and all(_within(abs(p - float(case["mli_share_percent"])), rounding["share_percent"])
                  for p in percents.values()))
    passed["P_load"] = ok
    share_text = "；".join(
        f"回路 {loop} 冷板设备 {value['members']} 发热 {value['Q_total_W']:.0f} W，经冷板进入回路 "
        f"{value['cold_plate_W']:.2f} W，比值 {value['share']:.6f}，未经冷板进入回路 "
        f"{value['Q_total_W'] - value['cold_plate_W']:.2f} W，占 {percents[loop]:.2f}%"
        for loop, value in sorted(shares.items()))
    iea_text = "，".join(f"{name} {loads[name]['P_load_W']:.2f} W" for name in
                         (b["name"] for b in inputs["devices"]["IEA"]))
    iea_counts = {loop: len(members) for loop, members in inputs["iea_members"].items()}
    results.append(case_record.check(
        "输入 P_load 取有限元中经冷板排出的热量",
        "有限元按冷却回路给出冷板热量：IEA 取所在 PVTCS 回路 iea 热量，每个 PVTCS 回路只有一台 IEA；MBSU 与 DDCU 的单台"
        "冷板热量没有单独输出，取发热乘所在回路 loop_breakdown oru 热量与该回路冷板设备总发热之比；P_load 小于设备发热；"
        f"回路冷板设备发热中未经冷板进入回路的比例与用例所述约 {float(case['mli_share_percent']):g}% 之差不超过 "
        f"{rounding['share_percent']:g} 个百分点。这部分包括多层隔热外表面的辐射换热与方块的储热，本检查不分开计量",
        f"{share_text}；IEA {iea_text}；每个 PVTCS 回路 IEA 台数 {iea_counts}",
        ok))
    OUTCOME["inputs"].update({"shares": shares, "percents": percents, "iea_single": iea_single})

    # precondition 2: cold plate with a very large capacitance at the coolant temperature, CR with a very large resistance
    plate = CFG["cold_plate"]
    C_plate = plate["mass_kg"] * plate["cp_J_kgK"]
    R_plate = plate["CR_equivalent_total_resistance_K_W"]
    rows = []
    ok = bool(fe003["runs"])
    for key, entry in fe003["runs"].items():
        params = entry.get("params")
        if params is None:
            ok = False
            rows.append(f"{key}: 装配失败 {entry.get('assembly_error')}")
            continue
        C_C = float(params.C_J_K[I_C])
        R_CR = float(params.R_K_W[I_CR])
        method = params.provenance["resistance"]["CR"]["method"]
        result = entry.get("result")
        T_C0 = float(result["archive"].accepted["state"][0][I_C]) if result else float("nan")
        ok = ok and (C_C == C_plate and R_CR == R_plate and method == "equivalent_total" and T_C0 == T_cool)
        rows.append(f"{key}: C_C {C_C:.3e} J/K，R_CR {R_CR:.3e} K/W，方法 {method}，T_C 初值 {T_C0:.6f} K")
    passed["plate"] = ok
    results.append(case_record.check(
        "前置条件 冷板热容取极大值并以冷却液温度为初温，CR 连接取极大热阻",
        f"装配的 C_C 为 {C_plate:.0e} J/K，R_CR 为 {R_plate:.0e} K/W 按等效总热阻装配，T_C 初值等于冷却液温度 "
        f"{T_cool:.6f} K",
        "；".join(rows) if rows else "没有运行",
        ok))

    # thermal design 9.4: the test configuration is recorded with every run
    rows = []
    records = {}
    ok = bool(fe003["runs"])
    for key, entry in fe003["runs"].items():
        result = entry.get("result")
        if not result:
            ok = False
            rows.append(f"{key}: 没有运行归档，{entry.get('assembly_error') or entry.get('run_error')}")
            continue
        record = _plate_record(result["archive"], T_cool)
        records[key] = record["flags"]
        ok = ok and all(record["flags"].values())
        rows.append(f"{key}: {record['text']}")
    passed["record_9_4"] = ok
    results.append(case_record.check(
        "前置条件 冷板测试配置按第 9.4 节记入运行归档",
        "每次运行的归档保存解析后的参数、来源、资产与初值：C_C 与 R_CR 的值与装配记录一致，冷板材料 "
        f"{plate['material_id']} 属于 {plate['instance_id']}，质量 {plate['mass_kg']:.0e} kg、比热 {plate['cp_J_kgK']:g} "
        "J/(kg·K)；CR 按等效总热阻装配并含接触部分；两者来源都是 fe003_config.json 中按第 9.4 节写明的测试配置说明，"
        f"冷板资产为 {plate['asset_id']} 版本 {plate['asset_version']}，表示有限元冷板边界而不是器件数据；没有参数覆盖；"
        "第一个已接受状态在起始时刻，T_C 等于冷却液温度；调用方记录 cold_plate 为同一说明",
        "；".join(rows) if rows else "没有运行",
        ok))
    case_record.metric("cold_plate_record_9_4", records)
    OUTCOME["inputs"]["passed"] = passed
    OUTCOME["inputs"]["preconditions_passed"] = all(results)
    _count("test_fe003_preconditions_and_inputs", results)
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 1: R_JC from T5


def test_fe003_step1_r_jc(fe003, case_record):
    _start("test_fe003_step1_r_jc")
    _require_setup(fe003)
    results = []
    inputs = fe003["inputs"]
    material = inputs["material"]
    tol = CRIT["relative_tol_exact"]
    per_class = {}
    for cls in DEVICES:
        keys = [key for key, entry in fe003["runs"].items() if entry["group"]["device"] == cls]
        geometry = fe003["runs"][keys[0]]["geometry"]
        rows = []
        rel_R_values = []
        rel_C_values = []
        ok = True
        for key in keys:
            entry = fe003["runs"][key]
            params = entry.get("params")
            if params is None:
                ok = False
                rows.append(f"{key}: 装配失败 {entry.get('assembly_error')}")
                continue
            R_mod = float(params.R_K_W[I_JC])
            C_mod = float(params.C_J_K[I_J])
            record = params.provenance["resistance"]["JC"]
            rel_R = abs(R_mod - geometry["R_JC_K_W"]) / geometry["R_JC_K_W"]
            rel_C = abs(C_mod - geometry["C_J_hand_J_K"]) / geometry["C_J_hand_J_K"]
            rel_cond = abs(record["inputs"]["conduction_K_W"] - geometry["conduction_K_W"]) / geometry["conduction_K_W"]
            rel_R_values.extend([rel_R, rel_cond])
            rel_C_values.append(rel_C)
            ok = ok and (record["method"] == "conduction_plus_contact" and _within(rel_R, tol)
                         and _within(rel_cond, tol)
                         and record["inputs"]["length_m"] == geometry["length_m"]
                         and record["inputs"]["area_m2"] == geometry["area_m2"]
                         and record["inputs"]["conductivity_W_mK"] == material["k"]
                         and record["inputs"]["contact_resistance_K_W"] == geometry["contact_K_W"])
            rows.append(f"{key}: 装配 R_JC {R_mod:.9f} K/W，方法 {record['method']}，导热部分 "
                        f"{record['inputs']['conduction_K_W']:.9f} K/W，相对差 {rel_R:.1e}")
        worst_R = _worst(rel_R_values)
        worst_C = _worst(rel_C_values)
        ok_R = ok
        results.append(case_record.check(
            f"步骤1 {cls} 按式 T5 第二行计算 R_JC",
            f"接触部分 1/(h A) = 1/({inputs['h_W_m2K']:g} × {geometry['area_m2']:.4f}) = {geometry['contact_K_W']:.9f} K/W，"
            f"导热部分 (L/3)/(κ A) = ({geometry['thickness_m']} m/3)/({material['k']:g} × {geometry['area_m2']:.4f}) = "
            f"{geometry['conduction_K_W']:.9f} K/W，R_JC = {geometry['R_JC_K_W']:.9f} K/W；assemble_thermal_parameters "
            f"按 conduction_plus_contact 装配，与手算的相对差不超过 {tol:g}",
            "；".join(rows), ok_R))

        slab = sup.slab_mean_rise_per_watt(geometry["thickness_m"], material["k"], geometry["area_m2"],
                                           int(CRIT["slab_cells"]))
        rel_slab = abs(slab["mean_rise_K_per_W"] - geometry["conduction_K_W"]) / geometry["conduction_K_W"]
        ok_slab = _within(rel_slab, CRIT["slab_relative_tol"]) and _within(abs(slab["face_heat_W"] - 1.0), 1e-9)
        results.append(case_record.check(
            f"步骤1 {cls} 导热长度取设备厚度的三分之一",
            f"厚度 {geometry['thickness_m']} m 的设备内均匀发热、只经冷板面散热时，一维导热有限体积解的平均温升每瓦等于 "
            f"(L/3)/(κ A) = {geometry['conduction_K_W']:.9f} K/W，相对差不超过 {CRIT['slab_relative_tol']:g}",
            f"{int(CRIT['slab_cells'])} 个单元的平均温升 {slab['mean_rise_K_per_W']:.9f} K/W，相对差 {rel_slab:.1e}，"
            f"冷板面热流 {slab['face_heat_W']:.12f} W，最远端温升 {slab['max_rise_K_per_W']:.9f} K/W 即 L/(2κA)",
            ok_slab))

        assembled_C = [float(fe003["runs"][k]["params"].C_J_K[I_J]) for k in keys
                       if fe003["runs"][k].get("params") is not None]
        ok_C = _within(worst_C, tol) and len(assembled_C) == len(keys)
        results.append(case_record.check(
            f"步骤1 {cls} C_J 按式 T5 第一行由方块质量与比热装配",
            f"C_J = 体积 {geometry['volume_m3']:.6f} m³ × {material['rho']:g} kg/m³ × {material['cp']:g} J/(kg·K) = "
            f"{geometry['C_J_hand_J_K']:.3f} J/K，相对差不超过 {tol:g}",
            f"装配 C_J {', '.join(f'{value:.3f}' for value in assembled_C)} J/K，最大相对差 {worst_C:.1e}",
            ok_C))
        per_class[cls] = {"geometry": geometry, "slab": slab, "rel_slab": rel_slab, "worst_rel_R": worst_R,
                          "worst_rel_C": worst_C, "passed": {"R_JC": ok_R, "slab": ok_slab, "C_J": ok_C}}
    OUTCOME["step1"] = per_class
    case_record.metric("step1_r_jc", {cls: {k: v for k, v in value["geometry"].items()} | {
        "slab_mean_rise_K_per_W": value["slab"]["mean_rise_K_per_W"], "slab_relative_difference": value["rel_slab"],
        "module_worst_relative_R": value["worst_rel_R"], "module_worst_relative_C": value["worst_rel_C"]}
        for cls, value in per_class.items()})
    _count("test_fe003_step1_r_jc", results)
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 2: steady state


def _run_arrays(entry: dict) -> dict:
    archive = entry["result"]["archive"]
    valid = np.asarray(archive.sample_valid, dtype=bool)
    return {
        "t": np.asarray(archive.time_s, dtype=float),
        "T": np.asarray(archive.temperature_K, dtype=float),
        "dT": np.asarray(archive.dT_dt_K_s, dtype=float),
        "q": np.asarray(archive.q_W, dtype=float),
        "P_load": np.asarray(archive.ports_W["P_load_W"], dtype=float),
        "valid": valid,
        "acc_t": np.asarray(archive.accepted["time_s"], dtype=float),
        "acc_y": np.asarray(archive.accepted["state"], dtype=float),
    }


def _max_abs(values: np.ndarray) -> float:
    """Largest absolute value with NaN propagated, +inf for an empty array."""

    values = np.asarray(values, dtype=float)
    return float(np.max(np.abs(values))) if values.size else float("inf")


def test_fe003_step2_steady_state(fe003, case_record):
    _start("test_fe003_step2_steady_state")
    _require_setup(fe003)
    results = []
    orbit = fe003["orbit"]
    T_cool = fe003["T_cool_K"]
    T_J0 = fe003["T_J0_K"]
    period = orbit.period_s
    per_run = {}
    for key, entry in fe003["runs"].items():
        group, geometry = entry["group"], entry["geometry"]
        result = entry.get("result")
        params = entry.get("params")
        label = f"{group['device']} 回路 {group['loop']}"
        if result is None or params is None:
            reason = entry.get("assembly_error") or entry.get("run_error")
            results.append(case_record.check(f"步骤2 {label} 运行完成", "status completed，无错误记录", f"未运行：{reason}",
                                             False))
            continue
        archive = result["archive"]
        stats = archive.statistics
        settings = dict(archive.solver_settings)
        settings_ok = all(settings.get(name) == SOLVER[name] for name in SOLVER_KEYS)
        completed = archive.status == "completed" and result["error"] is None and archive.error is None
        ok_run = completed and stats["invalid_output_samples"] == 0 and settings_ok
        results.append(case_record.check(
            f"步骤2 {label} 运行完成",
            f"sdtwin_sim.coupled.run_coupled 自轨道正午积分 {CFG['run']['orbits']} 个轨道周期到 {result['t_end']:.3f} s，"
            "status completed，无错误记录，全部输出样点有效；归档的求解设置等于表 8 的场景配置 "
            + "，".join(f"{name} {SOLVER[name]}" for name in SOLVER_KEYS),
            f"status {archive.status}，错误 {result['error'] or archive.error}，已接受步 {stats['accepted_steps']}，"
            f"拒绝步 {stats['rejected_steps']}，函数求值 {stats['function_evaluations']}，分段 {stats['segments']}，"
            f"日食边界 {stats['eclipse_boundaries']}，无效输出样点 {stats['invalid_output_samples']}，"
            f"用时 {result['wall_s']:.1f} s；归档的求解设置 "
            + "，".join(f"{name} {settings.get(name)}" for name in SOLVER_KEYS) + f"，与配置一致 {settings_ok}",
            ok_run))
        arrays = _run_arrays(entry)
        valid = arrays["valid"]
        has_valid = bool(valid.any())
        T, q, dT = arrays["T"], arrays["q"], arrays["dT"]
        R = geometry["R_JC_K_W"]
        C_J = geometry["C_J_hand_J_K"]
        C_C = CFG["cold_plate"]["mass_kg"] * CFG["cold_plate"]["cp_J_kgK"]
        R_CR = CFG["cold_plate"]["CR_equivalent_total_resistance_K_W"]
        P = result["P_load_W"]

        # cold plate held at the coolant temperature, CR carries no heat
        dev_out = _max_abs(T[valid, I_C] - T_cool) if has_valid else float("inf")
        dev_acc = _max_abs(arrays["acc_y"][:, I_C] - T_cool) if arrays["acc_y"].size else float("inf")
        q_cr = _max_abs(q[valid, I_CR]) if has_valid else float("inf")
        dev = _worst((dev_out, dev_acc))
        ok_plate = _within(dev, CRIT["cold_plate_hold_K"]) and _within(q_cr, CRIT["q_CR_max_W"])
        results.append(case_record.check(
            f"步骤2 {label} 冷板温度保持为冷却液温度",
            f"全部输出样点与已接受状态的 T_C 与冷却液温度 {T_cool:.6f} K 之差不超过 {CRIT['cold_plate_hold_K']:g} K，"
            f"q_CR 的绝对值不超过 {CRIT['q_CR_max_W']:g} W",
            f"T_C 最大偏差：输出样点 {dev_out:.2e} K，已接受状态 {dev_acc:.2e} K；q_CR 绝对值最大 {q_cr:.2e} W",
            ok_plate))

        # T3 second and third lines at every output sample, hand values from the archived temperatures
        tol = CRIT["derivative_rel_tol"]
        if has_valid:
            q_jc_hand = (T[valid, I_J] - T[valid, I_C]) / R
            q_cr_hand = (T[valid, I_C] - T[valid, I_R]) / R_CR
            dTJ_hand = (P - q_jc_hand) / C_J
            dTC_hand = (q_jc_hand - q_cr_hand) / C_C
            scale_J = (P + np.abs(q_jc_hand)) / C_J
            scale_C = (np.abs(q_jc_hand) + np.abs(q_cr_hand)) / C_C
            err_qjc = _max_abs((q[valid, I_JC] - q_jc_hand) / np.maximum(np.abs(q_jc_hand), 1.0))
            err_dTJ = _max_abs((dT[valid, I_J] - dTJ_hand) / scale_J)
            err_dTC = _max_abs((dT[valid, I_C] - dTC_hand) / scale_C)
        else:
            err_qjc = err_dTJ = err_dTC = float("inf")
        port_ok = has_valid and bool(np.all(arrays["P_load"][valid] == P))
        err_deriv = _worst((err_qjc, err_dTJ, err_dTC))
        ok_deriv = port_ok and _within(err_deriv, tol)
        results.append(case_record.check(
            f"步骤2 {label} 温度导数按式 T3 第二、三行",
            f"每个输出样点 P_load_W 等于 {P:.6f} W；q_JC = (T_J − T_C)/R_JC，C_J dT_J/dt = P_load − q_JC，"
            f"C_C dT_C/dt = q_JC − q_CR，与按归档温度手算之差相对于各项功率不超过 {tol:g}",
            f"{int(valid.sum())} 个输出样点，P_load_W 一致 {port_ok}；q_JC 相对差 {err_qjc:.1e}，dT_J/dt {err_dTJ:.1e}，"
            f"dT_C/dt {err_dTC:.1e}",
            ok_deriv))

        # transient against the closed-form exponential of T3 line 2 with T_C at the coolant temperature
        T_inf = T_cool + P * R
        tau = C_J * R
        ana_out = sup.exponential(arrays["t"], 0.0, T_J0, T_inf, tau)
        ana_acc = sup.exponential(arrays["acc_t"], 0.0, T_J0, T_inf, tau)
        err_out = _max_abs(T[:, I_J] - ana_out) if T.size else float("inf")
        err_acc = _max_abs(arrays["acc_y"][:, I_J] - ana_acc) if arrays["acc_y"].size else float("inf")
        err_exp = _worst((err_out, err_acc))
        ok_exp = _within(err_exp, CRIT["analytic_K"])
        results.append(case_record.check(
            f"步骤2 {label} 计算节点温度随时间按式 T3 第二行变化",
            f"T_J 自 {T_J0:.2f} K 起与指数解 T_C + P_load R_JC + (T_J0 − T_C − P_load R_JC) exp(−t/τ) 之差不超过 "
            f"{CRIT['analytic_K']:g} K，τ = C_J R_JC = {tau:.1f} s",
            f"输出样点最大差 {err_out:.2e} K，已接受状态最大差 {err_acc:.2e} K",
            ok_exp))

        # steady state: T_J = T_C + P_load R_JC at the end, and no change over the last orbit
        t1 = float(arrays["acc_t"][-1])
        end_state = np.asarray(archive.state_at(t1), dtype=float)
        T_J_end, T_C_end = float(end_state[I_J]), float(end_state[I_C])
        T_ss = T_C_end + P * R
        ss_err = T_J_end - T_ss
        previous = float(np.asarray(archive.state_at(t1 - period), dtype=float)[I_J])
        repetition = T_J_end - previous
        q_end = (T_J_end - T_C_end) / R
        ok_steady = (_within(abs(t1 - result["t_end"]), 1e-9 * result["t_end"])
                     and _within(abs(ss_err), CRIT["steady_state_K"]) and _within(abs(repetition), CRIT["repetition_K"]))
        results.append(case_record.check(
            f"步骤2 {label} 积分到稳态时 T_J 等于冷板温度加 P_load 乘 R_JC",
            f"结束时 T_J 与 T_C + P_load R_JC = T_C + {P:.4f} W × {R:.9f} K/W 之差不超过 {CRIT['steady_state_K']:g} K，"
            f"最后一个轨道周期内 T_J 的变化不超过 {CRIT['repetition_K']:g} K",
            f"t = {t1:.3f} s 时 T_J {T_J_end:.6f} K，T_C {T_C_end:.9f} K，T_C + P_load R_JC = {T_ss:.6f} K，差 {ss_err:.2e} K；"
            f"一个周期前 T_J {previous:.6f} K，变化 {repetition:.2e} K；q_JC {q_end:.4f} W，P_load {P:.4f} W",
            ok_steady))
        per_run[key] = {
            "device": group["device"], "loop": group["loop"], "items": group["items"], "P_load_W": P,
            "R_JC_K_W": R, "C_J_J_K": C_J, "tau_s": tau, "T_J_end_K": T_J_end, "T_C_end_K": T_C_end,
            "T_ss_K": T_ss, "T_ss_coolant_K": T_inf, "steady_error_K": ss_err, "repetition_K": repetition,
            "cold_plate_dev_K": dev, "q_CR_max_W": q_cr, "exp_error_K": err_exp,
            "derivative_rel_errors": {"q_JC": err_qjc, "dT_J": err_dTJ, "dT_C": err_dTC},
            "q_JC_end_W": q_end, "completed": completed, "solver_settings_match": settings_ok,
            "wall_s": result["wall_s"],
            "passed": {"run": ok_run, "cold_plate": ok_plate, "derivative": ok_deriv, "exponential": ok_exp,
                       "steady": ok_steady},
            "statistics": {name: stats[name] for name in ("accepted_steps", "rejected_steps", "function_evaluations",
                                                          "segments", "eclipse_boundaries", "output_samples")},
            "S_range_K": [float(np.min(T[:, I_S])), float(np.max(T[:, I_S]))] if T.size else None,
            "R_range_K": [float(np.min(T[:, I_R])), float(np.max(T[:, I_R]))] if T.size else None,
            "range_warnings": len(archive.range_warnings),
        }
    OUTCOME["step2"] = per_run

    # eclipse boundaries of the runs against the closed-form cylindrical shadow (metric of the chapter 8 splitting)
    eclipse = {}
    for key, entry in fe003["runs"].items():
        result = entry.get("result")
        if not result:
            continue
        archive = result["archive"]
        module_times = np.array([b.time_s for b in archive.eclipse_boundaries], dtype=float)
        closed = np.array([x for w in orbit.eclipse_windows(0.0, result["t_end"]) for x in w
                           if 0.0 < x < result["t_end"]], dtype=float)
        eclipse[key] = {"module": int(module_times.size), "closed_form": int(closed.size),
                        "max_error_s": _max_abs(module_times - closed) if module_times.size == closed.size
                        and closed.size else None}
    OUTCOME["eclipse"] = eclipse
    case_record.metric("step2_runs", per_run)
    case_record.metric("eclipse_boundaries", eclipse)
    case_record.metric("solver_settings", dict(SOLVER))
    _count("test_fe003_step2_steady_state", results)
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 3: FE comparison


def test_fe003_step3_fe_comparison(fe003, case_record):
    _start("test_fe003_step3_fe_comparison")
    _require_setup(fe003)
    results = []
    items = fe003["items"]
    orbit = fe003["orbit"]
    period = orbit.period_s
    rows_by_class = {cls: [] for cls in DEVICES}
    for key, entry in fe003["runs"].items():
        group = entry["group"]
        result = entry.get("result")
        stats = None
        if result is not None and result["archive"].status == "completed":
            archive = result["archive"]
            t1 = float(archive.accepted["time_s"][-1])
            t0 = t1 - period
            grid = sup.period_grid(archive.accepted["time_s"], t0, t1, float(CRIT["statistics_grid_s"]))
            values = np.asarray(archive.state_at(grid), dtype=float)[:, I_J] - K0
            stats = sup.trapezoid_stats(grid, values)
            stats.update({"t0_s": t0, "t1_s": t1, "grid_points": int(grid.size)})
        for name in group["items"]:
            fe = items[name]
            row = {"item": name, "run": key, "loop": group["loop"], "P_load_W": group["P_load_W"],
                   "fe_Tmin_C": fe["Tmin_C"], "fe_Tmean_C": fe["Tmean_C"], "fe_Tmax_C": fe["Tmax_C"]}
            if stats is not None:
                row.update({"module_mean_C": stats["mean"], "module_min_C": stats["min"], "module_max_C": stats["max"],
                            "diff_K": stats["mean"] - fe["Tmean_C"], "window_s": [stats["t0_s"], stats["t1_s"]],
                            "inside_fe_range": fe["Tmin_C"] <= stats["mean"] <= fe["Tmax_C"]})
            rows_by_class[group["device"]].append(row)
    worst = {}
    complete = {}
    for cls in DEVICES:
        rows = rows_by_class[cls]
        complete[cls] = bool(rows) and all(_finite_row(row) for row in rows)
        worst[cls] = _worst(abs(row["diff_K"]) for row in rows if "diff_K" in row)
        ok = complete[cls] and _within(worst[cls], ACCEPT_K)
        text = "；".join(
            (f"{row['item']} 回路 {row['loop']}：P_load {row['P_load_W']:.2f} W，热模块 {row['module_mean_C']:.3f} °C，"
             f"有限元 {row['fe_Tmean_C']:.3f} °C，差 {row['diff_K']:+.3f} K") if "diff_K" in row
            else f"{row['item']}：无热模块结果" for row in rows)
        results.append(case_record.check(
            f"步骤3 {cls} 平均温度与有限元第三圈平均温度比较",
            f"每台 {cls} 的热模块最后一个轨道周期 {period:.4f} s 内按时间加权的 T_J 平均值与有限元 items.csv 第三圈 Tmean_C "
            f"均为有限值，两者之差不超过 {ACCEPT_K:g} K",
            f"{text}；全部为有限值 {complete[cls]}；最大差的绝对值 {worst[cls]:.3f} K", ok))
    all_rows = [row for cls in DEVICES for row in rows_by_class[cls]]
    overall = _worst(worst.values())
    accepted = (len(all_rows) == 14 and all(_finite_row(row) for row in all_rows) and _within(overall, ACCEPT_K))
    results.append(case_record.check(
        f"验收判据 三类设备平均温度差不超过 {ACCEPT_K:g} K",
        f"MBSU、DDCU 与 IEA 共 14 台设备都有有限的平均温度差，绝对值均不超过 {ACCEPT_K:g} K",
        "；".join(f"{cls} 最大差 {worst[cls]:.3f} K" for cls in DEVICES)
        + f"；设备 {len(all_rows)} 台，有限值 {sum(1 for row in all_rows if _finite_row(row))} 台；总体最大 {overall:.3f} K",
        accepted))
    OUTCOME["step3"] = {"rows": rows_by_class, "worst": worst, "overall": overall, "complete": complete,
                        "accepted": accepted}
    case_record.metric("step3_comparison", rows_by_class)
    case_record.metric("step3_worst_abs_diff_K", worst)
    _count("test_fe003_step3_fe_comparison", results)
    assert all(results)


# ------------------------------------------------------------------------------------------------ evidence and summary


def _fe_context(fe003) -> dict:
    """FE-side numbers that describe the reference: averaging method and the warming of the hottest block."""

    fe = CFG["fe"]
    series = fe003["series"]
    t = series[fe["time_column"]]
    box = series[fe["box_class_column"]]
    hottest = series["box_Tmax_C"]
    period = fe003["orbit"].period_s
    order = np.argsort(t, kind="stable")
    unique_t, first = np.unique(t[order], return_index=True)
    hot_unique = hottest[order][first]
    t1 = float(unique_t[-1])
    t0 = t1 - period
    window = unique_t >= t0
    # the class maximum box_Tmax_C covers every block of class box; a block can carry it during orbit 3 only if its
    # orbit 3 Tmax reaches the lowest class maximum of that orbit
    boxes = {name: value for name, value in fe003["items"].items() if value["kind"] == "box"}
    finite = (bool(np.all(np.isfinite(hot_unique))) and bool(np.all(np.isfinite(box)))
              and all(math.isfinite(value["Tmax_C"]) for value in boxes.values()))
    floor = float(np.min(hot_unique[window]))
    candidates = sorted(name for name, value in boxes.items() if value["Tmax_C"] >= floor)
    hottest_item = max(boxes, key=lambda name: boxes[name]["Tmax_C"]) if boxes and finite else None
    start = float(np.interp(t0, unique_t, hot_unique))
    end = float(hot_unique[-1])
    return {
        "box_class_sample_mean_C": sup.fe_sample_mean(t, box, period),
        "box_class_time_weighted_mean_C": sup.fe_time_weighted_mean(t, box, period),
        "hottest_block_start_orbit3_C": start,
        "hottest_block_end_C": end,
        "hottest_block_rise_over_one_period_K": end - start,
        "hottest_item_orbit3": hottest_item,
        "hottest_item_Tmax_C": boxes[hottest_item]["Tmax_C"] if hottest_item else None,
        "hottest_candidates_orbit3": candidates,
        "hottest_class_is_DDCU": finite and bool(candidates) and all(name.startswith("DDCU") for name in candidates),
        "fe_periodicity_box_class_K": fe003["summary"]["periodicity_lastorbit_minus_previous_C"].get(
            fe["box_class_column"]),
        "orbit3_window_s": [t0, t1],
        "finite": finite,
    }


def _resolution_effect(fe003) -> dict:
    """Earth flux of the auxiliary S and R surfaces on the 120 x 180 grid against the default 240 x 360 grid."""

    entry = next((e for e in fe003["runs"].values() if e.get("params") is not None), None)
    if entry is None:
        return {}
    env, orbit = fe003["env"], fe003["orbit"]
    differences = []
    for t in np.linspace(0.0, orbit.period_s, 7)[:-1]:
        records = [earth_flux_record("fe003-resolution", float(t), orbit.position(t), orbit.sun_position(t),
                                     orbit.quaternion(t), entry["params"], albedo=env["albedo"], olr_W_m2=env["olr"],
                                     solar_constant_W_m2=env["S_sun"], earth_radius_m=orbit.earth_radius_m,
                                     resolution=res) for res in (tuple(CFG["environment"]["earth_flux_resolution"]),
                                                                 (240, 360))]
        for field in ("albedo_W_m2", "infrared_W_m2"):
            coarse, fine = np.asarray(records[0][field]), np.asarray(records[1][field])
            differences.append(_max_abs(coarse - fine))
    return {"max_abs_difference_W_m2": _worst(differences), "instants": 6}


def _p_load_split(fe003) -> dict:
    """Diagnostic of the one loop share used for the P_load of the MBSU and DDCU; not a check of the case.

    The FE writes the cold-plate heat per loop. With the hand R_JC of T5 the FE third-orbit mean temperature of each
    device gives the heat (T_mean - T_coolant) / R_JC that the lumped node passes at that temperature. Summed per loop
    it is compared with the FE loop heat; per device it shows how far the one loop share is from each device. Apart
    from the decayed initial transient the step 3 difference equals R_JC times (P_load - that heat).
    """

    inputs = fe003["inputs"]
    items = fe003["items"]
    T_cool = fe003["T_cool_K"]
    h, k = float(inputs["h_W_m2K"]), float(inputs["material"]["k"])
    rows3 = {row["item"]: row for rows in OUTCOME.get("step3", {}).get("rows", {}).values() for row in rows}
    devices, loops = {}, {}
    for cls in DEVICES:
        if CFG["devices"][cls]["breakdown_source"] != "oru":
            continue
        for block in inputs["devices"][cls]:
            name = block["name"]
            load = inputs["loads"][name]
            area, thickness = sup.cold_plate_geometry(block["size"], block["cool"]["face"])
            R = sup.hand_r_jc(h, k, area, thickness)["R_JC_K_W"]
            implied = (items[name]["Tmean_C"] + K0 - T_cool) / R
            excess = load["P_load_W"] - implied
            devices[name] = {
                "device": cls, "loop": load["loop"], "Q_W": float(block["Q"]), "P_load_W": load["P_load_W"],
                "uniform_share": load["share"], "R_JC_K_W": R, "implied_cold_plate_W": implied,
                "implied_share": implied / float(block["Q"]), "P_load_minus_implied_W": excess,
                "R_JC_times_excess_K": R * excess, "diff_K": rows3.get(name, {}).get("diff_K"),
            }
            loops.setdefault(load["loop"], []).append(name)
    loop_sums = {}
    for loop, names in sorted(loops.items()):
        implied = math.fsum(devices[name]["implied_cold_plate_W"] for name in names)
        heat = inputs["shares"][loop]["cold_plate_W"]
        loop_sums[loop] = {"members": names, "implied_W": implied, "fe_cold_plate_W": heat,
                           "difference_W": implied - heat}
    return {"method": "implied cold-plate heat (FE Tmean - coolant) / R_JC per device, R_JC by hand from T5",
            "devices": devices, "loops": loop_sums}


def _write_series(fe003) -> str | None:
    runs = {key: entry for key, entry in fe003["runs"].items() if entry.get("result")}
    if not runs:
        return None
    stride = max(1, int(round(120.0 / float(SOLVER["output_step_s"]))))
    first = next(iter(runs.values()))["result"]["archive"]
    time_s = np.asarray(first.time_s, dtype=float)
    common = all(np.array_equal(np.asarray(e["result"]["archive"].time_s, dtype=float), time_s) for e in runs.values())
    payload = {
        "case_id": "FE-003",
        "description": ("Module time histories of the computing node J and cold plate C for the ISS cold-plate devices "
                        "of the FE mean environment case nom0, sampled every 120 s on the accepted solution; FE third-"
                        "orbit statistics per item from iss_fem/out/nom0/items.csv. Temperatures in degrees Celsius, "
                        "heat flows in W, time in s from orbit noon."),
        "last_period_s": [float(fe003["t_end"] - fe003["orbit"].period_s), float(fe003["t_end"])],
        "common_time_grid": bool(common),
        "time_s": time_s[::stride].round(3).tolist() if common else None,
        "runs": {},
        "fe_items": {},
    }
    for key, entry in runs.items():
        archive = entry["result"]["archive"]
        T = np.asarray(archive.temperature_K, dtype=float)
        q = np.asarray(archive.q_W, dtype=float)
        t = np.asarray(archive.time_s, dtype=float)
        geometry = entry["geometry"]
        P = entry["result"]["P_load_W"]
        T_inf = fe003["T_cool_K"] + P * geometry["R_JC_K_W"]
        exp_curve = sup.exponential(t, 0.0, fe003["T_J0_K"], T_inf, geometry["C_J_hand_J_K"] * geometry["R_JC_K_W"])
        record = {
            "device": entry["group"]["device"], "loop": entry["group"]["loop"], "fe_items": entry["group"]["items"],
            "P_load_W": P, "R_JC_K_W": geometry["R_JC_K_W"], "C_J_J_K": geometry["C_J_hand_J_K"],
            "T_steady_C": T_inf - K0,
            "T_J_C": (T[::stride, I_J] - K0).round(6).tolist(),
            "T_C_C": (T[::stride, I_C] - K0).round(9).tolist(),
            "q_JC_W": q[::stride, I_JC].round(6).tolist(),
            "T_J_exponential_C": (exp_curve[::stride] - K0).round(6).tolist(),
        }
        if not common:
            record["time_s"] = t[::stride].round(3).tolist()
        payload["runs"][key] = record
    for cls, rows in OUTCOME.get("step3", {}).get("rows", {}).items():
        for row in rows:
            payload["fe_items"][row["item"]] = {
                "device": cls, "run": row["run"], "fe_Tmin_C": row["fe_Tmin_C"], "fe_Tmean_C": row["fe_Tmean_C"],
                "fe_Tmax_C": row["fe_Tmax_C"], "module_mean_C": row.get("module_mean_C"),
                "diff_K": row.get("diff_K"), "P_load_W": row["P_load_W"]}
    fe = CFG["fe"]
    series = fe003["series"]
    payload["fe_box_class_series"] = {
        "description": ("FE time histories of the class statistics over every block of class box (MBSU, DDCU, IEA and "
                        "the passive ATA, PM and NTA), iss_fem/out/nom0/series.csv; box_Tmax_C is the hottest point "
                        "of all blocks. They are not per item and are not compared; event rows appear twice."),
        "t_s": series[fe["time_column"]].tolist(),
        "box_Tmean_C": series[fe["box_class_column"]].tolist(),
        "box_Tmax_C": series["box_Tmax_C"].tolist(),
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "FE-003_series.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    return str(path.relative_to(THERMAL_DIR).as_posix())


# Chinese summary: every statement follows a recorded check or a computed value of this run


def _inputs_text(fe003) -> str:
    out = OUTCOME["inputs"]
    passed = out.get("passed")
    if not passed:
        return _missing_text("test_fe003_preconditions_and_inputs") + "。"
    case = CFG["case_inputs"]
    mismatched = [f"{cls} 的发热或冷板面" for cls in DEVICES if not passed["devices"].get(cls)]
    if not passed["h"]:
        mismatched.append("冷板换热系数")
    if not passed["k"]:
        mismatched.append("设备等效导热系数")
    text = (f"设备尺寸与发热、冷板换热系数 {out['h_W_m2K']:g} {UNIT_H} 与设备等效导热系数 {out['k_W_mK']:g} {UNIT_K} "
            "取自有限元模型参数表")
    text += "，与用例输入一致；" if not mismatched else f"，其中{'、'.join(mismatched)}与用例输入不一致；"
    T_cool_C = fe003["T_cool_K"] - K0
    case_C = float(case["coolant_C"])
    fahrenheit = out.get("fahrenheit", [])
    if passed["coolant"] and len(fahrenheit) == 1:
        shift = case_C - T_cool_C
        text += (f"冷却液温度取有限元设定点 {fahrenheit[0]:g} °F，即 {_num(T_cool_C, 2)} °C，用例写作 {case_C:g} °C，"
                 f"按 {case_C:g} °C 计算时各设备的稳态温度{'高' if shift >= 0 else '低'} {_num(abs(shift), 3)} K。")
    else:
        text += f"冷却液设定点与用例的 {case_C:g} °C 不一致，运行取 {_num(T_cool_C, 2)} °C。"
    return text


def _step1_text() -> str:
    step1 = OUTCOME["step1"]
    if not all(cls in step1 for cls in DEVICES):
        return _missing_text("test_fe003_step1_r_jc") + "。"
    texts = []
    for cls in DEVICES:
        g = step1[cls]["geometry"]
        texts.append(f"{cls} 冷板面 {g['area_m2']:.4g} m²，厚度 {g['thickness_m']:g} m，接触部分 "
                     f"{g['contact_K_W']:.6f} K/W，导热部分 {g['conduction_K_W']:.6f} K/W，R_JC 为 {g['R_JC_K_W']:.6f} K/W")
    worst_rel = _worst([step1[cls]["worst_rel_R"] for cls in DEVICES] + [step1[cls]["worst_rel_C"] for cls in DEVICES])
    worst_slab = _worst(step1[cls]["rel_slab"] for cls in DEVICES)
    return ("步骤1按式 T5 第二行计算 R_JC，接触部分取冷板换热系数与冷板面积乘积的倒数，导热部分以设备厚度的三分之一为"
            "导热长度：" + "；".join(texts) + "。assemble_thermal_parameters 装配的 R_JC 与 C_J 和手算值的相对差最大为 "
            f"{_sci(worst_rel)}，限值 {_limit(CRIT['relative_tol_exact'])}；一维均匀发热导热的有限体积解给出的每瓦平均温升与"
            f"三分之一厚度的导热热阻相对差最大为 {_sci(worst_slab)}，限值 {_limit(CRIT['slab_relative_tol'])}；"
            f"{_count_text('test_fe003_step1_r_jc')}。")


def _p_load_text(fe003, context: dict) -> str:
    out = OUTCOME["inputs"]
    passed = out.get("passed")
    if not passed:
        return ""
    inputs = fe003["inputs"]
    shares = inputs["shares"]
    loops = sorted(shares)
    percents = out["percents"]
    iea_loads = [inputs["loads"][block["name"]]["P_load_W"] for block in inputs["devices"]["IEA"]]
    loop_names = " 与 ".join(loops)
    share_values = " 与 ".join(f"{shares[loop]['share']:.4f}" for loop in loops)
    percent_values = " 与 ".join(f"{_num(percents[loop], 2)}%" for loop in loops)
    case_percent = f"{float(CFG['case_inputs']['mli_share_percent']):g}%"
    if not passed["P_load"]:
        return (f"P_load 取有限元第三圈经冷板排出的热量，回路 {loop_names} 冷板设备的发热分别有 {percent_values} 未经冷板进入"
                f"回路，P_load 的取值检查未通过，见异常记录。")
    text = ("P_load 取有限元第三圈经冷板排出的热量。有限元按冷却回路给出冷板热量，IEA 每个 PVTCS 回路只有一台，取所在回路的"
            f"冷板热量 {_class_range(iea_loads, 1, 'W')}；MBSU 与 DDCU 的单台冷板热量在有限元结果中没有单独输出，按所在回路"
            f"冷板热量与该回路冷板设备总发热之比折算，回路 {loop_names} 的比值为 {share_values}，即这些回路冷板设备的发热分别有 "
            f"{percent_values} 未经冷板进入回路，与用例所述约 {case_percent} 一致。这部分热量包括多层隔热外表面的辐射换热和"
            "方块的储热，本用例没有分开计量")
    rise = context.get("hottest_block_rise_over_one_period_K", float("nan")) if context else float("nan")
    if context and context.get("hottest_class_is_DDCU") and math.isfinite(rise) and rise > 0.0:
        text += (f"；有限元方块的最高温度在第三圈内一直出现在 DDCU，相隔一个轨道周期的第三圈首尾由 "
                 f"{_num(context['hottest_block_start_orbit3_C'], 2)} °C 升到 {_num(context['hottest_block_end_C'], 2)} °C，"
                 "说明第三圈末温度最高的 DDCU 方块在这一圈内仍在升温，一部分发热储存在方块内")
    return text + "。"


def _plate_text() -> str:
    passed = OUTCOME["inputs"].get("passed")
    if not passed:
        return ""
    plate = CFG["cold_plate"]
    C_text = sup.sci_exact(plate["mass_kg"] * plate["cp_J_kgK"])
    R_text = sup.sci_exact(plate["CR_equivalent_total_resistance_K_W"])
    if passed["plate"]:
        text = (f"冷板热容取 {C_text} J/K 并以冷却液温度为初温，CR 热阻取 {R_text} K/W，使冷板温度保持为冷却液温度，"
                "对应有限元的冷板边界")
    else:
        text = f"冷板热容 {C_text} J/K、CR 热阻 {R_text} K/W 或冷板初温的装配检查未通过"
    if passed["record_9_4"]:
        text += "；这组取值连同来源说明按第 9.4 节作为测试配置记入每次运行的归档"
    else:
        text += "；按第 9.4 节记录测试配置的检查未通过"
    return text + f"。{_count_text('test_fe003_preconditions_and_inputs')}。"


def _step2_text(fe003, resolution: dict) -> str:
    step2 = OUTCOME["step2"]
    if not step2:
        return _missing_text("test_fe003_step2_steady_state") + "。"
    runs = list(step2.values())
    done = sum(1 for run in runs if run["completed"])
    eclipse = OUTCOME.get("eclipse", {})
    eclipse_text = ""
    errors = [value["max_error_s"] for value in eclipse.values()]
    counts = {value["module"] for value in eclipse.values()}
    if (eclipse and len(counts) == 1 and all(value["module"] == value["closed_form"] for value in eclipse.values())
            and all(error is not None and math.isfinite(error) for error in errors)):
        eclipse_text = f"，每次运行的 {next(iter(counts))} 个日食边界与圆柱阴影的解析时刻相差最大 {_sci(_worst(errors))} s"
    resolution_text = ""
    difference = resolution.get("max_abs_difference_W_m2") if resolution else None
    if difference is not None and math.isfinite(difference):
        grid = CFG["environment"]["earth_flux_resolution"]
        resolution_text = (f"，按 {grid[0]} × {grid[1]} 网格积分，在一个轨道周期的 {resolution['instants']} 个时刻与默认的 "
                           f"240 × 360 网格相差最大 {_num(difference, 3)} W/m²")
    dev = _worst(run["cold_plate_dev_K"] for run in runs)
    q_cr = _worst(run["q_CR_max_W"] for run in runs)
    deriv = _worst(value for run in runs for value in run["derivative_rel_errors"].values())
    exp = _worst(run["exp_error_K"] for run in runs)
    steady = _worst(abs(run["steady_error_K"]) for run in runs)
    repetition = _worst(abs(run["repetition_K"]) for run in runs)
    if CRIT["steady_state_K"] == CRIT["repetition_K"]:
        end_limits = f"限值均为 {_limit(CRIT['steady_state_K'])} K"
    else:
        end_limits = f"限值分别为 {_limit(CRIT['steady_state_K'])} K 与 {_limit(CRIT['repetition_K'])} K"
    return (f"步骤2经 sdtwin_sim.coupled 在每次试算中调用 thermal_derivative，按每类设备与回路共运行 {len(fe003['runs'])} 次，"
            f"完成 {done} 次，积分方法 {SOLVER['method']}，相对容限 {sup.sci_exact(SOLVER['rtol'])}，温度绝对容限 "
            f"{sup.sci_exact(SOLVER['atol_T_K'])} K，最大步长 {SOLVER['max_step_s']:g} s，自轨道正午积分 "
            f"{CFG['run']['orbits']} 个轨道周期，在日食边界分段{eclipse_text}；计算节点初温取有限元方块初温 "
            f"{_num(fe003['T_J0_K'], 0)} K。太阳能板、电池、电源设备与散热板只用于补齐六个节点，不参与比较，太阳能板与散热板"
            f"表面的反照与地球红外由 sdtwin_sim.earth_flux 按平均环境工况给出{resolution_text}。冷板温度偏离冷却液温度最大 "
            f"{_sci(dev)} K，限值 {_limit(CRIT['cold_plate_hold_K'])} K；q_CR 的绝对值最大 {_sci(q_cr)} W，限值 "
            f"{_limit(CRIT['q_CR_max_W'])} W；温度导数与式 T3 第二、三行按归档温度手算的相对差最大为 {_sci(deriv)}，限值 "
            f"{_limit(CRIT['derivative_rel_tol'])}；计算节点温度全程与指数解之差最大 {_sci(exp)} K，限值 "
            f"{_limit(CRIT['analytic_K'])} K；结束时 T_J 与冷板温度加 P_load 乘 R_JC 之差最大 {_sci(steady)} K，最后一个轨道"
            f"周期内 T_J 的变化最大 {_sci(repetition)} K，{end_limits}；{_count_text('test_fe003_step2_steady_state')}。")


def _step3_text() -> str:
    step3 = OUTCOME["step3"]
    if not step3 or not step3.get("rows"):
        return _missing_text("test_fe003_step3_fe_comparison") + "。"
    texts = []
    total = 0
    usable = 0
    for cls in DEVICES:
        all_rows = step3["rows"].get(cls, [])
        rows = [row for row in all_rows if _finite_row(row)]
        total += len(all_rows)
        usable += len(rows)
        if rows:
            texts.append(f"{cls} 热模块 {_class_range([r['module_mean_C'] for r in rows], 2, '°C')}，有限元 "
                         f"{_class_range([r['fe_Tmean_C'] for r in rows], 2, '°C')}，差 "
                         f"{_class_range([r['diff_K'] for r in rows], 2, 'K')}")
    text = "步骤3在已接受状态的解上取最后一个轨道周期按时间加权的平均温度，与有限元第三圈平均温度比较："
    text += ("；".join(texts) + "。") if texts else "没有可比较的结果。"
    if usable < total:
        text += f"{total - usable} 台设备没有有限的热模块平均温度或差值。"
    overall = step3["overall"]
    if step3.get("accepted"):
        text += (f"{total} 台设备平均温度差的绝对值最大为 {_num(overall, 2)} K，不超过验收值 {ACCEPT_K:g} K，"
                 "三类设备的平均温度与有限元一致。")
    elif math.isfinite(overall):
        relation = "超过" if overall > ACCEPT_K else "不超过"
        text += (f"{total} 台设备平均温度差的绝对值最大为 {_num(overall, 2)} K，{relation}验收值 {ACCEPT_K:g} K，"
                 "验收判据的检查未通过，见异常记录。")
    else:
        text += "平均温度差不全是有限值，验收判据的检查未通过，见异常记录。"
    return text


def _split_text(split: dict) -> str:
    """Per-device implied cold-plate heat against the one loop share; written only when the numbers support it."""

    if not split or not split.get("devices") or not split.get("loops"):
        return ""
    loops = split["loops"]
    names = sorted(loops)
    differences = [loops[loop]["difference_W"] for loop in names]
    if not all(math.isfinite(value) for value in differences):
        return ""
    if all(value < 0.0 for value in differences):
        loop_relation = f"分别比有限元回路冷板热量少 {' W 与 '.join(_num(-value, 2) for value in differences)} W"
    elif all(value > 0.0 for value in differences):
        loop_relation = f"分别比有限元回路冷板热量多 {' W 与 '.join(_num(value, 2) for value in differences)} W"
    else:
        loop_relation = f"与有限元回路冷板热量分别相差 {' W 与 '.join(_num(value, 2) for value in differences)} W"
    shares, relations, signs = [], [], []
    consistent = True
    for cls in DEVICES:
        rows = [value for value in split["devices"].values() if value["device"] == cls]
        if not rows:
            continue
        shares.append(f"{cls} 为 {_class_range([row['implied_share'] for row in rows], 3, '')}")
        excess = [row["P_load_minus_implied_W"] for row in rows]
        diffs = [row["diff_K"] for row in rows]
        if any(diff is None or not math.isfinite(diff) for diff in diffs) or not all(math.isfinite(e) for e in excess):
            consistent = False
            continue
        if all(e < 0.0 for e in excess) and all(diff < 0.0 for diff in diffs):
            relations.append(f"{cls} 的 P_load 比反推值小 {_class_range([-e for e in excess], 1, 'W')}")
            signs.append(f"{cls} 差为负")
        elif all(e > 0.0 for e in excess) and all(diff > 0.0 for diff in diffs):
            relations.append(f"{cls} 的 P_load 比反推值大 {_class_range(excess, 1, 'W')}")
            signs.append(f"{cls} 差为正")
        else:
            consistent = False
    text = (f"用 R_JC 和有限元各设备第三圈平均温度反推单台冷板热量，回路 {' 与 '.join(names)} 的合计{loop_relation}；"
            f"反推的单台冷板热量与发热之比 {'，'.join(shares)}")
    if consistent and relations:
        text += f"；按回路统一比值折算时，{'，'.join(relations)}，与步骤3中 {'、'.join(signs)}一致"
    return text + "。"


def _averaging_text(context: dict) -> str:
    if not context or not context.get("finite"):
        return ""
    gap = abs(context["box_class_sample_mean_C"] - context["box_class_time_weighted_mean_C"])
    if not math.isfinite(gap):
        return ""
    return ("有限元各设备的第三圈平均温度是输出样点的算术平均，以全部舱外设备方块的平均温度为例，算术平均与按时间加权平均"
            f"相差 {_sci(gap)} K。")


def _summary_cn(fe003, context: dict, resolution: dict, split: dict) -> str:
    if fe003.get("setup_error"):
        return ("本用例按有限元平均环境工况检验计算节点经冷板的传热计算。有限元数据读取或运行准备没有完成，异常类型为 "
                f"{fe003.get('setup_error_type')}，各步骤未能执行。")
    inputs = fe003["inputs"]
    n_items = sum(len(inputs["devices"][cls]) for cls in DEVICES)
    parts = [
        f"本用例按有限元平均环境工况，对 MBSU、DDCU 与 IEA 三类冷板设备共 {n_items} 台检验计算节点经冷板的传热计算。",
        _inputs_text(fe003),
        _step1_text(),
        _p_load_text(fe003, context),
        _plate_text(),
        _step2_text(fe003, resolution),
        _step3_text(),
        _split_text(split),
        _averaging_text(context),
    ]
    return _markup("".join(parts))


def _record_run_metrics(fe003, case_record) -> None:
    case_record.metric("coolant_K", fe003["T_cool_K"])
    case_record.metric("T_J0_K", fe003["T_J0_K"])
    case_record.metric("run_end_s", fe003["t_end"])
    case_record.metric("orbit_period_s", fe003["orbit"].period_s)
    case_record.metric("coolant_case_value_shift_K", float(CFG["case_inputs"]["coolant_C"]) - (fe003["T_cool_K"] - K0))


def _failed_item_cn(check: dict) -> str:
    """Chinese name of a failed check; a failure that conftest records for a whole test function is named by step."""

    function, _, phase = check["name"].rpartition(" ")
    if function in STEP_FUNCTIONS and phase in PHASES_CN:
        return f"{STEP_FUNCTIONS[function]}的测试函数在{PHASES_CN[phase]}以失败结束"
    return _markup(check["name"])


def _anomalies_cn(checks: list[dict], unexecuted: list[str], pending: list[str]) -> str:
    failed = [_failed_item_cn(check) for check in checks if not check["passed"]] + list(pending)
    sentences = []
    if failed:
        sentences.append(f"共 {len(failed)} 项检查未通过：{'；'.join(failed)}。各项的期望值与实际值见本用例的证据文件。")
    if unexecuted:
        sentences.append(f"{'、'.join(unexecuted)}未执行。")
    return "".join(sentences) or "无"


def test_fe003_record(fe003, case_record):
    """Metrics, series file, Chinese summary and anomaly record, written after every other check of the case.

    A failing part is collected instead of stopping the function: summary and anomalies are always written, and the
    anomaly record already names the failure that conftest records for this function when it raises at the end.
    """

    _start("test_fe003_record")
    problems: list[tuple[str, BaseException]] = []

    def guarded(label: str, function, *args):
        try:
            return function(*args)
        except Exception as exc:  # noqa: BLE001  (named in the anomaly record and raised at the end)
            problems.append((label, exc))
            return None

    context = resolution = split = None
    if not fe003.get("setup_error"):
        context = guarded("有限元参照数据整理", _fe_context, fe003)
        resolution = guarded("地球反照与红外网格对比", _resolution_effect, fe003)
        split = guarded("冷板热量折算诊断", _p_load_split, fe003)
        series_path = guarded("时间历程文件写出", _write_series, fe003)
        if series_path is None and not any(label == "时间历程文件写出" for label, _ in problems):
            problems.append(("时间历程文件写出", RuntimeError("no run produced an archive")))
        case_record.metric("fe_context", context)
        case_record.metric("auxiliary_earth_flux_resolution", resolution)
        case_record.metric("p_load_split_diagnostic", split)
        case_record.metric("series_file", series_path)
        guarded("运行参数记录", _record_run_metrics, fe003, case_record)
    else:
        case_record.metric("setup_error", fe003["setup_error"])
    case_record.metric("setup_wall_s", fe003.get("setup_wall_s"))

    summary = guarded("实际结果摘要", _summary_cn, fe003, context or {}, resolution or {}, split or {})
    if summary is None:
        summary = ("本用例按有限元平均环境工况检验计算节点经冷板的传热计算。实际结果摘要没有生成，各项检查的期望值与实际值"
                   "见本用例的证据文件。")
    case_record.summary(summary)

    unexecuted = [label for name, label in STEP_FUNCTIONS.items()
                  if name != "test_fe003_record" and name not in OUTCOME["started"]]
    if unexecuted:
        case_record.status("partial")
    pending = []
    if problems:
        pending.append("证据记录的测试函数在执行阶段以失败结束，没有完成的部分为" + "、".join(label for label, _ in problems))
    case_record.anomalies(_anomalies_cn(case_record.checks, unexecuted, pending))
    if problems:
        raise AssertionError("FE-003 evidence incomplete: "
                             + "; ".join(f"{label}: {type(exc).__name__}: {exc}" for label, exc in problems))
