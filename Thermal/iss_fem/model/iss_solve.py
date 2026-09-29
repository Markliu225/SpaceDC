# -*- coding: utf-8 -*-
"""Solve the ISS model and write probes.

Called from iss_build.main() after the build, or standalone on a saved model:
    backend/.venv/Scripts/python iss_solve.py out/comsol/iss_beta0.mph --case beta0

Outputs (out/<tag>/):
  series.csv     one row per output time: loop globals, class statistics
  items.csv      per item (module skin, truss segment, box, rack, panel group)
                 min / mean / max over the LAST orbit
  summary.json   wall times, mesh, energy closure of the loops, periodicity
"""
import csv, json, math, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import iss_spec as S
import iss_layout as LAY

OUT = os.path.join(os.path.dirname(HERE), 'out')


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def ev(j, typ, expr, named=None, data=None, unit=None):
    """Evaluate a numerical feature over all time steps of `data`; returns a list."""
    tag = 'ev_tmp'
    try: j.result().numerical().remove(tag)
    except Exception: pass
    n = j.result().numerical().create(tag, typ)
    try:
        if named is not None: n.selection().named(named)
        if data is not None: n.set('data', data)
        n.set('expr', [expr] if isinstance(expr, str) else list(expr))
        if unit: n.set('unit', unit)
        try: n.set('innerinput', 'all')
        except Exception: pass
        vals = n.getReal()
        if isinstance(expr, str):
            return [float(v) for v in vals[0]]
        return [[float(v) for v in row] for row in vals]
    finally:
        try: j.result().numerical().remove(tag)
        except Exception: pass


def ev_global(model, exprs, dataset):
    out = {}
    for e in exprs:
        try: out[e] = np.atleast_1d(np.asarray(model.evaluate(e, dataset=dataset), dtype=float)).tolist()
        except Exception as ex: log('global eval failed', e, str(ex).replace(chr(10), ' ')[:160]); out[e] = None
    return out


def temperature_dataset(j, study_tag):
    """The OrbitalTemperature step's dataset (two-step OTL studies make two solutions:
    the loads step keeps T at its initial value)."""
    cands = []
    for ds in j.result().dataset():
        try:
            sol = str(ds.getString('solution'))
            st = str(j.sol(sol).study())
        except Exception:
            continue
        if st == study_tag:
            cands.append((str(ds.tag()), sol))
    return cands


def pick_temperature_dataset(j, study_tag, probe_sel, var):
    cands = temperature_dataset(j, study_tag)
    best, span = None, -1.0
    for dtag, sol in cands:
        try:
            v = ev(j, 'AvSurface', var, named=probe_sel, data=dtag)
            s = max(v) - min(v)
            if s > span: best, span = dtag, s
        except Exception:
            pass
    return best, cands


def run(b, a, tag, which=('stdO',)):
    j, model = b.j, b.model
    outdir = os.path.join(OUT, tag); os.makedirs(outdir, exist_ok=True)
    summ = dict(tag=tag, case=a.case, mesh=getattr(b, 'mesh_stats', {}), orbit=b.lay['orbit_info'])
    for st in which:
        t0 = time.time(); log('solving', st)
        try:
            j.study(st).run(); summ[f'{st}_wall_s'] = round(time.time() - t0, 1); log(st, 'done %.0f s' % (time.time() - t0))
        except Exception as e:
            summ[f'{st}_error'] = str(e).replace(chr(10), ' ')[:3000]; log(st, 'FAILED', summ[f'{st}_error'][:1500])
            json.dump(summ, open(os.path.join(outdir, 'summary.json'), 'w'), indent=1)
            b.save(os.path.join(os.path.dirname(HERE), 'out', 'comsol', f'iss_{tag}_failed.mph'))
            raise
        b.save(os.path.join(os.path.dirname(HERE), 'out', 'comsol', f'iss_{tag}.mph'))
    probe(b, a, tag, outdir, summ)


