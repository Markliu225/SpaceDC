# -*- coding: utf-8 -*-
"""EATCS radiator heat-rejection capacity.

The radiator-only model (iss_layout.build(case, capacity=True)) keeps the 48 HRS panels with the same
geometry, panel material, coating, TRRJ pointing law and orbital environment as the full model; the
radiator OTL group radiates only with itself, so the panels see the same environment in both models.
Capacity form of the loops: all flow through the radiators (no bypass), prescribed loop heat Qd per
loop; the radiator outlet is the supply temperature and the capacity at the design supply temperature
is the Qd at which the outlet reaches 2.8 C.

    backend/.venv/Scripts/python iss_capacity.py hot75 cold0 nom0 --q 20,35,50,70,90 [--orbits 2] [--dt 120] [--cores 2]

Writes out/capacity/capacity_<case>.csv: per Qd and loop the last-orbit mean / min / max outlet
temperature, and out/capacity/capacity_summary.json with the interpolated capacities.
"""
import argparse, csv, json, os, sys, time
import numpy as np
import mph

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import iss_layout as LAY
import iss_build as B

OUT = os.path.join(os.path.dirname(HERE), 'out', 'capacity')
T_SET_C = (37 - 32) / 1.8


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def builder_args(case, a):
    return argparse.Namespace(case='cap_' + case, cores=a.cores, lite=False, hemicube=128, vf_tol=0.02, planet_rings=2, planet_points=6,
                              h_default=2.0, dt_loads=60.0, dt_frozen=2000.0, t_frozen=40000.0, dt_out=a.dt, orbits=a.orbits, tag='cap_' + case)


def crossing(qs, ys, target):
    """Q at which the (monotone increasing) outlet temperature reaches `target`, by linear interpolation."""
    for k in range(len(qs) - 1):
        if (ys[k] - target) * (ys[k + 1] - target) <= 0 and ys[k + 1] != ys[k]:
            return qs[k] + (target - ys[k]) * (qs[k + 1] - qs[k]) / (ys[k + 1] - ys[k])
    return None


def global_dataset(j, model, study='stdO'):
    """MPh dataset name of the temperature step of `study` (the step whose Tout_A varies in time)."""
    best, span = None, -1.0
    for ds in j.result().dataset():
        try:
            sol = str(ds.getString('solution'))
            if str(j.sol(sol).study()) != study: continue
            lab = str(j.sol(sol).label())
        except Exception:
            continue
        mname = next((n for n in model.datasets() if n.endswith('//' + lab)), None)
        if not mname: continue
        try:
            y = np.atleast_1d(np.asarray(model.evaluate('Tout_A', dataset=mname), dtype=float))
            if y.size > 1 and np.ptp(y) > span: best, span = mname, float(np.ptp(y))
        except Exception:
            pass
    return best


