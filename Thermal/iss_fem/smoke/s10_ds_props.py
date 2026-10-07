import mph
c = mph.start(cores=1); m = c.create('x'); j = m.java
comp = j.component().create('comp1', True); g = comp.geom().create('geom1', 3)
cy = g.feature().create('c', 'Cylinder'); cy.set('type', 'surface'); g.run()
o = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1')
d = o.create('ds1', 'DiffuseSurface', 2); d.selection().all()
names = [str(x) for x in d.properties()]
print('ALL', len(names))
for n in names:
    if any(k in n.lower() for k in ('dir', 'side', 'opac', 'normal', 'radiat')):
        try: print('  ', n, '=', str(d.getString(n))[:60])
        except Exception: print('  ', n)
for k, v in (('radiationDirection', 'xxx'), ('radiationDirectionType', 'xxx'), ('RadiationDirection', 'xxx')):
    try: d.set(k, v)
    except Exception as e: print('try', k, '->', str(e).replace(chr(10), ' ')[:300])
