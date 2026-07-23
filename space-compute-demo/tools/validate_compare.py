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
     thermal:  T' = T + (0.95*(P_load+P_plat) - eps*sigma*A_rad*(T_K^4-250^4))*60/160000
     battery:  SOC' = SOC + (P_solar - P_load - P_plat)*60/(E_batt*3600)
     solar:    P_solar = eta*A_solar*1361*0.95 while sunlit (baseline LEO)
     EPS cap:  P_load <= N*TDP*(0.15+0.85*util)  (equality on the MFU path)
   A mismatch would mean the live modules do not implement the documented
   physics. Run: backend/.venv/Scripts/python tools/validate_compare.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8001"

SIGMA = 5.67e-8
T_BG4 = 250.0 ** 4
PHYS_SCALE = 60.0
THERMAL_MASS = 160_000.0
SOLAR_CONST = 1361.0
EMISSIVITY = {"Aluminum": 0.10, "WhitePaint": 0.85, "OSR": 0.92, "Graphite": 0.96}
EFF_SI = 0.22
H100_TDP = 700.0

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
        worst_th = worst_soc = 0.0
        n_th = 0
        for t0, t1 in pairs:
            a = by_elapsed[t0]["compare_live"]["variants"][vi]
            b = by_elapsed[t1]["compare_live"]["variants"][vi]
            # thermal law (skip samples pinned at the ±clamp)
            if -79.5 < a["temperature_c"] < 94.5 and -79.5 < b["temperature_c"] < 94.5:
                t_k = a["temperature_c"] + 273.15
                q_in = (b["payload_power_w"] + plat_w) * 0.95
                q_out = eps * SIGMA * a_rad * (t_k ** 4 - T_BG4)
                pred = a["temperature_c"] + (q_in - q_out) / THERMAL_MASS * PHYS_SCALE
                worst_th = max(worst_th, abs(pred - b["temperature_c"]))
                n_th += 1
            # battery law (skip clamp saturation)
            if 0.002 < a["battery_soc"] < 0.998 and 0.002 < b["battery_soc"] < 0.998:
                net = b["solar_input_w"] - b["payload_power_w"] - plat_w
                pred = a["battery_soc"] + net * PHYS_SCALE / (cap_wh * 3600.0)
                worst_soc = max(worst_soc, abs(pred - b["battery_soc"]))
        check(n_th >= 10 and worst_th <= 0.08,
              f"thermal law re-derivation [{vname}]: worst |dT_pred| {worst_th:.4f} C <= 0.08 over {n_th} ticks")
        check(worst_soc <= 0.0015,
              f"battery law re-derivation [{vname}]: worst |dSOC_pred| {worst_soc:.6f} <= 0.0015")

    # solar + EPS laws (variant 0; radiator dimension leaves solar identical)
    peak_expected = EFF_SI * a_solar * SOLAR_CONST * 0.95
    worst_sun = 0.0
    n_sun = 0
    worst_eps = 0.0
    for t in usable:
        v = by_elapsed[t]["compare_live"]["variants"][0]
        if v["solar_input_w"] > 1.0:
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
