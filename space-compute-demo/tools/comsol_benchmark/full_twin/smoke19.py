import mph, os, sys, time
D = os.path.dirname(os.path.abspath(__file__))
client = mph.start(cores=6)
model = client.load(os.path.join(D, "out", "comsol", "caseA_lite_copy.mph")); j = model.java
comp = j.component('comp1'); otl = comp.physics('otl')
for f in otl.feature():
    if str(f.getType()) == 'DiffuseSurface':
        f.set('epsilon_radSolAmb_mat', 'userdefBand')
        print("set userdefBand on", str(f.tag()), "bands:", [str(x) for x in f.getStringArray('epsilon_rad_bandSolAmb')], flush=True)
def ev(typ, expr, named, ds):
    try: j.result().numerical().remove('gev')
    except Exception: pass
    n = j.result().numerical().create('gev', typ); n.selection().named(named); n.set('expr', expr); n.set('data', ds); n.set('innerinput', 'all')
    try: return [float(x) for x in n.getReal()[0]]
    finally: j.result().numerical().remove('gev')
st = j.study().create('Y1_userdefBand')
for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
    s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', 'range(0,100,300)'); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_trans'])
    if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
t0 = time.time()
try: st.run(); print("Y1 solved %.0fs" % (time.time() - t0), flush=True)
except Exception as e: print("Y1 ERR", str(e).replace(chr(10), ' ')[:400], flush=True); sys.exit(1)
tags = [str(d.tag()) for d in j.result().dataset()]
best = None; bestr = -1
for tg in tags[-2:]:
    v = ev('AvVolume', 'T', 'geom1_csel_bus_dom', tg); r = max(v) - min(v)
    if r > bestr: best, bestr = tg, r
for nm in ('geom1_csel_wings_dom', 'geom1_csel_bus_dom', 'geom1_csel_rads_dom', 'geom1_csel_pkgs_dom'):
    v = ev('AvVolume', 'T', nm, best); print(f"Y1 {nm}: {v[0]-273.15:.2f} -> {v[-1]-273.15:.2f} C", flush=True)
for expr, sel in (('otl.epsilon_rad', 'sel_wing_back'), ('otl.epsilon_rad', 'RadiatorTop_p'), ('otl.Gext1', 'sel_wing_back'), ('otl.J', 'sel_wing_back')):
    try: v = ev('AvSurface', expr, sel, best); print(f"Y1 avg {expr} on {sel}: first={v[0]:.4g} last={v[-1]:.4g}", flush=True)
    except Exception as e: print(expr, sel, "ERR", str(e).replace(chr(10), ' ')[:80], flush=True)
print("done", flush=True)
