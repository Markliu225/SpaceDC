import mph
c = mph.start(cores=1); m = c.load(r'C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol\iss_nom0.mph'); j = m.java
for sol in j.sol():
    if str(sol.study()) != 'stdO': continue
    for f in sol.feature():
        if str(f.getType()) != 'Time': continue
        print('==', sol.tag(), f.tag())
        for g in f.feature():
            print('  ', str(g.tag()), str(g.getType()))
            if str(g.getType()) == 'Segregated':
                for k in ('maxsegiter', 'segterm', 'segaaccel'):
                    try: print('     ', k, '=', str(g.getString(k)))
                    except Exception: pass
                for ss in g.feature():
                    try: vars_ = [str(x) for x in ss.getStringArray('segvar')]
                    except Exception: vars_ = []
                    print('     ', str(ss.tag()), str(ss.getType()), vars_[:12])
