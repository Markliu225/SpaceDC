"""FE-002 散热板节点有限元对标: common radiator node R against the ISS FE EATCS radiators.

Case FE-002 of the Chinese test report (CASES['FE-002'] in Thermal/test_report/build_test_report_cn.py), design basis
section 4.3 T3 line 6, section 4.4 T4, section 4.5 T5 and chapter 10 of the thermal design report.

The real module runs: ``thermal_derivative`` through ``sdtwin_sim.coupled.run_coupled`` with the Earth albedo and
infrared of ``sdtwin_sim.earth_flux``, one run per FE case (cold0, nom0, hot75) and loop (A, B). The precondition of the
case replaces q_SR + q_CR + q_BR + q_DR by the FE radiator heat input Qrad: the input enters through the D node
(Q_D_W equal to the FE input, C_D = 100 J/K, R_DR = 1e-4 K/W) while SR, JC, CR and BR take 1e12 K/W; the test
verifies that the heat reaching R equals the FE input within 0.1 percent. The radiator surfaces follow the FE pointing
law (edge to the Sun in sunlight, front face to nadir in the Earth shadow). The references are the FE results
(external data), the FE parameter table, hand calculations and an independent implementation of T4 and of T3 line 6
in tests/data/fe_002/fe002_support.py; nothing is compared with the module's own output.

Steps of the case:
1. drive the radiator node with the FE heat input from the FE initial temperature over the FE span of three orbits
   (0 to 16560 s), split at the eclipse boundaries;
2. take the third orbit (the exact last orbital period) and compare with the mean of the panel mean temperatures of
   the three radiator ORUs of the loop; acceptance: third-orbit mean difference at most 5 K for both loops and all
   three cases;
3. record the difference between the coldest FE panel and the FE radiator mean at the same instant.
"""

from __future__ import annotations

import importlib.util
import json
import math
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from sdtwin_sim import coupled as cp
from thermal import ThermalState, assemble_thermal_parameters

pytestmark = pytest.mark.case("FE-002")

TESTS_DIR = Path(__file__).resolve().parent
THERMAL_DIR = TESTS_DIR.parent
DATA_DIR = TESTS_DIR / "data" / "fe_002"
RESULTS_DIR = TESTS_DIR / "results"
SERIES_FILE = RESULTS_DIR / "FE-002_series.json"
CONFIG = json.loads((DATA_DIR / "fe002_config.json").read_text(encoding="utf-8"))
CASES = ("cold0", "nom0", "hot75")
LOOPS = ("A", "B")
KELVIN = 273.15
# Paths whose second node is R in T3 line 6 (design 4.3): q_SR + q_CR + q_BR + q_DR enter the radiator.
R_PATHS = ("SR", "CR", "BR", "DR")
LEAK_PATHS = ("SR", "CR", "BR")


