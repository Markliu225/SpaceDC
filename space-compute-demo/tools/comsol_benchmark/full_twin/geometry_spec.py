# -*- coding: utf-8 -*-
"""Geometry + material specification for the COMSOL twin (stage metres, body
frame +X = orbit normal / solar-cell normal, +Y = ram (radiator faces),
+Z = nadir (spine / radiator long axis)).

EVERY number is either (a) OrbitWiz geometry (usdz bbox x 1.8, or
gen_twin_satellite.py constants) or (b) an EXTERNAL, cited source listed in
PHASE1_ADDENDUM_materials (user decision B, 2026-08-29). Nothing here is
taken from the lumped thermal model.
"""
import math

S = 1.8   # asset metre -> stage metre (twin_satellite.usda:5,286)

# --- external material set (decision B) -----------------------------------
AL = dict(k=238.0, rho=2700.0, cp=900.0)   # COMSOL 6.3 built-in "Aluminum" (Basic def)
# Optical (OrbitWiz coating table, state_engine.py:179-180; array constants 150-152)
OPT_WHITEPAINT = dict(alpha=0.25, eps=0.85)
OPT_BARE_AL = dict(alpha=0.25, eps=0.10)
OPT_CELL_FRONT = dict(alpha=0.80 - 0.20, eps=0.85)   # alpha - eta_elec (heat-effective)
OPT_CELL_BACK = dict(alpha=0.80, eps=0.85)
T_SPACE_K = 2.7
# Vendor interface / transport data (external, cited in the report)
TIM_R_M2K_W = 0.06e-4          # Honeywell PTM7000: 0.04-0.06 degC cm2/W @ no shim, ASTM D5470 mod. (brochure p.6; upper bound)
HP_R_K_W = 0.015               # ACT hybrid Al/NH3 CCHP HHF2: 275 W at R = 0.015 degC/W
HP_Q_MAX_W = 275.0             # same source (capacity used for pipe count)
HP_L_REF_M = 0.305             # "~12 inch long" test pipes, same paper
HP_OD_M = 0.0127               # 0.5-inch evaporator contact width, same paper
HP_A_M2 = math.pi * (HP_OD_M / 2) ** 2
HP_K_EFF = HP_L_REF_M / (HP_R_K_W * HP_A_M2)        # ~1.6e5 W/mK, length-proportional reading
HP_PITCH_M = 0.1016            # NTRS 19890011820 Fig.20 "branch tube spacing, cond = 0.1016 m"

# --- equivalent-thick shells (areal densities from OrbitWiz tables) --------
RAD_AREAL_KG_M2 = 4.4          # state_engine.py:180 WhitePaint density_kg_m2
SOL_AREAL_KG_M2 = 2.5          # state_engine.py:126 Si density_kg_m2
T_MODEL = 0.020                # modelling thickness of the equivalent shells (m)
def equiv_shell(areal):
    t_real = areal / AL['rho']
    return dict(t_real=t_real, t_model=T_MODEL,
                k=AL['k'] * t_real / T_MODEL, rho=AL['rho'] * t_real / T_MODEL, cp=AL['cp'])
RAD_SHELL = equiv_shell(RAD_AREAL_KG_M2)
SOL_SHELL = equiv_shell(SOL_AREAL_KG_M2)

# --- bus solids: usdz part bboxes x 1.8 (measured with pxr) ---------------
def box(name, native_min, native_size, optics=OPT_BARE_AL):
    mn = [v * S for v in native_min]; sz = [v * S for v in native_size]
    return dict(name=name, min=mn, size=sz, optics=optics)
