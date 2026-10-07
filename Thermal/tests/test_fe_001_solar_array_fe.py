"""FE-001 太阳能板节点有限元对标: the solar array node S against the ISS finite element solar array.

Implements the CASES entry FE-001 of Thermal/test_report/build_test_report_cn.py (thermal design 4.3 T3 first line,
4.4 T4, 4.5 T5; requirements TH-01 and TH-03).

Inputs: front absorptivity 0.72 and emissivity 0.82, back 0.55 and 0.85, areal heat capacity 1.6 kJ/m2K, all from the
FE model parameter table; P_pv is 0.073 times the direct solar power received by the array; the three FE cases (design
cold beta 0, 1321 W/m2, albedo 0.20, OLR 206 W/m2; mean beta 0, 1371, 0.31, 241; design hot beta 75, 1423, 0.40, 286);
400 km circular orbit with period 5553.6 s.
Preconditions: the FE third-orbit time histories and parameter table exist; the attitude quaternion keeps the front
normal on the Sun; SR takes a very large resistance because the FE has no array-radiator conduction, recorded per 9.4.
Steps: 1 orbit_input and earth_flux per case; 2 integrate with the chapter 8 settings until successive orbits repeat,
split at the eclipse boundaries, take the last orbit; 3 compare minimum, mean and maximum with the third orbit of the
FE solar array mean temperature; 4 rerun with albedo and infrared off, record the simplification per 9.4 and the
temperature difference.
Expected: the curves coincide with the FE; without albedo and infrared the temperatures are clearly lower.
Acceptance: minimum, mean and maximum of all three cases within 3 K of the FE.

The real module runs: thermal_derivative is called by sdtwin_sim.coupled.run_coupled (thermal-only run with prescribed
ports) and the surface environment comes from sdtwin_sim.earth_flux through the coupled EnvironmentProvider. Every
reference is independent of the module: FE data (iss_fem/out), the FE parameter table (iss_fem/model/iss_spec.py), the
FE orbit function text, ray direction and eclipse arc of summary.json, closed-form shadow geometry, an Earth-centred
view-factor quadrature and hand T3, T4 and T5 calculations (tests/data/fe_001/fe001_support.py).

How each expected result is judged:
* "curves coincide": every FE output instant of the third orbit against the module solution at the same instant, with
  the acceptance difference of 3 K. No time window is applied; the instants beyond 3 K are reported with their time
  after eclipse entry or exit. The FE report does not establish their cause (its section 5.7 checked the step size only
  on the radiator submodel), so the test reports the differences and does not attribute them.
* orbit_input: the record the module receives is compared with FE data that the test did not use to build it: the FE
  orbit function text evaluated directly, the FE ray direction and the FE eclipse arc eclipse_deg.
* P_pv: the module's absorbed_solar_S_W is compared with a hand T4 value, thermal_derivative is probed at P_pv equal to
  and above absorbed_solar_S_W (design 4.4 and 5.6), and the T3 deduction is measured by changing P_pv alone.
Aggregates never use Python max or min, which drop a NaN; a missing value fails its check. The Chinese summary and the
anomaly text are built only from the recorded check results.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from sdtwin_sim import coupled as cp
from thermal import ThermalInputs, ThermalRangeWarning, ThermalState, assemble_thermal_parameters, calculate_surface_heat, thermal_derivative
from thermal.types import NODE_ORDER, PATH_ORDER

pytestmark = pytest.mark.case("FE-001")

THERMAL_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data" / "fe_001"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load_support():
    spec = importlib.util.spec_from_file_location("fe001_support", DATA_DIR / "fe001_support.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load_support()
CFG = sup.load_json(DATA_DIR / "fe001_config.json")
CASES = tuple(CFG["cases"])
CRIT = CFG["criteria"]
SA = CFG["solar_array"]
SOLVER = CFG["solver"]
I_S = NODE_ORDER.index("S")
I_SR = PATH_ORDER.index("SR")
ACCEPT_K = float(CRIT["acceptance_K"])
STATS = ("min", "mean", "max")
STAT_CN = {"min": "最低", "mean": "平均", "max": "最高"}
SETTING_KEYS = ("method", "rtol", "atol_T_K", "max_step_s", "output_step_s", "environment_step_s", "event_time_tol_s")
NO_EARTH_REASON = (
    "FE-001 step 4: Earth albedo and infrared switched off to record their effect on the solar array temperature "
    "(thermal design 9.4 and appendix B: an explicitly labelled simplification, not a complete orbital environment)"
)
OUTCOME: dict = {"cases": {}}
FAILURES_CN: dict[str, str] = {}  # check name -> Chinese sentence of the failed check, rule-compliant
CURVE_CONTEXT_CN = (
    "有限元报告第 3.8 节规定外热流与温度都按 120 s 间隔计算，第 5.7 节说明散热器子模型以外部件的步长与网格影响未经检验，"
    "本用例没有确定这些逐点差的来源"
)


# ------------------------------------------------------------------------------------------------ check names


def _label(case: str) -> str:
    return CFG["cases"][case]["label_cn"]


def _tag(earth_on: bool) -> str:
    return "反照与红外开启" if earth_on else "反照与红外关闭"


N_FE_DATA = "前提 有限元三个工况的第三圈时程可用"
N_OPTICS = "输入 正面吸收率 0.72 与发射率 0.82，背面吸收率 0.55 与发射率 0.85，发电份额 0.073"
N_AREAL = "输入 面热容 1.6 kJ·m^{−2}·K^{−1}"
N_ENV = "输入 三个工况的环境参数"
N_ORBIT = "输入 高度 400 km 圆轨道，周期 5553.6 s"
N_T5 = "T5 太阳能板热容 C_S 由毯面质量与比热装配"
N_SURF = "T4 太阳能板正反两面的表面记录"
N_SR = "前提 SR 连接取极大热阻表示不导热，并按第 9.4 节记录"
N_QUAD = "步骤1 参照积分自检"
N_QSR = "前提 SR 极大热阻使太阳能板与散热板之间没有导热"
N_SETUP = "计算准备"
N_EVIDENCE = "证据文件写出"
N_SUMMARY = "中文摘要生成"


def n_orbit_input(case: str) -> str:
    return f"步骤1 {_label(case)} orbit_input 与有限元轨道数据一致"


def n_attitude(case: str) -> str:
    return f"步骤1 {_label(case)} 姿态使正面法向始终指向太阳"


def n_flux(case: str) -> str:
    return f"步骤1 {_label(case)} earth_flux 太阳能板两面的反照与地球红外辐照"


def n_run(case: str, earth_on: bool) -> str:
    return f"步骤2 {_label(case)} {_tag(earth_on)} 按第 8 章数值设置完成积分"


def n_repeat(case: str, earth_on: bool) -> str:
    return f"步骤2 {_label(case)} {_tag(earth_on)} 逐圈重复"


def n_segments(case: str) -> str:
    return f"步骤2 {_label(case)} 在日食边界分段"


def n_accept(case: str, key: str) -> str:
    return f"步骤3 验收 {_label(case)} 最后一圈{STAT_CN[key]}温度与有限元第三圈之差"


def n_curve(case: str) -> str:
    return f"步骤3 预期 {_label(case)} 温度曲线与有限元重合"


def n_recorded(case: str) -> str:
    return f"步骤4 {_label(case)} 按第 9.4 节记录关闭反照与红外的简化条件"


def n_direct(case: str) -> str:
    return f"步骤4 {_label(case)} 关闭后 Q_env,S 只含直射吸收"


def n_analytic(case: str) -> str:
    return f"步骤4 {_label(case)} 关闭反照与红外后的温度时程与解析解"


def n_lower(case: str) -> str:
    return f"步骤4 预期 {_label(case)} 关闭反照与红外后温度明显偏低"


def n_emit(case: str) -> str:
    return f"T4 {_label(case)} 太阳能板正反两面的表面辐射"


def n_env(case: str) -> str:
    return f"T4 {_label(case)} 太阳能板环境吸热"


def n_pv(case: str) -> str:
    return f"T3 T4 {_label(case)} 实际电输出不超过 absorbed_solar_S_W 并在太阳能板方程中扣除"


def n_t3(case: str) -> str:
    return f"T3 第一行 {_label(case)} 扣除实际电输出后的太阳能板温度变化"


# every check a complete run records, by test function: the anomaly text lists the ones that were not executed
EXPECTED_CHECKS = {
    "test_inputs_and_preconditions": [N_FE_DATA, N_OPTICS, N_AREAL, N_ENV, N_ORBIT, N_T5, N_SURF, N_SR],
    "test_step1_orbit_input_and_earth_flux": [N_QUAD] + [name(case) for case in CASES
                                                         for name in (n_orbit_input, n_attitude, n_flux)],
    "test_step2_periodic_last_orbit_and_eclipse_segments": [
        name for case in CASES for name in (n_run(case, True), n_repeat(case, True), n_run(case, False),
                                            n_repeat(case, False), n_segments(case))],
    "test_step3_compare_with_fe_third_orbit": [
        name for case in CASES for name in [n_accept(case, key) for key in STATS] + [n_curve(case)]],
    "test_step4_albedo_and_infrared_off": [
        name for case in CASES for name in (n_recorded(case), n_direct(case), n_analytic(case), n_lower(case))],
    "test_solar_array_terms_t3_t4": [
        name for case in CASES for name in (n_emit(case), n_env(case), n_pv(case), n_t3(case))] + [N_QSR],
}
FUNCTION_CN = {
    "test_inputs_and_preconditions": "输入与前提",
    "test_step1_orbit_input_and_earth_flux": "步骤1",
    "test_step2_periodic_last_orbit_and_eclipse_segments": "步骤2",
    "test_step3_compare_with_fe_third_orbit": "步骤3",
    "test_step4_albedo_and_infrared_off": "步骤4",
    "test_solar_array_terms_t3_t4": "T3 与 T4 各项",
    "test_zz_evidence_and_summary": "证据与摘要",
}


# ------------------------------------------------------------------------------------------------ helpers


def _worst(values) -> float:
    """Largest value; NaN when there is none or any value is NaN (Python max drops a NaN that is not first)."""

    array = np.asarray(values, dtype=float).ravel()
    if array.size == 0 or bool(np.isnan(array).any()):
        return math.nan
    return float(array.max())


def _least(values) -> float:
    """Smallest value; NaN when there is none or any value is NaN."""

    array = np.asarray(values, dtype=float).ravel()
    if array.size == 0 or bool(np.isnan(array).any()):
        return math.nan
    return float(array.min())


def _within(value, limit) -> bool:
    """``value <= limit`` for a finite value; NaN, infinity or a missing value fails."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number <= float(limit)


def _check(record, name: str, expected, actual, passed, anomaly_cn: str) -> bool:
    """Record one check; a failed check keeps its Chinese anomaly sentence (report rules) for anomalies_cn."""

    ok = record.check(name, expected, actual, bool(passed))
    if not ok:
        FAILURES_CN[name] = f"{name}未通过，{anomaly_cn or '检查条件未满足'}"
    return ok


def _plain_json(value):
    """JSON-ready copy: numpy values become Python values, NaN and infinities become None."""

    if isinstance(value, dict):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_plain_json(item) for item in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def _metric(record, key: str, value) -> None:
    record.metric(key, _plain_json(value))


def _completed(run: dict) -> bool:
    """The run reached its end: completed status, no error and the last accepted state at t_end."""

    archive = run["archive"]
    final = getattr(archive, "final_thermal_state", None)
    return (run["error"] is None and archive.status == "completed" and final is not None
            and float(final.time_s) == float(run["t_end"]))


def _last_accepted_s(archive) -> float:
    return float(np.asarray(archive.accepted["time_s"])[-1])


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    return math.atan2(float(np.linalg.norm(np.cross(a, b))), float(np.dot(a, b)))


# ------------------------------------------------------------------------------------------------ model set-up


def _area_m2(spec) -> float:
    """Front area of the 16 US solar array blankets of the FE geometry (iss_spec SAW, 8 wings of 2 blankets)."""

    saw = spec.SAW
    return len(saw["wings"]) * 2 * saw["x_len"] * saw["blanket_w"]


def _components(spec, area_m2: float) -> tuple[list[dict], list[dict]]:
    blanket = spec.MATERIALS["saw_blk"]
    mass_kg = blanket["rho"] * blanket["t"] * area_m2
    surfaces = []
    for side in ("front", "back"):
        record = SA[side]
        surfaces.append({
            "surface_id": record["surface_id"], "area_m2": area_m2, "normal_body": record["normal_body"],
            "absorptivity": record["absorptivity"], "emissivity": record["emissivity"], "source": SA["source"],
        })
    components = [{
        "instance_id": SA["instance_id"], "node_id": "S", "asset_id": SA["asset_id"],
        "asset_version": SA["asset_version"],
        "materials": [{"material_id": SA["material_id"], "mass_kg": mass_kg, "cp_J_kgK": blanket["cp"],
                       "source": SA["source"]}],
        "surfaces": surfaces, "temperature_range_K": SA["temperature_range_K"], "ports": ["P_pv_W"],
    }]
    aux = CFG["auxiliary_nodes"]
    for item in aux["components"]:
        components.append({
            "instance_id": item["instance_id"], "node_id": item["node_id"],
            "asset_id": f"fe001_aux_{item['instance_id'].lower()}", "asset_version": "1",
            "materials": [{"material_id": f"{item['instance_id']}_material", "mass_kg": item["mass_kg"],
                           "cp_J_kgK": item["cp_J_kgK"], "source": aux["source"]}],
            "surfaces": [dict(surface, source=aux["source"]) for surface in item.get("surfaces", [])],
            "temperature_range_K": aux["temperature_range_K"], "ports": item["ports"],
        })
    sr = CFG["SR"]
    connections = [{"path": "SR", "equivalent_total_resistance_K_W": sr["equivalent_total_resistance_K_W"],
                    "includes_contact": sr["includes_contact"], "source": sr["source"]}]
    for path, value in aux["resistances_K_W"].items():
        connections.append({"path": path, "equivalent_total_resistance_K_W": value, "includes_contact": True,
                            "source": aux["source"]})
    return components, connections


