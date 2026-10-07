# -*- coding: utf-8 -*-
"""Derived result quantities for the report (all from out/<tag>/ probe files)."""
import numpy as np
import iss_results as R

MODS = ('destiny', 'harmony', 'tranquility', 'columbus', 'kibo')
MOD_CN = {'destiny': 'Destiny', 'harmony': 'Harmony', 'tranquility': 'Tranquility', 'columbus': 'Columbus', 'kibo': 'Kibo'}


def num(x, nd=1):
    """Number with a true minus sign (U+2212); a value that rounds to zero prints without a sign."""
    if round(float(x), nd) == 0:
        x = 0.0
    s = f'{x:.{nd}f}'
    return s.replace('-', '−')


def rng(a, b, nd=1):
    return num(a, nd) if num(a, nd) == num(b, nd) else f'{num(a, nd)} 至 {num(b, nd)}'


def rngu(a, b, nd=1, unit='°C'):
    """Range for running text, unit after both numbers."""
    return f'{num(a, nd)} {unit}' if num(a, nd) == num(b, nd) else f'{num(a, nd)} {unit} 至 {num(b, nd)} {unit}'


def rack_stats(c):
    it = R.items_by_kind(c).get('rack', [])
    out = {}
    for m in MODS:
        rs = [r for r in it if r['name'].startswith(f'rk_{m}_')]
        if not rs: continue
        out[m] = dict(n=len(rs), Tmin=min(r['Tmin'] for r in rs), Tmean=float(np.mean([r['Tmean'] for r in rs])), Tmax=max(r['Tmax'] for r in rs))
    return out


def box_stats(c):
    it = R.items_by_kind(c).get('box', [])
    groups = {'MBSU': [], 'DDCU': [], 'IEA': [], 'ATA': [], 'PM': [], 'NTA': []}
    for r in it:
        for g in groups:
            if r['name'].startswith(g):
                groups[g].append(r)
    out = {}
    for g, rs in groups.items():
        if rs:
            out[g] = dict(n=len(rs), Tmin=min(r['Tmin'] for r in rs), Tmean=float(np.mean([r['Tmean'] for r in rs])), Tmax=max(r['Tmax'] for r in rs))
    return out


def payload_stats(c):
    return {r['name']: r for r in R.items_by_kind(c).get('payload', [])}


def oru_stats(c):
    it = R.items_by_kind(c)
    return {r['name']: r for r in it.get('hrs', [])}, {r['name']: r for r in it.get('pvr', [])}


def skin_stats(c):
    return {r['name']: r for r in R.items_by_kind(c).get('skin', [])}


def truss_stats(c):
    return {r['name']: r for r in R.items_by_kind(c).get('truss', [])}


def pv_loops(c):
    out = {}
    for u in ('P4', 'P6', 'S4', 'S6'):
        L = 'PV' + u
        if f'f_{L}' in c['s']:
            out[u] = dict(f=R.stat(c, f'feff_{L}' if f'feff_{L}' in c['s'] else f'f_{L}'), Q=R.stat(c, f'Q_{L}'), Tout=R.stat(c, f'Tout_{L}_C'), Tmix=R.stat(c, f'Tmix_{L}_C'))
    return out


def saw_eclipse(c):
    """Array temperature at eclipse exit (last orbit) and minutes from eclipse exit until the mean passes 0 C."""
    ecl = c['summ']['orbit'].get('eclipse_deg', 0.0)
    if not ecl or 'saw_Tmean_C' not in c['s']:
        return None
    per = c['per']; t = c['t']
    half = ecl / 360 * per / 2
    k = np.floor((t[-1] - 0.5 * per - half) / per)                              # last eclipse whose exit lies inside the data
    t_exit = (k + 0.5) * per + half
    if t_exit < t[0] or t_exit > t[-1]:
        return None
    Tm = c['s']['saw_Tmean_C']; Tn = c['s']['saw_Tmin_C']
    k = int(np.argmin(np.abs(t - t_exit)))
    before = Tm[max(0, k - 1)]
    after = np.where((t > t_exit) & (Tm > 0.0))[0]
    warm = float((t[after[0]] - t_exit) / 60.0) if len(after) else None
    return dict(T_exit=float(min(Tm[max(0, k - 1):k + 1].min(), before)), Tmin=float(Tn[c['last']].min()), warm_min=warm)


def capacity_note(c):
    """Radiator flow fraction needed for the present load; f = 1 would be the limit."""
    lt = R.loop_table(c)
    return {L: v['f']['max'] for L, v in lt.items()}


BREAKDOWN_CN = [('rack_MT', '舱内机柜冷板，中温水回路'), ('rack_LT', '舱内机柜冷板，低温水回路'), ('air', '舱内空气'), ('mli', '舱体多层隔热漏热'),
                ('oru', '舱外设备冷板'), ('crew', '乘员代谢热')]