def _load_support():
    spec = importlib.util.spec_from_file_location("fe002_support", DATA_DIR / "fe002_support.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUP = _load_support()
num = SUP.num
sci = SUP.sci


# ------------------------------------------------------------------------------------------------------ configuration


def radiator_geometry(cfg: dict) -> dict:
    """Hand calculation of the radiator loop inputs from the FE geometry and materials (T5)."""

    rad = cfg["radiator"]
    wing = abs(rad["wing_tip_x_m"] - rad["wing_root_x_m"])
    panel_length = (wing - (rad["panels_per_oru"] - 1) * rad["panel_gap_m"]) / rad["panels_per_oru"]
    panels = rad["orus_per_loop"] * rad["panels_per_oru"]
    area = panels * rad["panel_width_m"] * panel_length
    panel_mass = area * rad["panel_areal_density_kg_m2"]
    nh3_capacity = panels * rad["nh3_capacity_per_panel_J_K"]
    nh3_mass = nh3_capacity / rad["nh3_cp_J_kgK"]
    capacity = panel_mass * rad["panel_cp_J_kgK"] + nh3_capacity
    return {"wing_length_m": wing, "panel_length_m": panel_length, "panels": panels, "area_m2": area,
            "panel_mass_kg": panel_mass, "panel_capacity_J_K": panel_mass * rad["panel_cp_J_kgK"],
            "nh3_capacity_J_K": nh3_capacity, "nh3_mass_kg": nh3_mass, "capacity_J_K": capacity}


def build_network(cfg: dict, case_cfg: dict, geo: dict) -> tuple[list, list]:
    """Components and connections of the six-node network for one case (the radiator optics depend on the case)."""

    rad, inj, aux = cfg["radiator"], cfg["injection"], cfg["auxiliary_nodes"]
    aux_range = list(aux["temperature_range_K"])

    def component(instance_id, node, materials, surfaces=(), ports=(), temperature_range=aux_range,
                  asset_id=None, asset_version="fe002-1"):
        return {"instance_id": instance_id, "node_id": node, "asset_id": asset_id or f"fe002_{instance_id.lower()}",
                "asset_version": asset_version, "materials": materials, "surfaces": list(surfaces),
                "temperature_range_K": list(temperature_range), "ports": list(ports)}

    def material(material_id, mass, cp_value, source):
        return {"material_id": material_id, "mass_kg": mass, "cp_J_kgK": cp_value, "source": source}

    def surface(surface_id, normal, area, alpha, eps, source):
        return {"surface_id": surface_id, "area_m2": area, "normal_body": list(normal), "absorptivity": alpha,
                "emissivity": eps, "source": source}

    sa = aux["solar_array"]
    components = [
        component("SolarArray01", "S", [material("SolarArray01_auxiliary", sa["mass_kg"], sa["cp_J_kgK"], aux["source"])],
                  [surface("SolarArray01_front", (0.0, 0.0, 1.0), sa["area_m2"], sa["absorptivity"], sa["emissivity"],
                           aux["source"]),
                   surface("SolarArray01_back", (0.0, 0.0, -1.0), sa["area_m2"], sa["absorptivity"], sa["emissivity"],
                           aux["source"])],
                  ["P_pv_W"]),
    ]
    for item in aux["components"]:
        components.append(component(item["instance_id"], item["node_id"],
                                    [material(f"{item['instance_id']}_auxiliary", item["mass_kg"], item["cp_J_kgK"],
                                              aux["source"])], ports=item["ports"]))
    components.append(component("Controller01", "D", [material("Controller01_injection", inj["controller_mass_kg"],
                                                               inj["cp_J_kgK"], inj["source"])],
                                temperature_range=inj["temperature_range_K"]))
    components.append(component("PDU01", "D", [material("PDU01_injection", inj["pdu_mass_kg"], inj["cp_J_kgK"],
                                                        inj["source"])],
                                ports=["Q_D_W"], temperature_range=inj["temperature_range_K"]))
    optics_source = (f"iss_spec OPTICS z93 and OPTICS_BY_CASE: absorptivity {case_cfg['z93_absorptivity']}, "
                     f"emissivity {case_cfg['z93_emissivity']} ({case_cfg['label_cn']}); one side of the 24 panels")
    components.append(component(
        rad["instance_id"], "R",
        [material("Radiator01_panels", geo["panel_mass_kg"], rad["panel_cp_J_kgK"],
                  "iss_spec MATERIALS hrs_pan: areal mass 8 kg/m2 (rho 3200 kg/m3 x 2.5 mm) times the one-side area, "
                  "cp 900 J/kgK"),
         material("Radiator01_NH3", geo["nh3_mass_kg"], rad["nh3_cp_J_kgK"],
                  "iss_spec PARAMS C_f 1 kJ/K per panel (24 panels) entered as liquid NH3 mass with cp_nh3 4610 J/kgK")],
        [surface(rad["front"]["surface_id"], rad["front"]["normal_body"], geo["area_m2"],
                 case_cfg["z93_absorptivity"], case_cfg["z93_emissivity"], optics_source),
         surface(rad["back"]["surface_id"], rad["back"]["normal_body"], geo["area_m2"],
                 case_cfg["z93_absorptivity"], case_cfg["z93_emissivity"], optics_source)],
        temperature_range=rad["temperature_range_K"], asset_id=rad["asset_id"], asset_version=rad["asset_version"]))
    big = aux["no_conduction_resistance_K_W"]
    connections = [{"path": path, "equivalent_total_resistance_K_W": big, "includes_contact": True,
                    "source": aux["note"]} for path in ("SR", "JC", "CR", "BR")]
    connections.append({"path": "DR", "equivalent_total_resistance_K_W": inj["R_DR_K_W"], "includes_contact": True,
                        "source": inj["source"]})
    return components, connections


def resistance_of(cfg: dict, path: str) -> float:
    return cfg["injection"]["R_DR_K_W"] if path == "DR" else cfg["auxiliary_nodes"]["no_conduction_resistance_K_W"]


# ------------------------------------------------------------------------------------------------------ the runs


def make_ports(t_fe: np.ndarray, q_fe: np.ndarray, label: str):
    """Prescribed Power ports: Q_D_W is the FE radiator heat input (linear interpolation), the other ports are zero."""

    times = np.array(t_fe, dtype=float)
    values = np.array(q_fe, dtype=float)

    def ports(t: float) -> dict:
        return {"P_pv_W": 0.0, "P_load_W": 0.0, "Q_B_W": 0.0, "Q_D_W": float(np.interp(t, times, values))}

    ports.__name__ = f"fe002_fe_heat_input_{label}"
    return ports


def run_loop(cfg, case, loop, case_cfg, orbit, params, series, epoch, t_end):
    sol = cfg["solver"]
    run_id = f"fe002_{case}_loop{loop}"
    t_fe = series["t_s"]
    q_fe = series[cfg["fe"]["heat_input_columns"][loop]]
    T_fe_C = np.mean([series[name] for name in cfg["fe"]["oru_columns"][loop]], axis=0)
    earth = cp.EarthFluxModel(albedo=case_cfg["albedo"], olr_W_m2=case_cfg["olr_W_m2"],
                              solar_constant_W_m2=case_cfg["solar_constant_W_m2"],
                              earth_radius_m=cfg["orbit"]["earth_radius_m"],
                              resolution=tuple(sol["earth_flux_resolution"]))
    provider = cp.EnvironmentProvider.from_callables(
        run_id=run_id, epoch=epoch, parameters=params, position=orbit.position, sun_position=orbit.sun_position,
        quaternion=orbit.quaternion(case_cfg["pointing_law"]), G=orbit.irradiance(case_cfg["solar_constant_W_m2"]),
        earth_flux=earth, time_range_s=(0.0, t_end))
    T_R0 = float(T_fe_C[0]) + KELVIN
    aux0 = cfg["auxiliary_nodes"]["initial_temperature_K"]
    T_D0 = T_R0 + cfg["injection"]["R_DR_K_W"] * float(q_fe[0])
    initial = np.array([aux0, aux0, aux0, aux0, T_D0, T_R0])
    settings = cp.SolverSettings(method=sol["method"], rtol=sol["rtol"], atol_T_K=sol["atol_T_K"],
                                 max_step_s=sol["max_step_s"], output_step_s=sol["output_step_s"],
                                 environment_step_s=sol["environment_step_s"],
                                 event_time_tol_s=sol["event_time_tol_s"])
    boundaries = ([(float(t), "FE heat input sample") for t in t_fe if 0.0 < t < t_end]
                  if sol["split_at_fe_samples"] else [])
    provenance = {"case_id": "FE-002", "fe_case": case, "loop": loop,
                  "test_configuration": cfg["injection"]["source"], "auxiliary_nodes": cfg["auxiliary_nodes"]["note"],
                  "pointing_law": cfg["pointing"][case_cfg["pointing_law"]],
                  "fe_heat_input": cfg["fe"]["heat_input_definition"]}
    started = time.perf_counter()
    archive, error, crash = None, None, None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            archive = cp.run_coupled(params, ThermalState(run_id, 0.0, initial), provider, t_end, settings=settings,
                                     prescribed_ports=make_ports(t_fe, q_fe, f"{case}_{loop}"),
                                     boundaries_s=boundaries, provenance=provenance)
        except cp.CoupledRunError as exc:
            archive, error = exc.archive, dict(exc.archive.error or {})
        except Exception as exc:  # noqa: BLE001  (recorded as a failed check, never as a pass)
            crash = f"{type(exc).__name__}: {exc}"
    return {"run_id": run_id, "archive": archive, "error": error, "crash": crash,
            "wall_s": time.perf_counter() - started, "provider": provider, "settings": settings,
            "warnings": [f"{w.category.__name__}: {w.message}" for w in caught], "t_fe": t_fe, "q_fe": q_fe,
            "T_fe_C": T_fe_C, "initial_K": initial, "boundaries": len(boundaries)}


def post_process(cfg, run, orbit, period, t_end, geo, case_cfg, independent):
    """Numbers of one run that the checks need; every reference here is independent of the module."""

    arc = run["archive"]
    out: dict = {}
    if arc is None:
        return out
    ts = np.array(arc.time_s, dtype=float)
    T = np.array(arc.temperature_K, dtype=float)
    q = np.array(arc.q_W, dtype=float)
    Q_env = np.array(arc.Q_env_W, dtype=float)
    Q_emit = np.array(arc.Q_emit_W, dtype=float)
    dT = np.array(arc.dT_dt_K_s, dtype=float)
    Q_D = np.array(arc.ports_W["Q_D_W"], dtype=float)
    valid = np.array(arc.sample_valid, dtype=bool)
    order = list(arc.path_order)
    nodes = list(arc.node_order)
    iR, iD = nodes.index("R"), nodes.index("D")
    exposed = list(arc.exposed_node_order)
    eR = exposed.index("R")
    q_into_R = sum(q[:, order.index(path)] for path in R_PATHS)
    out.update(ts=ts, T=T, q_into_R=q_into_R, Q_env_R=Q_env[:, eR], Q_emit_R=Q_emit[:, eR], valid=valid,
               nodes=nodes, order=order)

    # heat input: Q_D_W equals the FE input; heat reaching R equals the FE input
    q_ref = np.interp(ts, run["t_fe"], run["q_fe"])
    out["QD_rel"] = float(np.max(np.abs(Q_D - q_ref) / np.abs(q_ref)))
    out["leak_W"] = float(max(np.max(np.abs(q[:, order.index(path)])) for path in LEAK_PATHS))
    t0 = t_end - period
    out["E_mod_full_J"] = SUP.interval_integral(ts, q_into_R, 0.0, t_end)
    out["E_fe_full_J"] = SUP.interval_integral(run["t_fe"], run["q_fe"], 0.0, t_end)
    out["E_mod_orbit3_J"] = SUP.interval_integral(ts, q_into_R, t0, t_end)
    out["E_fe_orbit3_J"] = SUP.interval_integral(run["t_fe"], run["q_fe"], t0, t_end)
    out["E_rel_full"] = (out["E_mod_full_J"] - out["E_fe_full_J"]) / out["E_fe_full_J"]
    out["E_rel_orbit3"] = (out["E_mod_orbit3_J"] - out["E_fe_orbit3_J"]) / out["E_fe_orbit3_J"]
    C_D = cfg["injection"]["cp_J_kgK"] * (cfg["injection"]["controller_mass_kg"] + cfg["injection"]["pdu_mass_kg"])
    out["E_D_storage_J"] = C_D * (float(T[-1, iD]) - float(T[0, iD]))

    # T2 by hand from the archived temperatures: the sum of the four flows into R
    hand_q = sum((T[:, nodes.index(path[0])] - T[:, iR]) / resistance_of(cfg, path) for path in R_PATHS)
    out["T2_rel"] = float(np.max(np.abs(hand_q - q_into_R)) / np.max(np.abs(q_into_R)))

    # two-sided emission by hand: sum over both faces eps sigma A T_R^4
    eps = case_cfg["z93_emissivity"]
    hand_emit = 2.0 * eps * SUP.SIGMA_W_M2_K4 * geo["area_m2"] * T[:, iR] ** 4
    out["emit_rel"] = float(np.max(np.abs(hand_emit - Q_emit[:, eR]) / hand_emit))

    # T3 line 6 with the hand capacity: C_R dT_R/dt = sum q + Q_env,R - Q_emit,R
    net = q_into_R + Q_env[:, eR] - Q_emit[:, eR]
    gross = np.abs(q_into_R) + np.abs(Q_env[:, eR]) + np.abs(Q_emit[:, eR])
    out["T3_rel"] = float(np.max(np.abs(geo["capacity_J_K"] * dT[:, iR] - net) / gross))

    # environment absorption against the independent T4 (computed once per case at the same output times)
    env_ind = independent["Q_env"](ts)
    out["Q_env_R_independent"] = env_ind
    out["env_rel"] = float(np.max(np.abs(Q_env[:, eR] - env_ind) / np.abs(env_ind)))
    out["env_abs_W"] = float(np.max(np.abs(Q_env[:, eR] - env_ind)))

    # independent integration of T3 line 6
    solution = independent["solver"].solve(float(run["initial_K"][iR]), t_end, run["t_fe"], run["q_fe"],
                                           rtol=cfg["independent_reference"]["rtol"],
                                           atol=cfg["independent_reference"]["atol_K"],
                                           max_step=cfg["independent_reference"]["max_step_s"])
    T_ind = solution(ts)
    out["T_ind_K"] = T_ind
    out["ind_max_K"] = float(np.max(np.abs(T[:, iR] - T_ind)))

    # third orbit: dense evaluation of the accepted solution and of the independent solution
    grid = SUP.dense_grid(np.array(arc.accepted["time_s"], dtype=float), t0, t_end,
                          cfg["solver"]["dense_statistics_step_s"])
    TR_dense = np.array(arc.state_at(grid), dtype=float)[:, iR]
    out["grid"] = grid
    out["module_stats_C"] = SUP.dense_stats(grid, TR_dense - KELVIN)
    out["independent_stats_C"] = SUP.dense_stats(grid, solution(grid) - KELVIN)
    out["fe_stats_C"] = SUP.fe_period_stats(run["t_fe"], run["T_fe_C"], t_end, period)
    out["q_fe_orbit3_mean_W"] = out["E_fe_orbit3_J"] / period
    out["Q_env_orbit3_mean_W"] = SUP.interval_integral(ts, Q_env[:, eR], t0, t_end) / period
    out["Q_emit_orbit3_mean_W"] = SUP.interval_integral(ts, Q_emit[:, eR], t0, t_end) / period
    out["TR_end_minus_start_orbit3_K"] = float(TR_dense[-1] - TR_dense[0])

    # eclipse boundaries of the run against the closed-form cylindrical shadow
    closed = []
    for entry, exit_ in orbit.eclipse_windows(0.0, t_end):
        if 0.0 < entry < t_end:
            closed.append((entry, "sunlit_to_umbra"))
        if 0.0 < exit_ < t_end:
            closed.append((exit_, "umbra_to_sunlit"))
    located = [(float(b.time_s), b.kind, float(b.time_left_s), float(b.time_right_s)) for b in arc.eclipse_boundaries]
    worst = 0.0
    matched = len(closed) == len(located)
    for moment, kind in closed:
        same = [item for item in located if item[1] == kind]
        if not same:
            matched = False
            continue
        worst = max(worst, min(abs(item[0] - moment) for item in same))
    out["eclipse_closed"] = closed
    out["eclipse_located"] = located
    out["eclipse_worst_s"] = worst
    out["eclipse_matched"] = matched
    t_old = np.array(arc.steps["t_old_s"], dtype=float)
    t_new = np.array(arc.steps["t_new_s"], dtype=float)
    out["steps_across_boundary"] = int(sum(int(np.sum((t_old < left) & (t_new > right)))
                                           for _, _, left, right in located))
    out["segments_ending_at_eclipse"] = int(sum(1 for seg in arc.segments
                                                if any(str(r).startswith("eclipse:") for r in seg["end_reasons"])))
    out["segments"] = len(arc.segments)
    return out


@pytest.fixture(scope="module")
def fe002():
    cfg = CONFIG
    started = time.perf_counter()
    spec = SUP.load_spec(THERMAL_DIR / cfg["fe"]["spec_file"])
    geo = radiator_geometry(cfg)
    epoch = datetime.fromisoformat(cfg["epoch_utc"])
    t_end = float(cfg["fe"]["end_time_s"])
    columns = (list(cfg["fe"]["heat_input_columns"].values())
               + [name for names in cfg["fe"]["oru_columns"].values() for name in names]
               + list(cfg["fe"]["panel_columns"].values()))
    result = {"cfg": cfg, "spec": spec, "geo": geo, "t_end": t_end, "cases": {}}
    for case in CASES:
        case_cfg = cfg["cases"][case]
        case_dir = THERMAL_DIR / cfg["fe"]["out_dir"] / case
        summary = SUP.load_json(case_dir / cfg["fe"]["summary_file"])
        series = SUP.read_fe_series(case_dir / cfg["fe"]["series_file"], columns, cfg["fe"]["time_column"])
        items = SUP.read_fe_items(case_dir / cfg["fe"]["items_file"])
        orbit = SUP.FEOrbit(summary["orbit"], cfg["orbit"]["earth_radius_m"])
        period = orbit.summary_period_s
        entry = {"case_cfg": case_cfg, "summary": summary, "series": series, "items": items, "orbit": orbit,
                 "period": period, "loops": {}, "params": None, "params_error": None}
        try:
            components, connections = build_network(cfg, case_cfg, geo)
            entry["components"] = components
            entry["params"] = assemble_thermal_parameters(components, connections, None)
        except Exception as exc:  # noqa: BLE001
            entry["params_error"] = f"{type(exc).__name__}: {exc}"
            result["cases"][case] = entry
            continue
        for loop in LOOPS:
            entry["loops"][loop] = run_loop(cfg, case, loop, case_cfg, orbit, entry["params"], series, epoch, t_end)
        # independent references of the case: T4 at the output times and the environment table of the integrator
        ref_cfg = cfg["independent_reference"]
        quadrature = tuple(ref_cfg["quadrature"])
        optics = {"absorptivity": case_cfg["z93_absorptivity"], "emissivity": case_cfg["z93_emissivity"]}
        first = next((entry["loops"][lp] for lp in LOOPS if entry["loops"][lp]["archive"] is not None), None)
        if first is not None:
            env_cache: dict[float, float] = {}

            def q_env_independent(times, orbit=orbit, case_cfg=case_cfg, optics=optics, cache=env_cache):
                values = []
                for moment in np.asarray(times, dtype=float):
                    key = float(moment)
                    if key not in cache:
                        cache[key] = SUP.radiator_environment(orbit, key, case_cfg["pointing_law"],
                                                              not orbit.in_shadow(key), case_cfg, optics,
                                                              geo["area_m2"], quadrature)["Q_env_W"]
                    values.append(cache[key])
                return np.array(values)

            solver = SUP.IndependentRadiator(orbit, case_cfg["pointing_law"], case_cfg, optics, geo["area_m2"],
                                             geo["capacity_J_K"], ref_cfg["table_step_s"], quadrature)
            independent = {"Q_env": q_env_independent, "solver": solver}
            for loop in LOOPS:
                run = entry["loops"][loop]
                run["post"] = post_process(cfg, run, orbit, period, t_end, geo, case_cfg, independent)
        entry["attitude"] = attitude_check(cfg, case_cfg, orbit, first, t_end)
        result["cases"][case] = entry
    result["wall_s"] = time.perf_counter() - started
    return result


def attitude_check(cfg, case_cfg, orbit, run, t_end):
    """Pointing law, quaternion and the module's incidence cosines of the radiator faces at sample instants."""

    if run is None or run["archive"] is None:
        return None
    law = case_cfg["pointing_law"]
    provider = run["provider"]
    times = list(np.array(run["archive"].time_s, dtype=float)[::10])
    for entry, exit_ in orbit.eclipse_windows(0.0, t_end):
        for moment in (entry, exit_):
            times += [moment - 0.5, moment + 0.5]
    times = sorted(t for t in times if 0.0 <= t <= t_end)
    quaternion = orbit.quaternion(law)
    rad = cfg["radiator"]
    worst = {"quaternion_axis": 0.0, "edge_to_sun": 0.0, "law": 0.0, "nadir": 0.0, "cos_module": 0.0}
    counts = {"sunlit": 0, "shadow": 0}
    for t in times:
        lit = not orbit.in_shadow(t)
        n = orbit.front_normal(t, law)
        z_axis = SUP.quaternion_to_matrix(quaternion(t))[:, 2]
        worst["quaternion_axis"] = max(worst["quaternion_axis"], float(np.linalg.norm(z_axis - n)))
        s_sat = orbit.sun_direction(t)
        if lit:
            counts["sunlit"] += 1
            worst["edge_to_sun"] = max(worst["edge_to_sun"], abs(float(n @ s_sat)))
            if law == "zero":
                worst["law"] = max(worst["law"], float(np.linalg.norm(n - orbit.h)))
            else:
                worst["law"] = max(worst["law"], abs(float(n @ orbit.velocity_hat(t))))
        else:
            counts["shadow"] += 1
            r = orbit.position(t)
            worst["nadir"] = max(worst["nadir"], float(np.linalg.norm(n + r / np.linalg.norm(r))))
        environment = provider.sample(t).surface_environment
        ids = list(environment["surface_ids"])
        cos = np.array(environment["cos_incidence"], dtype=float)
        expected_front = float(n @ s_sat)
        worst["cos_module"] = max(worst["cos_module"],
                                  abs(cos[ids.index(rad["front"]["surface_id"])] - expected_front),
                                  abs(cos[ids.index(rad["back"]["surface_id"])] + expected_front))
    return {"times": len(times), "counts": counts, "worst": worst}


# ------------------------------------------------------------------------------------------------------ helpers


def _runs(fe002):
    for case in CASES:
        entry = fe002["cases"][case]
        for loop in LOOPS:
            yield case, loop, entry, entry["loops"].get(loop)


def _run_ok(run) -> bool:
    return run is not None and run["archive"] is not None and run["crash"] is None and run["error"] is None \
        and bool(run.get("post"))


def _run_status(run) -> str:
    if run is None:
        return "未运行"
    if run["crash"]:
        return run["crash"]
    if run["archive"] is None:
        return "no archive"
    text = f"status {run['archive'].status}"
    if run["error"]:
        text += f", error {run['error'].get('kind')} at {run['error'].get('time_s')}: {run['error'].get('message')}"
    return text


def _missing(case_record, name, expected, reason):
    return case_record.check(name, expected, f"未执行: {reason}", False)


# ------------------------------------------------------------------------------------------------------ tests


def test_inputs_and_preconditions(case_record, fe002):
    """Case inputs against the FE parameter table, FE data availability, T5 capacity and the test configuration."""

    cfg, spec, geo = fe002["cfg"], fe002["spec"], fe002["geo"]
    rad = cfg["radiator"]
    results = []

    # inputs: panel count, one-side area and C_R by T5 against the FE parameter table and the case text
    hrs = spec.HRS
    spec_wing = abs(hrs["x_tip"] - hrs["x_root"])
    spec_lp = (spec_wing - (hrs["n_panels"] - 1) * hrs["gap"]) / hrs["n_panels"]
    spec_orus = {loop: [o for o, (side, _) in hrs["orus"].items() if (side > 0) == (loop == "A")] for loop in LOOPS}
    spec_panels = {loop: len(spec_orus[loop]) * hrs["n_panels"] for loop in LOOPS}
    spec_area = spec_panels["A"] * hrs["width"] * spec_lp
    mat = spec.MATERIALS["hrs_pan"]
    c_f_text = spec.PARAMS["C_f"][0]
    c_f = 1000.0 * float(c_f_text.split("[")[0]) if c_f_text.endswith("[kJ/K]") else float("nan")
    cp_nh3 = 1000.0 * float(spec.PARAMS["cp_nh3"][0].split("[")[0])
    spec_capacity = spec_area * mat["rho"] * mat["t"] * mat["cp"] + spec_panels["A"] * c_f
    ok_geometry = (spec_panels == {"A": 24, "B": 24} and geo["panels"] == 24
                   and abs(geo["area_m2"] - spec_area) <= 1e-12 * spec_area
                   and round(geo["area_m2"], 1) == rad["case_area_one_side_m2"]
                   and abs(rad["panel_areal_density_kg_m2"] - mat["rho"] * mat["t"]) <= 1e-12
                   and rad["panel_cp_J_kgK"] == mat["cp"] and rad["nh3_capacity_per_panel_J_K"] == c_f
                   and rad["nh3_cp_J_kgK"] == cp_nh3
                   and abs(geo["capacity_J_K"] - spec_capacity) <= 1e-12 * spec_capacity
                   and round(geo["capacity_J_K"] / 1e6, 2) == rad["case_capacity_MJ_K"])
    results.append(case_record.check(
        "输入数据 每个回路24块面板 单面面积与热容按T5手算",
        f"每个回路 3 个 ORU 共 24 块面板，单面面积 {rad['case_area_one_side_m2']} m2，C_R 为面板质量乘比热加 24 kJ/K 液氨热容，"
        f"共 {rad['case_capacity_MJ_K']} MJ/K，与 iss_spec HRS、MATERIALS hrs_pan 与 PARAMS C_f 一致",
        f"loop ORUs {spec_orus}, panels {spec_panels}; panel {spec_lp:.6f} m x {hrs['width']} m; one side "
        f"{geo['area_m2']:.6f} m2 (iss_spec {spec_area:.6f}); panel mass {geo['panel_mass_kg']:.6f} kg x "
        f"{mat['cp']} J/kgK = {geo['panel_capacity_J_K']:.1f} J/K; NH3 24 x {c_f:.0f} J/K = {geo['nh3_capacity_J_K']:.1f} "
        f"J/K ({geo['nh3_mass_kg']:.6f} kg x {cp_nh3:.0f} J/kgK); C_R {geo['capacity_J_K']:.1f} J/K",
        ok_geometry))
    case_record.metric("radiator_area_one_side_m2", geo["area_m2"])
    case_record.metric("radiator_capacity_J_K", geo["capacity_J_K"])
    case_record.metric("radiator_panel_capacity_J_K", geo["panel_capacity_J_K"])
    case_record.metric("radiator_nh3_capacity_J_K", geo["nh3_capacity_J_K"])

    # assembled parameters: C_R, R surfaces and the injection configuration by T5
    rows, ok_assembly = {}, True
    for case in CASES:
        entry = fe002["cases"][case]
        params = entry["params"]
        if params is None:
            rows[case] = entry["params_error"]
            ok_assembly = False
            continue
        nodes = list(params.provenance["node_order"])
        C = np.array(params.C_J_K, dtype=float)
        R = np.array(params.R_K_W, dtype=float)
        surfaces = {s.surface_id: s for s in params.surfaces}
        front, back = surfaces.get(rad["front"]["surface_id"]), surfaces.get(rad["back"]["surface_id"])
        C_D_hand = cfg["injection"]["cp_J_kgK"] * (cfg["injection"]["controller_mass_kg"] + cfg["injection"]["pdu_mass_kg"])
        c_rel = float(abs(C[nodes.index("R")] - geo["capacity_J_K"]) / geo["capacity_J_K"])
        d_rel = float(abs(C[nodes.index("D")] - C_D_hand) / C_D_hand)
        path_order = list(params.provenance["path_order"])
        r_ok = all(abs(R[path_order.index(path)] - resistance_of(cfg, path)) <= 1e-12 * resistance_of(cfg, path)
                   for path in ("SR", "JC", "CR", "BR", "DR"))
        s_ok = (front is not None and back is not None and front.node_id == "R" and back.node_id == "R"
                and abs(front.area_m2 - geo["area_m2"]) <= 1e-12 * geo["area_m2"]
                and abs(back.area_m2 - geo["area_m2"]) <= 1e-12 * geo["area_m2"]
                and front.absorptivity == entry["case_cfg"]["z93_absorptivity"]
                and front.emissivity == entry["case_cfg"]["z93_emissivity"]
                and back.absorptivity == front.absorptivity and back.emissivity == front.emissivity
                and np.allclose(front.normal_body, [0, 0, 1], atol=0) and np.allclose(back.normal_body, [0, 0, -1], atol=0))
        ports_ok = dict(params.instance_map["ports"]).get("Q_D_W") == "PDU01"
        ok = c_rel <= cfg["criteria"]["relative_tol_exact"] and d_rel <= cfg["criteria"]["relative_tol_exact"] \
            and r_ok and s_ok and ports_ok
        ok_assembly &= ok
        rows[case] = {"C_R_J_K": float(C[nodes.index("R")]), "C_R_rel": c_rel, "C_D_J_K": float(C[nodes.index("D")]),
                      "C_D_over_C_R": float(C[nodes.index("D")] / C[nodes.index("R")]),
                      "R_K_W": dict(zip(path_order, (float(x) for x in R))), "R_surfaces_ok": s_ok,
                      "Q_D_W_from": dict(params.instance_map["ports"]).get("Q_D_W")}
    results.append(case_record.check(
        "输入数据 assemble_thermal_parameters 按T5装配散热板与注入节点",
        "C_R 与手算相对误差不超过 1e-12；两面各 220.728 m2，法向 +Z 与 −Z，吸收率与发射率取本工况白色涂层值；"
        "C_D 为 100 J/K，DR 1e-4 K/W，SR、JC、CR、BR 1e12 K/W；Q_D_W 来自 PDU01",
        rows, ok_assembly))
    case_record.metric("assembled_parameters", rows)

    # inputs: coating optics and environment per case against iss_spec and the FE run summaries
    rows, ok_env = {}, True
    for case in CASES:
        case_cfg = cfg["cases"][case]
        z93 = dict(spec.OPTICS["z93"])
        z93.update(spec.OPTICS_BY_CASE.get(case, {}).get("z93", {}))
        env = spec.CASES[case]
        orbit = fe002["cases"][case]["orbit"]
        beta = orbit.beta_deg()
        law_spec = env["hrs_law"]
        ok = (case_cfg["z93_absorptivity"] == z93["alpha"] and case_cfg["z93_emissivity"] == z93["eps"]
              and case_cfg["solar_constant_W_m2"] == env["S_sun"] and case_cfg["albedo"] == env["albedo"]
              and case_cfg["olr_W_m2"] == env["olr"] and case_cfg["beta_deg"] == env["beta_deg"]
              and abs(beta - case_cfg["beta_deg"]) <= 1e-6 and case_cfg["pointing_law"] == law_spec)
        ok_env &= ok
        rows[case] = {"alpha": z93["alpha"], "eps": z93["eps"], "S_sun": env["S_sun"], "albedo": env["albedo"],
                      "olr": env["olr"], "beta_spec_deg": env["beta_deg"], "beta_from_sun_ecs_deg": beta,
                      "hrs_law": law_spec}
    results.append(case_record.check(
        "输入数据 白色涂层吸收率发射率与三个工况环境值",
        "冷工况 0.15 与 0.91，平均工况 0.20 与 0.91，热工况 0.24 与 0.90；β、太阳常数、反照率与地球红外同 ENV_LINES，"
        "由 sun_ecs 与轨道法向算得的 β 与 iss_spec 相差不超过 1e-6°",
        rows, ok_env))

    # orbit: FE functions, 400 km, period
    rows, ok_orbit = {}, True
    for case in CASES:
        orbit = fe002["cases"][case]["orbit"]
        r_expected = cfg["orbit"]["earth_radius_m"] + cfg["orbit"]["altitude_m"]
        period_kepler = 2.0 * math.pi * math.sqrt(r_expected**3 / spec.ORBIT["mu"])
        ok = (orbit.radius_m == r_expected and orbit.summary_radius_m == r_expected
              and abs(orbit.function_period_s - orbit.summary_period_s) < 1e-3
              and abs(orbit.summary_period_s - period_kepler) < 1e-6
              and abs(math.degrees(orbit.inclination_rad) - spec.ORBIT["incl_deg"]) < 1e-5
              and round(orbit.summary_period_s, 1) == 5553.6)
        ok_orbit &= ok
        rows[case] = {"radius_m": orbit.radius_m, "period_summary_s": orbit.summary_period_s,
                      "period_function_s": orbit.function_period_s, "period_kepler_s": period_kepler,
                      "inclination_deg": math.degrees(orbit.inclination_rad), "sun_ecs": orbit.sun_hat.tolist()}
    results.append(case_record.check(
        "输入数据 有限元轨道函数 高度400 km 周期5553.6 s",
        "轨道半径 6778137 m，周期与开普勒周期相差不超过 1e-6 s，倾角 51.64°", rows, ok_orbit))
    case_record.metric("orbit", rows)

    # precondition 1: FE heat input and ORU panel means available, FE initial temperature
    rows, ok_data = {}, True
    for case in CASES:
        series = fe002["cases"][case]["series"]
        t = series["t_s"]
        T0 = {loop: float(np.mean([series[name][0] for name in cfg["fe"]["oru_columns"][loop]])) for loop in LOOPS}
        q_min = {loop: float(np.min(series[cfg["fe"]["heat_input_columns"][loop]])) for loop in LOOPS}
        ok = (not series["missing"] and t[0] == 0.0 and t[-1] == cfg["fe"]["end_time_s"]
              and series["duplicate_value_spread"] == 0.0
              and all(abs(T0[loop] + KELVIN - spec.T_INIT["hrs"]) <= 1e-9 for loop in LOOPS)
              and all(value > 0.0 for value in q_min.values()))
        ok_data &= ok
        rows[case] = {"rows": series["rows"], "unique_times": int(t.size), "t_first_s": float(t[0]),
                      "t_last_s": float(t[-1]), "event_times_s": series["event_times_s"].tolist(),
                      "duplicate_value_spread": series["duplicate_value_spread"], "missing_columns": series["missing"],
                      "initial_loop_mean_C": T0, "min_heat_input_W": q_min}
    results.append(case_record.check(
        "前置条件 有限元回路进热量与三个散热器单元面板平均温度可用",
        "series.csv 含 Qrad_A、Qrad_B 与六个 ORU 面板平均温度，0 s 至 16560 s，事件重复行数值相同，"
        f"初始面板平均温度等于 iss_spec T_INIT hrs {spec.T_INIT['hrs']} K，进热量全程为正",
        rows, ok_data))
    case_record.metric("fe_data", rows)

    # precondition 2: the sum of the branch flows is replaced by the FE heat input through the D node
    inj = cfg["injection"]
    C_D = inj["cp_J_kgK"] * (inj["controller_mass_kg"] + inj["pdu_mass_kg"])
    tau = C_D * inj["R_DR_K_W"]
    results.append(case_record.check(
        "前置条件 q_SR q_CR q_BR q_DR 之和用有限元进热量代替 按第9.4节记录",
        "有限元进热量经 D 节点注入：Q_D_W 等于有限元进热量，C_D 远小于 C_R，R_DR 使时间常数远小于有限元 120 s 输出间隔；"
        "其余三条到 R 的连接 1e12 K/W；测试配置写入运行归档 provenance",
        {"C_D_J_K": C_D, "C_D_over_C_R": C_D / geo["capacity_J_K"], "R_DR_K_W": inj["R_DR_K_W"],
         "time_constant_s": tau, "no_conduction_K_W": cfg["auxiliary_nodes"]["no_conduction_resistance_K_W"],
         "record": inj["source"]},
        C_D / geo["capacity_J_K"] < 1e-3 and tau < 1.0))
    case_record.metric("injection", {"C_D_J_K": C_D, "R_DR_K_W": inj["R_DR_K_W"], "time_constant_s": tau})

    # precondition 3: attitude quaternion follows the FE radiator pointing law
    rows, ok_att = {}, True
    tol = cfg["criteria"]["attitude_tol"]
    for case in CASES:
        att = fe002["cases"][case].get("attitude")
        if att is None:
            rows[case] = "no run"
            ok_att = False
            continue
        w = att["worst"]
        expect_shadow = cfg["cases"][case]["beta_deg"] == 0.0
        ok = (all(value <= tol for value in w.values())
              and att["counts"]["sunlit"] > 0 and (att["counts"]["shadow"] > 0) == expect_shadow)
        ok_att &= ok
        rows[case] = {"instants": att["times"], **att["counts"], **{k: f"{v:.2e}" for k, v in w.items()}}
    results.append(case_record.check(
        "前置条件 姿态四元数按有限元散热器指向规律 受晒段侧边对日 日食段正面对地",
        f"体轴 +Z 等于指向规律给出的正面法向；受晒段正面法向与卫星指向太阳方向的点积绝对值不超过 {tol:g}，"
        f"β 为 0 时法向沿轨道法向，β 为 75° 时法向垂直于速度方向；日食段正面法向指向天底；"
        f"模块 prepare_surface_environment 的两面入射余弦与独立点积之差不超过 {tol:g}",
        rows, ok_att))
    case_record.metric("attitude", rows)
    assert all(results)


def test_step1_integration_and_heat_input(case_record, fe002):
    """Step 1: FE heat input drives R from the FE initial temperature over three orbits, split at the eclipses."""

    cfg, geo, t_end = fe002["cfg"], fe002["geo"], fe002["t_end"]
    crit = cfg["criteria"]
    results = []
    for case, loop, entry, run in _runs(fe002):
        key = f"{case}_{loop}"
        label = f"{case} 回路{loop}"
        if not _run_ok(run):
            results.append(_missing(case_record, f"步骤1 {label} 运行完成", "status completed", _run_status(run)))
            continue
        arc, post = run["archive"], run["post"]
        stats = arc.statistics
        T0_expected = float(run["T_fe_C"][0]) + KELVIN
        ok_run = (arc.status == "completed" and arc.t_start_s == 0.0 and arc.t_end_s == t_end
                  and float(arc.time_s[-1]) == t_end and bool(np.all(post["valid"]))
                  and abs(float(arc.temperature_K[0, post["nodes"].index("R")]) - T0_expected) <= 1e-12
                  and arc.solver_settings["method"] == cfg["solver"]["method"] and not arc.range_warnings)
        results.append(case_record.check(
            f"步骤1 {label} 从有限元初始温度起算三圈 运行完成",
            f"status completed，0 s 至 {t_end:.0f} s 即有限元时段，初值等于有限元初始面板平均温度 {T0_expected:.2f} K，"
            f"Radau 方法，全部输出样本有效，无温区越限记录",
            {"status": arc.status, "t_end_s": arc.t_end_s, "orbits": t_end / entry["period"],
             "T_R0_K": float(arc.temperature_K[0, post["nodes"].index("R")]), "method": arc.solver_settings["method"],
             "accepted_steps": stats["accepted_steps"], "rejected_steps": stats["rejected_steps"],
             "function_evaluations": stats["function_evaluations"], "segments": stats["segments"],
             "invalid_output_samples": stats["invalid_output_samples"], "range_warnings": len(arc.range_warnings),
             "wall_time_s": round(run["wall_s"], 1), "warnings": run["warnings"][:3]},
            ok_run))
        for name in ("accepted_steps", "rejected_steps", "function_evaluations", "segments", "solver_njev"):
            case_record.metric(f"{key}_{name}", int(stats[name]))
        case_record.metric(f"{key}_wall_time_s", round(run["wall_s"], 2))

        # eclipse boundaries: split there, located at the closed-form cylindrical shadow times
        n_expected = len(post["eclipse_closed"])
        ok_ecl = (post["eclipse_matched"] and post["eclipse_worst_s"] <= crit["eclipse_time_tol_s"]
                  and post["steps_across_boundary"] == 0 and post["segments_ending_at_eclipse"] == n_expected)
        results.append(case_record.check(
            f"步骤1 {label} 在日食边界分段积分",
            f"日食进出时刻与圆柱地影解析值之差不超过 {crit['eclipse_time_tol_s']:g} s，"
            f"共 {n_expected} 个边界，没有已接受步跨越边界，每个边界结束一个积分段",
            {"closed_form_s": [round(m, 4) for m, _ in post["eclipse_closed"]],
             "located_s": [round(item[0], 4) for item in post["eclipse_located"]],
             "worst_s": post["eclipse_worst_s"], "steps_across_boundary": post["steps_across_boundary"],
             "segments_ending_at_eclipse": post["segments_ending_at_eclipse"], "segments": post["segments"],
             "fe_event_rows_s": entry["series"]["event_times_s"].tolist()},
            ok_ecl))
        case_record.metric(f"{key}_eclipse_worst_s", post["eclipse_worst_s"])
        # FE event rows (shadow events of the FE solver output) against the closed-form cylindrical shadow, recorded
        events = entry["series"]["event_times_s"]
        if events.size and post["eclipse_closed"]:
            case_record.metric(f"{key}_fe_event_minus_closed_form_s",
                               [round(float(events[np.argmin(np.abs(events - moment))] - moment), 3)
                                for moment, _ in post["eclipse_closed"]])

        # FE heat input drives the radiator: Q_D_W equals the FE input and reaches R through q_DR
        ok_q = (post["QD_rel"] <= crit["relative_tol_exact"] and post["leak_W"] <= crit["leak_W"]
                and post["T2_rel"] <= crit["relative_tol_exact"])
        results.append(case_record.check(
            f"步骤1 {label} 有限元进热量时程驱动散热板节点",
            f"归档 Q_D_W 与有限元进热量线性插值相对差不超过 {crit['relative_tol_exact']:g}；SR、CR、BR 热流绝对值不超过 "
            f"{crit['leak_W']:g} W；到达 R 的热流与按 T2 手算之差相对不超过 {crit['relative_tol_exact']:g}",
            {"Q_D_rel": f"{post['QD_rel']:.2e}", "leak_W": f"{post['leak_W']:.2e}", "T2_rel": f"{post['T2_rel']:.2e}"},
            ok_q))
        ok_e = abs(post["E_rel_full"]) <= crit["heat_input_relative"] and abs(post["E_rel_orbit3"]) <= crit["heat_input_relative"]
        results.append(case_record.check(
            f"步骤1 {label} 到达散热板的累计热量等于有限元进热量",
            f"q_SR + q_CR + q_BR + q_DR 的时间积分与有限元进热量积分的相对差不超过 {crit['heat_input_relative']:g}，"
            "全程与第三圈分别检查",
            {"module_full_J": round(post["E_mod_full_J"], 1), "fe_full_J": round(post["E_fe_full_J"], 1),
             "relative_full": f"{post['E_rel_full']:.2e}", "module_orbit3_J": round(post["E_mod_orbit3_J"], 1),
             "fe_orbit3_J": round(post["E_fe_orbit3_J"], 1), "relative_orbit3": f"{post['E_rel_orbit3']:.2e}",
             "D_storage_change_J": round(post["E_D_storage_J"], 1)},
            ok_e))
        case_record.metric(f"{key}_heat_relative_full", post["E_rel_full"])
        case_record.metric(f"{key}_heat_relative_orbit3", post["E_rel_orbit3"])

        # T3 line 6 with T4 and T5: environment absorption, two-sided emission, capacity
        ok_t3 = (post["env_rel"] <= crit["environment_relative"] and post["emit_rel"] <= crit["relative_tol_exact"]
                 and post["T3_rel"] <= crit["derivative_relative"])
        results.append(case_record.check(
            f"步骤1 {label} 式T3第六行 环境吸热 双面表面辐射与热容",
            f"Q_env_R 与独立 T4 计算相对差不超过 {crit['environment_relative']:g}，两面独立积分地球视角系数；"
            f"Q_emit_R 与手算 2 ε σ A T_R⁴ 相对差不超过 {crit['relative_tol_exact']:g}；"
            f"C_R 手算值乘 dT_R/dt 与各支路进热加 Q_env_R 减 Q_emit_R 之差相对总量不超过 {crit['derivative_relative']:g}",
            {"env_rel": f"{post['env_rel']:.2e}", "env_abs_W": round(post["env_abs_W"], 4),
             "emit_rel": f"{post['emit_rel']:.2e}", "T3_rel": f"{post['T3_rel']:.2e}",
             "Q_env_R_range_W": [round(float(post["Q_env_R"].min()), 1), round(float(post["Q_env_R"].max()), 1)]},
            ok_t3))
        case_record.metric(f"{key}_environment_relative", post["env_rel"])

        # independent integration of T3 line 6 with the independent environment
        ok_ind = post["ind_max_K"] <= crit["independent_K"]
        results.append(case_record.check(
            f"步骤1 {label} 散热板温度与独立积分程序一致",
            f"同一输出时刻模块 T_R 与独立实现的式 T3 第六行积分之差不超过 {crit['independent_K']:g} K",
            {"max_abs_K": f"{post['ind_max_K']:.2e}",
             "third_orbit_mean_module_C": round(post["module_stats_C"]["mean"], 4),
             "third_orbit_mean_independent_C": round(post["independent_stats_C"]["mean"], 4)},
            ok_ind))
        case_record.metric(f"{key}_independent_max_K", post["ind_max_K"])
    assert all(results)


def test_step2_third_orbit_against_fe(case_record, fe002):
    """Step 2 and the acceptance: third-orbit mean of R against the mean of the three ORU panel means."""

    cfg, t_end = fe002["cfg"], fe002["t_end"]
    limit = cfg["criteria"]["acceptance_mean_K"]
    results = []
    window_rows = {}
    for case, loop, entry, run in _runs(fe002):
        label = f"{case} 回路{loop}"
        if not _run_ok(run):
            results.append(_missing(case_record, f"验收判据 {label} 第三圈平均温度差不超过5 K",
                                    f"|ΔT_mean| ≤ {limit} K", _run_status(run)))
            continue
        post = run["post"]
        mod, fe = post["module_stats_C"], post["fe_stats_C"]
        window_rows[f"{case}_{loop}"] = {"t0_s": round(fe["t0_s"], 4), "t1_s": fe["t1_s"], "fe_samples": fe["samples"],
                                         "module_points": int(post["grid"].size)}
        diff = {k: mod[k] - fe[k] for k in ("min", "mean", "max")}
        results.append(case_record.check(
            f"验收判据 {label} 第三圈平均温度差不超过5 K",
            f"模块第三圈时间加权平均温度与三个 ORU 面板平均温度之平均的差绝对值不超过 {limit} K",
            {"module_C": {k: round(mod[k], 3) for k in ("min", "mean", "max")},
             "fe_C": {k: round(fe[k], 3) for k in ("min", "mean", "max")},
             "difference_K": {k: round(v, 3) for k, v in diff.items()}},
            abs(diff["mean"]) <= limit))
        key = f"{case}_{loop}"
        case_record.metric(f"{key}_module_orbit3_C", {k: mod[k] for k in ("min", "mean", "max")})
        case_record.metric(f"{key}_fe_orbit3_C", {k: fe[k] for k in ("min", "mean", "max")})
        case_record.metric(f"{key}_difference_orbit3_K", diff)
    period = fe002["cases"]["nom0"]["period"]
    ok_window = bool(window_rows) and all(abs(row["t0_s"] - (t_end - period)) < 1e-3 and row["t1_s"] == t_end
                                          for row in window_rows.values())
    results.insert(0, case_record.check(
        "步骤2 取第三圈与三个散热器单元面板平均温度的平均值比较",
        f"第三圈为最后一个精确轨道周期 {t_end - period:.2f} s 至 {t_end:.0f} s；有限元取每个回路三个 ORU 面板平均温度之平均，"
        "按时间加权；模块在已接受解上按 5 s 加密并含全部已接受状态",
        window_rows, ok_window))
    assert all(results)


def coldest_rows(fe002) -> dict:
    """Step 3 record: instant of the coldest FE panel in the third orbit, FE mean at that instant, module T_R there."""

    cfg, t_end = fe002["cfg"], fe002["t_end"]
    pc = cfg["fe"]["panel_columns"]
    rows = {}
    for case in CASES:
        entry = fe002["cases"][case]
        series, period = entry["series"], entry["period"]
        t = series["t_s"]
        inside = t >= t_end - period
        tmin, tmean, tmax = series[pc["min"]], series[pc["mean"]], series[pc["max"]]
        index = int(np.flatnonzero(inside)[np.argmin(tmin[inside])])
        t_cold = float(t[index])
        row = {"time_s": t_cold, "coldest_panel_C": float(tmin[index]), "radiator_mean_C": float(tmean[index]),
               "mean_minus_coldest_K": float(tmean[index] - tmin[index]),
               "orbit3_mean_minus_min_K": [float((tmean - tmin)[inside].min()), float((tmean - tmin)[inside].max())],
               "orbit3_max_minus_min_K": [float((tmax - tmin)[inside].min()), float((tmax - tmin)[inside].max())],
               "items_orbit3_min_C": {name: entry["items"][name]["Tmin_C"]
                                      for loop in LOOPS for name in cfg["fe"]["oru_items"][loop]}}
        for loop in LOOPS:
            run = entry["loops"].get(loop)
            if _run_ok(run):
                iR = run["post"]["nodes"].index("R")
                T_mod = float(run["archive"].state_at(t_cold)[iR]) - KELVIN
                row[f"module_T_R_loop{loop}_C"] = T_mod
                row[f"module_minus_coldest_loop{loop}_K"] = T_mod - float(tmin[index])
        rows[case] = row
    return rows


def loop_difference_rows(fe002) -> dict:
    """Loop B minus loop A of the third-orbit means: module, FE and the hand estimate from the heat inputs.

    Hand estimate: the two loops share the environment, so the mean difference follows the heat-input difference
    over the linearized radiative conductance of both faces, dT = dQ / (4 eps sigma 2A T^3), with T the mean of the
    two independent solutions of the loops.
    """

    cfg, t_end = fe002["cfg"], fe002["t_end"]
    pc = cfg["fe"]["panel_columns"]
    rows = {}
    for case in CASES:
        entry = fe002["cases"][case]
        runs = {loop: entry["loops"].get(loop) for loop in LOOPS}
        if not all(_run_ok(run) for run in runs.values()):
            continue
        post = {loop: runs[loop]["post"] for loop in LOOPS}
        eps = cfg["cases"][case]["z93_emissivity"]
        area = fe002["geo"]["area_m2"]
        T_bar = 0.5 * sum(post[loop]["independent_stats_C"]["mean"] for loop in LOOPS) + KELVIN
        conductance = 4.0 * eps * SUP.SIGMA_W_M2_K4 * 2.0 * area * T_bar**3
        dQ = post["B"]["q_fe_orbit3_mean_W"] - post["A"]["q_fe_orbit3_mean_W"]
        series = entry["series"]
        inside = series["t_s"] >= t_end - entry["period"]
        spread = series[pc["max"]][inside] - series[pc["min"]][inside]
        module = post["B"]["module_stats_C"]["mean"] - post["A"]["module_stats_C"]["mean"]
        fe = post["B"]["fe_stats_C"]["mean"] - post["A"]["fe_stats_C"]["mean"]
        rows[case] = {"heat_input_B_minus_A_W": dQ, "radiative_conductance_W_K": conductance,
                      "hand_B_minus_A_K": dQ / conductance, "module_B_minus_A_K": module, "fe_B_minus_A_K": fe,
                      "fe_minus_module_K": fe - module,
                      "residual_K": {loop: post[loop]["module_stats_C"]["mean"] - post[loop]["fe_stats_C"]["mean"]
                                     for loop in LOOPS},
                      "fe_panel_spread_orbit3_K": [float(spread.min()), float(spread.max())]}
    return rows


def test_step3_coldest_panel_record(case_record, fe002):
    """Step 3: the FE coldest panel against the FE radiator mean at the same instant."""

    t_end = fe002["t_end"]
    rows, ok = coldest_rows(fe002), True
    for case, row in rows.items():
        period = fe002["cases"][case]["period"]
        good = (np.isfinite(row["mean_minus_coldest_K"]) and t_end - period <= row["time_s"] <= t_end
                and all(f"module_T_R_loop{loop}_C" in row for loop in LOOPS))
        ok &= bool(good)
    case_record.metric("coldest_panel", rows)
    passed = case_record.check(
        "步骤3 记录同一时刻有限元最冷面板与平均温度之差",
        "第三圈内有限元全部散热器面板最低温度出现的时刻，记录该时刻 hrs_Tmean_C 减 hrs_Tmin_C 与模块 T_R",
        {case: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items() if k != "items_orbit3_min_C"}
         for case, row in rows.items()},
        ok)
    assert passed