def _settings() -> cp.SolverSettings:
    return cp.SolverSettings(method=SOLVER["method"], rtol=SOLVER["rtol"], atol_T_K=SOLVER["atol_T_K"],
                             max_step_s=SOLVER["max_step_s"], output_step_s=SOLVER["output_step_s"],
                             environment_step_s=SOLVER["environment_step_s"],
                             event_time_tol_s=SOLVER["event_time_tol_s"])


def _ports(orbit, G, area_m2: float):
    """Prescribed Power ports: P_pv is 0.073 times the direct solar power received by the front, other ports zero."""

    fraction = float(SA["pv_fraction"])
    normal = np.array(SA["front"]["normal_body"], dtype=float)

    def prescribed_ports(t: float) -> dict:
        cos_front = float(orbit.rotation(t).apply(normal) @ orbit.sun_direction(t))
        direct_W = area_m2 * G(t) * max(0.0, cos_front)
        return {"P_pv_W": fraction * direct_W, "P_load_W": 0.0, "Q_B_W": 0.0, "Q_D_W": 0.0}

    return prescribed_ports


def _run(case: str, params, orbit, area_m2: float, earth_on: bool, t_end: float, shift_orbits: int) -> dict:
    env = CFG["cases"][case]
    run_id = f"FE-001-{case}-{'earth' if earth_on else 'no-earth'}-{shift_orbits}"
    G = orbit.irradiance(env["solar_constant_W_m2"])
    if earth_on:
        earth = cp.EarthFluxModel(albedo=env["albedo"], olr_W_m2=env["olr_W_m2"],
                                  solar_constant_W_m2=env["solar_constant_W_m2"], earth_radius_m=orbit.earth_radius_m)
    else:
        earth = cp.EarthFluxModel.disabled(NO_EARTH_REASON)
    epoch = datetime.fromisoformat(CFG["epoch_utc"])
    provider = cp.EnvironmentProvider.from_callables(
        run_id=run_id, epoch=epoch, parameters=params, position=orbit.position, sun_position=orbit.sun_position,
        quaternion=orbit.quaternion, G=G, earth_flux=earth)
    aux_T = CFG["auxiliary_nodes"]["initial_temperature_K"]
    initial = ThermalState(run_id, 0.0, [SA["initial_temperature_K"], aux_T, aux_T, aux_T, aux_T, aux_T])
    provenance = {
        "case_id": "FE-001", "fe_case": case, "fe_label_cn": env["label_cn"],
        "fe_data": f"{CFG['fe']['out_dir']}/{case}/{CFG['fe']['series_file']} column {CFG['fe']['temperature_column']}",
        "environment": dict(env), "earth_flux": "on" if earth_on else f"off: {NO_EARTH_REASON}",
        "time_origin": "orbit noon of the FE run; positions from the FE orbit functions of summary.json",
        "eclipse": "cylindrical Earth shadow along the FE sun_ecs direction, G already includes the eclipse",
        "attitude": "body +Z (front normal of SolarArray01) points at the Sun at every instant, like the FE solar array "
                    "group; body +X along the orbit normal component perpendicular to the Sun line",
        "P_pv_rule": "P_pv_W = 0.073 x front area x G x max(0, cos incidence of the front), the actual electrical "
                     "output given to Thermal; P_load_W = Q_B_W = Q_D_W = 0",
        "SR_configuration": CFG["SR"]["source"],
        "auxiliary_nodes": CFG["auxiliary_nodes"]["note"],
        "integration_span_s": t_end, "extra_orbits_for_repetition": shift_orbits,
        "epoch_note": "nominal UTC epoch; the FE environment is fixed by beta and the case values, not by a date",
    }
    started = time.perf_counter()
    error = None
    try:
        archive = cp.run_coupled(params, initial, provider, t_end, settings=_settings(),
                                 prescribed_ports=_ports(orbit, G, area_m2), provenance=provenance)
    except cp.CoupledRunError as exc:
        archive, error = exc.archive, f"{type(exc).__name__}: {exc}"
    return {"run_id": run_id, "archive": archive, "provider": provider, "error": error, "G": G, "t_end": t_end,
            "shift_orbits": shift_orbits, "wall_s": time.perf_counter() - started, "earth_on": earth_on}


def _repetition_K(run: dict, period: float) -> float:
    """Largest difference of T_S between the last orbit and the orbit before it at the same phase.

    NaN for a run that did not reach its end: beyond the last accepted state ``state_at`` holds that state, which
    would read as a perfectly periodic solution.
    """

    if not _completed(run):
        return math.nan
    archive, t_end = run["archive"], run["t_end"]
    grid = np.append(np.arange(t_end - period, t_end, float(CRIT["statistics_grid_s"])), t_end)
    last = archive.state_at(grid)[:, I_S]
    previous = archive.state_at(grid - period)[:, I_S]
    return float(np.max(np.abs(last - previous)))


@pytest.fixture(scope="module")
def fe001():
    spec = sup.load_spec(THERMAL_DIR / CFG["fe"]["spec_file"])
    area = _area_m2(spec)
    components, connections = _components(spec, area)
    params = assemble_thermal_parameters(components, connections, None)
    fe_dir = THERMAL_DIR / CFG["fe"]["out_dir"]
    data = {"spec": spec, "area_m2": area, "components": components, "connections": connections,
            "params": params, "cases": {}}
    for case in CASES:
        summary = sup.load_json(fe_dir / case / CFG["fe"]["summary_file"])
        orbit = sup.FEOrbit(summary["orbit"], spec.ORBIT["R_earth_m"])
        series = sup.read_fe_series(fe_dir / case / CFG["fe"]["series_file"], CFG["fe"]["time_column"],
                                    CFG["fe"]["temperature_column"], tuple(CFG["fe"]["spread_columns"]))
        fe_end = float(CFG["fe"]["end_time_s"])
        attempts = []
        for extra in range(int(CRIT["max_extra_orbits"]) + 1):
            run = _run(case, params, orbit, area, True, fe_end + extra * orbit.period_s, extra)
            run["repetition_K"] = _repetition_K(run, orbit.period_s)
            attempts.append(run)
            if run["error"] is not None or _within(run["repetition_K"], CRIT["repetition_K"]):
                break  # a stopped run is not retried with a longer span
        earth = attempts[-1]
        no_earth = _run(case, params, orbit, area, False, earth["t_end"], earth["shift_orbits"])
        no_earth["repetition_K"] = _repetition_K(no_earth, orbit.period_s)
        data["cases"][case] = {"name": case, "summary": summary, "orbit": orbit, "series": series,
                               "attempts": attempts, "earth": earth, "no_earth": no_earth, "fe_end": fe_end,
                               "shift_s": earth["shift_orbits"] * orbit.period_s}
    return data


# ------------------------------------------------------------------------------------------------ shared evaluations


def _check_times(case_data: dict) -> np.ndarray:
    """Output samples of the last orbit used for term checks: every k-th sample plus both neighbours of each
    closed-form eclipse boundary."""

    archive = case_data["earth"]["archive"]
    orbit = case_data["orbit"]
    t_end = case_data["earth"]["t_end"]
    t0 = t_end - orbit.period_s
    t = np.asarray(archive.time_s)
    inside = np.flatnonzero((t >= t0) & (t <= t_end))
    chosen = set(inside[:: int(CRIT["term_check_stride"])].tolist())
    for entry, exit_ in orbit.eclipse_windows(t0, t_end):
        for moment in (entry, exit_):
            if t0 <= moment <= t_end:
                after = int(np.searchsorted(t, moment))
                chosen.update(index for index in (after - 1, after) if 0 <= index < t.size and t0 <= t[index] <= t_end)
    return np.array(sorted(chosen), dtype=int)


def _reference_flux(case_data: dict) -> dict:
    """Independent albedo and infrared irradiances of the two array faces at the check instants (cached)."""

    if "reference_flux" in case_data:
        return case_data["reference_flux"]
    orbit = case_data["orbit"]
    env = CFG["cases"][case_data["name"]]
    quad = CFG["reference_quadrature"]
    archive = case_data["earth"]["archive"]
    indices = _check_times(case_data)
    times = np.asarray(archive.time_s)[indices]
    normals_body = np.array([SA["front"]["normal_body"], SA["back"]["normal_body"]], dtype=float)
    albedo, infrared, cosines = [], [], []
    for moment in times:
        rotation = orbit.rotation(float(moment))
        normals = rotation.apply(normals_body)
        view, alb = sup.plate_factors(orbit.position(float(moment)), normals, orbit.sun_hat, orbit.earth_radius_m,
                                      quad["n_psi"], quad["n_phi"])
        albedo.append(env["albedo"] * env["solar_constant_W_m2"] * alb)
        infrared.append(env["olr_W_m2"] * view)
        cosines.append(normals @ orbit.sun_direction(float(moment)))
    result = {"indices": indices, "times": times, "albedo": np.array(albedo), "infrared": np.array(infrared),
              "cos": np.array(cosines)}
    case_data["reference_flux"] = result
    return result


def _fe_geometry(case_data: dict) -> dict:
    """FE orbit record of summary.json: position from the function text, Sun direction from the FE rays, orbit normal,
    shadow centre (the FE ray direction projected on the orbit plane), eclipse arc and period."""

    if "fe_geometry" in case_data:
        return case_data["fe_geometry"]
    record = case_data["summary"]["orbit"]
    position = sup.fe_position_function(record["funcs"])
    rays = np.array([float(value) for value in record["rays"]])
    ray_hat = rays / np.linalg.norm(rays)
    period = float(record["period"])
    normal = np.cross(position(0.0), position(period / 4.0))
    normal /= np.linalg.norm(normal)
    centre = ray_hat - (ray_hat @ normal) * normal
    centre /= np.linalg.norm(centre)
    geometry = {"position": position, "sun_hat": -ray_hat, "centre": centre, "normal": normal,
                "eclipse_deg": float(record["eclipse_deg"]), "period_s": period}
    case_data["fe_geometry"] = geometry
    return geometry


def _dense(run: dict, period: float) -> dict:
    """Dense evaluation of T_S over the last orbit (1 s grid plus every accepted state) and its statistics; NaN
    statistics for a run that did not reach its end."""

    if "dense" in run:
        return run["dense"]
    if not _completed(run):
        missing = {key: math.nan for key in ("min", "mean", "max", "argmin_s", "argmax_s")}
        run["dense"] = {"grid": np.array([]), "T_C": np.array([]), "stats": missing}
        return run["dense"]
    archive = run["archive"]
    t_end = run["t_end"]
    grid = sup.dense_period_grid(archive.accepted["time_s"], t_end - period, t_end, float(CRIT["statistics_grid_s"]))
    values = archive.state_at(grid)[:, I_S] - 273.15
    run["dense"] = {"grid": grid, "T_C": values, "stats": sup.dense_period_stats(grid, values)}
    return run["dense"]


def _surface_index(params, surface_id: str) -> int:
    return [surface.surface_id for surface in params.surfaces].index(surface_id)


def _fmt_stats(stats: dict) -> str:
    return f"{sup.num(stats['min'])} / {sup.num(stats['mean'])} / {sup.num(stats['max'])} °C"


# ------------------------------------------------------------------------------------------------ inputs and preconditions


