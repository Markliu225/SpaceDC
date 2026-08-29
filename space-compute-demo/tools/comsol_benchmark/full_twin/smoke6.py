# -*- coding: utf-8 -*-
"""Smoke 6 (not a deliverable): view-factor update controls and planet
discretization vs. solve time, toy model, frozen study range(0,10,100)."""
import mph, time, os
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
client = mph.start(cores=4)
model = client.load(os.path.join(S, "smoke5.mph")); j = model.java
comp = j.component('comp1'); otl = comp.physics('otl'); rs = otl.prop('RadiationSettings'); plp = otl.feature('plp1')
for st in [str(s.tag()) for s in j.study()]:
    j.study().remove(st)

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val, flush=True); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace("\n", " ")[:300], flush=True); return False

def frozen(tag, tlist='range(0,10,100)'):
    try: j.study().remove(tag)
    except Exception: pass
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_trans'])
        if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
    t0 = time.time()
    try:
        st.run(); print(f"{tag} -> {time.time()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"{tag} ERR", str(e).replace("\n", " ")[:400], flush=True)

print("current:", {k: str(rs.getString(k)) for k in ('radiationResolution', 'viewFactorsUpdateExpression', 'viewFactorsUpdateTolerance', 'viewFactorsUpdateTime', 'viewFactorUpdateThreshold', 'storeViewFactors')}, flush=True)
print("planet:", {k: str(plp.getString(k)) for k in ('nRings', 'nPointsRing')}, flush=True)
rs.set('radiationResolution', '64')
frozen('B0_res64_default')
# planet discretization
plp.set('nRings', '2'); plp.set('nPointsRing', '6')
frozen('B1_res64_planet2x6')
plp.set('nRings', '5'); plp.set('nPointsRing', '10')
# update threshold enum discovery
for cand in ('never', 'onGeometryChange', 'everyTimeStep', 'tolerance', 'expression', 'manual', 'userdef'):
    if tryset(rs, 'viewFactorUpdateThreshold', cand, 'rs'):
        break
tryset(rs, 'viewFactorUpdateThreshold', 'everyIteration', 'rs')
tryset(rs, 'viewFactorsUpdateTolerance', '0.05', 'rs')
frozen('B2_res64_tol0.05')
tryset(rs, 'viewFactorsUpdateTolerance', '-1', 'rs')
tryset(rs, 'viewFactorsUpdateTime', '20', 'rs')
frozen('B3_res64_updtime20')
tryset(rs, 'viewFactorsUpdateTime', '0', 'rs')
tryset(rs, 'viewFactorsUpdateExpression', '1', 'rs')
frozen('B4_res64_updexpr')
tryset(rs, 'viewFactorsUpdateExpression', '0', 'rs')
# fast tumbling approximation on the events timeline (averaged loads) as a reference for cost
et = otl.feature('et1')
tryset(et, 'initFastTumbling', '1', 'et1')
frozen('B5_res64_fasttumbling')
tryset(et, 'initFastTumbling', '0', 'et1')
model.save(os.path.join(S, "smoke6.mph")); print("saved", flush=True)