def test_expected_residual_sources(case_record, fe002):
    """Expected result 2: the residual comes from the mutual obstruction of the two wings and the panel spread."""

    cfg = fe002["cfg"]
    tol = cfg["criteria"]["loop_difference_K"]
    rows = loop_difference_rows(fe002)
    ok_loop = len(rows) == len(CASES) and all(abs(row["module_B_minus_A_K"] - row["hand_B_minus_A_K"]) <= tol
                                              for row in rows.values())
    residuals = [abs(value) for row in rows.values() for value in row["residual_K"].values()]
    spreads = [row["fe_panel_spread_orbit3_K"][0] for row in rows.values()]
    case_record.metric("loop_difference", rows)
    shown = {case: {key: ([round(v, 2) for v in value] if isinstance(value, list) else
                          {k: round(v, 3) for k, v in value.items()} if isinstance(value, dict) else round(value, 3))
                    for key, value in row.items()} for case, row in rows.items()}
    results = [case_record.check(
        "预期结果 集总模型两个回路之差只来自进热量 不计两翼相互遮挡",
        f"模块回路 B 减回路 A 的第三圈平均温度与按进热量差除以线性化辐射热导 4 ε σ 2A T³ 的手算之差不超过 {tol} K；"
        "有限元两回路之差与模块之差的差值记为两翼相互遮挡等集总模型不表示的效应，见设计报告第 4.4 节与第 10 章",
        shown, ok_loop)]
    ok_spread = bool(residuals) and bool(spreads) and max(residuals) < min(spreads)
    results.append(case_record.check(
        "预期结果 平均温度残差小于有限元面板沿流向的温差",
        "六个第三圈平均温度残差的最大值小于有限元同一时刻散热器面板最高与最低温度之差在第三圈的最小值；"
        "每个 ORU 的 8 块面板沿流向串联，入口面板最热，出口面板最冷，见有限元报告第 5.2 节；集总温度不表示局部温差，见设计报告第 10 章",
        {"max_residual_K": round(max(residuals), 3) if residuals else None,
         "min_fe_panel_spread_K": round(min(spreads), 2) if spreads else None},
        ok_spread))
    case_record.metric("residual_vs_spread", {"max_residual_K": max(residuals) if residuals else None,
                                              "min_spread_K": min(spreads) if spreads else None})
    assert all(results)


