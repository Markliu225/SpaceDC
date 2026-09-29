p = 'iss_layout.py'
s = open(p, encoding='utf-8').read()
s = s.replace("""    'hrs': dict(label='OTL EATCS radiators: edge to Sun, face to Earth in eclipse',
                axes=('y', 'z'), orient=('antinormal', 'antisun'), default_optics=['0.2', '0.9'],
                eclipse=dict(axes=('y', 'x'), orient=('antinormal', 'nadir'))),""",
"""    # EATCS radiators: TRRJ rolls the wing about X. Reference pose = TRRJ zero (panel plane X-Z, normal +/-Y).
    # 'zero' law (beta 0): daylight = body attitude (edge to Sun at every orbit angle); 'track' law: model z points
    # away from the Sun projected on the plane normal to X (edge to Sun for any beta). Eclipse: normal (model y) to nadir.
    'hrs': dict(label='OTL EATCS radiators: edge to Sun in daylight, face to Earth in eclipse (TRRJ about X)',
                axes=('x', 'z'), orient=('velocity', 'nadir'), default_optics=['0.2', '0.9'],
                eclipse=dict(axes=('x', 'y'), orient=('velocity', 'nadir'))),""")
s = s.replace("""def optics_by_group():
    O = S.OPTICS""", """def optics_by_group(case=None):
    O = {k: dict(v) for k, v in S.OPTICS.items()}
    for k, v in S.OPTICS_BY_CASE.get(case, {}).items():
        O[k] = dict(v)""")
s = s.replace("""    lay['block_by_name'] = {b['name']: b for b in lay['blocks']}""", """    lay['block_by_name'] = {b['name']: b for b in lay['blocks']}
    groups = {k: dict(v) for k, v in GROUPS.items()}
    if C.get('hrs_law') == 'track':
        groups['hrs']['orient'] = ('velocity', 'antisun')
    lay['groups'] = groups
    lay['optics_by_group'] = optics_by_group(case)""")
open(p, 'w', encoding='utf-8').write(s)
p = 'iss_build.py'
s = open(p, encoding='utf-8').read()
s = s.replace("for gi, (gname, ginfo) in enumerate(LAY.GROUPS.items()):", "for gi, (gname, ginfo) in enumerate(lay['groups'].items()):")
s = s.replace("for oc in LAY.OPTICS_BY_GROUP[gname]:", "for oc in lay['optics_by_group'][gname]:")
open(p, 'w', encoding='utf-8').write(s)
print('ok')
