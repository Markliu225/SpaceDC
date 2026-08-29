# one-off patch for solve_and_probe.py (energy balance via Gext1/Gext2, robust eval)
import os, py_compile
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solve_and_probe.py")
s = open(p, encoding="utf-8").read()

old = s[s.index("def _ev(j, typ, expr"):s.index("def discover_flux_vars")]
new = '''def _ev(j, typ, expr, named=None, data=None, unit=None, extra=None):
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


def newest_dataset(j):
    return [str(d.tag()) for d in j.result().dataset()][-1]


'''
s = s.replace(old, new)

s = s.replace("""    j.study('stdLA').run(); log['stdLA_wall_s'] = round(time.time() - t0, 1); print("loads study LA done %.0fs" % log['stdLA_wall_s'], flush=True)
    t0 = time.time()
    j.study('stdA').run()
    log['stdA_wall_s'] = round(time.time() - t0, 1)
    print("study A done %.0fs" % log['stdA_wall_s'])
    dsA = _last_dataset_for(j, 'stdA')""",
"""    j.study('stdLA').run(); log['stdLA_wall_s'] = round(time.time() - t0, 1); print("loads study LA done %.0fs" % log['stdLA_wall_s'], flush=True)
    dsLA = newest_dataset(j)
    t0 = time.time()
    j.study('stdA').run()
    log['stdA_wall_s'] = round(time.time() - t0, 1)
    print("study A done %.0fs" % log['stdA_wall_s'], flush=True)
    dsA = newest_dataset(j)""")

s = s.replace("""    j.study('stdLB').run(); log['stdLB_wall_s'] = round(time.time() - t0, 1); print("loads study LB done %.0fs" % log['stdLB_wall_s'], flush=True)
    model.save(os.path.join(CM_DIR, tag + '.mph'))
    t0 = time.time()
    j.study('stdB').run()
    log['stdB_wall_s'] = round(time.time() - t0, 1)
    print("study B done %.0fs" % log['stdB_wall_s'])
    dsB = _last_dataset_for(j, 'stdB')""",
"""    j.study('stdLB').run(); log['stdLB_wall_s'] = round(time.time() - t0, 1); print("loads study LB done %.0fs" % log['stdLB_wall_s'], flush=True)
    dsLB = newest_dataset(j)
    t0 = time.time()
    j.study('stdB').run()
    log['stdB_wall_s'] = round(time.time() - t0, 1)
    print("study B done %.0fs" % log['stdB_wall_s'], flush=True)
    dsB = newest_dataset(j)""")

a0 = s.index("    P_src = info['heat_per_gpu_at_t0'] * 12 + info['heat_platform_w']")
a1 = s.index("    log['energy_balance_A'] = eb")
new_eb = """    P_src = info['heat_per_gpu_at_t0'] * 12 + info['heat_platform_w']
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
"""
s = s[:a0] + new_eb + s[a1:]

b0 = s.index("    if fv.get('rflux'):\n        series['net_rad_in_all_W']")
b1 = s.index("    path = os.path.join(CM_DIR, f'{tag}_probes.csv')")
new_series = """    series['emitted_gross_W'] = emitted(dsB)
    series['abs_solar_albedo_ext_W'] = absorbed_solar(dsLB)
    series['abs_planet_IR_ext_W'] = absorbed_ir(dsLB)
    series['abs_mutual_solar_W'] = mutual_solar(dsB)
    series['P_sources_W'] = [12 * float(x) + float(y) for x, y in zip(_ev(j, 'EvalGlobal', 'Pgpu(t/1[s])', data=dsB), _ev(j, 'EvalGlobal', 'Pplat(t/1[s])', data=dsB))]
    series['abs_IR_rad_faces_W'] = _ev(j, 'IntSurface', 'otl.epsilon_amb*otl.Gext2', named='sel_rad_faces', data=dsLB)
    series['abs_solar_rad_faces_W'] = [aR * v for v in _ev(j, 'IntSurface', 'otl.Gext1', named='sel_rad_faces', data=dsLB)]
"""
s = s[:b0] + new_series + s[b1:]
s = s.replace("""    if fv.get('rflux'):
        eb['net_radiative_in_all_surfaces_W'] = _ev(j, 'IntSurface', fv['rflux'], named='sel_ext', data=dsA)[-1]
""", "")
open(p, "w", encoding="utf-8").write(s)
py_compile.compile(p, doraise=True)
print("patched & compiles")
