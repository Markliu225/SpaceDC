# one-off patch: radiator TRRJ zero pose, researched optics/materials, per-case radiator law
p = 'iss_spec.py'
s = open(p, encoding='utf-8').read()


def rep_block(s, start, end, new):
    i = s.index(start); k = s.index(end, i)
    return s[:i] + new + s[k:]


s = rep_block(s, "# EATCS radiator wings: 3 ORUs side by side along Y", "# PVR: Y-Z plane, hanging nadir", '''# EATCS radiator wings. The TRRJ axis is parallel to X through (|Y| 14.68, Z 0) (docs/ISS_TRUSS_ARTICULATION.md 1:
# NASA TopCoder ISS coordinate model T2, IGOAL joint axes, ISAG clearance analysis). Reference pose =
# TRRJ zero: beam vertical, the three ORUs stacked along Z (centre distance 3.89 m), each extending
# aft from X -1.26 to -23.25 (G3D), panels in the X-Z plane, normal +/-Y. 8 panels per ORU along X (A p14).
HRS = dict(x_root=-1.26, x_tip=-23.25, y_abs=14.68, width=3.4, pitch=3.89, n_panels=8, gap=0.05,
           orus={'S1-1': (+1, -1), 'S1-2': (+1, 0), 'S1-3': (+1, +1), 'P1-1': (-1, -1), 'P1-2': (-1, 0), 'P1-3': (-1, +1)})
''')
s = s.replace("""PVR = dict(width=3.12, z_top=4.02, z_bot=15.19, n_panels=7, gap=0.05,
           units={'P4': (-0.35, -29.464), 'P6': (-0.35, -44.548), 'S4': (0.35, 29.464), 'S6': (0.35, 44.531)})""",
              """PVR = dict(width=3.12, z_top=4.02, z_bot=15.19, n_panels=7, gap=0.05,   # panel region Z from G3D; width A p3
           units={'P4': (-0.35, -29.49), 'P6': (-0.35, -44.525), 'S4': (0.35, 29.445), 'S6': (0.35, 44.555)})   # Y centres T2""")
s = s.replace("""SAW = dict(blanket_w=4.70, gap=2.29, x_in=3.30, x_len=32.83,""",
              """SAW = dict(blanket_w=4.752, gap=1.928, x_in=3.32, x_len=32.51,      # T2: blanket 32.51 x 4.752 m, gap 1.928 m, from |X| 3.32""")
s = rep_block(s, "OPTICS = {   # PROVISIONAL", "# ======================================================================= materials", '''OPTICS = {   # docs/ISS_OPTICS_MATERIALS.md item numbers in brackets
    'z93':       dict(alpha=0.20, eps=0.91),   # nominal aged Z-93/Z-93P: BOL 0.15/0.91 [2.1, 2.2], contaminated + VUV 0.21-0.24 [2.11]
    'skin_usos': dict(alpha=0.30, eps=0.45),   # chromic-anodized Al 6061 MMOD bumper [5.9-5.11]
    'skin_rus':  dict(alpha=0.31, eps=0.90),   # no public value [10.4]; aluminized beta cloth taken (D) [5.15]
    'truss':     dict(alpha=0.49, eps=0.85),   # sulfuric anodize [6.1, 6.2]
    'box':       dict(alpha=0.31, eps=0.90),   # ORU MLI outer layer, aluminized beta cloth [5.15, 6.4]
    'payload':   dict(alpha=0.31, eps=0.90),   # same outer layer (D)
    # US solar array: no public alpha/eps [10.2]; cell side 0.72 typical Si cell + coverglass (D) minus the
    # blanket-average electrical conversion 31 kW / (309 m2 x 1371 W/m2) = 0.073 [4.11] (derived)
    'saw_cells': dict(alpha=0.72 - 0.073, eps=0.82),
    'saw_back':  dict(alpha=0.55, eps=0.85),   # polyimide / glass-fibre substrate (D)
    'rsa_cells': dict(alpha=0.72 - 0.07, eps=0.82),
    'rsa_back':  dict(alpha=0.55, eps=0.85),
}
# case-dependent radiator coating: cold case BOL, hot case contaminated/aged nominal EOL (O37 practice [11.2])
OPTICS_BY_CASE = {'cold0': {'z93': dict(alpha=0.15, eps=0.91)}, 'hot75': {'z93': dict(alpha=0.24, eps=0.90)}}

''')
s = rep_block(s, "MATERIALS = {", "# ======================================================================= geometry (G3D unless noted)", '''MATERIALS = {   # docs/ISS_OPTICS_MATERIALS.md items in brackets; shells: rho*cp*t = areal heat capacity, k*t = in-plane conductance
    'al_skin_usos': dict(kind='shell', classes=['skin_usos'], label='MMOD bumper Al 6061-T6 2.0 mm [5.1, 8.4-8.6]', k=152.0, rho=2713.0, cp=875.0, t=2.0e-3),
    'al_skin_rus':  dict(kind='shell', classes=['skin_rus'], label='MMOD bumper AMG-6 1.0 mm [7.2]', k=120.0, rho=2640.0, cp=920.0, t=1.0e-3),
    # HRS/PVR panel: two 0.254 mm Al facesheets [3.1] + Al honeycomb + Inconel/steel tubes; panel areal mass 8 kg/m2
    # taken (ORU envelope 14.2 kg/m2 incl. deployment mechanism [3.6]) -> t 2.5 mm, rho 3200; k*t = 2 x 0.254 mm x 152 = 0.077 W/K
    'hrs_pan':  dict(kind='shell', classes=['hrs'], label='HRS panel, equivalent shell', k=31.0, rho=3200.0, cp=900.0, t=2.5e-3),
    'pvr_pan':  dict(kind='shell', classes=['pvr'], label='PVR panel, equivalent shell', k=31.0, rho=3200.0, cp=900.0, t=2.5e-3),
    # blanket: 200 um Si + 125 um coverglass + 125 um substrate + Cu [4.1-4.4]; areal heat capacity 1.6 kJ/m2K sized so the
    # eclipse-exit warm-up from -80 C to 0 C takes about 3 min [4.8] (derived: 0.66*1371*180 s / 80 K ~ 2 kJ/m2K)
    'saw_blk':  dict(kind='shell', classes=['saw', 'rsa'], label='solar array blanket, equivalent shell', k=5.0, rho=2000.0, cp=800.0, t=1.0e-3),
    # truss envelope: open lattice -> low k; rho = structure mass left after arrays, PVRs, radiators and IEAs are
    # removed (111 t segment masses, truss doc 2, minus 52 t) over the 1609 m3 of modelled boxes = 37 kg/m3 (derived)
    'truss_eq': dict(kind='solid', classes=['truss'], label='truss envelope, equivalent solid', k=1.0, rho=37.0, cp=850.0),
    'oru_eq':   dict(kind='solid', classes=['box'], label='external ORU / IEA, equivalent solid (IEA 7.7 t in 21.6 m3)', k=10.0, rho=300.0, cp=900.0),
    'pl_eq':    dict(kind='solid', classes=['payload'], label='external payload carrier, equivalent solid', k=10.0, rho=150.0, cp=900.0),
    'rack_eq':  dict(kind='solid', classes=['rack'], label='payload / system rack, equivalent solid', k=10.0, rho=400.0, cp=900.0),
}

''')
s = s.replace("""    'h_mli':    ('0.12[W/(m^2*K)]', 'MLI effective conductance cabin wall -> MMOD shield (R/D)'),""",
              """    'h_mli':    ('0.22[W/(m^2*K)]', 'MLI e* = 0.05 [optics 5.13] linearised: 4*e*sigma*Tm^3 at Tm 270 K (derived)'),""")
