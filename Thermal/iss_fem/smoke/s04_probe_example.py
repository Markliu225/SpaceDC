import mph
c = mph.start(cores=2)
base = r"D:\Program Files\COMSOL\COMSOL63\Multiphysics\applications\Heat_Transfer_Module\Tutorials,_Thin_Structure"
for fn in ('shell_conduction.mph', 'thin_plate.mph'):
    m = c.load(base + chr(92) + fn); j = m.java
    comp = j.component('comp1')
    print('=====', fn)
    for p in comp.physics():
        print('physics tag', str(p.tag()), 'type', str(p.getType()), 'name', str(p.name()) if hasattr(p, 'name') else '')
        for f in p.feature():
            print('   feature', str(f.tag()), str(f.getType()))
        for grp in ('ShellProperties', 'PhysicalModel'):
            try:
                pg = p.prop(grp); names = [str(x) for x in pg.properties()]
                print('   prop', grp, {n: str(pg.getString(n))[:40] for n in names})
            except Exception as e:
                pass
    for mp in comp.multiphysics():
        print('mp', str(mp.tag()), str(mp.getType()))
    c.remove(m)
