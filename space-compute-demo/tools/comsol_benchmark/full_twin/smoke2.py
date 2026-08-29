# -*- coding: utf-8 -*-
"""COMSOL API discovery smoke test (not a deliverable). Learns the Orbital
Thermal Loads / Heat Transfer property names needed by build_comsol.py and
verifies that a Stationary + Orbital Temperature study actually solves on a
toy geometry (two blocks + a plate + free-standing heat-pipe edges)."""
import mph, time, os, sys
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
open(os.path.join(S, "smoke_power.csv"), "w").write("0 500\n300 500\n301 900\n900 900\n901 400\n2000 400\n")
client = mph.start(cores=2)

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val)
        return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace("\n", " ")[:300]); return False

def props(obj, label):
    try:
        names = list(obj.properties()); print("PROPS", label, names)
    except Exception as e:
        print("PROPS", label, "ERR", str(e)[:100])

# ---- 0. learn OTL variable names / interface props from the shipped example
try:
    ex = client.load(r"D:\Program Files\COMSOL\COMSOL63\Multiphysics\applications\Heat_Transfer_Module\Orbital_Thermal_Loads\spacecraft_thermal_analysis.mph")
    print("=== example plot/eval expressions ===")
    def walk(node, depth=0):
        try:
            p = node.properties()
            for k in ('expr', 'expry', 'exprx', 'descr'):
                if k in p:
                    print("  " * depth + f"{node.name()} [{node.type()}] .{k} = {str(p[k])[:150]}")
        except Exception:
            pass
        for c in node.children():
            walk(c, depth + 1)
    for top in ('plots', 'evaluations', 'tables'):
        try: walk(ex / top)
        except Exception as e: print(top, 'ERR', e)
    otlx = ex.java.component('comp1').physics('otl')
    for grp in ['RadiationSettings', 'ShapeProperty']:
        try:
            pg = otlx.prop(grp); names = list(pg.properties()); print("EXAMPLE otl.prop", grp, names)
            for nme in names:
                try: print("      ", nme, "=", str(pg.getString(nme))[:100])
                except Exception: print("      ", nme, "(get err)")
        except Exception as e:
            print("EXAMPLE otl.prop", grp, "ERR", str(e)[:80])
    for st in ('otl', 'ot'):
        stp = ex.java.study('std1').feature(st)
        for k in ('timestepspec', 'tlist', 'tunit', 'rtol', 'initmethod', 'initstudy', 'initstudystep', 'useinitsol'):
            try: print(f"EXAMPLE std1/{st}.{k} =", str(stp.getString(k))[:100])
            except Exception: print(f"EXAMPLE std1/{st}.{k} ERR")
    client.remove(ex)
except Exception as e:
    print("example load ERR", e)

# ---- 1. toy model
model = client.create('smoke2'); j = model.java
comp = j.component().create('comp1', True)
geom = comp.geom().create('geom1', 3); geom.lengthUnit('m')
b1 = geom.feature().create('blk1', 'Block'); b1.set('size', [0.3, 0.3, 0.3]); b1.set('base', 'center')
b3 = geom.feature().create('blk3', 'Block'); b3.set('size', [0.1, 0.1, 0.01]); b3.set('base', 'center'); b3.set('pos', [0.0, 0.0, 0.155])
b2 = geom.feature().create('blk2', 'Block'); b2.set('size', [1.0, 0.02, 2.0]); b2.set('base', 'center'); b2.set('pos', [0.0, 0.0, 1.5])
ls = geom.feature().create('ls1', 'LineSegment'); ls.set('specify1', 'coord'); ls.set('coord1', [0.0, 0.0, 0.16]); ls.set('specify2', 'coord'); ls.set('coord2', [0.0, 0.01, 0.5])
ls2 = geom.feature().create('ls2', 'LineSegment'); ls2.set('specify1', 'coord'); ls2.set('coord1', [0.0, 0.01, 0.5]); ls2.set('specify2', 'coord'); ls2.set('coord2', [0.0, 0.01, 2.4])
geom.run()
print("geom: domains", geom.getNDomains(), "boundaries", geom.getNBoundaries(), "edges", geom.getNEdges())
mat = comp.material().create('mat1', 'Common'); mat.selection().all()
mat.propertyGroup('def').set('thermalconductivity', ['238']); mat.propertyGroup('def').set('density', '2700'); mat.propertyGroup('def').set('heatcapacity', '900')
f = j.func().create('int1', 'Interpolation'); f.set('source', 'file'); f.set('filename', os.path.join(S, "smoke_power.csv")); f.set('nargs', '1')
f.set('funcname', 'Pgpu'); f.set('interp', 'linear'); f.set('extrap', 'const'); f.set('argunit', 's'); f.set('fununit', 'W')
try: f.importData(); print("interp import OK")
except Exception as e: print("interp import ERR", str(e)[:200])
for nm, expr in (('rx', '6800e3*cos(2*pi*t/5574)'), ('ry', '6800e3*sin(2*pi*t/5574)*cos(51.6[deg])'), ('rz', '6800e3*sin(2*pi*t/5574)*sin(51.6[deg])')):
    fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')