def test_inputs_and_preconditions(fe001, case_record):
    """Case inputs against the FE parameter table and FE run summaries; T5 assembly of C_S; SR configuration."""

    spec, params, area = fe001["spec"], fe001["params"], fe001["area_m2"]
    inputs = OUTCOME.setdefault("inputs", {})
    results = []

    # precondition: FE third-orbit histories
    rows, reasons, ok = [], [], True
    column, end, interval = CFG["fe"]["temperature_column"], CFG["fe"]["end_time_s"], CFG["fe"]["output_interval_s"]
    for case in CASES:
        series = fe001["cases"][case]["series"]
        orbit = fe001["cases"][case]["orbit"]
        t = series["t_s"]
        t0 = series["t_s"][-1] - orbit.period_s
        window = t[t >= t0]
        gaps = float(np.max(np.diff(window))) if window.size > 1 else math.inf
        has = column in series["columns"]
        spread = series["duplicate_value_spread"]
        span_ok = t[0] == 0.0 and t[-1] == end
        good = has and span_ok and _within(gaps, interval) and spread == 0.0
        ok &= good
        rows.append(f"{case}: {series['rows']} 行，{t.size} 个不同时刻 {t[0]:g} 至 {t[-1]:g} s，第三圈 {t0:.2f} 至 "
                    f"{t[-1]:g} s 内最大间隔 {gaps:g} s，事件时刻 {np.round(series['event_times_s'], 2).tolist()} s 的重复行"
                    f"数值差 {spread:g}")
        if not good:
            why = ([] if has else [f"缺少 {column} 列"]) + ([] if span_ok else [f"时程为 {sup.gen(t[0])} 至 {sup.gen(t[-1])} s"])
            why += [] if _within(gaps, interval) else [f"第三圈最大输出间隔 {sup.gen(gaps)} s"]
            why += [] if spread == 0.0 else [f"事件时刻重复行的数值差 {sup.gen(spread)} K"]
            reasons.append(f"{_label(case)}的有限元时程{'，'.join(why)}")
    results.append(_check(
        case_record, N_FE_DATA,
        f"series.csv 含 {column}，自 0 s 起到 {end:g} s，最后一个轨道周期内输出间隔不超过 {interval:g} s，事件时刻的重复行"
        "数值相同",
        "；".join(rows), ok, "；".join(reasons)))

    # inputs: optical properties and areal heat capacity from the FE parameter table
    cells, back = spec.OPTICS["saw_cells"], spec.OPTICS["saw_back"]
    front_alpha_fe = cells["alpha"] + SA["pv_fraction"]
    blanket = spec.MATERIALS["saw_blk"]
    areal = blanket["rho"] * blanket["cp"] * blanket["t"]
    optics_ok = (abs(front_alpha_fe - SA["front"]["absorptivity"]) <= 1e-12
                 and cells["eps"] == SA["front"]["emissivity"]
                 and back["alpha"] == SA["back"]["absorptivity"] and back["eps"] == SA["back"]["emissivity"])
    results.append(_check(
        case_record, N_OPTICS,
        "iss_spec OPTICS saw_cells 的吸收率加发电份额 0.073 等于 0.72，发射率 0.82；saw_back 为 0.55 与 0.85",
        f"saw_cells 吸收率 {cells['alpha']!r} 加 {SA['pv_fraction']} 为 {front_alpha_fe!r}，发射率 {cells['eps']}；"
        f"saw_back 吸收率 {back['alpha']}，发射率 {back['eps']}", optics_ok,
        f"有限元参数表给出正面吸收率 {sup.gen(front_alpha_fe)}、发射率 {sup.gen(cells['eps'])}，背面吸收率 "
        f"{sup.gen(back['alpha'])}、发射率 {sup.gen(back['eps'])}，与输入的 0.72、0.82、0.55 与 0.85 不一致"))
    areal_ok = abs(areal - SA["areal_heat_capacity_J_m2K"]) <= 1e-9 * SA["areal_heat_capacity_J_m2K"]
    results.append(_check(
        case_record, N_AREAL,
        f"iss_spec MATERIALS saw_blk 的密度、比热与厚度之积等于 {SA['areal_heat_capacity_J_m2K']:g} J/(m²·K)",
        f"{blanket['rho']:g} kg/m³ × {blanket['cp']:g} J/(kg·K) × {blanket['t']:g} m = {areal:.6g} J/(m²·K)", areal_ok,
        f"有限元参数表 saw_blk 的密度、比热与厚度之积为 {sup.gen(areal)} J·m^{{−2}}·K^{{−1}}，与输入的 "
        f"{sup.gen(SA['areal_heat_capacity_J_m2K'])} J·m^{{−2}}·K^{{−1}} 不一致"))

    # inputs: environment of the three cases
    rows, reasons, ok = [], [], True
    for case in CASES:
        env, fe_env = CFG["cases"][case], spec.CASES[case]
        orbit = fe001["cases"][case]["orbit"]
        good = (fe_env["beta_deg"] == env["beta_deg"] and fe_env["S_sun"] == env["solar_constant_W_m2"]
                and fe_env["albedo"] == env["albedo"] and fe_env["olr"] == env["olr_W_m2"]
                and abs(orbit.beta_deg() - env["beta_deg"]) <= 0.01)
        ok &= good
        rows.append(f"{case}: β {fe_env['beta_deg']}°，太阳常数 {fe_env['S_sun']} W/m²，反照率 {fe_env['albedo']}，"
                    f"地球红外 {fe_env['olr']} W/m²；sun_ecs 与有限元轨道法向给出 β {orbit.beta_deg():.4f}°")
        if not good:
            reasons.append(f"{_label(case)}的有限元参数表给出 β {sup.gen(fe_env['beta_deg'])}°、太阳常数 "
                           f"{sup.gen(fe_env['S_sun'])} W/m^{{2}}、反照率 {sup.gen(fe_env['albedo'])}、地球红外 "
                           f"{sup.gen(fe_env['olr'])} W/m^{{2}}，sun_ecs 给出 β {sup.num(orbit.beta_deg(), 4)}°")
    inputs["env_ok"] = ok
    results.append(_check(
        case_record, N_ENV,
        "设计冷工况 β 0°、1321 W/m²、0.20、206 W/m²；平均环境工况 β 0°、1371 W/m²、0.31、241 W/m²；设计热工况 β 75°、"
        "1423 W/m²、0.40、286 W/m²；与 iss_spec CASES 相同，sun_ecs 的 β 与工况相差不超过 0.01°",
        "；".join(rows), ok, "；".join(reasons) + "，与输入不一致"))

    # inputs: orbit
    rows, reasons, ok = [], [], True
    for case in CASES:
        orbit = fe001["cases"][case]["orbit"]
        keplerian = 2.0 * math.pi * math.sqrt(orbit.radius_m**3 / spec.ORBIT["mu"])
        altitude = orbit.radius_m - orbit.earth_radius_m
        good = (abs(altitude - CFG["orbit"]["altitude_m"]) <= 1e-6 and orbit.radius_m == orbit.summary_radius_m
                and round(orbit.period_s, 1) == CFG["orbit"]["period_s"] and abs(orbit.period_s - keplerian) <= 1e-3
                and orbit.phase_rad == 0.0)
        ok &= good
        rows.append(f"{case}: 半径 {orbit.radius_m:.1f} m，高度 {altitude:.1f} m，周期 {orbit.period_s} s，"
                    f"按 μ 算得 {keplerian:.6f} s，倾角 {orbit.inclination_rad} rad，初始相位 {orbit.phase_rad}")
        if not good:
            reasons.append(f"{_label(case)}的轨道高度 {sup.gen(altitude)} m，周期 {sup.gen(orbit.period_s, 9)} s，开普勒周期 "
                           f"{sup.gen(keplerian, 9)} s，初始相位 {sup.gen(orbit.phase_rad)} rad")
    first_orbit = fe001["cases"][CASES[0]]["orbit"]
    inputs.update({"orbit_ok": ok, "period_s": first_orbit.period_s,
                   "altitude_m": first_orbit.radius_m - first_orbit.earth_radius_m})
    results.append(_check(
        case_record, N_ORBIT,
        "有限元轨道函数半径减地球半径 6378137 m 等于 400 km，周期取一位小数为 5553.6 s 且与开普勒周期相差不超过 1 ms，"
        "自轨道正午起算",
        "；".join(rows), ok, "；".join(reasons) + "，与输入不符"))

    # T5: C_S from mass and specific heat, surfaces of S, SR configuration
    c_s = float(params.C_J_K[I_S])
    c_hand = SA["areal_heat_capacity_J_m2K"] * area
    rel = abs(c_s - c_hand) / c_hand
    _metric(case_record, "solar_array", {"area_m2": area, "C_S_J_K": c_s, "C_S_hand_J_K": c_hand,
                                         "mass_kg": spec.MATERIALS["saw_blk"]["rho"] * spec.MATERIALS["saw_blk"]["t"]
                                         * area})
    inputs.update({"area_m2": area, "blankets": len(spec.SAW["wings"]) * 2, "areal_J_m2K": areal, "C_S_J_K": c_s})
    results.append(_check(
        case_record, N_T5,
        f"C_S 等于面热容乘正面面积 {area:.3f} m²，即 {c_hand:.6g} J/K，相对差不超过 {CRIT['relative_tol_exact']:g}",
        f"assemble_thermal_parameters 给出 C_S {c_s!r} J/K，相对差 {rel:.2e}", _within(rel, CRIT["relative_tol_exact"]),
        f"assemble_thermal_parameters 给出的 C_S 为 {sup.gen(c_s, 9)} J/K，手算为 {sup.gen(c_hand, 9)} J/K，相对差 "
        f"{sup.sci(rel)}，超过 {sup.sci(CRIT['relative_tol_exact'])}"))

    surfaces = {surface.surface_id: surface for surface in params.surfaces}
    rows, reasons, ok = [], [], True
    for side in ("front", "back"):
        record = SA[side]
        surface = surfaces.get(record["surface_id"])
        good = (surface is not None and surface.node_id == "S" and surface.area_m2 == area
                and surface.absorptivity == record["absorptivity"] and surface.emissivity == record["emissivity"]
                and np.array_equal(surface.normal_body, np.array(record["normal_body"], dtype=float)))
        ok &= good
        rows.append(f"{record['surface_id']}: 节点 {getattr(surface, 'node_id', None)}，面积 "
                    f"{getattr(surface, 'area_m2', float('nan')):.3f} m²，吸收率 {getattr(surface, 'absorptivity', None)}，"
                    f"发射率 {getattr(surface, 'emissivity', None)}，法向 "
                    f"{None if surface is None else surface.normal_body.tolist()}")
        if surface is None:
            reasons.append(f"缺少表面记录 {record['surface_id']}")
        elif not good:
            reasons.append(f"表面记录 {record['surface_id']} 的节点、面积、光学性质或法向与输入不符")
        else:
            inputs.setdefault("optics", {})[side] = (float(surface.absorptivity), float(surface.emissivity))
    inputs["surfaces_ok"] = ok
    results.append(_check(
        case_record, N_SURF,
        "正面与背面为两条独立记录，均属节点 S，面积相同，正面法向沿本体 +Z，背面沿 −Z，光学性质取输入值",
        "；".join(rows), ok, "；".join(reasons)))

    sr = params.provenance["resistance"]["SR"]
    r_sr = float(params.R_K_W[I_SR])
    sr_ok = (r_sr == CFG["SR"]["equivalent_total_resistance_K_W"] and sr["method"] == "equivalent_total"
             and "9.4" in sr["source"])
    inputs["R_SR_K_W"] = r_sr
    results.append(_check(
        case_record, N_SR,
        f"R_SR 为 {CFG['SR']['equivalent_total_resistance_K_W']:g} K/W，按等效总热阻装配，来源注明有限元不计太阳翼与散热器"
        "之间的导热与第 9.4 节",
        f"R_SR {r_sr:g} K/W，方法 {sr['method']}，来源 {sr['source']}", sr_ok,
        f"R_SR 为 {sup.sci(r_sr)} K/W，装配方法为 {sr['method']}，来源记录{'含' if '9.4' in sr['source'] else '缺少'}"
        "第 9.4 节"))
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 1


