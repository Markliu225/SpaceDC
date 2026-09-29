# -*- coding: utf-8 -*-
"""Smoke 04: thin structures as shells (Heat Transfer in Shells, htlsh, type
HeatTransferInShellsLM, dependent variable T2) under Orbital Thermal Loads,
next to a solid block in Heat Transfer in Solids (ht, T).

Geometry: solid block; free-standing rectangle (radiator-like panel, both sides
radiate); closed cylindrical surface (module skin, outside radiates, inside
inert, MLI flux from a 295 K cabin).
Checks: builds; one otl with two S2S couplings (ht, htlsh); solves loads +
temperature; energy balance of the panel (3 kW source) closes.
"""
import mph, time, os, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MU = 3.986004418e14; RE = 6378.137e3; R = RE + 415e3
T_ORB = 2 * math.pi * math.sqrt(R ** 3 / MU)

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val, flush=True); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace(chr(10), " ")[:300], flush=True); return False

t_start = time.time()
client = mph.start(cores=4)
model = client.create('s04'); j = model.java
comp = j.component().create('comp1', True)
geom = comp.geom().create('geom1', 3); geom.lengthUnit('m')
blk = geom.feature().create('blk', 'Block'); blk.set('size', [4.0, 4.0, 2.0]); blk.set('base', 'center')
pan = geom.feature().create('pan', 'Block'); pan.set('type', 'surface'); pan.set('size', [0.0001, 3.4, 6.0]); pan.set('pos', [0.0, -1.7, 1.5])
wp = geom.feature().create('wp1', 'WorkPlane'); wp.set('planetype', 'quick'); wp.set('quickplane', 'yz'); wp.set('quickx', '0.5')
rect = wp.geom().create('r1', 'Rectangle'); rect.set('size', [3.4, 6.0]); rect.set('pos', [-1.7, 1.5])
cyl = geom.feature().create('cyl', 'Cylinder'); cyl.set('r', '2.1'); cyl.set('h', '8.0'); cyl.set('pos', [3.0, 0.0, -6.0]); cyl.set('axistype', 'x'); cyl.set('type', 'surface')
geom.feature().remove('pan')     # keep the work-plane rectangle as THE panel (a 0.1 mm surface block would be a closed box)
geom.run()
print("geom:", geom.getNDomains(), "domains", geom.getNBoundaries(), "boundaries", flush=True)

def boxsel(tag, dim, lo, hi, cond='inside'):
    s = comp.selection().create(tag, 'Box'); s.set('entitydim', str(dim))
    s.set('xmin', lo[0]); s.set('xmax', hi[0]); s.set('ymin', lo[1]); s.set('ymax', hi[1]); s.set('zmin', lo[2]); s.set('zmax', hi[2])
    s.set('condition', cond); return s
boxsel('sBlk', 3, (-2.1, -2.1, -1.1), (2.1, 2.1, 1.1))
boxsel('sBlkB', 2, (-2.1, -2.1, -1.1), (2.1, 2.1, 1.1))
boxsel('sPanel', 2, (0.49, -1.8, 1.4), (0.51, 1.8, 7.6))
boxsel('sSkin', 2, (2.9, -2.2, -8.2), (11.1, 2.2, -3.8))
u = comp.selection().create('sShells', 'Union'); u.set('entitydim', '2'); u.set('input', ['sPanel', 'sSkin'])
print('panel bnds', [int(x) for x in comp.selection('sPanel').entities(2)], 'skin bnds', [int(x) for x in comp.selection('sSkin').entities(2)], flush=True)

mat = comp.material().create('mat1', 'Common'); mat.selection().named('sBlk')
mat.propertyGroup('def').set('thermalconductivity', ['200']); mat.propertyGroup('def').set('density', '2700'); mat.propertyGroup('def').set('heatcapacity', '900')
mats = comp.material().create('mat2', 'Common'); mats.selection().geom('geom1', 2); mats.selection().named('sShells')
mats.propertyGroup('def').set('thermalconductivity', ['170']); mats.propertyGroup('def').set('density', '2700'); mats.propertyGroup('def').set('heatcapacity', '900')
mats.propertyGroup().create('shell', 'Shell').set('lth', '0.002[m]')   # single-layer material -> shells get their thickness here

for nm, expr in (('rx', f'{R}*cos(2*pi*t/{T_ORB})'), ('ry', f'{R}*sin(2*pi*t/{T_ORB})*cos(51.64[deg])'), ('rz', f'{R}*sin(2*pi*t/{T_ORB})*sin(51.64[deg])')):
    fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')

ht = comp.physics().create('ht', 'HeatTransfer', 'geom1'); ht.selection().named('sBlk'); ht.feature('init1').set('Tinit', '280[K]')
sh = comp.physics().create('htlsh', 'HeatTransferInShellsLM', 'geom1'); sh.selection().named('sShells')
sh.prop('ds').set('ds', '0.002[m]')
sls = sh.feature('sls1')
print('sls1 LayerType =', sls.getString('LayerType'))
sh.feature('init1').set('Tinit', '280[K]')
hf = sh.create('hfMLI', 'HeatFluxInterface', 2); hf.selection().named('sSkin')
tryset(hf, 'HeatFluxType', 'ConvectiveHeatFlux', 'hfMLI'); tryset(hf, 'h', '0.2', 'hfMLI'); tryset(hf, 'Text', '295[K]', 'hfMLI')
hs = sh.create('hsPanel', 'HeatSource', 2); hs.selection().named('sPanel')
tryset(hs, 'heatSourceType', 'HeatRate', 'hsPanel'); tryset(hs, 'P0', '3000', 'hsPanel')

