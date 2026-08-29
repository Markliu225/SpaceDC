# -*- coding: utf-8 -*-
"""Phase 3/4/5 helper — solve studies A and B, run the sanity checks, probe
time series, export CSV + summary JSON. Called by build_comsol.py.

Probe definitions (all on the COMSOL solution):
  rad_mean   area-weighted mean T over both faces of both radiator panels
  rad_max    max T over the same faces
  rad_top/bot_mean / _max   per panel
  baseplate  area-weighted mean T over the 12 blade-top faces under the GPU
             packages (the TIM boundary)  -> "GPU baseplate T"
  pkg_max    max T over the package domains (hottest package)
  bus_mean   volume-weighted mean T over spine + thrusters + tanks + blades
  wing_mean  volume mean over the two solar wings
"""
import csv, json, math, os, time
import geometry_spec as G

SIGMA = 5.670374419e-8
HERE = os.path.dirname(os.path.abspath(__file__))
CM_DIR = os.path.join(HERE, "out", "comsol")


def _ev(j, typ, expr, named=None, data=None, unit=None, extra=None):
    """Create a numerical feature, evaluate, remove. Returns a list over the
    dataset's time steps (COMSOL returns 1 row x n_times columns)."""
    tag = 'ev_tmp'
    try:
        j.result().numerical().remove(tag)
    except Exception:
        pass
    n = j.result().numerical().create(tag, typ)
    try:
        if named is not None:
            n.selection().named(named)
        if data is not None:
            n.set('data', data)
        n.set('expr', expr)
        if unit:
            n.set('unit', unit)
        try:
            n.set('innerinput', 'all')
        except Exception:
            pass
        vals = n.getReal()
        return [float(v) for v in vals[0]]
    finally:
        try:
            j.result().numerical().remove(tag)
        except Exception:
            pass


def dataset_for_sol(j, soltag):
    for d in j.result().dataset():
        try:
            if str(d.getString('solution')) == soltag:
                return str(d.tag())
        except Exception:
            pass
    return newest_dataset(j)


def newest_dataset(j):
    return [str(d.tag()) for d in j.result().dataset()][-1]


def discover_flux_vars(j, data, named):
    """Find which OTL variable names exist in this COMSOL build (they are
    undocumented in the API): returns dict role -> expression or None."""
    roles = {
        'Gext_total': ['otl.Gext', 'otl.Gext_amb', 'otl.Gext_sol'],
        'Gext_sol': ['otl.Gext_sol', 'otl.Gextsol', 'otl.Gext_Bsol', 'otl.Gext_B1', 'otl.Gexts'],
        'Gext_amb': ['otl.Gext_amb', 'otl.Gextamb', 'otl.Gext_Bamb', 'otl.Gext_B2'],
        'G_sol': ['otl.G_sol', 'otl.Gsol', 'otl.G_Bsol', 'otl.G_B1'],
        'G_amb': ['otl.G_amb', 'otl.Gamb', 'otl.G_Bamb', 'otl.G_B2'],
        'J_amb': ['otl.J_amb', 'otl.Jamb', 'otl.J_Bamb', 'otl.J_B2'],
        'rflux': ['otl.rflux', 'ht.rflux'],
        'rflux_sol': ['otl.rflux_sol', 'otl.rfluxsol', 'otl.rflux_Bsol', 'otl.rflux_B1'],
        'rflux_amb': ['otl.rflux_amb', 'otl.rfluxamb', 'otl.rflux_Bamb', 'otl.rflux_B2'],
        'eps_sol': ['otl.epsilon_rad_sol', 'otl.eps_sol', 'otl.epsilon_sol', 'otl.epsilon_rad_Bsol', 'otl.epsilon_rad_B1'],
        'eps_amb': ['otl.epsilon_rad_amb', 'otl.eps_amb', 'otl.epsilon_amb', 'otl.epsilon_rad_Bamb', 'otl.epsilon_rad_B2', 'otl.epsilon_rad'],
        'illum': ['otl.isIlluminated'],
        'ntflux': ['ht.ntflux'],
    }
    found = {}
    for role, cands in roles.items():
        found[role] = None
        for c in cands:
            try:
                v = _ev(j, 'AvSurface', c, named=named, data=data)
                if v and all(math.isfinite(x) for x in v):
                    found[role] = c
                    break
            except Exception:
                continue
    return found


