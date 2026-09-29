# -*- coding: utf-8 -*-
"""ISS thermal FE model: every number used by the COMSOL build, with its source.

Source keys (full references in docs/ISS_SPEC.md):
  A    Boeing, "Active Thermal Control System (ATCS) Overview", 2006 (Thermal/ PDF), page numbers pN
  B    Cowan, Bond, Metcalf, ICES-2019-31, P1 EATCS ammonia leak (Thermal/ PDF)
  C    Morrison, Holt, 05ICES-279, IATCS coolant (Thermal/ PDF)
  G3D  NASA 3D Resources IGOAL model (JSC), converted to the ISS analysis frame,
       docs/iss3d/components_iss_frame.csv, joints_iss_frame.csv, saw_blankets_iss_frame.csv
  R    public-data research, docs/ISS_SPEC.md (verified values; item ids there)
  D    modelling decision / derived value (formula given)

Frame (G3D): +X forward (velocity in +XVV), +Y starboard, +Z nadir, origin at the
S0 geometric centre on the truss centre line. Epoch: 2019 configuration
(PMM on Node 3 forward, PMA-3 on Node 2 zenith, Pirs on SM nadir, BEAM on Node 3 aft,
no iROSA / Nauka / Bishop).
"""
import math

# ======================================================================= orbit & cases
ORBIT = dict(
    R_earth_m=6378.137e3,          # WGS84 equatorial radius (D)
    mu=3.986004418e14,             # m3/s2 (D)
    alt_m=400e3,                   # R L29-L31: mean ~401.5 km (2015), 389-407 km after reboosts
    incl_deg=51.64,                # R L28: 51.6424 deg
)
# environment per case (R L2-L27): SSP 41000 design-verification cold / hot pairs (TFAWS 2015
# short course slide 40) and the ISS mean environment (EVA thermal database, slide 51) with the
# beta-dependent orbit-average albedo correction of TM-2001-211221 Table 4.2.1-1 (+0.04 at beta 0).
# beta = Sun elevation above the orbit plane, positive toward the +orbit-normal (= -Y, port) side.
CASES = {
    # hrs_law: 'zero'  = TRRJ held at zero in daylight (edge to Sun for every orbit angle when beta = 0), face to Earth in eclipse
    #          'track' = TRRJ rolls about X to keep the Sun in the panel plane (beta != 0), face to Earth in eclipse
    'cold0':  dict(beta_deg=0.0,  S_sun=1321.0, albedo=0.20, olr=206.0, hrs_law='zero',  label='设计冷工况 beta 0'),
    'hot75':  dict(beta_deg=75.0, S_sun=1423.0, albedo=0.40, olr=286.0, hrs_law='track', label='设计热工况 beta 75'),
    'nom0':   dict(beta_deg=0.0,  S_sun=1371.0, albedo=0.31, olr=241.0, hrs_law='zero',  label='平均环境 beta 0'),
    'nom60':  dict(beta_deg=60.0, S_sun=1371.0, albedo=0.39, olr=241.0, hrs_law='track', label='平均环境 beta 60'),
}
for _c in CASES.values():
    _c.setdefault('u0_deg', 0.0)

# ======================================================================= mesh (m)
MESH_H = dict(skin_usos=1.4, skin_rus=1.6, truss=2.2, box=0.6, payload=1.2, rack=0.7,
              hrs=1.2, pvr=1.4, saw=3.0, rsa=2.0)

