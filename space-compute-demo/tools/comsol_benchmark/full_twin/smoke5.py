# -*- coding: utf-8 -*-
"""Smoke 5 (not a deliverable): where does the OTL solve time go? Toy model,
frozen study with variants; then the orbital study and variable discovery."""
import mph, time, os, sys
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
open(os.path.join(S, "smoke_power.csv"), "w").write("0 500\n300 500\n301 900\n900 900\n901 400\n2000 400\n")
client = mph.start(cores=4)
model = client.create('smoke5'); j = model.java
comp = j.component().create('comp1', True)
geom = comp.geom().create('geom1', 3); geom.lengthUnit('m')
b1 = geom.feature().create('blk1', 'Block'); b1.set('size', [0.3, 0.3, 0.3]); b1.set('base', 'center')
b3 = geom.feature().create('blk3', 'Block'); b3.set('size', [0.1, 0.1, 0.01]); b3.set('base', 'center'); b3.set('pos', [0.0, 0.0, 0.155])
b2 = geom.feature().create('blk2', 'Block'); b2.set('size', [1.0, 0.02, 2.0]); b2.set('base', 'center'); b2.set('pos', [0.0, 0.0, 1.5])
ls = geom.feature().create('ls1', 'LineSegment'); ls.set('specify1', 'coord'); ls.set('coord1', [0.0, 0.0, 0.16]); ls.set('specify2', 'coord'); ls.set('coord2', [0.0, 0.01, 0.5])
ls2 = geom.feature().create('ls2', 'LineSegment'); ls2.set('specify1', 'coord'); ls2.set('coord1', [0.0, 0.01, 0.5]); ls2.set('specify2', 'coord'); ls2.set('coord2', [0.0, 0.01, 2.4])
geom.run()
mat = comp.material().create('mat1', 'Common'); mat.selection().all()
mat.propertyGroup('def').set('thermalconductivity', ['238']); mat.propertyGroup('def').set('density', '2700'); mat.propertyGroup('def').set('heatcapacity', '900')
f = j.func().create('int1', 'Interpolation'); f.set('source', 'file'); f.set('filename', os.path.join(S, "smoke_power.csv")); f.set('nargs', '1')
f.set('interp', 'linear'); f.set('extrap', 'const'); f.set('argunit', 's'); f.set('fununit', 'W'); f.setIndex('funcs', 'Pgpu', 0, 0); f.setIndex('funcs', '1', 0, 1); f.importData()
for nm, expr in (('rx', '6800e3*cos(2*pi*t/5574)'), ('ry', '6800e3*sin(2*pi*t/5574)*cos(51.6[deg])'), ('rz', '6800e3*sin(2*pi*t/5574)*sin(51.6[deg])')):
    fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')
comp.variable().create('var_stat').set('tt', 't*1e-3')
comp.variable().create('var_trans').set('tt', 't')
ht = comp.physics().create('ht', 'HeatTransfer', 'geom1')
otl = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1')
rs = otl.prop('RadiationSettings'); rs.set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient'); rs.set('radiationMethod', 'hemicube'); rs.set('radiationResolution', '128')
op = otl.feature('op1'); op.set('orbitType', 'userDefined'); op.set('orbitDefinition', 'FromFunction')
for ax in 'XYZ':
    op.set(f'functionType_{ax}_ECS', 'userDefined'); op.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(tt)')
sup = otl.feature('sup1'); sup.set('sunDirection', 'userdef'); sup.set('SV_ECS', ['-1', '0', '0']); sup.set('solarFluxSolAmb', 'userdefBand'); sup.set('q0s_bandSolAmb', ['1361', '0'])
plp = otl.feature('plp1'); plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['0.3', '0'])
plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', '237'])
otl.feature('sa1').set('primaryAxis', 'z'); otl.feature('sa1').set('secondaryAxis', 'y')
otl.feature('so1').set('primaryOrientation', 'nadir'); otl.feature('so1').set('secondaryOrientation', 'velocity')
for feat in (otl.feature('dsurf1'),):
    feat.set('userDefinitionTypeSolAmb', 'userDefinedForEachBand'); feat.set('epsilon_radSolAmb_mat', 'userdef'); feat.set('epsilon_rad_bandSolAmb', ['0.25', '0.85']); feat.set('Tamb', '2.7[K]')