s = s.replace("""    'cp_nh3':   ('4.70[kJ/(kg*K)]', 'liquid ammonia specific heat near 0 C (R)'),""",
              """    'cp_nh3':   ('4.61[kJ/(kg*K)]', 'liquid NH3 at 2.8 C, 300 psia: 4612.6 J/kgK (NIST, optics doc 8.13)'),""")
s = rep_block(s, "    # EATCS radiators: panels in the X-Y plane at z", "    P_ = PVR", '''    # EATCS radiators, TRRJ zero pose: panels in the X-Z plane at y = +/-14.68 (work plane zx: u = z, v = x); ORUs stacked along Z
    H = HRS
    Ltot = abs(H['x_tip'] - H['x_root']); lp = (Ltot - (H['n_panels'] - 1) * H['gap']) / H['n_panels']
    for oru, (side, kz) in H['orus'].items():
        loop = 'A' if side > 0 else 'B'
        zc = kz * H['pitch']; members = []
        for i in range(H['n_panels']):
            x1 = H['x_root'] - i * (lp + H['gap']); x0 = x1 - lp
            nm = f"hrs_{oru.replace('-', '_')}_{i + 1}"
            panels.append(dict(name=nm, label=f'EATCS radiator {oru} panel {i + 1}', cls='hrs', plane='zx', offset=side * H['y_abs'],
                               u0=zc - H['width'] / 2, v0=x0, du=H['width'], dv=lp, group='hrs',
                               fluid=dict(loop=loop, oru=oru, idx=i + 1)))
            members.append(nm)
        pgroups['HRS_' + oru] = members
''')
old_cases = s[s.index("    'cold0':  dict(beta_deg=0.0"):s.index("}\nfor _c in CASES.values():")]
s = s.replace(old_cases, """    # hrs_law: 'zero'  = TRRJ held at zero in daylight (edge to Sun for every orbit angle when beta = 0), face to Earth in eclipse
    #          'track' = TRRJ rolls about X to keep the Sun in the panel plane (beta != 0), face to Earth in eclipse
    'cold0':  dict(beta_deg=0.0,  S_sun=1321.0, albedo=0.20, olr=206.0, hrs_law='zero',  label='设计冷工况 beta 0'),
    'hot75':  dict(beta_deg=75.0, S_sun=1423.0, albedo=0.40, olr=286.0, hrs_law='track', label='设计热工况 beta 75'),
    'nom0':   dict(beta_deg=0.0,  S_sun=1371.0, albedo=0.31, olr=241.0, hrs_law='zero',  label='平均环境 beta 0'),
    'nom60':  dict(beta_deg=60.0, S_sun=1371.0, albedo=0.39, olr=241.0, hrs_law='track', label='平均环境 beta 60'),
""")
open(p, 'w', encoding='utf-8').write(s)
print('patched')