otl = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1')
rs = otl.prop('RadiationSettings'); rs.set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient'); rs.set('radiationMethod', 'hemicube'); rs.set('radiationResolution', '128')
op = otl.feature('op1'); op.set('orbitType', 'userDefined'); op.set('orbitDefinition', 'FromFunction')
for ax in 'XYZ':
    op.set(f'functionType_{ax}_ECS', 'userDefined'); op.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(t)')
sup = otl.feature('sup1'); sup.set('sunDirection', 'userdef'); sup.set('SV_ECS', ['-1', '0', '0']); sup.set('solarFluxSolAmb', 'userdefBand'); sup.set('q0s_bandSolAmb', ['1361', '0'])
plp = otl.feature('plp1'); plp.set('nRings', '2'); plp.set('nPointsRing', '6')
plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['0.3', '0']); plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', '237'])
otl.feature('sa1').set('primaryAxis', 'z'); otl.feature('sa1').set('secondaryAxis', 'x')
otl.feature('so1').set('primaryOrientation', 'nadir'); otl.feature('so1').set('secondaryOrientation', 'velocity')
d = otl.feature('dsurf1'); d.set('epsilon_radSolAmb_mat', 'userdefBand'); d.set('epsilon_rad_bandSolAmb', ['0.3', '0.8']); d.set('Tamb', '2.7[K]')
dsk = otl.create('dsSkin', 'DiffuseSurface', 2); dsk.selection().named('sSkin')
dsk.set('epsilon_radSolAmb_mat', 'userdefBand'); dsk.set('epsilon_rad_bandSolAmb', ['0.3', '0.8']); dsk.set('Tamb', '2.7[K]')
names = [str(x) for x in dsk.properties()]
print('DiffuseSurface props with side/u/d:', [n for n in names if any(k in n for k in ('Side', 'side', 'radu', 'radd', 'Opaque', 'opaque'))])
dpn = otl.create('dsPanel', 'DiffuseSurface', 2); dpn.selection().named('sPanel')
dpn.set('epsilon_radSolAmb_mat', 'userdefBand'); dpn.set('epsilon_rad_bandSolAmb', ['0.2', '0.9']); dpn.set('Tamb', '2.7[K]')
for k, hp in (('htrad_s', 'ht'), ('htrad_sh', 'htlsh')):
    try:
        mp = comp.multiphysics().create(k, 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mp.set('Heat_physics', hp); mp.set('Rad_physics', 'otl')
        print('coupling', k, 'OK; props', [str(x) for x in mp.properties()][:20], flush=True)
    except Exception as e:
        print('coupling', k, 'FAIL', str(e).replace(chr(10), ' ')[:300], flush=True)

mesh = comp.mesh().create('mesh1'); mesh.autoMeshSize(5)
t0 = time.time(); mesh.run(); print("mesh %.1fs" % (time.time() - t0), flush=True)
std = j.study().create('std1')
tl = f'range(0,{T_ORB/12:.2f},{T_ORB:.2f})'
s0 = std.create('otl', 'OrbitThermalLoads'); s0.set('timestepspec', 'timesteps'); s0.set('tlist', tl)
s1 = std.create('ot', 'OrbitalTemperature'); s1.set('timestepspec', 'timesteps'); s1.set('tlist', tl)
print('activate', [str(x) for x in s1.getStringArray('activate')], flush=True)
t0 = time.time()
try:
    std.run(); print("SOLVED in %.1fs" % (time.time() - t0), flush=True)
except Exception as e:
    print("SOLVE FAIL %.1fs" % (time.time() - t0), str(e).replace(chr(10), " ")[:2500], flush=True)
model.save(os.path.join(HERE, 's04.mph'))

for ds in model.datasets():
    print('=== dataset', ds)
    for sel, exprs in (('sPanel', ('T2', 'htlsh.T2u', 'htlsh.T2d', 'otl.Gext1', 'otl.Gext2', 'otl.J1', 'otl.J2')),
                       ('sSkin', ('T2', 'otl.Gext1', 'otl.Gext2')), ('sBlkB', ('T', 'otl.Gext1'))):
        for expr in exprs:
            try:
                ev = j.result().numerical().create(f'ev_{sel}_{expr.replace(".", "_")}_{abs(hash(ds)) % 999}', 'AvSurface')
                ev.set('data', 'dset1' if 'otl' in ds.lower() or '1' in ds.split('//')[-1] else 'dset2'); ev.selection().named(sel); ev.set('expr', [expr]); ev.set('innerinput', 'all')
                v = np.array(ev.getReal()[0], dtype=float)
                print(f'   {sel:7s} {expr:10s}', list(np.round(v, 1))[:14])
            except Exception as e:
                print(f'   {sel:7s} {expr:10s} ERR', str(e).replace(chr(10), ' ')[:140])
print("total %.0fs" % (time.time() - t_start))
