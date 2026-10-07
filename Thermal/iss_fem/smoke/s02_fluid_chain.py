# -*- coding: utf-8 -*-
"""Smoke 02: ammonia flow path as a chain of Global Equations coupled to FE panels.

One EATCS-like radiator (8 panels in series along its 23.3 m length, 3.4 m wide,
equivalent-thickness solid) hanging nadir from a small box. Fluid node i is the
outlet temperature of panel i; the panel receives a volumetric exchange source
    q''' = g/t_m * (Tf_mean_i - T),  Tf_mean_i = (T_{i-1} + T_i)/2
and the chain closes with  mcp*(T_{i-1} - T_i) = intop_i(q''').
Checks: (1) the study solves with ht + otl + ge, (2) energy closure
sum(Q_i) = mcp*(T_in - T_8), (3) cost relative to a plain model.
"""
import mph, time, os

HERE = os.path.dirname(os.path.abspath(__file__))
T_ORB = 5554.0
R = 6778e3
NP = 8
L, W, TM = 23.3, 3.4, 0.02          # m; TM = model thickness

t_start = time.time()
client = mph.start(cores=4)
model = client.create('s02'); j = model.java
comp = j.component().create('comp1', True)
geom = comp.geom().create('geom1', 3); geom.lengthUnit('m')
b = geom.feature().create('truss', 'Block'); b.set('size', [4.0, 4.0, 2.0]); b.set('base', 'center'); b.set('pos', [0.0, 0.0, 0.0])
lp = L / NP
for i in range(NP):
    # panels hang toward +Z (nadir) below the truss with a 0.5 m gap, plane = Y-Z, normal = +/-X
    f = geom.feature().create(f'pan{i+1}', 'Block'); f.set('base', 'corner')
    f.set('pos', [-TM / 2, -W / 2, 1.5 + i * lp]); f.set('size', [TM, W, lp])
geom.run()
print("geom:", geom.getNDomains(), "domains", geom.getNBoundaries(), "boundaries", flush=True)

def boxsel(tag, dim, lo, hi, cond='inside'):
    s = comp.selection().create(tag, 'Box'); s.set('entitydim', str(dim))
    s.set('xmin', lo[0]); s.set('xmax', hi[0]); s.set('ymin', lo[1]); s.set('ymax', hi[1]); s.set('zmin', lo[2]); s.set('zmax', hi[2])
    s.set('condition', cond); return s
e = 1e-3
for i in range(NP):
    boxsel(f'selP{i+1}', 3, (-TM, -W / 2 - e, 1.5 + i * lp - e), (TM, W / 2 + e, 1.5 + (i + 1) * lp + e))
boxsel('selRad', 3, (-TM, -W / 2 - e, 1.5 - e), (TM, W / 2 + e, 1.5 + L + e))

j.param().set('mcp', '0.144*1.033[kg/s]*4700[J/(kg*K)]', 'radiator share of loop-A flow x cp (14.4 % at 35 kW)')
j.param().set('T_in', '283.15[K]', 'radiator inlet')
j.param().set('g_ex', '60[W/(m^2*K)]', 'fluid-to-panel conductance per unit panel area (placeholder)')
j.param().set('t_m', f'{TM}[m]')

mat = comp.material().create('mat1', 'Common'); mat.selection().all()
mat.propertyGroup('def').set('thermalconductivity', ['200']); mat.propertyGroup('def').set('density', '2700'); mat.propertyGroup('def').set('heatcapacity', '900')

for nm, expr in (('rx', f'{R}*cos(2*pi*t/{T_ORB})'), ('ry', f'{R}*sin(2*pi*t/{T_ORB})'), ('rz', '0')):
    fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')

# integration operators, one per panel
for i in range(NP):
    op = comp.cpl().create(f'intP{i+1}', 'Integration'); op.selection().named(f'selP{i+1}'); op.set('opname', f'intP{i+1}')

ht = comp.physics().create('ht', 'HeatTransfer', 'geom1'); ht.feature('init1').set('Tinit', '270[K]')
for i in range(NP):
    Tup = 'T_in' if i == 0 else f'Tf{i}'
    hs = ht.create(f'hsP{i+1}', 'HeatSource', 3); hs.selection().named(f'selP{i+1}')
    hs.set('Q0', f'g_ex/t_m*(0.5*({Tup}+Tf{i+1})-T)')

ge = comp.physics().create('ge', 'GlobalEquations')
g1 = ge.feature('ge1')
for i in range(NP):
    Tup = 'T_in' if i == 0 else f'Tf{i}'
    g1.setIndex('name', f'Tf{i+1}', i)
    g1.setIndex('equation', f'mcp*({Tup}-Tf{i+1})-intP{i+1}(g_ex/t_m*(0.5*({Tup}+Tf{i+1})-T))', i)
    g1.setIndex('initialValueU', '270[K]', i)
    g1.setIndex('initialValueUt', '0', i)
    g1.setIndex('description', f'NH3 outlet T of panel {i+1}', i)
