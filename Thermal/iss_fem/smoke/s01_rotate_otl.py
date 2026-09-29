# -*- coding: utf-8 -*-
"""Smoke 01: can a Rotating Domain (moving mesh) articulate a panel inside the
Orbital Thermal Loads interface?

Toy: fixed 1 m cube + fixed plate A (normal -Z at t=0) + plate B on a rotating
domain about +Y at the orbital rate. Equatorial circular user-defined orbit,
Sun rays along -X_ECS (beta = 0), body +Z nadir / +X velocity, so the Sun in
body axes is s = (-sin u, 0, -cos u), u = w t. Plate B's -Z face should see the
full solar flux all through the sunlit arc if the rotation is honoured by the
OTL view-factor evaluation; plate A should fall off as cos(u).
"""
import mph, time, sys, os

T_ORB = 5554.0
R = 6778e3

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val, flush=True); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace("\n", " ")[:250], flush=True); return False

def props(obj, label):
    try:
        names = list(obj.properties()); print("PROPS", label, names, flush=True)
        for n in names:
            try: print("     ", n, "=", str(obj.getString(n))[:120])
            except Exception:
                try: print("     ", n, "=", [str(x) for x in obj.getStringArray(n)][:6])
                except Exception: print("     ", n, "(get err)")
    except Exception as e:
        print("PROPS", label, "ERR", str(e)[:150])

t_start = time.time()
client = mph.start(cores=4)
model = client.create('s01'); j = model.java
comp = j.component().create('comp1', True)
geom = comp.geom().create('geom1', 3); geom.lengthUnit('m')
b = geom.feature().create('body', 'Block'); b.set('size', [1.0, 1.0, 1.0]); b.set('base', 'center')
pa = geom.feature().create('plA', 'Block'); pa.set('size', [2.0, 2.0, 0.02]); pa.set('base', 'center'); pa.set('pos', [4.0, 0.0, 0.0])
pb = geom.feature().create('plB', 'Block'); pb.set('size', [2.0, 2.0, 0.02]); pb.set('base', 'center'); pb.set('pos', [-4.0, 0.0, 0.0])
geom.run()
print("geom:", geom.getNDomains(), "domains", geom.getNBoundaries(), "boundaries", flush=True)

def boxsel(tag, dim, lo, hi, cond='inside'):
    s = comp.selection().create(tag, 'Box'); s.set('entitydim', str(dim))
    s.set('xmin', lo[0]); s.set('xmax', hi[0]); s.set('ymin', lo[1]); s.set('ymax', hi[1]); s.set('zmin', lo[2]); s.set('zmax', hi[2])
    s.set('condition', cond); return s
boxsel('selA', 3, (2.9, -1.1, -0.1), (5.1, 1.1, 0.1))
boxsel('selB', 3, (-5.1, -1.1, -0.1), (-2.9, 1.1, 0.1))
boxsel('selA_top', 2, (2.9, -1.1, -0.011), (5.1, 1.1, -0.009))   # -Z face of A (faces zenith at t=0)
boxsel('selB_top', 2, (-5.1, -1.1, -0.011), (-2.9, 1.1, -0.009))

mat = comp.material().create('mat1', 'Common'); mat.selection().all()
mat.propertyGroup('def').set('thermalconductivity', ['200']); mat.propertyGroup('def').set('density', '2700'); mat.propertyGroup('def').set('heatcapacity', '900')

# ---------------- moving mesh: rotating domain on plate B
rot = None
for where in ('common',):
    try:
        rot = comp.common().create('rot1', 'RotatingDomain'); print("RotatingDomain created under", where, flush=True)
    except Exception as e:
        print("RotatingDomain create FAIL", where, str(e)[:300], flush=True)
if rot is not None:
    rot.selection().named('selB')
    props(rot, 'rot1')

j.param().set('w_orb', f'2*pi/{T_ORB}[s]')
for nm, expr in (('rx', f'{R}*cos(2*pi*t/{T_ORB})'), ('ry', f'{R}*sin(2*pi*t/{T_ORB})'), ('rz', '0')):
    fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')

