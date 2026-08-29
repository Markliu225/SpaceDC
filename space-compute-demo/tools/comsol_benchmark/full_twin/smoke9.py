# -*- coding: utf-8 -*-
"""Smoke 9 (not a deliverable): orbital run through an eclipse on the toy
(D1 model) without / with implicit eclipse events in the Events Timeline."""
import mph, time, os
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
client = mph.start(cores=4)
model = client.load(os.path.join(S, "smoke8_D1.mph")); j = model.java
comp = j.component('comp1'); otl = comp.physics('otl'); et = otl.feature('et1')
rs = otl.prop('RadiationSettings'); rs.set('viewFactorsUpdateTolerance', '0.02')
for st in [str(s.tag()) for s in j.study()]:
    j.study().remove(st)

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val, flush=True); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace("\n", " ")[:300], flush=True); return False

def orbital(tag, tlist='range(0,60,5600)', rtol='0.005'):
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_stat'])
        if typ == 'OrbitalTemperature': s.set('rtol', rtol)
    t0 = time.time()
    try:
        st.run(); print(f"{tag} OK {time.time()-t0:.1f}s", flush=True); return True
    except Exception as e:
        print(f"{tag} ERR", str(e).replace("\n", " ")[:400], flush=True); return False

print("et1 props:", [str(n) for n in et.properties()], flush=True)
ok0 = False
# add implicit eclipse events
for cand in (['inEclipse', 'outEclipse'],):
    if tryset(et, 'eventType', cand, 'et1'):
        break
tryset(et, 'implicitAxesFeatures', ['sa1', 'sa1'], 'et1'); tryset(et, 'implicitOrientationFeatures', ['so1', 'so1'], 'et1')
tryset(et, 'implicitFastTumbling', ['0', '0'], 'et1'); tryset(et, 'implicitDescription', ['into eclipse', 'out of eclipse'], 'et1')
try:
    print("eventType array:", [str(x) for x in et.getStringArray('eventType')], flush=True)
except Exception as e:
    print("eventType read err", str(e)[:100], flush=True)
ok1 = orbital('E1_events')
if not ok1:
    orbital('E2_events_rtol1e-3', rtol='0.001')
model.save(os.path.join(S, "smoke9.mph")); print("done", flush=True)
