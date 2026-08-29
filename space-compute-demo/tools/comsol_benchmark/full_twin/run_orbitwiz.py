# -*- coding: utf-8 -*-
"""Phase 2 — OrbitWiz open-loop traces for the COMSOL comparison.

Runs the engine's OWN tick (compare_sim._OfflineTwin -> StateEngine.
_update_placeholder_physics, zero physics duplication) on the on-disk
scenario (usd/twin_params.json: truss, radiator 1.1/2.5, 7 clusters, 12
slots) with the user-chosen WhitePaint radiator, and logs everything COMSOL
needs at 1 PHYSICAL second: the tick normally advances 60 physical s
(PHYS_TIME_SCALE / timebase.TIME_SCALE = 60), so we call it with dt = 1/60
tick-seconds. The workload schedule runs in tick-seconds, so the 360-tick
"inference" cycle is 21 600 physical s either way.

Body frame (decision D): +X = orbit normal unit(r x v)  (solar-cell normal),
+Y = Z x X = velocity (ram) direction, +Z = -r_hat (nadir; spine / radiator
long axis). Radiator faces are +-Y (ram / wake).

Usage (backend venv):
    python run_orbitwiz.py sweep              # GPU sweep -> pick case A / B
    python run_orbitwiz.py export V100 caseA  # 1-s traces for one GPU type
    python run_orbitwiz.py equiv V100         # dt=1 vs dt=1/60 equivalence
"""
import csv, json, math, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

from services import timebase as _tb, geodyn as _geo, constellations as _consts
_tb.reset_mission()
from models import SatelliteConfig, TwinGeometry, SatelliteState
import compare_sim as _cs
import state_engine as _se
import llm_perf as _perf

OUT = os.path.join(HERE, "out", "orbitwiz")
os.makedirs(OUT, exist_ok=True)

TWIN_PARAMS = json.load(open(os.path.join(ROOT, "usd", "twin_params.json"), encoding="utf-8"))
RADIATOR_MATERIAL = "WhitePaint"          # user decision A (2026-08-29)
WORKLOAD = _se._DEFAULT_WORKLOAD_PROFILE  # "inference" (state_engine.py:655)
PLATFORM_W = 600.0                        # state_engine.py:731
TIME_SCALE = _tb.TIME_SCALE               # 60 physical s per tick-second
PRESET = _consts.get_preset("single_iss")
PERIOD_S = PRESET.period_s                # 5574.19 s (from the TLE)
SIGMA = 5.67e-8


def make_twin(gpu: str, radiator_material: str = RADIATOR_MATERIAL, t0_c: float = 20.0):
    slots = [gpu] * len(TWIN_PARAMS["gpu_slots"])
    cfg = SatelliteConfig(gpu=gpu, radiator_material=radiator_material, gpu_slots=slots)
    geom = TwinGeometry(architecture=TWIN_PARAMS["architecture"],
                        solar_clusters_per_side=TWIN_PARAMS["solar_clusters_per_side"],
                        radiator_long=TWIN_PARAMS["radiator_long"],
                        radiator_ratio=TWIN_PARAMS["radiator_ratio"])
    snap = _cs.LiveSnapshot(
        constellation_id="single_iss", config=cfg, geometry=geom,
        workload_profile=WORKLOAD, platform_power_w=PLATFORM_W,
        gpu_count=len(slots), sim_time_s=0.0,
        orbit_type=SatelliteState().orbit_type,
        battery_capacity_wh=_se._batt_capacity_wh(cfg), battery_soc=0.9,
        temperature_c=t0_c)
    tw = _cs._OfflineTwin(snap)
    tw.settle_deployables()
    # Re-apply through the public setters so slot bookkeeping (gpu_count,
    # groups) is exactly what the live engine would hold.
    tw.set_config({"gpu_slots": slots, "radiator_material": radiator_material}, mark_custom=False)
    tw.set_workload_profile(WORKLOAD, mark_custom=False)
    return tw