def test_zz_series_summary(case_record, fe002):
    """Series for the report figures, key metrics and the Chinese summary of the case."""

    cfg, geo, t_end = fe002["cfg"], fe002["geo"], fe002["t_end"]
    period = fe002["cases"]["nom0"]["period"]
    payload = {"case_id": "FE-002",
               "description": ("Radiator node R of the thermal module (thermal_derivative through sdtwin_sim.coupled with "
                               "sdtwin_sim.earth_flux) against the ISS FE EATCS radiators, loops A and B of the cases "
                               "cold0, nom0 and hot75. Module series on the output grid of the accepted solution; FE "
                               "series on the unique FE output times; the third orbit starts at third_orbit_start_s."),
               "orbit_period_s": period, "t_end_s": t_end, "third_orbit_start_s": t_end - period,
               "solver_settings": {k: cfg["solver"][k] for k in ("method", "rtol", "atol_T_K", "max_step_s",
                                                                 "output_step_s", "environment_step_s",
                                                                 "earth_flux_resolution")},
               "injection": {"C_D_J_K": 100.0, "R_DR_K_W": cfg["injection"]["R_DR_K_W"]},
               "radiator": {"area_one_side_m2": geo["area_m2"], "capacity_J_K": geo["capacity_J_K"]},
               "cases": {}}
    pc = cfg["fe"]["panel_columns"]
    for case in CASES:
        entry = fe002["cases"][case]
        series = entry["series"]
        windows = entry["orbit"].eclipse_windows(0.0, t_end)
        case_payload = {"label_cn": cfg["cases"][case]["label_cn"],
                        "eclipse_windows_s": [[round(a, 4), round(b, 4)] for a, b in windows],
                        "fe_time_s": series["t_s"].tolist(),
                        "fe_panel_Tmin_C": np.round(series[pc["min"]], 4).tolist(),
                        "fe_panel_Tmean_C": np.round(series[pc["mean"]], 4).tolist(),
                        "fe_panel_Tmax_C": np.round(series[pc["max"]], 4).tolist(),
                        "loops": {}}
        for loop in LOOPS:
            run = entry["loops"].get(loop)
            if not _run_ok(run):
                case_payload["loops"][loop] = {"status": _run_status(run)}
                continue
            post = run["post"]
            iR = post["nodes"].index("R")
            case_payload["loops"][loop] = {
                "run_id": run["run_id"],
                "time_s": post["ts"].tolist(),
                "T_R_module_C": np.round(post["T"][:, iR] - KELVIN, 5).tolist(),
                "T_R_independent_C": np.round(post["T_ind_K"] - KELVIN, 5).tolist(),
                "q_into_R_module_W": np.round(post["q_into_R"], 3).tolist(),
                "Q_env_R_module_W": np.round(post["Q_env_R"], 3).tolist(),
                "Q_emit_R_module_W": np.round(post["Q_emit_R"], 3).tolist(),
                "T_R_fe_mean_C": np.round(run["T_fe_C"], 5).tolist(),
                "Q_in_fe_W": np.round(run["q_fe"], 3).tolist(),
                "third_orbit_C": {"module": post["module_stats_C"], "fe": post["fe_stats_C"],
                                  "independent": post["independent_stats_C"]},
            }
        payload["cases"][case] = case_payload
    RESULTS_DIR.mkdir(exist_ok=True)
    SERIES_FILE.write_text(json.dumps(payload, ensure_ascii=False, default=float), encoding="utf-8")
    written = case_record.check(
        "结果归档 报告曲线所需时程写入 FE-002_series.json",
        "六次运行的模块 T_R、独立积分 T_R、进热量、环境吸热、表面辐射与有限元面板平均温度和进热量时程",
        f"{SERIES_FILE.name}, {SERIES_FILE.stat().st_size} bytes", SERIES_FILE.exists())
    case_record.metric("series_file", str(SERIES_FILE.relative_to(THERMAL_DIR)).replace("\\", "/"))
    case_record.metric("total_wall_time_s", round(fe002["wall_s"], 1))

    case_record.summary(_summary_cn(fe002))
    failed = [check["name"] for check in case_record.checks if not check["passed"]]
    case_record.anomalies("无" if not failed else "以下检查未通过：" + "；".join(failed) + "。")
    assert written


