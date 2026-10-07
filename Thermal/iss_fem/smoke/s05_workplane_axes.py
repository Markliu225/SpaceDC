# Smoke 05: verify WorkPlane quick-plane local axes and bounding boxes (for panel placement)
import mph
c = mph.start(cores=2); m = c.create('wp'); j = m.java
comp = j.component().create('comp1', True); g = comp.geom().create('geom1', 3); g.lengthUnit('m')
for tag, qp, key, off in (('wxy', 'xy', 'quickz', 5.0), ('wyz', 'yz', 'quickx', 6.0), ('wzx', 'zx', 'quicky', 7.0)):
    wp = g.feature().create(tag, 'WorkPlane'); wp.set('planetype', 'quick'); wp.set('quickplane', qp); wp.set(key, str(off))
    wp.set('unite', True)
    r = wp.geom().create('r1', 'Rectangle'); r.set('size', [1.0, 3.0]); r.set('pos', [10.0, 20.0])
g.run()
for tag in ('wxy', 'wyz', 'wzx'):
    try:
        bb = [float(v) for v in g.obj(tag).getBoundingBox()]
        print(tag, 'bbox', bb)
    except Exception as e:
        print(tag, 'bbox ERR', str(e)[:200])
# parametric surface: a tilted rectangle
ps = g.feature().create('ps1', 'ParametricSurface')
for k, v in (('parmin1', '0'), ('parmax1', '1'), ('parmin2', '0'), ('parmax2', '1'), ('coord', ['s1*2', 's2*3*cos(30[deg])', 's2*3*sin(30[deg])'])):
    try: ps.set(k, v); print('ps set', k, 'OK')
    except Exception as e: print('ps set', k, 'FAIL', str(e).replace(chr(10), ' ')[:160])
try:
    g.run(); print('ps bbox', [float(v) for v in g.obj('ps1').getBoundingBox()], 'nbnd', g.getNBoundaries())
except Exception as e:
    print('ps run ERR', str(e).replace(chr(10), ' ')[:300])
