# -*- coding: utf-8 -*-
"""Fill REPORT.md section 7.7 (orbits 4-5, extended run) from
out/compare/<case>_stats_o45.json and <case>_aligned.csv.  Re-runnable: replaces
everything between the '### 7.7' heading and '## 8.'.
    backend/.venv/Scripts/python fill_sec77.py
"""
import csv, json, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); CMP = os.path.join(HERE, "out", "compare")
P = 5574.193548387097
CASES = (("caseA", "V100", 83.0, "never throttles in OrbitWiz"), ("caseB", "A100", 85.0, "throttled in OrbitWiz"))
NAMES = {"radiator_mean_C": "Radiator, area-weighted mean", "radiator_max_C": "Radiator, max", "baseplate_mean_C": "GPU baseplate, mean of 12 TIM faces", "bus_mean_C": "Bus, volume mean"}


def crossings(case, thr, lo, hi):
    rows = list(csv.DictReader(open(os.path.join(CMP, f"{case}_aligned.csv"), encoding="utf-8")))
    t = np.array([float(r['tau_s']) for r in rows]); ow = np.array([float(r['orbitwiz_die_C']) for r in rows]); cm = np.array([float(r['comsol_die_equiv_C']) for r in rows])
    m = (t >= lo) & (t <= hi); t, ow, cm = t[m], ow[m], cm[m]
    out = {}
    for name, x, th in (("OrbitWiz die", ow, thr - 0.05), ("COMSOL die-equivalent", cm, thr)):
        ab = x >= th
        ups = [int(round(t[i + 1])) for i in np.where(~ab[:-1] & ab[1:])[0]]; downs = [int(round(t[i + 1])) for i in np.where(ab[:-1] & ~ab[1:])[0]]
        out[name] = dict(min=float(x.min()), max=float(x.max()), frac=float(ab.mean()), ups=ups, downs=downs)
    return out


def periodicity_diag(case):
    """Per-orbit means, orbit-to-orbit variation of the reference and of COMSOL, and the
    same-workload-phase check one workload cycle (21 600 s) apart."""
    rows = list(csv.DictReader(open(os.path.join(CMP, f"{case}_aligned.csv"), encoding="utf-8")))
    t = np.array([float(r['tau_s']) for r in rows]); col = lambda k: np.array([float(r[k]) for r in rows])
    rad, bp, bus, ow, pw = col('comsol_rad_mean_C'), col('comsol_baseplate_mean_C'), col('comsol_bus_mean_C'), col('orbitwiz_T_struct_C'), col('orbitwiz_payload_W')
    n_orb = int(round(t.max() / P))          # last orbit ends within one output step of 5P
    L = ["| Orbit | mean payload (W) | OrbitWiz node mean (°C) | COMSOL radiator mean | COMSOL baseplate mean | COMSOL bus mean | bus − node | radiator − node |", "|---|---|---|---|---|---|---|---|"]
    for k in range(n_orb):
        m = (t >= k * P) & (t < (k + 1) * P + 1.0)
        L.append(f"| {k+1} | {pw[m].mean():.0f} | {ow[m].mean():.1f} | {rad[m].mean():.1f} | {bp[m].mean():.1f} | {bus[m].mean():.1f} | {bus[m].mean()-ow[m].mean():+.1f} | {rad[m].mean()-ow[m].mean():+.1f} |")

    def per(x, k):
        m1 = (t >= (k - 1) * P) & (t <= k * P); m2 = (t >= k * P) & (t <= (k + 1) * P)
        return float(np.max(np.abs(np.interp(t[m1] + P, t[m2], x[m2]) - x[m1])))
    L += ["", "| Orbit pair | OrbitWiz node max \\|ΔT\\| (°C) | COMSOL radiator | COMSOL baseplate | COMSOL bus |", "|---|---|---|---|---|"]
    for k in range(1, n_orb):
        L.append(f"| {k} vs {k+1} | {per(ow, k):.2f} | {per(rad, k):.2f} | {per(bp, k):.2f} | {per(bus, k):.2f} |")
    W = 21600.0; m = (t >= P) & (t + W <= t.max())
    L.append("")
    if m.sum() >= 3:
        parts = []
        for name, x in (("OrbitWiz node", ow), ("COMSOL radiator mean", rad), ("COMSOL baseplate mean", bp), ("COMSOL bus mean", bus)):
            d = np.interp(t[m] + W, t, x) - x[m]
            parts.append(f"{name} mean {d.mean():+.2f} / max \\|Δ\\| {np.abs(d).max():.2f} °C")
        L.append(f"Same-workload-phase check, T(τ + 21 600 s) − T(τ) for τ ∈ [{P:.0f}, {t[m].max():.0f}] s ({m.sum()} samples at identical payload; the orbit phase is shifted by 21 600 − 3.875·5574 ≈ −697 s, i.e. eclipse timing differs by 12 % of an orbit, which the thin radiator feels and the bus does not): " + "; ".join(parts) + ".")
    else:
        L.append("Same-workload-phase check not possible (run shorter than one workload cycle + one orbit).")
    return L


