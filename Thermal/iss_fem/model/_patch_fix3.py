# one-off patch: anti-windup sign, MLI-covered ORU optics, MLI conductance calibrated to the Node 3 shell leak,
# and a run-driver override that re-applies the loop equations and optics to models built earlier
p = 'iss_layout.py'
s = open(p, encoding='utf-8').read()
old = """        rows.insert(0, (f'f_{L}', f"k_c*f_{L}t-(Tmix_{L}-{Tset})+k_aw*s_f*log(1+exp((f_min-f_{L})/s_f))", str(d.get('f_init', 0.3)),"""
new = """        rows.insert(0, (f'f_{L}', f"k_c*f_{L}t-(Tmix_{L}-{Tset})-k_aw*s_f*log(1+exp((f_min-f_{L})/s_f))", str(d.get('f_init', 0.3)),"""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)

p = 'iss_spec.py'
s = open(p, encoding='utf-8').read()
rep = [
    ("""    'box':       dict(alpha=0.36, eps=0.87),   # ORU MLI outer layer, ISS-batch aluminized beta cloth BOL (optics verification; 0.41-0.42 after MISSE-6)""",
     """    # ORUs and IEAs are wrapped in MLI [optics 6.4]: the block stands for the electronics BEHIND the blanket, so its
    # surface exchanges radiation through the MLI: eps* 0.03 (42-layer class), alpha = eps* x (beta cloth 0.36/0.87) (derived)
    'box':       dict(alpha=0.012, eps=0.03),"""),
    ("""    'h_mli':    ('0.22[W/(m^2*K)]', 'MLI e* = 0.05 [optics 5.13] linearised: 4*e*sigma*Tm^3 at Tm 270 K (derived)'),""",
     """    'h_mli':    ('0.08[W/(m^2*K)]', 'MLI conductance from the Node 3 shell leak: -720 W over 126 m2 at ~70 K cabin-to-shield difference (loads doc, Wise & Holt 2001; derived)'),"""),
]
for a, b in rep:
    assert a in s, a[:60]
    s = s.replace(a, b)
open(p, 'w', encoding='utf-8').write(s)

p = 'iss_run.py'
s = open(p, encoding='utf-8').read()
old = """        for i, n in enumerate(names):
            if n in rows:
                g.setIndex('initialValueU', rows[n][2], i)"""
new = """        for i, n in enumerate(names):
            if n in rows:
                g.setIndex('initialValueU', rows[n][2], i)
                g.setIndex('equation', rows[n][1], i)
    for k, v in lay['global_vars'].items():
        comp.variable('var_loops').set(k, v)
    # optics of every class-specific diffuse surface, from the current spec
    for gname, ocs in lay['optics_by_group'].items():
        try: o = comp.physics('otl_' + gname)
        except Exception: continue
        for oc in ocs:
            try: d = o.feature('ds_' + oc['name'])
            except Exception: continue
            if oc.get('two_sided'):
                d.set('epsilon_radu_bandSolAmb', oc['up']); d.set('epsilon_radd_bandSolAmb', oc['down'])
            else:
                d.set('epsilon_rad_bandSolAmb', oc['both'])"""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