hs = ht.create('hs1', 'HeatSource', 3); hs.selection().set([2]); hs.set('heatSourceType', 'HeatRate'); hs.set('P0', 'Pgpu(tt)')
rod = ht.create('rod1', 'ThinRod', 1); rod.selection().all(); rod.set('rl', '0.00635'); rod.set('kl_mat', 'userdef'); rod.set('kl', '1.6e5')
rod.set('rhol_mat', 'userdef'); rod.set('rhol', '2700'); rod.set('Cp_l_mat', 'userdef'); rod.set('Cp_l', '900')
ht.feature('init1').set('Tinit', '300[K]')
mp = comp.multiphysics().create('htrad1', 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mp.set('Heat_physics', 'ht'); mp.set('Rad_physics', 'otl')
mesh = comp.mesh().create('mesh1'); mesh.autoMeshSize(7); mesh.run()
print("mesh:", mesh.getNumElem('tet'), "tets", mesh.getNumElem('tri'), "tris", flush=True)

def frozen_study(tag, tlist):
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_trans'])
        if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
    t0 = time.time(); st.run(); dt = time.time() - t0
    print(f"{tag} tlist={tlist} -> {dt:.1f}s", flush=True); return st

frozen_study('A1_res128_3pts', 'range(0,50,100)')
frozen_study('A2_res128_11pts', 'range(0,10,100)')
rs.set('radiationResolution', '32')
frozen_study('A3_res32_11pts', 'range(0,10,100)')
rod.active(False)
frozen_study('A4_res32_norod_11pts', 'range(0,10,100)')
rod.active(True)
rs.set('radiationResolution', '64')
frozen_study('A5_res64_long', 'range(0,2000,20000)')
# orbital study from A5
stB = j.study().create('stdB')
for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
    s = stB.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', 'range(0,60,1800)'); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_stat'])
    if typ == 'OrbitalTemperature':
        s.set('rtol', '0.005'); s.set('initmethod', 'sol'); s.set('initstudy', 'A5_res64_long'); s.set('initstudystep', 'ot'); s.set('solnum', 'last')
t0 = time.time()
try:
    stB.run(); print("STUDY B (orbital 1800 s, 31 pts) OK %.1fs" % (time.time() - t0), flush=True)
except Exception as e:
    print("STUDY B ERR", str(e).replace("\n", " ")[:800], flush=True)
dsets = [(str(d.tag()), str(d.getString('solution'))) for d in j.result().dataset()]
print("datasets:", dsets, flush=True)
dset = dsets[-1][0]
cands = ['T', 'otl.isIlluminated', 'otl.SVX_ECS', 'otl.X_ECSViz', 'otl.Trad']
for base in ('Gext', 'G', 'J', 'rflux', 'Gm', 'Gamb', 'eps', 'q', 'Gext_sun', 'Gext_planet', 'Gext_albedo', 'Gextsun', 'Gextpl', 'Gextalb', 'qext', 'Gextsol', 'Gextamb', 'epsilon_rad', 'epsilon', 'Jext', 'Gr', 'qr', 'ntflux'):
    for suf in ('', '_sol', '_amb', 'sol', 'amb', '_Bsol', '_Bamb', '_B1', '_B2', '_solar', '_ambient', 'Sol', 'Amb', '_Sol', '_Amb'):
        cands.append(f'otl.{base}{suf}')
cands += ['ht.ntflux', 'ht.rflux', 'ht.q0', 'ht.Q', 'ht.Qtot']
ok = []
for expr in cands:
    try:
        gev = j.result().numerical().create('gev', 'AvSurface'); gev.selection().all(); gev.set('expr', expr); gev.set('data', dset)
        try:
            v = gev.getReal()
            if v is not None and len(v) > 0 and len(v[0]) > 0:
                ok.append(expr); print("EVAL OK", expr, "->", str(v[-1][0])[:30], flush=True)
        except Exception:
            pass
        j.result().numerical().remove('gev')
    except Exception:
        try: j.result().numerical().remove('gev')
        except Exception: pass
print("VALID EXPRESSIONS:", ok, flush=True)
model.save(os.path.join(S, "smoke5.mph")); print("saved", flush=True)
