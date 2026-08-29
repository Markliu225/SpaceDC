# -*- coding: utf-8 -*-
"""Smoke 10 (not a deliverable): Events interface with an indicator on
otl.isIlluminated so the solver restarts at eclipse entry/exit."""
import mph, time, os
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
client = mph.start(cores=4)
model = client.load(os.path.join(S, "smoke9.mph")); j = model.java
comp = j.component('comp1'); otl = comp.physics('otl')
for st in [str(s.tag()) for s in j.study()]:
    j.study().remove(st)

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val, flush=True); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace("\n", " ")[:300], flush=True); return False

ev = comp.physics().create('ev', 'Events', 'geom1')
print("ev default features:", [(str(f.tag()), str(f.getType())) for f in ev.feature()], flush=True)
ind = ev.create('is1', 'IndicatorStates', -1)
print("is1 props:", [str(n) for n in ind.properties()], flush=True)
ok = False
for k in ('indDim', 'indicatorStates'):
    try:
        ind.setIndex(k, 'ecl', 0, 0); ind.setIndex(k, 'otl.isIlluminated-0.5', 0, 1); ind.setIndex(k, '0', 0, 2); print("is1 table via", k, "OK", flush=True); ok = True; break
    except Exception as e:
        print("is1 table via", k, "FAIL", str(e).replace("\n", " ")[:200], flush=True)
if not ok:
    try:
        ind.setIndex('indDim', 'ecl', 0); ind.setIndex('g', 'otl.isIlluminated-0.5', 0); ind.setIndex('dimInit', '0', 0); print("is1 via indDim/g/dimInit OK", flush=True)
    except Exception as e:
        print("is1 alt FAIL", str(e).replace("\n", " ")[:200], flush=True)
for tag, cond in (('impl_in', 'ecl<0'), ('impl_out', 'ecl>0')):
    ie = ev.create(tag, 'ImplicitEvent', -1)
    print(tag, "props:", [str(n) for n in ie.properties()], flush=True)
    tryset(ie, 'condition', cond, tag)

def orbital(tag, tlist='range(0,60,5600)', rtol='0.005', activate_ev=True):
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_stat'])
        if typ == 'OrbitalTemperature': s.set('rtol', rtol)
        try:
            s.activate('ev', activate_ev)
        except Exception as e:
            print("activate ev err", str(e)[:120], flush=True)
    t0 = time.time()
    try:
        st.run(); print(f"{tag} OK {time.time()-t0:.1f}s", flush=True); return True
    except Exception as e:
        print(f"{tag} ERR", str(e).replace("\n", " ")[:400], flush=True); return False

ok1 = orbital('F1_events_iface')
model.save(os.path.join(S, "smoke10.mph")); print("done", flush=True)
