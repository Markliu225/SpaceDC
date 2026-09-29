import mph
c = mph.start(cores=2); m = c.create('x'); j = m.java
comp = j.component().create('comp1', True); g = comp.geom().create('geom1', 3)
b = g.feature().create('b', 'Block'); b.set('type', 'surface'); g.run()
sh = comp.physics().create('htlsh', 'HeatTransferInShellsLM', 'geom1')
ls = sh.prop('LayerSelection')
for k, v in (('shelllist', 'nonlayered'), ('shelllist', 'Nonlayered'), ('shelllist', 'xxx'), ('bndType', 'xxx'), ('applyTo', 'xxx'), ('lth_mat', 'userdef')):
    try:
        ls.set(k, v); print('LayerSelection set OK', k, v, '->', str(ls.getString(k)))
    except Exception as e:
        print('LayerSelection set', k, v, 'FAIL', str(e).replace(chr(10), ' ')[:300])
mat = comp.material().create('mat2', 'Common'); mat.selection().geom('geom1', 2); mat.selection().all()
print('material prop groups before:', [str(x.tag()) for x in mat.propertyGroup()])
for typ in ('Shell', 'shell', 'Layer', 'LayerThickness'):
    try:
        pg = mat.propertyGroup().create('shell', typ); print('created material group', typ, 'props', [str(x) for x in pg.properties()]); break
    except Exception as e:
        print('mat group', typ, 'FAIL', str(e).replace(chr(10), ' ')[:150])
for typ in ('SingleLayerMaterial', 'LayeredMaterial', 'LayeredMaterialLink'):
    try:
        x = comp.material().create('sl_' + typ, typ); print('created', typ, 'props', [str(p) for p in x.properties()][:30])
    except Exception as e:
        print('create', typ, 'FAIL', str(e).replace(chr(10), ' ')[:150])
