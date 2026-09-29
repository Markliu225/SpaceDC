# -*- coding: utf-8 -*-
"""Smoke 03: articulated parts as separate Orbital Thermal Loads interfaces.

OTL has no articulation (loads are expressed in the material frame; a moving
mesh breaks the orbit-velocity derivative, smoke 01). Workaround under test:
each articulated group gets its own OTL interface with its own pointing law,
all coupled to one Heat Transfer interface.
  otl_b  body   : cube + fixed plate A      nadir (+Z) / velocity (+X)
  otl_r  radiator plate R (plane Y-Z)      model +Y -> antinormal, model +Z -> anti-Sun
                                            (edge to Sun in daylight); events timeline
                                            switches to "face to Earth" (+X -> nadir) in eclipse
  otl_s  array plate S (normal -Z)          model -Z -> Sun, model +Y -> antinormal
Orbit: ISS-like circular, i = 51.64 deg, beta set by the Sun vector.
Checks: solves with 3 OTL + 1 HT; plate S sees ~S at all sunlit times; plate R
sees ~0 direct Sun (edge-on) in daylight; eclipse switch works.
"""
import mph, time, os, math

HERE = os.path.dirname(os.path.abspath(__file__))
MU = 3.986004418e14
RE = 6378.137e3
H = 415e3
R = RE + H
T_ORB = 2 * math.pi * math.sqrt(R ** 3 / MU)
INC = math.radians(51.64)
BETA = math.radians(0.0)

t_start = time.time()
client = mph.start(cores=4)
model = client.create('s03'); j = model.java
comp = j.component().create('comp1', True)
geom = comp.geom().create('geom1', 3); geom.lengthUnit('m')
def blk(tag, size, pos):
    f = geom.feature().create(tag, 'Block'); f.set('size', [float(v) for v in size]); f.set('base', 'center'); f.set('pos', [float(v) for v in pos])
blk('body', (1, 1, 1), (0, 0, 0))
blk('plA', (2, 2, 0.02), (4, 0, 0))            # body-fixed, normal +/-Z
blk('plR', (0.02, 3.4, 6), (0, 6, 4))          # radiator hanging nadir, plane Y-Z
blk('plS', (4, 2, 0.02), (0, -8, 0))           # array, normal +/-Z (active face -Z)
geom.run()
print("geom:", geom.getNDomains(), "domains", geom.getNBoundaries(), "boundaries", flush=True)

def boxsel(tag, dim, lo, hi, cond='inside'):
    s = comp.selection().create(tag, 'Box'); s.set('entitydim', str(dim))
    s.set('xmin', lo[0]); s.set('xmax', hi[0]); s.set('ymin', lo[1]); s.set('ymax', hi[1]); s.set('zmin', lo[2]); s.set('zmax', hi[2])
    s.set('condition', cond); return s
boxsel('dB', 3, (-0.6, -0.6, -0.6), (5.1, 1.1, 0.6))
boxsel('dR', 3, (-0.1, 4.2, 0.9), (0.1, 7.8, 7.1))
boxsel('dS', 3, (-2.1, -9.1, -0.1), (2.1, -6.9, 0.1))
for nm in ('B', 'R', 'S'):
    a = comp.selection().create('b' + nm, 'Adjacent'); a.set('entitydim', '3'); a.set('input', ['d' + nm]); a.set('outputdim', '2')
boxsel('A_top', 2, (2.9, -1.1, -0.011), (5.1, 1.1, -0.009))
boxsel('S_top', 2, (-2.1, -9.1, 0.009), (2.1, -6.9, 0.011))   # +Z face = cell side
boxsel('R_px', 2, (0.009, 4.2, 0.9), (0.011, 7.8, 7.1))

mat = comp.material().create('mat1', 'Common'); mat.selection().all()
mat.propertyGroup('def').set('thermalconductivity', ['200']); mat.propertyGroup('def').set('density', '2700'); mat.propertyGroup('def').set('heatcapacity', '900')

