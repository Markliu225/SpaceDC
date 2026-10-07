import mph, numpy as np
c = mph.start(cores=2); m = c.load('s03.mph'); j = m.java
ds = m.datasets()[0]
t = np.atleast_1d(m.evaluate('t', dataset=ds)); T = 5572.07
u = np.round(360 * t / T).astype(int)
print('u deg  ', list(u))
for name, sel in (('otl3', 'S_top'), ('otl2', 'R_px')):
    for band in ('Gext1', 'Gext2'):
        ev = j.result().numerical().create(f'ev_{name}_{band}', 'AvSurface'); ev.set('data', 'dset1'); ev.selection().named(sel)
        ev.set('expr', [f'{name}.{band}']); ev.set('innerinput', 'all')
        v = np.array(ev.getReal()[0], dtype=float)
        print(f'{name}.{band} on {sel}:', list(np.round(v).astype(int)))
