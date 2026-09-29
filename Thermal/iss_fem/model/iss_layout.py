# -*- coding: utf-8 -*-
"""Turn iss_spec.py into COMSOL primitives, loop equations and orbit functions.

Frame: ISS Analysis Coordinate System as built (see iss_spec.FRAME): +X forward
(velocity in +XVV), +Y starboard, +Z nadir; origin per iss_spec.FRAME.
Articulated items are placed in their reference pose (local noon, beta = 0):
solar array wings horizontal with the cell side up (-Z, toward the zenith Sun),
EATCS radiators hanging nadir (plane Y-Z, edge to the zenith Sun), PVRs and
Russian arrays per iss_spec. The OTL group of each item turns the reference
pose with the Sun during the orbit (see GROUPS).
"""
import math
import iss_spec as S

# ----------------------------------------------------------------- classes
SHELL_BODY_CLASSES = ['skin_usos', 'skin_rus']          # body-group shells
SHELL_CLASSES = SHELL_BODY_CLASSES + ['hrs', 'pvr', 'saw', 'rsa']
SOLID_BODY_CLASSES = ['truss', 'box', 'payload']        # radiating solids (body group)
SOLID_CLASSES = SOLID_BODY_CLASSES + ['rack']           # racks sit inside the cabins (no radiation)
GROUP_CLASSES = {'hrs': ['hrs'], 'sarj': ['pvr', 'rsa'], 'saw': ['saw']}

# articulation groups -> OTL spacecraft axes/orientation (validated in smoke s03)
GROUPS = {
    'body': dict(label='OTL body: modules, truss, boxes (+Z nadir, +X velocity)',
                 axes=('z', 'x'), orient=('nadir', 'velocity'), default_optics=['0.3', '0.8']),
    # EATCS radiators: TRRJ rolls the wing about X. Reference pose = TRRJ zero (panel plane X-Z, normal +/-Y).
    # 'zero' law (beta 0): daylight = body attitude (edge to Sun at every orbit angle); 'track' law: model z points
    # away from the Sun projected on the plane normal to X (edge to Sun for any beta). Eclipse: normal (model y) to nadir.
    'hrs': dict(label='OTL EATCS radiators: edge to Sun in daylight, face to Earth in eclipse (TRRJ about X)',
                axes=('x', 'z'), orient=('velocity', 'nadir'), default_optics=['0.2', '0.9'],
                eclipse=dict(axes=('x', 'y'), orient=('velocity', 'nadir'))),
    'sarj': dict(label='OTL SARJ frame: PVRs and Russian arrays (rotate about Y with the Sun)',
                 axes=('y', 'z'), orient=('antinormal', 'antisun'), default_optics=['0.2', '0.9']),
    'saw': dict(label='OTL US solar array wings: cell side normal to the Sun (SARJ + BGA)',
                axes=('z', 'y'), orient=('antisun', 'antinormal'), default_optics=['0.7', '0.8']),
}


def _opt(o):
    return [str(o['alpha']), str(o['eps'])]


def optics_by_group(case=None):
    O = {k: dict(v) for k, v in S.OPTICS.items()}
    for k, v in S.OPTICS_BY_CASE.get(case, {}).items():
        O[k] = dict(v)
    return {
        'body': [dict(name='skin_usos', classes=['skin_usos'], label='USOS module MMOD shield (outward side only)', direction='RadiationDirectionPlus',
                      both=_opt(O['skin_usos'])),
                 dict(name='skin_rus', classes=['skin_rus'], label='Russian module outer surface (outward side only)', direction='RadiationDirectionPlus',
                      both=_opt(O['skin_rus'])),
                 dict(name='truss', classes=['truss'], label='truss envelope', both=_opt(O['truss'])),
                 dict(name='box', classes=['box'], label='external ORU boxes (MLI + beta cloth)', both=_opt(O['box'])),
                 dict(name='payload', classes=['payload'], label='external payload blocks', both=_opt(O['payload']))],
        'hrs': [dict(name='hrs', classes=['hrs'], label='EATCS radiator panels Z-93 (both faces)', both=_opt(O['z93']))],
        'sarj': [dict(name='pvr', classes=['pvr'], label='PVR panels Z-93 (both faces)', both=_opt(O['z93'])),
                 dict(name='rsa', classes=['rsa'], label='Russian array: cells up, back down', two_sided=True,
                      up=_opt(O['rsa_back']), down=_opt(O['rsa_cells']))],
        'saw': [dict(name='saw', classes=['saw'], label='US array blanket: cells toward the Sun (-Z side)', two_sided=True,
                     up=_opt(O['saw_back']), down=_opt(O['saw_cells']))],
    }


OPTICS_BY_GROUP = optics_by_group()