# ISS-like circular orbit in ECS; ascending node on +X_ECS; Sun vector gives beta
# orbit normal h = (0, -sin i, cos i); Sun direction s = cos(b)*(cos phi, sin phi, 0)... keep it simple:
# choose s = cos(beta)*e1 + sin(beta)*h with e1 = (1,0,0) lying in the orbit plane (ascending node)
wexpr = f'2*pi*t/{T_ORB:.3f}'
rx = f'{R:.1f}*cos({wexpr})'
ry = f'{R:.1f}*sin({wexpr})*cos({INC})'
rz = f'{R:.1f}*sin({wexpr})*sin({INC})'
for nm, expr in (('rx', rx), ('ry', ry), ('rz', rz)):
    fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')
hx, hy, hz = 0.0, -math.sin(INC), math.cos(INC)
sx, sy, sz = math.cos(BETA) + math.sin(BETA) * hx, math.sin(BETA) * hy, math.sin(BETA) * hz
print("Sun dir ECS:", sx, sy, sz, " T_orb", T_ORB)

ht = comp.physics().create('ht', 'HeatTransfer', 'geom1'); ht.feature('init1').set('Tinit', '280[K]')

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val, flush=True); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace(chr(10), " ")[:400], flush=True); return False

def make_otl(tag, sel, prim_axis_vec, prim_orient, sec_axis_vec, sec_orient, events=None):
    o = comp.physics().create(tag, 'OrbitalThermalLoadsEvents', 'geom1')
    o.selection().named(sel) if False else None
    rs = o.prop('RadiationSettings'); rs.set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient'); rs.set('radiationMethod', 'hemicube'); rs.set('radiationResolution', '128')
    op = o.feature('op1'); op.set('orbitType', 'userDefined'); op.set('orbitDefinition', 'FromFunction')
    for ax in 'XYZ':
        op.set(f'functionType_{ax}_ECS', 'userDefined'); op.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(t)')
    sup = o.feature('sup1'); sup.set('sunDirection', 'userdef'); sup.set('SV_ECS', [f'{-sx:.6f}', f'{-sy:.6f}', f'{-sz:.6f}'])
    sup.set('solarFluxSolAmb', 'userdefBand'); sup.set('q0s_bandSolAmb', ['1361', '0'])
    plp = o.feature('plp1'); plp.set('nRings', '2'); plp.set('nPointsRing', '6')
    plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['0.3', '0'])
    plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', '237'])
    sa = o.feature('sa1'); so = o.feature('so1')
    tryset(sa, 'primaryAxis', prim_axis_vec, tag + '.sa1'); tryset(sa, 'secondaryAxis', sec_axis_vec, tag + '.sa1')
    tryset(so, 'primaryOrientation', prim_orient, tag + '.so1'); tryset(so, 'secondaryOrientation', sec_orient, tag + '.so1')
    d = o.feature('dsurf1'); d.set('epsilon_radSolAmb_mat', 'userdefBand'); d.set('epsilon_rad_bandSolAmb', ['0.5', '0.5']); d.set('Tamb', '2.7[K]')
    return o

def props(obj, label):
    try:
        names = list(obj.properties()); print("PROPS", label, names, flush=True)
    except Exception as e:
        print("PROPS", label, "ERR", str(e)[:150])

# learn the Spacecraft Axes / Orientation / Events Timeline property names once
probe = comp.physics().create('otl_probe', 'OrbitalThermalLoadsEvents', 'geom1')
for ft in ('sa1', 'so1', 'et1'):
    props(probe.feature(ft), ft)
    for n in list(probe.feature(ft).properties()):
        try: print("     ", n, "=", str(probe.feature(ft).getString(n))[:100])
        except Exception:
            try: print("     ", n, "=", [str(x) for x in probe.feature(ft).getStringArray(n)][:8])
            except Exception: print("     ", n, "(get err)")
props(probe, 'otl interface');
try: print('otl selection props:', [str(x) for x in probe.selection().entities()][:5])
except Exception as e: print('sel err', e)
comp.physics().remove('otl_probe')
print('--- building three OTL interfaces', flush=True)
t0 = time.time()
try:
    ob = make_otl('otl_b', 'bB', 'z', 'nadir', 'x', 'velocity')
    orr = make_otl('otl_r', 'bR', 'y', 'antinormal', 'z', 'antisun')
    osl = make_otl('otl_s', 'bS', 'z', 'sun', 'y', 'antinormal')
    for o, sel in ((ob, 'bB'), (orr, 'bR'), (osl, 'bS')):
        o.selection().named(sel)
    print('three OTL created %.1fs' % (time.time() - t0), flush=True)
