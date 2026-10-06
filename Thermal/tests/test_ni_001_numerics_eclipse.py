"""NI-001 数值计算与日食边界: numerical settings of thermal design chapter 8 (table 8) and chapter 7.

Implements the CASES entry NI-001 of Thermal/test_report/build_test_report_cn.py (requirement TH-01; design basis
chapter 8 table 8 and chapter 7).

Precondition: the FE-001 mean environment case runs.
Inputs: RK45 and Radau; relative tolerance 1e-6 and 1e-8; temperature absolute tolerance 1e-6 K and 1e-8 K; maximum
step 60 s and 10 s; output interval 10 s and 60 s; one load start and stop instant; one step that must be rejected.
Steps: 1 run every combination once and compare the last orbit; 2 check that integration is split at eclipse entry and
exit and at the load start and stop, with no averaging across a boundary; 3 check that the outputs are samples of the
accepted solution at the required instants, independent of the internal step; 4 check that a rejected step writes no
component temperature.
Expected: results converge as the tolerances tighten and RK45 and Radau agree; boundary handling and output sampling
follow chapter 8.
Acceptance: tightening the tolerances 100 times changes the last-orbit temperatures by at most 0.01 K; RK45 and Radau
differ by at most 0.01 K; eclipse entry and exit times are within 1 s; output sampling does not change with the
internal step.

The module runs for real: sdtwin_sim.coupled.run_coupled integrates the six temperatures with SciPy RK45 or Radau,
splits at the eclipse boundaries it locates and at the declared load start and stop, calls prepare_surface_environment
and thermal_derivative at every trial and samples the accepted solution. The FE-001 mean environment case is a
thermal-only run with prescribed ports, so the computing load of Compute01 is a prescribed P_load_W step whose start and
stop are declared input discontinuities. Earth albedo and infrared come from sdtwin_sim.earth_flux records of the
FE-001 environment sampled every 10 s and interpolated (design table 8: declared interpolation on continuous
intervals); one precondition run evaluates the FE-001 EarthFluxModel at every trial and shows that the table
represents it.

References are independent of the module: the closed-form cylindrical shadow times, a hand implementation of T2 to T5
integrated by a fixed-step fourth order Runge-Kutta method written in tests/data/ni_001/ni001_support.py (step
halving bounds its error), the Dormand-Prince 5(4) tableau of the literature for the step that must be rejected, and
the prescribed inputs themselves for the side of each boundary.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from sdtwin_sim import coupled as cp
from sdtwin_sim.earth_flux import earth_flux_record
from thermal import ThermalState, assemble_thermal_parameters
from thermal.types import NODE_ORDER, PATH_ORDER

pytestmark = pytest.mark.case("NI-001")

THERMAL_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data" / "ni_001"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load_support():
    spec = importlib.util.spec_from_file_location("ni001_support", DATA_DIR / "ni001_support.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load_support()
CFG = sup.load_json(DATA_DIR / "ni001_config.json")
SC = CFG["scenario"]
SA = SC["solar_array"]
AUX = SC["auxiliary_nodes"]
LOAD = CFG["load"]
MAT = CFG["matrix"]
TABLE = CFG["earth_flux_table"]
EXACT = CFG["exact_run"]
REJ = CFG["rejected_step"]
REF = CFG["reference"]
CRIT = CFG["criteria"]
T_END = float(SC["t_end_s"])
S0 = float(SC["solar_constant_W_m2"])
EPOCH = datetime.fromisoformat(SC["epoch_utc"])
NN = len(NODE_ORDER)
I_S = NODE_ORDER.index("S")
INITIAL_K = [float(SA["initial_temperature_K"])] + [float(AUX["initial_temperature_K"])] * (NN - 1)
METHODS = tuple(MAT["methods"])
RTOLS = tuple(float(value) for value in MAT["rtol"])
ATOLS = tuple(float(value) for value in MAT["atol_T_K"])
MAX_STEPS = tuple(float(value) for value in MAT["max_step_s"])
OUTPUTS = tuple(float(value) for value in MAT["output_step_s"])
KEYS = tuple((m, r, a, h, o) for m in METHODS for r in RTOLS for a in ATOLS for h in MAX_STEPS for o in OUTPUTS)
R_LOOSE, R_TIGHT = max(RTOLS), min(RTOLS)
A_LOOSE, A_TIGHT = max(ATOLS), min(ATOLS)
EXACT_KEY = (EXACT["method"], float(EXACT["rtol"]), float(EXACT["atol_T_K"]), float(EXACT["max_step_s"]),
             float(EXACT["output_step_s"]))
REJ_KEY = (REJ["method"], float(REJ["rtol"]), float(REJ["atol_T_K"]), float(REJ["max_step_s"]),
           float(REJ["output_step_s"]))
BOUNDARIES = ((float(LOAD["start_s"]), LOAD["start_label"]), (float(LOAD["stop_s"]), LOAD["stop_label"]))
TIGHTEN_K = float(CRIT["tighten_K"])
METHOD_K = float(CRIT["method_K"])
ECLIPSE_S = float(CRIT["eclipse_time_s"])
OUTPUT_K = float(CRIT["output_K"])
OUTCOME: dict = {}


def _label(key) -> str:
    method, rtol, atol, max_step, out = key
    return f"{method} rtol {rtol:g} atol {atol:g} K 最大步长 {max_step:g} s 输出间隔 {out:g} s"


def _values(values) -> str:
    return "、".join(f"{value:.1e}" for value in values)


# ------------------------------------------------------------------------------------------------ scenario


def _load_spec(path: Path):
    """FE model parameter table iss_spec.py (pure data, no side effects)."""

    spec = importlib.util.spec_from_file_location("ni001_iss_spec", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _area_m2(spec) -> float:
    """Front area of the 16 US solar array blankets of the FE geometry (8 wings of 2 blankets), as in FE-001."""

    saw = spec.SAW
    return len(saw["wings"]) * 2 * saw["x_len"] * saw["blanket_w"]


def _components(spec, area: float) -> tuple[list[dict], list[dict]]:
    blanket = spec.MATERIALS["saw_blk"]
    surfaces = [{"surface_id": SA[side]["surface_id"], "area_m2": area, "normal_body": SA[side]["normal_body"],
                 "absorptivity": SA[side]["absorptivity"], "emissivity": SA[side]["emissivity"],
                 "source": SC["source"]} for side in ("front", "back")]
    components = [{
        "instance_id": SA["instance_id"], "node_id": "S", "asset_id": SA["asset_id"],
        "asset_version": SA["asset_version"],
        "materials": [{"material_id": SA["material_id"], "mass_kg": blanket["rho"] * blanket["t"] * area,
                       "cp_J_kgK": blanket["cp"], "source": SC["source"]}],
        "surfaces": surfaces, "temperature_range_K": SA["temperature_range_K"], "ports": ["P_pv_W"],
    }]
    for item in AUX["components"]:
        components.append({
            "instance_id": item["instance_id"], "node_id": item["node_id"],
            "asset_id": f"fe001_aux_{item['instance_id'].lower()}", "asset_version": "1",
            "materials": [{"material_id": f"{item['instance_id']}_material", "mass_kg": item["mass_kg"],
                           "cp_J_kgK": item["cp_J_kgK"], "source": SC["source"]}],
            "surfaces": [dict(surface, source=SC["source"]) for surface in item.get("surfaces", [])],
            "temperature_range_K": AUX["temperature_range_K"], "ports": item["ports"],
        })
    connections = [{"path": "SR", "equivalent_total_resistance_K_W": SC["SR"]["equivalent_total_resistance_K_W"],
                    "includes_contact": SC["SR"]["includes_contact"], "source": SC["source"]}]
    for path, value in AUX["resistances_K_W"].items():
        connections.append({"path": path, "equivalent_total_resistance_K_W": value, "includes_contact": True,
                            "source": SC["source"]})
    return components, connections


def _hand_values(spec, area: float) -> tuple[dict, dict, list[dict]]:
    """T5 by hand: capacitance = sum of mass times specific heat per node, path resistances as given."""

    blanket = spec.MATERIALS["saw_blk"]
    capacitance = {"S": blanket["rho"] * blanket["t"] * area * blanket["cp"]}
    for node in NODE_ORDER[1:]:
        capacitance[node] = math.fsum(item["mass_kg"] * item["cp_J_kgK"] for item in AUX["components"]
                                      if item["node_id"] == node)
    resistance = {"SR": float(SC["SR"]["equivalent_total_resistance_K_W"])}
    resistance.update({path: float(value) for path, value in AUX["resistances_K_W"].items()})
    surfaces = [{"surface_id": SA[side]["surface_id"], "node": "S", "area_m2": area,
                 "normal_body": SA[side]["normal_body"], "absorptivity": SA[side]["absorptivity"],
                 "emissivity": SA[side]["emissivity"]} for side in ("front", "back")]
    for item in AUX["components"]:
        for surface in item.get("surfaces", []):
            surfaces.append({"surface_id": surface["surface_id"], "node": item["node_id"],
                             "area_m2": surface["area_m2"], "normal_body": surface["normal_body"],
                             "absorptivity": surface["absorptivity"], "emissivity": surface["emissivity"]})
    return capacitance, resistance, surfaces


class Scenario:
    """Prescribed inputs of the thermal-only FE-001 run: G with the FE cylindrical shadow, P_pv as 0.073 times the
    direct power on the front (FE-001 rule) and the NI-001 computing load of Compute01 between start and stop."""

    def __init__(self, orbit, area: float) -> None:
        self.orbit = orbit
        self.area = float(area)
        self.on = float(LOAD["start_s"])
        self.off = float(LOAD["stop_s"])
        self.power = float(LOAD["power_W"])
        self.front = np.array(SA["front"]["normal_body"], dtype=float)

    def G(self, t: float) -> float:
        return 0.0 if self.orbit.in_shadow(t) else S0

    def load(self, t: float) -> float:
        return self.power if self.on <= t < self.off else 0.0

    def cos_front(self, t: float) -> float:
        x_axis, y_axis, z_axis = self.orbit.axes(t)
        normal = self.front[0] * x_axis + self.front[1] * y_axis + self.front[2] * z_axis
        return float(normal @ self.orbit.sun_direction(t))

    def ports(self, t: float) -> dict:
        direct_W = self.area * self.G(t) * max(0.0, self.cos_front(t))
        return {"P_pv_W": float(SA["pv_fraction"]) * direct_W, "P_load_W": self.load(t), "Q_B_W": 0.0, "Q_D_W": 0.0}


def _direct_flux(params, orbit, t: float) -> dict:
    return earth_flux_record(
        "NI-001-earth-flux-input", float(t), orbit.position(t), orbit.sun_position(t), orbit.quaternion(t), params,
        albedo=SC["albedo"], olr_W_m2=SC["olr_W_m2"], solar_constant_W_m2=S0, earth_radius_m=orbit.earth_radius_m,
        resolution=tuple(TABLE["resolution"]))


def _earth_flux_table(params, orbit):
    spacing = float(TABLE["spacing_s"])
    times = spacing * np.arange(int(round(T_END / spacing)) + 1)
    albedo, infrared, ids = [], [], None
    for t in times:
        record = _direct_flux(params, orbit, float(t))
        albedo.append(np.array(record["albedo_W_m2"], dtype=float))
        infrared.append(np.array(record["infrared_W_m2"], dtype=float))
        ids = record["surface_ids"]
    return sup.EarthFluxTable(times, ids, np.array(albedo), np.array(infrared))


def _table_fidelity(table, params, orbit) -> dict:
    """Interpolated irradiances against direct sdtwin_sim.earth_flux records at off-grid instants (cell midpoints)."""

    times = table.times[:-1:int(TABLE["check_stride"])] + 0.5 * table.spacing_s
    worst_albedo = worst_infrared = 0.0
    for t in times:
        direct = _direct_flux(params, orbit, float(t))
        albedo, infrared = table.values(float(t))
        worst_albedo = max(worst_albedo, float(np.max(np.abs(albedo - direct["albedo_W_m2"]))))
        worst_infrared = max(worst_infrared, float(np.max(np.abs(infrared - direct["infrared_W_m2"]))))
    return {"check_instants": int(times.size), "albedo_W_m2": worst_albedo, "infrared_W_m2": worst_infrared,
            "albedo_view_factor": worst_albedo / (SC["albedo"] * S0),
            "infrared_view_factor": worst_infrared / SC["olr_W_m2"]}


def _run(ctx: dict, key, *, earth, tag: str, first_step: float | None = None, keep_records: bool = False) -> dict:
    method, rtol, atol, max_step, out = key
    run_id = f"NI-001-{tag}-{method}-rtol{rtol:.0e}-atol{atol:.0e}-h{max_step:g}s-out{out:g}s"
    orbit, scen = ctx["orbit"], ctx["scen"]
    provider = cp.EnvironmentProvider.from_callables(
        run_id=run_id, epoch=EPOCH, parameters=ctx["params"], position=orbit.position,
        sun_position=orbit.sun_position, quaternion=orbit.quaternion, G=scen.G, earth_flux=earth)
    settings = cp.SolverSettings(method=method, rtol=rtol, atol_T_K=atol, max_step_s=max_step, output_step_s=out,
                                 environment_step_s=float(MAT["environment_step_s"]),
                                 event_time_tol_s=float(MAT["event_time_tol_s"]), first_step_s=first_step)
    initial = ThermalState(run_id, 0.0, INITIAL_K)
    records: list = []
    if keep_records:
        hook = records.append
    else:
        def hook(record) -> None:
            records.append((record.time_s, record.solver_id, record.context == "integration"))
    provenance = {
        "case_id": "NI-001", "scenario": f"FE-001 {SC['fe_case']} {SC['label_cn']}", "run_tag": tag,
        "earth_flux": ("FE-001 EarthFluxModel evaluated at every trial" if isinstance(earth, cp.EarthFluxModel)
                       else f"{TABLE['interpolation']} of sdtwin_sim.earth_flux records every {TABLE['spacing_s']} s"),
        "load": {key_: LOAD[key_] for key_ in ("instance_id", "port", "power_W", "start_s", "stop_s")},
        "first_step_s": first_step,
    }
    started = time.perf_counter()
    try:
        archive = cp.run_coupled(ctx["params"], initial, provider, T_END, settings=settings,
                                 prescribed_ports=scen.ports, boundaries_s=list(BOUNDARIES), trial_hook=hook,
                                 provenance=provenance)
        error = None
    except cp.CoupledRunError as exc:
        archive, error = exc.archive, f"{type(exc).__name__}: {exc}"
    run = {"key": key, "tag": tag, "run_id": run_id, "archive": archive, "error": error,
           "wall_s": time.perf_counter() - started, "first_step_s": first_step,
           "earth": "exact" if isinstance(earth, cp.EarthFluxModel) else "table"}
    if keep_records:
        run["records"] = records
        rows = [(record.time_s, record.solver_id, record.context == "integration") for record in records]
    else:
        rows = records
    array = np.array(rows, dtype=float) if rows else np.empty((0, 3))
    run["hook_t"] = array[:, 0]
    run["hook_sid"] = array[:, 1].astype(int)
    run["hook_integration"] = array[:, 2].astype(bool)
    return run


def _completed(run: dict) -> bool:
    archive = run["archive"]
    return (run["error"] is None and archive.status == "completed" and float(archive.t_end_s) == T_END
            and archive.final_thermal_state is not None and archive.final_thermal_state.time_s == T_END)


def _rejected_locate(ctx: dict) -> dict:
    """Instants of the step that must be rejected: the last-orbit eclipse entry of the forced-step run."""

    orbit = ctx["orbit"]
    closed = [t for t, kind in orbit.boundaries(ctx["t0_last"], T_END) if kind == REJ["boundary_kind"]]
    index = int(REJ["boundary_index_in_last_orbit"])
    info: dict = {"t_cf": closed[index] if len(closed) > index else None, "h_force": float(REJ["first_step_s"])}
    archive = ctx["rejected"]["archive"]
    located = [b for b in archive.eclipse_boundaries if b.kind == REJ["boundary_kind"] and b.time_s >= ctx["t0_last"]]
    if len(located) <= index:
        return info
    boundary = located[index]
    t_x = boundary.time_right_s
    info.update(boundary=boundary, t_x=t_x, t_trial_end=t_x + info["h_force"])
    t_old = np.asarray(archive.steps["t_old_s"])
    hits = np.flatnonzero(t_old == t_x)
    if hits.size:
        i0 = int(hits[0])
        info.update(step_index=i0, t_accept_end=float(archive.steps["t_new_s"][i0]),
                    solver_id=int(archive.steps["solver_id"][i0]), attempts=int(archive.steps["attempts"][i0]))
    return info


def _ref_at(ctx: dict, times, which: str = "ref") -> np.ndarray:
    grid = ctx["g_ref"]
    times = np.atleast_1d(np.asarray(times, dtype=float))
    index = np.searchsorted(grid, times)
    index = np.minimum(index, grid.size - 1)
    if not np.array_equal(grid[index], times):
        raise KeyError("reference requested at a time outside its evaluation grid")
    return ctx[which]["T"][index]


def _reference(ctx: dict) -> None:
    orbit, scen = ctx["orbit"], ctx["scen"]
    model = sup.ReferenceModel(capacitance_J_K=ctx["hand_C"], resistance_K_W=ctx["hand_R"],
                               surfaces=ctx["ref_surfaces"], orbit=orbit, solar_constant_W_m2=S0,
                               pv_fraction=SA["pv_fraction"], pv_area_m2=ctx["area_m2"],
                               pv_surface_id=SA["front"]["surface_id"], earth=ctx["table"])
    segments = sup.reference_segments(orbit, 0.0, T_END, (scen.on, scen.off), scen.power)
    out_min = min(OUTPUTS)
    info = ctx.get("rejected_info") or {}
    special = [info[name] for name in ("t_cf", "t_x", "t_trial_end", "t_accept_end") if info.get(name) is not None]
    g_ref = np.unique(np.concatenate([out_min * np.arange(int(round(T_END / out_min)) + 1), ctx["g_last"],
                                      np.array(special, dtype=float)]))
    started = time.perf_counter()
    ref = sup.integrate_rk4(model, segments, np.array(INITIAL_K), g_ref, step_s=float(REF["rk4_step_s"]))
    wall = time.perf_counter() - started
    half = sup.integrate_rk4(model, segments, np.array(INITIAL_K), g_ref, step_s=float(REF["rk4_check_step_s"]))
    ctx.update(model=model, ref_segments=segments, g_ref=g_ref, ref=ref, ref_half=half, ref_wall_s=wall)
    ctx["ref_last"] = _ref_at(ctx, ctx["g_last"])


def _all_runs(ctx: dict) -> list[dict]:
    return [*ctx["runs"].values(), ctx["exact"], ctx["rejected"]]


@pytest.fixture(scope="module")
def ni001():
    started = time.perf_counter()
    spec = _load_spec(THERMAL_DIR / SC["spec_file"])
    summary = sup.load_json(THERMAL_DIR / SC["orbit_record"])
    orbit = sup.FEOrbit(summary["orbit"], spec.ORBIT["R_earth_m"])
    area = _area_m2(spec)
    components, connections = _components(spec, area)
    params = assemble_thermal_parameters(components, connections, None)
    hand_C, hand_R, ref_surfaces = _hand_values(spec, area)
    ctx: dict = {"spec": spec, "summary": summary, "orbit": orbit, "area_m2": area, "params": params,
                 "hand_C": hand_C, "hand_R": hand_R, "ref_surfaces": ref_surfaces, "scen": Scenario(orbit, area)}
    ctx["t0_last"] = T_END - orbit.period_s
    ctx["g_last"] = np.unique(np.concatenate([
        np.arange(math.ceil(ctx["t0_last"]), T_END + 0.5, float(CRIT["last_orbit_grid_s"])), [ctx["t0_last"], T_END]]))
    tic = time.perf_counter()
    ctx["table"] = _earth_flux_table(params, orbit)
    ctx["table_wall_s"] = time.perf_counter() - tic
    ctx["table_fidelity"] = _table_fidelity(ctx["table"], params, orbit)
    flux = ctx["table"].provider_callable()
    earth_model = cp.EarthFluxModel(albedo=SC["albedo"], olr_W_m2=SC["olr_W_m2"], solar_constant_W_m2=S0,
                                    earth_radius_m=orbit.earth_radius_m)
    ctx["exact"] = _run(ctx, EXACT_KEY, earth=earth_model, tag="exact-earth-flux")
    ctx["runs"] = {key: _run(ctx, key, earth=flux, tag="matrix") for key in KEYS}
    ctx["rejected"] = _run(ctx, REJ_KEY, earth=flux, tag="rejected-step", first_step=float(REJ["first_step_s"]),
                           keep_records=True)
    ctx["rejected_info"] = _rejected_locate(ctx)
    _reference(ctx)
    for run in _all_runs(ctx):
        run["last"] = np.asarray(run["archive"].state_at(ctx["g_last"]))[:, :NN]
        run["ref_err_last_K"] = float(np.max(np.abs(run["last"] - ctx["ref_last"])))
    ctx["build_wall_s"] = time.perf_counter() - started
    return ctx


# ------------------------------------------------------------------------------------------------ shared evaluations


def _diff(ctx: dict, key_a, key_b) -> dict:
    a, b = ctx["runs"][key_a], ctx["runs"][key_b]
    if not (_completed(a) and _completed(b)):
        return {"max_K": math.inf, "node": None, "time_s": None, "completed": False, "a": key_a, "b": key_b}
    d = np.abs(a["last"] - b["last"])
    i, j = np.unravel_index(int(np.argmax(d)), d.shape)
    return {"max_K": float(d[i, j]), "node": NODE_ORDER[j], "time_s": float(ctx["g_last"][i]), "completed": True,
            "per_node_K": dict(zip(NODE_ORDER, (float(v) for v in d.max(axis=0)))), "a": key_a, "b": key_b}


def _pairs(kind: str) -> list[tuple]:
    pairs = []
    if kind == "both":
        for m in METHODS:
            for h in MAX_STEPS:
                for o in OUTPUTS:
                    pairs.append(((m, R_LOOSE, A_LOOSE, h, o), (m, R_TIGHT, A_TIGHT, h, o)))
    elif kind == "rtol":
        for m in METHODS:
            for a in ATOLS:
                for h in MAX_STEPS:
                    for o in OUTPUTS:
                        pairs.append(((m, R_LOOSE, a, h, o), (m, R_TIGHT, a, h, o)))
    elif kind == "atol":
        for m in METHODS:
            for r in RTOLS:
                for h in MAX_STEPS:
                    for o in OUTPUTS:
                        pairs.append(((m, r, A_LOOSE, h, o), (m, r, A_TIGHT, h, o)))
    elif kind == "method":
        for r in RTOLS:
            for a in ATOLS:
                for h in MAX_STEPS:
                    for o in OUTPUTS:
                        pairs.append((("RK45", r, a, h, o), ("Radau", r, a, h, o)))
    elif kind == "max_step":
        for m in METHODS:
            for r in RTOLS:
                for a in ATOLS:
                    for o in OUTPUTS:
                        pairs.append(((m, r, a, max(MAX_STEPS), o), (m, r, a, min(MAX_STEPS), o)))
    elif kind == "output":
        for m in METHODS:
            for r in RTOLS:
                for a in ATOLS:
                    for h in MAX_STEPS:
                        pairs.append(((m, r, a, h, min(OUTPUTS)), (m, r, a, h, max(OUTPUTS))))
    return pairs


def _worst(diffs: list[dict]) -> dict:
    return max(diffs, key=lambda item: item["max_K"])


def _expected_boundaries(orbit) -> list[tuple[float, str, str]]:
    """Closed-form eclipse boundaries and declared load instants in time order: (time, source, segment reason)."""

    items = [(t, "eclipse", f"eclipse:{kind}") for t, kind in orbit.boundaries(0.0, T_END)]
    items += [(t, "load", f"declared:{label}") for t, label in BOUNDARIES]
    return sorted(items)


def _stats_text(stats) -> str:
    return (f"接受步 {stats['accepted_steps']}，拒绝步 {stats['rejected_steps']}，函数调用 "
            f"{stats['function_evaluations']}，其中积分 {stats['function_evaluations_by_context']['integration']}、"
            f"输出 {stats['function_evaluations_by_context']['output']}")


# ------------------------------------------------------------------------------------------------ inputs and preconditions


def test_inputs_and_preconditions(ni001, case_record):
    """Precondition: the FE-001 mean environment case runs; inputs of NI-001; Earth-flux table fidelity."""

    ctx = ni001
    spec, orbit, params = ctx["spec"], ctx["orbit"], ctx["params"]
    results = []

    # the scenario is the FE-001 mean environment case
    fe_path = THERMAL_DIR / SC["fe001_config"]
    try:
        fe = sup.load_json(fe_path)
        nom = fe["cases"][SC["fe_case"]]
        pairs = [("label_cn", nom["label_cn"], SC["label_cn"]), ("beta_deg", nom["beta_deg"], SC["beta_deg"]),
                 ("solar_constant_W_m2", nom["solar_constant_W_m2"], SC["solar_constant_W_m2"]),
                 ("albedo", nom["albedo"], SC["albedo"]), ("olr_W_m2", nom["olr_W_m2"], SC["olr_W_m2"]),
                 ("orbit.altitude_m", fe["orbit"]["altitude_m"], SC["altitude_m"]),
                 ("orbit.period_s", fe["orbit"]["period_s"], SC["period_s_rounded"]),
                 ("epoch_utc", fe["epoch_utc"], SC["epoch_utc"]), ("fe.end_time_s", fe["fe"]["end_time_s"], T_END),
                 ("solver.environment_step_s", fe["solver"]["environment_step_s"], SC["fe001_environment_step_s"]),
                 ("solver.event_time_tol_s", fe["solver"]["event_time_tol_s"], SC["fe001_event_time_tol_s"]),
                 ("SR.equivalent_total_resistance_K_W", fe["SR"]["equivalent_total_resistance_K_W"],
                  SC["SR"]["equivalent_total_resistance_K_W"]),
                 ("SR.includes_contact", fe["SR"]["includes_contact"], SC["SR"]["includes_contact"])]
        for name in ("instance_id", "asset_id", "asset_version", "material_id", "front", "back",
                     "areal_heat_capacity_J_m2K", "pv_fraction", "initial_temperature_K", "temperature_range_K"):
            pairs.append((f"solar_array.{name}", fe["solar_array"][name], SA[name]))
        for name in ("temperature_range_K", "initial_temperature_K", "components", "resistances_K_W"):
            pairs.append((f"auxiliary_nodes.{name}", fe["auxiliary_nodes"][name], AUX[name]))
        mismatched = [name for name, theirs, ours in pairs if theirs != ours]
        same_env = (MAT["environment_step_s"] == SC["fe001_environment_step_s"]
                    and MAT["event_time_tol_s"] == SC["fe001_event_time_tol_s"])
        ok = not mismatched and same_env
        actual = (f"与 {SC['fe001_config']} 比较 {len(pairs)} 项，不一致项 {mismatched or '无'}；NI-001 的日食扫描步长 "
                  f"{MAT['environment_step_s']} s 与事件时间容限 {MAT['event_time_tol_s']} s 与 FE-001 相同 {same_env}")
    except Exception as exc:  # noqa: BLE001  (a missing or changed FE-001 file is a failed precondition)
        ok, actual = False, f"读取 {fe_path} 失败：{type(exc).__name__}: {exc}"
    results.append(case_record.check(
        "前提 场景取 FE-001 的平均环境工况",
        "NI-001 的场景数据与 FE-001 配置中平均环境工况 nom0 的环境、轨道、太阳能板、SR 连接、辅助节点、积分时长与历元逐项相同",
        actual, ok))

    fe_env = spec.CASES[SC["fe_case"]]
    altitude = orbit.radius_m - orbit.earth_radius_m
    kepler = 2.0 * math.pi * math.sqrt(orbit.radius_m**3 / spec.ORBIT["mu"])
    env_ok = (fe_env["beta_deg"] == SC["beta_deg"] and fe_env["S_sun"] == S0 and fe_env["albedo"] == SC["albedo"]
              and fe_env["olr"] == SC["olr_W_m2"])
    orbit_ok = (abs(altitude - SC["altitude_m"]) <= 1e-6 and round(orbit.period_s, 1) == SC["period_s_rounded"]
                and abs(orbit.period_s - kepler) <= 1e-3 and abs(orbit.beta_deg() - SC["beta_deg"]) <= 0.01
                and orbit.phase_rad == 0.0 and orbit.radius_m == orbit.summary_radius_m)
    windows = orbit.eclipse_windows(0.0, T_END)
    results.append(case_record.check(
        "前提 平均环境工况的环境与轨道取自有限元参数表与轨道记录",
        "iss_spec CASES nom0 为 β 0°、太阳常数 1371 W/m²、反照率 0.31、地球红外 241 W/m²；有限元轨道函数给出高度 400 km、"
        "周期取一位小数 5553.6 s 且与开普勒周期相差不超过 1 ms、β 0°，自轨道正午起算",
        f"iss_spec nom0：β {fe_env['beta_deg']}°，太阳常数 {fe_env['S_sun']} W/m²，反照率 {fe_env['albedo']}，地球红外 "
        f"{fe_env['olr']} W/m²；轨道半径 {orbit.radius_m:.1f} m，高度 {altitude:.1f} m，周期 {orbit.period_s} s，开普勒周期 "
        f"{kepler:.6f} s，β {orbit.beta_deg():.6f}°，初始相位 {orbit.phase_rad}；{T_END:g} s 内圆柱地影 {len(windows)} 段",
        env_ok and orbit_ok))

    hand_C, hand_R = ctx["hand_C"], ctx["hand_R"]
    c_rel = max(abs(float(params.C_J_K[i]) - hand_C[node]) / hand_C[node] for i, node in enumerate(NODE_ORDER))
    r_ok = all(float(params.R_K_W[i]) == hand_R[path] for i, path in enumerate(PATH_ORDER))
    surfaces = {surface.surface_id: surface for surface in params.surfaces}
    s_ok = all(
        surface["surface_id"] in surfaces and surfaces[surface["surface_id"]].node_id == surface["node"]
        and surfaces[surface["surface_id"]].area_m2 == surface["area_m2"]
        and surfaces[surface["surface_id"]].absorptivity == surface["absorptivity"]
        and surfaces[surface["surface_id"]].emissivity == surface["emissivity"]
        and np.array_equal(surfaces[surface["surface_id"]].normal_body, np.array(surface["normal_body"], dtype=float))
        for surface in ctx["ref_surfaces"]) and len(surfaces) == len(ctx["ref_surfaces"])
    results.append(case_record.check(
        "前提 T5 装配的热容、热阻与表面记录等于手算值",
        "C_J_K 等于各节点质量乘比热之和，相对差不超过 1×10⁻¹²；R_K_W 等于场景给定值；四个外露表面的节点、面积、法向、吸收率与"
        "发射率等于输入值",
        f"热容 {dict(zip(NODE_ORDER, (round(float(v), 3) for v in params.C_J_K)))} J/K，最大相对差 {c_rel:.1e}；热阻 "
        f"{dict(zip(PATH_ORDER, (float(v) for v in params.R_K_W)))} K/W，相同 {r_ok}；表面 {list(surfaces)}，相同 {s_ok}",
        c_rel <= 1e-12 and r_ok and s_ok))
    case_record.metric("model", {"area_m2": ctx["area_m2"], "C_J_K": dict(zip(NODE_ORDER, map(float, params.C_J_K))),
                                 "R_K_W": dict(zip(PATH_ORDER, map(float, params.R_K_W))),
                                 "period_s": orbit.period_s, "t_end_s": T_END, "last_orbit_start_s": ctx["t0_last"]})

    table, fid = ctx["table"], ctx["table_fidelity"]
    tol = float(CRIT["table_view_factor_tol"])
    results.append(case_record.check(
        "前提 反照与地球红外插值输入的精度",
        f"按第 8 章表 8 的同时刻取值与已声明插值：sdtwin_sim.earth_flux 每 {TABLE['spacing_s']:g} s 给出一组记录，取 FE-001 的"
        f"反照率、地球红外、太阳常数、地球半径与积分分辨率；在相邻样点中点与直接计算之差折合视角系数不超过 {tol:g}",
        f"{table.times.size} 组记录，{table.times[0]:g} 至 {table.times[-1]:g} s，生成耗时 {ctx['table_wall_s']:.1f} s；"
        f"{fid['check_instants']} 个中点上反照差最大 {fid['albedo_W_m2']:.2e} W/m²，折合视角系数 "
        f"{fid['albedo_view_factor']:.2e}，红外差最大 {fid['infrared_W_m2']:.2e} W/m²，折合 {fid['infrared_view_factor']:.2e}",
        table.times.size == int(round(T_END / float(TABLE["spacing_s"]))) + 1
        and max(fid["albedo_view_factor"], fid["infrared_view_factor"]) <= tol))
    case_record.metric("earth_flux_table", {"samples": int(table.times.size), "spacing_s": table.spacing_s,
                                            "build_wall_s": ctx["table_wall_s"], **fid})

    exact = ctx["exact"]
    archive = exact["archive"]
    results.append(case_record.check(
        "前提 FE-001 平均环境工况可以运行",
        f"每次试算直接调用 FE-001 的 EarthFluxModel，{_label(EXACT_KEY)}，运行完成并积分到 {T_END:g} s",
        f"状态 {archive.status}，错误 {exact['error']}，终点 {float(archive.t_end_s):g} s，{_stats_text(archive.statistics)}，"
        f"积分段 {archive.statistics['segments']} 个，耗时 {exact['wall_s']:.1f} s",
        _completed(exact)))
    twin = ctx["runs"].get(EXACT_KEY)
    if twin is not None and _completed(twin) and _completed(exact):
        d = np.abs(exact["last"] - twin["last"])
        i, j = np.unravel_index(int(np.argmax(d)), d.shape)
        rep, rep_text = float(d[i, j]), (f"最后一圈 {ctx['g_last'].size} 个时刻六个节点最大差 {d[i, j]:.2e} K，在 "
                                         f"{NODE_ORDER[j]} 节点 {ctx['g_last'][i]:.0f} s；各节点 "
                                         f"{dict(zip(NODE_ORDER, (f'{v:.1e}' for v in d.max(axis=0))))} K")
    else:
        rep, rep_text = math.inf, "对应的插值输入运行未完成"
    results.append(case_record.check(
        "前提 插值输入的运行代表 FE-001 平均环境工况",
        f"同一数值设置下，用插值输入的运行与每次试算直接积分 earth_flux 的运行最后一圈温度之差不超过 "
        f"{CRIT['table_fidelity_K']:g} K，即验收值 0.01 K 的十分之一",
        rep_text, rep <= float(CRIT["table_fidelity_K"])))
    OUTCOME["table_fidelity_K"] = rep
    OUTCOME["table_vf"] = max(fid["albedo_view_factor"], fid["infrared_view_factor"])
    OUTCOME["exact_wall_s"] = exact["wall_s"]
    case_record.metric("exact_run", {"run_id": exact["run_id"], "status": archive.status, "wall_s": exact["wall_s"],
                                     "statistics": {k: archive.statistics[k] for k in (
                                         "accepted_steps", "rejected_steps", "function_evaluations", "segments")},
                                     "table_run_last_orbit_max_diff_K": rep})

    # inputs: 32 combinations with the recorded solver settings
    wrong = []
    for key, run in ctx["runs"].items():
        settings = dict(run["archive"].solver_settings)
        method, rtol, atol, max_step, out = key
        if not (settings["method"] == method and settings["rtol"] == rtol and settings["atol_T_K"] == atol
                and settings["max_step_s"] == max_step and settings["output_step_s"] == out
                and settings["environment_step_s"] == MAT["environment_step_s"]
                and settings["event_time_tol_s"] == MAT["event_time_tol_s"] and settings["first_step_s"] is None):
            wrong.append(_label(key))
    results.append(case_record.check(
        "输入 积分方法、容限、最大步长与输出间隔的全部组合",
        "RK45 与 Radau；相对容限 1×10⁻⁶ 与 1×10⁻⁸；温度绝对容限 1×10⁻⁶ K 与 1×10⁻⁸ K；最大步长 60 s 与 10 s；输出间隔 10 s 与 "
        "60 s；32 种组合各一次，归档的求解设置与要求相同",
        f"{len(ctx['runs'])} 次运行，不同组合 {len(set(ctx['runs']))} 种，设置不符 {wrong or '无'}；日食扫描步长 "
        f"{MAT['environment_step_s']} s，事件时间容限 {MAT['event_time_tol_s']} s",
        len(ctx["runs"]) == 32 and len(set(ctx["runs"])) == 32 and not wrong))

    scen = ctx["scen"]
    declared_ok, closest_eclipse, on_grid = True, math.inf, False
    for run in _all_runs(ctx):
        declared = [(item["time_s"], item["label"]) for item in run["archive"].provenance["declared_boundaries"]]
        declared_ok &= declared == [(t, f"declared:{label}") for t, label in BOUNDARIES]
    for t, _label_ in BOUNDARIES:
        closest_eclipse = min(closest_eclipse, min(abs(t - b) for b, _ in orbit.boundaries(0.0, T_END)))
        on_grid |= any(abs(t / step - round(t / step)) < 1e-12 for step in OUTPUTS)
    in_last = all(ctx["t0_last"] < t < T_END and scen.G(t) > 0.0 for t, _ in BOUNDARIES)
    results.append(case_record.check(
        "输入 一个负载启动与停止时刻",
        f"Compute01 的计算负载 {LOAD['power_W']:g} W 自 {LOAD['start_s']} s 启动、{LOAD['stop_s']} s 停止，作为 P_load_W 的"
        "规定输入；两个时刻作为输入不连续点交给联合运行，位于最后一圈的日照段，不在输出时刻上，离日食边界超过 60 s",
        f"全部运行的归档记录两个声明边界 {declared_ok}；两时刻位于最后一圈日照段 {in_last}；离最近日食边界 "
        f"{closest_eclipse:.1f} s；落在输出时刻上 {on_grid}",
        declared_ok and in_last and closest_eclipse > 60.0 and not on_grid))
    OUTCOME["load"] = dict(LOAD)
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 1


def test_step1_every_combination_last_orbit(ni001, case_record):
    """Step 1 and acceptance: tightening 100 times, RK45 against Radau, convergence to the independent reference."""

    ctx = ni001
    runs = ctx["runs"]
    results = []
    failed = [_label(key) for key, run in runs.items() if not _completed(run)]
    walls = [run["wall_s"] for run in runs.values()]
    accepted = [run["archive"].statistics["accepted_steps"] for run in runs.values()]
    results.append(case_record.check(
        "步骤1 每种组合各算一次",
        f"32 次运行全部完成并积分到 {T_END:g} s，取最后一圈 {ctx['t0_last']:.2f} 至 {T_END:g} s 比较六个节点温度，比较时刻为"
        f"每 1 s 一个，共 {ctx['g_last'].size} 个",
        f"未完成 {failed or '无'}；每次耗时 {min(walls):.1f} 至 {max(walls):.1f} s，合计 {sum(walls):.0f} s；接受步 "
        f"{min(accepted)} 至 {max(accepted)} 个",
        not failed))

    over, method_bad, largest, fewest = [], [], defaultdict(float), defaultdict(lambda: math.inf)
    jacobians = {"RK45": 0, "Radau": 0}
    for key, run in runs.items():
        archive = run["archive"]
        widths = np.asarray(archive.steps["t_new_s"]) - np.asarray(archive.steps["t_old_s"])
        if widths.size == 0 or float(widths.max()) > key[3] + 1e-9:
            over.append(_label(key))
        largest[key[3]] = max(largest[key[3]], float(widths.max()) if widths.size else math.inf)
        fewest[key[3]] = min(fewest[key[3]], int(widths.size))
        stats = archive.statistics
        implicit = stats["solver_njev"] > 0 and stats["solver_nlu"] > 0
        jacobians[key[0]] = jacobians.get(key[0], 0) + int(stats["solver_nlu"])
        if (key[0] == "Radau") != implicit:
            method_bad.append(_label(key))
    h_small = min(MAX_STEPS)
    binding = fewest[h_small] >= int(T_END / h_small)
    results.append(case_record.check(
        "步骤1 积分方法与最大步长按设置执行",
        "每次运行的已接受步长都不超过所设最大步长；最大步长 10 s 的运行接受步数不少于积分时长除以 10 s；Radau 运行有雅可比"
        "矩阵计算与 LU 分解，RK45 运行没有",
        f"超过最大步长的运行 {over or '无'}；最大步长 60 s 的运行最长一步 {largest[max(MAX_STEPS)]:.9f} s，10 s 的运行最长一步 "
        f"{largest[h_small]:.9f} s，接受步至少 {fewest[h_small]} 个，积分时长除以 10 s 为 {T_END / h_small:.0f}；LU 分解次数合计"
        f" RK45 {jacobians['RK45']} 次，Radau {jacobians['Radau']} 次；方法不符 {method_bad or '无'}",
        not over and binding and not method_bad))

    tighten = {kind: [_diff(ctx, a, b) for a, b in _pairs(kind)] for kind in ("both", "rtol", "atol")}
    names = {"both": "相对容限与温度绝对容限同时", "rtol": "相对容限单独", "atol": "温度绝对容限单独"}
    for kind in ("both", "rtol", "atol"):
        diffs = tighten[kind]
        worst = _worst(diffs)
        results.append(case_record.check(
            f"步骤1 验收 {names[kind]}收紧 100 倍后最后一圈温度变化",
            f"{len(diffs)} 对只差容限的运行，最后一圈六个节点逐时刻温度差的最大值都不超过 {TIGHTEN_K:g} K",
            f"最大 {worst['max_K']:.2e} K，出现在 {_label(worst['a'])} 与收紧后的运行之间，{worst['node']} 节点 "
            f"{worst['time_s']} s；各对最大值 {_values(item['max_K'] for item in diffs)} K",
            all(item["completed"] and item["max_K"] <= TIGHTEN_K for item in diffs)))
        case_record.metric(f"tighten_{kind}", [{"loose": _label(item["a"]), "tight": _label(item["b"]),
                                                 "max_K": item["max_K"], "node": item["node"],
                                                 "time_s": item["time_s"]} for item in diffs])
    OUTCOME["tighten"] = {kind: _worst(diffs)["max_K"] for kind, diffs in tighten.items()}
    OUTCOME["tighten_worst"] = _worst(tighten["both"])

    methods = [_diff(ctx, a, b) for a, b in _pairs("method")]
    worst = _worst(methods)
    results.append(case_record.check(
        "步骤1 验收 RK45 与 Radau 最后一圈温度之差",
        f"16 种容限、最大步长与输出间隔设置下，RK45 与 Radau 最后一圈六个节点逐时刻温度差的最大值都不超过 {METHOD_K:g} K",
        f"最大 {worst['max_K']:.2e} K，在 {_label(worst['a'])} 与对应 Radau 运行之间，{worst['node']} 节点 "
        f"{worst['time_s']} s；各设置最大值 {_values(item['max_K'] for item in methods)} K",
        all(item["completed"] and item["max_K"] <= METHOD_K for item in methods)))
    case_record.metric("rk45_vs_radau", [{"settings": _label(item["a"])[5:], "max_K": item["max_K"],
                                          "node": item["node"], "time_s": item["time_s"]} for item in methods])
    OUTCOME["method_K"] = worst["max_K"]
    OUTCOME["method_worst"] = worst

    ref, half = ctx["ref"]["T"], ctx["ref_half"]["T"]
    halving = float(np.max(np.abs(ref - half)))
    results.append(case_record.check(
        "步骤1 独立参考解自身的步长收敛",
        f"手算 T2 至 T5 在解析日食与负载分段上用四阶龙格库塔法积分，步长 {REF['rk4_step_s']:g} s 与 "
        f"{REF['rk4_check_step_s']:g} s 两次结果之差不超过 {CRIT['reference_agreement_K']:g} K",
        f"{ctx['g_ref'].size} 个时刻六个节点最大差 {halving:.2e} K；{ctx['ref']['steps']} 步，耗时 {ctx['ref_wall_s']:.1f} s；"
        f"分段 {len(ctx['ref_segments'])} 个",
        halving <= float(CRIT["reference_agreement_K"])))
    OUTCOME["ref_halving_K"] = halving

    groups, rows, ok = {}, [], True
    for m in METHODS:
        for h in MAX_STEPS:
            for o in OUTPUTS:
                loose = runs[(m, R_LOOSE, A_LOOSE, h, o)]["ref_err_last_K"]
                tight = runs[(m, R_TIGHT, A_TIGHT, h, o)]["ref_err_last_K"]
                groups[(m, h, o)] = (loose, tight)
                good = tight <= loose + halving
                ok &= good
                rows.append(f"{m} 最大步长 {h:g} s 输出 {o:g} s：{loose:.1e} 收紧后 {tight:.1e} K")
    errors = {key: run["ref_err_last_K"] for key, run in runs.items()}
    loose_max = max(errors[key] for key in KEYS if key[1] == R_LOOSE and key[2] == A_LOOSE)
    tight_max = max(errors[key] for key in KEYS if key[1] == R_TIGHT and key[2] == A_TIGHT)
    all_within = max(errors.values()) <= TIGHTEN_K
    results.append(case_record.check(
        "步骤1 预期 结果随容限收紧而收敛，RK45 与 Radau 一致",
        "每种方法、最大步长与输出间隔下，容限收紧 100 倍后与独立参考解的最后一圈最大温差不增大，允许参考解自身误差；收紧后的最大"
        f"温差小于收紧前；32 次运行与参考解之差都不超过 {TIGHTEN_K:g} K",
        f"{'；'.join(rows)}；收紧前最大 {loose_max:.2e} K，收紧后最大 {tight_max:.2e} K，全部运行最大 "
        f"{max(errors.values()):.2e} K",
        ok and tight_max < loose_max and all_within))
    case_record.metric("reference_error_last_orbit_K", {_label(key): value for key, value in errors.items()})
    OUTCOME.update(ref_loose_K=loose_max, ref_tight_K=tight_max, ref_all_K=max(errors.values()))

    s_stats = {}
    for key, run in runs.items():
        values = run["last"][:, I_S]
        s_stats[_label(key)] = {"min_K": float(values.min()), "max_K": float(values.max()),
                                "mean_K": float(np.trapezoid(values, ctx["g_last"]) / (ctx["g_last"][-1] - ctx["g_last"][0]))}
    case_record.metric("last_orbit_T_S", s_stats)
    reference_S = ctx["ref_last"][:, I_S]
    OUTCOME["ref_S"] = {"min": float(reference_S.min()), "max": float(reference_S.max()),
                        "mean": float(np.trapezoid(reference_S, ctx["g_last"]) / (ctx["g_last"][-1] - ctx["g_last"][0]))}
    OUTCOME["walls"] = (min(walls), max(walls), sum(walls))
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 2


def test_step2_eclipse_and_load_boundaries(ni001, case_record):
    """Step 2: segmentation at eclipse entry and exit and at the load start and stop, no averaging across them."""

    ctx = ni001
    orbit, scen = ctx["orbit"], ctx["scen"]
    runs = _all_runs(ctx)
    expected = _expected_boundaries(orbit)
    closed = orbit.boundaries(0.0, T_END)
    results = []

    worst_err, kinds_ok, exact_ok = 0.0, True, True
    for run in runs:
        located = run["archive"].eclipse_boundaries
        if [b.kind for b in located] != [kind for _, kind in closed]:
            kinds_ok = False
            continue
        for b, (t_cf, _) in zip(located, closed):
            worst_err = max(worst_err, abs(b.time_s - t_cf))
            sides = (scen.G(b.time_left_s) > 0.0) == (b.phase_before == "sunlit") and \
                    (scen.G(b.time_right_s) > 0.0) == (b.phase_after == "sunlit")
            exact_ok &= b.time_right_s == math.nextafter(b.time_left_s, math.inf) and sides
    sample = runs[0]["archive"].eclipse_boundaries
    results.append(case_record.check(
        "步骤2 验收 日食进出时刻与圆柱地影解析值之差",
        f"34 次运行定位的日食进出时刻与圆柱地影闭式解之差不超过 {ECLIPSE_S:g} s，边界两侧为相邻浮点数，左侧与右侧的 G 分别属于"
        "边界前后的状态",
        f"解析进出时刻 {[round(t, 6) for t, _ in closed]} s，模块 {[round(b.time_s, 6) for b in sample]} s；种类与顺序一致 "
        f"{kinds_ok}，最大差 {worst_err:.2e} s；左右时刻相邻且两侧 G 正确 {exact_ok}",
        kinds_ok and exact_ok and worst_err <= ECLIPSE_S))
    OUTCOME["eclipse_err_s"] = worst_err
    OUTCOME["n_eclipse"] = len(closed)
    case_record.metric("eclipse_boundaries", {"closed_form_s": [t for t, _ in closed],
                                              "module_s": [b.time_s for b in sample],
                                              "max_error_s_all_runs": worst_err})

    straddle, analytic_straddle, outside = 0, 0, 0
    margin = float(CRIT["analytic_margin_s"])
    for run in runs:
        archive = run["archive"]
        t_old = np.asarray(archive.steps["t_old_s"])
        t_new = np.asarray(archive.steps["t_new_s"])
        instants = [moment for b in archive.eclipse_boundaries for moment in (b.time_left_s, b.time_right_s)]
        instants += [t for t, _ in BOUNDARIES]
        for moment in instants:
            straddle += int(np.count_nonzero((t_old < moment) & (t_new > moment)))
        for moment, _source, _reason in expected:
            analytic_straddle += int(np.count_nonzero((t_old < moment - margin) & (t_new > moment + margin)))
        starts = np.array([segment["start_s"] for segment in archive.segments])
        ends = np.array([segment["end_s"] for segment in archive.segments])
        k = np.searchsorted(starts, t_old, side="right") - 1
        outside += int(np.count_nonzero((k < 0) | (t_new > ends[np.maximum(k, 0)])))
    steps_total = sum(len(run["archive"].steps["t_old_s"]) for run in runs)
    results.append(case_record.check(
        "步骤2 没有积分步跨越日食或负载启停边界",
        "全部已接受积分步都不包含日食边界左右时刻与负载启停时刻；以解析时刻前后各 1 μs 判别也没有跨越；每一步都在一个积分段内",
        f"34 次运行共 {steps_total} 个已接受步；跨越模块边界时刻的步 {straddle} 个，跨越解析时刻的步 {analytic_straddle} 个，"
        f"不在单一积分段内的步 {outside} 个",
        straddle == 0 and analytic_straddle == 0 and outside == 0))

    bad_segments = []
    for run in runs:
        archive = run["archive"]
        segments = list(archive.segments)
        located = list(archive.eclipse_boundaries)
        problems = []
        if len(segments) != len(expected) + 1:
            problems.append(f"积分段 {len(segments)} 个")
        else:
            if segments[0]["start_s"] != 0.0 or segments[0]["start_reasons"] != ["run_start"]:
                problems.append("首段")
            if segments[-1]["end_s"] != T_END or segments[-1]["end_reasons"] != ["run_end"]:
                problems.append("末段")
            eclipse_index = 0
            for i, (moment, source, reason) in enumerate(expected, start=1):
                previous, segment = segments[i - 1], segments[i]
                if segment["start_reasons"] != [reason] or previous["end_reasons"] != [reason]:
                    problems.append(f"第 {i} 段原因 {segment['start_reasons']}")
                if source == "eclipse":
                    b = located[eclipse_index]
                    eclipse_index += 1
                    left, right = b.time_left_s, b.time_right_s
                else:
                    left, right = math.nextafter(moment, -math.inf), math.nextafter(moment, math.inf)
                if previous["end_s"] != left or segment["start_s"] != right:
                    problems.append(f"第 {i} 段分界 {previous['end_s']!r} 与 {segment['start_s']!r}")
            for segment in segments:
                if not segment["integrated"] or segment["reached_s"] != segment["end_s"]:
                    problems.append(f"第 {segment['index']} 段未积分到段末")
        if problems:
            bad_segments.append((run["run_id"], problems))
    segs = list(runs[0]["archive"].segments)
    results.append(case_record.check(
        "步骤2 积分在日食与负载启停边界处分段",
        f"每次运行有 {len(expected) + 1} 个积分段，按时间依次在 6 个日食边界与负载启动、停止处分段；日食边界前一段止于边界左"
        "时刻、后一段始于右时刻；负载启停前一段止于指令时刻前一个浮点数、后一段始于后一个浮点数；每段积分到段末",
        f"不符合的运行 {bad_segments or '无'}；段起点原因 {[segment['start_reasons'][0] for segment in segs]}",
        not bad_segments))

    load_rows, load_ok = [], True
    for t_cmd, label in BOUNDARIES:
        seen = None
        for run in runs:
            archive = run["archive"]
            segments = list(archive.segments)
            index = [i for i, segment in enumerate(segments) if segment["start_reasons"] == [f"declared:{label}"]]
            if len(index) != 1:
                load_ok = False
                continue
            before, after = segments[index[0] - 1]["end_s"], segments[index[0]]["start_s"]
            times = np.asarray(archive.accepted["time_s"])
            kinds = archive.accepted["kind"]
            states = np.asarray(archive.accepted["state"])
            i_b = np.flatnonzero(times == before)
            i_a = np.flatnonzero(times == after)
            good = (i_b.size == 1 and i_a.size == 1 and kinds[int(i_b[0])] == "integration"
                    and kinds[int(i_a[0])] == "segment_start"
                    and np.array_equal(states[int(i_b[0])], states[int(i_a[0])])
                    and 0.0 < t_cmd - before <= 2 * math.ulp(t_cmd) and 0.0 < after - t_cmd <= 2 * math.ulp(t_cmd))
            load_ok &= bool(good)
            seen = (before, after)
        if seen is None:
            load_rows.append(f"{label} {t_cmd} s：没有找到以该时刻为起点的积分段")
        else:
            load_rows.append(f"{label} {t_cmd} s：前一段止于 {seen[0]!r} s，后一段始于 {seen[1]!r} s，与指令时刻相差 "
                             f"{t_cmd - seen[0]:.1e} s 与 {seen[1] - t_cmd:.1e} s")
    results.append(case_record.check(
        "步骤2 负载启停在指令时刻分段",
        "34 次运行在负载启动与停止时刻分段，两侧已接受状态与指令时刻相差一个浮点间隔，前一段末状态原样作为后一段初值",
        "；".join(load_rows) + f"；全部运行符合 {load_ok}", load_ok))
    OUTCOME["load_cut_s"] = max(math.ulp(t) for t, _ in BOUNDARIES)

    solvers, mixed_phase, mixed_load, out_of_segment, evaluations = 0, 0, 0, 0, 0
    examples = []
    for run in runs:
        archive = run["archive"]
        mask = run["hook_integration"]
        t_all, sid_all = run["hook_t"][mask], run["hook_sid"][mask]
        starts = np.array([segment["start_s"] for segment in archive.segments])
        ends = np.array([segment["end_s"] for segment in archive.segments])
        for sid in np.unique(sid_all):
            times = np.unique(t_all[sid_all == sid])
            solvers += 1
            evaluations += int(np.count_nonzero(sid_all == sid))
            phases = {scen.G(float(moment)) > 0.0 for moment in times}
            loads = {scen.load(float(moment)) for moment in times}
            k = int(np.searchsorted(starts, times[0], side="right") - 1)
            inside = k >= 0 and times[0] >= starts[k] and times[-1] <= ends[k]
            mixed_phase += len(phases) > 1
            mixed_load += len(loads) > 1
            out_of_segment += not inside
            if len(phases) > 1 or len(loads) > 1 or not inside:
                examples.append((run["run_id"], int(sid), float(times[0]), float(times[-1])))
    hook_vs_stats = all(int(np.count_nonzero(run["hook_integration"]))
                        == run["archive"].statistics["function_evaluations_by_context"]["integration"] for run in runs)
    results.append(case_record.check(
        "步骤2 同一积分步的全部试算位于边界同一侧，没有跨越边界后平均",
        "试算回调记录的每个积分器的全部试算时刻位于同一积分段内，按规定输入判断全部处于同一日照状态与同一负载功率；回调记录的"
        "积分试算次数等于运行统计",
        f"34 次运行 {solvers} 个积分器、{evaluations} 次积分试算；跨日照状态的积分器 {mixed_phase} 个，跨负载功率的 "
        f"{mixed_load} 个，超出积分段的 {out_of_segment} 个 {examples[:3] or ''}；回调次数与统计一致 {hook_vs_stats}",
        mixed_phase == 0 and mixed_load == 0 and out_of_segment == 0 and hook_vs_stats))
    OUTCOME.update(solvers=solvers, evaluations=evaluations, straddle=straddle + analytic_straddle,
                   steps_total=steps_total, n_segments=len(expected) + 1)
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 3


def test_step3_output_sampling(ni001, case_record):
    """Step 3 and acceptance: outputs sampled on the accepted solution at the required instants."""

    ctx = ni001
    runs = ctx["runs"]
    scen, model = ctx["scen"], ctx["model"]
    results = []

    grid_bad = []
    for key, run in runs.items():
        out = key[4]
        expected = out * np.arange(int(round(T_END / out)) + 1)
        if not np.array_equal(np.asarray(run["archive"].time_s), expected):
            grid_bad.append(_label(key))
    results.append(case_record.check(
        "步骤3 输出时刻为所需的固定间隔时刻",
        f"输出间隔 10 s 的运行在 0、10、20 至 {T_END:g} s 共 {int(T_END / 10) + 1} 个时刻输出，60 s 的运行在 0、60 至 "
        f"{T_END:g} s 共 {int(T_END / 60) + 1} 个时刻输出，与方法、容限和最大步长无关，逐位相同",
        f"32 次运行中不符 {grid_bad or '无'}", not grid_bad))

    pair_rows, pair_ok = [], True
    for key_10, key_60 in _pairs("output"):
        a, b = runs[key_10]["archive"], runs[key_60]["archive"]
        ratio = int(round(key_60[4] / key_10[4]))
        same_steps = all(np.array_equal(np.asarray(a.steps[name]), np.asarray(b.steps[name]))
                         for name in ("t_old_s", "t_new_s", "attempts"))
        same_states = (np.array_equal(np.asarray(a.accepted["time_s"]), np.asarray(b.accepted["time_s"]))
                       and np.array_equal(np.asarray(a.accepted["state"]), np.asarray(b.accepted["state"])))
        same_samples = (np.array_equal(np.asarray(a.time_s)[::ratio], np.asarray(b.time_s))
                        and np.array_equal(np.asarray(a.temperature_K)[::ratio], np.asarray(b.temperature_K)))
        same_count = (a.statistics["function_evaluations_by_context"]["integration"]
                      == b.statistics["function_evaluations_by_context"]["integration"])
        good = same_steps and same_states and same_samples and same_count
        pair_ok &= good
        if not good:
            pair_rows.append(f"{_label(key_10)}：步 {same_steps}，状态 {same_states}，样点 {same_samples}，试算 {same_count}")
    results.append(case_record.check(
        "步骤3 输出间隔不改变内部积分步",
        "其余设置相同时，输出间隔 10 s 与 60 s 的两次运行的已接受步起止时刻、尝试次数、已接受状态与积分试算次数逐位相同，"
        "共同输出时刻的温度逐位相同",
        f"16 对运行全部逐位相同 {pair_ok}；不同之处 {pair_rows or '无'}", pair_ok))

    on_solution_bad, inside_total, samples_total = [], 0, 0
    for key, run in runs.items():
        archive = run["archive"]
        times = np.asarray(archive.time_s)
        if not np.array_equal(np.asarray(archive.temperature_K), np.asarray(archive.state_at(times))[:, :NN]):
            on_solution_bad.append(_label(key))
        t_old = np.asarray(archive.steps["t_old_s"])
        t_new = np.asarray(archive.steps["t_new_s"])
        k = np.searchsorted(t_old, times, side="right") - 1
        valid = k >= 0
        inside = valid & (times > t_old[np.maximum(k, 0)]) & (times < t_new[np.maximum(k, 0)])
        inside_total += int(np.count_nonzero(inside))
        samples_total += int(times.size)
    base_key = (METHODS[0], R_LOOSE, A_LOOSE, max(MAX_STEPS), min(OUTPUTS))
    base = runs[base_key]["archive"]
    results.append(case_record.check(
        "步骤3 输出取自已接受解",
        "每个输出温度等于已接受解在该时刻的值；输出时刻多数落在已接受步内部，由该步的连续解取值，积分器不为输出时刻缩步",
        f"32 次运行输出与已接受解不同的 {on_solution_bad or '无'}；{samples_total} 个输出样点中 {inside_total} 个落在已接受步"
        f"内部；例如 {_label(base_key)} 有 {base.statistics['accepted_steps']} 个接受步与 {base.time_s.size} 个输出样点",
        not on_solution_bad and inside_total > samples_total // 2))

    worst_q, worst_dT, port_bad, g_bad, invalid = 0.0, 0.0, 0, 0, 0
    path_index = {path: (NODE_ORDER.index(a), NODE_ORDER.index(b)) for path, (a, b) in sup.PATH_ENDS.items()}
    C = np.array([ctx["hand_C"][node] for node in NODE_ORDER])
    for key, run in runs.items():
        archive = run["archive"]
        times = np.asarray(archive.time_s)
        T = np.asarray(archive.temperature_K)
        invalid += int(np.count_nonzero(~np.asarray(archive.sample_valid)))
        q = np.asarray(archive.q_W)
        for j, path in enumerate(PATH_ORDER):
            a, b = path_index[path]
            hand = (T[:, a] - T[:, b]) / ctx["hand_R"][path]
            worst_q = max(worst_q, float(np.max(np.abs(q[:, j] - hand) / np.maximum(np.abs(hand), 1.0))))
        ports = archive.ports_W
        G = np.asarray(archive.environment["G_W_m2"])
        dT = np.asarray(archive.dT_dt_K_s)
        for i, moment in enumerate(times):
            moment = float(moment)
            prescribed = scen.ports(moment)
            port_bad += int(any(float(ports[name][i]) != prescribed[name] for name in prescribed))
            g_bad += int(float(G[i]) != scen.G(moment))
            lit = scen.G(moment) > 0.0
            terms = model.terms(moment, T[i], lit, scen.load(moment))
            rate = model.rates(terms)
            gross = (float(np.sum(np.abs(terms["Q_env"])) + np.sum(np.abs(terms["Q_emit"]))) + abs(terms["P_pv"])
                     + abs(terms["P_load"]) + sum(abs(v) for v in terms["q"].values()) + 1.0)
            worst_dT = max(worst_dT, float(np.max(np.abs(C * (dT[i] - rate)))) / gross)
    results.append(case_record.check(
        "步骤3 输出样点的派生量在样点时刻按样点状态计算",
        "每个输出样点的热流等于样点温度按 T2 手算值，相对差不超过 1×10⁻¹²；四个功率端口与 G 等于该时刻的规定输入；温度导数"
        "等于按 T3 与 T4 手算的值，残差与各项绝对值之和之比不超过 1×10⁻⁹；没有无效样点",
        f"热流最大相对差 {worst_q:.1e}；端口不符 {port_bad} 个，G 不符 {g_bad} 个；导数残差比最大 {worst_dT:.1e}；无效样点 "
        f"{invalid} 个",
        worst_q <= 1e-12 and port_bad == 0 and g_bad == 0 and worst_dT <= 1e-9 and invalid == 0))
    OUTCOME["derived"] = {"q_rel": worst_q, "dT_rel": worst_dT}

    worst_ref, worst_key = 0.0, None
    for key, run in runs.items():
        archive = run["archive"]
        err = float(np.max(np.abs(np.asarray(archive.temperature_K) - _ref_at(ctx, archive.time_s))))
        run["ref_err_output_K"] = err
        if err >= worst_ref:
            worst_ref, worst_key = err, key
    results.append(case_record.check(
        "步骤3 输出样点与独立参考解之差",
        f"32 次运行全部输出样点六个节点温度与独立参考解之差不超过 {OUTPUT_K:g} K",
        f"最大 {worst_ref:.2e} K，在 {_label(worst_key)}", worst_ref <= OUTPUT_K))
    OUTCOME["output_ref_K"] = worst_ref

    rows, ok, worst = [], True, 0.0
    for key_a, key_b in _pairs("max_step"):
        a, b = runs[key_a]["archive"], runs[key_b]["archive"]
        same_times = np.array_equal(np.asarray(a.time_s), np.asarray(b.time_s))
        d = float(np.max(np.abs(np.asarray(a.temperature_K) - np.asarray(b.temperature_K)))) if same_times else math.inf
        steps = (a.statistics["accepted_steps"], b.statistics["accepted_steps"])
        worst = max(worst, d)
        ok &= same_times and d <= OUTPUT_K
        rows.append(f"{key_a[0]} rtol {key_a[1]:g} atol {key_a[2]:g} 输出 {key_a[4]:g} s：接受步 {steps[0]} 与 {steps[1]}，"
                    f"差 {d:.1e} K")
    results.append(case_record.check(
        "步骤3 验收 输出采样不随内部步长改变",
        f"其余设置相同时，最大步长 60 s 与 10 s 的运行输出时刻逐位相同，同一时刻输出温度之差不超过 {OUTPUT_K:g} K",
        f"16 对中最大差 {worst:.2e} K；{'；'.join(rows)}", ok))
    OUTCOME["output_maxstep_K"] = worst
    case_record.metric("output_sampling", {"max_step_pairs_max_K": worst, "reference_max_K": worst_ref,
                                           "samples_inside_steps": inside_total, "samples_total": samples_total})
    assert all(results)


# ------------------------------------------------------------------------------------------------ step 4


def _recount_rk45(records, archive, construction_evaluations: int) -> dict:
    """Attempts per accepted step counted from the trial hook alone.

    For RK45 every attempt from (t, y) with step h evaluates the model at t + c_i h for the five stages after the first
    and once more at t + h with the new state; the solver's construction evaluates it ``construction_evaluations``
    times. An attempt is accepted when its end time is the end of the next accepted step of that solver.
    """

    by_solver: dict[int, list] = defaultdict(list)
    for record in records:
        if record.context == "integration":
            by_solver[record.solver_id].append(record)
    ends: dict[int, list] = defaultdict(list)
    for sid, t_new in zip(np.asarray(archive.steps["solver_id"]), np.asarray(archive.steps["t_new_s"])):
        ends[int(sid)].append(float(t_new))
    attempts, rejected, anomalies = [], [], []
    for sid, recs in by_solver.items():
        body = recs[construction_evaluations:]
        if len(body) % 6:
            anomalies.append(sid)
        k, count, t_start = 0, 0, recs[0].time_s
        for i in range(0, len(body) - len(body) % 6, 6):
            group = body[i:i + 6]
            count += 1
            if k < len(ends[sid]) and group[-1].time_s == ends[sid][k]:
                attempts.append(count)
                k, count, t_start = k + 1, 0, group[-1].time_s
            else:
                rejected.append({"solver_id": sid, "t_start": t_start, "t_end": group[-1].time_s,
                                 "times": [record.time_s for record in group], "end_record": group[-1]})
        if k != len(ends[sid]) or count:
            anomalies.append(sid)
    return {"attempts": attempts, "rejected": rejected, "anomalies": anomalies}


def test_step4_rejected_step_writes_no_temperature(ni001, case_record):
    """Step 4: a step that must be rejected leaves no component temperature; step statistics and the trial hook."""

    ctx = ni001
    run = ctx["rejected"]
    archive = run["archive"]
    info = ctx["rejected_info"]
    scen, model = ctx["scen"], ctx["model"]
    results = []
    h_force = float(REJ["first_step_s"])

    consistency = sup.DP45.consistency()
    tableau_ok = consistency["row_sums_equal_c"] and consistency["sum_b"] == 1 and consistency["sum_e"] == 0
    t_cf = info.get("t_cf")
    y_cf = _ref_at(ctx, [t_cf])[0]
    load_W = scen.load(t_cf)

    def f_umbra(t, T):
        return model.rhs(t, T, False, load_W)

    prediction = sup.dp45_attempt(f_umbra, t_cf, y_cf, h_force, rtol=REJ["rtol"], atol=REJ["atol_T_K"])
    loose = sup.dp45_attempt(f_umbra, t_cf, y_cf, h_force, rtol=R_LOOSE, atol=A_LOOSE)
    h2_pred = h_force * max(0.2, 0.9 * prediction["error_norm"] ** -0.2)
    results.append(case_record.check(
        "步骤4 输入 必被拒绝的积分步",
        f"最后一圈进入日食的时刻以首步 {h_force:g} s 起算，{_label(REJ_KEY)}；用文献 Dormand Prince 5(4) 系数与独立参考解"
        "预先算出这一尝试的误差范数大于 1，按 RK45 的误差控制必被拒绝",
        f"系数检查：各行之和等于节点 {consistency['row_sums_equal_c']}，权重和 {consistency['sum_b']}，误差权重和 "
        f"{consistency['sum_e']}；解析进入日食时刻 {t_cf:.6f} s，参考解 T_S {y_cf[I_S]:.4f} K；预计误差范数 "
        f"{prediction['error_norm']:.2f}，太阳能板误差估计 {prediction['error_K'][I_S]:.3e} K；同一步在 1×10⁻⁶ 容限下误差范数 "
        f"{loose['error_norm']:.2f}；按 RK45 步长调整公式下一次尝试约 {h2_pred:.2f} s",
        tableau_ok and prediction["error_norm"] > 1.0))

    t_x = info.get("t_x")
    sid = info.get("solver_id")
    records = run["records"]
    recs = [r for r in records if r.solver_id == sid and r.context == "integration"] if sid is not None else []
    c_nodes = [float(c) for c in sup.DP45.C[1:]] + [1.0]
    if t_x is not None and len(recs) >= 7:
        first = recs[1:7]
        expected_times = [t_x + c * h_force for c in c_nodes]
        dev = max(abs(r.time_s - e) for r, e in zip(first, expected_times))
        trial = first[-1]
        trial_T = np.array(trial.state[:NN])
        accepted_times = np.asarray(archive.accepted["time_s"])
        accepted_states = np.asarray(archive.accepted["state"])
        start_index = np.flatnonzero(accepted_times == t_x)
        y_start = accepted_states[int(start_index[0])] if start_index.size == 1 else None
        h1 = trial.time_s - t_x
        repro = sup.dp45_attempt(f_umbra, t_x, y_start, h1, rtol=REJ["rtol"], atol=REJ["atol_T_K"]) \
            if y_start is not None else None
        repro_dev = float(np.max(np.abs(repro["y_new"] - trial_T))) if repro is not None else math.inf
        h2 = info["t_accept_end"] - t_x
        norm_from_h2 = (0.9 * h1 / h2) ** 5 if h2 > 0.2 * h1 else math.nan
        norm_rel = abs(norm_from_h2 - repro["error_norm"]) / repro["error_norm"] if repro is not None else math.inf
        hook_ok = (dev <= 1e-9 and trial.outcome == "ok" and repro_dev <= 1e-9 and info["attempts"] >= 2
                   and h2 < h1 and norm_rel <= 1e-6)
        hook_text = (f"积分器 {sid} 在 {t_x!r} s 的构造试算后，第一次尝试的六个试算时刻与 t 加 c_i 乘 {h_force:g} s 最大相差 "
                     f"{dev:.1e} s；第六个试算为 {trial.time_s:.6f} s 的试算状态，T_S {trial_T[I_S]:.6f} K，T_R "
                     f"{trial_T[NODE_ORDER.index('R')]:.6f} K；由已接受起点独立重算这一尝试，状态差 {repro_dev:.1e} K，误差"
                     f"范数 {repro['error_norm']:.3f}；模块接受的步自 {t_x:.6f} s 到 {info['t_accept_end']:.6f} s，步长 "
                     f"{h2:.4f} s，尝试 {info['attempts']} 次，按 RK45 步长调整公式对应误差范数 {norm_from_h2:.3f}，"
                     f"相对差 {norm_rel:.1e}")
    else:
        hook_ok, hook_text, trial, trial_T, h1, h2, repro, y_start = False, "未找到被拒绝步的积分器或试算记录", None, None, \
            math.nan, math.nan, None, None
    results.append(case_record.check(
        "步骤4 被拒绝的积分步的试算时刻与试算状态",
        "试算回调显示该积分器先按 60 s 尝试，六个试算时刻为 t 加 c_i 乘 60 s；第六个试算的状态与独立重算的同一尝试相差不超过 "
        "1×10⁻⁹ K；随后以更小步长重试并接受，接受步长对应的误差范数与独立重算值相对差不超过 1×10⁻⁶",
        hook_text, hook_ok))

    accepted_times = np.asarray(archive.accepted["time_s"])
    accepted_states = np.asarray(archive.accepted["state"])
    if trial is not None:
        trial_in_times = bool(np.any(accepted_times == trial.time_s))
        trial_in_states = bool(np.any(np.all(accepted_states[:, :NN] == trial_T, axis=1)))
        solution_at_trial = np.asarray(archive.state_at(trial.time_s))[:NN]
        gap = float(np.max(np.abs(solution_at_trial - trial_T)))
        ref_trial = _ref_at(ctx, [info["t_trial_end"]])[0]
        err_accepted = float(np.max(np.abs(solution_at_trial - ref_trial)))
        err_trial = float(np.max(np.abs(trial_T - ref_trial)))
        same_start = y_start is not None and np.array_equal(np.asarray(archive.state_at(t_x))[:NN], y_start[:NN])
        thermal_state = trial.thermal_state
        final = archive.final_thermal_state
        state_separate = (thermal_state is not None and thermal_state.time_s == trial.time_s
                          and final.time_s == T_END and not np.array_equal(final.temperature_K, thermal_state.temperature_K))
        out_t = np.asarray(archive.time_s)
        window = (out_t >= t_x) & (out_t <= trial.time_s)
        window_ok = np.array_equal(np.asarray(archive.temperature_K)[window],
                                   np.asarray(archive.state_at(out_t[window]))[:, :NN])
        no_write = (not trial_in_times and not trial_in_states and same_start and state_separate and window_ok
                    and gap > 0.0)
        no_write_text = (f"已接受状态 {accepted_times.size} 个中时刻等于 {trial.time_s:.6f} s 的 {int(trial_in_times)} 个，"
                         f"温度等于试算状态的 {int(trial_in_states)} 个；接受步自已接受状态原样起算 {same_start}；该时刻已接受解与"
                         f"试算状态相差 {gap:.2e} K，已接受解与参考解相差 {err_accepted:.2e} K，试算状态与参考解相差 "
                         f"{err_trial:.2e} K；试算 ThermalState 独立于最终状态 {state_separate}；"
                         f"{int(np.count_nonzero(window))} 个输出样点取自已接受解 {window_ok}")
        OUTCOME["rejected"] = {"t_x": t_x, "h1": h1, "h2": h2, "norm_pred": prediction["error_norm"],
                               "norm_repro": repro["error_norm"] if repro else math.nan, "gap_K": gap,
                               "err_accepted_K": err_accepted, "err_trial_K": err_trial,
                               "attempts": info.get("attempts"), "h2_pred": h2_pred}
    else:
        no_write, no_write_text = False, "没有可检查的试算状态"
    results.append(case_record.check(
        "步骤4 被拒绝的积分步没有写入组件温度",
        "被拒绝尝试的末时刻与试算温度都不在已接受状态中；接受步从原已接受状态起算；该时刻的已接受解不等于试算状态；试算 "
        "ThermalState 不进入最终状态；这段时间的输出样点取自已接受解",
        no_write_text, no_write))

    recount = _recount_rk45(records, archive, construction_evaluations=1)
    stats = archive.statistics
    attempts_module = [int(v) for v in np.asarray(archive.steps["attempts"])]
    rejected_states_in = sum(int(np.any(np.all(accepted_states[:, :NN] == np.asarray(item["end_record"].state[:NN]),
                                                axis=1))) for item in recount["rejected"])
    rejected_times_in = sum(int(np.any(accepted_times == item["end_record"].time_s)) for item in recount["rejected"])
    forced = [item for item in recount["rejected"] if item["t_start"] == t_x]
    stats_ok = (not recount["anomalies"] and recount["attempts"] == attempts_module
                and len(recount["rejected"]) == stats["rejected_steps"]
                and sum(attempts_module) - len(attempts_module) == stats["rejected_steps"]
                and rejected_states_in == 0 and rejected_times_in == 0 and len(forced) >= 1
                and int(np.count_nonzero(run["hook_integration"]))
                == stats["function_evaluations_by_context"]["integration"])
    results.append(case_record.check(
        "步骤4 步长统计与试算回调的重新计数一致",
        "由试算回调按每次尝试六个试算重新计数，各已接受步的尝试次数与归档相同，被拒绝尝试数等于统计的拒绝步数；全部被拒绝尝试的"
        "末状态都不在已接受状态中",
        f"统计接受步 {stats['accepted_steps']}，拒绝步 {stats['rejected_steps']}，积分试算 "
        f"{stats['function_evaluations_by_context']['integration']}；回调重新计数被拒绝尝试 {len(recount['rejected'])} 次，"
        f"其中起点在进入日食时刻的 {len(forced)} 次，尝试次数与归档一致 {recount['attempts'] == attempts_module}，计数异常 "
        f"{recount['anomalies'] or '无'}；被拒绝尝试的末时刻出现在已接受状态中 {rejected_times_in} 次，末状态出现 "
        f"{rejected_states_in} 次",
        stats_ok))
    OUTCOME["rejected_count"] = len(recount["rejected"])
    OUTCOME["rejected_stats"] = stats["rejected_steps"]

    bad, rejected_all = [], 0
    for item in _all_runs(ctx):
        a = item["archive"]
        kinds = Counter(a.accepted["kind"])
        times = np.asarray(a.accepted["time_s"])
        integration_times = times[np.array([kind == "integration" for kind in a.accepted["kind"]])]
        segment_times = times[np.array([kind == "segment_start" for kind in a.accepted["kind"]])]
        steps_new = np.asarray(a.steps["t_new_s"])
        attempts = np.asarray(a.steps["attempts"])
        rejected_all += int(a.statistics["rejected_steps"])
        good = (set(kinds) <= {"initial", "segment_start", "integration"} and kinds["initial"] == 1
                and kinds["integration"] == a.statistics["accepted_steps"] == steps_new.size
                and kinds["segment_start"] == len(a.segments) - 1
                and len(times) == a.statistics["accepted_states"]
                and np.array_equal(integration_times, steps_new)
                and np.array_equal(segment_times, np.array([s["start_s"] for s in a.segments][1:]))
                and int(np.sum(attempts - 1)) == a.statistics["rejected_steps"])
        if not good:
            bad.append(item["run_id"])
    results.append(case_record.check(
        "步骤4 全部运行中组件温度只来自已接受步与边界时刻",
        "34 次运行的已接受状态只有初值、各积分段起点与各已接受步终点三类，数目等于 1 加积分段数减 1 加接受步数，时刻与已接受步"
        "终点逐位相同；各步尝试次数减 1 之和等于统计的拒绝步数",
        f"不符合的运行 {bad or '无'}；34 次运行统计的拒绝步合计 {rejected_all} 个", not bad))
    OUTCOME["rejected_all"] = rejected_all

    twin = ctx["runs"].get(REJ_KEY)
    if twin is not None and _completed(twin) and _completed(run):
        d = float(np.max(np.abs(run["last"] - twin["last"])))
    else:
        d = math.inf
    results.append(case_record.check(
        "步骤4 强制拒绝后的结果与对应组合一致",
        f"首步强制为 {h_force:g} s 的运行完成，最后一圈温度与同设置但由求解器自选首步的运行之差不超过 {TIGHTEN_K:g} K",
        f"状态 {archive.status}，{_stats_text(stats)}；最后一圈最大差 {d:.2e} K，与参考解之差 {run['ref_err_last_K']:.2e} K",
        _completed(run) and d <= TIGHTEN_K))
    OUTCOME["rejected_vs_twin_K"] = d
    case_record.metric("rejected_step", {k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                                         for k, v in OUTCOME.get("rejected", {}).items()} | {
        "recount_rejected": len(recount["rejected"]), "statistics_rejected": stats["rejected_steps"],
        "forced_rejections": len(forced), "vs_twin_last_orbit_K": d})
    assert all(results)


# ------------------------------------------------------------------------------------------------ evidence and summary


def _run_record(ctx: dict, run: dict) -> dict:
    archive = run["archive"]
    stats = archive.statistics
    values = run["last"][:, I_S]
    grid = ctx["g_last"]
    return {
        "run_id": run["run_id"], "tag": run["tag"], "earth_flux": run["earth"], "settings": dict(archive.solver_settings),
        "status": archive.status, "error": run["error"], "wall_s": run["wall_s"],
        "statistics": {key: stats[key] for key in ("accepted_steps", "rejected_steps", "function_evaluations",
                                                   "function_evaluations_by_context", "solver_instances",
                                                   "segments", "eclipse_boundaries", "output_samples")},
        "eclipse_boundaries_s": [b.time_s for b in archive.eclipse_boundaries],
        "segments": [{"start_s": s["start_s"], "end_s": s["end_s"], "start_reasons": list(s["start_reasons"])}
                     for s in archive.segments],
        "last_orbit_T_S_K": {"min": float(values.min()), "max": float(values.max()),
                             "mean": float(np.trapezoid(values, grid) / (grid[-1] - grid[0]))},
        "reference_error_last_orbit_K": run.get("ref_err_last_K"),
        "reference_error_outputs_K": run.get("ref_err_output_K"),
    }


def _write_evidence(ctx: dict) -> str:
    RESULTS_DIR.mkdir(exist_ok=True)
    payload = {
        "case_id": "NI-001",
        "description": "Every run of NI-001 on the FE-001 mean environment case: solver settings, step statistics, "
                       "located eclipse boundaries, segments, last-orbit solar array temperature and the error against "
                       "the independent fourth order Runge-Kutta reference.",
        "last_orbit_s": [ctx["t0_last"], T_END],
        "closed_form_eclipse_s": [t for t, _ in ctx["orbit"].boundaries(0.0, T_END)],
        "load": LOAD,
        "reference": {"rk4_step_s": REF["rk4_step_s"], "halving_max_K": OUTCOME.get("ref_halving_K"),
                      "last_orbit_T_S_K": OUTCOME.get("ref_S")},
        "runs": [_run_record(ctx, run) for run in _all_runs(ctx)],
    }
    path = RESULTS_DIR / "NI-001_runs.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return str(path)


NODE_CN = {"S": "太阳能板", "J": "计算节点", "C": "冷板", "B": "电池", "D": "电源设备", "R": "散热板"}
BOUNDARY_CN = {"eclipse:sunlit_to_umbra": "进入日食", "eclipse:umbra_to_sunlit": "离开日食"}


def _where(ctx: dict, worst: dict) -> str:
    """Component and instant of a largest difference, placed relative to the nearest boundary of the run."""

    moment = float(worst["time_s"])
    nearest = min(_expected_boundaries(ctx["orbit"]), key=lambda item: abs(item[0] - moment))
    reason = nearest[2]
    if reason in BOUNDARY_CN:
        event = BOUNDARY_CN[reason]
    elif reason == f"declared:{LOAD['start_label']}":
        event = "负载启动"
    else:
        event = "负载停止"
    offset = moment - nearest[0]
    side = "后" if offset >= 0 else "前"
    return f"{NODE_CN[worst['node']]} {moment:.0f} s，即{event}{side} {abs(offset):.0f} s"


def _summary_text(ctx: dict | None) -> str:
    if ctx is None:
        return "NI-001 的联合运行未能完成，没有得到数值设置对比结果。"
    o = OUTCOME
    num, sci = sup.num, sup.sci
    parts = [
        f"在 FE-001 平均环境工况上，通过 sdtwin_sim.coupled 对积分方法 RK45 与 Radau、相对容限 1×10⁻⁶ 与 1×10⁻⁸、温度绝对"
        f"容限 1×10⁻⁶ K 与 1×10⁻⁸ K、最大步长 60 s 与 10 s、输出间隔 10 s 与 60 s 的 32 种组合各做一次只含热模块的联合运行，"
        f"每次自轨道正午积分 {T_END:.0f} s，取最后一圈 {ctx['t0_last']:.1f} 至 {T_END:.0f} s 每 1 s 比较六个组件温度。计算节点 "
        f"Compute01 的 {LOAD['power_W']:.0f} W 负载在 {LOAD['start_s']} s 启动、{LOAD['stop_s']} s 停止，两个时刻作为输入不连续点"
        f"交给联合运行。反照与地球红外按第 8 章表 8 的同时刻取值与已声明插值，取 sdtwin_sim.earth_flux 每 10 s 一组记录作三次"
        f"样条插值；每次试算直接积分 earth_flux 的 FE-001 运行完成，与插值输入的同设置运行相比最后一圈温度差 "
        f"{sci(o['table_fidelity_K'])} K。",
        f"容限同时收紧 100 倍后最后一圈温度变化最大 {sci(o['tighten']['both'])} K，出现在{_where(ctx, o['tighten_worst'])}；"
        f"单独收紧相对容限或温度绝对容限时最大 {sci(max(o['tighten']['rtol'], o['tighten']['atol']))} K；RK45 与 Radau 之差最大 "
        f"{sci(o['method_K'])} K，出现在{_where(ctx, o['method_worst'])}；均不超过 0.01 K。按 T2 至 T5 手算并用四阶龙格库塔法"
        f"积分的独立参考解，步长减半后变化 {sci(o['ref_halving_K'])} K；32 次运行与参考解的最后一圈温差在收紧前最大 "
        f"{sci(o['ref_loose_K'])} K，收紧后最大 {sci(o['ref_tight_K'])} K，结果随容限收紧而收敛。",
        f"每次运行定位到 {o['n_eclipse']} 个日食进出时刻，与圆柱地影解析值之差最大 {sci(o['eclipse_err_s'])} s，不超过 1 s；"
        f"负载启停处前一段止于指令时刻前一个浮点数，后一段始于后一个浮点数，相差约 {sci(o['load_cut_s'])} s。34 次运行的 "
        f"{o['steps_total']} 个已接受步都没有跨越边界，trial_hook 记录的 {o['solvers']} 个积分器共 {o['evaluations']} 次积分试算"
        f"全部位于边界同一侧，没有跨越边界后平均。",
        f"全部运行的输出时刻为所需的固定间隔时刻；输出间隔 10 s 与 60 s 的运行内部积分步逐位相同；最大步长 60 s 与 10 s 的运行在"
        f"同一输出时刻的温度差最大 {sci(o['output_maxstep_K'])} K，输出样点与参考解之差最大 {sci(o['output_ref_K'])} K，输出采样"
        f"不随内部步长改变。",
    ]
    r = o.get("rejected")
    if r:
        parts.append(
            f"另以 RK45、相对容限与温度绝对容限 1×10⁻⁸、首步 60 s 运行一次。在最后一圈进入日食的时刻，用文献 Dormand Prince "
            f"系数和独立参考解预先算出这一步的误差范数为 {num(r['norm_pred'], 1)}，该步必被拒绝。trial_hook 记录显示模块先按 "
            f"60 s 在六个试算时刻求值，随后以 {num(r['h2'], 2)} s 重试并接受，与按 RK45 步长调整公式预计的 "
            f"{num(r['h2_pred'], 2)} s 一致。被拒绝的试算状态与参考解相差 {sci(r['err_trial_K'])} K，同一时刻的已接受解与参考解"
            f"只差 {sci(r['err_accepted_K'])} K，该试算状态不在已接受状态中，也没有进入输出。按 trial_hook 重新计数的被拒绝尝试 "
            f"{o['rejected_count']} 次等于步长统计的拒绝步 {o['rejected_stats']} 个，34 次运行的组件温度只来自已接受步与边界时刻。")
    return "".join(parts)


_DROP = str.maketrans("", "", "()[]{}<>（）【】《》「」『』'\"")
_SUPERSCRIPT = str.maketrans("0123456789-+", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺")


def _clean_cn(text: str) -> str:
    """Raw check text in the form of the report rules: no brackets or quotes, U+2212 for negative numbers, powers of
    ten instead of e notation, no dash punctuation."""

    text = str(text).translate(_DROP)
    text = re.sub(r"(\d(?:\.\d+)?)e([+-]?)0*(\d+)",
                  lambda m: f"{m.group(1)}×10{(('-' if m.group(2) == '-' else '') + m.group(3)).translate(_SUPERSCRIPT)}",
                  text)
    text = re.sub(r"(?<![\w.])-(?=\d)", "−", text)
    text = text.replace("—", "，").replace("–", "至").replace("|", " ")
    return text


def test_zz_evidence_and_summary(request, case_record):
    """Run records for the report, Chinese summary and anomalies."""

    try:
        ctx = request.getfixturevalue("ni001")
    except Exception as exc:  # noqa: BLE001  (the setup failure is recorded, the summary still states it)
        ctx = None
        case_record.check("计算准备", "场景装配、输入表、34 次联合运行与参考解全部完成", f"{type(exc).__name__}: {exc}", False)
    path = _write_evidence(ctx) if ctx is not None else None
    case_record.metric("evidence_file", path)
    if ctx is not None:
        case_record.metric("build_wall_s", ctx["build_wall_s"])
    try:
        summary = _summary_text(ctx)
    except Exception as exc:  # noqa: BLE001  (a summary built from missing numbers is itself an unexecuted item)
        summary = "NI-001 的部分检查没有给出结果，摘要无法按全部数值写出。"
        case_record.check("摘要数据", "各步骤的检查都给出数值", f"{type(exc).__name__}: {exc}", False)
    case_record.summary(summary)
    failed = [check for check in case_record.checks if not check["passed"]]
    if failed:
        items = [f"{_clean_cn(check['name'])}未通过，实际结果为 {_clean_cn(check['actual'][:300])}" for check in failed]
        case_record.anomalies("；".join(items) + "。")
    else:
        case_record.anomalies("无")
    assert ctx is not None
