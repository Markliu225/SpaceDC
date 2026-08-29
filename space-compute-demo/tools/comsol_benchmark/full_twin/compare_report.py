# -*- coding: utf-8 -*-
"""Phase 5 — compare COMSOL probes with the OrbitWiz reference and plot.

    backend/.venv/Scripts/python compare_report.py caseA caseB

Inputs  out/orbitwiz/<case>_<gpu>_1s.csv     (run_orbitwiz.py)
        out/comsol/<case>_probes.csv          (build_comsol.py -> solve_and_probe.py)
        out/comsol/<case>_solve_log.json      (energy balance, areas)
Outputs out/compare/<case>_stats.json, <case>_overlay.png, <case>_aligned.csv,
        out/compare/SUMMARY.md
Timeline: COMSOL time tau = OrbitWiz t - T0_HOT (2051 s). Orbit 1 (tau < P) is
discarded; statistics are over orbits 2-3 (P <= tau <= 3P).
"""
import csv, json, math, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out"); CMP = os.path.join(OUT, "compare"); os.makedirs(CMP, exist_ok=True)
CASES = {"caseA": "V100", "caseB": "A100"}
T0 = 2051.0
P = 5574.193548387097
R_TH = {"V100": 0.12, "A100": 0.085, "H200": 0.060, "B200": 0.045}     # llm_perf.py (assumption; used ONLY to map a COMSOL baseplate to a die-equivalent)
T_THR = {"V100": 83.0, "A100": 85.0, "H200": 85.0, "B200": 85.0}
COL_COMSOL, COL_OW, COL_MUTED = "#2a78d6", "#eb6834", "#52514e"


def load_ow(case):
    gpu = CASES[case]
    rows = list(csv.DictReader(open(os.path.join(OUT, "orbitwiz", f"{case}_{gpu}_1s.csv"), encoding="utf-8")))
    t = np.array([float(r['t_s']) for r in rows]) - T0
    d = {k: np.array([float(r[k]) for r in rows]) for k in
         ('T_struct_c', 'gpu_die_temp_c', 'payload_w', 'heat_total_w', 'q_out_w', 'illum', 'sunlit', 'gpu_throttled',
          'q_env_sun_w', 'q_env_albedo_w', 'q_env_ir_w', 'gpu_power_w_per_gpu')}
    d['tau'] = t
    return d


