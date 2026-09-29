import mph
c = mph.start(cores=1); m = c.load(r'C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol\iss_nom0_test.mph'); j = m.java
print('datasets', m.datasets())
for ds in ('dset4', 'dset5'):
    for sel in ('sel_grp_hrs', 'sel_grp_body'):
        try:
            n = j.result().numerical().create('evx', 'AvSurface'); n.set('data', ds); n.selection().named(sel); n.set('expr', ['T2']); n.set('innerinput', 'all')
            v = n.getReal(); print(ds, sel, 'rows', len(v), 'cols', len(v[0]) if len(v) else 0, [float(x) for x in v[0]][:3] if len(v) else '')
        except Exception as e:
            print(ds, sel, 'ERR', str(e).replace(chr(10), ' ')[:300])
        try: j.result().numerical().remove('evx')
        except Exception: pass