def main():
    L = ["### 7.7 Orbits 4–5 (extended run, initialised from the orbit-3 state)\n",
         "Same definitions as §7.3–7.6; window 3P ≤ τ ≤ 5P (`out/compare/*_stats_o45.json`, `SUMMARY_o45.md`, overlays `*_overlay_o45.png`, `*_die_o45.png`). "
         "The extension re-uses the saved models, adds loads study LB2 and temperature study B2 (strict BDF-1, Δt = 120 s, initial values = last step of study B) and the OrbitWiz traces regenerated over 7 orbits (identical to the original ones where they overlap).\n"]
    for case, gpu, thr, note in CASES:
        p = os.path.join(CMP, f"{case}_stats_o45.json")
        if not os.path.exists(p):
            L.append(f"*{case}: orbits 4–5 statistics not available (extension did not complete).*\n"); continue
        s = json.load(open(p))
        L.append(f"**{case} — {gpu}, {note}**\n")
        L.append("| Probe | COMSOL min / max / cyclic mean (°C) | OrbitWiz min / max / mean (°C) | **max \\|dev\\|** (°C) | mean dev (°C) |")
        L.append("|---|---|---|---|---|")
        for k, v in s['probes'].items():
            c, o = v['comsol'], v['orbitwiz']
            L.append(f"| {NAMES.get(k, k)} | {c['min']:.1f} / {c['max']:.1f} / {c['mean']:.1f} | {o['min']:.1f} / {o['max']:.1f} / {o['mean']:.1f} | **{v['max_abs_dev_C']:.1f}** | {v['mean_dev_C']:+.1f} |")
        g = s['radiator_gradient_C']; per = s['periodicity_orbit2_vs_3_max_abs_C']
        L.append("")
        L.append(f"Radiator in-plane gradient (max − area-weighted mean): mean **{g['mean']:.2f} °C**, max **{g['max']:.2f} °C**"
                 + (f"; max − min over the faces mean {s['radiator_max_minus_min_C']['mean']:.1f} °C." if 'radiator_max_minus_min_C' in s else "."))
        crit = "PASS" if max(per.values()) <= 0.5 else "FAIL"
        L.append(f"**Periodicity, orbit 4 vs orbit 5** (max |T(τ+P) − T(τ)|): radiator mean {per['rad_mean_K']:.2f} °C, baseplate {per['baseplate_mean_K']:.2f} °C, bus {per['bus_mean_K']:.2f} °C → **{crit}** against the 0.5 °C criterion.")
        rp = s.get('radiated_power_W')
        if rp:
            L.append(f"Radiated power through the radiator faces, mean: COMSOL {rp['comsol_radiator_faces']['mean']:.0f} W vs OrbitWiz Q_out {rp['orbitwiz_q_out']['mean']:.0f} W.")
        tc = s['throttle_crossing']; cr = crossings(case, thr, 3 * P, 5 * P)
        L.append(f"Throttle line {thr:.0f} °C: OrbitWiz die max {tc['orbitwiz_die_max_C']:.1f} °C (≥ threshold {cr['OrbitWiz die']['frac']*100:.0f} % of the window; upward crossings at τ = {cr['OrbitWiz die']['ups'] or '—'} s, downward at {cr['OrbitWiz die']['downs'] or '—'} s); "
                 f"COMSOL die-equivalent {cr['COMSOL die-equivalent']['min']:.1f}–{cr['COMSOL die-equivalent']['max']:.1f} °C (≥ threshold {cr['COMSOL die-equivalent']['frac']*100:.0f} %; upward crossings at τ = {cr['COMSOL die-equivalent']['ups'] or '—'} s, downward at {cr['COMSOL die-equivalent']['downs'] or '—'} s).")
        w = tc['windows']
        for tag in sorted(w):
            d = w[tag]
            L.append(f"- {tag}: first ≥ threshold — OrbitWiz {d['orbitwiz_die_first_ge_thr_s']} s, COMSOL die-equiv {d['comsol_die_equiv_max_first_ge_thr_s']} s, difference {d['difference_s']} s")
        L.append("")
        p25 = os.path.join(CMP, f"{case}_stats_o25.json")
        if os.path.exists(p25):
            s25 = json.load(open(p25))
            L.append(f"Whole-run window, orbits 2–5 (`{case}_stats_o25.json`, `{case}_overlay_o25.png`): max \\|dev\\| " + ", ".join(f"{NAMES.get(k, k)} **{v['max_abs_dev_C']:.1f} °C** (mean {v['mean_dev_C']:+.1f})" for k, v in s25['probes'].items())
                     + f"; radiator gradient mean {s25['radiator_gradient_C']['mean']:.2f} / max {s25['radiator_gradient_C']['max']:.2f} °C.")
            L.append("")
        L.append("Periodicity diagnostics — per-orbit means, orbit-to-orbit variation of the *reference itself* and of COMSOL, and the same-workload-phase check:\n")
        L += periodicity_diag(case); L.append("")
    text = "\n".join(L) + "\n"
    rp = os.path.join(HERE, "REPORT.md"); r = open(rp, encoding="utf-8").read()
    a = r.index("### 7.7"); b = r.index("## 8. Things I am unsure about")
    r = r[:a] + text + r[b:]
    open(rp, "w", encoding="utf-8").write(r); print("section 7.7 written (%d lines)" % len(L))


if __name__ == "__main__":
    main()
