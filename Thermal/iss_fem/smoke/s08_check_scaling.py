import mph
c = mph.start(cores=2); m = c.load(r'C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol\iss_nom0_lite.mph'); j = m.java
for sol in j.sol():
    print('sol', str(sol.tag()), 'study', str(sol.study()))
    for f in sol.feature():
        if str(f.getType()) == 'Variables':
            print('  ', str(f.tag()), [(str(c_.tag()), str(c_.getString('scalemethod')), str(c_.getString('scaleval'))) for c_ in f.feature() if not 'band' in str(c_.tag())])