def mesh_sizes(a):
    base = S.MESH_H
    if getattr(a, 'lite', False):
        return {k: v * 1.6 for k, v in base.items()}
    return dict(base)


# ----------------------------------------------------------------- helpers
def cyl_bbox(c, e):
    ax = 'xyz'.index(c['axis']); lo = list(c['p0']); hi = list(c['p0'])
    for k in range(3):
        if k == ax: hi[k] = c['p0'][k] + c['L']
        else: lo[k] -= c['R']; hi[k] += c['R']
    return [v - e for v in lo], [v + e for v in hi]


def panel_bbox(p, e):
    # work-plane local (u, v) -> global: xy:(x,y) at z; yz:(y,z) at x; zx:(z,x) at y
    u0, v0, u1, v1 = p['u0'], p['v0'], p['u0'] + p['du'], p['v0'] + p['dv']
    if p['plane'] == 'xy': lo, hi = [u0, v0, p['offset']], [u1, v1, p['offset']]
    elif p['plane'] == 'yz': lo, hi = [p['offset'], u0, v0], [p['offset'], u1, v1]
    else: lo, hi = [v0, p['offset'], u0], [v1, p['offset'], u1]
    return [v - e for v in lo], [v + e for v in hi]


def panel_center(p):
    lo, hi = panel_bbox(p, 0.0)
    return [(lo[k] + hi[k]) / 2 for k in range(3)]


# ----------------------------------------------------------------- orbit
def orbit(case):
    C = S.CASES[case]; O = S.ORBIT
    R = O['R_earth_m'] + O['alt_m']; mu = O['mu']
    per = 2 * math.pi * math.sqrt(R ** 3 / mu)
    i = math.radians(O['incl_deg']); b = math.radians(C['beta_deg'])
    u0 = math.radians(C.get('u0_deg', 0.0))
    w = f'(2*pi*t/{per:.4f}+{u0:.6f})'
    funcs = {'rx': f'{R:.1f}*cos({w})', 'ry': f'{R:.1f}*sin({w})*cos({i:.8f})', 'rz': f'{R:.1f}*sin({w})*sin({i:.8f})'}
    # Sun direction: s = cos(b) e_node + sin(b) h, h = (0, -sin i, cos i) = orbit normal; u = 0 is local noon
    s = [math.cos(b), -math.sin(b) * math.sin(i), math.sin(b) * math.cos(i)]
    rays = [f'{-v:.8f}' for v in s]
    # eclipse half-angle about midnight (cylindrical shadow), for reporting only
    rho = math.asin(O['R_earth_m'] / R)
    ecl = 0.0 if abs(b) >= rho else 2 * math.degrees(math.acos(min(1.0, math.cos(rho) / math.cos(b))))
    return dict(period=per, funcs=funcs, rays=rays, sun_ecs=s, eclipse_deg=ecl, R=R)


# ----------------------------------------------------------------- build
def build(case, lite=False):
    lay = S.layout(case, lite=lite)          # cylinders, blocks, panels, loops ... (station-specific)
    ob = orbit(case)
    lay['period'] = ob['period']; lay['orbit_funcs'] = ob['funcs']; lay['sun_rays_ecs'] = ob['rays']
    lay['orbit_info'] = ob
    C = S.CASES[case]
    lay['params'] = {
        'S_sun': (f"{C['S_sun']}[W/m^2]", 'solar irradiance'),
        'albedo': (str(C['albedo']), 'Earth albedo (uniform)'),
        'q_olr': (f"{C['olr']}[W/m^2]", 'outgoing long-wave radiation (uniform)'),
        't0_frozen': (f"{C.get('t0_frozen', 0.0)}[s]", 'orbit time frozen in study F'),
        'Q_scale': (str(C.get('Q_scale', 1.0)), 'multiplier on internal payload/rack power'),
    }
    lay['block_by_name'] = {b['name']: b for b in lay['blocks']}
    groups = {k: dict(v) for k, v in GROUPS.items()}
    if C.get('hrs_law') == 'track':
        groups['hrs']['orient'] = ('velocity', 'antisun')
    lay['groups'] = groups
    lay['optics_by_group'] = optics_by_group(case)
    for b in lay['blocks']:
        b.setdefault('Qexpr', f"{b.get('Q', 0.0)}[W]*{'Q_scale' if b.get('scaled') else '1'}")
    lay['racks_by_module'] = {}
    for b in lay['blocks']:
        if b['cls'] == 'rack':
            lay['racks_by_module'].setdefault(b['module'], []).append(b['name'])
    _loops(lay)
    return lay