BUS = [
    box('Spine', (0.002, -0.037, -0.429), (0.0475, 0.0745, 0.8523)),
    box('ThrusterTop', (-0.004, -0.071, 0.383), (0.0756, 0.1419, 0.1165)),
    box('ThrusterBot', (-0.005, -0.071, -0.500), (0.0764, 0.1422, 0.1114)),
    box('TankPosY', (0.003, 0.028, -0.097), (0.0400, 0.1101, 0.1460)),
    box('TankNegY', (0.004, -0.138, -0.097), (0.0396, 0.1101, 0.1460)),
]
SPINE_Y_FACE = 0.0745 * S / 2 + (-0.037 * S) + 0.0745 * S / 2   # +Y face of spine = -0.0666+0.1341 = 0.0675
SPINE = BUS[0]
SPINE_YMAX = SPINE['min'][1] + SPINE['size'][1]      # 0.0675
SPINE_YMIN = SPINE['min'][1]                          # -0.0666

# --- blades / GPU packages (gen_twin_satellite.py:63-75, 94-96, 652) ------
BLADE_W, BLADE_D, BLADE_H = 0.130 * S, 0.155 * S, 0.034 * S     # 0.234, 0.279, 0.0612
SLOT_Y = 0.135 * S                                              # 0.243
SLOT_Z = dict(upper=[z * S for z in (0.1165, 0.2075, 0.2980)],
              lower=[z * S for z in (-0.1622, -0.2534, -0.3446)])
PKG_W, PKG_D, PKG_H = BLADE_W * 0.70, BLADE_D * 0.86, 0.006 * S  # 0.164, 0.240, 0.0108
def blades():
    out = []
    for rack, sign in (('UpY', +1), ('UnY', -1), ('LpY', +1), ('LnY', -1)):
        zs = SLOT_Z['upper'] if rack[0] == 'U' else SLOT_Z['lower']
        for i, zc in enumerate(zs):
            y_out = sign * (SLOT_Y + BLADE_D / 2)                # 0.3825
            y_in = SPINE_YMAX if sign > 0 else SPINE_YMIN         # extended to the spine face
            ymin, ymax = min(y_in, y_out), max(y_in, y_out)
            name = f'Blade_{rack}_{i+1}'
            b = dict(name=name, min=[-BLADE_W / 2, ymin, zc - BLADE_H / 2],
                     size=[BLADE_W, ymax - ymin, BLADE_H], optics=OPT_BARE_AL, sign=sign, zc=zc)
            pkg = dict(name=name.replace('Blade', 'Pkg'),
                       min=[-PKG_W / 2, sign * SLOT_Y - PKG_D / 2 if sign > 0 else sign * SLOT_Y - PKG_D / 2, zc + BLADE_H / 2],
                       size=[PKG_W, PKG_D, PKG_H], optics=OPT_BARE_AL)
            out.append((b, pkg))
    return out

# --- radiators (twin_params 1.1 / 2.5; RAD_NATIVE thickness NOT used) -----
RAD_LONG, RAD_SHORT = 1.1 * S, 1.1 / 2.5 * S           # 1.98, 0.792
RAD_X = 0.026 * S                                        # 0.0468 centre
RAD_Z0 = (0.5 + 0.16) * S                                # 1.188 root
BOOM_T, BOOM_L = 0.014 * S, 0.16 * S                     # 0.0252, 0.288
def radiators():
    out = []
    for tag, sgn in (('Top', +1), ('Bot', -1)):
        zlo = RAD_Z0 if sgn > 0 else -(RAD_Z0 + RAD_LONG)
        out.append(dict(name=f'Radiator{tag}', min=[RAD_X - RAD_SHORT / 2, -T_MODEL / 2, zlo],
                        size=[RAD_SHORT, T_MODEL, RAD_LONG], optics=OPT_WHITEPAINT, sign=sgn))
        blo = 0.5 * S if sgn > 0 else -(0.5 * S + BOOM_L)
        out.append(dict(name=f'RadBoom{tag}', min=[RAD_X - BOOM_T / 2, -BOOM_T / 2, blo],
                        size=[BOOM_T, BOOM_T, BOOM_L], optics=OPT_BARE_AL, sign=sgn, boom=True))
    return out

