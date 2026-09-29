import mph, numpy as np
c = mph.start(cores=2); m = c.load('s03.mph'); j = m.java
st = j.study('std1').feature('otl')
for n in [str(x) for x in st.properties()]:
    try: v = st.getString(n)
    except Exception:
        try: v = [str(x) for x in st.getStringArray(n)]
        except Exception: v = '(err)'
    if any(k in n.lower() for k in ('activ', 'phys', 'otl', 'interface', 'rad', 'orbit')):
        print('otl step prop', n, '=', str(v)[:300])
print('datasets', m.datasets())
for o in ('otl_b', 'otl_r', 'otl_s'):
    print(o, 'selection:', [int(x) for x in j.component('comp1').physics(o).selection().entities()])
for ds in m.datasets():
    for expr in ('otl_s.Gext1', 'otl_r.Gext1', 'otl_b.Gext1', 'otl_s.G1', 'otl_s.Gext', 'otl_s.J1', 'otl_s.q0s', 'otl_s.X_ECS'):
        try:
            v = m.evaluate(expr, dataset=ds)
            print(ds, expr, 'OK shape', np.shape(v), np.round(np.atleast_1d(np.asarray(v).ravel())[:5], 2))
        except Exception as e:
            print(ds, expr, 'ERR', str(e).replace(chr(10), ' ')[:120])
