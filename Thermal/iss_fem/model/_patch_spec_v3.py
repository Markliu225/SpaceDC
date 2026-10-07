# one-off patch: module hull dimensions from primary sources (Reference Guide 2010, ESA, JAXA via
# docs research "modules_layout"), attachments re-seated at 5 cm from the parent hull
p = 'iss_spec.py'
s = open(p, encoding='utf-8').read()
i = s.index("MODULES = [  # name, label, axis, centre, length, diameter, class")
k = s.index("TRUSS = [")
s = s[:i] + '''MODULES = [  # name, label, axis, centre, length, diameter, class
    # hull length / diameter: Reference Guide to the ISS 2010 (RG), ESA and JAXA fact sheets (research
    # "modules_layout"); centres: G3D, consistent with the JSC 26557 Rev AB mass-property centres within
    # 0.5 m; attached modules re-seated 5 cm from the parent hull so that no hulls intersect
    ('destiny', 'Destiny US Lab', 'x', (2.120, 0.0, Z_USOS), 8.50, 4.30, 'skin_usos'),          # RG p49
    ('unity', 'Unity Node 1', 'x', (-5.023, 0.0, Z_USOS), 5.50, 4.30, 'skin_usos'),            # RG p53
    ('harmony', 'Harmony Node 2', 'x', (9.773, 0.0, Z_USOS), 6.706, 4.48, 'skin_usos'),        # ESA
    ('tranquility', 'Tranquility Node 3', 'y', (-5.023, -5.553, Z_USOS), 6.706, 4.48, 'skin_usos'),   # ESA factsheet
    ('columbus', 'Columbus', 'y', (10.855, 5.726, Z_USOS), 6.871, 4.477, 'skin_usos'),         # ESA
    ('kibo', 'Kibo JEM PM', 'y', (10.957, -7.890, Z_USOS), 11.20, 4.40, 'skin_usos'),          # JAXA Kibo Handbook T3.1-1
    ('elm', 'Kibo JEM ELM-PS', 'z', (11.093, -10.173, 0.500), 4.20, 4.40, 'skin_usos'),        # JAXA
    ('quest', 'Quest airlock', 'y', (-5.023, 4.950, Z_USOS), 5.50, 4.00, 'skin_usos'),         # RG p56
    ('pmm', 'Leonardo PMM', 'x', (0.602, -6.681, Z_USOS), 6.67, 4.57, 'skin_usos'),           # RG p58
    ('beam', 'BEAM', 'x', (-9.319, -6.681, Z_USOS), 4.011, 3.23, 'skin_usos'),                 # NASA facts
    ('cupola', 'Cupola', 'z', (-5.023, -6.733, 7.890), 1.50, 2.955, 'skin_usos'),              # ESA
    ('pma1', 'PMA-1', 'x', (-8.734, 0.0, 4.702), 1.82, 1.90, 'skin_usos'),                     # RG p64 (1.86 m, fitted in the 1.92 m gap)
    ('pma2', 'PMA-2', 'x', (14.106, 0.0, Z_USOS), 1.86, 1.90, 'skin_usos'),
    ('pma3', 'PMA-3', 'z', (11.211, 0.0, 1.630), 1.86, 1.90, 'skin_usos'),
    ('zarya', 'Zarya FGB', 'x', (-16.189, 0.0, 4.071), 12.99, 4.10, 'skin_rus'),              # RG p59
    ('zvezda_f', 'Zvezda SM small-diameter section', 'x', (-26.184, 0.0, 4.264), 6.90, 2.90, 'skin_rus'),   # RG p63: 13.1 m, 4.2 m max
    ('zvezda_a', 'Zvezda SM large-diameter section', 'x', (-32.759, 0.0, 4.264), 6.15, 4.20, 'skin_rus'),
    ('poisk', 'Poisk MRM-2', 'z', (-24.100, 0.0, 0.314), 4.90, 2.55, 'skin_rus'),             # RG p61
    ('pirs', 'Pirs DC-1', 'z', (-24.100, 0.0, 8.214), 4.90, 2.55, 'skin_rus'),                # RG p60
    ('rassvet', 'Rassvet MRM-1', 'z', (-11.141, 0.0, 9.171), 6.00, 2.35, 'skin_rus'),          # RG p62
]

''' + s[k:]
s = s.replace("('JEMEF', (12.228, -16.290, 7.150), (5.0, 5.6, 3.5), 3000.0, ('B', 'T_MTL', '-z')),",
              "('JEMEF', (11.962, -16.340, 7.150), (5.0, 5.6, 3.5), 3000.0, ('B', 'T_MTL', '-z')),")
open(p, 'w', encoding='utf-8').write(s)
print('patched')