def load_cm(case):
    path = os.path.join(OUT, "comsol", f"{case}_probes.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    d = {}
    for k in rows[0]:
        try:
            d[k] = np.array([float(r[k]) if r[k] != '' else np.nan for r in rows])
        except ValueError:
            pass
    return d


def window(tau, lo, hi):
    return (tau >= lo) & (tau <= hi)


def stats(x):
    return dict(min=float(np.nanmin(x)), max=float(np.nanmax(x)), mean=float(np.nanmean(x)))


def first_crossing(t, x, thr):
    idx = np.where(x >= thr)[0]
    return float(t[idx[0]]) if len(idx) else None


WIN = (1.0, 3.0)   # orbits [lo, hi] used for statistics; periodicity compares [lo,lo+1] vs [lo+1,hi]


def analyse(case):
    gpu = CASES[case]
    ow = load_ow(case); cm = load_cm(case)
    cmC = {k: v - 273.15 for k, v in cm.items() if k.endswith('_K')}
    tau_cm = cm['t_s']
    # interpolate OrbitWiz onto the COMSOL output times
    ow_on = {k: np.interp(tau_cm, ow['tau'], ow[k]) for k in ('T_struct_c', 'gpu_die_temp_c', 'payload_w', 'heat_total_w', 'q_out_w', 'illum', 'gpu_power_w_per_gpu')}
    lo, hi = WIN[0] * P, WIN[1] * P
    w = window(tau_cm, lo, hi)
    probes = {
        'radiator_mean_C': (cmC['rad_mean_K'], ow_on['T_struct_c']),
        'radiator_max_C': (cmC['rad_max_K'], ow_on['T_struct_c']),
        'baseplate_mean_C': (cmC['baseplate_mean_K'], ow_on['T_struct_c']),
        'bus_mean_C': (cmC['bus_mean_K'], ow_on['T_struct_c']),
    }
    out = dict(case=case, gpu=gpu, n_comsol_points=int(len(tau_cm)), window_orbits=f'{WIN[0]+1:.0f}-{WIN[1]:.0f}', probes={})
    for name, (c, o) in probes.items():
        dev = c[w] - o[w]
        out['probes'][name] = dict(comsol=stats(c[w]), orbitwiz=stats(o[w]),
                                   max_abs_dev_C=float(np.nanmax(np.abs(dev))), mean_dev_C=float(np.nanmean(dev)),
                                   t_of_max_abs_dev_s=float(tau_cm[w][int(np.nanargmax(np.abs(dev)))]))
    # radiator in-plane gradient (max - area-weighted mean), per orbit window
    grad = cmC['rad_max_K'] - cmC['rad_mean_K']
    out['radiator_gradient_C'] = dict(max=float(np.nanmax(grad[w])), mean=float(np.nanmean(grad[w])), min=float(np.nanmin(grad[w])))
    if 'rad_min_K' in cmC:
        out['radiator_max_minus_min_C'] = dict(max=float(np.nanmax((cmC['rad_max_K'] - cmC['rad_min_K'])[w])), mean=float(np.nanmean((cmC['rad_max_K'] - cmC['rad_min_K'])[w])))
    # per-panel gradients
    for k in cmC:
        if k.startswith('Radiator') and k.endswith('_max_K'):
            base = k[:-6]
            if base + '_mean_K' in cmC:
                g = cmC[k] - cmC[base + '_mean_K']
                out.setdefault('per_face_gradient_C', {})[base] = dict(max=float(np.nanmax(g[w])), mean=float(np.nanmean(g[w])))
    # periodicity: orbit 2 vs orbit 3 overlap
    per = {}
    for name in ('rad_mean_K', 'baseplate_mean_K', 'bus_mean_K'):
        x = cmC[name]
        t2 = tau_cm[window(tau_cm, lo, lo + P)]; x2 = x[window(tau_cm, lo, lo + P)]
        t3 = tau_cm[window(tau_cm, lo + P, hi)]; x3 = x[window(tau_cm, lo + P, hi)]
        x3i = np.interp(t2 + P, t3, x3)
        per[name] = float(np.nanmax(np.abs(x3i - x2)))
    out['periodicity_orbit2_vs_3_max_abs_C'] = per
    # 85 C crossing (Case B): OrbitWiz die; COMSOL baseplate + P*R_th (die-equivalent) and raw baseplate max
    thr = T_THR[gpu]
    ow_die = ow_on['gpu_die_temp_c']
    cm_die_eq = cmC['baseplate_max_K'] + ow_on['gpu_power_w_per_gpu'] * R_TH[gpu]
    cm_die_eq_mean = cmC['baseplate_mean_K'] + ow_on['gpu_power_w_per_gpu'] * R_TH[gpu]
    cross = {}
    for lo_, hi_, tag in ((lo, lo + P, f'orbit{WIN[0]+1:.0f}'), (lo + P, hi, f'orbit{WIN[1]:.0f}'), (0, hi, 'all')):
        m = window(tau_cm, lo_, hi_)
        cross[tag] = dict(
            orbitwiz_die_first_ge_thr_s=first_crossing(tau_cm[m], ow_die[m], thr - 0.05),
            comsol_die_equiv_max_first_ge_thr_s=first_crossing(tau_cm[m], cm_die_eq[m], thr),
            comsol_die_equiv_mean_first_ge_thr_s=first_crossing(tau_cm[m], cm_die_eq_mean[m], thr),
            comsol_baseplate_max_first_ge_thr_s=first_crossing(tau_cm[m], cmC['baseplate_max_K'][m], thr))
        a, b = cross[tag]['orbitwiz_die_first_ge_thr_s'], cross[tag]['comsol_die_equiv_max_first_ge_thr_s']
        cross[tag]['difference_s'] = (b - a) if (a is not None and b is not None) else None
    out['throttle_crossing'] = dict(threshold_C=thr, r_th_used_K_per_W=R_TH[gpu], windows=cross,
                                    orbitwiz_throttled_fraction_orbits2_3=float(np.nanmean(np.interp(tau_cm[w], ow['tau'], ow['gpu_throttled']))),
                                    comsol_die_equiv_max_C=float(np.nanmax(cm_die_eq[w])), orbitwiz_die_max_C=float(np.nanmax(ow_die[w])))
    # radiated power comparison
    if 'emitted_rad_W' in cm:
        out['radiated_power_W'] = dict(comsol_radiator_faces=stats(cm['emitted_rad_W'][w]), orbitwiz_q_out=stats(ow_on['q_out_w'][w]))
    # aligned CSV
    with open(os.path.join(CMP, f"{case}_aligned.csv"), "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        cols = ['tau_s', 'comsol_rad_mean_C', 'comsol_rad_max_C', 'comsol_baseplate_mean_C', 'comsol_baseplate_max_C', 'comsol_bus_mean_C', 'comsol_wing_mean_C',
                'orbitwiz_T_struct_C', 'orbitwiz_die_C', 'comsol_die_equiv_C', 'orbitwiz_payload_W', 'orbitwiz_illum']
        wr.writerow(cols)
        for i in range(len(tau_cm)):
            wr.writerow([tau_cm[i], cmC['rad_mean_K'][i], cmC['rad_max_K'][i], cmC['baseplate_mean_K'][i], cmC['baseplate_max_K'][i], cmC['bus_mean_K'][i], cmC.get('wing_mean_K', np.full_like(tau_cm, np.nan))[i],
                         ow_on['T_struct_c'][i], ow_die[i], cm_die_eq[i], ow_on['payload_w'][i], ow_on['illum'][i]])
    json.dump(out, open(os.path.join(CMP, f"{case}_stats_o{WIN[0]+1:.0f}{WIN[1]:.0f}.json"), "w"), indent=1)
    plot(case, gpu, tau_cm, cmC, ow_on, ow_die, cm_die_eq, thr)
    return out


def plot(case, gpu, tau, cmC, ow_on, ow_die, cm_die_eq, thr):
    m = window(tau, WIN[0] * P, WIN[1] * P)
    t = tau[m] / 3600.0
    fig, axes = plt.subplots(4, 1, figsize=(9, 11), sharex=True, facecolor="#fcfcfb")
    panels = [
        ('Radiator (area-weighted mean)', cmC['rad_mean_K'][m], ow_on['T_struct_c'][m], 'OrbitWiz single node'),
        ('Radiator max', cmC['rad_max_K'][m], ow_on['T_struct_c'][m], 'OrbitWiz single node'),
        ('GPU baseplate (mean of 12 TIM faces)', cmC['baseplate_mean_K'][m], ow_on['T_struct_c'][m], 'OrbitWiz single node'),
        ('Bus mean', cmC['bus_mean_K'][m], ow_on['T_struct_c'][m], 'OrbitWiz single node'),
    ]
    for ax, (title, c, o, olabel) in zip(axes, panels):
        ax.set_facecolor("#fcfcfb")
        ax.plot(t, o, color=COL_OW, lw=2, label=olabel)
        ax.plot(t, c, color=COL_COMSOL, lw=2, label='COMSOL')
        ax.set_ylabel('°C', color=COL_MUTED)
        ax.set_title(title, loc='left', fontsize=10, color='#0b0b0b')
        ax.grid(True, color='#e6e5e1', lw=0.6); ax.spines[['top', 'right']].set_visible(False)
        ax.tick_params(colors=COL_MUTED)
        ax.legend(frameon=False, fontsize=8, loc='upper right')
    # eclipse shading
    ill = ow_on['illum'][m]
    for ax in axes:
        ax.fill_between(t, ax.get_ylim()[0], ax.get_ylim()[1], where=ill < 0.5, color='#f0efec', zorder=0)
    axes[-1].set_xlabel(f'time since hot instant [h]  (orbits {WIN[0]+1:.0f}-{WIN[1]:.0f})', color=COL_MUTED)
    fig.suptitle(f'{case} ({gpu}, 12 cards, WhitePaint radiator): COMSOL vs OrbitWiz', fontsize=12, x=0.02, ha='left')
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(os.path.join(CMP, f'{case}_overlay_o{WIN[0]+1:.0f}{WIN[1]:.0f}.png'), dpi=150)
    plt.close(fig)
    # die-temperature figure
    fig, ax = plt.subplots(figsize=(9, 3.6), facecolor="#fcfcfb"); ax.set_facecolor("#fcfcfb")
    ax.plot(t, ow_die[m], color=COL_OW, lw=2, label='OrbitWiz die (T_struct + P·R_th)')
    ax.plot(t, cm_die_eq[m], color=COL_COMSOL, lw=2, label='COMSOL baseplate max + P·R_th (die-equivalent)')
    ax.axhline(thr, color='#e34948', lw=1, ls='--'); ax.text(t[0], thr + 0.5, f'throttle {thr:.0f} °C', color='#e34948', fontsize=8)
    ax.fill_between(t, ax.get_ylim()[0], ax.get_ylim()[1], where=ill < 0.5, color='#f0efec', zorder=0)
    ax.set_ylabel('°C', color=COL_MUTED); ax.set_xlabel('time since hot instant [h]', color=COL_MUTED)
    ax.grid(True, color='#e6e5e1', lw=0.6); ax.spines[['top', 'right']].set_visible(False); ax.legend(frameon=False, fontsize=8)
    ax.set_title(f'{case} ({gpu}): GPU die-equivalent temperature', loc='left', fontsize=10)
    fig.tight_layout(); fig.savefig(os.path.join(CMP, f'{case}_die_o{WIN[0]+1:.0f}{WIN[1]:.0f}.png'), dpi=150); plt.close(fig)


def summary_md(results):
    L = [f"# COMSOL vs OrbitWiz — comparison summary (orbits {WIN[0]+1:.0f}-{WIN[1]:.0f})\n"]
    for r in results:
        L.append(f"## {r['case']} ({r['gpu']})\n")
        L.append("| Probe | COMSOL min / max / mean (°C) | OrbitWiz min / max / mean (°C) | max |dev| (°C) | mean dev (°C) |")
        L.append("|---|---|---|---|---|")
        for k, v in r['probes'].items():
            c, o = v['comsol'], v['orbitwiz']
            L.append(f"| {k} | {c['min']:.1f} / {c['max']:.1f} / {c['mean']:.1f} | {o['min']:.1f} / {o['max']:.1f} / {o['mean']:.1f} | {v['max_abs_dev_C']:.1f} | {v['mean_dev_C']:+.1f} |")
        g = r['radiator_gradient_C']
        L.append(f"\nRadiator in-plane gradient (max − area-weighted mean): mean {g['mean']:.2f} °C, max {g['max']:.2f} °C.")
        per = r['periodicity_orbit2_vs_3_max_abs_C']
        L.append(f"Periodicity (orbit {WIN[0]+1:.0f} vs {WIN[1]:.0f}, max |ΔT|): " + ", ".join(f"{k} {v:.2f} °C" for k, v in per.items()))
        tc = r['throttle_crossing']
        L.append(f"\nThrottle threshold {tc['threshold_C']:.0f} °C: OrbitWiz die max {tc['orbitwiz_die_max_C']:.1f} °C (throttled {100*tc['orbitwiz_throttled_fraction_orbits2_3']:.0f} % of orbits 2-3); COMSOL die-equivalent max {tc['comsol_die_equiv_max_C']:.1f} °C.")
        for wname, wv in tc['windows'].items():
            L.append(f"- {wname}: OrbitWiz first ≥ thr at {wv['orbitwiz_die_first_ge_thr_s']} s; COMSOL die-equiv (max baseplate) at {wv['comsol_die_equiv_max_first_ge_thr_s']} s; raw baseplate max ≥ thr at {wv['comsol_baseplate_max_first_ge_thr_s']} s; difference {wv['difference_s']} s")
        if 'radiated_power_W' in r:
            rp = r['radiated_power_W']
            L.append(f"\nRadiated power (radiator faces, orbits {WIN[0]+1:.0f}-{WIN[1]:.0f}): COMSOL mean {rp['comsol_radiator_faces']['mean']:.0f} W vs OrbitWiz Q_out mean {rp['orbitwiz_q_out']['mean']:.0f} W.")
        L.append("")
    open(os.path.join(CMP, f"SUMMARY_o{WIN[0]+1:.0f}{WIN[1]:.0f}.md"), "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0].startswith('--window='):
        lo, hi = argv[0].split('=')[1].split(','); WIN = (float(lo), float(hi)); argv = argv[1:]
    cases = argv or list(CASES)
    res = [analyse(c) for c in cases]
    summary_md(res)
