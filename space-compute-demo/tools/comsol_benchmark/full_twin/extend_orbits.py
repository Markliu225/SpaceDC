# -*- coding: utf-8 -*-
"""Extend a solved case by N more orbits as a TRUE continuation of study B.

Why this exists / what went wrong the first time: setting `initmethod='sol'`,
`initstudy`, `initstudystep`, `solnum` on the study step alone did NOT make the
orbital transient start from the previous solution -- both study B (from A)
and the first extension restarted from the uniform ht initial value
(T_struct at t0, 50.4 C).  This version (1) sets `useinitsol='on'` on the
study step, (2) sets the initial values on the solver sequence's Variables
node itself (`initmethod='sol'`, `initsol=<solB>`, `solnum='last'`), and
(3) runs a 2-step continuity self-test and aborts if the first extension
sample is not within 0.5 C of study B's last bus temperature.

    backend/.venv/Scripts/python extend_orbits.py caseA --from-orbit 3 --orbits 2 --cores 5
"""
import argparse, os, sys, time
import mph
import build_comsol as BC
import probe_offline as PO

HERE = os.path.dirname(os.path.abspath(__file__))
CM_DIR = os.path.join(HERE, "out", "comsol")
P = BC.PERIOD_S


def remove_quiet(container, tag):
    try: container.remove(tag); return True
    except Exception: return False


