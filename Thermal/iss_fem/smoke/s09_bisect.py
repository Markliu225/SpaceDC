# -*- coding: utf-8 -*-
"""Smoke 09: bisect the nonlinear-convergence problem of the lite ISS model with fixed 60 s steps.
    python s09_bisect.py <model.mph> <variant> [t_end]
variants:
  base     loop equations (ge) and panel fluid sources (fx_*) disabled
  loopfix  loops active but the panel-fluid coupling frozen: fx_* use a fixed fluid temperature
  full     as built
Progress log: s09_<variant>_progress.log
"""
import os, sys, time
import mph, jpype

path, variant = sys.argv[1], sys.argv[2]
t_end = float(sys.argv[3]) if len(sys.argv) > 3 else 600.0
HERE = os.path.dirname(os.path.abspath(__file__))
client = mph.start(cores=5)
jpype.JClass('com.comsol.model.util.ModelUtil').showProgress(os.path.join(HERE, f's09_{variant}_progress.log'))
m = client.load(path); j = m.java; comp = j.component('comp1')
for s in ('otl', 'ot'):
    j.study('stdO').feature(s).set('tlist', f'range(0,60,{t_end})')
for sol in j.sol():
    if str(sol.study()) != 'stdO': continue
    for f in sol.feature():
        if str(f.getType()) == 'Time':
            f.set('tstepsbdf', 'manual'); f.set('timestepbdf', '60'); f.set('maxorder', '1')
sh = comp.physics('htlsh')
if variant in ('base', 'loopfix'):
    for f in sh.feature():
        if str(f.tag()).startswith('fx_'):
            if variant == 'base':
                f.active(False)
            else:
                f.set('Q0', '120[W/(m^2*K)]*(268[K]-T2)/0.0025[m]')
if variant == 'base':
    for s in ('otl', 'ot'):
        st = j.study('stdO').feature(s); a = [str(x) for x in st.getStringArray('activate')]
        if 'ge' in a:
            a[a.index('ge') + 1] = 'off'; st.set('activate', a)
    # solver sequence must follow the study change
    for tg in [str(sol.tag()) for sol in j.sol() if str(sol.study()) == 'stdO']:
        try: j.sol().remove(tg)
        except Exception as e: print('remove sol', e)
    j.study('stdO').createAutoSequences('all')
    for sol in j.sol():
        if str(sol.study()) != 'stdO': continue
        for f in sol.feature():
            if str(f.getType()) == 'Time':
                f.set('tstepsbdf', 'manual'); f.set('timestepbdf', '60'); f.set('maxorder', '1')
            if str(f.getType()) == 'Variables':
                for c in f.feature():
                    if str(c.tag()) in ('comp1_T', 'comp1_T2'):
                        c.set('scalemethod', 'manual'); c.set('scaleval', '300')
t0 = time.time()
try:
    j.study('stdO').run(); print(variant, 'SOLVED %.0f s wall for %.0f s orbit' % (time.time() - t0, t_end), flush=True)
except Exception as e:
    print(variant, 'FAILED %.0f s' % (time.time() - t0), str(e).replace(chr(10), ' ')[:800], flush=True)