# --- solar wings (7 clusters/side; SOLAR_NATIVE x PANEL_SCALE; no booms) --
CL_H, CL_D = 0.981 * 1.45 * S, 0.777 * 1.05 * S        # 2.560, 1.469
N_CL = 7
WING_Y0 = 0.42 * S                                       # 0.756 (BOOM_Y1)
SOLAR_X, SOLAR_Z = 0.030 * S, -0.024 * S
def wings():
    out = []
    for tag, sgn in (('PosY', +1), ('NegY', -1)):
        L = N_CL * CL_D
        ylo = WING_Y0 if sgn > 0 else -(WING_Y0 + L)
        out.append(dict(name=f'Wing{tag}', min=[SOLAR_X - T_MODEL / 2, ylo, SOLAR_Z - CL_H / 2],
                        size=[T_MODEL, L, CL_H], sign=sgn))
    return out

# --- heat-pipe network (Thin Rod edges) -----------------------------------
def heat_pipes(peak_heat_per_gpu_w):
    """Transport bundles sized from the vendor capacity: n = ceil(3 blades x
    heat / Q_max). Returns list of dict(name, points, n_pipes)."""
    n_tr = math.ceil(3 * peak_heat_per_gpu_w / HP_Q_MAX_W)
    rods = []
    yf = T_MODEL / 2                                     # rod on the radiator face
    for rad, sgn in (('Top', +1), ('Bot', -1)):
        zs = SLOT_Z['upper'] if sgn > 0 else SLOT_Z['lower']
        z_root = sgn * RAD_Z0
        z_tip = sgn * (RAD_Z0 + RAD_LONG)
        for side in (+1, -1):
            y_bl = side * SLOT_Y
            z_first = min(zs) - BLADE_H / 2 if sgn > 0 else max(zs) + BLADE_H / 2
            z_last = max(zs) + BLADE_H / 2 if sgn > 0 else min(zs) - BLADE_H / 2
            rods.append(dict(name=f'HP_tr_{rad}_{"p" if side>0 else "n"}', n_pipes=n_tr,
                             points=[(0.0, y_bl, z_first), (0.0, y_bl, z_last), (RAD_X, side * yf, z_root)]))
            # header along X at the root, on this face
            xs = [RAD_X + (i - (8 - 1) / 2) * HP_PITCH_M for i in range(8)]
            z_h = z_root + sgn * 0.005
            rods.append(dict(name=f'HP_hd_{rad}_{"p" if side>0 else "n"}', n_pipes=n_tr,
                             points=[(xs[0], side * yf, z_h), (xs[-1], side * yf, z_h)]))
            for i, x in enumerate(xs):
                rods.append(dict(name=f'HP_sp_{rad}_{"p" if side>0 else "n"}_{i+1}', n_pipes=1,
                                 points=[(x, side * yf, z_h), (x, side * yf, z_tip - sgn * 0.01)]))
    return rods

HP_SIDE = HP_OD_M                      # square 12.7 mm pipe cross-section (block model)

