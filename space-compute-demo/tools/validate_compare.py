"""validate_compare.py — audit the live what-if comparison physics.

Two independent lines of evidence against a RUNNING backend (port 8001):

A. LOCKSTEP EQUALITY — start a comparison whose first variant equals the
   live loadout (baseline design, WhitePaint radiators). That variant must
   reproduce the live satellite's tick-owned integration states
   (temperature, SOC) tick for tick: same snapshot seed + same physics +
   same step cadence leaves nothing to diverge. Any drift would expose a
   difference between the compare path and the live engine.

B. FIRST-PRINCIPLES RE-DERIVATION — treating the broadcast variant samples
   as data, re-derive each next sample from the documented laws using ONLY
   table constants (no engine code):
     env:      F = (1-sqrt(1-(R/r)^2))/2;  S_eff = 1361/d_au^2 (analytic sun)
               Q_env = a*S_eff*illum*A/4 + a*0.3*S_eff*A*F*max(0,cosz)
                       + eps*237*A*F
     thermal:  T' = T + ((P_load+P_plat)*0.95 + Q_env
                         - eps*sigma*A_rad*T_K^4)*60/160000
     battery:  SOC' = SOC + eff_chg(P_solar - P_load - P_plat)*60/(E_batt*3600)
     solar:    P_solar = eta*A_solar*S_eff*0.95*(1+k*(T-25)) while sunlit
               (free/SADA mode; k = cell temperature coefficient, Si -0.45%/K)
     EPS cap:  P_load <= N*TDP*(0.15+0.85*util)  (equality on the MFU path)
   A mismatch would mean the live modules do not implement the documented
   physics. Run: backend/.venv/Scripts/python tools/validate_compare.py
"""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.request

BASE = f"http://127.0.0.1:{sys.argv[1]}" if len(sys.argv) > 1 else "http://127.0.0.1:8001"

SIGMA = 5.67e-8
PHYS_SCALE = 60.0
THERMAL_MASS = 160_000.0
SOLAR_CONST = 1361.0
EARTH_IR = 237.0
ALBEDO = 0.30
R_EARTH_TH = 6371.0
EMISSIVITY = {"Aluminum": 0.10, "WhitePaint": 0.85, "OSR": 0.92, "Graphite": 0.96}
ALPHA = {"Aluminum": 0.25, "WhitePaint": 0.25, "OSR": 0.08, "Graphite": 0.90}
EFF_SI = 0.22
SOLAR_TEMP_COEFF_SI = -0.0045   # fraction/K around the 25 C reference
BATT_EFF_LIION = 0.95
H100_TDP = 700.0
DEMO_JD = 2460545.0  # 2024-08-22 12:00:00 UTC — engine demo epoch


def s_eff_w_m2(sim_t_s: float) -> float:
    """Solar irradiance at the true Earth-Sun distance (documented two-term
    analytic sun, same law as services/geodyn.py)."""
    jd = DEMO_JD + sim_t_s * PHYS_SCALE / 86400.0
    t = (jd - 2451545.0) / 36525.0
    m = math.radians((357.5291092 + 35999.05034 * t) % 360.0)
    r_au = 1.000140612 - 0.016708617 * math.cos(m) - 0.000139589 * math.cos(2 * m)
    return SOLAR_CONST / (r_au * r_au)


def env_heat_w(alpha: float, eps: float, area: float, alt_km: float,
               s_eff: float, illum: float, cos_zen: float) -> float:
    r = R_EARTH_TH + max(0.0, alt_km)
    rho = R_EARTH_TH / r
    f = 0.5 * (1.0 - math.sqrt(max(0.0, 1.0 - rho * rho)))
    return (alpha * s_eff * illum * area / 4.0
            + alpha * ALBEDO * s_eff * area * f * max(0.0, cos_zen)
            + eps * EARTH_IR * area * f)

_results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    _results.append((ok, msg))
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")


def req(path: str, payload: dict | None = None) -> dict:
    r = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(r, timeout=10) as f:
        return json.loads(f.read())