def step(tw, dt_tick: float):
    tw._sim_time_s += dt_tick
    tw._update_placeholder_physics(dt_tick)


def _unit(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sample(tw) -> dict:
    """One row: everything COMSOL needs + the OrbitWiz reference outputs."""
    sat = tw._sat
    r = sat.sat_xyz_km
    v = tw._tracked_vel_km_s
    s = tw._sun_unit_eci
    xb = _unit(_cross(r, v))            # orbit normal
    zb = tuple(-c for c in _unit(r))    # nadir
    yb = _cross(zb, xb)                 # ram
    r_km = math.sqrt(_dot(r, r))
    geom = tw._twin_geometry
    a_rad = _se._radiator_area_m2(geom)
    rm = _se._RAD_MAT_TABLE[tw._config.radiator_material]
    alpha, eps = rm["absorptivity"], rm["emissivity"]
    S = tw._solar_s_w_m2
    illum = tw._solar_illum
    f = _geo.earth_view_factor(max(r_km, _geo.R_EARTH_THERMAL_KM))
    q_sun = alpha * S * illum * a_rad / 4.0
    q_alb = alpha * _geo.EARTH_ALBEDO * S * a_rad * f * max(0.0, sat.sun_cos)
    q_ir = eps * _geo.EARTH_IR_W_M2 * a_rad * f
    det = sat.workload_detail
    g = lambda k, d=float("nan"): getattr(det, k, d) if det is not None else d
    payload = sat.payload_power_w
    plat = sat.platform_power_w
    tick_t = tw._sim_time_s
    row = dict(
        t_phys_s=tick_t * TIME_SCALE, t_tick_s=tick_t,
        jd_utc=_tb.jd_utc_at(tick_t),
        payload_w=payload, platform_w=plat,
        heat_total_w=(payload + plat) * 0.95,
        heat_payload_w=payload * 0.95, heat_platform_w=plat * 0.95,
        heat_per_gpu_w=payload * 0.95 / max(1, sat.gpu_count),
        gpu_count=sat.gpu_count,
        gpu_power_w_per_gpu=g("power_w_per_gpu"), gpu_power_cap_w=g("power_cap_w"),
        gpu_freq_frac=g("freq_frac"), gpu_die_temp_c=g("gpu_die_temp_c"),
        gpu_throttled=int(bool(g("thermal_throttled", False))),
        gpu_runaway=int(bool(g("thermal_runaway", False))),
        gpu_util=sat.gpu_utilization, job=g("job_key", ""),
        T_struct_c=sat.temperature_c,
        q_out_w=sat.radiator_power_w, q_env_sun_w=q_sun, q_env_albedo_w=q_alb, q_env_ir_w=q_ir,
        illum=illum, sunlit=int(bool(sat.sunlit)), sun_cos=sat.sun_cos,
        solar_flux_w_m2=S, view_factor_orbitwiz=f,
        r_eci_x_km=r[0], r_eci_y_km=r[1], r_eci_z_km=r[2],
        v_eci_x=v[0], v_eci_y=v[1], v_eci_z=v[2],
        sun_eci_x=s[0], sun_eci_y=s[1], sun_eci_z=s[2],
        sun_body_x=_dot(s, xb), sun_body_y=_dot(s, yb), sun_body_z=_dot(s, zb),
        altitude_km=sat.altitude_km, lat_deg=sat.lat, lon_deg=sat.lon,
        solar_input_w=sat.solar_input_w, battery_soc=sat.battery_soc,
        solar_incidence=sat.solar_incidence,
        radiator_area_m2=a_rad, alpha=alpha, eps=eps,
    )
    return row


def spin_up(tw, orbits: float):
    n = int(round(orbits * PERIOD_S / TIME_SCALE))
    for _ in range(n):
        step(tw, 1.0)


def run_export(gpu: str, label: str, orbits_out: float = 7.0, spin_orbits: float = 8.0):
    tw = make_twin(gpu)
    t0 = time.time()
    spin_up(tw, spin_orbits)
    n = int(round(orbits_out * PERIOD_S))
    rows = []
    for _ in range(n + 1):
        rows.append(sample(tw))
        step(tw, 1.0 / TIME_SCALE)
    rows[-1] = sample(tw)
    # re-base time to the export window
    t_base = rows[0]["t_phys_s"]
    for r in rows:
        r["t_s"] = r["t_phys_s"] - t_base
    keys = ["t_s"] + [k for k in rows[0] if k != "t_s"]
    path = os.path.join(OUT, f"{label}_{gpu}_1s.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    summ = summarize(rows)
    summ.update(gpu=gpu, label=label, rows=len(rows), spin_orbits=spin_orbits,
                period_s=PERIOD_S, t_phys_start_s=t_base, wall_s=round(time.time() - t0, 1))
    json.dump(summ, open(os.path.join(OUT, f"{label}_{gpu}_summary.json"), "w"), indent=2)
    print(json.dumps(summ, indent=2))
    return path


def summarize(rows):
    T = [r["T_struct_c"] for r in rows]
    die = [r["gpu_die_temp_c"] for r in rows]
    thr = [r["gpu_throttled"] for r in rows]
    P = [r["payload_w"] for r in rows]
    return dict(T_struct_min_c=min(T), T_struct_max_c=max(T), T_struct_mean_c=sum(T) / len(T),
                die_min_c=min(die), die_max_c=max(die),
                throttled_frac=sum(thr) / len(thr),
                payload_min_w=min(P), payload_max_w=max(P), payload_mean_w=sum(P) / len(P),
                heat_total_mean_w=sum(r["heat_total_w"] for r in rows) / len(rows),
                sunlit_frac=sum(r["sunlit"] for r in rows) / len(rows))


def run_sweep():
    res = {}
    for gpu in _se._GPU_TABLE:
        tw = make_twin(gpu)
        spin_up(tw, 8.0)
        rows = []
        n = int(round(4.0 * PERIOD_S / TIME_SCALE))
        for _ in range(n):
            rows.append(sample(tw))
            step(tw, 1.0)
        s = summarize(rows)
        g = _perf.GPU_PERF[gpu]
        s["t_throttle_c"] = g.t_throttle_c
        s["r_th_k_per_w"] = g.r_th_k_per_w
        s["onset_struct_c_at_tdp"] = g.t_throttle_c - g.tdp_w * g.r_th_k_per_w
        res[gpu] = s
        print(gpu, json.dumps(s))
    json.dump(res, open(os.path.join(OUT, "gpu_sweep.json"), "w"), indent=2)


def run_equiv(gpu: str):
    """dt = 1 tick vs dt = 1/60 tick from the same spun-up state, 2 orbits."""
    # Satrec is not picklable -> build two twins and spin both up identically
    # (the tick is deterministic), then let them diverge only in dt.
    twA = make_twin(gpu); spin_up(twA, 8.0)
    twB = make_twin(gpu); spin_up(twB, 8.0)
    assert twA._sat.temperature_c == twB._sat.temperature_c
    n = int(round(2.0 * PERIOD_S / TIME_SCALE))
    maxdT = 0.0; maxdP = 0.0
    for i in range(n):
        step(twA, 1.0)
        for _ in range(int(TIME_SCALE)):
            step(twB, 1.0 / TIME_SCALE)
        maxdT = max(maxdT, abs(twA._sat.temperature_c - twB._sat.temperature_c))
        maxdP = max(maxdP, abs(twA._sat.payload_power_w - twB._sat.payload_power_w))
    print(json.dumps(dict(gpu=gpu, ticks=n, max_abs_dT_struct_c=maxdT, max_abs_dPayload_w=maxdP,
                          T_end_dt1=twA._sat.temperature_c, T_end_dt60=twB._sat.temperature_c)))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sweep"
    if mode == "sweep":
        run_sweep()
    elif mode == "export":
        run_export(sys.argv[2], sys.argv[3])
    elif mode == "equiv":
        run_equiv(sys.argv[2])
