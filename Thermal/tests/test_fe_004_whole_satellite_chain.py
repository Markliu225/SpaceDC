"""FE-004 整星有限元链路对标: computing node J, cold plate C and radiator R against the whole-satellite COMSOL model.

Implements the CASES entry FE-004 of Thermal/test_report/build_test_report_cn.py (thermal design 3.1 figure 1, 4.3 T3,
appendix B; requirements TH-01 and TH-04).

Preconditions: the whole-satellite COMSOL results of 30 August 2026 exist (GPU baseplate, bus and radiator time
histories in out/comsol/<case>_probes.csv); the TIM and heat-pipe data of the FE model are converted by T5 into R_JC
and R_CR with the method and the sources recorded.
Inputs: two cases, 12 x V100 (caseA) and 12 x A100 (caseB); the same orbit, attitude and load power history as the FE.
Steps: 1 assemble J, C and R from the FE model parameters; 2 run five orbits with the same power history; 3 compare the
GPU baseplate mean and the radiator mean of orbits 4 and 5.
Expected: the J to C to R chain reproduces the temperature difference between the computing equipment and the
radiator; the single-node model is 12 to 15 degC below the GPU baseplate in the same comparison.
Acceptance: in orbits 4 and 5 the GPU baseplate and radiator mean temperature differences are each at most 5 K.

Mapping of the FE model onto the design network (recorded in the parameter provenance):
* J (Compute01): the 12 GPU packages, the 12 blades and the bus structure (spine, thrusters, tanks). The FE bus carries
  the 570 W platform heat, which leaves through the blades and the same heat-pipe network as the GPU heat; the design
  network has no bus node, so the bus mass and its heat join J and pass JC and CR like in the FE. A sensitivity run
  puts the bus on the power equipment node D instead (its own DR path) to show the effect of this representation.
* C (ColdPlate01): the four heat-pipe transport bundles and connectors between the blades and the radiator panels.
* R (Radiator01): the two radiator panels with the surface-mounted headers and spreaders; its exposed surfaces are the
  four panel faces, 6.273 m2, the radiating area of the FE (REPORT.md section 6 check 3).
* R_JC = TIM contact resistance (T5 contact term) + conduction from the package footprint through the blade to the
  bundle contact (T5 conduction term, effective cross-section from a three-dimensional conduction solution of the FE
  blade); R_CR = heat-pipe network with the FE k_eff (vendor resistance per length) plus the panel fin conduction.
* S (SolarArray01): the FE solar wings, decoupled by a very large SR like the FE (no booms); B and D are auxiliary nodes
  without heat and decoupled; they are not compared.

The real module runs: thermal_derivative is called by sdtwin_sim.coupled.run_coupled (thermal-only run with prescribed
ports). References are independent of the module: the FE probes and the OrbitWiz trace, the FE model files, a
three-dimensional conduction solution and a heat-pipe network calculation, an Earth-centred view-factor quadrature and
hand T2, T3, T4 and T5 calculations (tests/data/fe_004/fe004_support.py).
"""

from __future__ import annotations

import importlib.util
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest

from sdtwin_sim import coupled as cp
from thermal import ThermalState, assemble_thermal_parameters
from thermal.types import NODE_ORDER, PATH_ORDER

pytestmark = pytest.mark.case("FE-004")