except Exception as e:
    print('OTL create FAIL', str(e).replace('\n', ' ')[:800], flush=True)
    raise
for k, o in (('b', 'otl_b'), ('r', 'otl_r'), ('s', 'otl_s')):
    mp = comp.multiphysics().create('htrad_' + k, 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mp.set('Heat_physics', 'ht'); mp.set('Rad_physics', o)

# radiator: face to Earth in eclipse via a second axes/orientation pair + events timeline
try:
    sa2 = so2 = None
    for args in (('sa2', 'SpacecraftAxes', -1), ('sa2', 'SpacecraftAxes')):
        try: sa2 = orr.create(*args); print('sa2 created with', args); break
        except Exception as e: print('sa2 create FAIL', args, str(e).replace(chr(10), ' ')[:200])
    for args in (('so2', 'SpacecraftOrientation', -1), ('so2', 'SpacecraftOrientation')):
        try: so2 = orr.create(*args); print('so2 created with', args); break
        except Exception as e: print('so2 create FAIL', args, str(e).replace(chr(10), ' ')[:200])
    tryset(sa2, 'primaryAxis', 'y', 'sa2'); tryset(sa2, 'secondaryAxis', 'x', 'sa2')
    tryset(so2, 'primaryOrientation', 'antinormal', 'so2'); tryset(so2, 'secondaryOrientation', 'nadir', 'so2')
    et = orr.feature('et1'); props(et, 'et1 (otl_r)')
    et.set('eventType', ['inEclipse', 'outEclipse'])
    et.set('implicitAxesFeatures', ['sa2', 'sa1']); et.set('implicitOrientationFeatures', ['so2', 'so1'])
    et.set('implicitFastTumbling', ['0', '0']); et.set('implicitDescription', ['face to Earth', 'edge to Sun'])
    print('events timeline set', flush=True)
except Exception as e:
    print('EVENTS set FAIL', str(e).replace('\n', ' ')[:600], flush=True)

mesh = comp.mesh().create('mesh1'); mesh.autoMeshSize(6)
t0 = time.time(); mesh.run(); print("mesh %.1fs" % (time.time() - t0), flush=True)

std = j.study().create('std1')
s0 = std.create('otl', 'OrbitThermalLoads'); s0.set('timestepspec', 'timesteps'); s0.set('tlist', f'range(0,{T_ORB/24:.2f},{T_ORB:.2f})')
s1 = std.create('ot', 'OrbitalTemperature'); s1.set('timestepspec', 'timesteps'); s1.set('tlist', f'range(0,{T_ORB/24:.2f},{T_ORB:.2f})')
t0 = time.time()
try:
    std.run(); print("LOADS SOLVED in %.1fs" % (time.time() - t0), flush=True)
except Exception as e:
    print("LOADS SOLVE FAIL %.1fs" % (time.time() - t0), str(e).replace("\n", " ")[:2000], flush=True)

for ds in j.result().dataset():
    tagd = str(ds.tag())
    for otag, sel in (('otl_b', 'A_top'), ('otl_s', 'S_top'), ('otl_r', 'R_px')):
        for expr in (f'{otag}.Gext1', f'{otag}.Gext2'):
            try:
                ev = j.result().numerical().create(f'ev_{tagd}_{sel}_{expr.replace(".", "_")}', 'AvSurface')
                ev.set('data', tagd); ev.selection().named(sel); ev.set('expr', [expr]); ev.set('innerinput', 'all')
                vals = ev.getReal()
                print(f"{tagd} {sel:6s} {expr:12s}", [round(float(v)) for v in list(vals[0])], flush=True)
            except Exception as e:
                print(f"{tagd} {sel} {expr}: ERR", str(e).replace("\n", " ")[:200], flush=True)
print("u(deg) at outputs:", [round(360 * k / 24) for k in range(25)])
model.save(os.path.join(HERE, 's03b.mph'))
print("total %.0fs" % (time.time() - t_start))
