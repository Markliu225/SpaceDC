# -*- coding: utf-8 -*-
"""Result extraction for the report: last-orbit statistics of every case from out/<tag>/series.csv,
items.csv and summary.json. All numbers quoted in the report come from here."""
import csv, json, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'out')


def load_case(tag):
    d = os.path.join(OUT, tag)
    rows = list(csv.DictReader(open(os.path.join(d, 'series.csv'), encoding='utf-8')))
    s = {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
    items = list(csv.DictReader(open(os.path.join(d, 'items.csv'), encoding='utf-8')))
    summ = json.load(open(os.path.join(d, 'summary.json'), encoding='utf-8'))
    per = summ['orbit']['period']
    t = s['t_s']
    last = t >= t[-1] - per + 1e-6
    prev = (t >= t[-1] - 2 * per + 1e-6) & ~last
    # exact one-period windows for time-weighted means (sample-count differences between windows otherwise
    # bias the orbit mean of fast components such as the solar arrays by about 1 K)
    win = (t[-1] - per, t[-1]); win_prev = (t[-1] - 2 * per, t[-1] - per)
    return dict(tag=tag, s=s, items=items, summ=summ, per=per, last=last, prev=prev, t=t, win=win, win_prev=win_prev)


def twmean(t, y, a, b):
    """Time-weighted mean of y over [a, b], linear interpolation between samples."""
    tt = np.concatenate(([a], t[(t > a) & (t < b)], [b]))
    yy = np.interp(tt, t, y)
    return float(np.sum((yy[1:] + yy[:-1]) * np.diff(tt)) / 2.0 / (b - a))


def stat(c, key, where='last'):
    v = c['s'][key][c[where]]
    a, b = c['win'] if where == 'last' else c['win_prev']
    return dict(mean=twmean(c['t'], c['s'][key], a, b), min=float(v.min()), max=float(v.max()))


def loop_table(c, loops=('A', 'B')):
    out = {}
    for L in loops:
        if f'Q_{L}' not in c['s']:
            continue
        q, qr = stat(c, f'Q_{L}'), stat(c, f'Qrad_{L}')
        # reported flow fraction = smoothly bounded share actually sent through the radiators (feff); f is the valve integrator state
        fkey = f'feff_{L}' if f'feff_{L}' in c['s'] else f'f_{L}'
        out[L] = dict(Q=q, Qrad=qr, f=stat(c, fkey), f_int=stat(c, f'f_{L}'), Tout=stat(c, f'Tout_{L}_C'), Tret=stat(c, f'Tret_{L}_C'),
                      Tmix=stat(c, f'Tmix_{L}_C'), closure_pct=100.0 * (qr['mean'] - q['mean']) / q['mean'])
    return out


def class_table(c, classes=('hrs', 'pvr', 'saw', 'rsa', 'skin_usos', 'skin_rus', 'truss', 'box', 'payload', 'rack')):
    out = {}
    for k in classes:
        if f'{k}_Tmean_C' in c['s']:
            out[k] = dict(mean=twmean(c['t'], c['s'][f'{k}_Tmean_C'], *c['win']),
                          min=float(c['s'][f'{k}_Tmin_C'][c['last']].min()),
                          max=float(c['s'][f'{k}_Tmax_C'][c['last']].max()))
    return out


def periodicity(c):
    """Difference of last-orbit and previous-orbit means per class (K)."""
    out = {}
    if not c['prev'].any():
        return out
    t = c['t']
    for k, v in c['s'].items():
        if k.endswith('_Tmean_C'):
            out[k[:-len('_Tmean_C')]] = twmean(t, v, *c['win']) - twmean(t, v, *c['win_prev'])
    for L in ('A', 'B'):
        if f'Q_{L}' in c['s']:
            q = c['s'][f'Q_{L}']
            out['Q_' + L + '_kW'] = (twmean(t, q, *c['win']) - twmean(t, q, *c['win_prev'])) / 1e3
    return out


def items_by_kind(c):
    out = {}
    for r in c['items']:
        out.setdefault(r['kind'], []).append(dict(name=r['name'], Tmin=float(r['Tmin_C']), Tmean=float(r['Tmean_C']), Tmax=float(r['Tmax_C'])))
    return out


def eclipse_split(c, key):
    """Mean of a series over the sunlit and eclipse parts of the last orbit (beta 0 cases)."""
    ecl = c['summ']['orbit'].get('eclipse_deg', 0.0)
    if not ecl:
        return None
    per = c['per']; t = c['t']
    u = 360.0 * ((t % per) / per)
    in_ecl = (u > 180 - ecl / 2) & (u < 180 + ecl / 2)
    v = c['s'][key]
    return dict(sun=float(v[c['last'] & ~in_ecl].mean()), ecl=float(v[c['last'] & in_ecl].mean()))


if __name__ == '__main__':
    import sys
    for tag in sys.argv[1:]:
        c = load_case(tag)
        print('==', tag, 'period', c['per'], 'n', len(c['t']), 'last-orbit points', int(c['last'].sum()))
        for L, v in loop_table(c).items():
            print(' loop', L, {k: (round(x['mean'], 2) if isinstance(x, dict) else round(x, 2)) for k, x in v.items()})
        for k, v in class_table(c).items():
            print(' class %-10s mean %7.1f min %7.1f max %7.1f' % (k, v['mean'], v['min'], v['max']))
        print(' periodicity', {k: round(v, 2) for k, v in periodicity(c).items()})