def run_case(client, case, a, qs):
    key = case + a.suffix
    if a.hmax:
        LAY.S.MESH_H['hrs'] = a.hmax
    lay = LAY.build(case, capacity=True)
    b = B.Builder(builder_args(case, a), lay, client=client)
    b.geometry(); b.selections(); b.materials(); b.physics(); b.mesh(); b.studies(); b.solver_scaling()
    j, model, per = b.j, b.model, lay['period']
    rows = []
    loads_done = False
    for q in qs:
        for L in ('A', 'B'):
            j.param().set(f'Qd_{L}', f'{q}[kW]')
        t0 = time.time()
        try:
            if loads_done and a.reuse_loads:
                # the orbital loads do not depend on the loop heat: re-solve only the temperature step,
                # which reads the loads stored by the first run
                sol = next(s for s in j.sol() if str(s.study()) == 'stdO' and 'st2' in [str(f.tag()) for f in s.feature()])
                sol.runFromTo('st2', 't2')
            else:
                j.study('stdO').run(); loads_done = True
        except Exception as e:
            log(case, 'Qd', q, 'FAILED', str(e).replace(chr(10), ' ')[:400]); continue
        wall = time.time() - t0
        ds = global_dataset(j, model)
        t = np.atleast_1d(np.asarray(model.evaluate('t', dataset=ds), dtype=float))
        last = t >= t[-1] - per + 1e-6; prev = (t >= t[-1] - 2 * per + 1e-6) & ~last
        for L in ('A', 'B'):
            To = np.atleast_1d(np.asarray(model.evaluate(f'Tout_{L}-273.15', dataset=ds), dtype=float))
            Ti = np.atleast_1d(np.asarray(model.evaluate(f'Tret_{L}-273.15', dataset=ds), dtype=float))
            r = dict(case=case, Qd_kW=q, loop=L, Tout_mean_C=float(To[last].mean()), Tout_min_C=float(To[last].min()), Tout_max_C=float(To[last].max()),
                     Tin_mean_C=float(Ti[last].mean()), drift_C=float(To[last].mean() - To[prev].mean()) if prev.any() else float('nan'),
                     wall_s=round(wall, 1))
            rows.append(r)
            log(case, 'Qd %.0f kW loop %s: outlet mean %.2f C, min %.2f, max %.2f, orbit-to-orbit drift %.3f K (%.0f s)'
                % (q, L, r['Tout_mean_C'], r['Tout_min_C'], r['Tout_max_C'], r['drift_C'], wall))
        with open(os.path.join(OUT, f'capacity_{key}.csv'), 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        if q == qs[0]:
            # time history of the first load for the report figure
            hist = {'t_s': t}
            for L in ('A', 'B'):
                hist[f'Tout_{L}_C'] = np.atleast_1d(np.asarray(model.evaluate(f'Tout_{L}-273.15', dataset=ds), dtype=float))
            np.savetxt(os.path.join(OUT, f'history_{key}_{int(q)}kW.csv'), np.column_stack(list(hist.values())), delimiter=',',
                       header=','.join(hist.keys()), comments='')
    try:
        b.save(os.path.join(B.CM, f'cap_{key}.mph'))
    except Exception as e:
        log('save failed', str(e)[:200])
    res = {}
    for L in ('A', 'B'):
        rr = sorted([r for r in rows if r['loop'] == L], key=lambda r: r['Qd_kW'])
        qv = [r['Qd_kW'] for r in rr]
        res[L] = dict(Q_at_mean_setpoint_kW=crossing(qv, [r['Tout_mean_C'] for r in rr], T_SET_C),
                      Q_at_max_setpoint_kW=crossing(qv, [r['Tout_max_C'] for r in rr], T_SET_C))
    try:
        client.remove(model)
    except Exception:
        pass
    return rows, res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('cases', nargs='+'); ap.add_argument('--q', default='20,35,50,70,90')
    ap.add_argument('--orbits', type=float, default=2.0); ap.add_argument('--dt', type=float, default=120.0); ap.add_argument('--cores', type=int, default=2)
    ap.add_argument('--no-reuse-loads', dest='reuse_loads', action='store_false')
    ap.add_argument('--hmax', type=float, default=None, help='radiator mesh size (m), default iss_spec.MESH_H')
    ap.add_argument('--suffix', default='', help='appended to the case name in the output files (sensitivity runs)')
    a = ap.parse_args()
    qs = [float(x) for x in a.q.split(',')]
    os.makedirs(OUT, exist_ok=True)
    client = mph.start(cores=a.cores)
    import jpype
    jpype.JClass('com.comsol.model.util.ModelUtil').showProgress(os.path.join(OUT, f"progress_{'_'.join(a.cases)}{a.suffix}.log"))
    sp = os.path.join(OUT, 'capacity_summary.json')
    summ = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
    for case in a.cases:
        log('capacity case', case, 'Qd', qs)
        rows, res = run_case(client, case, a, qs)
        summ = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
        summ[case + a.suffix] = dict(capacity=res, T_set_C=T_SET_C, q_kW=qs, orbits=a.orbits, dt_s=a.dt, hmax_m=a.hmax or LAY.S.MESH_H['hrs'],
                                     rows=rows)
        json.dump(summ, open(sp, 'w', encoding='utf-8'), indent=1)
        log(case, 'capacity', res)


if __name__ == '__main__':
    main()