def main() -> int:
    print("== validate_compare: lockstep equality + first-principles re-derivation ==")
    req("/designs/baseline/apply", {})
    req("/compare/stop", {})
    time.sleep(2.0)

    started = req("/compare/start", {
        "dimension": "radiator_material",
        "values": ["WhitePaint", "OSR", "Aluminum"],  # variant 0 == live loadout
    })
    check(started.get("ok") is True, "compare/start accepted (WhitePaint=live, OSR, Aluminum)")

    # Sample fast enough to catch every tick; keep the latest state per
    # elapsed value so law checks can use strictly consecutive tick pairs.
    by_elapsed: dict[int, dict] = {}
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        s = req("/state")
        cl = s.get("compare_live")
        if cl and cl.get("active"):
            by_elapsed[int(cl["elapsed_s"])] = s
        time.sleep(0.35)

    req("/compare/stop", {})

    ticks = sorted(by_elapsed)
    usable = [t for t in ticks if t >= 1]
    check(len(usable) >= 30, f"collected {len(usable)} stepped ticks (want >=30)")

    # ---- A. lockstep equality --------------------------------------------
    max_dT = max_dSOC = max_skew = 0.0
    for t in usable:
        s = by_elapsed[t]
        live = s["satellite"]
        v0 = s["compare_live"]["variants"][0]
        max_dT = max(max_dT, abs(v0["temperature_c"] - live["temperature_c"]))
        max_dSOC = max(max_dSOC, abs(v0["battery_soc"] - live["battery_soc"]))
        skew = abs((s["sim_time_s"] - s["compare_live"]["start_sim_time_s"])
                   - s["compare_live"]["elapsed_s"])
        max_skew = max(max_skew, skew)
    check(max_dT <= 0.02,
          f"lockstep: same-config variant tracks live temperature (max |dT| {max_dT:.4f} C <= 0.02)")
    check(max_dSOC <= 0.002,
          f"lockstep: same-config variant tracks live SOC (max |dSOC| {max_dSOC:.5f} <= 0.002)")
    check(max_skew <= 1.5,
          f"lockstep: elapsed_s == live ticks since start (max skew {max_skew:.2f} s <= 1.5)")

    # ---- B. first-principles re-derivation -------------------------------
    any_state = by_elapsed[usable[0]]
    a_rad = any_state["satellite"]["radiator_area_m2"]
    a_solar = any_state["satellite"]["solar_area_m2"]
    cap_wh = any_state["satellite"]["battery_capacity_wh"]
    plat_w = any_state["satellite"]["platform_power_w"]
    n_gpu = any_state["satellite"]["gpu_count"]
    values = [v["value"] for v in any_state["compare_live"]["variants"]]

    pairs = [(t, t + 1) for t in usable if t + 1 in by_elapsed]
    check(len(pairs) >= 25, f"{len(pairs)} consecutive tick pairs for law checks (want >=25)")

    for vi, vname in enumerate(values):
        eps = EMISSIVITY[str(vname)]
        alpha = ALPHA[str(vname)]
        worst_th = worst_soc = 0.0
        n_th = 0
        for t0, t1 in pairs:
            a = by_elapsed[t0]["compare_live"]["variants"][vi]
            b = by_elapsed[t1]["compare_live"]["variants"][vi]
            live_a = by_elapsed[t0]["satellite"]
            live_b = by_elapsed[t1]["satellite"]  # lockstep: same orbit state
            illum_a = live_a.get("solar_illum", 1.0 if live_a["sunlit"] else 0.0)
            illum = live_b.get("solar_illum", 1.0 if live_b["sunlit"] else 0.0)
            # Skip eclipse-transition pairs: broadcast kinematics are refreshed
            # at READ time (up to 1 s after the tick that integrated T), so a
            # tick straddling the penumbra pairs the new illum with the old
            # integration — a sampling-skew artifact, not a physics error. The
            # law is still exercised on every steady sunlit/eclipse tick.
            in_transition = (abs(illum - illum_a) > 0.005
                             or 0.005 < illum < 0.995)
            # thermal law (skip samples pinned at the ±clamp)
            if (not in_transition
                    and -79.5 < a["temperature_c"] < 94.5
                    and -79.5 < b["temperature_c"] < 94.5):
                t_k = a["temperature_c"] + 273.15
                s_eff = s_eff_w_m2(by_elapsed[t1]["sim_time_s"])
                q_env = env_heat_w(alpha, eps, a_rad, live_b["altitude_km"],
                                   s_eff, illum, live_b.get("sun_cos", 0.0))
                q_in = (b["payload_power_w"] + plat_w) * 0.95 + q_env
                q_out = eps * SIGMA * a_rad * t_k ** 4
                pred = a["temperature_c"] + (q_in - q_out) / THERMAL_MASS * PHYS_SCALE
                worst_th = max(worst_th, abs(pred - b["temperature_c"]))
                n_th += 1
            # battery law (skip clamp saturation)
            if 0.002 < a["battery_soc"] < 0.998 and 0.002 < b["battery_soc"] < 0.998:
                net = b["solar_input_w"] - b["payload_power_w"] - plat_w
                eff_net = net * BATT_EFF_LIION if net >= 0.0 else net
                pred = a["battery_soc"] + eff_net * PHYS_SCALE / (cap_wh * 3600.0)
                worst_soc = max(worst_soc, abs(pred - b["battery_soc"]))
        check(n_th >= 10 and worst_th <= 0.08,
              f"thermal law re-derivation [{vname}]: worst |dT_pred| {worst_th:.4f} C <= 0.08 over {n_th} ticks")
        check(worst_soc <= 0.0015,
              f"battery law re-derivation [{vname}]: worst |dSOC_pred| {worst_soc:.6f} <= 0.0015")

    # solar + EPS laws (variant 0; radiator dimension leaves solar identical)
    worst_sun = 0.0
    n_sun = 0
    worst_eps = 0.0
    for t in usable:
        v = by_elapsed[t]["compare_live"]["variants"][0]
        if v["solar_input_w"] > 1.0:
            temp_factor = max(0.0, min(1.25, 1.0 + SOLAR_TEMP_COEFF_SI
                                       * (v["temperature_c"] - 25.0)))
            peak_expected = (EFF_SI * a_solar
                             * s_eff_w_m2(by_elapsed[t]["sim_time_s"])
                             * 0.95 * temp_factor)
            worst_sun = max(worst_sun, abs(v["solar_input_w"] - peak_expected) / peak_expected)
            n_sun += 1
        cap = n_gpu * H100_TDP * (0.15 + 0.85 * v["gpu_utilization"])
        worst_eps = max(worst_eps, v["payload_power_w"] - cap)
    if n_sun:
        check(worst_sun <= 0.005,
              f"solar law: sunlit samples equal eta*A*S*0.95 within {worst_sun * 100:.2f}% (n={n_sun})")
    else:
        print("  SKIP  solar law: window fell entirely in eclipse")
    check(worst_eps <= 1.0,
          f"EPS law: payload never exceeds N*TDP*(0.15+0.85*util) (worst excess {worst_eps:.2f} W)")

    req("/designs/baseline/apply", {})

    fails = [m for ok, m in _results if not ok]
    print()
    if fails:
        print(f"{len(fails)} CHECK(S) FAILED")
        return 1
    print(f"ALL {len(_results)} COMPARE-PHYSICS CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