v1 = comp.variable().create('var_stat'); v1.set('tt', '0[s]'); v1.label('tt frozen (stationary)')
v2 = comp.variable().create('var_trans'); v2.set('tt', 't'); v2.label('tt = t (transient)')
ht = comp.physics().create('ht', 'HeatTransfer', 'geom1')
otl = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1')
for grp in ['RadiationSettings', 'ShapeProperty']:
    try:
        pg = otl.prop(grp); names = list(pg.properties()); print("otl.prop", grp, names)
        for nme in names:
            try: print("      ", nme, "=", str(pg.getString(nme))[:100])
            except Exception: print("      ", nme, "(get err)")
    except Exception as e:
        print("otl.prop", grp, "ERR", str(e)[:80])
rs = otl.prop('RadiationSettings')
for cand in ('wavelengthDependenceOfSurfaceProperties',):
    if tryset(rs, cand, 'SolarAndAmbient', 'otl.RS'): break
tryset(rs, 'radiationMethod', 'hemicube', 'otl.RS')
for cand in ('radiationResolution',):
    if tryset(rs, cand, '128', 'otl.RS'): break
op = otl.feature('op1'); op.set('orbitType', 'userDefined'); op.set('orbitDefinition', 'FromFunction')
for ax in 'XYZ':
    op.set(f'functionType_{ax}_ECS', 'userDefined'); op.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(tt)')
sup = otl.feature('sup1'); sup.set('sunDirection', 'userdef'); sup.set('q0s_src', 'userdef'); sup.set('q0s', '1361')
tryset(sup, 'SV_ECS', ['-1', '0', '0'], 'sup1')

tryset(sup, 'solarFluxSolAmb', 'userdefBand', 'sup1'); tryset(sup, 'q0s_bandSolAmb', ['1361', '0'], 'sup1')
plp = otl.feature('plp1'); plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['0.3', '0'])
plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', '237'])
otl.feature('sa1').set('primaryAxis', 'z'); otl.feature('sa1').set('secondaryAxis', 'y')
otl.feature('so1').set('primaryOrientation', 'nadir'); otl.feature('so1').set('secondaryOrientation', 'velocity')
print('otl features:', [(str(f.tag()), str(f.getType())) for f in otl.feature()])
for f_ in otl.feature():
    if str(f_.getType()) == 'DiffuseSurface':
        tryset(f_, 'epsilon_rad_bandSolAmb', ['0.25', '0.10'], 'default ' + str(f_.tag())); tryset(f_, 'Tamb', '2.7[K]', 'default ds')
ds = otl.create('ds1', 'DiffuseSurface', 2); ds.selection().all(); props(ds, 'ds1')
tryset(ds, 'epsilon_rad_bandSolAmb', ['0.25', '0.85'], 'ds1'); tryset(ds, 'Tamb', '2.7[K]', 'ds1')
tryset(ds, 'defineSurfaceEmissivityOnEachSide', '1', 'ds1'); tryset(ds, 'epsilon_radu_bandSolAmb', ['0.6', '0.85'], 'ds1'); tryset(ds, 'epsilon_radd_bandSolAmb', ['0.8', '0.85'], 'ds1')
tryset(ds, 'defineSurfaceEmissivityOnEachSide', '0', 'ds1')
hs = ht.create('hs1', 'HeatSource', 3); hs.selection().set([2]); hs.set('heatSourceType', 'HeatRate'); hs.set('P0', 'Pgpu(tt)')
tl = ht.create('tl1', 'SolidLayeredShell', 2); props(tl, 'tl1')
for cand in ('Resistive', 'ThermallyThin', 'General', 'ThermallyThick'):
    tryset(tl, 'LayerType', cand, 'tl1')
for cand in ('ThermalResistance', 'LayerProperties', 'UserDefined', 'Resistance'):
    tryset(tl, 'ThermalResistanceType', cand, 'tl1')
