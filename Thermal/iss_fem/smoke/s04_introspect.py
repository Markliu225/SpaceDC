import mph
c = mph.start(cores=2); m = c.create('x'); j = m.java
comp = j.component().create('comp1', True); g = comp.geom().create('geom1', 3)
b = g.feature().create('b', 'Block'); b.set('type', 'surface'); g.run()
ht = comp.physics().create('ht', 'HeatTransfer', 'geom1')
sh = comp.physics().create('htlsh', 'HeatTransferInShellsLM', 'geom1')
for grp in ('LayerSelection', 'ds', 'PhysicalModelProperty'):
    pg = sh.prop(grp); names = [str(x) for x in pg.properties()]
    print('GROUP', grp)
    for n in names:
        try: print('   ', n, '=', str(pg.getString(n))[:80])
        except Exception:
            try: print('   ', n, '=', [str(x) for x in pg.getStringArray(n)][:6])
            except Exception: print('   ', n, '(err)')
print('dependent vars htlsh:', [str(x) for x in sh.field('temperature').component()] if True else '')
for cand in ('HeatFluxInterface', 'InterfaceHeatFlux', 'HeatFluxInt', 'LayerHeatFlux', 'HeatFlux'):
    for ed in (2, 1):
        try:
            f = sh.create('hf_' + cand + str(ed), cand, ed); print('CREATE OK', cand, 'edim', ed, 'props', [str(x) for x in f.properties()][:40]); break
        except Exception as e:
            print('create', cand, ed, 'FAIL', str(e).replace(chr(10), ' ')[:120])
for cand in ('HeatSource', 'LayerHeatSource', 'HeatSourceInterface'):
    try:
        f = sh.create('hs_' + cand, cand, 2); print('CREATE OK', cand, 'props', [str(x) for x in f.properties()][:40])
    except Exception as e:
        print('create', cand, 'FAIL', str(e).replace(chr(10), ' ')[:120])
