# -*- coding: utf-8 -*-
"""Extract chart-ready JSON from the benchmark CSVs for the visual report.

Also re-derives the PRE-FIX ("before") series from the legacy formulas the
engine used before geodyn (fixed scene-light sun, hemisphere eclipse test,
spherical Earth + GMST(0)=0), so the report can overlay before/after/truth.

Run:  ..\\..\\backend\\.venv\\Scripts\\python.exe gen_plot_data.py
"""

import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cases  # noqa: E402

SUN_RAW = (0.648, -0.648, 0.398)          # legacy fixed sun (state_engine v1)
OMEGA_E = 2.0 * math.pi / 86164.0905      # legacy GMST rate, GMST(0)=0
LEGACY_BASE = (cases.SOLAR_EFFICIENCY * cases.SOLAR_AREA_M2 * 1361.0)
LEGACY_T_EQ_K = (cases.THERM_DISSIPATION_W
                 / (cases.THERM_EMISSIVITY * 5.67e-8
                    * cases.THERM_RADIATING_AREA_M2)
                 + 250.0 ** 4) ** 0.25    # legacy: Q_out vs T_bg=250 K


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    hdr = rows[0]
    out = {h: [] for h in hdr}
    for r in rows[1:]:
        for h, v in zip(hdr, r):
            try:
                out[h].append(float(v))
            except ValueError:
                out[h].append(v)
    return out


def stk(n):
    return load(os.path.join(cases.STK_OUT, n))


def ours(n):
    return load(os.path.join(cases.OURS_OUT, n))


def legacy_latlon(x, y, z, t):
    g = (OMEGA_E * t) % (2.0 * math.pi)
    cg, sg = math.cos(g), math.sin(g)
    xe, ye, ze = cg * x + sg * y, -sg * x + cg * y, z
    lon = math.degrees(math.atan2(ye, xe))
    lat = math.degrees(math.atan2(ze, math.hypot(xe, ye)))
    return lat, lon


def legacy_sunlit(x, y, z):
    r = max(1e-6, math.sqrt(x * x + y * y + z * z))
    return ((x * SUN_RAW[0] + y * SUN_RAW[1] + z * SUN_RAW[2]) / r) > -0.05


def rnd(v, nd=3):
    return round(v, nd)


