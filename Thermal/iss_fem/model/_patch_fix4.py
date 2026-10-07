# one-off patch: JEM-EF passive, box/rack effective conductivity, near-equilibrium initial temperatures;
# run-driver overrides so models built earlier pick these up without a rebuild
p = 'iss_spec.py'
s = open(p, encoding='utf-8').read()
rep = [
    ("""    ('JEMEF', (11.962, -16.340, 7.150), (5.0, 5.6, 3.5), 3000.0, ('B', 'T_MTL', '-z')),""",
     """    ('JEMEF', (11.962, -16.340, 7.150), (5.0, 5.6, 3.5), 3000.0, None),   # passive like the ELCs: a cold plate at 17 C on a
    #                                                                          freely radiating block turned it into a 7 kW sink of loop B"""),
    ("""    'oru_eq':   dict(kind='solid', classes=['box'], label='external ORU / IEA, equivalent solid (IEA 7.7 t in 21.6 m3)', k=10.0, rho=300.0, cp=900.0),""",
     """    # electronics sit on Al base plates bolted to the cold plates: nearly isothermal box, k 150 (D)
    'oru_eq':   dict(kind='solid', classes=['box'], label='external ORU / IEA, equivalent solid (IEA 7.7 t in 21.6 m3)', k=150.0, rho=300.0, cp=900.0),"""),
    ("""    'rack_eq':  dict(kind='solid', classes=['rack'], label='payload / system rack, equivalent solid', k=10.0, rho=400.0, cp=900.0),""",
     """    'rack_eq':  dict(kind='solid', classes=['rack'], label='payload / system rack, equivalent solid', k=50.0, rho=400.0, cp=900.0),"""),
    ("""T_INIT = dict(rack=298.0, box=283.0, payload=283.0, truss=253.0, skin_usos=268.0, skin_rus=268.0,""",
     """# racks: T_MTL + Q/(h_cp*A) = 290.15 + 500/(40*1.8) ~ 297.5 K; LT racks start at 284 K (T_INIT_RACK_LT)
T_INIT_RACK_LT = 284.0
T_INIT = dict(rack=297.5, box=285.0, payload=255.0, truss=253.0, skin_usos=268.0, skin_rus=268.0,"""),
]
for a, b in rep:
    assert a in s, a[:60]
    s = s.replace(a, b)
open(p, 'w', encoding='utf-8').write(s)

p = 'iss_run.py'
s = open(p, encoding='utf-8').read()
old = """    SOL.log('overrides applied: k_c', S.PARAMS['k_c'][0], 'f_init A', rows['f_A'][2], 'T_init hrs', S.T_INIT['hrs'])"""
new = """    # materials (thermal conductivity etc.) from the spec
    for mname, mm in S.MATERIALS.items():
        try:
            pg = comp.material('mat_' + mname).propertyGroup('def')
            pg.set('thermalconductivity', [str(mm['k'])]); pg.set('density', str(mm['rho'])); pg.set('heatcapacity', str(mm['cp']))
        except Exception:
            pass
    # cold plates that the current layout no longer has (JEM-EF) are switched off
    cooled = set(b['name'] for b in lay['blocks'] if b.get('cool'))
    ht = comp.physics('ht')
    for f in ht.feature():
        tg = str(f.tag())
        if tg.startswith('cp_') and tg[3:] not in cooled:
            f.active(False); SOL.log('cold plate switched off:', tg)
    # LT racks get their own initial temperature
    lt = [b['name'] for b in lay['blocks'] if b['cls'] == 'rack' and b['cool']['T'] == 'T_LTL']
    if lt:
        try: f = ht.feature('init_rack_lt')
        except Exception:
            u = comp.selection().create('sel_rack_lt', 'Union'); u.set('entitydim', '3'); u.set('input', ['sd_' + n for n in lt])
            f = ht.create('init_rack_lt', 'init', 3); f.selection().named('sel_rack_lt')
        f.set('Tinit', f'{S.T_INIT_RACK_LT}[K]')
    SOL.log('overrides applied: k_c', S.PARAMS['k_c'][0], 'f_init A', rows['f_A'][2], 'T_init hrs', S.T_INIT['hrs'], 'LT racks', len(lt))"""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
