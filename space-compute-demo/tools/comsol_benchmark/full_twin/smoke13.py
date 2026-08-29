import mph, os, sys, time
D = os.path.dirname(os.path.abspath(__file__))
client = mph.start(cores=3)
model = client.load(os.path.join(D, "out", "comsol", "caseA_lite_copy.mph")); j = model.java
comp = j.component('comp1'); ht = comp.physics('ht'); mp = comp.multiphysics('htrad1')
ents = list(mp.selection().entities()); print("htrad1 boundaries:", len(ents), " wings faces in it:", [b for b in (446, 451, 458, 459) if b in ents], flush=True)
try:
    print("htrad1 props:", {k: str(mp.getString(k)) for k in ('Heat_physics', 'Rad_physics', 'defaultDomainOpacities')}, flush=True)
except Exception as e: print("props err", str(e)[:100], flush=True)
def ev(typ, expr, named, ds='dset2'):
    try: j.result().numerical().remove('gev')
    except Exception: pass
    n = j.result().numerical().create('gev', typ); n.selection().named(named); n.set('expr', expr); n.set('data', ds); n.set('innerinput', 'all')
    try: return [float(x) for x in n.getReal()[0]]
    finally: j.result().numerical().remove('gev')
for expr in ('ht.ntflux', 'ht.ndflux', 'otl.rflux', 'otl.J', 'otl.Gm1'):
    for sel in ('sel_wing_back', 'RadiatorTop_p'):
        try: v = ev('AvSurface', expr, sel); print(f"avg {expr:10s} {sel:14s} first={v[0]:.4g} last={v[-1]:.4g}", flush=True)
        except Exception as e: print(expr, sel, "ERR", str(e).replace(chr(10), ' ')[:80], flush=True)
# opacity of wing domains as seen by otl
for expr in ('otl.dfltopaque', 'ht.opaque', 'otl.opaque'):
    try: v = ev('AvVolume', expr, 'geom1_csel_wings_dom'); print(f"wing {expr}: {v[-1]}", flush=True)
    except Exception as e: print(expr, "ERR", str(e).replace(chr(10), ' ')[:60], flush=True)
# ---- stage 2: remesh wings with free tets and run a short frozen solve
mesh = comp.mesh('mesh1')
try:
    mesh.feature().remove('swe_wings'); print("removed sweep", flush=True)
except Exception as e: print("remove sweep err", str(e)[:80], flush=True)
try:
    mesh.feature().remove('ftri_src')
except Exception: pass
t0 = time.time(); mesh.run(); print("remeshed: %d tets %d prisms in %.0fs" % (mesh.getNumElem('tet'), mesh.getNumElem('prism'), time.time() - t0), flush=True)
st = j.study().create('stdT2')
for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
    s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', 'range(0,100,300)'); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_trans'])
    if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
t0 = time.time(); st.run(); print("short solve %.0fs" % (time.time() - t0), flush=True)
dsets = [(str(d.tag()), str(d.getString('solution'))) for d in j.result().dataset()]
print("datasets:", dsets, flush=True)
for ds in [d[0] for d in dsets[-2:]]:
    try:
        v = ev('AvVolume', 'T', 'geom1_csel_wings_dom', ds); print(f"{ds}: wing T first={v[0]-273.15:.2f}C last={v[-1]-273.15:.2f}C n={len(v)}", flush=True)
        v = ev('AvVolume', 'T', 'geom1_csel_bus_dom', ds); print(f"{ds}: bus T first={v[0]-273.15:.2f}C last={v[-1]-273.15:.2f}C", flush=True)
    except Exception as e: print(ds, "ERR", str(e).replace(chr(10), ' ')[:80], flush=True)
print("done", flush=True)
