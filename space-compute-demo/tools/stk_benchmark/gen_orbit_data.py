# -*- coding: utf-8 -*-
"""Orbit-only chart data (ours vs STK) for the orbit benchmark web report."""
import csv, json, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cases

def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    hdr = rows[0]; out = {h: [] for h in hdr}
    for r in rows[1:]:
        for h, v in zip(hdr, r):
            try: out[h].append(float(v))
            except ValueError: out[h].append(v)
    return out
stk = lambda n: load(os.path.join(cases.STK_OUT, n))
ours = lambda n: load(os.path.join(cases.OURS_OUT, n))
def wrap(d):
    while d > 180: d -= 360
    while d < -180: d += 360
    return d
def gaps(ivs, t0, t1):
    out, cur = [], t0
    for s, e in sorted(ivs):
        if s > cur: out.append((cur, s))
        cur = max(cur, e)
    if cur < t1: out.append((cur, t1))
    return out
def pair(truth, mine):
    rows, used = [], set()
    for a in truth:
        best, bo = None, 0
        for k, b in enumerate(mine):
            ov = min(a[1], b[1]) - max(a[0], b[0])
            if ov > bo: best, bo = k, ov
        if best is None: rows.append([a[0], a[1], None, None]); continue
        used.add(best); b = mine[best]
        rows.append([a[0], a[1], b[0], b[1]])
    extra = [b for k, b in enumerate(mine) if k not in used]
    return rows, extra
r = lambda v, n=3: round(v, n)

out = {"cases": {}, "meta": {"epoch": cases.EPOCH_UTCG, "gs": [cases.GS_LAT_DEG, cases.GS_LON_DEG]}}
for cname, cfg in cases.TLE_CASES.items():
    se, oe = stk("ephem_%s.csv" % cname), ours("ephem_%s.csv" % cname)
    ss, os_ = stk("sun_%s.csv" % cname), ours("sun_%s.csv" % cname)
    io_ = {round(t): i for i, t in enumerate(oe["t"])}
    is_ = {round(t): i for i, t in enumerate(os_["t"])}
    pos, lat, lon, alt, sun, beta = [], [], [], [], [], []
    for i, t in enumerate(se["t"]):
        j = io_.get(round(t)); k = is_.get(round(t))
        if j is None or k is None: continue
        d = math.dist((se["x_km"][i], se["y_km"][i], se["z_km"][i]), (oe["x_km"][j], oe["y_km"][j], oe["z_km"][j]))
        if round(t) % 300 == 0:
            pos.append([t, r(d * 1e6, 4)])
            lat.append([t, r((oe["lat_deg"][j] - se["lat_deg"][i]) * 1e6, 3)])
            lon.append([t, r(wrap(oe["lon_deg"][j] - se["lon_deg"][i]) * 1e6, 3)])
            alt.append([t, r((oe["alt_km"][j] - se["alt_km"][i]) * 1e6, 3)])
            m = math.sqrt(ss["sun_x_km"][i]**2 + ss["sun_y_km"][i]**2 + ss["sun_z_km"][i]**2)
            dot = (ss["sun_x_km"][i]*os_["sun_ux"][k] + ss["sun_y_km"][i]*os_["sun_uy"][k] + ss["sun_z_km"][i]*os_["sun_uz"][k]) / m
            sun.append([t, r(math.degrees(math.acos(max(-1, min(1, dot)))), 4)])
            beta.append([t, r(ss["beta_deg"][i], 3), r(os_["beta_deg"][k], 3)])
    sl = stk("lighting_%s.csv" % cname)
    sunl = [(a, b) for kd, a, b in zip(sl["kind"], sl["start"], sl["stop"]) if kd == "Sunlight"]
    pen = [(a, b) for kd, a, b in zip(sl["kind"], sl["start"], sl["stop"]) if kd == "Penumbra"]
    dark_stk = gaps(sunl, 0.0, cases.DURATION_S)
    ol = ours("lighting_%s.csv" % cname)
    dark_ours = [(a, b) for kd, a, b in zip(ol["kind"], ol["start"], ol["stop"]) if kd == "dark"]
    ecl_rows, ecl_extra = pair(dark_stk, dark_ours)
    ecl = [[r(a,1), r(b,1), None if c is None else r(c,1), None if d is None else r(d,1)] for a,b,c,d in ecl_rows]
    acc = {}
    if cfg["access"]:
        for m in cases.ELEVATION_MASKS_DEG:
            s = stk("access_%s_m%02d.csv" % (cname, int(m))); o = ours("access_%s_m%02d.csv" % (cname, int(m)))
            rows, extra = pair(list(zip(s["start"], s["stop"])), list(zip(o["start"], o["stop"])))
            acc["m%d" % int(m)] = {"rows": [[r(a,1), r(b,1), None if c is None else r(c,1), None if d is None else r(d,1)] for a,b,c,d in rows], "extra": len(extra)}
    out["cases"][cname] = {
        "pos_err_mm": pos, "lat_err_udeg": lat, "lon_err_udeg": lon, "alt_err_mm": alt,
        "sun_err_deg": sun, "beta": beta,
        "eclipse": ecl, "eclipse_extra": len(ecl_extra), "penumbra_mean_s": r(sum(b-a for a,b in pen)/len(pen),1) if pen else 0,
        "sunlit_frac_stk": r(sum(b-a for a,b in sunl)/cases.DURATION_S*100, 2),
        "sunlit_frac_ours": r(100 - sum(b-a for a,b in dark_ours)/cases.DURATION_S*100, 2),
        "access": acc,
    }
# checks B1..B5, final and baseline
def checks(path):
    with open(path, encoding="utf-8") as f: return json.load(f)
fin = [c for c in checks(os.path.join(cases.OUT_DIR, "summary.json")) if c["id"] in ("B1","B2","B3","B4","B5")]
base = [c for c in checks(os.path.join(cases.OUT_DIR, "summary_baseline.json")) if c["id"] in ("B1","B2","B3","B4","B5")]
out["checks_final"] = fin; out["checks_baseline"] = base
# reuse track + elev from plot_data.json
with open(os.path.join(cases.OUT_DIR, "plot_data.json"), encoding="utf-8") as f:
    pd = json.load(f)
out["track"] = pd["track"]; out["elev"] = pd["elev"]
p = os.path.join(cases.OUT_DIR, "orbit_plot_data.json")
with open(p, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False)
print("wrote", p, os.path.getsize(p)//1024, "KB")
