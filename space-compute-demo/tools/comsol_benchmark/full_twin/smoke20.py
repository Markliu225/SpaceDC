import mph, os, sys, time
D = os.path.dirname(os.path.abspath(__file__))
client = mph.start(cores=8)
model = client.load(os.path.join(D, "out", "comsol", "caseA_lite_copy.mph")); j = model.java
comp = j.component('comp1'); otl = comp.physics('otl')
for f in otl.feature():
    if str(f.getType()) == 'DiffuseSurface': f.set('epsilon_radSolAmb_mat', 'userdefBand')
def ev(typ, expr, named, ds):
    try: j.result().numerical().remove('gev')
    except Exception: pass
    n = j.result().numerical().create('gev', typ); n.selection().named(named); n.set('expr', expr); n.set('data', ds); n.set('innerinput', 'all')
    try: return [float(x) for x in n.getReal()[0]]
    finally: j.result().numerical().remove('gev')
def run_B(tag, tlist, segiter=None, fully_coupled=False):
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_stat'])
        if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
    sol = j.sol().create('sol_' + tag); sol.study(tag); sol.createAutoSequence(tag)
    for f in sol.feature():
        if str(f.getType()) == 'Time':
            f.set('tstepsbdf', 'strict'); f.set('maxstepconstraintbdf', 'const'); f.set('maxstepbdf', '60'); f.set('maxorder', '1')
            kids = [(str(c.tag()), str(c.getType())) for c in f.feature()]; print(tag, "time solver children:", kids, flush=True)
            for c in f.feature():
                if str(c.getType()) == 'Segregated':
                    print(tag, "segregated props:", [str(p) for p in c.properties()][:40], flush=True)
                    if segiter:
                        for k, v in (('segiter', str(segiter)), ('segterm', 'iter'), ('ntolfact', '1')):
                            try: c.set(k, v); print("  set", k, v, flush=True)
                            except Exception as e: print("  set FAIL", k, str(e).replace(chr(10), ' ')[:100], flush=True)
                    if fully_coupled:
                        try:
                            f.feature().remove(str(c.tag())); fc = f.create('fc1', 'FullyCoupled'); fc.set('maxiter', '25'); print("  fully coupled", flush=True)
                        except Exception as e: print("  fc FAIL", str(e).replace(chr(10), ' ')[:100], flush=True)
    t0 = time.time()
    try: sol.runAll(); print(f"{tag} OK {time.time()-t0:.0f}s", flush=True); return True
    except Exception as e: print(f"{tag} ERR", str(e).replace(chr(10), ' ')[:300], flush=True); return False
# eclipse exit at tau = 2510 s: run 2280 -> 2700 (7 strict steps) from the (uniform) initial state
ok = run_B('Z1_segiter30', 'range(2280,60,2700)', segiter=30)
if not ok:
    ok = run_B('Z2_fullycoupled', 'range(2280,60,2700)', fully_coupled=True)
print("done", flush=True)
