p = 'iss_layout.py'
s = open(p, encoding='utf-8').read()
# flow uses the smoothly bounded fraction f_eff = f_min + softplus(f - f_min)
old = """                eq = f"C_f*{tf}t-((f_{L}*{mdot}/{len(d['orus'])})*{cp}*({prev}-{tf})-ip_{p['name']}({p['fluid']['qexpr']}))\""""
new = """                eq = f"C_f*{tf}t-((feff_{L}*{mdot}/{len(d['orus'])})*{cp}*({prev}-{tf})-ip_{p['name']}({p['fluid']['qexpr']}))\""""
assert old in s; s = s.replace(old, new)
old = """        gv[f'Tmix_{L}'] = f"f_{L}*Tout_{L}+(1-f_{L})*Tret_{L}"
        rows.insert(0, (f'f_{L}', f"k_c*f_{L}t-(Tmix_{L}-{Tset})", str(d.get('f_init', 0.3)), f'{L}: radiator flow fraction, integral control of the mixed supply temperature', 'f'))"""
new = """        # radiator flow fraction: valve travel bounded below by f_min (fully bypassed valve) with a smooth
        # softplus; anti-windup pulls the integrator back when it runs below f_min (low loop load)
        gv[f'feff_{L}'] = f"f_min+s_f*log(1+exp((f_{L}-f_min)/s_f))"
        gv[f'Tmix_{L}'] = f"feff_{L}*Tout_{L}+(1-feff_{L})*Tret_{L}"
        rows.insert(0, (f'f_{L}', f"k_c*f_{L}t-(Tmix_{L}-{Tset})+k_aw*s_f*log(1+exp((f_min-f_{L})/s_f))", str(d.get('f_init', 0.3)),
                        f'{L}: radiator flow fraction, integral control of the mixed supply temperature', 'f'))"""
assert old in s; s = s.replace(old, new)
old = """        gv[f'Qrad_{L}'] = f"f_{L}*{mdot}*{cp}*(Tret_{L}-Tout_{L})\""""
new = """        gv[f'Qrad_{L}'] = f"feff_{L}*{mdot}*{cp}*(Tret_{L}-Tout_{L})\""""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
p = 'iss_spec.py'
s = open(p, encoding='utf-8').read()
old = """    'k_c':      ('600[K*s]', 'mixing-valve integral gain: 10 K supply error changes the radiator fraction by 1/60 per s (D)'),"""
new = old + """
    'f_min':    ('0.02', 'lower bound of the radiator flow fraction, valve fully on bypass (D)'),
    's_f':      ('0.01', 'smoothing width of the flow-fraction bound (numerical, D)'),
    'k_aw':     ('200[K]', 'anti-windup gain of the valve integrator below f_min (numerical, D)'),"""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
