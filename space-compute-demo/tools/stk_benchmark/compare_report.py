# -*- coding: utf-8 -*-
"""Align STK truth vs our-engine exports, score against gates, emit REPORT.md.

Pure stdlib — runnable with either interpreter:
    python compare_report.py
"""

import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cases  # noqa: E402

AU_KM = 149597870.7
SIGMA = 5.67e-8


# --- IO ----------------------------------------------------------------------

def load_csv(path):
    """CSV -> {col: [floats or strings]}; missing file -> None."""
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return {h: [] for h in rows[0]} if rows else None
    header, out = rows[0], {}
    for j, h in enumerate(header):
        col = []
        for r in rows[1:]:
            v = r[j] if j < len(r) else ""
            try:
                col.append(float(v))
            except ValueError:
                col.append(v)
        out[h] = col
    return out


def stk(name):
    return load_csv(os.path.join(cases.STK_OUT, name))


def ours(name):
    return load_csv(os.path.join(cases.OURS_OUT, name))


# --- math helpers ------------------------------------------------------------

def stats(diffs):
    if not diffs:
        return {"n": 0, "rms": 0.0, "max": 0.0, "mean": 0.0}
    n = len(diffs)
    return {
        "n": n,
        "rms": math.sqrt(sum(d * d for d in diffs) / n),
        "max": max(abs(d) for d in diffs),
        "mean": sum(diffs) / n,
    }


def wrap180(d):
    while d > 180.0:
        d -= 360.0
    while d < -180.0:
        d += 360.0
    return d


def join_on_t(a, b, cols_a, cols_b):
    """Inner-join two tables on integer-rounded t; returns list of tuples."""
    ib = {round(t): i for i, t in enumerate(b["t"])}
    out = []
    for i, t in enumerate(a["t"]):
        j = ib.get(round(t))
        if j is None:
            continue
        out.append(tuple(a[c][i] for c in cols_a) + tuple(b[c][j] for c in cols_b))
    return out


def load_intervals(table, kind=None):
    if table is None:
        return []
    if kind is not None and "kind" in table:
        return [(s, e) for k, s, e in
                zip(table["kind"], table["start"], table["stop"]) if k == kind]
    return list(zip(table["start"], table["stop"]))


def gaps_of(intervals, t0, t1):
    """Complement of sorted intervals within [t0, t1]."""
    ivs = sorted(intervals)
    out, cur = [], t0
    for s, e in ivs:
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < t1:
        out.append((cur, t1))
    return out


def match_intervals(truth, mine, edge_slop=1e9):
    """Pair truth intervals with max-overlap mine intervals.

    Returns (pairs, missed, spurious): pairs are (truth_iv, mine_iv, dstart,
    dstop). Boundary-clipped truth intervals (touching 0 / DURATION) keep
    only their interior edge comparison."""
    used = set()
    pairs, missed = [], []
    for tiv in truth:
        best, best_ov = None, 0.0
        for k, miv in enumerate(mine):
            ov = min(tiv[1], miv[1]) - max(tiv[0], miv[0])
            if ov > best_ov:
                best, best_ov = k, ov
        if best is None:
            missed.append(tiv)
            continue
        used.add(best)
        miv = mine[best]
        pairs.append((tiv, miv, miv[0] - tiv[0], miv[1] - tiv[1]))
    spurious = [miv for k, miv in enumerate(mine) if k not in used]
    return pairs, missed, spurious


def fmt(x, nd=3):
    if isinstance(x, float):
        if x != 0 and (abs(x) >= 1e5 or abs(x) < 10 ** (-nd)):
            return "%.3e" % x
        return ("%%.%df" % nd) % x
    return str(x)


# --- battery integrator (engine rule) ---------------------------------------

def integrate_soc(ts, p_solar, load_w, cap_wh, eff, soc0=0.85):
    soc, out = soc0, []
    cap_j = cap_wh * 3600.0
    for i, t in enumerate(ts):
        dt = ts[i] - ts[i - 1] if i else 0.0
        net = p_solar[i] - load_w
        eff_net = net * eff if net >= 0 else net
        soc = min(1.0, max(0.0, soc + eff_net * dt / cap_j))
        out.append(soc)
    return out


