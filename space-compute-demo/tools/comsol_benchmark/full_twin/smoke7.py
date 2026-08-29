# -*- coding: utf-8 -*-
"""Smoke 7 (not a deliverable): heat-pipe rod parameters vs solve time
(toy, frozen study range(0,10,100), hemicube 32)."""
import mph, time, os
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
client = mph.start(cores=4)
model = client.load(os.path.join(S, "smoke5.mph")); j = model.java
comp = j.component('comp1'); otl = comp.physics('otl'); rs = otl.prop('RadiationSettings'); ht = comp.physics('ht'); rod = ht.feature('rod1')
for st in [str(s.tag()) for s in j.study()]:
    j.study().remove(st)
rs.set('radiationResolution', '32'); rod.active(True)

def frozen(tag, tlist='range(0,10,100)'):
    try: j.study().remove(tag)
    except Exception: pass
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_trans'])
        if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
    t0 = time.time()
    try:
        st.run(); dt = time.time() - t0
        # number of time steps taken
        try:
            n = len(j.sol(str(st.getSolverSequences()[0]) if False else 'sol' + tag).getDoubleArray('t'))
        except Exception:
            n = -1
        print(f"{tag} -> {dt:.1f}s", flush=True)
    except Exception as e:
        print(f"{tag} ERR", str(e).replace("\n", " ")[:400], flush=True)

for tag, k, rho, rl in (('C0_k1.6e5_rho2700', '1.6e5', '2700', '0.00635'),
                        ('C1_k1.6e4_rho2700', '1.6e4', '2700', '0.00635'),
                        ('C2_k1.6e5_rho2.7e5', '1.6e5', '2.7e5', '0.00635'),
                        ('C3_k1.6e3_rho2700', '1.6e3', '2700', '0.00635'),
                        ('C4_k1.6e4_rho2700_r0.02', '1.6e4', '2700', '0.02')):
    rod.set('kl', k); rod.set('rhol', rho); rod.set('rl', rl)
    frozen(tag)
model.save(os.path.join(S, "smoke7.mph")); print("saved", flush=True)
