# -*- coding: utf-8 -*-
"""Derived result quantities for the report (all from out/<tag>/ probe files)."""
import numpy as np
import iss_results as R

MODS = ('destiny', 'harmony', 'tranquility', 'columbus', 'kibo')
MOD_CN = {'destiny': 'Destiny', 'harmony': 'Harmony', 'tranquility': 'Tranquility', 'columbus': 'Columbus', 'kibo': 'Kibo'}


def num(x, nd=1):
    """Number with a true minus sign (U+2212)."""
    s = f'{x:.{nd}f}'
    return s.replace('-', '−')


def rng(a, b, nd=1):
    return num(a, nd) if num(a, nd) == num(b, nd) else f'{num(a, nd)} 至 {num(b, nd)}'


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
            out[u] = dict(f=R.stat(c, f'f_{L}'), Q=R.stat(c, f'Q_{L}'), Tout=R.stat(c, f'Tout_{L}_C'), Tmix=R.stat(c, f'Tmix_{L}_C'))
    return out


def saw_eclipse(c):
    """Array temperature at eclipse exit (last orbit) and minutes from eclipse exit until the mean passes 0 C."""
    ecl = c['summ']['orbit'].get('eclipse_deg', 0.0)
    if not ecl or 'saw_Tmean_C' not in c['s']:
        return None
    per = c['per']; t = c['t']
    t_exit = (np.floor(t[-1] / per) - 1 + 0.5) * per + ecl / 360 * per / 2      # eclipse exit in the last full orbit
    if t_exit < t[0]:
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


BREAKDOWN_CN = [('rack_MT', '舱内机柜冷板，中温回路'), ('rack_LT', '舱内机柜冷板，低温回路'), ('air', '舱内空气'), ('mli', '舱体多层隔热漏热'),
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
    """Loop heat at which the (monotone increasing) outlet temperature reaches `target`, linear interpolation."""
    for k in range(len(qs) - 1):
        if (ys[k] - target) * (ys[k + 1] - target) <= 0 and ys[k + 1] != ys[k]:
            return qs[k] + (target - ys[k]) * (qs[k + 1] - qs[k]) / (ys[k + 1] - ys[k])
    return None


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
        rows[key] = rr
        res = {}
        for L in ('A', 'B'):
            s = sorted([r for r in rr if r['loop'] == L], key=lambda r: r['Qd_kW'])
            q = [r['Qd_kW'] for r in s]
            res[L] = dict(Q_at_mean_setpoint_kW=_crossing(q, [r['Tout_mean_C'] for r in s], T_SET_C),
                          Q_at_max_setpoint_kW=_crossing(q, [r['Tout_max_C'] for r in s], T_SET_C))
        summ[key] = dict(capacity=res)
    return dict(summary=summ, rows=rows)
