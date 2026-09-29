import mph
c = mph.start(cores=1); m = c.create('x'); j = m.java
comp = j.component().create('comp1', True); g = comp.geom().create('geom1', 3)
cy = g.feature().create('c', 'Cylinder'); cy.set('type', 'surface'); g.run()
o = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1')
o.prop('RadiationSettings').set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient')
d = o.create('ds1', 'DiffuseSurface', 2); d.selection().all()
for k in ('radDirectionTypeSolAmb', 'radDirectionTypeSolAmbAllBands', 'radDirectionType'):
    try: d.set(k, 'xxx')
    except Exception as e: print(k, '->', str(e).replace(chr(10), ' ')[:400])