def test_step1_orbit_input_and_earth_flux(fe001, case_record):
    """Step 1: orbit_input against independent FE orbit data, prepare_surface_environment and earth_flux."""

    params = fe001["params"]
    spec = fe001["spec"]
    i_front = _surface_index(params, SA["front"]["surface_id"])
    i_back = _surface_index(params, SA["back"]["surface_id"])
    epoch = datetime.fromisoformat(CFG["epoch_utc"])
    results = []

    # accuracy of the independent reference quadrature itself: closed-form plates and a 1-D integral
    quad = CFG["reference_quadrature"]
    orbit0 = fe001["cases"][CASES[0]]["orbit"]
    r, R = orbit0.radius_m, orbit0.earth_radius_m
    view, albedo = sup.plate_factors(np.array([r, 0.0, 0.0]), np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                                                                          [1.0, 0.0, 0.0]]),
                                     np.array([1.0, 0.0, 0.0]), R, quad["n_psi"], quad["n_phi"])
    nadir_1d, nadir_albedo_1d = sup.nadir_plate_factors_1d(r, R)
    exact = {"nadir": (R / r) ** 2, "vertical": sup.vertical_plate_view_factor(r, R), "zenith": 0.0}
    self_err = _worst([abs(view[0] - exact["nadir"]), abs(view[1] - exact["vertical"]), abs(view[2] - exact["zenith"]),
                       abs(albedo[0] - nadir_albedo_1d), abs(nadir_1d - exact["nadir"])])
    OUTCOME["quadrature_err"] = self_err
    results.append(_check(
        case_record, N_QUAD,
        f"地心球冠积分给出的对地平板视角系数等于 (R/r)²，垂直平板等于解析式，背地平板为零，对地平板反照系数与一维自适应积分"
        f"一致，差不超过视角系数容差的十分之一 {CRIT['view_factor_tol'] / 10:g}",
        f"对地 {view[0]:.10f}，解析 {exact['nadir']:.10f}；垂直 {view[1]:.10f}，解析 {exact['vertical']:.10f}；背地 "
        f"{view[2]:.3g}；对地反照系数 {albedo[0]:.10f}，一维积分 {nadir_albedo_1d:.10f}；最大差 {self_err:.2e}",
        _within(self_err, CRIT["view_factor_tol"] / 10),
        f"地心球冠参照积分与解析值和一维积分的最大差为 {sup.sci(self_err)}，超过 {sup.sci(CRIT['view_factor_tol'] / 10)}，"
        "earth_flux 对比缺少可靠参照"))
    _metric(case_record, "reference_quadrature_self_check", {
        "nadir_view": float(view[0]), "nadir_exact": exact["nadir"], "vertical_view": float(view[1]),
        "vertical_exact": exact["vertical"], "zenith_view": float(view[2]), "nadir_albedo": float(albedo[0]),
        "nadir_albedo_1d": nadir_albedo_1d, "max_error": self_err, "n_psi": quad["n_psi"], "n_phi": quad["n_phi"]})

    for case in CASES:
        data = fe001["cases"][case]
        env = CFG["cases"][case]
        orbit = data["orbit"]
        run = data["earth"]
        archive, provider = run["archive"], run["provider"]
        ref = _reference_flux(data)
        geometry = _fe_geometry(data)
        solar_constant = float(spec.CASES[case]["S_sun"])

        # orbit_input as the module receives it, against FE data the test did not use to build it
        record_bad, position_err, sun_err, changed_G = [], [], [], 0
        cos_front, cos_back, alb_err, ir_err = [], [], [], []
        for k, moment in enumerate(ref["times"]):
            t = float(moment)
            sample = provider.sample(t)
            orbit_input, surface_env, flux = sample.orbit_input, sample.surface_environment, sample.earth_flux
            quaternion = np.asarray(orbit_input["quaternion_xyzw"], dtype=float)
            stamp = orbit_input["epoch"]
            fields_ok = (orbit_input["frame"] == "GCRS" and orbit_input["run_id"] == run["run_id"]
                         and float(orbit_input["time_s"]) == t and isinstance(stamp, datetime)
                         and stamp.utcoffset() is not None and stamp == epoch
                         and abs(float(np.linalg.norm(quaternion)) - 1.0) <= CRIT["quaternion_norm_tol"]
                         and float(orbit_input["G_W_m2"]) >= 0.0)
            if not fields_ok:
                record_bad.append(t)
            position_err.append(np.max(np.abs(np.asarray(orbit_input["position_m"], dtype=float)
                                              - geometry["position"](t))))
            sun = np.asarray(orbit_input["sun_position_m"], dtype=float)
            sun_err.append(np.max(np.abs(sun / np.linalg.norm(sun) - geometry["sun_hat"])))
            changed_G += int(surface_env["G_W_m2"] != orbit_input["G_W_m2"])
            cos_front.append(float(surface_env["cos_incidence"][i_front]))
            cos_back.append(float(surface_env["cos_incidence"][i_back]))
            for j, index in enumerate((i_front, i_back)):
                alb_err.append(abs(float(flux["albedo_W_m2"][index]) - ref["albedo"][k, j])
                               / (env["albedo"] * env["solar_constant_W_m2"]))
                ir_err.append(abs(float(flux["infrared_W_m2"][index]) - ref["infrared"][k, j]) / env["olr_W_m2"])
        position_max, sun_max = _worst(position_err), _worst(sun_err)

        # eclipse arcs that the run located from G, against the FE eclipse arc eclipse_deg and the FE shadow centre
        pairs, structure_ok, pending = [], True, None
        for boundary in archive.eclipse_boundaries:
            if boundary.is_eclipse_entry and pending is None:
                pending = boundary.time_s
            elif boundary.is_eclipse_exit and pending is not None:
                pairs.append((pending, boundary.time_s))
                pending = None
            else:
                structure_ok = False
        ecl_deg = geometry["eclipse_deg"]
        to_s = geometry["period_s"] / 360.0
        arc_err, centre_err = [], []
        for entry, exit_ in pairs:
            r_in, r_out = geometry["position"](entry), geometry["position"](exit_)
            arc_err.append(abs(math.degrees(_angle(r_in, r_out)) - ecl_deg) * to_s)
            middle = r_in / np.linalg.norm(r_in) + r_out / np.linalg.norm(r_out)
            centre_err.append(math.degrees(_angle(middle, geometry["centre"])) * to_s)
        arc_max = _worst(arc_err + centre_err) if pairs else 0.0
        arcs_ok = structure_ok and (len(pairs) > 0) == (ecl_deg > 0.0) and _within(arc_max, CRIT["eclipse_time_tol_s"])

        # G of every output sample against the FE shadow arc (half of eclipse_deg on each side of the FE shadow centre)
        out_t = np.asarray(archive.time_s)
        out_G = np.asarray(archive.environment["G_W_m2"])
        expected_G = np.array([0.0 if ecl_deg > 0.0 and math.degrees(_angle(geometry["position"](float(moment)),
                                                                             geometry["centre"])) < 0.5 * ecl_deg
                               else solar_constant for moment in out_t])
        g_bad = int(np.count_nonzero(~(out_G == expected_G)))  # a NaN sample counts as a mismatch
        eclipse_samples = int(np.count_nonzero(expected_G == 0.0))
        fe_events = data["series"]["event_times_s"]
        located = [boundary.time_s - data["shift_s"] for boundary in archive.eclipse_boundaries]
        orbit_ok = (not record_bad and _within(position_max, CRIT["position_tol_m"])
                    and _within(sun_max, CRIT["sun_direction_tol"]) and arcs_ok and g_bad == 0 and changed_G == 0)
        problems = []
        if record_bad:
            problems.append(f"{len(record_bad)} 个校核时刻的 orbit_input 字段与本次运行不符")
        if not _within(position_max, CRIT["position_tol_m"]):
            problems.append(f"位置与有限元轨道函数文本求值之差最大 {sup.sci(position_max)} m，超过 "
                            f"{sup.sci(CRIT['position_tol_m'])} m")
        if not _within(sun_max, CRIT["sun_direction_tol"]):
            problems.append(f"太阳方向与有限元光线反方向之差最大 {sup.sci(sun_max)}，超过 {sup.sci(CRIT['sun_direction_tol'])}")
        if not arcs_ok:
            problems.append(f"由 G 定位的日食 {len(pairs)} 段与有限元 eclipse_deg {sup.gen(ecl_deg)}° 不符，弧长与中心之差折合"
                            f"时间最大 {sup.sci(arc_max)} s")
        if g_bad:
            problems.append(f"{g_bad} 个输出样点的 G 与有限元地影弧段不符")
        if changed_G:
            problems.append(f"prepare_surface_environment 在 {changed_G} 个时刻改动了 G")
        results.append(_check(
            case_record, n_orbit_input(case),
            "模块收到的 orbit_input 中 frame 为 GCRS，run_id、time_s 与 epoch 与本次运行一致，四元数模长与 1 之差不超过 "
            f"{CRIT['quaternion_norm_tol']:g}；position_m 与直接按有限元 summary.json 轨道函数文本求得的位置之差不超过 "
            f"{CRIT['position_tol_m']:g} m；sun_position_m 的方向与有限元光线 rays 的反方向之差不超过 "
            f"{CRIT['sun_direction_tol']:g}；由 G_W_m2 定位的日食弧段与有限元 eclipse_deg 及光线投影方向相差折合时间不超过 "
            f"{CRIT['eclipse_time_tol_s']:g} s；全部输出样点的 G_W_m2 在有限元地影弧段内为 0、弧段外为工况太阳常数；"
            "prepare_surface_environment 原样传递 G",
            f"{len(ref['times'])} 个校核时刻记录字段不符 {len(record_bad)} 个，位置最大差 {position_max:.3g} m，太阳方向最大差 "
            f"{sun_max:.3g}，G 被改动 {changed_G} 次；模块定位日食 {len(pairs)} 段，有限元 eclipse_deg {ecl_deg:.9f}°，弧长与"
            f"中心之差折合时间最大 {arc_max:.3g} s；全部 {out_t.size} 个输出样点中 G 不符 {g_bad} 个，地影内样点 "
            f"{eclipse_samples} 个；有限元求解器记录的事件时刻 {np.round(fe_events, 2).tolist()} s，模块定位的边界 "
            f"{np.round(located, 4).tolist()} s，前者是有限元结果的输出事件，只作记录",
            orbit_ok, "；".join(problems)))

        cos_err = _worst(np.abs(np.concatenate([np.array(cos_front) - 1.0, np.array(cos_back) + 1.0,
                                                ref["cos"][:, 0] - 1.0])))
        results.append(_check(
            case_record, n_attitude(case),
            f"四元数把本体 +Z 转到卫星指向太阳的方向；模块给出的正面入射余弦为 1，背面为 −1，偏差不超过 "
            f"{CRIT['relative_tol_exact']:g}",
            f"正面余弦 {min(cos_front):.16f} 至 {max(cos_front):.16f}，背面 {min(cos_back):.16f} 至 "
            f"{max(cos_back):.16f}，独立旋转给出的正面余弦最小 {ref['cos'][:, 0].min():.16f}，最大偏差 {cos_err:.2e}",
            _within(cos_err, CRIT["relative_tol_exact"]),
            f"模块给出的正反两面入射余弦与 1 和 {sup.MINUS}1 之差最大 {sup.sci(cos_err)}，超过 "
            f"{sup.sci(CRIT['relative_tol_exact'])}"))
        alb_max, ir_max = _worst(alb_err), _worst(ir_err)
        results.append(_check(
            case_record, n_flux(case),
            f"与地心球冠独立积分之差折合视角系数不超过 {CRIT['view_factor_tol']:g}，即反照差不超过 "
            f"{CRIT['view_factor_tol'] * env['albedo'] * env['solar_constant_W_m2']:.4f} W/m²，红外差不超过 "
            f"{CRIT['view_factor_tol'] * env['olr_W_m2']:.4f} W/m²",
            f"{len(ref['times'])} 个时刻两面反照差最大折合视角系数 {alb_max:.2e}，红外 {ir_max:.2e}；独立积分正面反照 "
            f"{ref['albedo'][:, 0].min():.2f} 至 {ref['albedo'][:, 0].max():.2f} W/m²，背面反照 "
            f"{ref['albedo'][:, 1].min():.2f} 至 {ref['albedo'][:, 1].max():.2f} W/m²，背面红外 "
            f"{ref['infrared'][:, 1].min():.2f} 至 {ref['infrared'][:, 1].max():.2f} W/m²",
            _within(alb_max, CRIT["view_factor_tol"]) and _within(ir_max, CRIT["view_factor_tol"]),
            f"两面反照差折合视角系数最大 {sup.sci(alb_max)}，红外 {sup.sci(ir_max)}，限值 {sup.sci(CRIT['view_factor_tol'])}"))
        OUTCOME["cases"].setdefault(case, {}).update({
            "position_err_m": position_max, "sun_direction_err": sun_max, "eclipse_arc_err_s": arc_max,
            "g_out_bad": g_bad, "cos_err": cos_err, "flux_view_factor_err": _worst([alb_max, ir_max]),
            "check_instants": int(len(ref["times"])), "fe_eclipse_deg": ecl_deg})
        _metric(case_record, f"{case}_step1", {
            "check_instants": int(len(ref["times"])), "orbit_input_field_mismatches": len(record_bad),
            "position_err_vs_fe_function_text_m": position_max, "sun_direction_err_vs_fe_rays": sun_max,
            "eclipse_arcs": [list(pair) for pair in pairs], "fe_eclipse_deg": ecl_deg,
            "eclipse_arc_and_centre_err_s": arc_max, "G_mismatch_output_samples": g_bad,
            "eclipse_output_samples": eclipse_samples, "G_changed_by_prepare_surface_environment": changed_G,
            "fe_event_times_s": fe_events, "module_boundaries_on_fe_axis_s": located,
            "cos_front_minmax": [min(cos_front), max(cos_front)], "cos_back_minmax": [min(cos_back), max(cos_back)],
            "albedo_err_view_factor": alb_max, "infrared_err_view_factor": ir_max})
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 2


def test_step2_periodic_last_orbit_and_eclipse_segments(fe001, case_record):
    """Step 2: chapter 8 settings, integration until successive orbits repeat, segments at the eclipse boundaries."""

    results = []
    status_cn = {"completed": "完成", "stopped": "中途停止"}
    for case in CASES:
        data = fe001["cases"][case]
        orbit = data["orbit"]
        outcome = OUTCOME["cases"].setdefault(case, {})
        for run in (data["earth"], data["no_earth"]):
            archive = run["archive"]
            settings = dict(archive.solver_settings)
            OUTCOME.setdefault("settings", settings)
            settings_ok = all(settings.get(key) == SOLVER[key] for key in SETTING_KEYS)
            stats = archive.statistics
            done = _completed(run)
            last = _last_accepted_s(archive)
            problems = [] if done else [f"运行状态为{status_cn.get(archive.status, archive.status)}，最后接受的时刻为 "
                                        f"{sup.gen(last)} s"]
            problems += [] if settings_ok else ["求解设置与第 8 章配置不一致"]
            results.append(_check(
                case_record, n_run(case, run["earth_on"]),
                f"运行完成，RK45，相对容限 {SOLVER['rtol']:g}，温度绝对容限 {SOLVER['atol_T_K']:g} K，最大步长 "
                f"{SOLVER['max_step_s']:g} s，输出间隔 {SOLVER['output_step_s']:g} s，积分到 {run['t_end']:.4f} s",
                f"状态 {archive.status}，错误 {run['error']}，最后接受时刻 {last:.4f} s，设置 {settings}，接受步 "
                f"{stats['accepted_steps']}，拒绝步 {stats['rejected_steps']}，函数调用 {stats['function_evaluations']}，"
                f"耗时 {run['wall_s']:.1f} s",
                done and settings_ok, "，".join(problems)))
            repetition = run["repetition_K"]
            results.append(_check(
                case_record, n_repeat(case, run["earth_on"]),
                f"最后一圈与前一圈同相位的太阳能板温度差不超过 {CRIT['repetition_K']:g} K",
                f"积分 {run['t_end']:.2f} s，即 {run['t_end'] / orbit.period_s:.4f} 圈，同相位温度差最大 "
                f"{repetition:.2e} K；尝试的积分时长 "
                f"{[round(item['t_end'], 2) for item in data['attempts']] if run['earth_on'] else [round(run['t_end'], 2)]} s",
                _within(repetition, CRIT["repetition_K"]),
                (f"同相位温度差最大 {sup.sci(repetition)} K，超过 {sup.gen(CRIT['repetition_K'])} K" if math.isfinite(repetition)
                 else "运行没有到达结束时刻，未得到最后两圈的同相位温度差")))
            outcome[f"run_ok_{'earth' if run['earth_on'] else 'no_earth'}"] = done and settings_ok
            _metric(case_record, f"{case}_{'earth' if run['earth_on'] else 'no_earth'}_run", {
                "run_id": run["run_id"], "status": archive.status, "t_end_s": run["t_end"],
                "last_accepted_s": last, "repetition_K": repetition, "wall_s": run["wall_s"],
                "accepted_steps": stats["accepted_steps"], "rejected_steps": stats["rejected_steps"],
                "function_evaluations": stats["function_evaluations"], "segments": stats["segments"],
                "eclipse_boundaries": stats["eclipse_boundaries"], "range_warnings": len(archive.range_warnings)})

        # eclipse boundaries of the earth run against the closed-form cylindrical shadow
        archive = data["earth"]["archive"]
        windows = orbit.eclipse_windows(0.0, data["earth"]["t_end"])
        expected = sorted([(entry, "sunlit_to_umbra") for entry, _ in windows if 0.0 < entry < data["earth"]["t_end"]]
                          + [(exit_, "umbra_to_sunlit") for _, exit_ in windows if 0.0 < exit_ < data["earth"]["t_end"]])
        located = [(boundary.time_s, boundary.kind) for boundary in archive.eclipse_boundaries]
        kinds_ok = [kind for _, kind in located] == [kind for _, kind in expected]
        errors = [abs(a - b) for (a, _), (b, _) in zip(located, expected)] if kinds_ok else [math.inf]
        max_err = _worst(errors) if errors else 0.0
        t_old = np.asarray(archive.steps["t_old_s"])
        t_new = np.asarray(archive.steps["t_new_s"])
        straddle = []
        for boundary in archive.eclipse_boundaries:
            for moment in (boundary.time_left_s, boundary.time_right_s):
                straddle += np.flatnonzero((t_old < moment) & (t_new > moment)).tolist()
        segments = list(archive.segments)
        segment_ok = (len(segments) == len(located) + 1 and all(segment["integrated"] for segment in segments)
                      and all(any(reason.startswith("eclipse:") for reason in segment["start_reasons"])
                              for segment in segments[1:]))
        shadow_text = ("无地影，模块未找到边界" if not expected else
                       f"解析进出时刻 {[round(b, 4) for b, _ in expected]} s，模块 {[round(a, 4) for a, _ in located]} s")
        problems = [] if kinds_ok else [f"模块定位的边界 {len(located)} 个，解析地影给出 {len(expected)} 个，类型或个数不符"]
        problems += [] if _within(max_err, CRIT["eclipse_time_tol_s"]) or not kinds_ok else [
            f"日食进出时刻与解析值之差最大 {sup.sci(max_err)} s，超过 {sup.sci(CRIT['eclipse_time_tol_s'])} s"]
        problems += [f"{len(straddle)} 个积分步跨越边界"] if straddle else []
        problems += [] if segment_ok else [f"积分段 {len(segments)} 个，个数或起点原因与边界不符"]
        results.append(_check(
            case_record, n_segments(case),
            f"日食进出时刻与圆柱地影解析值之差不超过 {CRIT['eclipse_time_tol_s']:g} s，没有积分步跨越边界，每个边界后"
            "开始新的积分段",
            f"{shadow_text}，最大差 {max_err:.2e} s；跨越边界的积分步 {len(straddle)} 个；积分段 {len(segments)} 个，"
            f"段起点原因 {[segment['start_reasons'] for segment in segments]}",
            kinds_ok and _within(max_err, CRIT["eclipse_time_tol_s"]) and not straddle and segment_ok,
            "，".join(problems)))
        last_windows = [w for w in windows if w[1] > data["fe_end"] - orbit.period_s and w[0] < data["fe_end"]]
        outcome.update({
            "eclipse_err_s": max_err if expected else 0.0, "n_boundaries": len(located), "straddle": len(straddle),
            "segments": len(segments), "repetition_K": data["earth"]["repetition_K"],
            "repetition_no_earth_K": data["no_earth"]["repetition_K"], "t_end": data["earth"]["t_end"],
            "attempts": len(data["attempts"])})
        _metric(case_record, f"{case}_eclipse", {
            "closed_form_boundaries_s": [b for b, _ in expected], "module_boundaries_s": [a for a, _ in located],
            "max_error_s": max_err if expected else 0.0, "straddling_steps": len(straddle),
            "fe_event_times_s": data["series"]["event_times_s"],
            "closed_form_windows_last_orbit_s": [list(w) for w in last_windows],
            "fe_eclipse_deg": orbit.eclipse_deg})
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 3