def _loops(lay):
    """Loop bookkeeping: integration operators, global variables, DAE rows."""
    P = S.LOOPS
    ops = []            # (opname, selection resolver)
    gv = {}
    rows = []

    # --- heat pick-up per loop from cold-plate faces and cabin air
    pick = {L: [] for L in P['loops']}
    for b in lay['blocks']:
        cl = b.get('cool')
        if not cl: continue
        op = 'ic_' + b['name']
        ops.append((op, ('face', b['name'], cl['face'])))
        pick[cl['loop']].append(f"{op}({cl['h']}*(T-{cl['T']}))")
    for mod, racks in lay['racks_by_module'].items():
        op = 'ia_' + mod
        ops.append((op, ('air', mod)))
        lt_loop = S.MODULE_LOOPS[mod]['LT']
        pick[lt_loop].append(f"{op}(h_air*(T-T_cab))")
    for c in lay['cylinders']:
        if c['name'] in S.MODULE_LOOPS:
            op = 'is_' + c['name']
            ops.append((op, ('skin', c['name'])))
            pick[S.MODULE_LOOPS[c['name']]['LT']].append(f"-{op}(h_mli*(T_cab-T2))")
    for L, extra in P.get('other_loads', {}).items():
        pick[L].append(extra)
    # the collected heat is a global UNKNOWN Qc_L with the algebraic equation Qc_L = sum(pick-ups):
    # only that one row touches all rack/box DOFs; radiator panels then depend on Qc_L alone
    # (a global VARIABLE would put every rack DOF into every panel row: dense Jacobian block)
    qrows = []
    for L in P['loops']:
        gv[f'Q_{L}'] = f'Qc_{L}'
        expr = ' + '.join(pick[L]) if pick[L] else '0[W]'
        qrows.append((f'Qc_{L}', f'tau_Q*Qc_{L}t-(({expr})-Qc_{L})', '24[kW]' if not L.startswith('PV') else '6[kW]', f'{L}: heat collected by the loop (cold plates, IFHX), 20 s lag', 'Q'))

    # --- radiator chains
    for L, d in P['loops'].items():
        mdot, cp, Tset = d['mdot'], 'cp_nh3', d['T_set']
        gv[f'Tret_{L}'] = f"{Tset}+Q_{L}/({mdot}*{cp})"
        outs = []
        for k, oru in enumerate(d['orus']):
            panels = [p for p in lay['panels'] if p.get('fluid') and p['fluid']['loop'] == L and p['fluid']['oru'] == oru]
            panels.sort(key=lambda p: p['fluid']['idx'])
            prev = f'Tret_{L}'
            for p in panels:
                i = p['fluid']['idx']; tf = f"Tf_{L}_{k+1}_{i}"
                p['fluid']['qexpr'] = f"{d['g']}*(0.5*({prev}+{tf})-T2)"
                p['fluid']['t_name'] = 't_' + p['cls']
                eq = f"C_f*{tf}t-((feff_{L}*{mdot}/{len(d['orus'])})*{cp}*({prev}-{tf})-ip_{p['name']}({p['fluid']['qexpr']}))"
                rows.append((tf, eq, d.get('Tf_init', f'{Tset}-10[K]'), f'{L} ORU {oru} panel {i} NH3 outlet T', 'T'))
                prev = tf
            outs.append(prev)
        gv[f'Tout_{L}'] = '(' + '+'.join(outs) + f')/{len(outs)}'
        # radiator flow fraction: valve travel bounded below by f_min (fully bypassed valve) with a smooth
        # softplus; anti-windup pulls the integrator back when it runs below f_min (low loop load)
        gv[f'feff_{L}'] = f"f_min+s_f*log(1+exp((f_{L}-f_min)/s_f))"
        gv[f'Tmix_{L}'] = f"feff_{L}*Tout_{L}+(1-feff_{L})*Tret_{L}"
        rows.insert(0, (f'f_{L}', f"k_c*f_{L}t-(Tmix_{L}-{Tset})+k_aw*s_f*log(1+exp((f_min-f_{L})/s_f))", str(d.get('f_init', 0.3)),
                        f'{L}: radiator flow fraction, integral control of the mixed supply temperature', 'f'))
        gv[f'Qrad_{L}'] = f"feff_{L}*{mdot}*{cp}*(Tret_{L}-Tout_{L})"
    lay['int_ops_spec'] = ops
    lay['global_vars'] = gv
    lay['ge_rows'] = qrows + rows

    def int_ops(builder):
        out = []
        for op, spec in ops:
            if spec[0] == 'face':
                out.append((op, (builder.block_face[(spec[1], spec[2])], 2)))
            elif spec[0] == 'air':
                out.append((op, ('sair_' + spec[1], 2)))
            elif spec[0] == 'skin':
                out.append((op, (builder.skin_sel[spec[1]], 2)))
        return out
    lay['int_ops'] = int_ops
