"""Per-preset orbit-cycle physics validation against the live backend.

For each design preset: apply it, let one full orbit (~93 wall-s at 60x)
play out, sample /state at 2 Hz, then check:
  - battery SOC never pins at 0 and stays above 0.20 (no low_battery)
  - SOC actually CHARGES in sunlight and DISCHARGES in eclipse (physics visible)
  - temperature stays inside [-40, 70] (no overtemp/undertemp)
  - no standing design alarms (solar_undersized / radiator_undersized)
  - solar input follows sunlit (tracking model: >0 in sun, 0 in eclipse)
"""
import json
import time
import urllib.request

BASE = "http://localhost:8001"
PRESETS = ["baseline", "redwire", "compute_max", "eco_light", "thermal_guard",
           "wide_wing"]
ORBIT_WALL_S = 100
SAMPLE_DT = 2.0


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return json.load(r)


def post(path):
    req = urllib.request.Request(BASE + path, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def validate(preset_id):
    r = post(f"/designs/{preset_id}/apply")
    assert r["ok"] and r["regenerated"], f"apply failed: {r}"
    time.sleep(4)  # let the switch settle a couple of ticks

    rows = []
    n = int(ORBIT_WALL_S / SAMPLE_DT)
    for _ in range(n):
        s = get("/state")
        sat = s["satellite"]
        rows.append({
            "sunlit": sat["sunlit"],
            "solar": sat["solar_input_w"],
            "net": sat["battery_charge_w"],
            "soc": sat["battery_soc"],
            "temp": sat["temperature_c"],
            "wl": sat["workload"],
            "alarms": set(sat.get("alarms", [])),
            "supply": sat["solar_supply_avg_w"],
            "demand": sat["solar_demand_avg_w"],
            "emit": sat["thermal_max_emit_w"],
            "tdem": sat["thermal_peak_demand_w"],
        })
        time.sleep(SAMPLE_DT)

    socs   = [r["soc"] for r in rows]
    temps  = [r["temp"] for r in rows]
    alarms = set().union(*(r["alarms"] for r in rows))
    sun_rows = [r for r in rows if r["sunlit"]]
    ecl_rows = [r for r in rows if not r["sunlit"]]
    sun_net = [r["net"] for r in sun_rows]
    charging_in_sun = sum(1 for v in sun_net if v > 0)
    solar_off_in_eclipse = all(r["solar"] < 1 for r in ecl_rows)
    solar_on_in_sun = all(r["solar"] > 100 for r in sun_rows)

    checks = {
        "soc_min>0.20":        min(socs) > 0.20,
        "soc_swings":          (max(socs) - min(socs)) > 0.03,
        "charges_in_sun":      len(sun_rows) == 0 or charging_in_sun / max(1, len(sun_rows)) > 0.7,
        "drains_in_eclipse":   len(ecl_rows) == 0 or all(r["net"] < 0 for r in ecl_rows),
        "solar_tracks_sunlit": solar_off_in_eclipse and solar_on_in_sun,
        "temp_in_envelope":    -40 < min(temps) and max(temps) < 70,
        "no_design_alarms":    not ({"solar_undersized", "radiator_undersized"} & alarms),
        "no_battery_alarms":   not ({"low_battery", "eclipse_deficit"} & alarms),
        "saw_both_phases":     len(sun_rows) > 3 and len(ecl_rows) > 3,
    }
    last = rows[-1]
    print(f"\n=== {preset_id} ===")
    print(f"  supply/demand: {last['supply']:.0f}/{last['demand']:.0f} W "
          f"({(last['supply']/max(1,last['demand'])-1)*100:+.0f}%) | "
          f"emit/peak-demand: {last['emit']:.0f}/{last['tdem']:.0f} W "
          f"({(last['emit']/max(1,last['tdem'])-1)*100:+.0f}%)")
    print(f"  SOC [{min(socs):.2f} .. {max(socs):.2f}]  temp [{min(temps):.1f} .. {max(temps):.1f}] C  "
          f"sun/ecl samples {len(sun_rows)}/{len(ecl_rows)}  alarms={sorted(alarms) or 'none'}")
    ok = True
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
        ok = ok and v
    return ok


def main():
    all_ok = True
    for p in PRESETS:
        all_ok = validate(p) and all_ok
    post("/designs/baseline/apply")
    print("\n" + ("ALL PRESETS PASS" if all_ok else "SOME PRESETS FAIL"))


if __name__ == "__main__":
    main()
