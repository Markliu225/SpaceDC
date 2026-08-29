# -*- coding: utf-8 -*-
"""Offline probing of a solved COMSOL twin (.mph saved by build_comsol.py after
studies A and B). Maps datasets to studies explicitly (the in-run prober used
"newest dataset", which is wrong after the planet-check re-runs of study LA).

    backend/.venv/Scripts/python probe_offline.py caseA [--mph out/comsol/caseA.mph]

Writes out/comsol/<tag>_probes.csv and <tag>_solve_log.json (same format as
solve_and_probe.run), so compare_report.py works unchanged.
"""
import argparse, csv, json, os, sys, time
import mph
import geometry_spec as G
import build_comsol as BC
import solve_and_probe as SP

HERE = os.path.dirname(os.path.abspath(__file__))
CM_DIR = os.path.join(HERE, "out", "comsol")
SIGMA = SP.SIGMA


def dataset_map(j):
    """study tag -> dataset tag. A two-step study (Orbit Thermal Loads + Orbital
    Temperature) owns TWO solution datasets: the loads-step one (T frozen at the
    initial value) and the temperature one. Pick, per study, the dataset whose
    temperature actually varies in time (largest range of the bus mean T)."""
    cands = {}
    for d in j.result().dataset():
        try:
            if str(d.getType()) != 'Solution':
                continue
            sol = str(d.getString('solution'))
            st = str(j.sol(sol).study())
            cands.setdefault(st, []).append(str(d.tag()))
        except Exception:
            continue
    m = {}
    for st, tags in cands.items():
        if len(tags) == 1:
            m[st] = tags[0]; continue
        best, best_range = None, -1.0
        for tg in tags:
            try:
                T = SP._ev(j, 'AvVolume', 'T', named='geom1_csel_bus_dom', data=tg)
                rng = max(T) - min(T)
            except Exception:
                rng = -1.0
            print(f"  {st}: {tg} T-range {rng:.3f} K over {len(T) if rng >= 0 else 0} times", flush=True)
            if rng > best_range:
                best, best_range = tg, rng
        m[st] = best
    return m


def ensure_selections(comp, meta):
    def has(tag):
        try:
            comp.selection(tag); return True
        except Exception:
            return False
    if not has('sel_rad_faces'):
        s = comp.selection().create('sel_rad_faces', 'Union'); s.set('entitydim', '2'); s.set('input', meta['rad_faces'])
    if not has('sel_alldom'):
        a = comp.selection().create('sel_alldom', 'Box'); a.set('entitydim', '3'); a.set('condition', 'inside')
        for k, v in (('xmin', -50.0), ('xmax', 50.0), ('ymin', -50.0), ('ymax', 50.0), ('zmin', -50.0), ('zmax', 50.0)): a.set(k, v)
    if not has('sel_ext'):
        e = comp.selection().create('sel_ext', 'Adjacent'); e.set('entitydim', '3'); e.set('outputdim', '2'); e.set('input', ['sel_alldom']); e.set('exterior', True); e.set('interior', False)
    # exterior-only surface classes with KNOWN optics (the COMSOL variable epsilon_amb is the AMBIENT emissivity, not the surface's)
    if not has('sel_rad_ext'):
        x = comp.selection().create('sel_rad_ext', 'Intersection'); x.set('entitydim', '2'); x.set('input', ['sel_rad_paint', 'sel_ext'])
    if not has('sel_wings_ext'):
        w = comp.selection().create('sel_wings_ext', 'Union'); w.set('entitydim', '2'); w.set('input', ['sel_wing_front', 'sel_wing_back'])
    if not has('sel_rest_ext'):
        r = comp.selection().create('sel_rest_ext', 'Difference'); r.set('entitydim', '2'); r.set('add', ['sel_ext']); r.set('subtract', ['sel_rad_ext', 'sel_wings_ext'])


