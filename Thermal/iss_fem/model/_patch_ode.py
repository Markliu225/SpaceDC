# one-off patch: loop equations as ODEs (no algebraic constraints for the consistent initialisation)
#   Qc_L : tau_Q * dQc/dt = sum(pick-ups) - Qc                    (heat collected, 20 s lag)
#   Tf   : C_f * dTf/dt   = mcp_path*(Tprev - Tf) - Q_panel         (NH3 node per panel, 1 kJ/K)
#   f_L  : k_c * df/dt    = T_mix - T_set,  T_mix = f*Tout + (1-f)*Tret   (integral control of the mixing valve)
p = 'iss_layout.py'
s = open(p, encoding='utf-8').read()
old = """        qrows.append((f'Qc_{L}', f'Qc_{L}-({expr})', '20[kW]' if not L.startswith('PV') else '6[kW]', f'{L}: heat collected by the loop (cold plates, IFHX)', 'Q'))"""
new = """        qrows.append((f'Qc_{L}', f'tau_Q*Qc_{L}t-(({expr})-Qc_{L})', '24[kW]' if not L.startswith('PV') else '6[kW]', f'{L}: heat collected by the loop (cold plates, IFHX), 20 s lag', 'Q'))"""
assert old in s; s = s.replace(old, new)
old = """                eq = f"(f_{L}*{mdot}/{len(d['orus'])})*{cp}*({prev}-{tf})-ip_{p['name']}({p['fluid']['qexpr']})\""""
new = """                eq = f"C_f*{tf}t-((f_{L}*{mdot}/{len(d['orus'])})*{cp}*({prev}-{tf})-ip_{p['name']}({p['fluid']['qexpr']}))\""""
assert old in s; s = s.replace(old, new)
old = """        rows.insert(0, (f'f_{L}', f"f_{L}*(Tret_{L}-Tout_{L})-(Tret_{L}-{Tset})", str(d.get('f_init', 0.3)), f'{L}: radiator flow fraction (bypass mixing to set point)', 'f'))"""
new = """        gv[f'Tmix_{L}'] = f"f_{L}*Tout_{L}+(1-f_{L})*Tret_{L}"
        rows.insert(0, (f'f_{L}', f"k_c*f_{L}t-(Tmix_{L}-{Tset})", str(d.get('f_init', 0.3)), f'{L}: radiator flow fraction, integral control of the mixed supply temperature', 'f'))"""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)

p = 'iss_spec.py'
s = open(p, encoding='utf-8').read()
old = """    'T_init_solid': ('273.15[K]', 'initial temperature, solids'),"""
new = """    'tau_Q':    ('20[s]', 'lag of the collected-heat state (numerical, D)'),
    'C_f':      ('1[kJ/K]', 'NH3 node heat capacity per radiator panel: 22 tubes x 2.7 m of liquid NH3 plus tube wall (D)'),
    'k_c':      ('600[K*s]', 'mixing-valve integral gain: 10 K supply error changes the radiator fraction by 1/60 per s (D)'),
    'T_init_solid': ('273.15[K]', 'initial temperature, solids'),"""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