for k in ('DependentVariableQuantity', 'SourceTermQuantity'):
    try: print(k, '=', g1.getString(k))
    except Exception as ex: print(k, 'n/a', str(ex)[:80])
try:
    g1.set('DependentVariableQuantity', 'temperature'); g1.set('SourceTermQuantity', 'power'); print('ge units set')
except Exception as ex:
    print('ge unit set FAIL', str(ex)[:200])

otl = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1')
rs = otl.prop('RadiationSettings'); rs.set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient'); rs.set('radiationMethod', 'hemicube'); rs.set('radiationResolution', '128')
opf = otl.feature('op1'); opf.set('orbitType', 'userDefined'); opf.set('orbitDefinition', 'FromFunction')
for ax in 'XYZ':
    opf.set(f'functionType_{ax}_ECS', 'userDefined'); opf.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(t)')
sup = otl.feature('sup1'); sup.set('sunDirection', 'userdef'); sup.set('SV_ECS', ['-1', '0', '0'])
sup.set('solarFluxSolAmb', 'userdefBand'); sup.set('q0s_bandSolAmb', ['1361', '0'])
plp = otl.feature('plp1'); plp.set('nRings', '2'); plp.set('nPointsRing', '6')
plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['0.3', '0'])
plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', '237'])
otl.feature('sa1').set('primaryAxis', 'z'); otl.feature('sa1').set('secondaryAxis', 'x')
otl.feature('so1').set('primaryOrientation', 'nadir'); otl.feature('so1').set('secondaryOrientation', 'velocity')
d = otl.feature('dsurf1'); d.set('epsilon_radSolAmb_mat', 'userdefBand'); d.set('epsilon_rad_bandSolAmb', ['0.2', '0.9']); d.set('Tamb', '2.7[K]')
mp = comp.multiphysics().create('htrad1', 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mp.set('Heat_physics', 'ht'); mp.set('Rad_physics', 'otl')

mesh = comp.mesh().create('mesh1')
mesh.feature('size').set('custom', True); mesh.feature('size').set('hmax', '0.8'); mesh.feature('size').set('hmin', '0.02')
src = boxsel('selSrc', 2, (TM / 2 - e, -W / 2 - e, 1.5 - e), (TM / 2 + e, W / 2 + e, 1.5 + L + e))
ft = mesh.create('ftri', 'FreeTri'); ft.selection().geom('geom1', 2); ft.selection().named('selSrc')
sw = mesh.create('swe', 'Sweep'); sw.selection().geom('geom1', 3); sw.selection().named('selRad'); sw.create('dis', 'Distribution').set('numelem', '1')
tet = mesh.create('ftet', 'FreeTet'); tet.selection().geom('geom1', 3); tet.selection().remaining()
t0 = time.time(); mesh.run(); print("mesh %.1fs" % (time.time() - t0), flush=True)

std = j.study().create('std1')
s0 = std.create('otl', 'OrbitThermalLoads'); s0.set('timestepspec', 'timesteps'); s0.set('tlist', 'range(0,600,5400)')
s1 = std.create('ot', 'OrbitalTemperature'); s1.set('timestepspec', 'timesteps'); s1.set('tlist', 'range(0,600,5400)')
for stp in (s0, s1):
    try: print(stp.tag(), 'activate list:', [str(x) for x in stp.getStringArray('activate')])
    except Exception as ex: print('activate n/a', str(ex)[:100])
t0 = time.time()
try:
    std.run(); print("SOLVED in %.1fs" % (time.time() - t0), flush=True)
except Exception as ex:
    print("SOLVE FAIL %.1fs" % (time.time() - t0), str(ex).replace("\n", " ")[:2000], flush=True)

for ds in j.result().dataset():
    tagd = str(ds.tag())
    try:
        ev = j.result().numerical().create('gv_' + tagd, 'Global'); ev.set('data', tagd)
        exprs = ['T_in-273.15'] + [f'Tf{i+1}-273.15' for i in range(NP)] + ['mcp*(T_in-Tf8)'] + [f'intP{i+1}(g_ex/t_m*(0.5*({"T_in" if i == 0 else f"Tf{i}"}+Tf{i+1})-T))' for i in range(NP)]
        ev.set('expr', exprs); ev.set('innerinput', 'all')
        vals = ev.getReal()
        rows = [list(map(float, r)) for r in vals]
        print(f"{tagd}: t-rows={len(rows[0]) if rows else 0}")
        for k, ex in enumerate(exprs):
            print(f"   {ex[:40]:40s}", [round(v, 2) for v in rows[k]][:10])
    except Exception as ex:
        print(tagd, "eval ERR", str(ex).replace("\n", " ")[:200])
model.save(os.path.join(HERE, 's02.mph'))
print("total %.0fs" % (time.time() - t_start))
