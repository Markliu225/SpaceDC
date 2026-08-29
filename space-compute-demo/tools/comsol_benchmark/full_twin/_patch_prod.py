# one-off patch: production configuration (live loads + strict BDF1 steps, 13-point planet,
# loads-only studies kept for the absorbed-power integrals)
import os, py_compile
D = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(D, "build_comsol.py"); s = open(p, encoding="utf-8").read()

# planet discretization
old = "    plp = otl.feature('plp1'); plp.set('planetProperties', 'earth')\n"
new = old + """    # planet discretisation 2 rings x 6 = 13 point sources (default 5x10 = 51):
    # every external view-factor update costs ~1.2 s per source per step on the
    # lite mesh (smoke12), and the 13-point disc changes the integrated planet
    # loads by < 1 % (reported in the solve log)
    plp.set('nRings', str(args.planet_rings)); plp.set('nPointsRing', str(args.planet_points))
"""
assert old in s; s = s.replace(old, new)

# studies
a = s.index("    # ---- studies: external loads are PRECOMPUTED"); b = s.index("    return client, model, dict(")
new_st = """    # ---- studies. Temperature studies evaluate the loads LIVE (one study with
    # an Orbit Thermal Loads step + an Orbital Temperature step); the orbital
    # one is integrated with STRICT BDF-1 steps equal to the output interval —
    # the only stepping that passed the eclipse switch in the smoke tests
    # (smoke9-12). Separate loads-only studies (LA, LB) exist solely so the
    # absorbed external power can be integrated explicitly (otl.Gext2 can only
    # be evaluated on a loads-study dataset in this build).
    def loads_study(tag, tlist, disabled, label):
        st = j.study().create(tag); st.label(label); s = st.create('otl', 'OrbitThermalLoads')
        s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', [disabled]); return st
    def temp_study(tag, tlist, disabled, label, init=None):
        st = j.study().create(tag); st.label(label)
        for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
            s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', [disabled])
            if typ == 'OrbitalTemperature':
                s.set('rtol', str(args.rtol))
                if init:
                    s.set('initmethod', 'sol'); s.set('initstudy', init); s.set('initstudystep', 'ot'); s.set('solnum', 'last')
        return st
    tlist_A = f"range(0,{args.dt_frozen},{args.t_frozen})"
    loads_study('stdLA', f"range(0,{args.t_frozen},{args.t_frozen})", 'var_trans', 'LA: frozen loads (for the energy balance)')
    temp_study('stdA', tlist_A, 'var_trans', 'A: frozen environment -> steady state (1000x slow motion)')
    t_end = args.orbits * PERIOD_S
    tlist_B = f"range(0,{args.dt_out},{t_end:.1f})"
    loads_study('stdLB', tlist_B, 'var_stat', 'LB: orbital loads (for the absorbed-power series)')
    temp_study('stdB', tlist_B, 'var_stat', 'B: orbital transient, strict BDF-1 steps (init from A)', init='stdA')
"""
s = s[:a] + new_st + s[b:]
s = s.replace("    ap.add_argument('--vf-tol', dest='vf_tol', type=float, default=0.02)",
              "    ap.add_argument('--vf-tol', dest='vf_tol', type=float, default=0.02)\n    ap.add_argument('--planet-rings', dest='planet_rings', type=int, default=2)\n    ap.add_argument('--planet-points', dest='planet_points', type=int, default=6)\n    ap.add_argument('--log', default=None)")
# production mesh sizes
s = s.replace("    for nm, hmax in (('rads', 0.12 if args.lite else 0.05), ('wings', 0.6 if args.lite else 0.20), ('hp', 0.08 if args.lite else 0.04)):",
              "    for nm, hmax in (('rads', 0.12 if args.lite else 0.06), ('wings', 0.6 if args.lite else 0.40), ('hp', 0.08 if args.lite else 0.05)):")
s = s.replace("    ap.add_argument('--dt-out', dest='dt_out', type=float, default=20.0)   # also the loads sampling interval",
              "    ap.add_argument('--dt-out', dest='dt_out', type=float, default=60.0)   # strict solver step = output interval")
open(p, "w", encoding="utf-8").write(s)

p2 = os.path.join(D, "solve_and_probe.py"); s2 = open(p2, encoding="utf-8").read()
old2 = """    j.study('stdLA').run(); log['stdLA_wall_s'] = round(time.time() - t0, 1); print("loads study LA done %.0fs" % log['stdLA_wall_s'], flush=True)
    dsLA = newest_dataset(j)
    t0 = time.time()
    j.study('stdA').run()
    log['stdA_wall_s'] = round(time.time() - t0, 1)
    print("study A done %.0fs" % log['stdA_wall_s'], flush=True)
    dsA = newest_dataset(j)"""
new2 = """    j.study('stdLA').run(); log['stdLA_wall_s'] = round(time.time() - t0, 1); print("loads study LA done %.0fs" % log['stdLA_wall_s'], flush=True)
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
    dsA = newest_dataset(j)"""
assert old2 in s2; s2 = s2.replace(old2, new2)
old3 = """    solB = j.sol().create('solB'); solB.study('stdB'); solB.createAutoSequence('stdB')
    for f in solB.feature():
        if str(f.getType()) == 'Time':
            f.set('tstepsbdf', 'strict'); f.set('maxstepconstraintbdf', 'const'); f.set('maxstepbdf', str(args.dt_out)); f.set('maxorder', '2'); f.set('rtol', str(args.rtol))"""
new3 = """    solB = j.sol().create('solB'); solB.study('stdB'); solB.createAutoSequence('stdB')
    for f in solB.feature():
        if str(f.getType()) == 'Time':
            f.set('tstepsbdf', 'strict'); f.set('maxstepconstraintbdf', 'const'); f.set('maxstepbdf', str(args.dt_out)); f.set('maxorder', '1'); f.set('rtol', str(args.rtol))"""
assert old3 in s2; s2 = s2.replace(old3, new3)
open(p2, "w", encoding="utf-8").write(s2)
py_compile.compile(p, doraise=True); py_compile.compile(p2, doraise=True); print("patched & compiles")