# ======================================================================= parameters (value, description)
PARAMS = {
    'T_space':  ('2.7[K]', 'deep-space sink'),
    'cp_nh3':   ('4.61[kJ/(kg*K)]', 'liquid NH3 at 2.8 C, 300 psia: 4612.6 J/kgK (NIST, optics doc 8.13)'),
    'T_setA':   ('(37-32)/1.8[K]+273.15[K]', 'EATCS NH3 supply set point 37 F = 2.8 C (A p6, p11)'),
    'T_setB':   ('(37-32)/1.8[K]+273.15[K]', 'EATCS NH3 supply set point 37 F = 2.8 C (A p6, p11)'),
    'mdot_A':   ('8200[lb/h]', 'EATCS loop A nominal flow (A p10)'),
    'mdot_B':   ('8900[lb/h]', 'EATCS loop B nominal flow (A p10)'),
    'T_MTL':    ('17[degC]', 'IATCS moderate temperature loop (A p2)'),
    'T_LTL':    ('4[degC]', 'IATCS low temperature loop (A p2)'),
    'T_cab':    ('22[degC]', 'cabin air temperature (R)'),
    'h_air':    ('2[W/(m^2*K)]', 'rack surface to cabin air; racks reject almost all heat to water, sensible air share limited to 250-500 W per module (R L61; D)'),
    'h_mli':    ('0.22[W/(m^2*K)]', 'MLI e* = 0.05 [optics 5.13] linearised: 4*e*sigma*Tm^3 at Tm 270 K (derived)'),
    'h_cp_rack': ('40[W/(m^2*K)]', 'rack cold-plate face conductance: 600 W over 1.8 m2 at about 8 K above the coolant (D)'),
    'h_cp_oru':  ('60[W/(m^2*K)]', 'ORU base to finned NH3 cold plate, radiant fins (A p9; D)'),
    'g_hrs':    ('120[W/(m^2*K)]', 'NH3 to radiator panel conductance per unit panel area (D)'),
    'g_pvr':    ('120[W/(m^2*K)]', 'NH3 to PVR panel conductance per unit panel area (D)'),
    'tau_Q':    ('20[s]', 'lag of the collected-heat state (numerical, D)'),
    'C_f':      ('1[kJ/K]', 'NH3 node heat capacity per radiator panel: 22 tubes x 2.7 m of liquid NH3 plus tube wall (D)'),
    'k_c':      ('3000[K*s]', 'mixing-valve integral gain: closed-loop time constant k_c/|dTmix/df| ~ 3000/25 = 120 s, below the 16 min panel time constant (D)'),
    'f_min':    ('0.02', 'lower bound of the radiator flow fraction, valve fully on bypass (D)'),
    's_f':      ('0.01', 'smoothing width of the flow-fraction bound (numerical, D)'),
    'k_aw':     ('50[K]', 'anti-windup gain of the valve integrator below f_min (numerical, D)'),
    'T_init_solid': ('273.15[K]', 'initial temperature, solids'),
    'T_init_shell': ('263.15[K]', 'initial temperature, shells'),
}

# initial temperatures by class (K): rough orbit-average expectations to shorten the spin-up (D)
T_INIT = dict(rack=298.0, box=283.0, payload=283.0, truss=253.0, skin_usos=268.0, skin_rus=268.0,
              hrs=262.0, pvr=262.0, saw=290.0, rsa=290.0)

# ======================================================================= optics (alpha solar, eps IR)
OPTICS = {   # docs/ISS_OPTICS_MATERIALS.md item numbers in brackets
    'z93':       dict(alpha=0.20, eps=0.91),   # nominal aged Z-93/Z-93P: BOL 0.15/0.91 [2.1, 2.2], contaminated + VUV 0.21-0.24 [2.11]
    'skin_usos': dict(alpha=0.30, eps=0.45),   # chromic-anodized Al 6061 MMOD bumper [5.9-5.11]
    'skin_rus':  dict(alpha=0.36, eps=0.87),   # no public value [10.4]; ISS-batch aluminized beta cloth BOL taken (optics verification)
    'truss':     dict(alpha=0.49, eps=0.85),   # sulfuric anodize [6.1, 6.2]
    'box':       dict(alpha=0.36, eps=0.87),   # ORU MLI outer layer, ISS-batch aluminized beta cloth BOL (optics verification; 0.41-0.42 after MISSE-6)
    'payload':   dict(alpha=0.36, eps=0.87),   # same outer layer (D)
    # US solar array: no public alpha/eps [10.2]; cell side 0.72 typical Si cell + coverglass (D) minus the
    # blanket-average electrical conversion 31 kW / (309 m2 x 1371 W/m2) = 0.073 [4.11] (derived)
    'saw_cells': dict(alpha=0.72 - 0.073, eps=0.82),
    'saw_back':  dict(alpha=0.55, eps=0.85),   # polyimide / glass-fibre substrate (D)
    'rsa_cells': dict(alpha=0.72 - 0.07, eps=0.82),
    'rsa_back':  dict(alpha=0.55, eps=0.85),
}
# case-dependent radiator coating: cold case BOL, hot case contaminated/aged nominal EOL (O37 practice [11.2])
OPTICS_BY_CASE = {'cold0': {'z93': dict(alpha=0.15, eps=0.91)}, 'hot75': {'z93': dict(alpha=0.24, eps=0.90)}}

