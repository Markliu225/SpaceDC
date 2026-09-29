import mph
c = mph.start(cores=1); m = c.create('x'); j = m.java
comp = j.component().create('comp1', True); g = comp.geom().create('geom1', 3)
cy = g.feature().create('c', 'Cylinder'); cy.set('r', '2'); cy.set('h', '8'); cy.set('axistype', 'x')
for typ in ('ConvertToSurface', 'ConvertSurface', 'Convert2Surface'):
    try:
        cv = g.feature().create('cv', typ); cv.selection('input').set(['c']); print('created', typ); break
    except Exception as e:
        print(typ, 'FAIL', str(e).replace(chr(10), ' ')[:150])
try:
    cv.set('contributeto', 'none') if False else None
    g.run(); print('after convert: domains', g.getNDomains(), 'boundaries', g.getNBoundaries())
except Exception as e:
    print('run ERR', str(e).replace(chr(10), ' ')[:300])
