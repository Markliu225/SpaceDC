# -*- coding: utf-8 -*-
"""Our-side reference series for the COMSOL thermal comparison.

Case T1: isothermal aluminium shell sphere, identical parameters to the STK
SEET benchmark (cross-section 10 m2, alpha 0.25, eps 0.85, 2850 W).
Case T2: nadir-pointing flat aluminium radiator plate 2 m x 1 m x 3 mm, OSR
coating both faces, 1000 W injected in a central 0.2 m x 0.2 m patch.

Outputs out/ref/*.csv on the benchmark timeline (2024-08-22 12:00 UTC + 24 h,
60 s) plus orbit_elements.json for COMSOL's Orbital Thermal Loads input.
Run with the backend venv interpreter.
"""
import csv, json, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.abspath(os.path.join(HERE, "..", "stk_benchmark"))
BACKEND = os.path.abspath(os.path.join(HERE, "..", "..", "backend"))
sys.path.insert(0, BENCH); sys.path.insert(0, BACKEND)
import cases
from sgp4.api import Satrec
from services import geodyn, elements, timebase
timebase.reset_mission()

SIGMA = 5.67e-8
REF = os.path.join(HERE, "out", "ref"); os.makedirs(REF, exist_ok=True)

# ---- case parameters (mirrored in SPEC.md) -----------------------------
T1 = dict(r_m=math.sqrt(10.0 / math.pi), shell_m=0.002, rho=2700.0, cp=900.0,
          alpha=0.25, eps=0.85, P_W=2850.0)
T1["A_surf"] = 4.0 * math.pi * T1["r_m"] ** 2
T1["C_J_K"] = T1["A_surf"] * T1["shell_m"] * T1["rho"] * T1["cp"]
T2 = dict(Lx=2.0, Ly=1.0, t_m=0.003, rho=2700.0, cp=900.0, k=237.0,
          alpha=0.08, eps=0.92, P_W=1000.0, patch_m=0.2)
T2["A_face"] = T2["Lx"] * T2["Ly"]
T2["C_J_K"] = T2["A_face"] * T2["t_m"] * T2["rho"] * T2["cp"]
ALBEDO, Q_IR, S0 = geodyn.EARTH_ALBEDO, geodyn.EARTH_IR_W_M2, geodyn.SOLAR_CONSTANT_W_M2

cfg = cases.TLE_CASES["leo_iss"]
sat = Satrec.twoline2rv(cfg["line1"], cfg["line2"])
n = int(cases.DURATION_S / cases.STEP_S) + 1
ts = [i * cases.STEP_S for i in range(n)]

# ---- orbit elements at epoch for COMSOL --------------------------------
jd, fr = timebase.jd_after(0.0)
e, r0, v0 = sat.sgp4(jd, fr)
oe = elements.rv_to_oe(r0, v0)
orbit = {
    "epoch_utc": cases.EPOCH_ISO,
    "frame": "TEME (treat as ECI/J2000 for COMSOL; difference < 0.02 deg)",
    "semi_major_axis_km": oe["a_km"], "eccentricity": oe["e"],
    "inclination_deg": math.degrees(oe["inc_rad"]),
    "raan_deg": math.degrees(oe["raan_rad"]),
    "arg_periapsis_deg": math.degrees(oe["argp_rad"]),
    "true_anomaly_deg": math.degrees(oe["nu_rad"]),
    "altitude_km_mean": oe["a_km"] - 6378.137,
    "period_s": elements.period_s(oe["a_km"]),
    "position_teme_km_at_epoch": list(r0), "velocity_teme_km_s_at_epoch": list(v0),
    "note": "osculating elements from SGP4 at epoch; a two-body/J2 propagator drifts "
            "from SGP4 by tens of seconds in eclipse timing over 24 h, compare by "
            "sunlit/eclipse segment means",
}
with open(os.path.join(REF, "orbit_elements.json"), "w", encoding="utf-8") as f:
    json.dump(orbit, f, indent=2)

def geometry(t):
    jd, fr = timebase.jd_after(t)
    e, r, v = sat.sgp4(jd, fr)
    sun_km, r_au = geodyn.sun_teme(timebase.jd_utc_after(t))
    sn = math.sqrt(sum(c * c for c in sun_km)); su = tuple(c / sn for c in sun_km)
    rn = math.sqrt(sum(c * c for c in r)); rh = tuple(c / rn for c in r)
    illum = geodyn.sun_visible_fraction(r, sun_km)
    cosz = sum(a * b for a, b in zip(rh, su))          # zenith . sun
    S = S0 / (r_au * r_au)
    F_sph = geodyn.earth_view_factor(rn)               # sphere-to-Earth
    F_nadir = (geodyn.R_EARTH_THERMAL_KM / rn) ** 2    # flat plate facing nadir
    return illum, cosz, S, F_sph, F_nadir