def main():
    se = stk("ephem_leo_iss.csv")
    oe = ours("ephem_leo_iss.csv")
    si = stk("intensity_leo_iss.csv")
    oi = ours("intensity_leo_iss.csv")
    ss = stk("sun_leo_iss.csv")
    op = ours("power_leo_iss.csv")
    st = stk("seet_leo_iss.csv")
    ot = ours("thermal_leo_iss.csv")
    el = ours("elev_leo_iss.csv")
    aer = stk("aer_leo_iss.csv")

    idx_o = {round(t): i for i, t in enumerate(oe["t"])}
    idx_si = {round(t): i for i, t in enumerate(si["t"])}
    idx_ss = {round(t): i for i, t in enumerate(ss["t"])}

    # --- ground track (first ~1.4 orbits) -------------------------------
    track = {"t": [], "stk": [], "after": [], "before": []}
    for i, t in enumerate(se["t"]):
        if t > 8100:
            break
        j = idx_o.get(round(t))
        if j is None:
            continue
        x, y, z = oe["x_km"][j], oe["y_km"][j], oe["z_km"][j]
        blat, blon = legacy_latlon(x, y, z, t)
        track["t"].append(t)
        track["stk"].append([rnd(se["lon_deg"][i]), rnd(se["lat_deg"][i])])
        track["after"].append([rnd(oe["lon_deg"][j]), rnd(oe["lat_deg"][j])])
        track["before"].append([rnd(blon), rnd(blat)])

    # --- solar power, sun-pointing (2 orbits) ----------------------------
    power = {"t": [], "stk": [], "after": [], "before": []}
    for j, t in enumerate(op["t"]):
        if t > 12000:
            break
        i, k = idx_si.get(round(t)), idx_ss.get(round(t))
        if i is None or k is None:
            continue
        d = math.sqrt(ss["sun_x_km"][k] ** 2 + ss["sun_y_km"][k] ** 2
                      + ss["sun_z_km"][k] ** 2)
        truth = (LEGACY_BASE / 1361.0 * (1361.0 / (d / 149597870.7) ** 2)
                 * si["intensity_pct"][i] / 100.0)
        jo = idx_o.get(round(t))
        x, y, z = oe["x_km"][jo], oe["y_km"][jo], oe["z_km"][jo]
        power["t"].append(t)
        power["stk"].append(rnd(truth, 1))
        power["after"].append(rnd(op["p_sun_w"][j], 1))
        power["before"].append(rnd(LEGACY_BASE if legacy_sunlit(x, y, z) else 0.0, 1))

    # --- thermal 24h (5-min decimation) ----------------------------------
    thermal = {"t": [], "stk": [], "after": []}
    idx_ot = {round(t): i for i, t in enumerate(ot["t"])}
    for i, t in enumerate(st["t"]):
        if round(t) % 300 != 0:
            continue
        j = idx_ot.get(round(t))
        if j is None:
            continue
        thermal["t"].append(t)
        thermal["stk"].append(rnd(st["temp_k"][i] - 273.15, 2))
        thermal["after"].append(rnd(ot["temp_k"][j] - 273.15, 2))
    thermal["before_const"] = rnd(LEGACY_T_EQ_K - 273.15, 2)

    # --- elevation + access windows --------------------------------------
    elev = {"t": [], "after": []}
    for i, t in enumerate(el["t"]):
        if t > 10800:
            break
        elev["t"].append(t)
        elev["after"].append(rnd(el["el_deg"][i], 3))
    elev["stk_pts"] = [[rnd(t, 1), rnd(e, 3)] for t, e in
                       zip(aer["t"], aer["el_deg"]) if t <= 10800]
    acc = {}
    for mask in (0, 5, 10, 20):
        s = stk("access_leo_iss_m%02d.csv" % mask)
        o = ours("access_leo_iss_m%02d.csv" % mask)
        acc["m%d" % mask] = {
            "stk": [[rnd(a, 1), rnd(b, 1)] for a, b in zip(s["start"], s["stop"])],
            "after": [[rnd(a, 1), rnd(b, 1)] for a, b in zip(o["start"], o["stop"])],
        }

    # --- per-case summary numbers (before values from REPORT_baseline) ---
    sunlit_frac = {}
    for cname in cases.TLE_CASES:
        sl = stk("lighting_%s.csv" % cname)
        sun_s = sum(b - a for k, a, b in
                    zip(sl["kind"], sl["start"], sl["stop"]) if k == "Sunlight")
        oin = ours("intensity_%s.csv" % cname)
        after = sum(oin["illum"]) / len(oin["illum"])
        # legacy hemisphere fraction
        oeph = ours("ephem_%s.csv" % cname)
        before = (sum(1 for x, y, z in
                      zip(oeph["x_km"], oeph["y_km"], oeph["z_km"])
                      if legacy_sunlit(x, y, z)) / len(oeph["x_km"]))
        sunlit_frac[cname] = {"stk": rnd(sun_s / 86400.0 * 100, 1),
                              "after": rnd(after * 100, 1),
                              "before": rnd(before * 100, 1)}

    data = {
        "track": track,
        "power": power,
        "thermal": thermal,
        "elev": elev,
        "access": acc,
        "sunlit_frac": sunlit_frac,
        "energy_wh": {   # from REPORT / REPORT_baseline B7 (sun-pointing, 24h)
            "leo_iss": {"stk": 196871, "after": 196392, "before": 163976},
            "sso_landsat": {"stk": 218471, "after": 217621, "before": 170526},
            "geo_goes": {"stk": 307687, "after": 307674, "before": 162229},
        },
    }
    out = os.path.join(cases.OUT_DIR, "plot_data.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    n = os.path.getsize(out)
    print("wrote %s (%.1f KB)" % (out, n / 1024.0))


if __name__ == "__main__":
    main()
