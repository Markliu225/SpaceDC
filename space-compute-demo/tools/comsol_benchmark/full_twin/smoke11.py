# -*- coding: utf-8 -*-
"""Smoke 11 (not a deliverable): get through an eclipse switch on the toy.
H1: temperature step uses precomputed external loads (separate loads study).
H2: BDF order 1 + strict bounded steps.  H3: both."""
import mph, time, os
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
client = mph.start(cores=4)
model = client.load(os.path.join(S, "smoke10.mph")); j = model.java
comp = j.component('comp1')
for st in [str(s.tag()) for s in j.study()]:
    j.study().remove(st)
for so in [str(s.tag()) for s in j.sol()]:
    try: j.sol().remove(so)
    except Exception: pass

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val, flush=True); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace("\n", " ")[:250], flush=True); return False

TL = 'range(0,30,5600)'
# ---- H1: separate loads study
stL = j.study().create('stdL'); sL = stL.create('otl', 'OrbitThermalLoads'); sL.set('timestepspec', 'timesteps'); sL.set('tlist', TL); sL.set('useadvanceddisable', True); sL.set('disabledvariables', ['var_stat'])
t0 = time.time()
try:
    stL.run(); print("loads study OK %.1fs" % (time.time() - t0), flush=True)
except Exception as e:
    print("loads study ERR", str(e).replace("\n", " ")[:300], flush=True)
stT = j.study().create('stdT'); sT = stT.create('ot', 'OrbitalTemperature'); sT.set('timestepspec', 'timesteps'); sT.set('tlist', TL); sT.set('useadvanceddisable', True); sT.set('disabledvariables', ['var_stat']); sT.set('rtol', '0.005')
print("ot gext props:", {k: str(sT.getString(k)) for k in ('gextsol', 'gextsoluse', 'gextstudy', 'gextstudystep') if True}, flush=True)
tryset(sT, 'gextstudy', 'stdL', 'ot'); tryset(sT, 'gextstudystep', 'otl', 'ot')
for cand in ('sol', 'stdL', 'study'):
    if tryset(sT, 'gextsoluse', cand, 'ot'): break
t0 = time.time()
try:
    stT.run(); print("H1 precomputed-loads OK %.1fs" % (time.time() - t0), flush=True)
except Exception as e:
    print("H1 ERR", str(e).replace("\n", " ")[:400], flush=True)

# ---- H2: BDF order 1, strict steps, max step 20 s (live loads)
stH = j.study().create('stdH')
for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
    s = stH.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', TL); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_stat'])
    if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
sol = j.sol().create('solH'); sol.study('stdH'); sol.createAutoSequence('stdH')
print("solH features:", [(str(f.tag()), str(f.getType())) for f in sol.feature()], flush=True)
for f in sol.feature():
    if str(f.getType()) == 'Time':
        print("time solver props:", [str(n) for n in f.properties()][:80], flush=True)
        tryset(f, 'maxorder', '1', 'time'); tryset(f, 'tstepsbdf', 'strict', 'time'); tryset(f, 'maxstepconstraintbdf', 'const', 'time'); tryset(f, 'maxstepbdf', '20', 'time')
        tryset(f, 'eventtol', '0.01', 'time')
t0 = time.time()
try:
    sol.runAll(); print("H2 bdf1-strict OK %.1fs" % (time.time() - t0), flush=True)
except Exception as e:
    print("H2 ERR", str(e).replace("\n", " ")[:400], flush=True)
model.save(os.path.join(S, "smoke11.mph")); print("done", flush=True)
