import mph, numpy as np
c = mph.start(cores=2); m = c.load(r'C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol\iss_nom0_test_failed.mph'); j = m.java
print(m.datasets())
ds = None
for d in j.result().dataset():
    try:
        sol = str(d.getString('solution')); st = str(j.sol(sol).study())
        print(str(d.tag()), str(d.label()), sol, st)
    except Exception as e: pass
for lab in m.datasets():
    try:
        t = np.atleast_1d(m.evaluate('t', dataset=lab))
        if len(t) < 3: continue
        out = {}
        for e in ('f_A', 'f_B', 'Q_A', 'Q_B', 'Tret_A-273.15', 'Tout_A-273.15', 'Tmix_A-273.15', 'Tout_B-273.15', 'Tmix_B-273.15',
                  'f_PVP4', 'Q_PVP4', 'Tout_PVP4-273.15', 'Tf_A_1_8-273.15', 'Tf_B_1_8-273.15'):
            try: out[e] = np.atleast_1d(m.evaluate(e, dataset=lab))
            except Exception as ex: out[e] = str(ex)[:80]
        print('=== dataset', lab, 't', t[:3], '...', t[-3:])
        for k, v in out.items():
            if isinstance(v, str): print('  ', k, v)
            else: print('  ', f'{k:18s}', np.round(v[::3], 3))
    except Exception as ex:
        print(lab, 'ERR', str(ex)[:120])