THERMAL_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = THERMAL_DIR.parent
DATA_DIR = Path(__file__).resolve().parent / "data" / "fe_004"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load_support():
    spec = importlib.util.spec_from_file_location("fe004_support", DATA_DIR / "fe004_support.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load_support()
CFG = sup.load_json(DATA_DIR / "fe004_config.json")
FE_DIR = REPO_DIR / CFG["fe"]["dir"]
CASES = tuple(CFG["cases"])
CRIT = CFG["criteria"]
SOLVER = CFG["solver"]
ENVCFG = CFG["environment"]
ACCEPT_K = float(CRIT["acceptance_K"])
N_GPU = int(CFG["gpu_count"])
I = {node: index for index, node in enumerate(NODE_ORDER)}
IP = {path: index for index, path in enumerate(PATH_ORDER)}
BIG = float(CFG["decoupling"]["resistance_K_W"])
ORBITS = (4, 5)
OUTCOME: dict = {}


# ------------------------------------------------------------------------------------------------ T5 derivation


def _derive(G) -> dict:
    """J, C and R parameters of the design network from the FE model files (T5), with the derivation details."""

    masses = sup.mass_table(G)
    cp_al = float(G.AL["cp"])
    grid = {}
    for h in CFG["blade_grid_m"]:
        grid[h] = {"gpu": sup.blade_conduction(G, h, 1.0, 0.0), "bus": sup.blade_conduction(G, h, 0.0, 1.0)}
    used = grid[CFG["blade_grid_used_m"]]
    r_tim_package = G.TIM_R_M2K_W / (G.PKG_W * G.PKG_D)
    r_contact = r_tim_package / N_GPU
    r_cond = used["gpu"]["baseplate_K"] / N_GPU
    length = used["gpu"]["conduction_length_m"]
    k_al = float(G.AL["k"])
    area_eff = length / (k_al * r_cond)
    network = sup.heat_pipe_network(G)
    cover = sup.radiator_face_coverage(G)
    wing_area = sum(w["size"][1] * w["size"][2] for w in G.wings())
    panels = [r for r in G.radiators() if not r.get("boom")]
    face_area = panels[0]["size"][0] * panels[0]["size"][2]
    aux = {item["instance_id"]: item for item in CFG["auxiliary_nodes"]["components"]}
    m_j = masses["packages"]["mass_kg"] + masses["blades"]["mass_kg"] + masses["bus"]["mass_kg"]
    m_r = masses["radiator_panels"]["mass_kg"] + masses["hp_condenser"]["mass_kg"]
    capacitance = {
        "S": G.SOL_AREAL_KG_M2 * wing_area * cp_al,
        "J": m_j * cp_al,
        "C": masses["hp_transport"]["mass_kg"] * cp_al,
        "B": aux["Battery01"]["mass_kg"] * aux["Battery01"]["cp_J_kgK"],
        "D": aux["Controller01"]["mass_kg"] * aux["Controller01"]["cp_J_kgK"]
        + aux["PDU01"]["mass_kg"] * aux["PDU01"]["cp_J_kgK"],
        "R": m_r * cp_al,
    }
    resistance = {
        "SR": BIG,
        "JC": length / (k_al * area_eff) + r_contact,
        "CR": network["R_CR_K_W"],
        "BR": BIG,
        "DR": BIG,
    }
    # sensitivity configuration: bus on node D with its own path to R (spine contact, blade, one heat-pipe copy)
    r_dr_bus = used["bus"]["spine_contact_K"] / N_GPU + network["R_CR_K_W"]
    return {
        "masses": masses, "grid": grid, "used": used, "r_tim_package": r_tim_package, "r_contact": r_contact,
        "r_cond": r_cond, "length": length, "k_al": k_al, "area_eff": area_eff, "network": network, "cover": cover,
        "wing_area": wing_area, "face_area": face_area, "capacitance": capacitance, "resistance": resistance,
        "r_dr_bus": r_dr_bus, "cp_al": cp_al,
    }


def _components(G, der: dict, bus_on_D: bool) -> tuple[list[dict], list[dict]]:
    comp = CFG["components"]
    cp_al = der["cp_al"]
    rng = CFG["temperature_range_K"]
    masses = der["masses"]
    sa = comp["SolarArray01"]
    surfaces_s = []
    for side in ("front", "back"):
        rec = sa[side]
        surfaces_s.append({"surface_id": rec["surface_id"], "area_m2": der["wing_area"], "normal_body": rec["normal_body"],
                           "absorptivity": rec["absorptivity"], "emissivity": rec["emissivity"], "source": sa["source"]})
    j = comp["Compute01"]
    j_materials = [
        {"material_id": j["materials"]["packages"], "mass_kg": masses["packages"]["mass_kg"], "cp_J_kgK": cp_al,
         "source": j["source"] + "; 12 package boxes PKG_W x PKG_D x PKG_H"},
        {"material_id": j["materials"]["blades"], "mass_kg": masses["blades"]["mass_kg"], "cp_J_kgK": cp_al,
         "source": j["source"] + "; 12 blade boxes BLADE_W x (spine face to 0.3825 m) x BLADE_H"},
    ]
    bus_material = {"material_id": j["materials"]["bus"], "mass_kg": masses["bus"]["mass_kg"], "cp_J_kgK": cp_al,
                    "source": j["source"] + "; union of the BUS boxes; the bus has no node in the design network and "
                              "is lumped with the blades it holds, its 570 W platform heat joins P_load_W"}
    aux = {item["instance_id"]: item for item in CFG["auxiliary_nodes"]["components"]}
    aux_src = CFG["auxiliary_nodes"]["source"]
    if bus_on_D:
        controller_materials = [dict(bus_material, material_id="Controller01_bus_structure",
                                     source=j["source"] + "; sensitivity configuration: the bus on the power equipment "
                                                          "node D with Q_D_W = platform heat and its own DR path")]
    else:
        j_materials.append(bus_material)
        controller_materials = [{"material_id": "Controller01_material", "mass_kg": aux["Controller01"]["mass_kg"],
                                 "cp_J_kgK": aux["Controller01"]["cp_J_kgK"], "source": aux_src}]
    r = comp["Radiator01"]
    surfaces_r = []
    for rad in ("Top", "Bot"):
        for side, ny in (("p", 1.0), ("n", -1.0)):
            surfaces_r.append({"surface_id": f"Radiator{rad}_{side}", "area_m2": der["face_area"],
                               "normal_body": [0.0, ny, 0.0], "absorptivity": r["absorptivity"],
                               "emissivity": r["emissivity"], "source": r["source"]})
    components = [
        {"instance_id": "SolarArray01", "node_id": "S", "asset_id": sa["asset_id"], "asset_version": sa["asset_version"],
         "materials": [{"material_id": sa["material_id"], "mass_kg": G.SOL_AREAL_KG_M2 * der["wing_area"],
                        "cp_J_kgK": cp_al, "source": sa["source"]}],
         "surfaces": surfaces_s, "temperature_range_K": rng, "ports": sa["ports"]},
        {"instance_id": "Compute01", "node_id": "J", "asset_id": j["asset_id"], "asset_version": j["asset_version"],
         "materials": j_materials, "temperature_range_K": rng, "ports": j["ports"]},
        {"instance_id": "ColdPlate01", "node_id": "C", "asset_id": comp["ColdPlate01"]["asset_id"],
         "asset_version": comp["ColdPlate01"]["asset_version"],
         "materials": [{"material_id": comp["ColdPlate01"]["material_id"], "mass_kg": masses["hp_transport"]["mass_kg"],
                        "cp_J_kgK": cp_al, "source": comp["ColdPlate01"]["source"]}],
         "temperature_range_K": rng, "ports": comp["ColdPlate01"]["ports"]},
        {"instance_id": "Battery01", "node_id": "B", "asset_id": "fe004_aux_battery01", "asset_version": "1",
         "materials": [{"material_id": "Battery01_material", "mass_kg": aux["Battery01"]["mass_kg"],
                        "cp_J_kgK": aux["Battery01"]["cp_J_kgK"], "source": aux_src}],
         "temperature_range_K": CFG["auxiliary_nodes"]["temperature_range_K"], "ports": aux["Battery01"]["ports"]},
        {"instance_id": "Controller01", "node_id": "D", "asset_id": "fe004_aux_controller01", "asset_version": "1",
         "materials": controller_materials, "temperature_range_K": CFG["auxiliary_nodes"]["temperature_range_K"],
         "ports": aux["Controller01"]["ports"]},
        {"instance_id": "PDU01", "node_id": "D", "asset_id": "fe004_aux_pdu01", "asset_version": "1",
         "materials": [{"material_id": "PDU01_material", "mass_kg": aux["PDU01"]["mass_kg"],
                        "cp_J_kgK": aux["PDU01"]["cp_J_kgK"], "source": aux_src}],
         "temperature_range_K": CFG["auxiliary_nodes"]["temperature_range_K"], "ports": aux["PDU01"]["ports"]},
        {"instance_id": "Radiator01", "node_id": "R", "asset_id": r["asset_id"], "asset_version": r["asset_version"],
         "materials": [
             {"material_id": r["materials"]["panels"], "mass_kg": masses["radiator_panels"]["mass_kg"], "cp_J_kgK": cp_al,
              "source": r["source"] + "; 2 panels x 4.4 kg/m2 x 1.568 m2"},
             {"material_id": r["materials"]["condenser"], "mass_kg": masses["hp_condenser"]["mass_kg"], "cp_J_kgK": cp_al,
              "source": r["source"] + "; 4 headers and 32 spreaders, union volume x 2700 kg/m3"}],
         "surfaces": surfaces_r, "temperature_range_K": rng, "ports": r["ports"]},
    ]
    net = der["network"]
    dec = CFG["decoupling"]
    jc_source = (f"T5 second line, FE-004 derivation: contact term = FE TIM {G.TIM_R_M2K_W} m2K/W (Honeywell PTM7000, "
                 "PHASE1_ADDENDUM_materials.md) over the package footprint PKG_W x PKG_D, 12 in parallel; conduction term "
                 "= blade path from the package footprint to the heat-pipe bundle contact, length 0.117 m along x, "
                 "aluminium 238 W/mK, effective cross-section from a steady three-dimensional conduction solution of the "
                 f"FE blade and package at {CFG['blade_grid_used_m'] * 1000:.1f} mm cells (12 blades in parallel)")
    cr_source = (f"heat-pipe equivalent total of T5 (design 4.5), FE-004 derivation: FE heat-pipe blocks with k_eff "
                 f"{net['k_eff_W_mK']:.6g} W/mK = 0.305 m / (0.015 K/W x pi 6.35 mm^2) (ACT CCHP data, geometry_spec.py "
                 "HP_K_EFF), segments l/(k_eff A) of bundle, connector, header and spreaders with the FE block "
                 "cross-sections, distributed inputs and outputs at length/3, plus the radiator panel fin conduction "
                 "with the FE equivalent shell k t = 0.388 W/K; the FE joins pipes, blades and panels with perfect "
                 "contact, so the total includes the contact part")
    connections = [
        {"path": "SR", "equivalent_total_resistance_K_W": BIG, "includes_contact": True, "source": dec["SR_source"]},
        {"path": "JC", "length_m": der["length"], "conductivity_W_mK": der["k_al"], "area_m2": der["area_eff"],
         "contact_resistance_K_W": der["r_contact"], "source": jc_source},
        {"path": "CR", "equivalent_total_resistance_K_W": net["R_CR_K_W"], "includes_contact": True, "source": cr_source},
        {"path": "BR", "equivalent_total_resistance_K_W": BIG, "includes_contact": True, "source": dec["BR_source"]},
    ]
    if bus_on_D:
        connections.append({"path": "DR", "equivalent_total_resistance_K_W": der["r_dr_bus"], "includes_contact": True,
                            "source": "FE-004 sensitivity configuration: bus heat from the spine contact through one "
                                      "blade path and a separate copy of the heat-pipe network R_CR"})
    else:
        connections.append({"path": "DR", "equivalent_total_resistance_K_W": BIG, "includes_contact": True,
                            "source": dec["DR_source"]})
    return components, connections


def _settings() -> cp.SolverSettings:
    return cp.SolverSettings(method=SOLVER["method"], rtol=SOLVER["rtol"], atol_T_K=SOLVER["atol_T_K"],
                             max_step_s=SOLVER["max_step_s"], output_step_s=SOLVER["output_step_s"],
                             environment_step_s=SOLVER["environment_step_s"],
                             event_time_tol_s=SOLVER["event_time_tol_s"])


# ------------------------------------------------------------------------------------------------ FE inputs


def _solar_irradiance(trace: dict, t0: float, period: float) -> float:
    t = trace["t_s"]
    sel = (t >= t0 - 120.0) & (t <= t0 + 3 * period + 60.0)
    return round(float(np.mean(trace["solar_flux_w_m2"][sel])), 2)


def _power(trace: dict, t0: float):
    tau = trace["t_s"] - t0
    heat = trace["heat_per_gpu_w"]
    plat = trace["heat_platform_w"]

    def gpu_W(t: float) -> float:
        return N_GPU * float(np.interp(t, tau, heat))

    def platform_W(t: float) -> float:
        return float(np.interp(t, tau, plat))

    return gpu_W, platform_W


def _ports(gpu_W, platform_W, bus_on_D: bool):
    def prescribed_ports(t: float) -> dict:
        if bus_on_D:
            return {"P_pv_W": 0.0, "P_load_W": gpu_W(t), "Q_B_W": 0.0, "Q_D_W": platform_W(t)}
        return {"P_pv_W": 0.0, "P_load_W": gpu_W(t) + platform_W(t), "Q_B_W": 0.0, "Q_D_W": 0.0}

    return prescribed_ports


def _power_steps(trace: dict, t0: float, t_end: float) -> list[float]:
    """Both ends of every 1 s ramp of the power table larger than the threshold (input discontinuities)."""

    tau = trace["t_s"] - t0
    heat = trace["heat_per_gpu_w"]
    plat = trace["heat_platform_w"]
    jump = np.abs(np.diff(heat)) > SOLVER["power_step_threshold_W"]
    jump |= np.abs(np.diff(plat)) > SOLVER["power_step_threshold_W"]
    out = []
    for index in np.where(jump)[0]:
        for moment in (float(tau[index]), float(tau[index + 1])):
            if 0.0 < moment < t_end:
                out.append(moment)
    return out


def _run(case: str, label: str, params, env, power, bus_on_D: bool, t_init: float, t_end: float, S_sun: float,
         bounds: list[float], provenance: dict) -> dict:
    run_id = f"FE-004-{case}-{label}"
    earth = cp.EarthFluxModel(albedo=ENVCFG["albedo"], olr_W_m2=ENVCFG["olr_W_m2"], solar_constant_W_m2=S_sun,
                              earth_radius_m=ENVCFG["earth_radius_m"])
    provider = cp.EnvironmentProvider.from_callables(
        run_id=run_id, epoch=env.epoch, parameters=params, position=env.position, sun_position=env.sun_position,
        quaternion=env.quaternion, G=env.irradiance, earth_flux=earth, eclipse_fraction=env.illumination,
        time_range_s=env.tau_range)
    initial = ThermalState(run_id, 0.0, [t_init] * len(NODE_ORDER))
    started = time.perf_counter()
    error = None
    try:
        archive = cp.run_coupled(params, initial, provider, t_end, settings=_settings(),
                                 prescribed_ports=_ports(*power, bus_on_D), boundaries_s=bounds,
                                 provenance=provenance)
    except cp.CoupledRunError as exc:
        archive, error = exc.archive, f"{type(exc).__name__}: {exc}"
    return {"run_id": run_id, "archive": archive, "provider": provider, "error": error,
            "wall_s": time.perf_counter() - started}


@pytest.fixture(scope="module")
def fe004():
    G = sup.load_geometry_spec(FE_DIR / CFG["fe"]["geometry_spec"])
    const = sup.fe_constants(FE_DIR / CFG["fe"]["build_script"])
    t0, period = const["T0_HOT_S"], const["PERIOD_S"]
    t_end = 5.0 * period
    der = _derive(G)
    comps, conns = _components(G, der, bus_on_D=False)
    params = assemble_thermal_parameters(comps, conns, None)
    comps_d, conns_d = _components(G, der, bus_on_D=True)
    params_d = assemble_thermal_parameters(comps_d, conns_d, None)
    data = {"G": G, "t0": t0, "period": period, "t_end": t_end, "der": der, "components": comps,
            "connections": conns, "params": params, "params_bus_D": params_d, "cases": {}}
    for case in CASES:
        cfg = CFG["cases"][case]
        trace = sup.read_trace(FE_DIR / cfg["trace"])
        probes = sup.read_csv_columns(FE_DIR / cfg["probes"])
        solve_log = sup.load_json(FE_DIR / cfg["solve_log"])
        S_sun = _solar_irradiance(trace, t0, period)
        env = sup.FEOrbitEnvironment(trace, t0, -10.0, t_end + 10.0, ENVCFG["earth_radius_m"], S_sun)
        power = _power(trace, t0)
        t_init = round(float(np.interp(0.0, trace["t_s"] - t0, trace["T_struct_c"])) + 273.15, 2)
        bounds = _power_steps(trace, t0, t_end)
        provenance = {
            "case_id": "FE-004", "fe_case": case, "gpu": cfg["gpu"], "fe_dir": CFG["fe"]["dir"],
            "orbit": CFG["orbit_source"], "attitude": CFG["attitude_source"], "power": CFG["power_source"],
            "environment": ENVCFG["source"], "solar_irradiance_W_m2": S_sun,
            "initial_temperature": f"uniform {t_init} K = FE ht initial value (OrbitWiz T_struct at the hot instant)",
            "time_origin": f"tau = 0 at the FE hot instant t_s = {t0} s of the OrbitWiz trace",
            "bus_representation": "bus mass and platform heat lumped into J (Compute01)",
            "decoupling": CFG["decoupling"],
        }
        runs = {"main": _run(case, "main", params, env, power, False, t_init, t_end, S_sun, bounds, provenance)}
        prov_d = dict(provenance, bus_representation="sensitivity: bus on node D (Controller01) with Q_D_W = platform heat")
        runs["bus_D"] = _run(case, "busD", params_d, env, power, True, t_init, t_end, S_sun, bounds, prov_d)
        data["cases"][case] = {"cfg": cfg, "trace": trace, "probes": probes, "solve_log": solve_log, "S_sun": S_sun,
                               "env": env, "power": power, "t_init": t_init, "bounds": bounds, "runs": runs}
    return data


# ------------------------------------------------------------------------------------------------ helpers


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-300)