ht = comp.physics().create('ht', 'HeatTransfer', 'geom1')
ht.feature('init1').set('Tinit', '280[K]')
otl = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1')
rs = otl.prop('RadiationSettings'); rs.set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient'); rs.set('radiationMethod', 'hemicube'); rs.set('radiationResolution', '128')
op = otl.feature('op1'); op.set('orbitType', 'userDefined'); op.set('orbitDefinition', 'FromFunction')
for ax in 'XYZ':
    op.set(f'functionType_{ax}_ECS', 'userDefined'); op.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(t)')
sup = otl.feature('sup1'); sup.set('sunDirection', 'userdef'); sup.set('SV_ECS', ['-1', '0', '0'])
sup.set('solarFluxSolAmb', 'userdefBand'); sup.set('q0s_bandSolAmb', ['1361', '0'])
plp = otl.feature('plp1'); plp.set('nRings', '2'); plp.set('nPointsRing', '6')
plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['0.0', '0'])   # no albedo: isolate the direct sun
plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', '0'])
otl.feature('sa1').set('primaryAxis', 'z'); otl.feature('sa1').set('secondaryAxis', 'x')
otl.feature('so1').set('primaryOrientation', 'nadir'); otl.feature('so1').set('secondaryOrientation', 'velocity')
d = otl.feature('dsurf1'); d.set('epsilon_radSolAmb_mat', 'userdefBand'); d.set('epsilon_rad_bandSolAmb', ['0.5', '0.5']); d.set('Tamb', '2.7[K]')
mp = comp.multiphysics().create('htrad1', 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mp.set('Heat_physics', 'ht'); mp.set('Rad_physics', 'otl')

if rot is not None:
    rot.set('rotationType', 'userDefined'); rot.set('rotationAngle', 'w_orb*t')
    rot.set('rotationAxis', ['0', '1', '0']); rot.set('rotationAxisBasePoint', ['-4', '0', '0'])
    props(rot, 'rot1 after set')

mesh = comp.mesh().create('mesh1'); mesh.autoMeshSize(6)
t0 = time.time(); mesh.run(); print("mesh %.1fs" % (time.time() - t0), flush=True)

std = j.study().create('std1')
s0 = std.create('otl', 'OrbitThermalLoads'); s0.set('timestepspec', 'timesteps'); s0.set('tlist', 'range(0,300,2700)')
s1 = std.create('ot', 'OrbitalTemperature'); s1.set('timestepspec', 'timesteps'); s1.set('tlist', 'range(0,300,2700)')
t0 = time.time()
try:
    std.run(); print("SOLVED in %.1fs" % (time.time() - t0), flush=True)
except Exception as e:
    print("SOLVE FAIL %.1fs" % (time.time() - t0), str(e).replace("\n", " ")[:1500], flush=True)

# evaluate the external solar-band irradiation on the zenith faces, dataset by dataset
for ds in j.result().dataset():
    tagd = str(ds.tag())
    for expr in ('otl.Gext1', 'otl.G1', 'T'):
        for sel in ('selA_top', 'selB_top'):
            try:
                ev = j.result().numerical().create('ev_' + tagd + sel + expr.replace('.', '_'), 'AvSurface')
                ev.set('data', tagd); ev.selection().named(sel); ev.set('expr', [expr]); ev.set('innerinput', 'all')
                vals = ev.getReal()
                print(f"{tagd} {sel} {expr}:", [round(float(v), 1) for v in list(vals[0])][:12], flush=True)
            except Exception as e:
                print(f"{tagd} {sel} {expr}: ERR", str(e).replace("\n", " ")[:160], flush=True)
print("expected plate-A solar-band flux ~1361*max(0,cos(u)) at u = 2*pi*t/T; u(t=0,300,..)=", [round(360 * t / T_ORB) for t in range(0, 2701, 300)])
model.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), 's01.mph'))
print("total %.0fs" % (time.time() - t_start))
