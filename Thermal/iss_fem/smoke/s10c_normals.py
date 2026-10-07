import mph
c = mph.start(cores=2); m = c.load('s04.mph'); j = m.java
for ds in ('dset1', 'dset2'):
    for expr in ('y*nx*0+y*ny+(z+6[m])*nz', 'nx', 'y*htlsh.nuy+(z+6[m])*htlsh.nuz', 'x'):
        try:
            n = j.result().numerical().create('ev', 'AvSurface'); n.set('data', ds); n.selection().named('sSkin'); n.set('expr', [expr]); n.set('innerinput', 'first')
            print(ds, expr, [float(v) for v in n.getReal()[0]][:3]); j.result().numerical().remove('ev')
        except Exception as e:
            print(ds, expr, 'ERR', str(e).replace(chr(10), ' ')[:160])
            try: j.result().numerical().remove('ev')
            except Exception: pass
    break