def make_time_solver(j, sol_tag, study_tag, init_sol, dt_out, rtol):
    sol = j.sol().create(sol_tag); sol.study(study_tag); sol.createAutoSequence(study_tag)
    report = {}
    for f in sol.feature():
        typ = str(f.getType())
        if typ == 'Variables':
            for k, v in (('initmethod', 'sol'), ('initsol', init_sol), ('solnum', 'last'), ('notsolmethod', 'sol'), ('notsol', init_sol), ('notsolnum', 'last')):
                try: f.set(k, v); report[k] = v
                except Exception as ex: report[k] = 'FAILED ' + str(ex).splitlines()[0][:60]
        if typ == 'Time':
            f.set('tstepsbdf', 'strict'); f.set('maxstepconstraintbdf', 'const'); f.set('maxstepbdf', str(dt_out)); f.set('maxorder', '1'); f.set('rtol', str(rtol))
            for c in f.feature():
                if str(c.getType()) == 'Segregated':
                    for k, v in (('segiter', '30'), ('maxsegiter', '30'), ('ntolfact', '1')):
                        try: c.set(k, v)
                        except Exception: pass
    print("solver Variables init settings:", report, flush=True)
    return sol


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('case'); ap.add_argument('--from-orbit', dest='from_orbit', type=float, default=3.0)
    ap.add_argument('--orbits', type=float, default=2.0); ap.add_argument('--dt-out', dest='dt_out', type=float, default=120.0); ap.add_argument('--cores', type=int, default=5); ap.add_argument('--rtol', type=float, default=0.005); ap.add_argument('--test-only', dest='test_only', action='store_true', help='skip LB2, run the 2-step continuity test, do not save')
    args = ap.parse_args()
    total = args.from_orbit + args.orbits
    input_path, info, _ = BC.write_inputs(args.case, total)
    print("input rows:", info['n_rows'], flush=True)
    client = mph.start(cores=args.cores)
    path = os.path.join(CM_DIR, args.case + '.mph'); model = client.load(path); j = model.java; comp = j.component('comp1')
    # --- clean up a previous (invalid) extension if present
    remove_quiet(j.sol(), 'solB2')
    for t in ('stdB2', 'stdLB2'):
        remove_quiet(j.study(), t)
    # --- longer input table (importData on an existing file-sourced function is unsupported -> recreate)
    j.func().remove('tab')
    fi = j.func().create('tab', 'Interpolation'); fi.set('source', 'file'); fi.set('filename', input_path); fi.set('nargs', '1')
    for i, nm in enumerate(('Pgpu', 'Pplat', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz')):
        fi.setIndex('funcs', nm, i, 0); fi.setIndex('funcs', str(i + 1), i, 1)
    fi.set('interp', 'linear'); fi.set('extrap', 'const'); fi.importData(); print("table recreated", flush=True)
    # --- study B's solver + its last bus temperature (reference for the continuity test)
    # A 2-step OTL study owns TWO solution stores: the loads step's (T frozen at the initial
    # value) and the temperature step's.  Taking "the solver of stdB" picks the wrong one
    # (that was the actual root cause of the restart at 50.44 C) -> take the solution tag
    # from the T-varying dataset instead and verify it with withsol() before solving.
    dm0 = PO.dataset_map(j)
    solB = str(j.result().dataset(dm0['stdB']).getString('solution'))
    print("temperature solution of stdB:", solB, "(dataset", dm0['stdB'], ")", flush=True)
    # record what study B's own solver had as initial-value settings (diagnosis of the uniform start)
    try:
        for f in j.sol(solB).feature():
            if str(f.getType()) == 'Variables':
                print("solB Variables:", {k: str(f.getString(k)) for k in ('initmethod', 'initsol', 'solnum') if k in [str(p) for p in f.properties()]}, flush=True)
    except Exception as ex:
        print("solB Variables read failed:", str(ex)[:80], flush=True)
    dm = PO.dataset_map(j); dsB = dm['stdB']
    PO.ensure_selections(comp, dict(rad_faces=['RadiatorTop_p', 'RadiatorTop_n', 'RadiatorBot_p', 'RadiatorBot_n']))
    ev = PO.SP._ev
    tB = ev(j, 'AvSurface', 't', named='sel_rad_faces', data=dsB); busB = ev(j, 'AvVolume', 'T', named='geom1_csel_bus_dom', data=dsB)
    print("study B: last t = %.0f s, bus mean %.2f C (first t bus %.2f C)" % (tB[-1], busB[-1] - 273.15, busB[0] - 273.15), flush=True)
    # --- THE mechanism that works: make the physics initial value the stored study-B field.
    # (study-step initmethod/initstudy/solnum and the solver Variables node's initsol are both
    #  ignored by the OrbitalTemperature step -- verified by the continuity test: 50.44 C restart)
    tinit_expr = f"withsol('{solB}', T, setval(t, {tB[-1]:.1f}))"
    wchk = ev(j, 'AvVolume', tinit_expr, named='geom1_csel_bus_dom', data=dsB)[0] - 273.15
    print("pre-flight: withsol bus = %.2f C vs study-B last %.2f C" % (wchk, busB[-1] - 273.15), flush=True)
    if abs(wchk - (busB[-1] - 273.15)) > 0.05:
        print("PRE-FLIGHT FAILED: withsol does not return study B's last field", flush=True); sys.exit(3)
    ht = j.component('comp1').physics('ht'); ht.feature('init1').set('Tinit', tinit_expr)
    print("ht init1 Tinit =", tinit_expr, flush=True)
    t0, t1 = args.from_orbit * P, total * P
    tl_full = f"range({t0:.1f},{args.dt_out},{t1:.1f})"; tl_test = f"range({t0:.1f},{args.dt_out},{t0 + 2 * args.dt_out:.1f})"
    # --- loads study over the extension window
    stL = j.study().create('stdLB2'); stL.label('LB2: orbital loads (extension)'); s = stL.create('otl', 'OrbitThermalLoads')
    s.set('timestepspec', 'timesteps'); s.set('tlist', tl_full); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_stat'])
    # --- temperature study, initialised from study B's last step
    stB = j.study().create('stdB2'); stB.label('B2: orbital transient extension (continuation of B)')
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = stB.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tl_test); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_stat'])
        if typ == 'OrbitalTemperature':
            s.set('rtol', str(args.rtol))
            for k, v in (('useinitsol', 'on'), ('initmethod', 'sol'), ('initstudy', 'stdB'), ('initstudystep', 'ot'), ('solnum', 'last')):
                try: s.set(k, v)
                except Exception as ex: print("study-step", k, "FAILED:", str(ex).splitlines()[0][:80], flush=True)
    if not args.test_only:
        tt = time.time(); stL.run(); print("LB2 done %.0fs" % (time.time() - tt), flush=True)
    # --- continuity self-test: 2 steps
    solB2 = make_time_solver(j, 'solB2', 'stdB2', solB, args.dt_out, args.rtol)
    tt = time.time(); solB2.runAll(); print("B2 test run %.0fs" % (time.time() - tt), flush=True)
    dm = PO.dataset_map(j); ds2 = dm.get('stdB2')
    t2 = ev(j, 'AvSurface', 't', named='sel_rad_faces', data=ds2); bus2 = ev(j, 'AvVolume', 'T', named='geom1_csel_bus_dom', data=ds2)
    d = bus2[0] - busB[-1]
    print("continuity: B2 first t = %.0f s bus %.2f C vs B last bus %.2f C -> diff %.2f C" % (t2[0], bus2[0] - 273.15, busB[-1] - 273.15, d), flush=True)
    if abs(d) > 0.5:
        print("CONTINUITY FAILED - not running the full extension", flush=True); sys.exit(2)
    if args.test_only:
        print("CONTINUITY OK (test-only, not saved)", flush=True); return
    # --- full run
    stB.feature('otl').set('tlist', tl_full); stB.feature('ot').set('tlist', tl_full)
    tt = time.time(); solB2.runAll(); print("B2 done %.0fs" % (time.time() - tt), flush=True)
    model.save(path); print("saved", path, flush=True)


if __name__ == '__main__':
    main()