# --- report ------------------------------------------------------------------

CHECKS = []          # (id, case, metric, value, gate, passed, note)


def check(bid, case, metric, value, gate_desc, passed, note=""):
    CHECKS.append({"id": bid, "case": case, "metric": metric,
                   "value": value, "gate": gate_desc,
                   "pass": bool(passed), "note": note})


def run_case(cname, cfg, lines):
    se, oe = stk("ephem_%s.csv" % cname), ours("ephem_%s.csv" % cname)
    lines.append("\n## 用例 `%s`\n" % cname)

    # ---- B1 TEME position/velocity (NTU OD-003) ----
    j = join_on_t(se, oe,
                  ["x_km", "y_km", "z_km", "vx_kms", "vy_kms", "vz_kms"],
                  ["x_km", "y_km", "z_km", "vx_kms", "vy_kms", "vz_kms"])
    dp = [math.dist(r[0:3], r[6:9]) for r in j]
    dv = [math.dist(r[3:6], r[9:12]) for r in j]
    sp, sv = stats(dp), stats(dv)
    check("B1", cname, "TEME |Δr| max (km)", sp["max"], "≤0.001", sp["max"] <= 0.001)
    check("B1", cname, "TEME |Δv| max (km/s)", sv["max"], "≤1e-6", sv["max"] <= 1e-6)
    lines.append("- **B1 SGP4/TEME**：|Δr| max %s km (rms %s)，|Δv| max %s km/s"
                 % (fmt(sp["max"], 6), fmt(sp["rms"], 6), fmt(sv["max"], 9)))

    # ---- B2 LLA subpoint ----
    j = join_on_t(se, oe, ["lat_deg", "lon_deg", "alt_km", "lat_centric_deg"],
                  ["lat_deg", "lon_deg", "alt_km"])
    dlat = [r[4] - r[0] for r in j]
    dlon = [wrap180(r[5] - r[1]) for r in j]
    dalt = [r[6] - r[2] for r in j]
    dlatc = [r[4] - r[3] for r in j]     # vs geocentric lat: isolates GMST error
    slat, slon, salt = stats(dlat), stats(dlon), stats(dalt)
    slatc = stats(dlatc)
    check("B2", cname, "lat max Δ (deg)", slat["max"], "≤0.02", slat["max"] <= 0.02)
    check("B2", cname, "lon max Δ (deg)", slon["max"], "≤0.02", slon["max"] <= 0.02)
    check("B2", cname, "alt max Δ (km)", salt["max"], "≤1.0", salt["max"] <= 1.0)
    lines.append("- **B2 星下点**：Δlat max %s°，Δlon max %s°，Δalt max %s km"
                 "（vs 地心纬度 Δ max %s°——大地/地心之差与 GMST 误差分离）"
                 % (fmt(slat["max"]), fmt(slon["max"]), fmt(salt["max"]),
                    fmt(slatc["max"])))

    # ---- B3 sun direction + beta ----
    ss, os_ = stk("sun_%s.csv" % cname), ours("sun_%s.csv" % cname)
    j = join_on_t(ss, os_, ["sun_x_km", "sun_y_km", "sun_z_km", "beta_deg"],
                  ["sun_ux", "sun_uy", "sun_uz", "beta_deg"])
    ang, dbeta = [], []
    for r in j:
        m = math.sqrt(r[0] ** 2 + r[1] ** 2 + r[2] ** 2) or 1.0
        dotp = (r[0] * r[4] + r[1] * r[5] + r[2] * r[6]) / m
        ang.append(math.degrees(math.acos(max(-1.0, min(1.0, dotp)))))
        dbeta.append(r[7] - r[3])
    sa, sb = stats(ang), stats(dbeta)
    check("B3", cname, "太阳方向角差 max (deg)", sa["max"], "≤0.5", sa["max"] <= 0.5)
    check("B3", cname, "β 角差 max (deg)", sb["max"], "≤0.5", sb["max"] <= 0.5)
    lines.append("- **B3 太阳几何**：方向角差 max %s°（mean %s°），Δβ max %s°"
                 % (fmt(sa["max"]), fmt(sa["mean"]), fmt(sb["max"])))

    # ---- B4 lighting ----
    sl = stk("lighting_%s.csv" % cname)
    sun_ivs = load_intervals(sl, "Sunlight")
    stk_dark = gaps_of(sun_ivs, 0.0, cases.DURATION_S)
    our_dark = load_intervals(ours("lighting_%s.csv" % cname), "dark")
    stk_sun_frac = sum(e - s for s, e in sun_ivs) / cases.DURATION_S
    our_dark_s = sum(e - s for s, e in our_dark)
    our_sun_frac = 1.0 - our_dark_s / cases.DURATION_S
    dfrac = abs(our_sun_frac - stk_sun_frac)
    check("B4", cname, "日照占比差 (pp)", dfrac * 100.0, "≤1", dfrac <= 0.01)
    pairs, missed, spurious = match_intervals(stk_dark, our_dark)
    edge = [abs(d) for _t, _m, ds, de in pairs for d in (ds, de)]
    sedge = stats(edge)
    if stk_dark:
        check("B4", cname, "地影事件时刻差 max (s)", sedge["max"], "≤15",
              sedge["max"] <= 15.0 and not missed and not spurious,
              "漏 %d / 多 %d" % (len(missed), len(spurious)))
    lines.append("- **B4 地影**：日照占比 STK %.1f%% vs 我方 %.1f%%；"
                 "事件时刻差 max %s s，漏报 %d、误报 %d（STK 地影段 %d 个）"
                 % (stk_sun_frac * 100, our_sun_frac * 100,
                    fmt(sedge["max"], 1), len(missed), len(spurious),
                    len(stk_dark)))

    # ---- B6 illumination factor (NTU SE-004 semantics: LEVEL accuracy on
    # full-sun / full-umbra samples; the few-second transition TIMING is
    # gated by B4, and penumbra boundedness by the [0,1] check) ----
    si, oi = stk("intensity_%s.csv" % cname), ours("intensity_%s.csv" % cname)
    illum_col = "illum" if "illum" in oi else "sunlit"
    j = join_on_t(si, oi, ["intensity_pct"], [illum_col])
    level, transition = [], 0
    bounded = True
    for r in j:
        if r[0] >= 99.9 or r[0] <= 0.1:
            level.append(r[1] - r[0] / 100.0)
        else:
            transition += 1
        if not (-1e-9 <= r[1] <= 1.0 + 1e-9):
            bounded = False
    sil = stats(level)
    check("B6", cname, "光照因子电平 RMS", sil["rms"], "≤0.02",
          sil["rms"] <= 0.02 and bounded,
          "过渡样本 %d 个由 B4 定时门限管辖" % transition)
    lines.append("- **B6 光照因子**：电平 RMS %s（max %s，样本 %d），"
                 "过渡样本 %d 个（定时见 B4），越界 %s"
                 % (fmt(sil["rms"]), fmt(sil["max"]), sil["n"], transition,
                    "无" if bounded else "有"))

    # ---- B7 solar power (truth from STK geometry) ----
    op = ours("power_%s.csv" % cname)
    jt = join_on_t(si, ss, ["intensity_pct"],
                   ["sun_x_km", "sun_y_km", "sun_z_km"])
    jr = join_on_t(si, se, ["t"], ["x_km", "y_km", "z_km"])
    base = (cases.SOLAR_EFFICIENCY * cases.SOLAR_AREA_M2
            * cases.SOLAR_CONSTANT_W_M2)
    truth_sun, truth_nadir, tts = [], [], []
    for (illum, sx, sy, sz), (t, x, y, z) in zip(jt, jr):
        d = math.sqrt(sx * sx + sy * sy + sz * sz)
        scale = (AU_KM / d) ** 2 * illum / 100.0
        truth_sun.append(base * scale)
        rn = math.sqrt(x * x + y * y + z * z) or 1.0
        cosn = max(0.0, (x * sx + y * sy + z * sz) / (rn * d))
        truth_nadir.append(base * scale * cosn)
        tts.append(t)
    jo = {round(t): i for i, t in enumerate(op["t"])}
    ours_sun = [op["p_sun_w"][jo[round(t)]] for t in tts if round(t) in jo]
    ours_nadir = [op["p_nadir_w"][jo[round(t)]] for t in tts if round(t) in jo]
    def wh(ts_, ps):
        return sum(p * cases.STEP_S for p in ps) / 3600.0
    e_ts, e_os = wh(tts, truth_sun), wh(tts, ours_sun)
    e_tn, e_on = wh(tts, truth_nadir), wh(tts, ours_nadir)
    rel_sun = abs(e_os - e_ts) / max(1.0, e_ts)
    rel_nad = abs(e_on - e_tn) / max(1.0, e_tn)
    check("B7", cname, "对日姿态 24h 能量差", rel_sun * 100.0, "≤2%", rel_sun <= 0.02,
          "STK %.1f Wh vs 我方 %.1f Wh" % (e_ts, e_os))
    check("B7", cname, "对地姿态 24h 能量差", rel_nad * 100.0, "≤2%", rel_nad <= 0.02,
          "STK %.1f Wh vs 我方 %.1f Wh" % (e_tn, e_on))
    lines.append("- **B7 太阳能**：24h 能量（对日）STK %.0f Wh vs 我方 %.0f Wh（差 %.1f%%）；"
                 "（对地）STK %.0f Wh vs 我方 %.0f Wh（差 %.1f%%）"
                 % (e_ts, e_os, rel_sun * 100, e_tn, e_on, rel_nad * 100))

    # ---- B8 SOC using engine battery rule on both power series ----
    soc_t = integrate_soc(tts, truth_sun, cases.LOAD_W,
                          cases.BATTERY_CAPACITY_WH, cases.BATTERY_CHARGE_EFF)
    soc_o = integrate_soc(tts, ours_sun, cases.LOAD_W,
                          cases.BATTERY_CAPACITY_WH, cases.BATTERY_CHARGE_EFF)
    dmin = abs(min(soc_o) - min(soc_t)) * 100.0
    dend = abs(soc_o[-1] - soc_t[-1]) * 100.0
    check("B8", cname, "SOC 最低点差 (pp)", dmin, "≤5", dmin <= 5.0)
    lines.append("- **B8 电池**：min SOC STK 驱动 %.1f%% vs 我方驱动 %.1f%%；"
                 "期末 SOC 差 %.1f pp" % (min(soc_t) * 100, min(soc_o) * 100, dend))

    # ---- B9 thermal vs SEET ----
    st = stk("seet_%s.csv" % cname)
    ot = ours("thermal_%s.csv" % cname)
    if st and ot:
        j = join_on_t(st, ot, ["temp_k"], ["temp_k"])
        ji = {round(t): i for i, t in enumerate(si["t"])}
        sun_d, ecl_d = [], []
        for (tk, ok), t in zip(j, st["t"]):
            i = ji.get(round(t))
            lit = (si["intensity_pct"][i] > 50.0) if i is not None else True
            (sun_d if lit else ecl_d).append(ok - tk)
        ssn, sec = stats(sun_d), stats(ecl_d)
        check("B9", cname, "光照段温差 mean (K)", abs(ssn["mean"]), "≤10",
              abs(ssn["mean"]) <= 10.0)
        if ecl_d:
            check("B9", cname, "地影段温差 mean (K)", abs(sec["mean"]), "≤10",
                  abs(sec["mean"]) <= 10.0)
        lines.append("- **B9 热**：SEET 光照段均温 %.1f K / 地影段 %.1f K，"
                     "我方恒定 %.1f K → 光照段偏差 mean %s K、地影段 mean %s K"
                     % ((sum(x - d for x, d in zip([r[0] for r in j], [0]*len(j)))
                         and 0) or 0.0, 0.0, ot["temp_k"][0],
                        fmt(ssn["mean"], 1), fmt(sec["mean"], 1)))
        # cleaner narrative numbers
        stk_sun_t = [r[0] for r, t in zip(j, st["t"])
                     if (ji.get(round(t)) is not None
                         and si["intensity_pct"][ji[round(t)]] > 50.0)]
        stk_ecl_t = [r[0] for r, t in zip(j, st["t"])
                     if (ji.get(round(t)) is not None
                         and si["intensity_pct"][ji[round(t)]] <= 50.0)]
        if stk_sun_t:
            lines[-1] = ("- **B9 热**：SEET 光照段均温 %.1f K、地影段均温 %.1f K；"
                         "我方恒定 %.1f K（无轨道相位依赖）→ 光照段偏差 mean %s K、"
                         "地影段 mean %s K"
                         % (sum(stk_sun_t) / len(stk_sun_t),
                            (sum(stk_ecl_t) / len(stk_ecl_t)) if stk_ecl_t else float("nan"),
                            ot["temp_k"][0], fmt(ssn["mean"], 1),
                            fmt(sec["mean"], 1) if ecl_d else "n/a"))

    # ---- B5 access ----
    if cfg["access"]:
        for mask in cases.ELEVATION_MASKS_DEG:
            suffix = "access_%s_m%02d.csv" % (cname, int(mask))
            tiv = load_intervals(stk(suffix))
            miv = load_intervals(ours(suffix))
            pairs, missed, spurious = match_intervals(tiv, miv)
            edges = [abs(d) for _t, _m, ds, de in pairs for d in (ds, de)]
            sed = stats(edges)
            ok = (not missed and not spurious and sed["max"] <= 1.0)
            check("B5", cname, "接入窗口@%g° 起止差 max (s)" % mask,
                  sed["max"] if pairs else float("nan"), "≤1 且无漏/误报", ok,
                  "STK %d 窗 vs 我方 %d 窗，漏 %d 多 %d"
                  % (len(tiv), len(miv), len(missed), len(spurious)))
            lines.append("- **B5 接入 @%g°**：STK %d 窗 / 我方 %d 窗，配对 %d，"
                         "漏 %d、多 %d，起止差 max %s s"
                         % (mask, len(tiv), len(miv), len(pairs), len(missed),
                            len(spurious), fmt(sed["max"], 1) if pairs else "n/a"))


