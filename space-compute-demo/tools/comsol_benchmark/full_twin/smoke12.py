# -*- coding: utf-8 -*-
"""Smoke 12: per-step cost of study B on the LITE full-twin model: live loads,
strict 60-s steps, BDF order 1, 0.1 orbit (10 steps, crosses eclipse entry)."""
import mph, time, os, glob, sys
D = os.path.dirname(os.path.abspath(__file__))
files = sorted(glob.glob(os.path.join(D, "out", "comsol", "caseA_lite*.mph")), key=os.path.getmtime)
path = files[-1]; print("loading", path, flush=True)
client = mph.start(cores=8)
model = client.load(path); j = model.java
for st in []:
    j.study().remove(st)
comp = j.component('comp1')
def live_study(tag, tlist, disabled, nrings=None):
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', [disabled])
        if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
    sol = j.sol().create('sol_' + tag); sol.study(tag); sol.createAutoSequence(tag)
    for f in sol.feature():
        if str(f.getType()) == 'Time':
            f.set('tstepsbdf', 'strict'); f.set('maxstepconstraintbdf', 'const'); f.set('maxstepbdf', '60'); f.set('maxorder', '1')
    return sol
otl = comp.physics('otl'); plp = otl.feature('plp1')
for label, nr, npr in (('planet5x10', '5', '10'), ('planet2x6', '2', '6')):
    plp.set('nRings', nr); plp.set('nPointsRing', npr)
    sol = live_study('B_' + label, 'range(0,60,600)', 'var_stat')
    t0 = time.time()
    try:
        sol.runAll(); print(f"{label}: 600 s orbit / 10 strict steps -> {time.time()-t0:.0f}s", flush=True)
    except Exception as e:
        print(f"{label}: ERR", str(e).replace(chr(10), ' ')[:400], flush=True)
print("done", flush=True)
