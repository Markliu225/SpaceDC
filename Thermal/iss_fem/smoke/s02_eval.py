import mph, numpy as np
c = mph.start(cores=2); m = c.load('s02.mph')
print('datasets:', m.datasets())
for ds in m.datasets():
    try:
        t = m.evaluate('t', dataset=ds)
        Tin = m.evaluate('T_in-273.15', dataset=ds)
        Tf = [m.evaluate(f'Tf{i}-273.15', dataset=ds) for i in range(1, 9)]
        Qfl = m.evaluate('mcp*(T_in-Tf8)', dataset=ds)
        Qp = sum(m.evaluate(f'intP{i+1}(g_ex/t_m*(0.5*({"T_in" if i == 0 else f"Tf{i}"}+Tf{i+1})-T))', dataset=ds) for i in range(8))
        print(ds, 't:', np.round(np.atleast_1d(t), 0))
        for i, v in enumerate(Tf): print('  Tf%d' % (i + 1), np.round(np.atleast_1d(v), 2))
        print('  Q_fluid W', np.round(np.atleast_1d(Qfl), 1)); print('  sum Q_panels W', np.round(np.atleast_1d(Qp), 1))
    except Exception as e:
        print(ds, 'ERR', str(e)[:300])