tryset(tl, 'R_s', '7e-6', 'tl1'); tryset(tl, 'lth', '2.5e-4', 'tl1'); tryset(tl, 'k_mat', 'userdef', 'tl1'); tryset(tl, 'k', ['35.7'], 'tl1')
rod = ht.create('rod1', 'ThinRod', 1); rod.selection().all(); props(rod, 'rod1')
tryset(rod, 'rl', '0.00635', 'rod1'); tryset(rod, 'kl_mat', 'userdef', 'rod1'); tryset(rod, 'kl', '1.6e5', 'rod1')
tryset(rod, 'rhol_mat', 'userdef', 'rod1'); tryset(rod, 'rhol', '2700', 'rod1'); tryset(rod, 'Cp_l_mat', 'userdef', 'rod1'); tryset(rod, 'Cp_l', '900', 'rod1')
ht.feature('init1').set('Tinit', '300[K]')
mp = None
for ed in (2, 1, 0):
    try:
        mp = comp.multiphysics().create('htrad1', 'HeatTransferWithSurfaceToSurfaceRadiation', ed); print('multiphysics created at edim', ed); break
    except Exception as e:
        print('multiphysics edim', ed, 'FAIL', str(e).replace(chr(10),' ')[:120])
tryset(mp, 'Heat_physics', 'ht', 'mp'); tryset(mp, 'Rad_physics', 'otl', 'mp')
mesh = comp.mesh().create('mesh1'); mesh.autoMeshSize(7); t0 = time.time(); mesh.run(); print("mesh OK %.1fs" % (time.time() - t0))
try:
    st = mesh.getStat() if hasattr(mesh, 'getStat') else None
except Exception: pass
std = j.study().create('std1')
s0 = std.create('otlstep', 'OrbitThermalLoads'); tryset(s0, 'timestepspec', 'timesteps', 'otlstep'); tryset(s0, 'tlist', 'range(0,60,1200)', 'otlstep')
for fmt in (['var_trans'], ['comp1.var_trans']):
    if tryset(s0, 'disabledvariables', fmt, 'otlstep'): break
s1 = std.create('stat', 'Stationary'); props(s1, 'stat')
for fmt in (['var_trans'], ['comp1.var_trans']):
    if tryset(s1, 'disabledvariables', fmt, 'stat'): break
s2 = std.create('ot', 'OrbitalTemperature'); props(s2, 'ot')
for cand in ('timesteps', 'timeSteps', 'tlist', 'manual', 'time'):
    if tryset(s2, 'timestepspec', cand, 'ot'): break
tryset(s2, 'tlist', 'range(0,60,1200)', 'ot'); tryset(s2, 'tunit', 's', 'ot'); tryset(s2, 'rtol', '0.005', 'ot')
tryset(s2, 'initmethod', 'sol', 'ot'); tryset(s2, 'initstudy', 'std1', 'ot'); tryset(s2, 'initstudystep', 'stat', 'ot')
for fmt in (['var_stat'], ['comp1.var_stat']):
    if tryset(s2, 'disabledvariables', fmt, 'ot'): break
t0 = time.time()
try:
    std.run(); print("STUDY RUN OK %.1fs" % (time.time() - t0))
except Exception as e:
    print("STUDY RUN ERR", str(e).replace("\n", " ")[:800])
    try:
        std2 = j.study().create('std2'); s3 = std2.create('ot2', 'OrbitalTemperature'); s3.set('timestepspec', 'timesteps'); s3.set('tlist', 'range(0,60,1200)')
        t0 = time.time(); std2.run(); print("STUDY2 (no stationary) RUN OK %.1fs" % (time.time() - t0))
    except Exception as e2:
        print("STUDY2 ERR", str(e2).replace("\n", " ")[:800])
for expr in ('T', 'otl.isIlluminated', 'otl.Gext', 'otl.Gexts', 'otl.Gext_s', 'otl.G', 'otl.J', 'otl.rflux', 'otl.q_s', 'otl.Gext_amb', 'otl.Gext_sol', 'ht.ntflux', 'otl.eclipse', 'otl.ecl', 'otl.Fs', 'otl.Fp', 'otl.qsun', 'otl.qalb', 'otl.qpl', 'otl.Gextsun', 'otl.Gextalb', 'otl.Gextpl', 'otl.Gext_sun', 'otl.Gext_alb', 'otl.Gext_pl'):
    try:
        gev = j.result().numerical().create('gev', 'AvSurface'); gev.selection().all(); gev.set('expr', expr); gev.set('data', 'dset1')
        try:
            v = gev.getReal(); print("EVAL OK", expr, "->", str(v)[:60])
        except Exception as e:
            print("EVAL FAIL", expr, str(e).replace("\n", " ")[:120])
        j.result().numerical().remove('gev')
    except Exception as e:
        print("EVAL create FAIL", expr, str(e)[:80])
model.save(os.path.join(S, "smoke2.mph")); print("saved")
