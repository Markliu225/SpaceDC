p = 'iss_build.py'
s = open(p, encoding='utf-8').read()
old = """        for c in lay['cylinders']:
            f = g.feature().create('cy_' + c['name'], 'Cylinder')
            f.set('type', 'surface'); f.set('r', str(c['R'])); f.set('h', str(c['L']))
            f.set('pos', [float(v) for v in c['p0']]); f.set('axistype', c['axis'])
            f.set('contributeto', self._csel(c['cls'])); f.label(c['label'])"""
new = """        # module skins: solid cylinders converted to CLOSED surfaces (a surface-type Cylinder has no end caps)
        by_cls = {}
        for c in lay['cylinders']:
            f = g.feature().create('cy_' + c['name'], 'Cylinder')
            f.set('r', str(c['R'])); f.set('h', str(c['L']))
            f.set('pos', [float(v) for v in c['p0']]); f.set('axistype', c['axis']); f.label(c['label'])
            by_cls.setdefault(c['cls'], []).append('cy_' + c['name'])
        for cls, objs in by_cls.items():
            cv = g.feature().create('cv_' + cls, 'ConvertToSurface'); cv.selection('input').set(objs)
            cv.set('contributeto', self._csel(cls)); cv.label('closed skins ' + cls)"""
assert old in s; s = s.replace(old, new)
old = """                if oc.get('two_sided'):"""
new = """                if oc.get('direction'):
                    # radiate from one side only (module skins: outward normal = RadiationDirectionPlus, checked
                    # in smoke s10c); no radiosity unknowns inside the closed skin, no singular reflecting enclosure
                    d.set('radDirectionTypeSolAmb', oc['direction'])
                    d.set('epsilon_radSolAmb_mat', 'userdefBand'); d.set('epsilon_rad_bandSolAmb', oc['both'])
                elif oc.get('two_sided'):"""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)

p = 'iss_layout.py'
s = open(p, encoding='utf-8').read()
old = """        'body': [dict(name='skin_usos', classes=['skin_usos'], label='USOS module MMOD shield (outside only)', two_sided=True,
                      up=_opt(O['skin_usos']), down=['0', '0']),
                 dict(name='skin_rus', classes=['skin_rus'], label='Russian module thermal blanket (outside only)', two_sided=True,
                      up=_opt(O['skin_rus']), down=['0', '0']),"""
new = """        'body': [dict(name='skin_usos', classes=['skin_usos'], label='USOS module MMOD shield (outward side only)', direction='RadiationDirectionPlus',
                      both=_opt(O['skin_usos'])),
                 dict(name='skin_rus', classes=['skin_rus'], label='Russian module outer surface (outward side only)', direction='RadiationDirectionPlus',
                      both=_opt(O['skin_rus'])),"""
assert old in s; s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