def probe(model, case, tag, info, meta, orbits):
    j = model.java; comp = j.component('comp1')
    ensure_selections(comp, meta)
    dm = dataset_map(j)
    print("dataset map:", dm, flush=True)
    dsLA, dsA, dsLB, dsB = dm.get('stdLA'), dm.get('stdA'), dm.get('stdLB'), dm.get('stdB')
    dsLB2, dsB2 = dm.get('stdLB2'), dm.get('stdB2')
    ev = SP._ev
    log = dict(case=case, tag=tag, datasets=dm)
    aF, aB, aR = G.OPT_CELL_FRONT['alpha'], G.OPT_CELL_BACK['alpha'], G.OPT_WHITEPAINT['alpha']

    EPS = {'sel_rad_ext': G.OPT_WHITEPAINT['eps'], 'sel_wing_front': G.OPT_CELL_FRONT['eps'], 'sel_wing_back': G.OPT_CELL_BACK['eps'], 'sel_rest_ext': G.OPT_BARE_AL['eps']}
    ALP = {'sel_rad_ext': G.OPT_WHITEPAINT['alpha'], 'sel_wing_front': G.OPT_CELL_FRONT['alpha'], 'sel_wing_back': G.OPT_CELL_BACK['alpha'], 'sel_rest_ext': G.OPT_BARE_AL['alpha']}

    def by_class(expr, coef, ds):
        tot = None
        for sel, c in coef.items():
            v = ev(j, 'IntSurface', expr, named=sel, data=ds)
            tot = [c * x for x in v] if tot is None else [t + c * x for t, x in zip(tot, v)]
        return tot

    def absorbed_solar(ds):      # solar band: direct sun + albedo (otl.Gext1), loads dataset
        return by_class('otl.Gext1', ALP, ds)

    def absorbed_ir(ds):         # ambient band: planet IR (otl.Gext2), absorptivity = emissivity
        return by_class('otl.Gext2', EPS, ds)

    def emitted(ds):             # gross thermal emission eps*sigma*T^4 over all exterior surfaces
        return [SIGMA * v for v in by_class('T^4', EPS, ds)]

    def mutual_solar(ds):        # solar-band mutual irradiation absorbed (otl.Gm1)
        return by_class('otl.Gm1', ALP, ds)

    # ---------------- study A: steady state + energy balance
    if dsA:
        tA = ev(j, 'AvSurface', 't', named='sel_rad_faces', data=dsA)
        TA = ev(j, 'AvSurface', 'T', named='sel_rad_faces', data=dsA)
        log['A_times_s'] = tA; log['A_rad_mean_K_series'] = TA
        log['A_rad_mean_K'] = TA[-1]; log['A_rad_drift_last_interval_K'] = TA[-1] - TA[-2] if len(TA) > 1 else None
        log['A_rad_max_K'] = ev(j, 'MaxSurface', 'T', named='sel_rad_faces', data=dsA)[-1]
        log['A_rad_min_K'] = ev(j, 'MinSurface', 'T', named='sel_rad_faces', data=dsA)[-1]
        log['A_baseplate_mean_K'] = ev(j, 'AvSurface', 'T', named='sel_tim', data=dsA)[-1]
        log['A_pkg_max_K'] = ev(j, 'MaxVolume', 'T', named='geom1_csel_pkgs_dom', data=dsA)[-1]
        log['A_bus_mean_K'] = ev(j, 'AvVolume', 'T', named='geom1_csel_bus_dom', data=dsA)[-1]
        log['A_blades_mean_K'] = ev(j, 'AvVolume', 'T', named='geom1_csel_blades_dom', data=dsA)[-1]
        log['A_wing_mean_K'] = ev(j, 'AvVolume', 'T', named='geom1_csel_wings_dom', data=dsA)[-1]
        P_src = info['heat_per_gpu_at_t0'] * 12 + info['heat_platform_w']
        eb = dict(P_sources_W=P_src)
        eb['absorbed_solar_albedo_ext_W'] = absorbed_solar(dsLA)[-1]
        eb['absorbed_planet_IR_ext_W'] = absorbed_ir(dsLA)[-1]
        eb['absorbed_mutual_solar_band_W'] = mutual_solar(dsA)[-1]
        em = emitted(dsA); eb['emitted_gross_W'] = em[-1]; eb['emitted_gross_series_W'] = em
        eb['absorbed_total_W'] = P_src + eb['absorbed_solar_albedo_ext_W'] + eb['absorbed_planet_IR_ext_W'] + eb['absorbed_mutual_solar_band_W']
        eb['residual_W_(mutual_IR_absorbed+error)'] = eb['emitted_gross_W'] - eb['absorbed_total_W']
        eb['closure_pct_gross'] = 100.0 * (eb['emitted_gross_W'] - eb['absorbed_total_W']) / eb['absorbed_total_W']
        eb['emitted_rad_faces_W'] = G.OPT_WHITEPAINT['eps'] * SIGMA * ev(j, 'IntSurface', 'T^4', named='sel_rad_faces', data=dsA)[-1]
        eb['emitted_wings_W'] = SIGMA * G.OPT_CELL_FRONT['eps'] * (ev(j, 'IntSurface', 'T^4', named='sel_wing_front', data=dsA)[-1] + ev(j, 'IntSurface', 'T^4', named='sel_wing_back', data=dsA)[-1])
        eb['absorbed_solar_wings_W'] = aF * ev(j, 'IntSurface', 'otl.Gext1', named='sel_wing_front', data=dsLA)[-1] + aB * ev(j, 'IntSurface', 'otl.Gext1', named='sel_wing_back', data=dsLA)[-1]
        eb['absorbed_IR_wings_W'] = G.OPT_CELL_FRONT['eps'] * (ev(j, 'IntSurface', 'otl.Gext2', named='sel_wing_front', data=dsLA)[-1] + ev(j, 'IntSurface', 'otl.Gext2', named='sel_wing_back', data=dsLA)[-1])
        eb['absorbed_solar_rad_faces_W'] = aR * ev(j, 'IntSurface', 'otl.Gext1', named='sel_rad_faces', data=dsLA)[-1]
        eb['absorbed_IR_rad_faces_W'] = G.OPT_WHITEPAINT['eps'] * ev(j, 'IntSurface', 'otl.Gext2', named='sel_rad_faces', data=dsLA)[-1]
        eb['emitted_bus_bareAl_W'] = SIGMA * G.OPT_BARE_AL['eps'] * ev(j, 'IntSurface', 'T^4', named='sel_rest_ext', data=dsA)[-1]
        eb['area_rest_ext_m2'] = ev(j, 'IntSurface', '1', named='sel_rest_ext', data=dsA)[-1]
        eb['area_rad_faces_m2'] = ev(j, 'IntSurface', '1', named='sel_rad_faces', data=dsA)[-1]
        eb['area_all_exterior_m2'] = ev(j, 'IntSurface', '1', named='sel_ext', data=dsA)[-1]
        eb['area_wings_m2'] = ev(j, 'IntSurface', '1', named='sel_wing_front', data=dsA)[-1] + ev(j, 'IntSurface', '1', named='sel_wing_back', data=dsA)[-1]
        log['energy_balance_A'] = eb
        print("energy balance A:", json.dumps({k: v for k, v in eb.items() if 'series' not in k}, indent=1), flush=True)
    # ---------------- study B: time series
    def b_series(dsB, dsLB):
        series = {'t_s': ev(j, 'AvSurface', 't', named='sel_rad_faces', data=dsB)}
        series['rad_mean_K'] = ev(j, 'AvSurface', 'T', named='sel_rad_faces', data=dsB)
        series['rad_max_K'] = ev(j, 'MaxSurface', 'T', named='sel_rad_faces', data=dsB)
        series['rad_min_K'] = ev(j, 'MinSurface', 'T', named='sel_rad_faces', data=dsB)
        for rf in meta['rad_faces']:
            series[f'{rf}_mean_K'] = ev(j, 'AvSurface', 'T', named=rf, data=dsB)
            series[f'{rf}_max_K'] = ev(j, 'MaxSurface', 'T', named=rf, data=dsB)
        series['baseplate_mean_K'] = ev(j, 'AvSurface', 'T', named='sel_tim', data=dsB)
        series['baseplate_max_K'] = ev(j, 'MaxSurface', 'T', named='sel_tim', data=dsB)
        series['pkg_max_K'] = ev(j, 'MaxVolume', 'T', named='geom1_csel_pkgs_dom', data=dsB)
        series['pkg_mean_K'] = ev(j, 'AvVolume', 'T', named='geom1_csel_pkgs_dom', data=dsB)
        series['bus_mean_K'] = ev(j, 'AvVolume', 'T', named='geom1_csel_bus_dom', data=dsB)
        series['blades_mean_K'] = ev(j, 'AvVolume', 'T', named='geom1_csel_blades_dom', data=dsB)
        series['wing_mean_K'] = ev(j, 'AvVolume', 'T', named='geom1_csel_wings_dom', data=dsB)
        series['illum'] = ev(j, 'AvSurface', 'otl.isIlluminated', named='sel_rad_faces', data=dsB)
        series['emitted_rad_W'] = [G.OPT_WHITEPAINT['eps'] * SIGMA * v for v in ev(j, 'IntSurface', 'T^4', named='sel_rad_faces', data=dsB)]
        series['emitted_gross_W'] = emitted(dsB)
        series['abs_mutual_solar_W'] = mutual_solar(dsB)
        series['P_sources_W'] = [12 * float(x) + float(y) for x, y in zip(ev(j, 'EvalGlobal', 'Pgpu(t/1[s])', data=dsB), ev(j, 'EvalGlobal', 'Pplat(t/1[s])', data=dsB))]
        if dsLB:
            tLB = ev(j, 'AvSurface', 't', named='sel_rad_faces', data=dsLB)
            sA = absorbed_solar(dsLB); sI = absorbed_ir(dsLB)
            sIr = [G.OPT_WHITEPAINT['eps'] * v for v in ev(j, 'IntSurface', 'otl.Gext2', named='sel_rad_faces', data=dsLB)]
            sSr = [aR * v for v in ev(j, 'IntSurface', 'otl.Gext1', named='sel_rad_faces', data=dsLB)]
            import bisect
            def at(tt, ts, vs):
                i = bisect.bisect_left(ts, tt - 1e-6); i = min(max(i, 0), len(vs) - 1); return vs[i]
            series['abs_solar_albedo_ext_W'] = [at(tt, tLB, sA) for tt in series['t_s']]
            series['abs_planet_IR_ext_W'] = [at(tt, tLB, sI) for tt in series['t_s']]
            series['abs_IR_rad_faces_W'] = [at(tt, tLB, sIr) for tt in series['t_s']]
            series['abs_solar_rad_faces_W'] = [at(tt, tLB, sSr) for tt in series['t_s']]
        return series
    if dsB:
        series = b_series(dsB, dsLB)
        if dsB2:
            s2 = b_series(dsB2, dsLB2)
            # drop the duplicated first time of the extension, append
            for k in series:
                if k in s2:
                    series[k] = list(series[k]) + list(s2[k][1:])
            print("extension stdB2 appended: %d + %d times" % (len(series['t_s']) - len(s2['t_s']) + 1, len(s2['t_s']) - 1), flush=True)
        path = os.path.join(CM_DIR, f'{tag}_probes.csv')
        keys = list(series); n = len(series['t_s'])
        with open(path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh); w.writerow(keys)
            for i in range(n):
                w.writerow([series[k][i] if i < len(series[k]) else '' for k in keys])
        log['probes_csv'] = path; log['n_B_times'] = n
        print("probes ->", path, "(%d times)" % n, flush=True)
    json.dump(log, open(os.path.join(CM_DIR, f'{tag}_solve_log.json'), 'w'), indent=1)
    return log