def heat_pipe_blocks(peak_heat_per_gpu_w):
    """Heat pipes as slender solid blocks (one merged network per radiator
    face): a transport bundle (n pipes side by side along Y) running up the
    +X side of the three blades of one rack, a connector across to the
    radiator face, a header along X and 8 spreaders along Z lying ON the
    face. Overlapping blocks merge into one domain per face in Form Union.
    Returns list of dict(name, min, size, net) ; net = face id."""
    n_tr = math.ceil(3 * peak_heat_per_gpu_w / HP_Q_MAX_W)
    w_tr = n_tr * HP_SIDE
    xs_out = BLADE_W / 2                                 # outside the blades' +X face
    blocks = []
    yf = T_MODEL / 2
    for rad, sgn in (('Top', +1), ('Bot', -1)):
        zs = SLOT_Z['upper'] if sgn > 0 else SLOT_Z['lower']
        z_root = sgn * RAD_Z0
        z_tip = sgn * (RAD_Z0 + RAD_LONG)
        z_h0 = z_root + sgn * 0.002                      # header just inside the panel root
        z_h1 = z_h0 + sgn * HP_SIDE
        zlo_h, zhi_h = min(z_h0, z_h1), max(z_h0, z_h1)
        for side in (+1, -1):
            net = f"{rad}_{'p' if side > 0 else 'n'}"
            y_bl = side * SLOT_Y
            z_first = (min(zs) - BLADE_H / 2) if sgn > 0 else (max(zs) + BLADE_H / 2)
            zlo, zhi = min(z_first, zhi_h), max(z_first, zlo_h)
            blocks.append(dict(name=f'HPtr_{net}', net=net, min=[xs_out, y_bl - w_tr / 2, zlo], size=[HP_SIDE, w_tr, zhi - zlo]))
            # connector across Y from the radiator face to the transport bundle
            y0, y1 = (yf, y_bl + w_tr / 2) if side > 0 else (y_bl - w_tr / 2, -yf)
            blocks.append(dict(name=f'HPcn_{net}', net=net, min=[xs_out, y0, zlo_h], size=[HP_SIDE, y1 - y0, HP_SIDE]))
            xs = [RAD_X + (i - 3.5) * HP_PITCH_M for i in range(8)]
            yb0, yb1 = (yf, yf + HP_SIDE) if side > 0 else (-yf - HP_SIDE, -yf)
            blocks.append(dict(name=f'HPhd_{net}', net=net, min=[xs[0] - HP_SIDE / 2, yb0, zlo_h], size=[xs[-1] - xs[0] + HP_SIDE, yb1 - yb0, HP_SIDE]))
            for i, x in enumerate(xs):
                z_a, z_b = z_h0, z_tip - sgn * 0.01
                blocks.append(dict(name=f'HPsp_{net}_{i+1}', net=net, min=[x - HP_SIDE / 2, yb0, min(z_a, z_b)], size=[HP_SIDE, yb1 - yb0, abs(z_b - z_a)]))
    return blocks, n_tr


def mass_table():
    rows = []
    def vol(b): return b['size'][0] * b['size'][1] * b['size'][2]
    for b in BUS:
        rows.append((b['name'], vol(b) * AL['rho']))
    for b, p in blades():
        rows.append((b['name'], vol(b) * AL['rho'])); rows.append((p['name'], vol(p) * AL['rho']))
    for r in radiators():
        if r.get('boom'): rows.append((r['name'], vol(r) * AL['rho']))
        else: rows.append((r['name'], r['size'][0] * r['size'][2] * RAD_AREAL_KG_M2))
    for w in wings():
        rows.append((w['name'], w['size'][1] * w['size'][2] * SOL_AREAL_KG_M2))
    hp_len = 0.0
    for rod in heat_pipes(400 * 0.95):
        pts = rod['points']
        L = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        hp_len += L * rod['n_pipes']
    rows.append(('HeatPipes(solid-Al equivalent)', hp_len * HP_A_M2 * AL['rho']))
    return rows, hp_len

if __name__ == '__main__':
    rows, hp_len = mass_table()
    tot = 0.0; bus = 0.0
    for n, m in rows:
        tot += m
        if not n.startswith('Wing'): bus += m
        print(f"{n:32s} {m:8.2f} kg")
    print(f"TOTAL {tot:.1f} kg  (bus+payload+radiators {bus:.1f} kg; capacity ~{bus*AL['cp']/1e3:.0f} kJ/K vs OrbitWiz 160 kJ/K)")
    print(f"heat-pipe length x pipes = {hp_len:.1f} m; k_eff = {HP_K_EFF:.3g} W/mK; A_pipe = {HP_A_M2:.3e} m2")
    print("RAD_SHELL", RAD_SHELL); print("SOL_SHELL", SOL_SHELL)
    print("preset estimate (design_presets.py:206-209): 300 + 52.64*2.5 + 3.136*4.4 + 32 =", 300 + 52.64 * 2.5 + 3.136 * 4.4 + 32)