def breakdown(c):
    """Loop heat pick-up by source category, last-orbit mean in W: {loop: {category: W}} from loop_breakdown.csv."""
    import csv, os
    p = os.path.join(R.OUT, c['tag'], 'loop_breakdown.csv')
    if not os.path.exists(p):
        return None
    out = {}
    for r in csv.DictReader(open(p, encoding='utf-8')):
        src = r['source']
        cat = ('rack_' + src.rsplit('_', 1)[1]) if src.startswith('rack_') else src.split('_', 1)[0]
        out.setdefault(r['loop'], {}).setdefault(cat, 0.0)
        out[r['loop']][cat] += float(r['W_mean'])
    return out


def loop_mcp(L):
    """Loop heat-capacity rate mdot*cp (W/K) from the model parameters (lb/h and kJ/(kg K))."""
    import iss_spec as S
    lbh = float(S.PARAMS[f'mdot_{L}'][0].split('[')[0]); cp = float(S.PARAMS['cp_nh3'][0].split('[')[0]) * 1e3
    return lbh * 0.45359237 / 3600.0 * cp


T_SET_C = (37 - 32) / 1.8


def _crossing(qs, ys, target):
    """Loop heat at which the (monotone increasing) outlet temperature reaches `target`: quadratic through the
    bracketing pair and its nearest neighbour (the curve is concave; linear interpolation over 50 kW steps would
    overstate the crossing by about 2 kW), linear when only two points exist."""
    for k in range(len(qs) - 1):
        if (ys[k] - target) * (ys[k + 1] - target) <= 0 and ys[k + 1] != ys[k]:
            lin = qs[k] + (target - ys[k]) * (qs[k + 1] - qs[k]) / (ys[k + 1] - ys[k])
            idx = [k - 1, k, k + 1] if k >= 1 else ([k, k + 1, k + 2] if k + 2 < len(qs) else None)
            if idx is None:
                return lin
            c = np.polyfit([qs[i] for i in idx], [ys[i] for i in idx], 2)
            roots = [r.real for r in np.roots([c[0], c[1], c[2] - target]) if abs(r.imag) < 1e-9 and qs[k] - 1e-9 <= r.real <= qs[k + 1] + 1e-9]
            return float(roots[0]) if roots else lin
    return None


T_IN_MAX_C = 45.0   # liquid NH3 properties at 300 psia are used; points with a hotter radiator inlet are dropped


def capacity():
    """Radiator-only capacity runs (model/iss_capacity.py, out/capacity/capacity_<key>.csv): rows per key
    (case plus optional sensitivity suffix), loop and loop heat, and the interpolated loop heat at which
    the last-orbit mean / maximum outlet temperature reaches 2.8 C."""
    import csv, glob, os
    files = sorted(glob.glob(os.path.join(R.OUT, 'capacity', 'capacity_*.csv')))
    if not files:
        return None
    rows, summ = {}, {}
    for p in files:
        key = os.path.basename(p)[len('capacity_'):-len('.csv')]
        rr = [dict(r, **{k: float(r[k]) for k in r if k not in ('case', 'loop')}) for r in csv.DictReader(open(p, encoding='utf-8'))]
        rr = [r for r in rr if r['Tin_mean_C'] <= T_IN_MAX_C]
        rows[key] = rr
        res = {}
        for L in ('A', 'B'):
            s = sorted([r for r in rr if r['loop'] == L], key=lambda r: r['Qd_kW'])
            q = [r['Qd_kW'] for r in s]
            res[L] = dict(Q_at_mean_setpoint_kW=_crossing(q, [r['Tout_mean_C'] for r in s], T_SET_C),
                          Q_at_max_setpoint_kW=_crossing(q, [r['Tout_max_C'] for r in s], T_SET_C))
        summ[key] = dict(capacity=res)
    return dict(summary=summ, rows=rows)


def capacity_history(case, q):
    """End time of a capacity run and the outlet change over its last orbit at the same orbit position (K)."""
    import os
    p = os.path.join(R.OUT, 'capacity', f'history_{case}_{int(q)}kW.csv')
    if not os.path.exists(p):
        return None
    d = np.genfromtxt(p, delimiter=',', names=True)
    t = d['t_s']; per = 2 * np.pi * np.sqrt((6378.137e3 + 400e3) ** 3 / 3.986004418e14)
    drift = max(abs(d[k][-1] - np.interp(t[-1] - per, t, d[k])) for k in d.dtype.names if k.startswith('Tout_'))
    return dict(t_end=float(t[-1]), drift=float(drift))


def capacity_drifts():
    """End-of-run outlet drift of every capacity run: {(key, q_kW): drift_K}."""
    import glob, os
    out = {}
    for p in sorted(glob.glob(os.path.join(R.OUT, 'capacity', 'history_*.csv'))):
        b = os.path.basename(p)[len('history_'):-len('kW.csv')]
        key, q = b.rsplit('_', 1)
        h = capacity_history(key, q)
        if h: out[(key, float(q))] = h['drift']
    return out
