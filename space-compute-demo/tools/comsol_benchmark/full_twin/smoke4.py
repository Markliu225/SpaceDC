# -*- coding: utf-8 -*-
"""Smoke test 3 (not a deliverable): frozen-environment steady state (tt=0)
-> orbital transient initialised from it; then discover OTL variable names."""
import mph, time, os
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
open(os.path.join(S, "smoke_power.csv"), "w").write("0 500\n300 500\n301 900\n900 900\n901 400\n2000 400\n")
client = mph.start(cores=2)
model = client.create('smoke3'); j = model.java

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace("\n", " ")[:300]); return False

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
f.set('interp', 'linear'); f.set('extrap', 'const'); f.set('argunit', 's'); f.set('fununit', 'W')
try:
    f.setIndex('funcs', 'Pgpu', 0, 0); f.setIndex('funcs', '1', 0, 1); print('funcs table OK')
except Exception as e:
    print('funcs table FAIL', str(e).replace(chr(10),' ')[:200])
f.importData()
try: print('int1 funcs:', [str(x) for x in f.getStringMatrix('funcs')])
except Exception as e: print('getStringMatrix funcs err', str(e)[:100])
for nm, expr in (('rx', '6800e3*cos(2*pi*t/5574)'), ('ry', '6800e3*sin(2*pi*t/5574)*cos(51.6[deg])'), ('rz', '6800e3*sin(2*pi*t/5574)*sin(51.6[deg])')):
    fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')
v1 = comp.variable().create('var_stat'); v1.set('tt', 't*1e-3')
v2 = comp.variable().create('var_trans'); v2.set('tt', 't')
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
otl.feature('dsurf1').set('epsilon_rad_bandSolAmb', ['0.25', '0.10']); otl.feature('dsurf1').set('Tamb', '2.7[K]')
ds = otl.create('ds1', 'DiffuseSurface', 2); ds.selection().all(); ds.set('Tamb', '2.7[K]')
for feat in (otl.feature('dsurf1'), ds):
    for cand in ('userDefinedForEachBand', 'userDefinedEachBand', 'eachBand', 'userDefinedPerBand'):
        if tryset(feat, 'userDefinitionTypeSolAmb', cand, 'ds userDefinitionTypeSolAmb'): break
    tryset(feat, 'epsilon_radSolAmb_mat', 'userdef', 'ds'); tryset(feat, 'epsilon_radSolAmb', '0.5', 'ds')
    tryset(feat, 'epsilon_rad_bandSolAmb', ['0.25', '0.85'], 'ds per band')
