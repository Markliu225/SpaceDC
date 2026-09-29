import sys, re
sys.path.insert(0, r'C:\Workspace\SpaceDC\Thermal\iss_fem\model')
import mph, numpy as np
import iss_layout as L
lay = L.build('nom0')
c = mph.start(cores=1); m = c.load(r'C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol\iss_nom0_test_10860.mph'); j = m.java
name = next(n for n in m.datasets() if n.endswith('//解 4'))
comp = j.component('comp1')
for L_ in ('A', 'B'):
    expr = lay['global_vars'].get('Q_' + L_)
    rows = [r for r in lay['ge_rows'] if r[0] == 'Qc_' + L_][0][1]
    terms = re.findall(r'(-?\w+\([^()]*\([^()]*\)[^()]*\)|-?\w+\([^()]*\))', rows.split('-((', 1)[1])
    tot = 0.0; zeros = []; bymod = {}
    for tm in terms:
        try:
            v = float(np.atleast_1d(m.evaluate(tm, dataset=name))[-1])
        except Exception as e:
            v = float('nan'); print('ERR', tm[:60], str(e)[:80])
        tot += v if v == v else 0
        key = re.sub(r'_\d+_\d+$', '', tm.split('(')[0].lstrip('-'))
        bymod[key] = bymod.get(key, 0) + v
        if abs(v) < 1: zeros.append(tm.split('(')[0])
    print('loop', L_, 'n terms', len(terms), 'sum %.0f W' % tot)
    for k, v in sorted(bymod.items(), key=lambda x: -abs(x[1]))[:14]: print('    %-28s %9.0f' % (k, v))
    print('   ~zero terms:', len(zeros), zeros[:12])
for sel in ('sf_rk_kibo_0_0' + x for x in ('px', 'mx', 'pz', 'mz')):
    try: print(sel, [int(v) for v in comp.selection(sel).entities(2)])
    except Exception as e: print(sel, 'n/a')