def newest_model(case):
    """Newest out/comsol/<case>*.mph that is a production model (not lite/copy/afterA)."""
    import glob
    cands = [f for f in glob.glob(os.path.join(CM_DIR, case + '*.mph')) if not any(k in os.path.basename(f) for k in ('lite', 'copy', 'afterA'))]
    return max(cands, key=os.path.getmtime) if cands else os.path.join(CM_DIR, case + '.mph')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('case', choices=list(BC.CASES)); ap.add_argument('--mph', default=None); ap.add_argument('--orbits', type=float, default=3.0); ap.add_argument('--cores', type=int, default=4)
    args = ap.parse_args()
    tag = os.path.splitext(os.path.basename(args.mph))[0] if args.mph else args.case
    path = args.mph or newest_model(args.case)
    if not args.mph: tag = args.case      # outputs named by case (compare_report.py expects <case>_probes.csv)
    _, info, _ = BC.write_inputs(args.case, args.orbits)
    meta = dict(rad_faces=['RadiatorTop_p', 'RadiatorTop_n', 'RadiatorBot_p', 'RadiatorBot_n'])
    client = mph.start(cores=args.cores)
    model = client.load(path); print("loaded", path, flush=True)
    probe(model, args.case, tag, info, meta, args.orbits)


if __name__ == '__main__':
    main()