def _boundary_marks(orbit, t0: float, t1: float) -> list[tuple[float, str]]:
    marks = []
    for entry, exit_ in orbit.eclipse_windows(t0, t1):
        marks += [(entry, "entry"), (exit_, "exit")]
    return sorted(marks)


def _exceedance_groups(fe_t: np.ndarray, raw: np.ndarray, marks: list, limit: float) -> list[dict]:
    """FE instants with a same-instant difference above ``limit``, grouped by consecutive FE samples after the same
    eclipse boundary (kind ``None`` when no boundary precedes the instant)."""

    groups: list[dict] = []
    for i in np.flatnonzero(np.abs(raw) > limit):  # a NaN difference is reported separately
        moment = float(fe_t[i])
        before = [index for index, (b, _) in enumerate(marks) if b <= moment]
        mark = before[-1] if before else None
        since = moment - marks[mark][0] if mark is not None else math.nan
        sign = 1 if raw[i] > 0 else -1
        if groups and groups[-1]["mark"] == mark and groups[-1]["last"] == i - 1:
            group = groups[-1]
            group.update(last=int(i), count=group["count"] + 1, to_s=since, max_K=max(group["max_K"], abs(raw[i])))
            group["signs"].add(sign)
        else:
            groups.append({"mark": mark, "kind": marks[mark][1] if mark is not None else None, "first": int(i),
                           "last": int(i), "count": 1, "from_s": since, "to_s": since, "signs": {sign},
                           "max_K": float(abs(raw[i]))})
    for group in groups:
        group["signs"] = sorted(group["signs"])
    return groups


def _group_cn(group: dict) -> str:
    where = {"entry": "进入日食后", "exit": "离开日食后"}.get(group["kind"])
    if where is None:
        span = f"全程受晒时的 {group['count']} 个输出时刻"
    elif group["count"] == 1:
        span = f"{where} {group['from_s']:.0f} s 的 1 个输出时刻"
    else:
        span = f"{where} {group['from_s']:.0f} s 至 {group['to_s']:.0f} s 的 {group['count']} 个输出时刻"
    side = {(-1,): "集总模型低于有限元", (1,): "集总模型高于有限元"}.get(tuple(group["signs"]), "集总模型与有限元高低交替")
    return f"{span}，{side}"


def test_step3_compare_with_fe_third_orbit(fe001, case_record):
    """Step 3 and acceptance: minimum, mean and maximum of the last orbit against the FE third orbit; the expected
    result that the curves coincide, judged at every FE output instant."""

    results = []
    spread_low, spread_high = CFG["fe"]["spread_columns"]
    for case in CASES:
        data = fe001["cases"][case]
        orbit = data["orbit"]
        period = orbit.period_s
        run = data["earth"]
        archive = run["archive"]
        shift = data["shift_s"]
        dense = _dense(run, period)
        module = dense["stats"]
        series = data["series"]
        fe = sup.sampled_period_stats(series["t_s"], series["value"], data["fe_end"], period)
        diffs = {key: module[key] - fe[key] for key in STATS}
        for key in STATS:
            results.append(_check(
                case_record, n_accept(case, key),
                f"不超过 {ACCEPT_K:g} K",
                f"{abs(diffs[key]):.2f} K：集总模型 {sup.num(module[key])} °C，有限元太阳翼平均温度 "
                f"{sup.num(fe[key])} °C，统计区间 {run['t_end'] - period:.2f} 至 {run['t_end']:.2f} s 与有限元 "
                f"{fe['t0_s']:.2f} 至 {fe['t1_s']:.2f} s，按时间加权",
                _within(abs(diffs[key]), ACCEPT_K),
                (f"集总模型 {sup.num(module[key])} °C，有限元 {sup.num(fe[key])} °C，差 {sup.num(abs(diffs[key]))} K，超过 "
                 f"{sup.gen(ACCEPT_K)} K" if math.isfinite(diffs[key])
                 else f"运行没有到达结束时刻，未得到最后一圈的{STAT_CN[key]}温度")))

        # curves: every FE output instant of the third orbit against the module solution at the same instant
        inside = (series["t_s"] > fe["t0_s"]) & (series["t_s"] <= data["fe_end"])
        fe_t, fe_v = series["t_s"][inside], series["value"][inside]
        spread = (series["extra"][spread_high] - series["extra"][spread_low])[inside]
        if _completed(run):
            at_fe = archive.state_at(fe_t + shift)[:, I_S] - 273.15
        else:
            at_fe = np.full(fe_t.shape, np.nan)
        raw = at_fe - fe_v
        worst = _worst(np.abs(raw))
        rms = float(np.sqrt(np.mean(raw**2))) if raw.size else math.nan
        marks = _boundary_marks(orbit, fe["t0_s"] - period, data["fe_end"])
        groups = _exceedance_groups(fe_t, raw, marks, ACCEPT_K)
        over = np.array([i for group in groups for i in range(group["first"], group["last"] + 1)], dtype=int)
        spread_over = _worst(spread[over]) if over.size else math.nan
        spread_all = _worst(spread)
        if math.isfinite(worst):
            i_worst = int(np.argmax(np.abs(raw)))
            before = [(b, kind) for b, kind in marks if b <= fe_t[i_worst]]
            worst_kind = before[-1][1] if before else None
            worst_since = float(fe_t[i_worst] - before[-1][0]) if before else math.nan
            where_cn = ({"entry": f"进入日食后 {worst_since:.0f} s", "exit": f"离开日食后 {worst_since:.0f} s"}
                        .get(worst_kind, f"全程受晒工况的 {fe_t[i_worst]:.1f} s"))
            worst_time = float(fe_t[i_worst])
        else:
            worst_kind, worst_since, worst_time, where_cn = None, math.nan, math.nan, "未得到"
        passed = _within(worst, ACCEPT_K)
        spans = "；".join(_group_cn(group) for group in groups)
        if passed:
            anomaly = ""
        elif not math.isfinite(worst):
            anomaly = "运行没有到达结束时刻或有限元数据缺失，未得到同一时刻的逐点差"
        else:
            anomaly = (f"有限元第三圈 {fe_t.size} 个输出时刻中，集总模型同一时刻的温度与有限元之差最大 {sup.num(worst)} K，"
                       f"出现在{where_cn}；超过 {sup.gen(ACCEPT_K)} K 的是{spans}；逐点差均方根 {sup.num(rms)} K；这些时刻"
                       f"有限元太阳翼最高与最低温度之差不超过 {sup.num(spread_over)} K")
            OUTCOME["curve_context"] = True
        results.append(_check(
            case_record, n_curve(case),
            f"有限元第三圈每个输出时刻的太阳翼平均温度与集总模型同一时刻的温度之差不超过 {ACCEPT_K:g} K，逐点比较，不加时间窗",
            f"{fe_t.size} 个输出时刻逐点差最大 {worst:.2f} K，出现在 {worst_time:.1f} s，{where_cn}；超过 {ACCEPT_K:g} K "
            f"的时刻 {spans or '无'}；逐点差均方根 {rms:.2f} K；有限元太阳翼最高与最低温度之差在第三圈最大 "
            f"{spread_all:.2f} K，在超过 {ACCEPT_K:g} K 的时刻最大 {spread_over:.2f} K",
            passed, anomaly))
        OUTCOME["cases"].setdefault(case, {}).update({
            "module": module, "fe": {k: fe[k] for k in STATS}, "diffs": diffs,
            "curve": {"samples": int(fe_t.size), "max_K": worst, "max_time_s": worst_time, "max_kind": worst_kind,
                      "max_since_s": worst_since, "rms_K": rms, "groups": groups, "spread_over_K": spread_over,
                      "spread_all_K": spread_all, "passed": passed, "eclipse": bool(marks)},
            "fe_window": (fe["t0_s"], fe["t1_s"])})
        _metric(case_record, f"{case}_comparison", {
            "module_last_orbit_C": {k: module[k] for k in STATS},
            "module_argmin_s": module["argmin_s"], "module_argmax_s": module["argmax_s"],
            "fe_third_orbit_C": {k: fe[k] for k in STATS},
            "module_minus_fe_K": diffs, "max_abs_diff_K": _worst([abs(v) for v in diffs.values()]),
            "pointwise_max_abs_K": worst, "pointwise_max_time_s": worst_time,
            "pointwise_max_after": worst_kind, "pointwise_max_since_boundary_s": worst_since,
            "pointwise_rms_K": rms,
            "pointwise_over_limit": [{key: group[key] for key in ("kind", "from_s", "to_s", "count", "signs", "max_K")}
                                     for group in groups],
            "fe_spread_max_K": spread_all, "fe_spread_at_over_limit_K": spread_over,
            "fe_time_s": fe_t, "module_minus_fe_pointwise_K": raw,
            "fe_samples": int(fe_t.size), "statistics_grid_points": int(dense["grid"].size)})
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 4