def _summary_cn(fe002) -> str:
    """Chinese summary: what was run and the key numbers against the thresholds (report wording rules)."""

    cfg, geo, t_end = fe002["cfg"], fe002["geo"], fe002["t_end"]
    crit, sol = cfg["criteria"], cfg["solver"]
    names = {case: cfg["cases"][case]["label_cn"] for case in CASES}
    period = fe002["cases"]["nom0"]["period"]
    posts = {(case, loop): run["post"] for case, loop, entry, run in _runs(fe002) if _run_ok(run)}
    c_rel = []
    for case in CASES:
        params = fe002["cases"][case]["params"]
        if params is not None:
            nodes = list(params.provenance["node_order"])
            c_rel.append(abs(float(params.C_J_K[nodes.index("R")]) - geo["capacity_J_K"]) / geo["capacity_J_K"])
    parts = [
        "本用例按设计报告式 T3 第六行、式 T4 与式 T5，用 thermal_derivative 经 sdtwin_sim.coupled 与 sdtwin_sim.earth_flux "
        "计算国际空间站舱外主动热控系统散热器的公共散热板温度，设计冷工况、平均环境工况与设计热工况各算回路 A 与回路 B，"
        f"共 {len(CASES) * len(LOOPS)} 次运行，完成 {len(posts)} 次。",
        f"散热板按每个回路 24 块面板建模，单面面积 {num(geo['area_m2'], 3)} m²，两面按本工况白色涂层的吸收率与发射率计算环境吸热与表面辐射；"
        f"热容按式 T5 由面板质量 {num(geo['panel_mass_kg'], 3)} kg 乘比热 900 J·kg⁻¹·K⁻¹ 再加 24 个液氨节点共 "
        f"{num(geo['nh3_capacity_J_K'] / 1e3, 0)} kJ/K 求得 {num(geo['capacity_J_K'] / 1e6, 4)} MJ/K",
    ]
    parts.append(f"，装配所得散热板热容与手算的相对差最大为 {sci(max(c_rel))}。" if c_rel else "，三个工况的参数装配均未完成。")
    parts.append(
        f"有限元散热器进热量按第 9.4 节记录的测试配置经电源设备节点注入，该节点热容 100 J/K，DR 热阻 "
        f"{sci(cfg['injection']['R_DR_K_W'], 0)} K/W，SR、JC、CR 与 BR 取 "
        f"{sci(cfg['auxiliary_nodes']['no_conduction_resistance_K_W'], 0)} K/W 表示不导热。")
    if posts:
        e_full = max(abs(p["E_rel_full"]) for p in posts.values())
        e_orb = max(abs(p["E_rel_orbit3"]) for p in posts.values())
        parts.append(f"到达散热板的累计热量与有限元进热量的相对差全程最大 {sci(e_full)}，第三圈最大 {sci(e_orb)}，"
                     f"判据为 {sci(crit['heat_input_relative'], 0)}。")
    atts = [fe002["cases"][case].get("attitude") for case in CASES]
    if all(att is not None for att in atts):
        cos_worst = max(att["worst"]["cos_module"] for att in atts)
        parts.append(f"姿态四元数使散热板在受晒段侧边对日，在日食段正面对地，模块算得的两面入射余弦与独立计算之差最大 {sci(cos_worst)}。")
    if posts:
        ecl = max(p["eclipse_worst_s"] for p in posts.values())
        across = sum(p["steps_across_boundary"] for p in posts.values())
        first = posts[next(iter(posts))]
        parts.append(
            f"每次运行从有限元初始温度 {num(float(first['T'][0, first['nodes'].index('R')]), 2)} K 起算到 {t_end:.0f} s，"
            f"即有限元计算时段，合 {num(t_end / period, 2)} 个轨道周期，采用第 8 章表 8 中用于时间尺度差别较大情形的 Radau 方法，"
            f"相对容限 {sci(sol['rtol'], 0)}，温度绝对容限 {sci(sol['atol_T_K'], 0)} K，最大步长 {sol['max_step_s']:.0f} s，"
            f"在日食边界与有限元进热量采样时刻分段积分；日食进出时刻与圆柱地影解析值之差最大为 {sci(ecl)} s，"
            + ("没有积分步跨越日食边界。" if across == 0 else f"有 {across} 个积分步跨越日食边界。"))
        env = max(p["env_rel"] for p in posts.values())
        emit = max(p["emit_rel"] for p in posts.values())
        t3 = max(p["T3_rel"] for p in posts.values())
        ind = max(p["ind_max_K"] for p in posts.values())
        parts.append(
            f"散热板环境吸热与独立数值积分的相对差最大为 {sci(env)}，判据为 {sci(crit['environment_relative'], 0)}；"
            f"双面表面辐射与手算的相对差最大为 {sci(emit)}；热容乘温度导数与各支路进热、环境吸热及表面辐射之和的相对差最大为 "
            f"{sci(t3)}；散热板温度与独立积分程序之差最大为 {num(ind, 4)} K，判据为 {num(crit['independent_K'], 2)} K。")
        diffs = {key: p["module_stats_C"]["mean"] - p["fe_stats_C"]["mean"] for key, p in posts.items()}
        means = "；".join(f"{names[case]}模块为 {num(posts[(case, 'A')]['module_stats_C']['mean'], 2)} °C 与 "
                          f"{num(posts[(case, 'B')]['module_stats_C']['mean'], 2)} °C，有限元为 "
                          f"{num(posts[(case, 'A')]['fe_stats_C']['mean'], 2)} °C 与 "
                          f"{num(posts[(case, 'B')]['fe_stats_C']['mean'], 2)} °C"
                          for case in CASES if (case, 'A') in posts and (case, 'B') in posts)
        text = "，".join(f"{names[case]}回路 A 与回路 B 分别为 {num(diffs[(case, 'A')], 2)} K 与 {num(diffs[(case, 'B')], 2)} K"
                        for case in CASES if (case, 'A') in diffs and (case, 'B') in diffs)
        worst = max(abs(v) for v in diffs.values())
        parts.append(f"第三圈时间加权平均温度，回路 A 与回路 B 依次排列，{means}。")
        parts.append(f"模块减有限元三个散热器单元面板平均温度之平均，{text}，绝对值最大 {num(worst, 2)} K，验收门限 "
                     f"{num(crit['acceptance_mean_K'], 0)} K。")
        d_min = [p["module_stats_C"]["min"] - p["fe_stats_C"]["min"] for p in posts.values()]
        d_max = [p["module_stats_C"]["max"] - p["fe_stats_C"]["max"] for p in posts.values()]
        parts.append(f"验收判据只针对平均温度，第三圈最低温度之差为 {num(min(d_min), 2)} 至 {num(max(d_min), 2)} K，"
                     f"最高温度之差为 {num(min(d_max), 2)} 至 {num(max(d_max), 2)} K，有限元按 120 s 输出点统计，模块按已接受解加密统计。")
    rows = loop_difference_rows(fe002)
    if rows:
        mods = [row["module_B_minus_A_K"] for row in rows.values()]
        hands = [row["hand_B_minus_A_K"] for row in rows.values()]
        fe_text = "、".join(num(rows[case]["fe_B_minus_A_K"], 2) for case in CASES if case in rows)
        parts.append(
            f"模块中回路 B 的第三圈平均温度比回路 A 高 {num(min(mods), 2)} 至 {num(max(mods), 2)} K，按两回路进热量差除以线性化辐射热导手算为 "
            f"{num(min(hands), 2)} 至 {num(max(hands), 2)} K，两者之差最大为 "
            f"{num(max(abs(row['module_B_minus_A_K'] - row['hand_B_minus_A_K']) for row in rows.values()), 3)} K，"
            f"判据为不超过 {num(crit['loop_difference_K'], 2)} K；"
            f"有限元回路 B 与回路 A 之差在三个工况依次为 {fe_text} K。")
        if "hot75" in rows:
            row = rows["hot75"]
            parts.append(
                f"设计热工况有限元回路 B 比回路 A 高 {num(row['fe_B_minus_A_K'], 2)} K，比模块多 {num(row['fe_minus_module_K'], 2)} K，"
                "有限元报告把这一差别归于两翼整体转动后上下相叠造成的相互遮挡，设计报告第 4.4 节与第 10 章说明本版不计组件间相互遮挡、"
                "相互辐射与局部温差。")
    cold = coldest_rows(fe002)
    residuals = [abs(value) for row in rows.values() for value in row["residual_K"].values()]
    if cold and residuals:
        lows = [row["mean_minus_coldest_K"] for row in cold.values()]
        spreads = [value for row in cold.values() for value in row["orbit3_max_minus_min_K"]]
        parts.append(
            f"同一时刻有限元最冷面板比散热器平均温度低 {num(min(lows), 1)} 至 {num(max(lows), 1)} K，第三圈各时刻有限元面板最高与最低温度之差为 "
            f"{num(min(spreads), 1)} 至 {num(max(spreads), 1)} K，平均温度残差最大 {num(max(residuals), 2)} K，集总温度不能代替最冷点。")
    return "".join(parts)