# ---- T1 sphere ---------------------------------------------------------
rows = []; T = None
for t in ts:
    illum, cosz, S, F, _ = geometry(t)
    A = T1["A_surf"]
    q_sun = T1["alpha"] * S * illum * A / 4.0
    q_alb = T1["alpha"] * ALBEDO * S * A * F * max(0.0, cosz)
    q_ir = T1["eps"] * Q_IR * A * F
    q_in = T1["P_W"] + q_sun + q_alb + q_ir
    T_eq = (q_in / (T1["eps"] * SIGMA * A)) ** 0.25
    if T is None: T = T_eq
    else: T += (q_in - T1["eps"] * SIGMA * A * T ** 4) / T1["C_J_K"] * cases.STEP_S
    rows.append([t, round(illum, 4), round(cosz, 4), round(S, 2), round(F, 5),
                 round(q_sun, 2), round(q_alb, 2), round(q_ir, 2), round(T_eq, 3), round(T, 3)])
with open(os.path.join(REF, "t1_sphere_ref.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["t_s", "illum", "cos_zenith_sun", "S_W_m2", "F_view",
        "Q_sun_W", "Q_albedo_W", "Q_ir_W", "T_eq_K", "T_lumped_K"]); w.writerows(rows)

# ---- T2 nadir-pointing plate -------------------------------------------
rows = []; T = None
for t in ts:
    illum, cosz, S, _, Fn = geometry(t)
    Af = T2["A_face"]
    # zenith face: normal = +r_hat; nadir face: normal = -r_hat
    q_sun_z = T2["alpha"] * S * illum * max(0.0, cosz) * Af
    q_sun_n = T2["alpha"] * S * illum * max(0.0, -cosz) * Af
    q_alb_n = T2["alpha"] * ALBEDO * S * Fn * max(0.0, cosz) * Af
    q_ir_n = T2["eps"] * Q_IR * Fn * Af
    q_in = T2["P_W"] + q_sun_z + q_sun_n + q_alb_n + q_ir_n
    A_rad = 2.0 * Af
    T_eq = (q_in / (T2["eps"] * SIGMA * A_rad)) ** 0.25
    if T is None: T = T_eq
    else: T += (q_in - T2["eps"] * SIGMA * A_rad * T ** 4) / T2["C_J_K"] * cases.STEP_S
    rows.append([t, round(illum, 4), round(cosz, 4), round(S, 2), round(Fn, 5),
                 round(q_sun_z / Af, 2), round(q_sun_n / Af, 2), round(q_alb_n / Af, 2),
                 round(q_ir_n / Af, 2), round(T_eq, 3), round(T, 3)])
with open(os.path.join(REF, "t2_plate_ref.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["t_s", "illum", "cos_zenith_sun", "S_W_m2", "F_nadir",
        "q_sun_zenith_W_m2", "q_sun_nadir_W_m2", "q_albedo_nadir_W_m2", "q_ir_nadir_W_m2",
        "T_eq_K", "T_lumped_K"]); w.writerows(rows)

# ---- STK umbra/penumbra intervals for eclipse cross-check ---------------
import shutil
shutil.copy(os.path.join(cases.STK_OUT, "lighting_leo_iss.csv"), os.path.join(REF, "stk_lighting_leo.csv"))
shutil.copy(os.path.join(cases.STK_OUT, "seet_leo_iss.csv"), os.path.join(REF, "stk_seet_t1.csv"))

with open(os.path.join(REF, "case_params.json"), "w", encoding="utf-8") as f:
    json.dump({"T1": T1, "T2": T2, "albedo": ALBEDO, "earth_ir_W_m2": Q_IR,
               "solar_constant_1AU_W_m2": S0, "earth_radius_thermal_km": geodyn.R_EARTH_THERMAL_KM,
               "step_s": cases.STEP_S, "duration_s": cases.DURATION_S}, f, indent=2)
print("T1 A_surf %.2f m2  C %.0f J/K  T_eq(0) %.1f K" % (T1["A_surf"], T1["C_J_K"], float(open(os.path.join(REF,'t1_sphere_ref.csv')).read().splitlines()[1].split(',')[8])))
print("T2 C %.0f J/K" % T2["C_J_K"])
print("orbit a=%.1f km e=%.5f i=%.3f RAAN=%.3f argp=%.3f nu=%.3f" % (oe["a_km"], oe["e"], math.degrees(oe["inc_rad"]), math.degrees(oe["raan_rad"]), math.degrees(oe["argp_rad"]), math.degrees(oe["nu_rad"])))
