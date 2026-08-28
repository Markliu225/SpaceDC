# -*- coding: utf-8 -*-
"""Score COMSOL thermal results against our lumped model (and STK SEET for T1).

Inputs (drop COMSOL table exports here, see SPEC.md for the column contract):
    out/comsol/t1.csv   isothermal sphere case
    out/comsol/t2.csv   nadir-pointing radiator plate case
Reference (from gen_reference.py):
    out/ref/t1_sphere_ref.csv, out/ref/t2_plate_ref.csv, out/ref/stk_seet_t1.csv
Output: out/REPORT.md + out/summary.json.  Pure stdlib.

COMSOL table exports start with '%' comment lines; the last one is the
header. Columns are matched by keyword (case-insensitive):
    time:   t, time
    T mean: mean, avg, aveop, average
    T max:  max            T min: min
    fluxes (optional, T1 in W; T2 in W/m2 per face):
        sun / solar, albedo, ir / infrared / planet
"""
import csv, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REF, COM, OUT = (os.path.join(HERE, "out", d) for d in ("ref", "comsol", ""))
CHECKS = []


def load_ref(name):
    with open(os.path.join(REF, name), newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    hdr = rows[0]
    return {h: [float(r[i]) for r in rows[1:]] for i, h in enumerate(hdr)}


def load_comsol(name):
    """Tolerant reader for COMSOL table exports (csv or whitespace txt)."""
    path = os.path.join(COM, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    header, data = None, []
    for ln in lines:
        if ln.startswith("%"):
            header = ln.lstrip("% ").strip()
            continue
        data.append(ln)
    if header is None:                       # plain csv with a normal header
        header, data = data[0], data[1:]
    # data separator from the data rows themselves (csv export: comma;
    # txt export: whitespace) — the header may use commas either way
    dsep = "," if "," in data[0] else None
    rows = [[v for v in (ln.split(dsep) if dsep else ln.split()) if v.strip()] for ln in data]
    ncols = max(set(len(r) for r in rows), key=lambda k: sum(1 for r in rows if len(r) == k))
    if "," in header:
        cols = [c.strip() for c in header.split(",")]
    else:
        cols = [c.strip() for c in re.split(r"\s{2,}|\t", header) if c.strip()]
    # COMSOL column descriptions can contain commas ("Temperature, mean (K)"):
    # merge tokens without a closing unit parenthesis into the next one until
    # the header count matches the data count
    while len(cols) > ncols:
        merged = False
        for i in range(len(cols) - 1):
            if ")" not in cols[i]:
                cols[i:i + 2] = [cols[i] + " " + cols[i + 1]]
                merged = True
                break
        if not merged:
            cols[-2:] = [cols[-2] + " " + cols[-1]]
    while len(cols) < ncols:
        cols.append("col%d" % len(cols))
    table = {c: [] for c in cols}
    for vals in rows:
        if len(vals) != ncols:
            continue
        for c, v in zip(cols, vals):
            try:
                table[c].append(float(v))
            except ValueError:
                table[c].append(float("nan"))
    return table


def pick(table, *keys, exclude=()):
    for c in table:
        lc = c.lower()
        if any(k in lc for k in keys) and not any(x in lc for x in exclude):
            return table[c]
    return None


def interp(xs, ys, x):
    """Linear interpolation onto x (xs ascending)."""
    import bisect
    i = bisect.bisect_left(xs, x)
    if i <= 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def stats(d):
    if not d:
        return dict(n=0, mean=0.0, rms=0.0, max=0.0)
    return dict(n=len(d), mean=sum(d) / len(d),
                rms=math.sqrt(sum(v * v for v in d) / len(d)), max=max(abs(v) for v in d))


def check(case, metric, value, gate, ok, note=""):
    CHECKS.append(dict(case=case, metric=metric, value=value, gate=gate, ok=bool(ok), note=note))


def seg_compare(case, ref_t, ref_T, ref_illum, com_t, com_T, label, gate_k):
    """Segment-mean comparison of com_T (interpolated) against ref_T."""
    d_sun, d_ecl = [], []
    for t, T, il in zip(ref_t, ref_T, ref_illum):
        if t < com_t[0] or t > com_t[-1]:
            continue
        d = interp(com_t, com_T, t) - T
        (d_sun if il >= 0.5 else d_ecl).append(d)
    s_sun, s_ecl = stats(d_sun), stats(d_ecl)
    check(case, "%s 光照段均温差 (K)" % label, s_sun["mean"], "|Δ|≤%g" % gate_k, abs(s_sun["mean"]) <= gate_k)
    if d_ecl:
        check(case, "%s 地影段均温差 (K)" % label, s_ecl["mean"], "|Δ|≤%g" % gate_k, abs(s_ecl["mean"]) <= gate_k)
    return s_sun, s_ecl


def flux_compare(case, ref_t, ref_q, ref_illum, com_t, com_q, label, gate_rel, sunlit_only):
    """Energy-weighted relative error sum(com-ref)/sum(ref) over the segment
    (robust near the terminator where pointwise ratios blow up); pointwise
    rms of the absolute difference is reported as a note."""
    num = den = 0.0
    absd = []
    for t, q, il in zip(ref_t, ref_q, ref_illum):
        if t < com_t[0] or t > com_t[-1]:
            continue
        if sunlit_only and il < 0.5:
            continue
        c = interp(com_t, com_q, t)
        num += c - q
        den += q
        absd.append(c - q)
    rel = num / den if den else 0.0
    s = stats(absd)
    check(case, "%s 能量加权相对误差" % label, rel * 100, "|Δ|≤%g%%" % (gate_rel * 100), abs(rel) <= gate_rel,
          "逐点差 rms %.2f" % s["rms"])
    return dict(mean=rel, rms=s["rms"])


def main():
    lines = ["# COMSOL 热对比报告\n"]
    t1r, t2r = load_ref("t1_sphere_ref.csv"), load_ref("t2_plate_ref.csv")
    seet = load_ref("stk_seet_t1.csv")
    c1, c2 = load_comsol("t1.csv"), load_comsol("t2.csv")

    lines.append("## T1 等温球，三方对照\n")
    if c1 is None:
        lines.append("未找到 out/comsol/t1.csv。\n")
    else:
        ct = pick(c1, "time", "t_s", "t (") or pick(c1, "t")
        cT = pick(c1, "mean", "avg", "aveop", "average") or pick(c1, "temperature", "temp")
        s_sun, s_ecl = seg_compare("T1", t1r["t_s"], t1r["T_lumped_K"], t1r["illum"], ct, cT, "COMSOL−SpaceDC", 2.0)
        lines.append("- COMSOL − SpaceDC 集总：光照段 mean %.2f K (rms %.2f)，地影段 mean %.2f K (rms %.2f)" % (
            s_sun["mean"], s_sun["rms"], s_ecl["mean"], s_ecl["rms"]))
        # STK SEET is a steady-state model; COMSOL's transient shell lags the
        # equilibrium by the thermal-mass term, so the transient-vs-SEET offset
        # is informational only. The like-for-like three-way check uses the
        # equilibrium implied by COMSOL's OWN absorbed fluxes.
        st, sT = seet["t"], seet["temp_k"]
        seet_on_grid = [interp(st, sT, t) for t in t1r["t_s"]]
        d_info = [interp(ct, cT, t) - s for t, s in zip(t1r["t_s"], seet_on_grid) if ct[0] <= t <= ct[-1]]
        lines.append("- COMSOL 瞬态 − STK SEET 稳态：mean %.2f K，仅供参考，差值来自热容滞后" % stats(d_info)["mean"])
        qcols = {}
        for key, col, gate, sun_only in (("sun", "Q_sun_W", 0.02, True), ("albedo", "Q_albedo_W", 0.10, True), ("ir", "Q_ir_W", 0.10, False)):
            q = pick(c1, key, "solar" if key == "sun" else key, "infrared" if key == "ir" else key, "planet" if key == "ir" else key)
            if q is not None:
                qcols[key] = q
                s = flux_compare("T1", t1r["t_s"], t1r[col], t1r["illum"], ct, q, "热流 %s" % key, gate, sun_only)
                lines.append("- 热流 %s：COMSOL 相对我方能量加权 %.1f%%" % (key, s["mean"] * 100))
        if len(qcols) == 3:
            P = json.load(open(os.path.join(REF, "case_params.json"), encoding="utf-8"))["T1"]
            sig = 5.67e-8
            T_eq_c = [((P["P_W"] + interp(ct, qcols["sun"], t) + interp(ct, qcols["albedo"], t) + interp(ct, qcols["ir"], t))
                       / (P["eps"] * sig * P["A_surf"])) ** 0.25 for t in t1r["t_s"]]
            fake_t = t1r["t_s"]
            s1, e1 = seg_compare("T1", t1r["t_s"], seet_on_grid, t1r["illum"], fake_t, T_eq_c, "COMSOL 热流推得平衡温度−STK SEET", 2.0)
            s2, e2 = seg_compare("T1", t1r["t_s"], t1r["T_eq_K"], t1r["illum"], fake_t, T_eq_c, "COMSOL 热流推得平衡温度−SpaceDC 平衡", 2.0)
            lines.append("- 由 COMSOL 吸收热流推得的平衡温度：对 STK SEET 光照段 %.2f K、地影段 %.2f K；对 SpaceDC 平衡温度光照段 %.2f K、地影段 %.2f K"
                         % (s1["mean"], e1["mean"], s2["mean"], e2["mean"]))
        else:
            lines.append("- 未导出全部三项热流，跳过与 STK SEET 的稳态三方对照")

    lines.append("\n## T2 对地辐射板，集总假设误差\n")
    if c2 is None:
        lines.append("未找到 out/comsol/t2.csv。\n")
    else:
        ct = pick(c2, "time", "t_s", "t (") or pick(c2, "t")
        cT = pick(c2, "mean", "avg", "aveop", "average") or pick(c2, "temperature", "temp")
        cmax, cmin = pick(c2, "max"), pick(c2, "min")
        s_sun, s_ecl = seg_compare("T2", t2r["t_s"], t2r["T_lumped_K"], t2r["illum"], ct, cT, "COMSOL 板均温−SpaceDC", 5.0)
        lines.append("- COMSOL 板均温 − SpaceDC 集总：光照段 mean %.2f K，地影段 mean %.2f K" % (s_sun["mean"], s_ecl["mean"]))
        if cmax is not None:
            grad = [a - b for a, b in zip(cmax, cT)]
            g = stats(grad)
            check("T2", "热点−均温 (K) max", g["max"], "报告值，>10 K 则需增加冷板节点", True,
                  "mean %.2f K" % g["mean"])
            lines.append("- 热点（热源区）与板均温之差：mean %.2f K，max %.2f K" % (g["mean"], g["max"]))
            if cmin is not None:
                span = [a - b for a, b in zip(cmax, cmin)]
                lines.append("- 板内最大温差 (max−min)：mean %.2f K，max %.2f K" % (stats(span)["mean"], stats(span)["max"]))
        for key, col, gate, sun_only in (("sun", "q_sun_zenith_W_m2", 0.02, True), ("albedo", "q_albedo_nadir_W_m2", 0.10, True), ("ir", "q_ir_nadir_W_m2", 0.10, False)):
            q = pick(c2, key, "solar" if key == "sun" else key, "infrared" if key == "ir" else key)
            if q is not None:
                s = flux_compare("T2", t2r["t_s"], t2r[col], t2r["illum"], ct, q, "面热流 %s" % key, gate, sun_only)
                lines.append("- 面热流 %s：COMSOL 相对我方能量加权 %.1f%%" % (key, s["mean"] * 100))

    lines.append("\n## 判定\n\n| 用例 | 指标 | 值 | 门限 | 判定 | 备注 |\n| --- | --- | --- | --- | --- | --- |")
    for c in CHECKS:
        lines.append("| %s | %s | %.3f | %s | %s | %s |" % (c["case"], c["metric"], c["value"], c["gate"], "✅" if c["ok"] else "❌", c["note"]))
    n_ok = sum(1 for c in CHECKS if c["ok"])
    lines.append("\n**通过 %d / %d**\n" % (n_ok, len(CHECKS)))
    rep = "\n".join(lines)
    with open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write(rep)
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(CHECKS, f, ensure_ascii=False, indent=2)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(rep)


if __name__ == "__main__":
    main()
