# -*- coding: utf-8 -*-
"""Smoke 07: profile the orbital-temperature solve of a saved ISS model with COMSOL's
progress/solver log written to a file.
    python s07_profile.py <model.mph> <t_end_s> [dt_out] [--hemicube N] [--vf-tol x] [--rtol r]
"""
import argparse, os, sys, time
import mph, jpype

ap = argparse.ArgumentParser(); ap.add_argument('mph'); ap.add_argument('t_end', type=float); ap.add_argument('dt', type=float, nargs='?', default=60.0)
ap.add_argument('--hemicube', default=None); ap.add_argument('--vf-tol', dest='vf_tol', default=None); ap.add_argument('--rtol', default=None)
ap.add_argument('--cores', type=int, default=5); ap.add_argument('--tag', default='prof'); ap.add_argument('--manual', default=None)
a = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
plog = os.path.join(HERE, f's07_{a.tag}_progress.log')
client = mph.start(cores=a.cores)
MU = jpype.JClass('com.comsol.model.util.ModelUtil')
try:
    MU.showProgress(plog); print('progress log ->', plog, flush=True)
except Exception as e:
    print('showProgress(file) failed:', str(e)[:200], flush=True)
m = client.load(a.mph); j = m.java; comp = j.component('comp1')
for p in comp.physics():
    if str(p.getType()) == 'OrbitalThermalLoadsEvents':
        rs = p.prop('RadiationSettings')
        if a.hemicube: rs.set('radiationResolution', a.hemicube)
        if a.vf_tol: rs.set('viewFactorsUpdateTolerance', a.vf_tol)
tl = f'range(0,{a.dt},{a.t_end})'
for s in ('otl', 'ot'):
    j.study('stdO').feature(s).set('tlist', tl)
if a.rtol:
    j.study('stdO').feature('ot').set('rtol', a.rtol)
if a.manual:
    for sol in j.sol():
        if str(sol.study()) != 'stdO': continue
        for f in sol.feature():
            if str(f.getType()) != 'Time': continue
            for k, v in (('tstepsbdf', 'manual'), ('timestepbdf', a.manual), ('maxorder', '1')):
                try: f.set(k, v); print('set', sol.tag(), f.tag(), k, v, flush=True)
                except Exception as e: print('set FAIL', k, v, str(e).replace(chr(10), ' ')[:300], flush=True)
t0 = time.time()
try:
    j.study('stdO').run(); print('SOLVED %.0f s wall for %.0f s orbit' % (time.time() - t0, a.t_end), flush=True)
except Exception as e:
    print('FAILED %.0f s' % (time.time() - t0), str(e).replace(chr(10), ' ')[:1500], flush=True)
# per-solver statistics from the solution sequences
for sol in j.sol():
    for f in sol.feature():
        try:
            tp = str(f.getType())
            if tp == 'Time':
                print('solver', str(sol.tag()), str(f.tag()), 'rtol', f.getString('rtol') if 'rtol' in [str(x) for x in f.properties()] else '?')
        except Exception:
            pass
m.save(os.path.join(HERE, f's07_{a.tag}.mph'))