def run(model, args, info, meta, tag):
    j = model.java
    comp = j.component('comp1')
    log = {}
    # ------------------------------------------------------------ study A
    t0 = time.time()
    j.study('stdLA').run(); log['stdLA_wall_s'] = round(time.time() - t0, 1); print("loads study LA done %.0fs" % log['stdLA_wall_s'], flush=True)
    dsLA = newest_dataset(j)
    # planet-discretisation sensitivity of the integrated loads (13 vs 51 points), frozen instant
    try:
        otl = comp.physics('otl'); plp = otl.feature('plp1')
        sel_ext_tmp = comp.selection().create('sel_ext_tmp', 'Box'); sel_ext_tmp.set('entitydim', '2'); sel_ext_tmp.set('condition', 'inside')
        for k, v in (('xmin', -50.0), ('xmax', 50.0), ('ymin', -50.0), ('ymax', 50.0), ('zmin', -50.0), ('zmax', 50.0)): sel_ext_tmp.set(k, v)
        g2_13 = _ev(j, 'IntSurface', 'otl.epsilon_amb*otl.Gext2', named='sel_ext_tmp', data=dsLA)[-1]
        plp.set('nRings', '5'); plp.set('nPointsRing', '10'); j.study('stdLA').run(); ds51 = newest_dataset(j)
        g2_51 = _ev(j, 'IntSurface', 'otl.epsilon_amb*otl.Gext2', named='sel_ext_tmp', data=ds51)[-1]
        g1_51 = _ev(j, 'IntSurface', 'otl.Gext1', named='sel_ext_tmp', data=ds51)[-1]
        plp.set('nRings', str(args.planet_rings)); plp.set('nPointsRing', str(args.planet_points)); j.study('stdLA').run(); dsLA = newest_dataset(j)
        g1_13 = _ev(j, 'IntSurface', 'otl.Gext1', named='sel_ext_tmp', data=dsLA)[-1]
        log['planet_discretisation_check'] = dict(absorbed_IR_13pt_W=g2_13, absorbed_IR_51pt_W=g2_51, Gext1_13pt_W=g1_13, Gext1_51pt_W=g1_51,
                                                  IR_diff_pct=100.0 * (g2_13 - g2_51) / g2_51, solar_diff_pct=100.0 * (g1_13 - g1_51) / g1_51)
        print("planet discretisation check:", log['planet_discretisation_check'], flush=True)
    except Exception as e:
        print("planet check skipped:", str(e).replace(chr(10), ' ')[:200], flush=True)
    t0 = time.time()
    j.study('stdA').run()
    log['stdA_wall_s'] = round(time.time() - t0, 1)
    print("study A done %.0fs" % log['stdA_wall_s'], flush=True)
    dsA = newest_dataset(j)
    try:
        model.save(os.path.join(CM_DIR, tag + '.mph')); print("saved after A", flush=True)
    except Exception as e:
        print("save after A failed:", str(e)[:120], flush=True)
    SKIP = os.environ.get('SKIP_INRUN_PROBES') == '1'
    # selections used by probes
    rad_all = comp.selection().create('sel_rad_faces', 'Union'); rad_all.set('entitydim', '2'); rad_all.set('input', meta['rad_faces'])
    # exterior boundaries only (interior faces such as the TIM layer carry side-dependent fluxes)
    alldom = comp.selection().create('sel_alldom', 'Box'); alldom.set('entitydim', '3'); alldom.set('condition', 'inside')
    alldom.set('xmin', -50.0); alldom.set('xmax', 50.0); alldom.set('ymin', -50.0); alldom.set('ymax', 50.0); alldom.set('zmin', -50.0); alldom.set('zmax', 50.0)
    ext_all = comp.selection().create('sel_ext', 'Adjacent'); ext_all.set('entitydim', '3'); ext_all.set('outputdim', '2'); ext_all.set('input', ['sel_alldom']); ext_all.set('exterior', True); ext_all.set('interior', False)
    if not SKIP:
        fv = discover_flux_vars(j, dsA, 'sel_rad_faces')
        log['flux_vars'] = fv
        print("flux variables:", fv)
        # steady-state check on the last A time: temperatures + energy balance
        TA = _ev(j, 'AvSurface', 'T', named='sel_rad_faces', data=dsA)
        log['A_rad_mean_K_series'] = TA
        log['A_rad_mean_K'] = TA[-1]
        log['A_rad_mean_drift_last_step_K'] = TA[-1] - TA[-2] if len(TA) > 1 else None
        log['A_rad_max_K'] = _ev(j, 'MaxSurface', 'T', named='sel_rad_faces', data=dsA)[-1]
        log['A_pkg_max_K'] = _ev(j, 'MaxVolume', 'T', named='geom1_csel_pkgs_dom', data=dsA)[-1]
        log['A_bus_mean_K'] = _ev(j, 'AvVolume', 'T', named='geom1_csel_bus_dom', data=dsA)[-1]
        log['A_blades_mean_K'] = _ev(j, 'AvVolume', 'T', named='geom1_csel_blades_dom', data=dsA)[-1]
        log['A_wing_mean_K'] = _ev(j, 'AvVolume', 'T', named='geom1_csel_wings_dom', data=dsA)[-1]
        # energy balance: sources vs radiation. Emitted computed explicitly from
        # known emissivities (independent of variable naming); absorbed external
        # from the OTL irradiation variables if found.
        P_src = info['heat_per_gpu_at_t0'] * 12 + info['heat_platform_w']
        eb = dict(P_sources_W=P_src)
        aF, aB, aR = G.OPT_CELL_FRONT['alpha'], G.OPT_CELL_BACK['alpha'], G.OPT_WHITEPAINT['alpha']   # every other exterior surface: bare Al alpha 0.25 == aR

        def absorbed_solar(ds):
            # otl.Gext1 = external irradiation, solar band (direct sun + albedo) -> evaluate on the LOADS study dataset
            tot = _ev(j, 'IntSurface', 'otl.Gext1', named='sel_ext', data=ds)
            fr = _ev(j, 'IntSurface', 'otl.Gext1', named='sel_wing_front', data=ds)
            bk = _ev(j, 'IntSurface', 'otl.Gext1', named='sel_wing_back', data=ds)
            return [aR * t + (aF - aR) * f + (aB - aR) * b for t, f, b in zip(tot, fr, bk)]

        def absorbed_ir(ds):
            # otl.Gext2 = external irradiation, ambient band (planet IR); absorptivity = emissivity
            return _ev(j, 'IntSurface', 'otl.epsilon_amb*otl.Gext2', named='sel_ext', data=ds)

        def emitted(ds):
            return [SIGMA * v for v in _ev(j, 'IntSurface', 'otl.epsilon_amb*T^4', named='sel_ext', data=ds)]

        def mutual_solar(ds):
            tot = _ev(j, 'IntSurface', 'otl.Gm1', named='sel_ext', data=ds)
            fr = _ev(j, 'IntSurface', 'otl.Gm1', named='sel_wing_front', data=ds)
            bk = _ev(j, 'IntSurface', 'otl.Gm1', named='sel_wing_back', data=ds)
            return [aR * t + (aF - aR) * f + (aB - aR) * b for t, f, b in zip(tot, fr, bk)]

        eb['absorbed_solar_albedo_ext_W'] = absorbed_solar(dsLA)[-1]
        eb['absorbed_planet_IR_ext_W'] = absorbed_ir(dsLA)[-1]
        eb['absorbed_mutual_solar_band_W'] = mutual_solar(dsA)[-1]
        eb['emitted_gross_W'] = emitted(dsA)[-1]
        eb['emitted_gross_series_W'] = emitted(dsA)
        eb['absorbed_total_W'] = P_src + eb['absorbed_solar_albedo_ext_W'] + eb['absorbed_planet_IR_ext_W'] + eb['absorbed_mutual_solar_band_W']
        # mutual absorption in the ambient band (otl.Gm2) cannot be evaluated in this build (COMSOL NPE) -> shows up in the residual
        eb['residual_W_(mutual_IR_absorbed+error)'] = eb['emitted_gross_W'] - eb['absorbed_total_W']
        eb['closure_pct_gross'] = 100.0 * (eb['emitted_gross_W'] - eb['absorbed_total_W']) / eb['absorbed_total_W']
        eb['emitted_rad_faces_W'] = G.OPT_WHITEPAINT['eps'] * SIGMA * _ev(j, 'IntSurface', 'T^4', named='sel_rad_faces', data=dsA)[-1]
        eb['emitted_wings_W'] = SIGMA * (_ev(j, 'IntSurface', 'otl.epsilon_amb*T^4', named='sel_wing_front', data=dsA)[-1] + _ev(j, 'IntSurface', 'otl.epsilon_amb*T^4', named='sel_wing_back', data=dsA)[-1])
        eb['absorbed_solar_wings_W'] = (aF * _ev(j, 'IntSurface', 'otl.Gext1', named='sel_wing_front', data=dsLA)[-1] + aB * _ev(j, 'IntSurface', 'otl.Gext1', named='sel_wing_back', data=dsLA)[-1])
        eb['absorbed_solar_rad_faces_W'] = aR * _ev(j, 'IntSurface', 'otl.Gext1', named='sel_rad_faces', data=dsLA)[-1]
        eb['absorbed_IR_rad_faces_W'] = _ev(j, 'IntSurface', 'otl.epsilon_amb*otl.Gext2', named='sel_rad_faces', data=dsLA)[-1]
        log['energy_balance_A'] = eb
        print("energy balance A:", json.dumps(eb, indent=1))
        # radiating area check
        eb['area_rad_faces_m2'] = _ev(j, 'IntSurface', '1', named='sel_rad_faces', data=dsA)[-1]
        eb['area_all_exterior_m2'] = _ev(j, 'IntSurface', '1', named='sel_ext', data=dsA)[-1]
        print("radiating area: radiator faces %.3f m2, all exterior %.3f m2" % (eb['area_rad_faces_m2'], eb['area_all_exterior_m2']))
    # ------------------------------------------------------------ study B
    t0 = time.time()
    j.study('stdLB').run(); log['stdLB_wall_s'] = round(time.time() - t0, 1); print("loads study LB done %.0fs" % log['stdLB_wall_s'], flush=True)
    dsLB = newest_dataset(j)
    # Study B solver sequence (created only now: creating it before the loads
    # studies have solutions makes StudyClient.run throw a NullPointerException).
    # STRICT steps equal to the load-sampling interval: the precomputed loads are
    # piecewise-linear (kink every dt_out); a free BDF stepper crawls through the
    # kinks (lite mesh: 0.3 orbit unfinished after 5 CPU-hours). Max BDF order 2.
    solB = j.sol().create('solB'); solB.study('stdB'); solB.createAutoSequence('stdB')
    for f in solB.feature():
        if str(f.getType()) == 'Time':
            f.set('tstepsbdf', 'strict'); f.set('maxstepconstraintbdf', 'const'); f.set('maxstepbdf', str(args.dt_out)); f.set('maxorder', '1'); f.set('rtol', str(args.rtol))
            # eclipse-exit robustness: the radiosity<->temperature segregated loop hit its default
            # iteration cap at the event restart (v2 Case A died at tau = 2511.8 s = eclipse exit)
            for c in f.feature():
                if str(c.getType()) == 'Segregated':
                    for k, v in (('segiter', '30'), ('maxsegiter', '30'), ('ntolfact', '1')):
                        try: c.set(k, v)
                        except Exception as e: print('segregated set', k, 'failed:', str(e)[:80], flush=True)
    t0 = time.time()
    solB.runAll()
    log['stdB_wall_s'] = round(time.time() - t0, 1)
    print("study B done %.0fs" % log['stdB_wall_s'], flush=True)
    dsB = dataset_for_sol(j, 'solB')
    try:
        model.save(os.path.join(CM_DIR, tag + '.mph')); print("saved after B", flush=True)
    except Exception as e:
        print("save after B failed:", str(e)[:120], flush=True)
    if not SKIP:
        times = _ev(j, 'EvalGlobal', 't', data=dsB)
        series = {'t_s': times}
        series['rad_mean_K'] = _ev(j, 'AvSurface', 'T', named='sel_rad_faces', data=dsB)
        series['rad_max_K'] = _ev(j, 'MaxSurface', 'T', named='sel_rad_faces', data=dsB)
        series['rad_min_K'] = _ev(j, 'MinSurface', 'T', named='sel_rad_faces', data=dsB)
        for rf in meta['rad_faces']:
            series[f'{rf}_mean_K'] = _ev(j, 'AvSurface', 'T', named=rf, data=dsB)
            series[f'{rf}_max_K'] = _ev(j, 'MaxSurface', 'T', named=rf, data=dsB)
        series['baseplate_mean_K'] = _ev(j, 'AvSurface', 'T', named='sel_tim', data=dsB)
        series['baseplate_max_K'] = _ev(j, 'MaxSurface', 'T', named='sel_tim', data=dsB)
        series['pkg_max_K'] = _ev(j, 'MaxVolume', 'T', named='geom1_csel_pkgs_dom', data=dsB)
        series['pkg_mean_K'] = _ev(j, 'AvVolume', 'T', named='geom1_csel_pkgs_dom', data=dsB)
        series['bus_mean_K'] = _ev(j, 'AvVolume', 'T', named='geom1_csel_bus_dom', data=dsB)
        series['blades_mean_K'] = _ev(j, 'AvVolume', 'T', named='geom1_csel_blades_dom', data=dsB)
        series['wing_mean_K'] = _ev(j, 'AvVolume', 'T', named='geom1_csel_wings_dom', data=dsB)
        if fv.get('illum'):
            series['illum'] = _ev(j, 'AvSurface', fv['illum'], named='sel_rad_faces', data=dsB)
        series['emitted_rad_W'] = [G.OPT_WHITEPAINT['eps'] * SIGMA * v for v in _ev(j, 'IntSurface', 'T^4', named='sel_rad_faces', data=dsB)]
        series['emitted_gross_W'] = emitted(dsB)
        series['abs_solar_albedo_ext_W'] = absorbed_solar(dsLB)
        series['abs_planet_IR_ext_W'] = absorbed_ir(dsLB)
        series['abs_mutual_solar_W'] = mutual_solar(dsB)
        series['P_sources_W'] = [12 * float(x) + float(y) for x, y in zip(_ev(j, 'EvalGlobal', 'Pgpu(t/1[s])', data=dsB), _ev(j, 'EvalGlobal', 'Pplat(t/1[s])', data=dsB))]
        series['abs_IR_rad_faces_W'] = _ev(j, 'IntSurface', 'otl.epsilon_amb*otl.Gext2', named='sel_rad_faces', data=dsLB)
        series['abs_solar_rad_faces_W'] = [aR * v for v in _ev(j, 'IntSurface', 'otl.Gext1', named='sel_rad_faces', data=dsLB)]
        path = os.path.join(CM_DIR, f'{tag}_probes.csv')
        keys = list(series)
        n = len(series['t_s'])
        with open(path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh); w.writerow(keys)
            for i in range(n):
                w.writerow([series[k][i] if i < len(series[k]) else '' for k in keys])
        log['probes_csv'] = path
    json.dump(log, open(os.path.join(CM_DIR, f'{tag}_solve_log.json'), 'w'), indent=1)
    model.save(os.path.join(CM_DIR, tag + '.mph'))
    print("probes ->", path)
    return log


def _last_dataset_for(j, study_tag):
    """Dataset tag of the solution produced by a study (the last Solution
    dataset whose solution belongs to that study)."""
    best = None
    for d in j.result().dataset():
        try:
            if str(d.getType()) != 'Solution':
                continue
            sol = str(d.getString('solution'))
            st = str(j.sol(sol).getString('study')) if hasattr(j.sol(sol), 'getString') else ''
            if study_tag in (st, str(j.sol(sol).study())):
                best = str(d.tag())
        except Exception:
            continue
    if best is None:
        tags = [str(d.tag()) for d in j.result().dataset()]
        best = tags[-1]
    return best