def probe(b, a, tag, outdir, summ, study='stdO'):
    j, model, lay = b.j, b.model, b.lay
    ds, cands = pick_temperature_dataset(j, study, b.grp.get('hrs', b.grp['body']), 'T2')
    summ['datasets'] = cands; summ['temperature_dataset'] = ds
    log('temperature dataset', ds, 'of', cands)
    t = ev(j, 'AvSurface', 't', named=b.grp['body'], data=ds)
    per = lay['period']
    cols = {'t_s': t, 'orbit': [x / per for x in t]}
    # loop globals
    gnames = []
    for L in S.LOOPS['loops']:
        gnames += [f'f_{L}', f'Q_{L}', f'Qrad_{L}', f'Tret_{L}-273.15', f'Tout_{L}-273.15']
    g = ev_global(model, gnames, None)
    # MPh evaluate with dataset=None uses the default (latest) dataset; redo on the temperature dataset label
    try:
        label = str(j.result().dataset(ds).label())
        g = ev_global(model, gnames, label)
    except Exception as e:
        log('global on labelled dataset failed', str(e)[:120])
    for k, v in g.items():
        if v is not None and len(v) == len(t): cols[k.replace('-273.15', '_C')] = v
    # class statistics
    for cls in b.cs:
        var = 'T2' if cls in LAY.SHELL_CLASSES else 'T'
        sel = b.cs[cls]['bnd']
        if cls in LAY.SOLID_CLASSES:
            sel_dom = b.cs[cls]['dom']
            cols[f'{cls}_Tmean_C'] = [x - 273.15 for x in ev(j, 'AvVolume', 'T', named=sel_dom, data=ds)]
            cols[f'{cls}_Tmax_C'] = [x - 273.15 for x in ev(j, 'MaxVolume', 'T', named=sel_dom, data=ds)]
            cols[f'{cls}_Tmin_C'] = [x - 273.15 for x in ev(j, 'MinVolume', 'T', named=sel_dom, data=ds)]
        else:
            cols[f'{cls}_Tmean_C'] = [x - 273.15 for x in ev(j, 'AvSurface', var, named=sel, data=ds)]
            cols[f'{cls}_Tmax_C'] = [x - 273.15 for x in ev(j, 'MaxSurface', var, named=sel, data=ds)]
            cols[f'{cls}_Tmin_C'] = [x - 273.15 for x in ev(j, 'MinSurface', var, named=sel, data=ds)]
    # per-ORU radiator means and fluid chain
    for L, d in S.LOOPS['loops'].items():
        for k, oru in enumerate(d['orus']):
            ps = [p for p in lay['panels'] if p.get('fluid') and p['fluid']['loop'] == L and p['fluid']['oru'] == oru]
            if not ps: continue
            u = f'su_{L}_{k}'
            try: b.union(u, 2, [b.panel_sel[p['name']] for p in ps])
            except Exception: pass
            cols[f'{L}_{oru}_Tmean_C'] = [x - 273.15 for x in ev(j, 'AvSurface', 'T2', named=u, data=ds)]
    n = len(t)
    keys = [k for k, v in cols.items() if isinstance(v, list) and len(v) == n]
    with open(os.path.join(outdir, 'series.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(keys)
        for i in range(n): w.writerow([f'{cols[k][i]:.6g}' for k in keys])
    log('series.csv', n, 'rows', len(keys), 'columns')
    # last-orbit item statistics
    t_arr = np.array(t); last = t_arr >= (t_arr[-1] - per + 1e-6)
    rows = []
    def add(kind, name, typ_mean, typ_min, typ_max, expr, sel):
        try:
            vm = np.array(ev(j, typ_mean, expr, named=sel, data=ds)) - 273.15
            vn = np.array(ev(j, typ_min, expr, named=sel, data=ds)) - 273.15
            vx = np.array(ev(j, typ_max, expr, named=sel, data=ds)) - 273.15
            rows.append(dict(kind=kind, name=name, Tmin_C=float(vn[last].min()), Tmean_C=float(vm[last].mean()), Tmax_C=float(vx[last].max())))
        except Exception as e:
            log('item probe failed', kind, name, str(e)[:120])
    for c in lay['cylinders']:
        add('skin', c['name'], 'AvSurface', 'MinSurface', 'MaxSurface', 'T2', b.skin_sel[c['name']])
    for bl in lay['blocks']:
        add(bl['cls'], bl['name'], 'AvVolume', 'MinVolume', 'MaxVolume', 'T', b.block_dom[bl['name']])
    for grp_name, members in lay.get('panel_groups', {}).items():
        u = 'spg_' + grp_name
        try: b.union(u, 2, [b.panel_sel[m] for m in members])
        except Exception: pass
        cls = lay['panel_by_name'][members[0]]['cls']
        add(cls, grp_name, 'AvSurface', 'MinSurface', 'MaxSurface', 'T2', u)
    with open(os.path.join(outdir, 'items.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=['kind', 'name', 'Tmin_C', 'Tmean_C', 'Tmax_C']); w.writeheader(); w.writerows(rows)
    # loop energy closure and periodicity
    closure = {}
    for L in S.LOOPS['loops']:
        q, qr = cols.get(f'Q_{L}'), cols.get(f'Qrad_{L}')
        if q and qr:
            q, qr = np.array(q), np.array(qr)
            closure[L] = dict(Q_pickup_lastorbit_mean_W=float(q[last].mean()), Q_rad_lastorbit_mean_W=float(qr[last].mean()),
                              f_min=float(np.array(cols[f'f_{L}'])[last].min()), f_max=float(np.array(cols[f'f_{L}'])[last].max()))
    summ['loops'] = closure
    per_chk = {}
    if t_arr[-1] >= 2 * per - 1:
        prev = (t_arr >= t_arr[-1] - 2 * per + 1e-6) & ~last
        for k in keys:
            if k.endswith('_Tmean_C'):
                v = np.array(cols[k]); per_chk[k] = float(v[last].mean() - v[prev].mean())
    summ['periodicity_lastorbit_minus_previous_C'] = per_chk
    json.dump(summ, open(os.path.join(outdir, 'summary.json'), 'w'), indent=1)
    log('probes written to', outdir)


if __name__ == '__main__':
    import argparse, mph
    ap = argparse.ArgumentParser(); ap.add_argument('mph'); ap.add_argument('--case', default='beta0'); ap.add_argument('--cores', type=int, default=4)
    ap.add_argument('--lite', action='store_true'); ap.add_argument('--tag', default='')
    a = ap.parse_args()
    raise SystemExit('standalone probing of a saved model: use iss_post.py (rebuilds selections from the layout)')
