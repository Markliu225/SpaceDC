# one-off patch: gentler valve integrator, steady-state initial guesses, no group merge
p = 'iss_spec.py'
s = open(p, encoding='utf-8').read()
rep = [
    ("""    'k_c':      ('600[K*s]', 'mixing-valve integral gain: 10 K supply error changes the radiator fraction by 1/60 per s (D)'),""",
     """    'k_c':      ('3000[K*s]', 'mixing-valve integral gain: closed-loop time constant k_c/|dTmix/df| ~ 3000/25 = 120 s, below the 16 min panel time constant (D)'),"""),
    ("""    'k_aw':     ('200[K]', 'anti-windup gain of the valve integrator below f_min (numerical, D)'),""",
     """    'k_aw':     ('50[K]', 'anti-windup gain of the valve integrator below f_min (numerical, D)'),"""),
    ("""        'A': dict(mdot='mdot_A', T_set='T_setA', g='g_hrs', orus=['S1-1', 'S1-2', 'S1-3'], f_init=0.3),
        'B': dict(mdot='mdot_B', T_set='T_setB', g='g_hrs', orus=['P1-1', 'P1-2', 'P1-3'], f_init=0.3),""",
     """        # f_init: steady-state estimate f = (Tret - Tset)/(Tret - Tout) with a 5 K loop rise and a ~30 K radiator drop
        'A': dict(mdot='mdot_A', T_set='T_setA', g='g_hrs', orus=['S1-1', 'S1-2', 'S1-3'], f_init=0.2),
        'B': dict(mdot='mdot_B', T_set='T_setB', g='g_hrs', orus=['P1-1', 'P1-2', 'P1-3'], f_init=0.2),"""),
    ("""    LOOPS['loops']['PV' + _m] = dict(mdot='mdot_pv', T_set='T_set_pv', g='g_pvr', orus=['PVR_' + _m], f_init=0.5)""",
     """    LOOPS['loops']['PV' + _m] = dict(mdot='mdot_pv', T_set='T_set_pv', g='g_pvr', orus=['PVR_' + _m], f_init=0.3)"""),
    ("""              hrs=255.0, pvr=260.0, saw=290.0, rsa=290.0)""", """              hrs=262.0, pvr=262.0, saw=290.0, rsa=290.0)"""),
]
for a, b in rep:
    assert a in s, a[:70]
    s = s.replace(a, b)
open(p, 'w', encoding='utf-8').write(s)

p = 'iss_run.py'
s = open(p, encoding='utf-8').read()
old = """                f.set('tstepsbdf', 'manual'); f.set('timestepbdf', str(a.dt)); f.set('maxorder', '1')
                configure_segregated(f)"""
new = """                f.set('tstepsbdf', 'manual'); f.set('timestepbdf', str(a.dt)); f.set('maxorder', '1')
                for g in f.feature():
                    if str(g.getType()) == 'Segregated':
                        g.set('maxsegiter', '25')
    apply_overrides(j, lay)"""
assert old in s; s = s.replace(old, new)
old = """def main():"""
new = '''def apply_overrides(j, lay):
    """Push the current iss_spec parameters, loop initial values and class initial temperatures into a
    model built with older values (so a model file does not have to be rebuilt for such changes)."""
    for k, (v, d) in S.PARAMS.items():
        j.param().set(k, v, d)
    comp = j.component('comp1'); ge = comp.physics('ge')
    rows = {r[0]: r for r in lay['ge_rows']}
    for g in ge.feature():
        if str(g.getType()) != 'GlobalEquations': continue
        names = [str(x) for x in g.getStringArray('name')]
        for i, n in enumerate(names):
            if n in rows:
                g.setIndex('initialValueU', rows[n][2], i)
    for cls, T0 in S.T_INIT.items():
        for iface in ('ht', 'htlsh'):
            try:
                comp.physics(iface).feature('init_' + cls).set('Tinit', f'{T0}[K]')
            except Exception:
                pass
    SOL.log('overrides applied: k_c', S.PARAMS['k_c'][0], 'f_init A', rows['f_A'][2], 'T_init hrs', S.T_INIT['hrs'])


def main():'''
assert old in s; s = s.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