# ======================================================================= materials
# shells: t = modelled layer thickness; rho*cp*t reproduces the areal heat capacity, k*t the in-plane conductance
MATERIALS = {   # docs/ISS_OPTICS_MATERIALS.md items in brackets; shells: rho*cp*t = areal heat capacity, k*t = in-plane conductance
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

# ======================================================================= geometry (G3D unless noted)
Z_USOS = 4.85            # USOS module axis height below the truss centre line (G3D 2.6)

MODULES = [  # name, label, axis, centre, length, diameter, class
    # hull length / diameter: Reference Guide to the ISS 2010 (RG), ESA and JAXA fact sheets (research
    # "modules_layout"); centres: G3D, consistent with the JSC 26557 Rev AB mass-property centres within
    # 0.5 m; attached modules re-seated 5 cm from the parent hull so that no hulls intersect
    ('destiny', 'Destiny US Lab', 'x', (2.120, 0.0, Z_USOS), 8.50, 4.45, 'skin_usos'),          # RG p49; MMOD envelope 4.45 (IGOAL, data book)
    ('unity', 'Unity Node 1', 'x', (-5.023, 0.0, Z_USOS), 5.50, 4.45, 'skin_usos'),            # RG p53; envelope R2223 mm (JSC 26557)
    ('harmony', 'Harmony Node 2', 'x', (9.773, 0.0, Z_USOS), 6.706, 4.48, 'skin_usos'),        # ESA
    ('tranquility', 'Tranquility Node 3', 'y', (-5.023, -5.628, Z_USOS), 6.706, 4.48, 'skin_usos'),   # ESA factsheet
    ('columbus', 'Columbus', 'y', (10.855, 5.726, Z_USOS), 6.871, 4.477, 'skin_usos'),         # ESA
    ('kibo', 'Kibo JEM PM', 'y', (10.957, -7.890, Z_USOS), 11.20, 4.40, 'skin_usos'),          # JAXA Kibo Handbook T3.1-1
    ('elm', 'Kibo JEM ELM-PS', 'z', (11.093, -10.173, 0.500), 4.20, 4.40, 'skin_usos'),        # JAXA
    ('quest', 'Quest airlock', 'y', (-5.023, 5.025, Z_USOS), 5.50, 4.00, 'skin_usos'),         # RG p56
    ('pmm', 'Leonardo PMM', 'x', (0.602, -6.756, Z_USOS), 6.67, 4.57, 'skin_usos'),           # RG p58
    ('beam', 'BEAM', 'x', (-9.319, -6.756, Z_USOS), 4.011, 3.23, 'skin_usos'),                 # NASA facts
    ('cupola', 'Cupola', 'z', (-5.023, -6.808, 7.890), 1.50, 2.955, 'skin_usos'),              # ESA
    ('pma1', 'PMA-1', 'x', (-8.734, 0.0, 4.702), 1.82, 1.90, 'skin_usos'),                     # RG p64 (1.86 m, fitted in the 1.92 m gap)
    ('pma2', 'PMA-2', 'x', (14.106, 0.0, Z_USOS), 1.86, 1.90, 'skin_usos'),
    ('pma3', 'PMA-3', 'z', (11.211, 0.0, 1.630), 1.86, 1.90, 'skin_usos'),
    ('zarya', 'Zarya FGB', 'x', (-16.189, 0.0, 4.071), 12.99, 4.10, 'skin_rus'),              # RG p59
    ('zvezda_f', 'Zvezda SM small-diameter section', 'x', (-26.184, 0.0, 4.264), 6.90, 2.90, 'skin_rus'),   # RG p63: 13.1 m, 4.2 m max
    ('zvezda_a', 'Zvezda SM large-diameter section', 'x', (-32.759, 0.0, 4.264), 6.15, 4.25, 'skin_rus'),   # R2125 mm (JSC 26557)
    ('poisk', 'Poisk MRM-2', 'z', (-24.100, 0.0, 0.314), 4.90, 2.55, 'skin_rus'),             # RG p61
    ('pirs', 'Pirs DC-1', 'z', (-24.100, 0.0, 8.214), 4.90, 2.55, 'skin_rus'),                # RG p60
    ('rassvet', 'Rassvet MRM-1', 'z', (-11.141, 0.0, 9.171), 6.00, 2.35, 'skin_rus'),          # RG p62
]

TRUSS = [    # name, xmin, xmax, ymin, ymax, zmin, zmax
    # X/Z from the G3D 2.2 main-structure boxes (S0 trimmed to the truss body without the
    # fore struts over Destiny, Z1 to its box without antenna booms); Y boundaries between
    # neighbours at the midpoint of the G3D box overlap (boxes include fittings)
    ('P6', -2.63, 1.44, -48.80, -35.585, -2.23, 2.40),
    ('P5', -3.22, 0.84, -35.585, -32.925, -2.47, 2.48),
    ('P4', -1.69, 1.69, -32.925, -26.015, -2.22, 2.34),
    ('P3', -1.76, 1.73, -26.015, -20.34, -2.24, 2.27),
    ('P1', -0.17, 1.73, -20.34, -6.625, -2.47, 2.47),
    ('S0', -2.74, 2.20, -6.625, 6.63, -2.23, 2.40),
    ('S1', -0.17, 1.73, 6.63, 20.345, -2.47, 2.47),
    ('S3', -1.91, 1.74, 20.345, 25.935, -2.47, 2.47),
    ('S4', -1.69, 2.43, 25.935, 32.93, -2.48, 2.48),
    ('S5', -0.84, 3.22, 32.93, 35.595, -2.47, 2.48),
    ('S6', -1.27, 1.75, 35.595, 48.73, -2.21, 2.39),
    ('Z1', -6.53, -2.96, -2.30, 2.30, -2.00, 2.30),
]
# overlapping neighbours share a face in the equivalent-solid model: shrink every
# segment by GAP_T at both Y ends so segments are separate domains (joint conductance neglected)
GAP_T = 0.05

# EATCS radiator wings. The TRRJ axis is parallel to X through (|Y| 14.68, Z 0) (docs/ISS_TRUSS_ARTICULATION.md 1:
# NASA TopCoder ISS coordinate model T2, IGOAL joint axes, ISAG clearance analysis). Reference pose =
# TRRJ zero: beam vertical, the three ORUs stacked along Z (centre distance 3.89 m), each extending
# aft from X -1.26 to -23.25 (G3D), panels in the X-Z plane, normal +/-Y. 8 panels per ORU along X (A p14).
HRS = dict(x_root=-1.26, x_tip=-23.25, y_abs=14.68, width=3.4, pitch=3.89, n_panels=8, gap=0.05,
           orus={'S1-1': (+1, -1), 'S1-2': (+1, 0), 'S1-3': (+1, +1), 'P1-1': (-1, -1), 'P1-2': (-1, 0), 'P1-3': (-1, +1)})
# PVR: Y-Z plane, hanging nadir, 7 panels along Z (A p3: 7 panels, 3.12 m x 13.6 m deployed)
PVR = dict(width=3.12, z_top=4.02, z_bot=15.19, n_panels=7, gap=0.05,   # panel region Z from G3D; width A p3
           units={'P4': (-0.35, -29.49), 'P6': (-0.35, -44.525), 'S4': (0.35, 29.445), 'S6': (0.35, 44.555)})   # Y centres T2
# US solar array wings: reference pose = local noon, beta 0: blankets horizontal at the BGA axis
# height, cells up (-Z). Two blankets per wing (4.70 m x 32.83 m cells, 2.29 m mast gap, G3D 2.4)
SAW = dict(blanket_w=4.752, gap=1.928, x_in=3.32, x_len=32.51,      # T2: blanket 32.51 x 4.752 m, gap 1.928 m, from |X| 3.32
           wings={'2A': (-1, -33.435, -0.660), '4A': (+1, -33.435, 0.661), '2B': (+1, -48.447, 0.655), '4B': (-1, -48.445, -0.664),
                  '1A': (+1, 33.371, -0.661), '3A': (-1, 33.371, 0.661), '1B': (-1, 48.445, 0.664), '3B': (+1, 48.447, -0.657)})
# Zvezda arrays: horizontal, along +/-Y from the hull (G3D VTAD panels), cells up
RSA = dict(x_c=-27.5, width=3.6, y_in=2.4, y_out=15.4, z=4.264)

# ======================================================================= heat-source blocks
# external ORUs on NH3 cold plates (A p5, p8, p9); positions D (on truss faces, 5 cm gap)
ORU_BOXES = [   # name, size (m), centre, Q (W), loop, cold-plate face
    ('MBSU_1', (0.94, 0.84, 0.51), (0.0, -4.5, -2.23 - 0.05 - 0.255), 495.0, 'A', '+z'),
    ('MBSU_4', (0.94, 0.84, 0.51), (0.0, -1.5, -2.23 - 0.05 - 0.255), 495.0, 'A', '+z'),
    ('MBSU_2', (0.94, 0.84, 0.51), (0.0, 1.5, -2.23 - 0.05 - 0.255), 495.0, 'B', '+z'),
    ('MBSU_3', (0.94, 0.84, 0.51), (0.0, 4.5, -2.23 - 0.05 - 0.255), 495.0, 'B', '+z'),
    ('DDCU_S0_1A', (0.89, 0.71, 0.79), (2.20 + 0.05 + 0.445, -4.5, 0.0), 694.0, 'A', '-x'),
    ('DDCU_S0_4B', (0.89, 0.71, 0.79), (2.20 + 0.05 + 0.445, -1.5, 0.0), 694.0, 'A', '-x'),
    ('DDCU_S0_3B', (0.89, 0.71, 0.79), (2.20 + 0.05 + 0.445, 1.5, 0.0), 694.0, 'B', '-x'),
    ('DDCU_S0_2B', (0.89, 0.71, 0.79), (2.20 + 0.05 + 0.445, 4.5, 0.0), 694.0, 'B', '-x'),
    ('DDCU_S1_4B', (0.89, 0.71, 0.79), (1.73 + 0.05 + 0.445, 16.0, 0.0), 694.0, 'A', '-x'),
    ('DDCU_P1_3A', (0.89, 0.71, 0.79), (1.73 + 0.05 + 0.445, -16.0, 0.0), 694.0, 'B', '-x'),
]
# passive EATCS hardware (A p10, p13; on S1/P1, zenith side for the ATA per A p12)
PASSIVE_BOXES = [
    # ATA on the aft face at the inboard end (ATCS p19 drawing, STS-113 press kit, IGOAL box X -1.55..-0.09, |Y| 6.6..7.8)
    ('ATA_S1', (1.17, 2.01, 1.40), (-0.17 - 0.05 - 0.585, 7.65, 0.0)), ('ATA_P1', (1.17, 2.01, 1.40), (-0.17 - 0.05 - 0.585, -7.65, 0.0)),
    ('PM_S1', (1.27, 1.75, 0.91), (1.73 + 0.05 + 0.635, 11.0, 0.0)), ('PM_P1', (1.27, 1.75, 0.91), (1.73 + 0.05 + 0.635, -11.0, 0.0)),
    ('NTA_S1', (0.91, 1.63, 0.76), (1.73 + 0.05 + 0.455, 13.5, 0.0)), ('NTA_P1', (0.91, 1.63, 0.76), (1.73 + 0.05 + 0.455, -13.5, 0.0)),
]
# PV module IEA electronics (PVTCS heat source), block on the nadir face of each PV truss segment (D)
IEA = dict(size=(3.0, 4.5, 1.6), Q=6000.0, units={'P4': (0.0, -29.84), 'P6': (-0.6, -40.0), 'S4': (0.37, 29.77), 'S6': (0.24, 40.0)})
# external payload carriers (G3D 2.6 envelopes); PROVISIONAL powers (R)
PAYLOADS = [   # name, centre, size, Q (W), cooling
    ('ELC1', (-0.854, -24.417, 4.629), (4.3, 2.0, 2.6), 1000.0, None),
    ('ELC2', (-0.865, 24.693, -4.624), (4.3, 2.0, 2.6), 1000.0, None),
    ('ELC3', (-0.863, -24.043, -4.627), (4.3, 1.7, 2.6), 1000.0, None),
    ('ELC4', (-0.858, 21.147, 4.632), (4.3, 2.0, 2.6), 1000.0, None),
    ('AMS02', (-0.864, 21.319, -4.10), (4.9, 3.2, 3.16), 2500.0, None),
    ('JEMEF', (11.962, -16.340, 7.150), (5.0, 5.6, 3.5), 3000.0, ('B', 'T_MTL', '-z')),
]

# internal racks: per module, bays along the axis, 4 walls; rack block 1.0 (axial) x 0.85 (radial) x 1.8 (tangential)
RACK = dict(axial=1.0, radial=0.85, tang=1.8, r_back=1.85)
RACK_MODULES = {   # module: (n_bays, W per rack); totals sized to the AC planning budget (R L63-L65):
    # USOS payload heat about 30 kW average plus housekeeping, 50 kW class in total, inside the
    # module capacities found (JEM 25 kW MT + 9 kW LT, Columbus 22 kW, Destiny payload MTL 7.7-13 kW)
    'destiny': (6, 500.0),      # 24 racks, 12.0 kW
    'harmony': (2, 300.0),      #  8 racks,  2.4 kW
    'tranquility': (4, 400.0),  # 16 racks,  6.4 kW (ECLSS)
    'columbus': (4, 600.0),     # 16 racks,  9.6 kW
    'kibo': (6, 600.0),         # 24 racks, 14.4 kW
}
RACK_LT_WALL = 3                # one of the four walls of every module runs on the LTL (D)
# which IATCS temperature each module's racks use and which EATCS loop takes the MT and LT heat (A p5 schematic)
MODULE_LOOPS = {
    'destiny': dict(MT='B', LT='A'), 'harmony': dict(MT='A', LT='B'), 'tranquility': dict(MT='A', LT='B'),
    'columbus': dict(MT='A', LT='B'), 'kibo': dict(MT='B', LT='A'),
}

# ======================================================================= loops
LOOPS = dict(
    loops={
        # f_init: steady-state estimate f = (Tret - Tset)/(Tret - Tout) with a 5 K loop rise and a ~30 K radiator drop
        'A': dict(mdot='mdot_A', T_set='T_setA', g='g_hrs', orus=['S1-1', 'S1-2', 'S1-3'], f_init=0.2),
        'B': dict(mdot='mdot_B', T_set='T_setB', g='g_hrs', orus=['P1-1', 'P1-2', 'P1-3'], f_init=0.2),
    },
    other_loads={'A': '410[W]', 'B': '410[W]'},     # crew metabolic heat, 6 crew x 136.8 W (R L85-L86), split between loops
)
PV_LOOPS = {   # PVTCS: IEA cold plates -> PVR, bypass mixing to a set point (A p2-p3; flow R/D)
    'P4': dict(mdot='mdot_pv', T_set='T_set_pv'), 'P6': dict(mdot='mdot_pv', T_set='T_set_pv'),
    'S4': dict(mdot='mdot_pv', T_set='T_set_pv'), 'S6': dict(mdot='mdot_pv', T_set='T_set_pv'),
}
PARAMS.update({
    'mdot_pv':  ('0.5[kg/s]', 'PVTCS loop flow (PROVISIONAL, R)'),
    'T_set_pv': ('(37-32)/1.8[K]+273.15[K]', 'PVTCS supply set point, taken equal to EATCS (PROVISIONAL, R)'),
})
for _m in PV_LOOPS:
    LOOPS['loops']['PV' + _m] = dict(mdot='mdot_pv', T_set='T_set_pv', g='g_pvr', orus=['PVR_' + _m], f_init=0.3)


# ======================================================================= layout
def layout(case, lite=False):
    """Primitives in the reference pose. Returns dict with cylinders, blocks, panels, panel_groups."""
    cyl, blocks, panels, pgroups = [], [], [], {}
    for name, label, axis, c, L, D, cls in MODULES:
        ax = 'xyz'.index(axis); p0 = list(c); p0[ax] -= L / 2
        cyl.append(dict(name=name, label=label, axis=axis, p0=p0, L=L, R=D / 2, cls=cls))
    for name, x0, x1, y0, y1, z0, z1 in TRUSS:
        ya, yb = (y0 + GAP_T, y1 - GAP_T) if name != 'Z1' else (y0, y1)
        blocks.append(dict(name=name, label=f'truss {name}', cls='truss', center=[(x0 + x1) / 2, (ya + yb) / 2, (z0 + z1) / 2], size=[x1 - x0, yb - ya, z1 - z0], Q=0.0))
    for name, size, c, Q, loop, face in ORU_BOXES:
        T = 'T_setA' if loop == 'A' else 'T_setB'
        blocks.append(dict(name=name, label=name, cls='box', center=list(c), size=list(size), Q=Q, cool=dict(face=face, h='h_cp_oru', T=T, loop=loop)))
    for name, size, c in PASSIVE_BOXES:
        blocks.append(dict(name=name, label=name, cls='box', center=list(c), size=list(size), Q=0.0))
    for u, (xc, yc) in IEA['units'].items():
        sx, sy, sz = IEA['size']
        zc = 2.48 + 0.05 + sz / 2          # below (nadir of) the segment
        # keep clear of the PVR (x ~ +/-0.35, z >= 4.02): shift the IEA block fore/aft
        xc2 = xc + (2.0 if u.startswith('P') else -2.0)
        blocks.append(dict(name='IEA_' + u, label=f'IEA {u} (PVTCS heat)', cls='box', center=[xc2, yc, zc], size=[sx, sy, sz], Q=IEA['Q'],
                           cool=dict(face='-z', h='h_cp_oru', T='T_set_pv', loop='PV' + u)))
    for name, c, size, Q, cool in PAYLOADS:
        b = dict(name=name, label=f'payload {name}', cls='payload', center=list(c), size=list(size), Q=Q, scaled=True)
        if cool:
            b['cool'] = dict(face=cool[2], h='h_cp_oru', T=cool[1], loop=cool[0])
        blocks.append(b)
    # racks
    for mod, (nb, W) in RACK_MODULES.items():
        m = next(x for x in MODULES if x[0] == mod)
        _, label, axis, c, L, D, cls = m
        ax = 'xyz'.index(axis); others = [k for k in range(3) if k != ax]
        a0 = c[ax] - (nb * RACK['axial']) / 2 + RACK['axial'] / 2
        rc = RACK['r_back'] - RACK['radial'] / 2
        for ib in range(nb):
            for wall, (s1, s2) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
                ctr = list(c); ctr[ax] = a0 + ib * RACK['axial']
                size = [0, 0, 0]; size[ax] = RACK['axial'] * 0.96
                k1, k2 = others
                ctr[k1] = c[k1] + s1 * rc; ctr[k2] = c[k2] + s2 * rc
                size[k1] = RACK['radial'] if s1 else RACK['tang']; size[k2] = RACK['radial'] if s2 else RACK['tang']
                face = ('+' if (s1 > 0 or s2 > 0) else '-') + 'xyz'[k1 if s1 else k2]
                lt = (wall == RACK_LT_WALL)
                loop = MODULE_LOOPS[mod]['LT' if lt else 'MT']
                blocks.append(dict(name=f'rk_{mod}_{ib}_{wall}', label=f'{label} rack bay {ib + 1} wall {wall + 1}', cls='rack', module=mod,
                                   center=ctr, size=size, Q=W, scaled=True, cool=dict(face=face, h='h_cp_rack', T='T_LTL' if lt else 'T_MTL', loop=loop),
                                   air=dict(exclude=face)))
    # EATCS radiators, TRRJ zero pose: panels in the X-Z plane at y = +/-14.68 (work plane zx: u = z, v = x); ORUs stacked along Z
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
    P_ = PVR
    lp = ((P_['z_bot'] - P_['z_top']) - (P_['n_panels'] - 1) * P_['gap']) / P_['n_panels']
    for u, (xc, yc) in P_['units'].items():
        members = []
        for i in range(P_['n_panels']):
            z0 = P_['z_top'] + i * (lp + P_['gap'])
            nm = f'pvr_{u}_{i + 1}'
            panels.append(dict(name=nm, label=f'PVR {u} panel {i + 1}', cls='pvr', plane='yz', offset=xc,
                               u0=yc - P_['width'] / 2, v0=z0, du=P_['width'], dv=lp, group='sarj',
                               fluid=dict(loop='PV' + u, oru='PVR_' + u, idx=i + 1)))
            members.append(nm)
        pgroups['PVR_' + u] = members
    Sw = SAW
    for wing, (sx, yb, zb) in Sw['wings'].items():
        members = []
        for side in (+1, -1):
            y0 = yb + side * (Sw['gap'] / 2) if side > 0 else yb - Sw['gap'] / 2 - Sw['blanket_w']
            x0 = Sw['x_in'] if sx > 0 else -Sw['x_in'] - Sw['x_len']
            nm = f'saw_{wing}_{"a" if side > 0 else "b"}'
            panels.append(dict(name=nm, label=f'SAW {wing} blanket {"a" if side > 0 else "b"}', cls='saw', plane='xy', offset=zb,
                               u0=x0, v0=y0, du=Sw['x_len'], dv=Sw['blanket_w'], group='saw'))
            members.append(nm)
        pgroups['SAW_' + wing] = members
    R_ = RSA
    for side, nm in ((+1, 'rsa_s'), (-1, 'rsa_p')):
        y0 = R_['y_in'] if side > 0 else -R_['y_out']
        panels.append(dict(name=nm, label=f'Zvezda array {"stbd" if side > 0 else "port"}', cls='rsa', plane='xy', offset=R_['z'],
                           u0=R_['x_c'] - R_['width'] / 2, v0=y0, du=R_['width'], dv=R_['y_out'] - R_['y_in'], group='sarj'))
    pgroups['RSA'] = ['rsa_s', 'rsa_p']
    if lite:
        keep_mods = {'destiny', 'unity', 'harmony', 'zarya'}
        cyl = [c for c in cyl if c['name'] in keep_mods]
        blocks = [b for b in blocks if b['cls'] != 'rack' or b.get('module') in keep_mods]
    lay = dict(cylinders=cyl, blocks=blocks, panels=panels, panel_groups=pgroups)
    lay['panel_by_name'] = {p['name']: p for p in panels}
    return lay


# ======================================================================= consistency check
def aabb_overlaps(lay, tol=0.0):
    """Axis-aligned bounding-box overlaps between primitives (racks inside their own module excluded)."""
    items = []
    for c in lay['cylinders']:
        ax = 'xyz'.index(c['axis']); lo = list(c['p0']); hi = list(c['p0'])
        for k in range(3):
            if k == ax: hi[k] += c['L']
            else: lo[k] -= c['R']; hi[k] += c['R']
        items.append(('cyl', c['name'], lo, hi, None))
    for b in lay['blocks']:
        lo = [b['center'][k] - b['size'][k] / 2 for k in range(3)]; hi = [b['center'][k] + b['size'][k] / 2 for k in range(3)]
        items.append((b['cls'], b['name'], lo, hi, b.get('module')))
    for p in lay['panels']:
        u0, v0, u1, v1, o = p['u0'], p['v0'], p['u0'] + p['du'], p['v0'] + p['dv'], p['offset']
        if p['plane'] == 'xy': lo, hi = [u0, v0, o], [u1, v1, o]
        elif p['plane'] == 'yz': lo, hi = [o, u0, v0], [o, u1, v1]
        else: lo, hi = [v0, o, u0], [v1, o, u1]
        items.append(('panel', p['name'], lo, hi, None))
    out = []
    for i in range(len(items)):
        for k in range(i + 1, len(items)):
            a, b = items[i], items[k]
            if a[0] == 'rack' and b[0] == 'cyl' and a[4] == b[1]: continue
            if b[0] == 'rack' and a[0] == 'cyl' and b[4] == a[1]: continue
            if all(a[2][d] < b[3][d] - tol and b[2][d] < a[3][d] - tol for d in range(3)):
                out.append((a[1], b[1]))
    return out


if __name__ == '__main__':
    lay = layout('beta0')
    ov = aabb_overlaps(lay, tol=1e-6)
    print(len(lay['cylinders']), 'cylinders', len(lay['blocks']), 'blocks', len(lay['panels']), 'panels')
    print('AABB overlaps:', len(ov)); [print('  ', o) for o in ov]