hs = ht.create('hs1', 'HeatSource', 3); hs.selection().set([2]); hs.set('heatSourceType', 'HeatRate'); hs.set('P0', 'Pgpu(tt)')
tl = ht.create('tl1', 'SolidLayeredShell', 2); tl.set('LayerType', 'Resistive'); tl.set('ThermalResistanceType', 'ThermalResistance'); tl.set('R_s', '6e-6')
# interior boundary between blk1 and blk3: pick by coordinates
tl.selection().set([])
rod = ht.create('rod1', 'ThinRod', 1); rod.selection().all(); rod.set('rl', '0.00635'); rod.set('kl_mat', 'userdef'); rod.set('kl', '1.6e5')
rod.set('rhol_mat', 'userdef'); rod.set('rhol', '2700'); rod.set('Cp_l_mat', 'userdef'); rod.set('Cp_l', '900')
ht.feature('init1').set('Tinit', '300[K]')
mp = comp.multiphysics().create('htrad1', 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mp.set('Heat_physics', 'ht'); mp.set('Rad_physics', 'otl')
plate = comp.selection().create('sel_plate', 'Box'); plate.set('entitydim', '3'); plate.set('condition', 'inside')
plate.set('xmin', -0.6); plate.set('xmax', 0.6); plate.set('ymin', -0.05); plate.set('ymax', 0.05); plate.set('zmin', 0.4); plate.set('zmax', 2.6)
mesh = comp.mesh().create('mesh1'); mesh.feature('size').set('hauto', '7')
szp = mesh.create('size_plate', 'Size'); szp.selection().geom('geom1', 3); szp.selection().named('sel_plate'); szp.set('custom', True); szp.set('hmaxactive', True); szp.set('hmax', '0.15')
swe = mesh.create('swe1', 'Sweep'); swe.selection().geom('geom1', 3); swe.selection().named('sel_plate'); dis = swe.create('dis1', 'Distribution'); dis.set('numelem', '1')
ftet = mesh.create('ftet1', 'FreeTet'); ftet.selection().geom('geom1', 3); ftet.selection().remaining()
try:
    mesh.run(); print('MESH OK (sweep+tet)')
except Exception as e:
    print('MESH ERR', str(e).replace(chr(10), ' ')[:500]); mesh.feature().clear(); mesh.autoMeshSize(7); mesh.run(); print('fallback auto mesh')
# ---- study A: frozen environment to steady state
stdA = j.study().create('stdA')
a0 = stdA.create('otl', 'OrbitThermalLoads'); a0.set('timestepspec', 'timesteps'); a0.set('tlist', 'range(0,10,100)'); a0.set('useadvanceddisable', True); a0.set('disabledvariables', ['var_trans'])
a1 = stdA.create('ot', 'OrbitalTemperature'); a1.set('timestepspec', 'timesteps'); a1.set('tlist', 'range(0,10,100)'); a1.set('rtol', '0.005'); a1.set('useadvanceddisable', True); a1.set('disabledvariables', ['var_trans'])
t0 = time.time()
try:
    stdA.run(); print("STUDY A (frozen) OK %.1fs" % (time.time() - t0))
except Exception as e:
    print("STUDY A ERR", str(e).replace("\n", " ")[:900])
# ---- study B: orbital transient from A's last solution
stdB = j.study().create('stdB')
b0 = stdB.create('otl', 'OrbitThermalLoads'); b0.set('timestepspec', 'timesteps'); b0.set('tlist', 'range(0,10,200)'); b0.set('useadvanceddisable', True); b0.set('disabledvariables', ['var_stat'])
b1s = stdB.create('ot', 'OrbitalTemperature'); b1s.set('timestepspec', 'timesteps'); b1s.set('tlist', 'range(0,10,200)'); b1s.set('rtol', '0.005'); b1s.set('useadvanceddisable', True); b1s.set('disabledvariables', ['var_stat'])
tryset(b1s, 'initmethod', 'sol', 'B.ot'); tryset(b1s, 'initstudy', 'stdA', 'B.ot'); tryset(b1s, 'initstudystep', 'ot', 'B.ot')
for k, v in (('solnum', 'last'), ('initsolusesolnum', 'last'), ('initsol', 'last')):
    tryset(b1s, k, v, 'B.ot')
try:
    print("B.ot props:", [p for p in list(b1s.properties()) if 'sol' in p.lower() or 'init' in p.lower()])
except Exception as e: print("props err", e)
t0 = time.time()
try:
    stdB.run(); print("STUDY B (orbital) OK %.1fs" % (time.time() - t0))
except Exception as e:
    print("STUDY B ERR", str(e).replace("\n", " ")[:900])
# ---- datasets & variable discovery
try:
    print("datasets:", [(str(d.tag()), str(d.getType())) for d in j.result().dataset()])
except Exception as e: print("dataset list err", e)
dsets = [str(d.tag()) for d in j.result().dataset()]
dset = dsets[-1]
cands = ['T', 'otl.isIlluminated', 'otl.SVX_ECS', 'otl.X_ECSViz', 'otl.Trad']
for base in ('Gext', 'G', 'J', 'rflux', 'Gm', 'Gamb', 'eps', 'q', 'Gext_sun', 'Gext_planet', 'Gext_albedo', 'Gextsun', 'Gextpl', 'Gextalb', 'Gext_s', 'Gext_p', 'Gext_a', 'qext', 'Gextsol', 'Gextamb', 'ntflux'):
    for suf in ('', '_sol', '_amb', 'sol', 'amb', '_Bsol', '_Bamb', '_B1', '_B2', '_solar', '_ambient'):
        cands.append(f'otl.{base}{suf}')
cands += ['ht.ntflux', 'ht.rflux', 'ht.q0']
ok = []
for expr in cands:
    try:
        gev = j.result().numerical().create('gev', 'AvSurface'); gev.selection().all(); gev.set('expr', expr); gev.set('data', dset)
        try:
            v = gev.getReal(); s = str(v.tolist() if hasattr(v, 'tolist') else v)[:50]
            if v is not None and len(v) > 0 and len(v[0]) > 0:
                ok.append(expr); print("EVAL OK", expr, "->", s)
        except Exception as e:
            pass
        j.result().numerical().remove('gev')
    except Exception as e:
        try: j.result().numerical().remove('gev')
        except Exception: pass
print("VALID EXPRESSIONS:", ok)
model.save(os.path.join(S, "smoke4.mph")); print("saved")
