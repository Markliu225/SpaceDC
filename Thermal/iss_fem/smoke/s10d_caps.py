import mph
c = mph.start(cores=1); m = c.create('x'); j = m.java
comp = j.component().create('comp1', True); g = comp.geom().create('geom1', 3)
cy = g.feature().create('c', 'Cylinder'); cy.set('type', 'surface'); cy.set('r', '2'); cy.set('h', '8'); cy.set('axistype', 'x'); g.run()
print('surface cylinder: boundaries', g.getNBoundaries(), 'bbox of each:')
for b in range(1, g.getNBoundaries() + 1):
    print('  bnd', b, [round(float(v), 2) for v in g.getBoundingBox()] if b == 1 else '')
g.feature().remove('c')
cy2 = g.feature().create('c2', 'Cylinder'); cy2.set('type', 'solid'); cy2.set('r', '2'); cy2.set('h', '8'); cy2.set('axistype', 'x'); g.run()
print('solid cylinder: domains', g.getNDomains(), 'boundaries', g.getNBoundaries())