def main():
    lines = ["# STK 11 对标报告 · 轨道/电/热\n",
             "场景：%s 起 24 h，步长 %g s；判据源自 NTU 测试报告（STK 为真值）。"
             % (cases.EPOCH_UTCG, cases.STEP_S)]
    for cname, cfg in cases.TLE_CASES.items():
        run_case(cname, cfg, lines)

    # verdict table
    lines.append("\n## 判定汇总\n")
    lines.append("| ID | 用例 | 指标 | 实测 | 门限 | 判定 | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    n_pass = 0
    for c in CHECKS:
        n_pass += c["pass"]
        lines.append("| %s | %s | %s | %s | %s | %s | %s |"
                     % (c["id"], c["case"], c["metric"], fmt(c["value"]),
                        c["gate"], "✅" if c["pass"] else "❌", c["note"]))
    lines.append("\n**通过 %d / %d**\n" % (n_pass, len(CHECKS)))

    os.makedirs(cases.OUT_DIR, exist_ok=True)
    report = "\n".join(lines) + "\n"
    with open(os.path.join(cases.OUT_DIR, "REPORT.md"), "w",
              encoding="utf-8") as f:
        f.write(report)
    with open(os.path.join(cases.OUT_DIR, "summary.json"), "w",
              encoding="utf-8") as f:
        json.dump(CHECKS, f, indent=2, ensure_ascii=False)
    print(report)


if __name__ == "__main__":
    main()
