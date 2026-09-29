# one-off patch: verification corrections (VERIFY docs): ISS-batch beta cloth optics, MMOD envelope
# diameters of Destiny/Unity (JSC 26557 R2223 mm), Zvezda max diameter 4.25 m (R2125 mm), re-seat
p = 'iss_spec.py'
s = open(p, encoding='utf-8').read()
rep = [
    ("    'skin_rus':  dict(alpha=0.31, eps=0.90),   # no public value [10.4]; aluminized beta cloth taken (D) [5.15]",
     "    'skin_rus':  dict(alpha=0.36, eps=0.87),   # no public value [10.4]; ISS-batch aluminized beta cloth BOL taken (optics verification)"),
    ("    'box':       dict(alpha=0.31, eps=0.90),   # ORU MLI outer layer, aluminized beta cloth [5.15, 6.4]",
     "    'box':       dict(alpha=0.36, eps=0.87),   # ORU MLI outer layer, ISS-batch aluminized beta cloth BOL (optics verification; 0.41-0.42 after MISSE-6)"),
    ("    'payload':   dict(alpha=0.31, eps=0.90),   # same outer layer (D)",
     "    'payload':   dict(alpha=0.36, eps=0.87),   # same outer layer (D)"),
    ("    ('destiny', 'Destiny US Lab', 'x', (2.120, 0.0, Z_USOS), 8.50, 4.30, 'skin_usos'),          # RG p49",
     "    ('destiny', 'Destiny US Lab', 'x', (2.120, 0.0, Z_USOS), 8.50, 4.45, 'skin_usos'),          # RG p49; MMOD envelope 4.45 (IGOAL, data book)"),
    ("    ('unity', 'Unity Node 1', 'x', (-5.023, 0.0, Z_USOS), 5.50, 4.30, 'skin_usos'),            # RG p53",
     "    ('unity', 'Unity Node 1', 'x', (-5.023, 0.0, Z_USOS), 5.50, 4.45, 'skin_usos'),            # RG p53; envelope R2223 mm (JSC 26557)"),
    ("    ('tranquility', 'Tranquility Node 3', 'y', (-5.023, -5.553, Z_USOS), 6.706, 4.48, 'skin_usos'),   # ESA factsheet",
     "    ('tranquility', 'Tranquility Node 3', 'y', (-5.023, -5.628, Z_USOS), 6.706, 4.48, 'skin_usos'),   # ESA factsheet"),
    ("    ('quest', 'Quest airlock', 'y', (-5.023, 4.950, Z_USOS), 5.50, 4.00, 'skin_usos'),         # RG p56",
     "    ('quest', 'Quest airlock', 'y', (-5.023, 5.025, Z_USOS), 5.50, 4.00, 'skin_usos'),         # RG p56"),
    ("    ('pmm', 'Leonardo PMM', 'x', (0.602, -6.681, Z_USOS), 6.67, 4.57, 'skin_usos'),           # RG p58",
     "    ('pmm', 'Leonardo PMM', 'x', (0.602, -6.756, Z_USOS), 6.67, 4.57, 'skin_usos'),           # RG p58"),
    ("    ('beam', 'BEAM', 'x', (-9.319, -6.681, Z_USOS), 4.011, 3.23, 'skin_usos'),                 # NASA facts",
     "    ('beam', 'BEAM', 'x', (-9.319, -6.756, Z_USOS), 4.011, 3.23, 'skin_usos'),                 # NASA facts"),
    ("    ('cupola', 'Cupola', 'z', (-5.023, -6.733, 7.890), 1.50, 2.955, 'skin_usos'),              # ESA",
     "    ('cupola', 'Cupola', 'z', (-5.023, -6.808, 7.890), 1.50, 2.955, 'skin_usos'),              # ESA"),
    ("    ('zvezda_a', 'Zvezda SM large-diameter section', 'x', (-32.759, 0.0, 4.264), 6.15, 4.20, 'skin_rus'),",
     "    ('zvezda_a', 'Zvezda SM large-diameter section', 'x', (-32.759, 0.0, 4.264), 6.15, 4.25, 'skin_rus'),   # R2125 mm (JSC 26557)"),
]
for a, b in rep:
    assert a in s, a[:60]
    s = s.replace(a, b)
open(p, 'w', encoding='utf-8').write(s)
print('patched')