def test_step4_albedo_and_infrared_off(fe001, case_record):
    """Step 4: rerun without albedo and infrared, the 9.4 record of the simplification and the temperature change."""

    results = []
    area = fe001["area_m2"]
    for case in CASES:
        data = fe001["cases"][case]
        env = CFG["cases"][case]
        period = data["orbit"].period_s
        run, base = data["no_earth"], data["earth"]
        archive = run["archive"]
        provenance = archive.provenance
        earth_record = provenance["environment"]["earth_flux"]
        note = f"Earth albedo and infrared switched off: {NO_EARTH_REASON}"
        sample = run["provider"].sample(float(archive.time_s[len(archive.time_s) // 2]))
        zero_flux = (not np.any(np.asarray(sample.earth_flux["albedo_W_m2"]))
                     and not np.any(np.asarray(sample.earth_flux["infrared_W_m2"])))
        items = {"归档说明含关闭原因": note in archive.notes,
                 "环境记录的关闭原因一致": earth_record.get("disabled_reason") == NO_EARTH_REASON,
                 "环境记录不含反照率": earth_record.get("albedo") is None,
                 "调用方记录标明关闭": str(provenance["caller"]["earth_flux"]).startswith("off"),
                 "样点反照与红外全为零": zero_flux}
        recorded = all(items.values())
        results.append(_check(
            case_record, n_recorded(case),
            "运行归档的说明与环境来源记录关闭原因，earth_flux 的反照与红外为零，未把缺失值当作完整环境",
            f"归档说明含关闭原因 {items['归档说明含关闭原因']}，环境记录 disabled_reason 一致 "
            f"{items['环境记录的关闭原因一致']}，调用方记录 {provenance['caller']['earth_flux'][:3]}，"
            f"样点反照与红外全为零 {zero_flux}", recorded,
            "不满足的记录项为" + "、".join(key for key, value in items.items() if not value)))

        # Q_env,S of the run without Earth flux holds only the direct term A alpha_front G
        Q_env = np.asarray(archive.Q_env_W)[:, 0]
        G = np.asarray(archive.environment["G_W_m2"])
        direct = area * SA["front"]["absorptivity"] * G
        scale = np.maximum(np.abs(direct), 1.0)
        rel = float(np.max(np.abs(Q_env - direct) / scale))
        results.append(_check(
            case_record, n_direct(case),
            f"每个输出样点 Q_env,S 等于正面面积乘吸收率 0.72 乘 G，相对差不超过 {CRIT['relative_tol_exact']:g}，地影内为零",
            f"{Q_env.size} 个样点最大相对差 {rel:.2e}，地影内样点 Q_env,S 最大 "
            f"{float(np.max(np.abs(Q_env[G == 0.0]))) if np.any(G == 0.0) else 0.0:.3g} W",
            _within(rel, CRIT["relative_tol_exact"]),
            f"Q_env,S 与正面直射吸收的相对差最大 {sup.sci(rel)}，超过 {sup.sci(CRIT['relative_tol_exact'])}"))

        # without albedo and infrared the node obeys c dT/dt = (alpha_f - 0.073) G - (eps_f + eps_b) sigma T^4,
        # whose piecewise closed-form solution from 290 K at orbit noon is the reference of the whole history
        orbit = data["orbit"]
        absorbed = (SA["front"]["absorptivity"] - SA["pv_fraction"]) * env["solar_constant_W_m2"]
        b = (SA["front"]["emissivity"] + SA["back"]["emissivity"]) * sup.SIGMA_W_M2_K4
        out_t = np.asarray(archive.time_s)
        T_ref = sup.radiative_plate_reference(out_t, 0.0, SA["initial_temperature_K"],
                                              orbit.eclipse_windows(0.0, run["t_end"]), absorbed, b,
                                              SA["areal_heat_capacity_J_m2K"])
        T_mod = np.asarray(archive.temperature_K)[:, I_S]
        analytic_err = float(np.max(np.abs(T_mod - T_ref)))
        T_eq = (absorbed / b) ** 0.25
        done = _completed(run)
        results.append(_check(
            case_record, n_analytic(case),
            f"受晒段按 c dT/dt 等于正面吸收率 0.72 减 0.073 后乘 G，再减两面发射率之和乘 σT⁴ 的解析解，日食段按纯辐射冷却"
            f"解析解，c 为面热容，自正午 "
            f"{SA['initial_temperature_K']:g} K 起逐段递推，运行到达结束时刻，全部输出样点温差不超过 {CRIT['analytic_K']:g} K",
            f"{out_t.size} 个输出样点最大温差 {analytic_err:.2e} K，运行到达结束时刻 {done}；受晒平衡温度 "
            f"{sup.num(T_eq - 273.15)} °C，解析解最低 {sup.num(float(np.min(T_ref)) - 273.15)} °C，最高 "
            f"{sup.num(float(np.max(T_ref)) - 273.15)} °C",
            done and _within(analytic_err, CRIT["analytic_K"]),
            (f"温度时程与分段解析解之差最大 {sup.sci(analytic_err)} K，超过 {sup.gen(CRIT['analytic_K'])} K" if done
             else "运行没有到达结束时刻，温度时程不完整")))

        stats_off = _dense(run, period)["stats"]
        stats_on = _dense(base, period)["stats"]
        lower = {key: stats_on[key] - stats_off[key] for key in STATS}
        clearly = all(_within(CRIT["clearly_lower_K"], value) and value > CRIT["clearly_lower_K"]
                      for value in lower.values())
        results.append(_check(
            case_record, n_lower(case),
            f"最后一圈最低、平均与最高温度都比开启时低，且降幅都大于验收差值 {CRIT['clearly_lower_K']:g} K",
            f"开启 {_fmt_stats(stats_on)}，关闭 {_fmt_stats(stats_off)}，最低低 {lower['min']:.2f} K，平均低 "
            f"{lower['mean']:.2f} K，最高低 {lower['max']:.2f} K",
            clearly,
            f"关闭后最低、平均与最高温度分别低 {sup.num(lower['min'])}、{sup.num(lower['mean'])} 与 {sup.num(lower['max'])} K，"
            f"未全部大于 {sup.gen(CRIT['clearly_lower_K'])} K"))
        OUTCOME["cases"].setdefault(case, {}).update({"no_earth": stats_off, "lower": lower,
                                                      "analytic_err_K": analytic_err, "direct_rel": rel})
        _metric(case_record, f"{case}_no_earth", {
            "module_last_orbit_C": {k: stats_off[k] for k in STATS},
            "with_minus_without_K": lower, "simplification_recorded": recorded, "Q_env_direct_only_rel": rel,
            "analytic_max_abs_K": analytic_err, "sunlit_equilibrium_C": T_eq - 273.15})
    assert all(results)


# ------------------------------------------------------------------------------------------------ T3 and T4 terms


def _probe(state, run_id: str, t: float, environment, params, P_pv: float):
    """thermal_derivative with the given P_pv and the other three ports zero; returns (evaluation, error)."""

    try:
        inputs = ThermalInputs(run_id, t, environment, P_pv, 0.0, 0.0, 0.0)
        return thermal_derivative(state, inputs, params), None
    except Exception as exc:  # noqa: BLE001  (the error type and text are judged by the caller)
        return None, exc


def test_solar_array_terms_t3_t4(fe001, case_record):
    """Goal: environmental absorption, deduction of the actual electrical output and two-sided emission of S."""

    params = fe001["params"]
    area = fe001["area_m2"]
    c_hand = SA["areal_heat_capacity_J_m2K"] * area
    eps_sum = SA["front"]["emissivity"] + SA["back"]["emissivity"]
    alpha = np.array([SA["front"]["absorptivity"], SA["back"]["absorptivity"]])
    eps = np.array([SA["front"]["emissivity"], SA["back"]["emissivity"]])
    normals_body = np.array([SA["front"]["normal_body"], SA["back"]["normal_body"]], dtype=float)
    tol = CRIT["relative_tol_exact"]
    results = []
    q_sr_cases = []
    for case in CASES:
        data = fe001["cases"][case]
        orbit = data["orbit"]
        run = data["earth"]
        archive, provider, run_id = run["archive"], run["provider"], run["run_id"]
        ref = _reference_flux(data)
        idx = ref["indices"]
        times = np.asarray(archive.time_s)
        temperatures = np.asarray(archive.temperature_K)
        T_S = temperatures[:, I_S]
        Q_env = np.asarray(archive.Q_env_W)[:, 0]
        Q_emit = np.asarray(archive.Q_emit_W)[:, 0]
        P_pv = np.asarray(archive.ports_W["P_pv_W"])
        q_SR = np.asarray(archive.q_W)[:, I_SR]
        dTdt = np.asarray(archive.dT_dt_K_s)[:, I_S]
        G = np.asarray(archive.environment["G_W_m2"])
        valid = np.asarray(archive.sample_valid)
        invalid = int(np.count_nonzero(~valid))

        # T4 emission of both faces at every output sample
        emit_hand = eps_sum * sup.SIGMA_W_M2_K4 * area * T_S**4
        emit_rel = float(np.max(np.abs(Q_emit - emit_hand) / emit_hand))
        results.append(_check(
            case_record, n_emit(case),
            f"Q_emit,S 等于 0.82 与 0.85 之和乘 σ、面积与 T_S 四次方，相对差不超过 {tol:g}，全部输出样点有效",
            f"{T_S.size} 个输出样点最大相对差 {emit_rel:.2e}，无效样点 {invalid} 个，Q_emit,S {np.nanmin(Q_emit) / 1e6:.4f} 至 "
            f"{np.nanmax(Q_emit) / 1e6:.4f} MW", _within(emit_rel, tol) and invalid == 0,
            f"Q_emit,S 与两面发射率手算的相对差最大 {sup.sci(emit_rel)}，限值 {sup.sci(tol)}，无效输出样点 {invalid} 个"))

        # T4 absorption against the independent Earth flux and closed-form direct term at the check instants
        g_sun = G[idx][:, None] * np.clip(ref["cos"], 0.0, None)
        env_hand = area * np.sum(alpha[None, :] * (g_sun + ref["albedo"]) + eps[None, :] * ref["infrared"], axis=1)
        env_rel = float(np.max(np.abs(Q_env[idx] - env_hand) / env_hand))
        results.append(_check(
            case_record, n_env(case),
            f"Q_env,S 等于两面面积乘吸收率乘直射与反照之和，加发射率乘地球红外；反照与红外取独立积分，相对差不超过 "
            f"{CRIT['relative_tol_env']:g}",
            f"{idx.size} 个校核时刻最大相对差 {env_rel:.2e}，Q_env,S {Q_env[idx].min() / 1e6:.4f} 至 "
            f"{Q_env[idx].max() / 1e6:.4f} MW", _within(env_rel, CRIT["relative_tol_env"]),
            f"Q_env,S 与按独立积分手算的相对差最大 {sup.sci(env_rel)}，超过 {sup.sci(CRIT['relative_tol_env'])}"))

        # actual electrical output: the module's absorbed_solar_S_W, its limit in thermal_derivative and the deduction
        absorbed_mod = np.full(times.size, np.nan)
        absorbed_hand = np.full(times.size, np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("error", ThermalRangeWarning)  # a range warning would fail the sample, not pass
            for k, moment in enumerate(times):
                t = float(moment)
                cosines = orbit.rotation(t).apply(normals_body) @ orbit.sun_direction(t)
                absorbed_hand[k] = area * G[k] * float(alpha @ np.clip(cosines, 0.0, None))
                try:
                    state = ThermalState(run_id, t, temperatures[k])
                    environment = provider.sample(t).surface_environment
                    absorbed_mod[k] = calculate_surface_heat(state, environment, params)["absorbed_solar_S_W"]
                except Exception:  # noqa: BLE001  (left NaN, so the check fails)
                    pass
        absorbed_rel = _worst(np.abs(absorbed_mod - absorbed_hand) / np.maximum(absorbed_hand, 1.0))
        excess = _worst(P_pv - absorbed_mod)
        lit = absorbed_mod > 0.0
        ratio = _worst(P_pv[lit] / absorbed_mod[lit]) if np.any(lit) else math.nan
        sunlit_probes = accepted_equal = rejected_over = eclipse_probes = rejected_eclipse = 0
        other_errors, deduction_rel, other_change = [], [], []
        for k in idx:
            t = float(times[k])
            state = ThermalState(run_id, t, temperatures[k])
            environment = provider.sample(t).surface_environment
            limit = calculate_surface_heat(state, environment, params)["absorbed_solar_S_W"]
            if limit > 0.0:
                sunlit_probes += 1
                evaluation, error = _probe(state, run_id, t, environment, params, limit)
                accepted_equal += int(evaluation is not None)
                probe = limit * (1.0 + CRIT["pv_over_limit_relative"])
            else:
                eclipse_probes += 1
                probe = float(CRIT["pv_eclipse_probe_W"])
            evaluation, error = _probe(state, run_id, t, environment, params, probe)
            named = (error is not None and type(error).__name__ == "ThermalInputError" and "P_pv_W" in str(error)
                     and "absorbed_solar_S_W" in str(error))
            if named:
                rejected_over += int(limit > 0.0)
                rejected_eclipse += int(limit <= 0.0)
            elif error is not None:
                other_errors.append(type(error).__name__)
            if limit > 0.0 and P_pv[k] > 0.0:
                given, _ = _probe(state, run_id, t, environment, params, float(P_pv[k]))
                zero, _ = _probe(state, run_id, t, environment, params, 0.0)
                if given is None or zero is None:
                    deduction_rel.append(math.nan)
                    other_change.append(math.nan)
                    continue
                change = np.asarray(zero.dT_dt_K_s) - np.asarray(given.dT_dt_K_s)
                deduction_rel.append(abs(change[I_S] * c_hand - P_pv[k]) / P_pv[k])
                other_change.append(float(np.max(np.abs(np.delete(change, I_S)))))
        deduction_max, other_max = _worst(deduction_rel), _worst(other_change)
        pv_ok = (_within(absorbed_rel, tol) and _within(excess, 0.0) and sunlit_probes > 0
                 and accepted_equal == sunlit_probes and rejected_over == sunlit_probes
                 and rejected_eclipse == eclipse_probes and not other_errors
                 and _within(deduction_max, tol) and _within(other_max, 0.0))
        problems = []
        if not _within(absorbed_rel, tol):
            problems.append(f"absorbed_solar_S_W 与手算直射吸收的相对差最大 {sup.sci(absorbed_rel)}，超过 {sup.sci(tol)}")
        if not _within(excess, 0.0):
            problems.append(f"给定的 P_pv 超出 absorbed_solar_S_W 最多 {sup.gen(excess)} W")
        if accepted_equal != sunlit_probes:
            problems.append(f"{sunlit_probes} 个受晒校核时刻中 P_pv 等于 absorbed_solar_S_W 时被接受 {accepted_equal} 次")
        if rejected_over != sunlit_probes or rejected_eclipse != eclipse_probes or other_errors:
            problems.append(f"P_pv 超出 absorbed_solar_S_W 时报出超限的次数为受晒 {rejected_over} 次，日食 {rejected_eclipse} 次，"
                            f"应为 {sunlit_probes} 次与 {eclipse_probes} 次"
                            + (f"，另有 {'、'.join(sorted(set(other_errors)))} 异常" if other_errors else ""))
        if not (_within(deduction_max, tol) and _within(other_max, 0.0)):
            problems.append(f"P_pv 由零增至给定值时 dT_S/dt 减少量乘 C_S 与 P_pv 的相对差最大 {sup.sci(deduction_max)}，其余"
                            f"节点导数变化最大 {sup.sci(other_max)} K/s")
        results.append(_check(
            case_record, n_pv(case),
            f"calculate_surface_heat 给出的 absorbed_solar_S_W 等于正面面积乘 0.72 乘 G 乘非负入射余弦与背面对应项之和，相对"
            f"差不超过 {tol:g}；给定的 P_pv 在全部输出样点不超过 absorbed_solar_S_W；thermal_derivative 在 P_pv 等于 "
            f"absorbed_solar_S_W 时接受，超出 {CRIT['pv_over_limit_relative']:g} 相对量或在日食中取 "
            f"{CRIT['pv_eclipse_probe_W']:g} W 时报出 P_pv_W 超过 absorbed_solar_S_W；P_pv 由零增至给定值时 dT_S/dt 的减少量"
            f"乘 C_S 等于 P_pv，相对差不超过 {tol:g}，其余节点导数不变",
            f"{times.size} 个输出样点 absorbed_solar_S_W 与手算最大相对差 {absorbed_rel:.2e}，P_pv 减 absorbed_solar_S_W 最大 "
            f"{excess:.3g} W，受晒时两者之比最大 {ratio:.5f}，P_pv 最大 {np.nanmax(P_pv) / 1e3:.2f} kW；{sunlit_probes} 个受晒"
            f"校核时刻等于上限时接受 {accepted_equal} 次，超出时报错 {rejected_over} 次；{eclipse_probes} 个日食校核时刻报错 "
            f"{rejected_eclipse} 次；其他异常 {sorted(set(other_errors))}；{len(deduction_rel)} 个受晒时刻扣除量相对差最大 "
            f"{deduction_max:.2e}，其余节点导数变化最大 {other_max:.3g} K/s",
            pv_ok, "；".join(problems)))

        # T3 first line at every output sample, with the hand T5 capacitance
        rhs = Q_env - P_pv - q_SR - Q_emit
        gross = np.abs(Q_env) + np.abs(P_pv) + np.abs(q_SR) + np.abs(Q_emit)
        t3_rel = float(np.max(np.abs(c_hand * dTdt - rhs) / gross))
        results.append(_check(
            case_record, n_t3(case),
            f"C_S 乘 dT_S/dt 等于 Q_env,S 减 P_pv 减 q_SR 减 Q_emit,S，C_S 取手算 1.6 kJ·m⁻²·K⁻¹ 乘面积，残差与各项绝对值之和"
            f"之比不超过 {tol:g}",
            f"{T_S.size} 个输出样点最大比值 {t3_rel:.2e}", _within(t3_rel, tol),
            f"T3 第一行残差与各项绝对值之和之比最大 {sup.sci(t3_rel)}，超过 {sup.sci(tol)}"))
        q_sr_case = _worst(np.abs(np.concatenate([q_SR, np.asarray(data["no_earth"]["archive"].q_W)[:, I_SR]])))
        q_sr_cases.append(q_sr_case)
        OUTCOME["cases"].setdefault(case, {}).update({
            "env_rel": env_rel, "emit_rel": emit_rel, "t3_rel": t3_rel, "q_SR_max_W": q_sr_case,
            "P_pv_max_kW": float(np.nanmax(P_pv) / 1e3) if np.any(np.isfinite(P_pv)) else math.nan,
            "pv": {"absorbed_rel": absorbed_rel, "excess_W": excess, "ratio": ratio, "sunlit_probes": sunlit_probes,
                   "accepted_equal": accepted_equal, "rejected_over": rejected_over, "eclipse_probes": eclipse_probes,
                   "rejected_eclipse": rejected_eclipse, "deduction_rel": deduction_max, "other_change": other_max,
                   "deduction_instants": len(deduction_rel)}})
        _metric(case_record, f"{case}_terms", {
            "check_instants": int(idx.size), "Q_env_rel_max": env_rel, "Q_emit_rel_max": emit_rel,
            "absorbed_solar_S_W_rel_max": absorbed_rel, "P_pv_minus_absorbed_max_W": excess,
            "P_pv_over_absorbed_solar_max": ratio, "limit_sunlit_probes": sunlit_probes,
            "limit_accepted_at_equal": accepted_equal, "limit_rejected_above": rejected_over,
            "limit_eclipse_probes": eclipse_probes, "limit_rejected_in_eclipse": rejected_eclipse,
            "limit_other_errors": sorted(set(other_errors)), "deduction_rel_max": deduction_max,
            "deduction_other_nodes_max_K_s": other_max, "T3_row1_rel_max": t3_rel,
            "q_SR_max_abs_W": q_sr_case, "invalid_output_samples": invalid,
            "Q_env_S_range_MW": [float(np.nanmin(Q_env) / 1e6), float(np.nanmax(Q_env) / 1e6)]})
    q_sr_max = _worst(q_sr_cases)
    OUTCOME["q_SR_max_W"] = q_sr_max
    results.append(_check(
        case_record, N_QSR,
        f"两次运行全部输出样点 |q_SR| 不超过 {CRIT['q_SR_max_W']:g} W",
        f"|q_SR| 最大 {q_sr_max:.3e} W", _within(q_sr_max, CRIT["q_SR_max_W"]),
        f"q_SR 的绝对值最大 {sup.sci(q_sr_max)} W，超过 {sup.sci(CRIT['q_SR_max_W'])} W"))
    assert all(results)


# ------------------------------------------------------------------------------------------------ evidence and summary


def _run_record(run: dict) -> dict:
    archive = run["archive"]
    plain = archive.as_dict()
    keep = ("format", "run_id", "epoch_utc", "status", "error", "t_start_s", "t_end_s", "node_order", "path_order",
            "exposed_node_order", "port_order", "instance_map", "eclipse_boundaries", "segments", "solver_settings",
            "statistics", "range_warnings", "notes", "final_state", "provenance")
    record = {key: plain[key] for key in keep}
    record["initial_state_K"] = dict(zip(NODE_ORDER, (float(v) for v in archive.accepted["state"][0][:6])))
    record["last_accepted_s"] = _last_accepted_s(archive)
    record["repetition_K"] = run["repetition_K"]
    record["wall_s"] = run["wall_s"]
    return record


def _write_evidence(fe001: dict) -> dict:
    """Time histories for the report figures and the 9.4 run records. Module values are taken only up to the last
    accepted state of each run, never from the held state beyond a stop."""

    RESULTS_DIR.mkdir(exist_ok=True)
    series_out = {
        "case_id": "FE-001",
        "description": "Solar array node S of the thermal module, last orbit, against the ISS FE solar array mean "
                       "temperature saw_Tmean_C of the third orbit. Module times are mapped onto the FE time axis "
                       "(time from orbit noon of the FE run); eclipse windows are the closed-form cylindrical shadow. "
                       "Module values exist only up to the last accepted state of a run.",
        "period_s": None, "cases": {}}
    runs_out = {"case_id": "FE-001", "record": "thermal design 9.4: resolved parameters, provenance, initial state, "
                "environment configuration, solver settings and statistics of every run", "runs": []}
    for case in CASES:
        data = fe001["cases"][case]
        orbit = data["orbit"]
        period = orbit.period_s
        series_out["period_s"] = period
        shift = data["shift_s"]
        earth, no_earth = data["earth"], data["no_earth"]
        archive = earth["archive"]
        t_end = earth["t_end"]
        t0 = t_end - period
        last_on = _last_accepted_s(archive)
        last_off = _last_accepted_s(no_earth["archive"])
        out_t = np.asarray(archive.time_s)
        sel = (out_t >= t0) & (out_t <= t_end)
        times = np.unique(np.concatenate([[t0], out_t[sel]]))
        times = times[times <= last_on]
        states_on = archive.state_at(times)[:, I_S] - 273.15 if times.size else np.array([])
        states_off = np.array([no_earth["archive"].state_at(float(moment))[I_S] - 273.15 if moment <= last_off
                               else math.nan for moment in times])
        fe = sup.sampled_period_stats(data["series"]["t_s"], data["series"]["value"], data["fe_end"], period)
        windows = [w for w in orbit.eclipse_windows(t0 - shift, t_end - shift)]
        result = OUTCOME["cases"].get(case, {})
        series_out["cases"][case] = {
            "label_cn": CFG["cases"][case]["label_cn"],
            "environment": CFG["cases"][case],
            "last_orbit_start_s": t0 - shift, "last_orbit_end_s": t_end - shift,
            "module_status": archive.status, "module_last_accepted_s": last_on - shift,
            "module_time_s": times - shift,
            "module_T_S_C": states_on,
            "module_no_albedo_infrared_T_S_C": states_off,
            "module_output_time_s": out_t[sel] - shift,
            "module_P_pv_W": np.asarray(archive.ports_W["P_pv_W"])[sel],
            "module_Q_env_S_W": np.asarray(archive.Q_env_W)[sel, 0],
            "module_Q_emit_S_W": np.asarray(archive.Q_emit_W)[sel, 0],
            "module_G_W_m2": np.asarray(archive.environment["G_W_m2"])[sel],
            "fe_time_s": fe["t_s"],
            "fe_T_saw_mean_C": fe["value"],
            "eclipse_windows_s": [list(w) for w in windows],
            "module_eclipse_boundaries_s": [b.time_s - shift for b in archive.eclipse_boundaries
                                            if t0 <= b.time_s <= t_end],
            "stats_C": {"module": {k: result.get("module", {}).get(k) for k in STATS},
                        "fe": result.get("fe"),
                        "module_no_albedo_infrared": {k: result.get("no_earth", {}).get(k) for k in STATS}},
            "module_minus_fe_K": result.get("diffs"),
            "pointwise": {key: result.get("curve", {}).get(key) for key in ("max_K", "max_time_s", "rms_K", "passed")},
        }
        for run in data["attempts"] + [no_earth]:
            runs_out["runs"].append(_run_record(run))
    (RESULTS_DIR / "FE-001_series.json").write_text(
        json.dumps(_plain_json(series_out), ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    (RESULTS_DIR / "FE-001_runs.json").write_text(
        json.dumps(_plain_json(runs_out), ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    return {"series": str(RESULTS_DIR / "FE-001_series.json"), "runs": str(RESULTS_DIR / "FE-001_runs.json")}


def _summary_text(fe001: dict | None, checks: list[dict]) -> str:
    """Chinese summary from the recorded checks and values: a claim is written only when its check passed, otherwise
    the sentence states that the check did not pass or was not executed."""

    if fe001 is None:
        return "本用例的三个工况未能完成模型装配或联合计算，未得到与有限元的对比结果。"
    status = {check["name"]: check["passed"] for check in checks}

    def passed(*names: str) -> bool:
        return all(status.get(name) is True for name in names)

    def executed(*names: str) -> bool:
        return all(name in status for name in names)

    def labels(cases) -> str:
        return "、".join(_label(case) for case in cases)

    m = {case: OUTCOME["cases"].get(case, {}) for case in CASES}
    inputs = OUTCOME.get("inputs", {})
    parts = []

    # what was run
    attempts = sum(len(fe001["cases"][case]["attempts"]) for case in CASES)
    parts.append(
        "本用例对设计冷工况、平均环境工况与设计热工况各运行两次热模块积分，第一次按工况计入地球反照与地球红外，第二次关闭"
        "这两项。sdtwin_sim.coupled 在每次试算中调用 prepare_surface_environment 与 thermal_derivative，earth_flux 由 "
        "sdtwin_sim.earth_flux 按工况的反照率与地球红外生成"
        + (f"；为达到逐圈重复，计入反照与红外的运行共试算 {attempts} 个积分时长。" if attempts > len(CASES) else "。"))

    # inputs
    text = f"太阳能板取有限元 {inputs.get('blankets', sup.MISSING_CN)} 块美国太阳翼毯面，正面面积 {sup.num(fe001['area_m2'], 1)} m^{{2}}"
    optics = inputs.get("optics", {})
    if passed(N_OPTICS, N_AREAL, N_SURF, N_T5) and "front" in optics and "back" in optics:
        text += (f"，正面吸收率 {sup.gen(optics['front'][0])}、发射率 {sup.gen(optics['front'][1])}，背面吸收率 "
                 f"{sup.gen(optics['back'][0])}、发射率 {sup.gen(optics['back'][1])}，面热容 "
                 f"{sup.gen(inputs.get('areal_J_m2K', math.nan) / 1000.0)} kJ·m^{{−2}}·K^{{−1}}，与有限元模型参数表一致，"
                 f"C_S 按 T5 装配为 {sup.gen(inputs.get('C_S_J_K', math.nan) / 1e6, 4)} MJ/K")
    else:
        text += "，光学性质、面热容或 C_S 装配的核对未全部通过，见异常情况"
    pv_max = _worst([m[case].get("P_pv_max_kW", math.nan) for case in CASES])
    text += "；P_pv 按 0.073 乘正面收到的直射功率给定" + (f"，最大 {sup.num(pv_max, 1)} kW。" if math.isfinite(pv_max) else "。")
    parts.append(text)

    # orbit, attitude and SR
    if passed(N_ORBIT, N_ENV):
        text = (f"轨道取有限元轨道函数，高度 {sup.gen(inputs.get('altitude_m', math.nan) / 1000.0)} km，周期 "
                f"{sup.num(inputs.get('period_s', math.nan), 4)} s，三个工况的环境参数与有限元参数表一致")
    else:
        text = "轨道或环境参数与有限元的核对未全部通过，见异常情况"
    if passed(*[n_orbit_input(case) for case in CASES]):
        text += (f"；模块收到的 orbit_input 与有限元轨道函数文本求值的位置之差最大 "
                 f"{sup.sci(_worst([m[c].get('position_err_m', math.nan) for c in CASES]))} m，太阳方向与有限元光线反方向"
                 f"之差最大 {sup.sci(_worst([m[c].get('sun_direction_err', math.nan) for c in CASES]))}，由 G 定位的日食弧段"
                 f"与有限元 eclipse_deg 及其中心相差折合时间最大 "
                 f"{sup.sci(_worst([m[c].get('eclipse_arc_err_s', math.nan) for c in CASES]))} s，全部输出样点的 G 与有限元"
                 "地影弧段相符")
    else:
        bad = [case for case in CASES if not passed(n_orbit_input(case))]
        text += f"；{labels(bad)}的 orbit_input 与有限元轨道数据的核对未通过或未执行"
    if passed(*[n_attitude(case) for case in CASES]):
        text += (f"；姿态使正面法向始终指向太阳，模块给出的正面与背面入射余弦与 1 和 {sup.MINUS}1 之差最大 "
                 f"{sup.sci(_worst([m[c].get('cos_err', math.nan) for c in CASES]))}")
    else:
        text += "；姿态检查未全部通过或未执行"
    if passed(N_SR):
        text += f"；SR 连接取 {sup.sci(inputs.get('R_SR_K_W', math.nan))} K/W 表示不导热，并按第 9.4 节记录"
    else:
        text += "；SR 连接配置的核对未通过或未执行"
    q_sr = OUTCOME.get("q_SR_max_W", math.nan)
    if executed(N_QSR):
        text += (f"，全部运行 q_SR 的绝对值最大 {sup.sci(q_sr)} W，"
                 + ("不超过" if passed(N_QSR) else "未满足不超过") + f" {sup.sci(CRIT['q_SR_max_W'])} W 的要求")
    parts.append(text + "。")

    # step 2
    settings = OUTCOME.get("settings", {})
    run_names = [n_run(case, earth_on) for case in CASES for earth_on in (True, False)]
    t_end = _worst([m[case].get("t_end", math.nan) for case in CASES])
    text = (f"积分用 {settings.get('method', sup.MISSING_CN)}，相对容限 {sup.sci(settings.get('rtol'))}，温度绝对容限 "
            f"{sup.sci(settings.get('atol_T_K'))} K，最大步长 {sup.gen(settings.get('max_step_s'))} s，输出间隔 "
            f"{sup.gen(settings.get('output_step_s'))} s，自轨道正午积分 {sup.gen(t_end)} s")
    done = sum(passed(name) for name in run_names)
    text += (f"，{len(run_names)} 次运行全部按第 8 章设置完成" if done == len(run_names)
             else f"，{len(run_names)} 次运行中 {done} 次按第 8 章设置完成")
    eclipse_cases = [case for case in CASES if m[case].get("n_boundaries", 0) > 0]
    if passed(*[n_segments(case) for case in CASES]) and eclipse_cases:
        text += (f"；{labels(eclipse_cases)}在日食边界分段，日食进出时刻与圆柱阴影解析值之差最大 "
                 f"{sup.sci(_worst([m[c].get('eclipse_err_s', math.nan) for c in eclipse_cases]))} s，跨越边界的积分步 "
                 f"{sum(int(m[c].get('straddle', 0)) for c in CASES)} 个，每个边界后开始新的积分段")
    elif not passed(*[n_segments(case) for case in CASES]):
        text += "；日食边界分段的检查未全部通过或未执行"
    repeat_names = [n_repeat(case, earth_on) for case in CASES for earth_on in (True, False)]
    repetition = _worst([m[case].get(key, math.nan) for case in CASES for key in ("repetition_K", "repetition_no_earth_K")])
    if passed(*repeat_names):
        text += (f"；最后一圈与前一圈同相位的太阳能板温度差最大 {sup.sci(repetition)} K，不超过 "
                 f"{sup.gen(CRIT['repetition_K'])} K，取最后一圈按时间加权统计。")
    else:
        text += f"；逐圈重复的检查未全部通过或未执行，限值 {sup.gen(CRIT['repetition_K'])} K。"
    parts.append(text)

    # step 3 acceptance
    rows = []
    for case in CASES:
        v = m[case]
        values = [v.get(group, {}).get(key, math.nan) for group in ("module", "fe") for key in STATS]
        if "diffs" not in v or not all(math.isfinite(value) for value in values):
            rows.append(f"{_label(case)}未得到最后一圈的统计结果")
            continue
        mod, fe, d = v["module"], v["fe"], v["diffs"]
        rows.append(f"{_label(case)}集总模型最低、平均、最高温度为 {sup.num(mod['min'])}、{sup.num(mod['mean'])}、"
                    f"{sup.num(mod['max'])} °C，有限元为 {sup.num(fe['min'])}、{sup.num(fe['mean'])}、{sup.num(fe['max'])} °C，"
                    f"差为 {sup.num(abs(d['min']))}、{sup.num(abs(d['mean']))}、{sup.num(abs(d['max']))} K")
    accept_names = [n_accept(case, key) for case in CASES for key in STATS]
    diffs = [abs(m[case]["diffs"][key]) for case in CASES if "diffs" in m[case] for key in STATS]
    if passed(*accept_names):
        verdict = (f"{len(diffs)} 个统计量与有限元之差最大 {sup.num(_worst(diffs))} K，全部不超过验收值 "
                   f"{sup.gen(ACCEPT_K)} K，验收准则满足")
    elif executed(*accept_names):
        failed = sum(not passed(name) for name in accept_names)
        verdict = f"{len(accept_names)} 个统计量中 {failed} 个与有限元之差超过验收值 {sup.gen(ACCEPT_K)} K 或未得到，验收准则未满足"
    else:
        verdict = "部分统计量的验收检查未执行，验收准则未能判定"
    parts.append("；".join(rows) + f"。{verdict}。")

    # curves
    curves = {case: m[case].get("curve") for case in CASES}
    good = [case for case in CASES if curves[case] and passed(n_curve(case))]
    bad = [case for case in CASES if curves[case] and not passed(n_curve(case)) and math.isfinite(curves[case]["max_K"])]
    missing = [case for case in CASES if case not in good and case not in bad]
    pieces = []
    for case in good:
        c = curves[case]
        pieces.append(f"{_label(case)}{'' if c['eclipse'] else '全程受晒，'}逐点差最大 {sup.num(c['max_K'])} K，不超过 "
                      f"{sup.gen(ACCEPT_K)} K")
    for case in bad:
        c = curves[case]
        where = {"entry": f"进入日食后 {c['max_since_s']:.0f} s", "exit": f"离开日食后 {c['max_since_s']:.0f} s"}.get(
            c["max_kind"], f"{sup.num(c['max_time_s'], 1)} s")
        spans = "与".join(_group_cn(group).split("，")[0] for group in c["groups"])
        pieces.append(f"{_label(case)}逐点差最大 {sup.num(c['max_K'])} K，出现在{where}，超过 {sup.gen(ACCEPT_K)} K 的是{spans}，"
                      f"逐点差均方根 {sup.num(c['rms_K'])} K")
    for case in missing:
        pieces.append(f"{_label(case)}未得到逐点差")
    text = ("曲线对比把有限元第三圈每个输出时刻的太阳翼平均温度与集总模型同一时刻的温度相减，不加时间窗。"
            + "；".join(pieces) + "。")
    if bad:
        text += (f"曲线重合的预期在{labels(bad)}未满足，超过 {sup.gen(ACCEPT_K)} K 的时刻集中在进出日食后的温度快速变化段，"
                 f"这些时刻有限元太阳翼最高与最低温度之差不超过 "
                 f"{sup.num(_worst([curves[c]['spread_over_K'] for c in bad]))} K；{CURVE_CONTEXT_CN}。")
    elif missing:
        text += f"{labels(missing)}的曲线对比没有完成。"
    else:
        text += "三个工况的温度曲线在每个有限元输出时刻都与有限元相差不超过验收值，曲线重合。"
    parts.append(text)

    # T3 and T4 terms
    pieces = []
    flux = _worst([m[c].get("flux_view_factor_err", math.nan) for c in CASES])
    env_rel = _worst([m[c].get("env_rel", math.nan) for c in CASES])
    emit_rel = _worst([m[c].get("emit_rel", math.nan) for c in CASES])
    t3_rel = _worst([m[c].get("t3_rel", math.nan) for c in CASES])
    flux_ok, env_ok = passed(*[n_flux(c) for c in CASES]), passed(*[n_env(c) for c in CASES])
    emit_ok, t3_ok = passed(*[n_emit(c) for c in CASES]), passed(*[n_t3(c) for c in CASES])
    pieces.append(f"太阳能板两面的反照与红外辐照与独立球冠积分之差折合视角系数最大 {sup.sci(flux)}，"
                  + ("不超过" if flux_ok else "未全部满足") + f" {sup.sci(CRIT['view_factor_tol'])}")
    pieces.append(f"Q_env,S 与按 T4 独立手算的相对差最大 {sup.sci(env_rel)}，" + ("不超过" if env_ok else "未全部满足")
                  + f" {sup.sci(CRIT['relative_tol_env'])}")
    pieces.append(f"Q_emit,S 按两面发射率手算的相对差最大 {sup.sci(emit_rel)}，T3 第一行残差与各项绝对值之和之比最大 "
                  f"{sup.sci(t3_rel)}，" + ("均不超过" if emit_ok and t3_ok else "未全部满足") + f" {sup.sci(CRIT['relative_tol_exact'])}")
    pv = [m[c].get("pv") for c in CASES if m[c].get("pv")]
    if passed(*[n_pv(c) for c in CASES]) and len(pv) == len(CASES):
        pieces.append(
            f"calculate_surface_heat 给出的 absorbed_solar_S_W 与手算直射吸收的相对差最大 "
            f"{sup.sci(_worst([p['absorbed_rel'] for p in pv]))}，给定的 P_pv 全部不超过 absorbed_solar_S_W；在 "
            f"{sum(p['sunlit_probes'] for p in pv)} 个受晒校核时刻 P_pv 等于 absorbed_solar_S_W 时 thermal_derivative 接受，"
            f"超出 {sup.sci(CRIT['pv_over_limit_relative'])} 相对量时报出超限，在 {sum(p['eclipse_probes'] for p in pv)} 个日食"
            f"校核时刻 P_pv 取 {sup.gen(CRIT['pv_eclipse_probe_W'])} W 时报出超限；P_pv 由零增至给定值时只有 dT_S/dt 改变，"
            f"减少量乘 C_S 与 P_pv 的相对差最大 {sup.sci(_worst([p['deduction_rel'] for p in pv]))}")
    else:
        bad_pv = [case for case in CASES if not passed(n_pv(case))]
        pieces.append(f"{labels(bad_pv)}的实际电输出上限与扣除检查未通过或未执行")
    parts.append("；".join(pieces) + "。")

    # step 4
    lows = {key: [m[c]["lower"][key] for c in CASES if "lower" in m[c]] for key in STATS}
    if lows["max"]:
        recorded = passed(*[n_recorded(c) for c in CASES])
        text = ("关闭反照与红外后，三次运行的归档按第 9.4 节记录了简化条件" if recorded
                else "关闭反照与红外后，简化条件的归档记录检查未全部通过")
        text += (f"；最后一圈最高温度低 {sup.num(_least(lows['max']), 1)} 至 {sup.num(_worst(lows['max']), 1)} K，平均温度低 "
                 f"{sup.num(_least(lows['mean']), 1)} 至 {sup.num(_worst(lows['mean']), 1)} K")
        eclipse_cases = [c for c in CASES if m[c].get("n_boundaries", 0) > 0 and "lower" in m[c]]
        sunlit_cases = [c for c in CASES if m[c].get("n_boundaries", 0) == 0 and "lower" in m[c]]
        if eclipse_cases:
            mins = [m[c]["lower"]["min"] for c in eclipse_cases]
            text += f"，有日食工况的最低温度低 {sup.num(_least(mins), 1)} 至 {sup.num(_worst(mins), 1)} K"
        if sunlit_cases:
            text += "，" + "、".join(f"{_label(c)}最低温度低 {sup.num(m[c]['lower']['min'], 1)} K" for c in sunlit_cases)
        text += ("，三个工况的降幅都大于 3 K，温度明显偏低" if passed(*[n_lower(c) for c in CASES])
                 else "，部分统计量的降幅不大于 3 K 或未得到")
        analytic = _worst([m[c].get("analytic_err_K", math.nan) for c in CASES])
        text += (f"；关闭后的温度时程与受晒段和日食段的分段解析解之差最大 {sup.sci(analytic)} K，"
                 + ("不超过" if passed(*[n_analytic(c) for c in CASES]) else "未全部满足") + f" {sup.gen(CRIT['analytic_K'])} K")
        text += ("，Q_env,S 只含正面直射吸收。" if passed(*[n_direct(c) for c in CASES])
                 else "，Q_env,S 只含直射吸收的检查未全部通过。")
        parts.append(text)
    else:
        parts.append("关闭反照与红外的对比没有完成。")
    return "".join(parts)


def _hook_failure_cn(function: str, when: str, actual: str, checks: list[dict]) -> tuple[str, str]:
    """Chinese sentence for a test function failure that conftest recorded from the pytest report."""

    stage = {"setup": "准备阶段", "call": "执行阶段", "teardown": "清理阶段"}.get(when, when)
    match = re.search(r":\d+: ([A-Za-z_][\w.]*)\s*$", str(actual))
    exception = match.group(1).split(".")[-1] if match else None
    own = set(EXPECTED_CHECKS.get(function, []))
    own_failed = any(not check["passed"] and check["name"] in own for check in checks)
    if exception == "AssertionError" and own_failed:
        return stage, "因该函数中的检查未通过判为失败"
    if exception:
        return stage, f"出现 {exception} 异常，异常信息记录在证据文件中"
    return stage, "失败，失败信息记录在证据文件中"


def _anomalies_text(checks: list[dict], closing_failure: bool) -> str:
    """Every failed check and every check that was not executed, in Chinese sentences of the report rules."""

    items = []
    recorded = {check["name"] for check in checks}
    hook_groups: dict[tuple[str, str], list[str]] = {}
    curve_failed = False
    for check in checks:
        if check["passed"]:
            continue
        name = check["name"]
        hook = (re.fullmatch(r"(test_\w+) (setup|call|teardown)", name)
                if check["expected"] == "test function completes" else None)
        if hook:
            stage, reason = _hook_failure_cn(hook.group(1), hook.group(2), check["actual"], checks)
            hook_groups.setdefault((stage, reason), []).append(hook.group(1))
        elif name in FAILURES_CN:
            items.append(FAILURES_CN[name])
            curve_failed |= name in {n_curve(case) for case in CASES}
        else:
            items.append(f"{sup.cn_clean(name)}未通过，实际结果为 {sup.cn_clean(check['actual'], 200)}")
    if curve_failed and OUTCOME.get("curve_context"):
        items.append(CURVE_CONTEXT_CN)
    for function, names in EXPECTED_CHECKS.items():
        missing = [name for name in names if name not in recorded]
        if not missing:
            continue
        if len(missing) <= 3:
            items.append(f"{'、'.join(missing)}未执行")
        else:
            items.append(f"{FUNCTION_CN[function]}的 {len(missing)} 项检查未执行")
    for (stage, reason), functions in hook_groups.items():
        items.append(f"测试函数 {'、'.join(functions)} 在{stage}{reason}")
    if closing_failure:
        items.append("测试函数 test_zz_evidence_and_summary 在执行阶段因上述准备、证据或摘要问题判为失败")
    return "。".join(items) + "。" if items else "无"


def test_zz_evidence_and_summary(request, case_record):
    """Time histories for the report figures, 9.4 run records, Chinese summary and anomalies.

    The evidence files and the summary are written inside try blocks that record a failed check, and the anomalies are
    written last from every recorded check, so a failure is never reported with an empty summary or as 无.
    """

    try:
        fe001 = request.getfixturevalue("fe001")
    except Exception as exc:  # noqa: BLE001  (the setup failure is recorded, the summary still states it)
        fe001 = None
        _check(case_record, N_SETUP, "三个工况的模型装配与联合计算完成", f"{type(exc).__name__}: {exc}", False,
               f"三个工况的模型装配或联合计算出现 {type(exc).__name__} 异常，计算检查均未执行")
    files = {}
    if fe001 is not None:
        try:
            files = _write_evidence(fe001)
        except Exception as exc:  # noqa: BLE001
            _check(case_record, N_EVIDENCE, "FE-001_series.json 与 FE-001_runs.json 写出", f"{type(exc).__name__}: {exc}",
                   False, f"时程文件与运行记录文件未能写出，出现 {type(exc).__name__} 异常")
    _metric(case_record, "evidence_files", files)
    try:
        summary = _summary_text(fe001, case_record.checks)
    except Exception as exc:  # noqa: BLE001
        summary = "本用例的中文摘要未能按计算结果生成，各项检查的结果见检查记录与异常情况。"
        _check(case_record, N_SUMMARY, "中文摘要按计算结果生成", f"{type(exc).__name__}: {exc}", False,
               f"中文摘要生成时出现 {type(exc).__name__} 异常")
    case_record.summary(summary)
    own = {N_SETUP, N_EVIDENCE, N_SUMMARY}
    closing_ok = not any(check["name"] in own and not check["passed"] for check in case_record.checks)
    try:
        anomalies = _anomalies_text(case_record.checks, not closing_ok)
    except Exception as exc:  # noqa: BLE001
        failed = sum(1 for check in case_record.checks if not check["passed"])
        anomalies = (f"本用例有 {failed} 项检查未通过，异常情况的中文说明在生成时出现 {type(exc).__name__} 异常，未通过的检查见"
                     "证据文件 tests/results/FE-001.json")
    case_record.anomalies(anomalies)
    assert closing_ok