def _fe_events(probes: dict) -> list[tuple[float, str]]:
    t, ill = probes["t_s"], probes["illum"]
    out = []
    for k in range(len(t) - 1):
        if ill[k] != ill[k + 1]:
            out.append((float(t[k + 1]), "entry" if ill[k + 1] < ill[k] else "exit"))
    return out


def _orbit_window(period: float, orbit: int) -> tuple[float, float]:
    return (orbit - 1) * period, orbit * period


def _check_indices(archive, period: float) -> list[int]:
    n = len(archive.time_s)
    picks = set(int(v) for v in np.linspace(0, n - 1, int(CRIT["check_samples"])))
    illum = np.asarray(archive.environment["illumination_fraction"])
    dark = np.where(illum == 0.0)[0]
    if dark.size:
        picks.update(int(v) for v in dark[:: max(1, dark.size // 4)][:4])
    return sorted(picks)


# ------------------------------------------------------------------------------------------------ step 1


def test_step1_assemble_j_c_r(fe004, case_record):
    """Step 1: assemble J, C and R from the whole-satellite model parameters (T5) and record every source."""

    G, der, params = fe004["G"], fe004["der"], fe004["params"]
    period = fe004["period"]
    ok = []
    out = OUTCOME.setdefault("step1", {})

    # FE data used as the reference reproduce the numbers of the FE report (orbits 4 to 5, sample means)
    lo, hi = 3 * period, 5 * period
    for case in CASES:
        c = fe004["cases"][case]
        pr, tr = c["probes"], c["trace"]
        rep = c["cfg"]["report_o45_C"]
        tau_tr = tr["t_s"] - fe004["t0"]
        node_on_fe = np.interp(pr["t_s"], tau_tr, tr["T_struct_c"])
        mine = {"radiator_mean": sup.sample_mean(pr["t_s"], pr["rad_mean_K"], lo, hi) - 273.15,
                "baseplate_mean": sup.sample_mean(pr["t_s"], pr["baseplate_mean_K"], lo, hi) - 273.15,
                "bus_mean": sup.sample_mean(pr["t_s"], pr["bus_mean_K"], lo, hi) - 273.15,
                "orbitwiz_node": sup.sample_mean(pr["t_s"], node_on_fe, lo, hi)}
        worst = max(abs(mine[k] - rep[k]) for k in rep)
        passed = worst <= CRIT["report_match_K"]
        ok.append(case_record.check(
            f"步骤1 {case} 有限元数据与报告一致",
            f"probes 与 OrbitWiz 轨迹的第四、五圈样本均值与 {CFG['report_o45_source']} 相差不超过 {CRIT['report_match_K']} K",
            "; ".join(f"{k} {mine[k]:.3f} °C 报告 {rep[k]} °C" for k in rep) + f"; 最大差 {worst:.3f} K", passed))
        area_fe = float(c["solve_log"]["energy_balance_A"]["area_rad_faces_m2"])
        area_mod = sum(s.area_m2 for s in params.surfaces if s.node_id == "R")
        passed = _rel(area_mod, area_fe) <= 1e-6
        ok.append(case_record.check(
            f"步骤1 {case} 散热板辐射面积与有限元一致",
            "四个散热板面面积之和等于有限元积分的散热板面积, 相对差 <= 1e-6",
            f"模块 {area_mod:.6f} m2, 有限元 {area_fe:.6f} m2", passed))

    # capacitances by T5 first line
    m = der["masses"]
    hand = der["capacitance"]
    for node, detail in (
        ("J", f"封装 {m['packages']['mass_kg']:.3f} kg + 刀片 {m['blades']['mass_kg']:.3f} kg + 机身 {m['bus']['mass_kg']:.3f} kg, "
              f"cp {der['cp_al']} J/kgK"),
        ("C", f"热管传输段与连接段 {m['hp_transport']['mass_kg']:.3f} kg, cp {der['cp_al']} J/kgK"),
        ("R", f"散热板 {m['radiator_panels']['mass_kg']:.3f} kg + 集热管与分支热管 {m['hp_condenser']['mass_kg']:.3f} kg, "
              f"cp {der['cp_al']} J/kgK"),
        ("S", f"太阳翼 {G.SOL_AREAL_KG_M2} kg/m2 x {der['wing_area']:.4f} m2, cp {der['cp_al']} J/kgK"),
    ):
        value = float(params.C_J_K[I[node]])
        passed = _rel(value, hand[node]) <= CRIT["relative_tol_exact"]
        ok.append(case_record.check(
            f"步骤1 C_{node} 按 T5 第一行", f"C_{node} = sum m cp = {hand[node]:.6f} J/K, 相对差 <= 1e-12; {detail}",
            f"模块 C_J_K[{node}] = {value:.6f} J/K", passed))
    portions = [p["material_id"] for node in NODE_ORDER for p in params.provenance["capacitance"][node]["portions"]]
    passed = (m["bus"]["volume_m3"] < m["bus"]["box_sum_volume_m3"] and len(portions) == len(set(portions)))
    ok.append(case_record.check(
        "步骤1 质量只计一次",
        "有限元重叠块按 Form Union 合并后计体积, 机身并集体积小于各块体积之和; 每个材料份额只属于一个组件",
        f"机身并集 {m['bus']['volume_m3']:.6f} m3, 各块之和 {m['bus']['box_sum_volume_m3']:.6f} m3; "
        f"{len(portions)} 个材料份额各出现一次", passed))

    # R_JC: TIM contact + blade conduction from the three-dimensional solution
    grid = der["grid"]
    hs = sorted(grid, reverse=True)
    energy = max(abs(grid[h][k]["contact_flow_W"] - 1.0) for h in hs for k in ("gpu", "bus"))
    change = _rel(grid[hs[-1]]["gpu"]["baseplate_K"], grid[hs[-2]]["gpu"]["baseplate_K"])
    passed = energy <= 1e-8 and change <= CRIT["grid_change_max_rel"]
    ok.append(case_record.check(
        "步骤1 刀片三维导热解", f"热平衡误差 <= 1e-8 W/W, 最细两级网格的基板温升相对变化 <= {CRIT['grid_change_max_rel']}",
        "; ".join(f"{h * 1000:.1f} mm {grid[h]['gpu']['cells']} 单元 基板 {grid[h]['gpu']['baseplate_K']:.5f} K/W "
                  f"封装 {grid[h]['gpu']['package_K']:.5f} K/W 机身热 {grid[h]['bus']['baseplate_K']:.5f} K/W" for h in hs)
        + f"; 热平衡最大误差 {energy:.2e}; 相对变化 {change:.4f}", passed))
    hand_jc = der["length"] / (der["k_al"] * der["area_eff"]) + der["r_contact"]
    value = float(params.R_K_W[IP["JC"]])
    passed = _rel(value, hand_jc) <= CRIT["relative_tol_exact"] and _rel(der["r_cond"] + der["r_contact"], hand_jc) <= 1e-12
    ok.append(case_record.check(
        "步骤1 R_JC 按 T5 第二行",
        f"R_JC = l/(k A) + R_contact = {der['length']:.4f}/({der['k_al']} x {der['area_eff']:.6f}) + {der['r_contact']:.4e} "
        f"= {hand_jc:.6e} K/W; 导热部分为刀片三维解 {der['used']['gpu']['baseplate_K']:.5f} K/W 除以 12, 接触部分为导热垫 "
        f"{G.TIM_R_M2K_W} m2K/W 除以封装底面 {G.PKG_W * G.PKG_D:.5f} m2 再除以 12",
        f"模块 R_K_W[JC] = {value:.6e} K/W, 方法 {params.provenance['resistance']['JC']['method']}", passed))
    net = der["network"]
    value = float(params.R_K_W[IP["CR"]])
    seg = net["networks"]["Top_p"]
    per_net = ", ".join(f"{name} {item['R_net_K_W']:.5f}" for name, item in net["networks"].items())
    passed = _rel(value, net["R_CR_K_W"]) <= CRIT["relative_tol_exact"]
    ok.append(case_record.check(
        "步骤1 R_CR 按热管网络",
        f"R_CR = 四个热管网络平均热阻 / 4 = {net['R_CR_K_W']:.6e} K/W; 上方网络: 传输段 {seg['bundle_mean_rise_K_W']:.5f}, "
        f"连接段 {seg['R_connector_K_W']:.5f}, 集热管与分支热管及翅片 {seg['R_header_spreaders_fins_K_W']:.5f} K/W, "
        f"k_eff {net['k_eff_W_mK']:.6g} W/mK",
        f"模块 R_K_W[CR] = {value:.6e} K/W, 方法 {params.provenance['resistance']['CR']['method']}, "
        f"各网络 {per_net} K/W", passed))

    # radiator surfaces and optics
    rs = [s for s in params.surfaces if s.node_id == "R"]
    opt = G.OPT_WHITEPAINT
    passed = (len(rs) == 4 and all(abs(s.area_m2 - der["face_area"]) <= 1e-12 for s in rs)
              and all(s.absorptivity == opt["alpha"] and s.emissivity == opt["eps"] for s in rs)
              and sorted(round(float(s.normal_body[1])) for s in rs) == [-1, -1, 1, 1])
    ok.append(case_record.check(
        "步骤1 散热板表面与光学性质",
        f"四个面 {der['face_area']:.5f} m2, 法向 +Y 与 -Y, 吸收率 {opt['alpha']}, 发射率 {opt['eps']} 取自 geometry_spec OPT_WHITEPAINT",
        "; ".join(f"{s.surface_id} {s.area_m2:.5f} m2 n {tuple(float(v) for v in s.normal_body)} a {s.absorptivity} e {s.emissivity}"
                  for s in rs), passed))
    # decoupled auxiliary paths
    passed = all(float(params.R_K_W[IP[p]]) == BIG for p in ("SR", "BR", "DR"))
    ok.append(case_record.check(
        "步骤1 SR BR DR 测试配置", f"有限元无太阳翼支架导热, 无电池与独立电源设备: SR, BR, DR 取 {BIG:g} K/W, 按第 9.4 节记录",
        f"SR {params.R_K_W[IP['SR']]:g}, BR {params.R_K_W[IP['BR']]:g}, DR {params.R_K_W[IP['DR']]:g} K/W; "
        f"来源 {params.provenance['resistance']['SR']['source'][:80]}", passed))
    # every parameter has its source recorded
    prov = params.provenance
    sources = [p["source"] for node in NODE_ORDER for p in prov["capacitance"][node]["portions"]]
    sources += [prov["resistance"][p]["source"] for p in PATH_ORDER]
    sources += [prov["surfaces"][s]["source"] for s in prov["surfaces"]]
    passed = all(isinstance(s, str) and len(s) > 20 for s in sources) and "geometry_spec" in prov["resistance"]["CR"]["source"]
    ok.append(case_record.check(
        "步骤1 参数来源记录", "每个材料份额, 连接与表面在 provenance 中记录来源", f"{len(sources)} 条来源均已记录", passed))

    out.update({"C_J_K": {n: float(params.C_J_K[I[n]]) for n in NODE_ORDER},
                "R_K_W": {p: float(params.R_K_W[IP[p]]) for p in PATH_ORDER}})
    case_record.metric("parameters", {
        "masses_kg": {"packages": m["packages"]["mass_kg"], "blades": m["blades"]["mass_kg"], "bus": m["bus"]["mass_kg"],
                      "hp_transport": m["hp_transport"]["mass_kg"], "radiator_panels": m["radiator_panels"]["mass_kg"],
                      "hp_condenser": m["hp_condenser"]["mass_kg"], "wings": G.SOL_AREAL_KG_M2 * der["wing_area"]},
        "C_J_K": out["C_J_K"], "R_K_W": out["R_K_W"],
        "R_JC_parts_K_W": {"contact_TIM": der["r_contact"], "blade_conduction": der["r_cond"],
                           "effective_area_m2": der["area_eff"], "length_m": der["length"]},
        "blade_grid": {f"{h * 1000:.1f}mm": {"gpu_baseplate_K_W": grid[h]["gpu"]["baseplate_K"],
                                             "gpu_package_K_W": grid[h]["gpu"]["package_K"],
                                             "bus_baseplate_K_W": grid[h]["bus"]["baseplate_K"],
                                             "bus_spine_contact_K_W": grid[h]["bus"]["spine_contact_K"],
                                             "cells": grid[h]["gpu"]["cells"]} for h in hs},
        "R_CR_networks_K_W": {k: {kk: vv for kk, vv in v.items() if kk not in ("fins",)} for k, v in net["networks"].items()},
        "radiator_face_exposed_fraction": der["cover"]["exposed_fraction"],
        "R_DR_bus_sensitivity_K_W": der["r_dr_bus"],
    })
    assert all(ok), "step 1 checks failed"


# ------------------------------------------------------------------------------------------------ step 2


def test_step2_run_five_orbits(fe004, case_record):
    """Step 2: run five orbits with the same orbit, attitude and power history as the FE."""

    period, t_end, der, params = fe004["period"], fe004["t_end"], fe004["der"], fe004["params"]
    ok = []
    out = OUTCOME.setdefault("step2", {})
    sigma = sup.SIGMA_W_M2_K4
    for case in CASES:
        c = fe004["cases"][case]
        pr, tr, env = c["probes"], c["trace"], c["env"]
        tau_tr = tr["t_s"] - fe004["t0"]
        gpu_W, plat_W = c["power"]
        for label in ("main", "bus_D"):
            run = c["runs"][label]
            a = run["archive"]
            passed = (run["error"] is None and a.status == "completed" and abs(a.t_end_s - t_end) <= 1e-9
                      and len(a.range_warnings) == 0)
            ok.append(case_record.check(
                f"步骤2 {case} {label} 运行五圈", f"运行到 5 P = {t_end:.3f} s 完成, 无报错, 无温度范围警告",
                f"状态 {a.status}, 终点 {a.t_end_s:.3f} s, 报错 {run['error']}, 范围警告 {len(a.range_warnings)}, "
                f"已接受步 {a.statistics['accepted_steps']}, 拒绝步 {a.statistics['rejected_steps_total']}, "
                f"函数调用 {a.statistics['function_evaluations']}, 墙钟 {run['wall_s']:.1f} s", passed))
        a = c["runs"]["main"]["archive"]
        # power history equals the FE heat sources
        fe_t = pr["t_s"]
        mine = np.array([gpu_W(t) + plat_W(t) for t in fe_t])
        diff = float(np.max(np.abs(mine - pr["P_sources_W"])))
        arch_p = np.asarray(a.ports_W["P_load_W"])
        hand_p = np.array([gpu_W(t) + plat_W(t) for t in a.time_s])
        diff_a = float(np.max(np.abs(arch_p - hand_p)))
        passed = diff <= CRIT["power_match_W"] and diff_a <= 1e-9 * float(np.max(hand_p))
        ok.append(case_record.check(
            f"步骤2 {case} 功率时程与有限元相同",
            f"P_load_W = 12 x heat_per_gpu_w + heat_platform_w, 与有限元 P_sources_W 在 {len(fe_t)} 个输出时刻相差 <= "
            f"{CRIT['power_match_W']} W; 归档 P_load_W 等于给定时程",
            f"最大差 {diff:.2e} W; 归档最大差 {diff_a:.2e} W; 第四、五圈平均 {sup.window_mean(fe_t, pr['P_sources_W'], 3 * period, 5 * period):.1f} W; "
            f"声明的功率阶跃 {len(c['bounds'])} 个", passed))
        # orbit and attitude: module incidence cosines against the OrbitWiz body-frame Sun components
        idx = _check_indices(a, period)
        worst_cos, worst_r = 0.0, 0.0
        sid = [s.surface_id for s in params.surfaces]
        for k in idx:
            t = float(a.time_s[k])
            sample = c["runs"]["main"]["provider"].sample(t)
            cosines = np.asarray(sample.surface_environment["cos_incidence"])
            sb = np.array([np.interp(t, tau_tr, tr[f"sun_body_{ax}"]) for ax in "xyz"])
            for s, value in zip(params.surfaces, cosines):
                worst_cos = max(worst_cos, abs(float(value) - float(np.asarray(s.normal_body) @ sb)))
            r_teme = np.array([np.interp(t, tau_tr, tr[f"r_eci_{ax}_km"]) for ax in "xyz"]) * 1e3
            worst_r = max(worst_r, _rel(float(np.linalg.norm(sample.orbit_input["position_m"])), float(np.linalg.norm(r_teme))))
        passed = worst_cos <= CRIT["incidence_tol"] and worst_r <= 1e-6
        ok.append(case_record.check(
            f"步骤2 {case} 轨道与姿态与有限元相同",
            f"{len(idx)} 个时刻 {len(sid)} 个表面的入射余弦等于 OrbitWiz 本体系太阳分量, 差 <= {CRIT['incidence_tol']}; "
            "GCRS 位置模长等于 TEME 轨迹模长, 相对差 <= 1e-6",
            f"入射余弦最大差 {worst_cos:.2e}; 位置模长最大相对差 {worst_r:.2e}", passed))
        # eclipse boundaries: module against the independent bisection and against the FE events
        mod_ev = [(b.time_s, "entry" if b.is_eclipse_entry else "exit") for b in a.eclipse_boundaries]
        ref_ev = [ev for ev in env.shadow_boundaries(10.0) if 0.0 < ev[0] < t_end]
        fe_ev = [ev for ev in _fe_events(pr) if 0.0 < ev[0] < t_end]
        d_ref = max(abs(x[0] - y[0]) for x, y in zip(mod_ev, ref_ev)) if len(mod_ev) == len(ref_ev) else math.inf
        d_fe = [x[0] - y[0] for x, y in zip(mod_ev, fe_ev)] if len(mod_ev) == len(fe_ev) else []
        kinds = len(mod_ev) == len(fe_ev) and all(x[1] == y[1] for x, y in zip(mod_ev, fe_ev))
        passed = (d_ref <= CRIT["eclipse_reference_tol_s"] and kinds and d_fe
                  and max(abs(v) for v in d_fe) <= CRIT["fe_eclipse_resolution_s"])
        ok.append(case_record.check(
            f"步骤2 {case} 日食进出时刻",
            f"模块日食边界与独立二分结果相差 <= {CRIT['eclipse_reference_tol_s']} s; 与有限元事件次数与类型相同, 时刻差不超过有限元的日食分辨率 "
            f"{CRIT['fe_eclipse_resolution_s']} s ({CRIT['fe_eclipse_resolution_source']})",
            f"模块 {len(mod_ev)} 个边界, 与独立二分最大差 {d_ref:.2e} s; 有限元 {len(fe_ev)} 个事件; 模块减有限元 "
            + ", ".join(f"{v:+.2f}" for v in d_fe) + " s", bool(passed)))
        # surface environment of R and S against the independent T4 with the Earth-centred quadrature
        rq = CFG["reference_quadrature"]
        worst_env = {"S": 0.0, "R": 0.0}
        for k in idx:
            t = float(a.time_s[k])
            r = env.position(t)
            axes = env.body_axes(t)
            sun_hat = env.sun_unit(t)
            sb = np.array([np.interp(t, tau_tr, tr[f"sun_body_{ax}"]) for ax in "xyz"])
            G_t = c["S_sun"] * env.illumination(t)
            q_ref = {"S": 0.0, "R": 0.0}
            for s in params.surfaces:
                n_body = np.asarray(s.normal_body, dtype=float)
                F, Fa = sup.earth_plate_factors(r, axes @ n_body, sun_hat, ENVCFG["earth_radius_m"], rq["n_psi"], rq["n_phi"])
                g_sun = G_t * max(0.0, float(n_body @ sb))
                q_ref[s.node_id] += s.area_m2 * (s.absorptivity * (g_sun + ENVCFG["albedo"] * c["S_sun"] * Fa)
                                                 + s.emissivity * ENVCFG["olr_W_m2"] * F)
            for node, j in (("S", 0), ("R", 1)):
                worst_env[node] = max(worst_env[node], _rel(float(a.Q_env_W[k, j]), q_ref[node]))
        passed = max(worst_env.values()) <= CRIT["env_tol_rel"]
        ok.append(case_record.check(
            f"步骤2 {case} 环境吸热按 T4",
            f"{len(idx)} 个输出时刻 Q_env 与独立 T4 计算相对差 <= {CRIT['env_tol_rel']}: 直射用 OrbitWiz 本体系太阳分量, 反照与红外用地心积分",
            f"太阳能板最大相对差 {worst_env['S']:.2e}, 散热板最大相对差 {worst_env['R']:.2e}", passed))
        # heat flows, emission and derivatives at the archived samples against hand T2, T3, T4
        C_hand = der["capacitance"]
        R_hand = der["resistance"]
        w_flow = w_emit = w_der = 0.0
        for k in idx:
            T = np.asarray(a.temperature_K[k])
            q_hand = {p: (T[I[p[0]]] - T[I[p[1]]]) / R_hand[p] for p in PATH_ORDER}
            for p in PATH_ORDER:
                w_flow = max(w_flow, abs(float(a.q_W[k, IP[p]]) - q_hand[p]) / max(1.0, abs(q_hand[p])))
            emit = {"S": 0.0, "R": 0.0}
            for s in params.surfaces:
                emit[s.node_id] += s.emissivity * sigma * s.area_m2 * T[I[s.node_id]] ** 4
            for node, j in (("S", 0), ("R", 1)):
                w_emit = max(w_emit, _rel(float(a.Q_emit_W[k, j]), emit[node]))
            ports = {name: float(a.ports_W[name][k]) for name in ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")}
            env_q = {"S": float(a.Q_env_W[k, 0]), "R": float(a.Q_env_W[k, 1])}
            net_W = {
                "S": env_q["S"] - ports["P_pv_W"] - q_hand["SR"] - emit["S"],
                "J": ports["P_load_W"] - q_hand["JC"],
                "C": q_hand["JC"] - q_hand["CR"],
                "B": ports["Q_B_W"] - q_hand["BR"],
                "D": ports["Q_D_W"] - q_hand["DR"],
                "R": q_hand["SR"] + q_hand["CR"] + q_hand["BR"] + q_hand["DR"] + env_q["R"] - emit["R"],
            }
            for node in NODE_ORDER:
                hand = net_W[node] / C_hand[node]
                scale = max(abs(hand), 1e-9)
                w_der = max(w_der, abs(float(a.dT_dt_K_s[k, I[node]]) - hand) / scale)
        passed = w_flow <= 1e-12 and w_emit <= CRIT["relative_tol_exact"] and w_der <= CRIT["derivative_tol_rel"]
        ok.append(case_record.check(
            f"步骤2 {case} 热流, 表面辐射与温度导数",
            f"{len(idx)} 个输出时刻: q 与手算 T2 相对差 <= 1e-12, Q_emit 与手算 T4 相对差 <= 1e-12, dT/dt 与手算 T3 相对差 <= "
            f"{CRIT['derivative_tol_rel']}",
            f"热流 {w_flow:.2e}, 表面辐射 {w_emit:.2e}, 温度导数 {w_der:.2e}", passed))
        out[case] = {"eclipse_minus_fe_s": d_fe, "power_diff_W": diff, "incidence_diff": worst_cos,
                     "env_rel": worst_env, "wall_s": {k: v["wall_s"] for k, v in c["runs"].items()},
                     "statistics": {k: {kk: vv for kk, vv in v["archive"].statistics.items()
                                        if isinstance(vv, (int, float))} for k, v in c["runs"].items()}}
    case_record.metric("run", out)
    assert all(ok), "step 2 checks failed"


# ------------------------------------------------------------------------------------------------ step 3


def _orbit_means(fe004, case: str) -> dict:
    c = fe004["cases"][case]
    pr, tr = c["probes"], c["trace"]
    period = fe004["period"]
    t = pr["t_s"]
    st = c["runs"]["main"]["archive"].state_at(t)
    st_d = c["runs"]["bus_D"]["archive"].state_at(t)
    node = np.interp(t, tr["t_s"] - fe004["t0"], tr["T_struct_c"]) + 273.15
    dense_t = np.arange(0.0, fe004["t_end"], 10.0)
    dense = c["runs"]["main"]["archive"].state_at(dense_t)
    res = {}
    for orbit in ORBITS:
        lo, hi = _orbit_window(period, orbit)
        wm = lambda x: sup.window_mean(t, x, lo, hi)  # noqa: E731
        sel = (dense_t >= lo) & (dense_t <= hi)
        res[orbit] = {
            "fe_baseplate_K": wm(pr["baseplate_mean_K"]), "fe_radiator_K": wm(pr["rad_mean_K"]),
            "fe_bus_K": wm(pr["bus_mean_K"]), "fe_blades_K": wm(pr["blades_mean_K"]), "fe_packages_K": wm(pr["pkg_mean_K"]),
            "fe_wing_K": wm(pr["wing_mean_K"]), "orbitwiz_node_K": wm(node),
            "J_K": wm(st[:, I["J"]]), "C_K": wm(st[:, I["C"]]), "R_K": wm(st[:, I["R"]]), "S_K": wm(st[:, I["S"]]),
            "J_dense_K": float(np.mean(dense[sel, I["J"]])), "R_dense_K": float(np.mean(dense[sel, I["R"]])),
            "busD_J_K": wm(st_d[:, I["J"]]), "busD_R_K": wm(st_d[:, I["R"]]), "busD_D_K": wm(st_d[:, I["D"]]),
        }
    lo, hi = 3 * period, 5 * period
    res["report_window"] = {"orbitwiz_node_C": sup.sample_mean(t, node, lo, hi) - 273.15,
                            "fe_baseplate_C": sup.sample_mean(t, pr["baseplate_mean_K"], lo, hi) - 273.15}
    return res


def test_step3_compare_orbits_4_5(fe004, case_record):
    """Step 3 and acceptance: GPU baseplate and radiator means of orbits 4 and 5 within 5 K; expected results."""

    ok = []
    out = OUTCOME.setdefault("step3", {})
    for case in CASES:
        res = _orbit_means(fe004, case)
        out[case] = res
        label = CFG["cases"][case]["label_cn"]
        for orbit in ORBITS:
            r = res[orbit]
            d_j = r["J_K"] - r["fe_baseplate_K"]
            d_r = r["R_K"] - r["fe_radiator_K"]
            ok.append(case_record.check(
                f"验收 {case} 第{orbit}圈 GPU 基板平均温度",
                f"{label} 第{orbit}圈计算节点平均温度与有限元 GPU 基板平均温度之差绝对值 <= {ACCEPT_K} K",
                f"模块 T_J {r['J_K'] - 273.15:.2f} °C, 有限元基板 {r['fe_baseplate_K'] - 273.15:.2f} °C, 差 {d_j:+.2f} K "
                f"(10 s 稠密平均 T_J {r['J_dense_K'] - 273.15:.2f} °C)", abs(d_j) <= ACCEPT_K))
            ok.append(case_record.check(
                f"验收 {case} 第{orbit}圈散热板平均温度",
                f"{label} 第{orbit}圈散热板平均温度与有限元散热板面积加权平均温度之差绝对值 <= {ACCEPT_K} K",
                f"模块 T_R {r['R_K'] - 273.15:.2f} °C, 有限元散热板 {r['fe_radiator_K'] - 273.15:.2f} °C, 差 {d_r:+.2f} K "
                f"(10 s 稠密平均 T_R {r['R_dense_K'] - 273.15:.2f} °C)", abs(d_r) <= ACCEPT_K))
        for orbit in ORBITS:
            r = res[orbit]
            d_mod = r["J_K"] - r["R_K"]
            d_fe = r["fe_baseplate_K"] - r["fe_radiator_K"]
            ok.append(case_record.check(
                f"预期 {case} 第{orbit}圈计算设备到散热板温差",
                f"链路复现计算设备与散热板之间的温差: 模块 T_J - T_R 与有限元基板减散热板之差绝对值 <= {ACCEPT_K} K "
                "(与验收判据相同的容差)",
                f"模块 {d_mod:.2f} K, 有限元 {d_fe:.2f} K, 差 {d_mod - d_fe:+.2f} K", abs(d_mod - d_fe) <= ACCEPT_K))
        rw = res["report_window"]
        below = rw["fe_baseplate_C"] - rw["orbitwiz_node_C"]
        lo_c, hi_c = CRIT["single_node_range_C"]
        prec = CRIT["single_node_precision_C"]
        ok.append(case_record.check(
            f"预期 {case} 单节点模型比 GPU 基板低 12 至 15 °C",
            f"第四、五圈 OrbitWiz 单节点平均温度比有限元 GPU 基板低 {lo_c:.0f} 至 {hi_c:.0f} °C, 按整数精度判断 "
            f"({CRIT['single_node_source']})",
            f"单节点 {rw['orbitwiz_node_C']:.2f} °C, 基板 {rw['fe_baseplate_C']:.2f} °C, 低 {below:.2f} °C",
            lo_c <= below <= hi_c))
    case_record.metric("orbit_means_K", {case: {str(k): v for k, v in out[case].items()} for case in CASES})
    failed = [c["name"] for c in case_record.checks if c["name"].startswith("验收") and not c["passed"]]
    assert all(ok), f"FE-004 acceptance or expected-result checks failed: {failed}"


# ------------------------------------------------------------------------------------------------ bus and diagnostics


def test_bus_representation_and_heat_paths(fe004, case_record):
    """How the FE bus is represented and its effect; FE energy budget that explains the differences."""

    der = fe004["der"]
    period = fe004["period"]
    m = der["masses"]
    cpa = der["cp_al"]
    caps = {"bus": m["bus"]["mass_kg"] * cpa, "blades": m["blades"]["mass_kg"] * cpa,
            "packages": m["packages"]["mass_kg"] * cpa, "transport": m["hp_transport"]["mass_kg"] * cpa,
            "radiator": (m["radiator_panels"]["mass_kg"] + m["hp_condenser"]["mass_kg"]) * cpa}
    r_chain = der["resistance"]["JC"] + der["resistance"]["CR"]
    ok = []
    out = OUTCOME.setdefault("bus", {})
    for case in CASES:
        res = OUTCOME["step3"][case] if case in OUTCOME.get("step3", {}) else _orbit_means(fe004, case)
        c = fe004["cases"][case]
        pr = c["probes"]
        a = c["runs"]["main"]["archive"]
        out[case] = {}
        for orbit in ORBITS:
            r = res[orbit]
            lo, hi = _orbit_window(period, orbit)
            budget = sup.fe_energy_budget(pr, lo, hi, der["cover"]["exposed_fraction"], caps)
            sel = (a.time_s >= lo) & (a.time_s <= hi)
            q_emit_r = float(np.mean(a.Q_emit_W[sel, 1]))
            q_env_r = float(np.mean(a.Q_env_W[sel, 1]))
            q_cr = float(np.mean(a.q_W[sel, IP["CR"]]))
            # first-order effect of the FE heat that leaves through other surfaces, if it did not pass R and the chain
            dTR = -budget["heat_other_surfaces_W"] * r["R_K"] / (4.0 * q_emit_r)
            dTJ = dTR - budget["heat_other_surfaces_W"] * r_chain
            out[case][orbit] = {
                "fe_budget": budget, "module_Q_emit_R_W": q_emit_r, "module_Q_env_R_W": q_env_r, "module_q_CR_W": q_cr,
                "module_chain_resistance_K_W": r_chain,
                "estimate_without_other_surfaces": {"dT_R_K": dTR, "dT_J_K": dTJ,
                                                    "J_minus_baseplate_K": r["J_K"] - r["fe_baseplate_K"] + dTJ,
                                                    "R_minus_radiator_K": r["R_K"] - r["fe_radiator_K"] + dTR},
                "bus_on_J": {"J_minus_baseplate_K": r["J_K"] - r["fe_baseplate_K"], "R_minus_radiator_K": r["R_K"] - r["fe_radiator_K"],
                             "J_minus_fe_bus_K": r["J_K"] - r["fe_bus_K"]},
                "bus_on_D": {"J_minus_baseplate_K": r["busD_J_K"] - r["fe_baseplate_K"],
                             "R_minus_radiator_K": r["busD_R_K"] - r["fe_radiator_K"],
                             "D_minus_fe_bus_K": r["busD_D_K"] - r["fe_bus_K"]},
            }
        # evidence for the exposed-face correction: FE infrared probe against the unobstructed whole-face value
        env = c["env"]
        rq = CFG["reference_quadrature"]
        lo, hi = 3 * period, 5 * period
        times = np.linspace(lo, hi, 25)
        unob = []
        for t in times:
            axes = env.body_axes(float(t))
            r_pos = env.position(float(t))
            total = 0.0
            for ny in (1.0, -1.0):
                F, _ = sup.earth_plate_factors(r_pos, axes @ np.array([0.0, ny, 0.0]), env.sun_unit(float(t)),
                                               ENVCFG["earth_radius_m"], rq["n_psi"] // 3, rq["n_phi"] // 3)
                total += 2 * der["face_area"] * fe004["G"].OPT_WHITEPAINT["eps"] * ENVCFG["olr_W_m2"] * F
            unob.append(total)
        fe_ir = sup.window_mean(pr["t_s"], pr["abs_IR_rad_faces_W"], lo, hi)
        out[case]["ir_probe_coverage"] = {"fe_probe_IR_W": fe_ir, "unobstructed_whole_faces_IR_W": float(np.mean(unob)),
                                          "ratio": fe_ir / float(np.mean(unob)),
                                          "exposed_fraction": der["cover"]["exposed_fraction"],
                                          "fe_planet_discretisation_IR_change": -0.015}
        o4, o5 = out[case][4], out[case][5]
        ok.append(case_record.check(
            f"机身表示 {case} 机身并入计算节点与改为电源设备节点的影响",
            "两种表示均完成五圈运行; 记录第四、五圈计算节点与散热板相对有限元的差",
            "; ".join(f"第{k}圈 并入J: J {v['bus_on_J']['J_minus_baseplate_K']:+.2f} K, R {v['bus_on_J']['R_minus_radiator_K']:+.2f} K, "
                      f"J 比有限元机身 {v['bus_on_J']['J_minus_fe_bus_K']:+.2f} K; 改为D: J {v['bus_on_D']['J_minus_baseplate_K']:+.2f} K, "
                      f"R {v['bus_on_D']['R_minus_radiator_K']:+.2f} K, D 比有限元机身 {v['bus_on_D']['D_minus_fe_bus_K']:+.2f} K"
                      for k, v in ((4, o4), (5, o5))),
            c["runs"]["main"]["error"] is None and c["runs"]["bus_D"]["error"] is None))
    case_record.metric("bus_and_heat_paths", {case: {str(k): v for k, v in out[case].items()} for case in CASES})
    assert all(ok)


# ------------------------------------------------------------------------------------------------ evidence


def _series(fe004) -> dict:
    series = {"case_id": "FE-004",
              "description": "Module (thermal-only coupled run) and COMSOL whole-satellite time histories; tau = 0 at "
                             "the FE hot instant; FE samples at the probe output times, module states on the accepted "
                             "solution at the same times and on the 60 s output grid",
              "node_order": list(NODE_ORDER), "path_order": list(PATH_ORDER), "units": "K, W, s",
              "period_s": fe004["period"], "t0_hot_s": fe004["t0"], "cases": {}}
    for case in CASES:
        c = fe004["cases"][case]
        pr, tr = c["probes"], c["trace"]
        t = pr["t_s"]
        main = c["runs"]["main"]["archive"]
        bus_d = c["runs"]["bus_D"]["archive"]
        st = main.state_at(t)
        st_d = bus_d.state_at(t)
        series["cases"][case] = {
            "gpu": c["cfg"]["gpu"], "epoch_utc": c["env"].epoch.isoformat(), "solar_irradiance_W_m2": c["S_sun"],
            "initial_temperature_K": c["t_init"],
            "fe": {k: [float(v) for v in pr[k]] for k in ("t_s", "rad_mean_K", "rad_max_K", "baseplate_mean_K",
                                                         "pkg_mean_K", "blades_mean_K", "bus_mean_K", "wing_mean_K",
                                                         "P_sources_W", "illum", "emitted_rad_W")},
            "orbitwiz_single_node_K": [float(v) for v in np.interp(t, tr["t_s"] - fe004["t0"], tr["T_struct_c"]) + 273.15],
            "module_at_fe_times": {f"T_{n}_K": [float(v) for v in st[:, I[n]]] for n in NODE_ORDER},
            "module_bus_on_D_at_fe_times": {f"T_{n}_K": [float(v) for v in st_d[:, I[n]]] for n in ("J", "C", "D", "R")},
            "module_output": {
                "time_s": [float(v) for v in main.time_s],
                "temperature_K": np.asarray(main.temperature_K).round(6).tolist(),
                "q_W": np.asarray(main.q_W)[:, [IP["JC"], IP["CR"]]].round(4).tolist(), "q_paths": ["JC", "CR"],
                "Q_env_R_W": np.asarray(main.Q_env_W)[:, 1].round(4).tolist(),
                "Q_emit_R_W": np.asarray(main.Q_emit_W)[:, 1].round(4).tolist(),
                "P_load_W": np.asarray(main.ports_W["P_load_W"]).round(4).tolist(),
                "G_W_m2": np.asarray(main.environment["G_W_m2"]).round(4).tolist(),
            },
            "eclipse_boundaries_s": [float(b.time_s) for b in main.eclipse_boundaries],
            "solver_settings": dict(main.solver_settings),
        }
    return series


def test_zz_evidence_and_summary(fe004, case_record):
    """Write the time histories and the Chinese summary of the case."""

    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "FE-004_series.json"
    path.write_text(json.dumps(_series(fe004), ensure_ascii=False, default=float), encoding="utf-8")
    der = fe004["der"]
    s3 = OUTCOME.get("step3") or {case: _orbit_means(fe004, case) for case in CASES}
    bus = OUTCOME.get("bus", {})
    s2 = OUTCOME.get("step2", {})
    n = sup.cn_number

    def d(case, orbit, key_mod, key_fe):
        return s3[case][orbit][key_mod] - s3[case][orbit][key_fe]

    def span(values, digits=1, unit="K"):
        lo_v, hi_v = min(values), max(values)
        sep = "" if unit == "%" else " "
        if n(lo_v, digits) == n(hi_v, digits):
            return f"{n(lo_v, digits)}{sep}{unit}"
        return f"{n(lo_v, digits)}{sep}{unit} 至 {n(hi_v, digits)}{sep}{unit}"

    def upper(value, digits=1):
        """Bound for a statement of the form 不超过 x: rounded up, never below the value."""

        scale = 10 ** digits
        return n(math.ceil(value * scale - 1e-9) / scale, digits)

    def word(v):
        return f"高 {n(v)} K" if v >= 0 else f"低 {n(-v)} K"

    cap = der["capacitance"]
    parts = [
        "按整星有限元模型的几何、材料、导热垫与热管参数，用式 T5 装配计算节点、冷板与公共散热板。整星模型的机身在设计报告的热网络中没有"
        "对应组件，本用例把机身质量与 570 W 平台热量并入计算节点。"
        f"计算节点由 12 个 GPU 封装、12 块刀片与机身组成，热容 {n(cap['J'] / 1e3)} kJ/K；冷板为 4 束传热热管与 4 段连接热管，"
        f"热容 {n(cap['C'] / 1e3)} kJ/K；公共散热板为两块板与板面上的集管热管和分支热管，热容 {n(cap['R'] / 1e3)} kJ/K，"
        f"四个板面共 {n(4 * der['face_area'], 3)} m²，吸收率 0.25，发射率 0.85。R_JC 为 {n(der['resistance']['JC'], 5)} K/W，"
        f"由导热垫接触热阻与刀片三维稳态导热解组成；R_CR 为 {n(der['resistance']['CR'], 5)} K/W，由热管各段按式 T5 计算的热阻与"
        "散热板翅片导热组成。"]
    ecl = [v for case in CASES for v in s2.get(case, {}).get("eclipse_minus_fe_s", [])]
    if ecl and all(v < 0 for v in ecl):
        ecl_txt = f"日食进出时刻比有限元早 {span([abs(v) for v in ecl], 1, 's')}，"
    elif ecl:
        ecl_txt = f"日食进出时刻与有限元相差不超过 {upper(max(abs(v) for v in ecl))} s，"
    else:
        ecl_txt = ""
    s_wing = [abs(s3[case][o]["S_K"] - s3[case][o]["fe_wing_K"]) for case in CASES for o in ORBITS]
    parts.append(
        f"以与有限元相同的轨道、姿态与 1 s 功率时程运行五圈，{ecl_txt}环境吸热、热流与温度导数与独立手算一致，"
        f"与散热板脱开的太阳能板平均温度与有限元太阳能板相差不超过 {upper(max(s_wing), 2)} K。")
    for case in CASES:
        lab = CFG["cases"][case]["label_cn"]
        dj = [d(case, o, "J_K", "fe_baseplate_K") for o in ORBITS]
        dr = [d(case, o, "R_K", "fe_radiator_K") for o in ORBITS]
        dm = [s3[case][o]["J_K"] - s3[case][o]["R_K"] for o in ORBITS]
        dfe = [s3[case][o]["fe_baseplate_K"] - s3[case][o]["fe_radiator_K"] for o in ORBITS]
        verdict = ("，均超过 5 K 的验收判据" if all(abs(v) > ACCEPT_K for v in dj + dr)
                   else "，验收判据为 5 K")
        parts.append(
            f"{lab} 算例第四、五圈计算节点平均温度比有限元 GPU 基板分别{word(dj[0])} 与{word(dj[1])}，散热板平均温度比有限元"
            f"分别{word(dr[0])} 与{word(dr[1])}{verdict}；计算节点与散热板之差为 {n(dm[0])} K 与 {n(dm[1])} K，有限元基板与散热板"
            f"之差为 {n(dfe[0])} K 与 {n(dfe[1])} K。")
    if bus:
        other = [bus[case][o]["fe_budget"]["heat_other_surfaces_W"] for case in CASES for o in ORBITS]
        share = [100.0 * bus[case][o]["fe_budget"]["heat_other_surfaces_W"] / bus[case][o]["fe_budget"]["P_sources_W"]
                 for case in CASES for o in ORBITS]
        r_fe = [bus[case][o]["fe_budget"]["chain_resistance_K_W"] for case in CASES for o in ORBITS]
        r_mod = der["resistance"]["JC"] + der["resistance"]["CR"]
        dev = [100.0 * abs(r_mod - v) / v for v in r_fe]
        est = [bus[case][o]["estimate_without_other_surfaces"] for case in CASES for o in ORBITS]
        shift = [bus[case][o]["bus_on_D"]["J_minus_baseplate_K"] - bus[case][o]["bus_on_J"]["J_minus_baseplate_K"]
                 for case in CASES for o in ORBITS]
        shift_r = [bus[case][o]["bus_on_D"]["R_minus_radiator_K"] - bus[case][o]["bus_on_J"]["R_minus_radiator_K"]
                   for case in CASES for o in ORBITS]
        left_r = [bus[case][o]["bus_on_D"]["R_minus_radiator_K"] for case in CASES for o in ORBITS]
        parts.append(
            f"有限元能量收支在扣除四个散热板主表面后仍有 {span(other, 0, 'W')} 的剩余项，占热源的 {span(share, 0, '%')}。"
            "该剩余项同时包含散热板侧面、集管与分支热管外表面，以及机身、刀片与封装等未纳入这四个主表面的贡献。"
            "这些表面分别属于不同节点，现有导出数据不能分离各自热量。因而不能把整个剩余项归因于计算节点与冷板没有外露表面，"
            "也不能用整个剩余项修正计算节点温度或认定热阻已得到验证。"
            f"当前装配的 R_JC 加 R_CR 为 {n(r_mod, 5)} K/W。有限元与集总模型的表面范围不完全一致，"
            "需要在相同表面范围下重新比较后才能确认偏差的主因。")
        parts.append(
            "机身并入计算节点时，其平台热量与有限元一样经 JC 与 CR 传到散热板；改由电源设备节点经单独的 DR 连接表示时，计算节点降低 "
            f"{span([-v for v in shift])}，散热板升高 {span(shift_r)}，仍比有限元高 {span(left_r)}。")
    case_record.summary("".join(parts))

    failed = [c for c in case_record.checks if not c["passed"]]
    if not failed:
        case_record.anomalies("无")
    else:
        lines = []
        n_accept = 0
        for case in CASES:
            lab = CFG["cases"][case]["label_cn"]
            for orbit in ORBITS:
                dj = d(case, orbit, "J_K", "fe_baseplate_K")
                dr = d(case, orbit, "R_K", "fe_radiator_K")
                bad = []
                if abs(dj) > ACCEPT_K:
                    bad.append(f"计算节点平均温度比 GPU 基板{word(dj)}")
                    n_accept += 1
                if abs(dr) > ACCEPT_K:
                    bad.append(f"散热板平均温度比有限元{word(dr)}")
                    n_accept += 1
                if bad:
                    lines.append(f"{lab} 算例第{'四' if orbit == 4 else '五'}圈" + "，".join(bad) + "。")
        if n_accept:
            lines.append(f"以上 {n_accept} 项均超过 5 K 的验收判据。")
        function_failures = [c["name"] for c in failed if c["name"].endswith((" call", " setup", " teardown"))]
        other_names = [c["name"] for c in failed if not c["name"].startswith("验收") and c["name"] not in function_failures]
        if function_failures and n_accept:
            lines.append("步骤 3 的测试函数在记录上述验收检查后以断言失败结束，这一项是验收未通过的结果。")
        elif function_failures:
            lines.append("测试函数异常结束：" + "，".join(function_failures) + "。")
        if other_names:
            lines.append("其余未通过的检查为 " + "，".join(other_names) + "。")
        if bus:
            other = [bus[case][o]["fe_budget"]["heat_other_surfaces_W"] for case in CASES for o in ORBITS]
            lines.append(
                f"有限元能量收支中四个散热板主表面以外的剩余项为 {span(other, 0, 'W')}，包含多个节点的表面贡献。"
                "目前只确认两种模型的表面范围不同，尚未分离各表面对温差的贡献，不能据此排除实现或参数装配问题。"
                "式 T2、T3 与 T4 的独立手算检查通过，整星温度验收仍未通过。")
        case_record.anomalies("".join(lines))
    case_record.metric("series_file", str(path.relative_to(THERMAL_DIR)).replace("\\", "/"))
    assert path.exists()
