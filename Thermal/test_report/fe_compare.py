# -*- coding: utf-8 -*-
"""Prototype comparison of the SDTwin thermal design report formulas against the ISS FE results.

The prototype follows the design report literally:
  T3 line 1  C_S dT_S/dt = Q_env,S - P_pv - q_SR - Q_emit,S        (q_SR = 0, the FE has no array-radiator conduction)
  T3 line 6  C_R dT_R/dt = q_SR + q_CR + q_BR + q_DR + Q_env,R - Q_emit,R   (sum of q replaced by the FE heat input)
  T3 line 2  C_J dT_J/dt = P_load - q_JC, q_JC = (T_J - T_C)/R_JC at steady state with T_C held at the coolant
  T4         g_sun = G max(0, cos theta); Q_env = sum A [alpha (g_sun + g_alb) + eps g_IR]; Q_emit = sum eps sigma A T^4
  T5         C = sum m c_p;  R = l/(kappa A) + R_contact
Integration follows design chapter 8: adaptive RK45, split at the eclipse boundaries, output sampled on the accepted solution.
All parameters come from Thermal/iss_fem/model/iss_spec.py; nothing is fitted.
"""
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

HERE = Path(__file__).resolve().parent
ISS = HERE.parent / 'iss_fem'
sys.path.insert(0, str(ISS / 'model'))
import iss_spec as S  # noqa: E402

SIG = 5.670374419e-8                       # design report table 5
R_E = S.ORBIT['R_earth_m']
A_ORB = R_E + S.ORBIT['alt_m']
T_ORB = 2 * math.pi * math.sqrt(A_ORB**3 / S.ORBIT['mu'])
CASES = ('cold0', 'nom0', 'hot75')
RK = dict(method='RK45', rtol=1e-8, atol=1e-6, max_step=30.0)

# ---------------------------------------------------------------- Earth view factor and albedo factor of a plate
_PSI_MAX = math.acos(R_E / A_ORB)
_NPSI, _NPHI = 240, 360
_psi = (np.arange(_NPSI) + 0.5) * _PSI_MAX / _NPSI
_phi = (np.arange(_NPHI) + 0.5) * 2 * math.pi / _NPHI
_PS, _PH = np.meshgrid(_psi, _phi, indexing='ij')
_EP = np.stack([np.sin(_PS) * np.cos(_PH), np.sin(_PS) * np.sin(_PH), np.cos(_PS)], -1)
_DA = R_E**2 * np.sin(_PS) * (_PSI_MAX / _NPSI) * (2 * math.pi / _NPHI)
_D = R_E * _EP - np.array([0.0, 0.0, A_ORB])
_DIST = np.linalg.norm(_D, axis=-1)
_DHAT = _D / _DIST[..., None]
_KERN = np.einsum('ijk,ijk->ij', _EP, -_DHAT).clip(0) * _DA / (math.pi * _DIST**2)


def earth_terms(rhat, n, shat):
    """View factor to Earth and albedo factor of a plate with outward normal n at position rhat.
    g_IR = OLR * F and g_alb = albedo * S * F_alb are the per-surface irradiances that earth_flux supplies."""
    z = rhat
    tmp = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(tmp, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    m = np.stack([x, y, z])
    cos_p = np.einsum('ijk,k->ij', _DHAT, m @ n).clip(0)
    lit = np.einsum('ijk,k->ij', _EP, m @ shat).clip(0)
    return float((_KERN * cos_p).sum()), float((_KERN * cos_p * lit).sum())


def orbit_frame(beta_deg):
    p, q, h = np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
    b = math.radians(beta_deg)
    return p, q, h, math.cos(b) * p + math.sin(b) * h


def eclipse_window(beta_deg):
    """Cylindrical-shadow eclipse interval in seconds after orbit noon, or None (G already includes eclipse)."""
    c = math.sqrt(1 - (R_E / A_ORB)**2) / math.cos(math.radians(beta_deg))
    if c >= 1:
        return None
    w = math.acos(c)
    return (math.pi - w) / (2 * math.pi) * T_ORB, (math.pi + w) / (2 * math.pi) * T_ORB


def segments(beta_deg):
    """Orbit split at the eclipse boundaries: (t0, t1, sunlit) with t measured from orbit noon."""
    ecl = eclipse_window(beta_deg)
    if ecl is None:
        return [(0.0, T_ORB, True)]
    return [(0.0, ecl[0], True), (ecl[0], ecl[1], False), (ecl[1], T_ORB, True)]


def position(t):
    u = 2 * math.pi * t / T_ORB
    return np.array([math.cos(u), math.sin(u), 0.0]), np.array([-math.sin(u), math.cos(u), 0.0])


def integrate(rhs, segs, y0, t_end, sample=10.0):
    """Adaptive RK45 run split at every segment boundary; output sampled on the accepted solution."""
    ts, ys, y, t = [0.0], [y0], y0, 0.0
    k = 0
    while t < t_end - 1e-9:
        for (a, b, lit) in segs:
            t0, t1 = k * T_ORB + a, min(k * T_ORB + b, t_end)
            if t1 <= t0 + 1e-9:
                continue
            ev = np.arange(math.ceil(t0 / sample) * sample, t1, sample)
            ev = np.unique(np.concatenate([ev[ev > t0], [t1]]))
            sol = solve_ivp(lambda tt, yy: rhs(tt, yy, lit), (t0, t1), [y], t_eval=ev, **RK)
            if not sol.success:
                raise RuntimeError(sol.message)
            ts.extend(sol.t.tolist())
            ys.extend(sol.y[0].tolist())
            y, t = sol.y[0][-1], t1
        k += 1
    return np.array(ts), np.array(ys)


def read_series(case):
    with open(ISS / 'out' / case / 'series.csv', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    return {c: np.array([float(r[c]) for r in rows]) for c in rows[0]}


def last_orbit_stats(t, v):
    """Time-weighted min / mean / max over the exact last orbital period."""
    t0 = t[-1] - T_ORB
    tt = np.concatenate([[t0], t[t > t0]])
    vv = np.interp(tt, t, v)
    return float(vv.min()), float(np.trapezoid(vv, tt) / (tt[-1] - tt[0])), float(vv.max())


def last_orbit_curve(t, v):
    t0 = t[-1] - T_ORB
    sel = t >= t0 - 1e-6
    return (t[sel] - t0).tolist(), v[sel].tolist()


def env_table(segs, fn):
    """Per-segment tables of an environment quantity on a 10 s grid inside the segment, boundaries included."""
    out = []
    for (a, b, lit) in segs:
        g = np.unique(np.concatenate([np.arange(a, b, 10.0), [b]]))
        out.append((a, b, lit, g, np.array([fn(t, lit) for t in g])))
    return out


def env_value(tab, t):
    ph = t % T_ORB
    for (a, b, lit, g, v) in tab:
        if a - 1e-6 <= ph <= b + 1e-6:
            return float(np.interp(ph, g, v))
    return float(np.interp(ph, tab[-1][3], tab[-1][4]))


# ---------------------------------------------------------------- S node, design T3 line 1 with T4
SAW = dict(alpha_f=S.OPTICS['saw_cells']['alpha'] + 0.073, eps_f=S.OPTICS['saw_cells']['eps'],
           alpha_b=S.OPTICS['saw_back']['alpha'], eps_b=S.OPTICS['saw_back']['eps'],
           c=S.MATERIALS['saw_blk']['rho'] * S.MATERIALS['saw_blk']['cp'] * S.MATERIALS['saw_blk']['t'])
PV_FRACTION = 0.073        # blanket-average electrical output over incident sunlight, iss_spec OPTICS note


def s_node(case, pv=True, earth=True, n_orb=6):
    """Per square metre of blanket: front normal points at the Sun, back normal away from it."""
    cs = S.CASES[case]
    p, q, _, shat = orbit_frame(cs['beta_deg'])
    segs = segments(cs['beta_deg'])

    def q_env(t, lit):
        rh, _ = position(t)
        rhat = rh[0] * p + rh[1] * q
        g = cs['S_sun'] if lit else 0.0                       # G already includes eclipse
        val = SAW['alpha_f'] * g * 1.0                         # cos theta = 1 on the sun-pointing front face
        if earth:
            ff, af = earth_terms(rhat, shat, shat)
            fb, ab = earth_terms(rhat, -shat, shat)
            val += (SAW['alpha_f'] * cs['albedo'] * cs['S_sun'] * af + SAW['eps_f'] * cs['olr'] * ff
                    + SAW['alpha_b'] * cs['albedo'] * cs['S_sun'] * ab + SAW['eps_b'] * cs['olr'] * fb)
        return val

    tab = env_table(segs, q_env)

    def rhs(t, y, lit):
        p_pv = PV_FRACTION * cs['S_sun'] if (pv and lit) else 0.0
        q_emit = (SAW['eps_f'] + SAW['eps_b']) * SIG * y[0]**4
        return [(env_value(tab, t) - p_pv - q_emit) / SAW['c']]

    ts, temps = integrate(rhs, segs, 290.0, n_orb * T_ORB)
    temps = temps - 273.15
    stats = last_orbit_stats(ts, temps)
    sel = ts >= ts[-1] - T_ORB - 1e-6
    phase = ts[sel] % T_ORB
    order = np.argsort(phase)
    return stats, phase[order][::3].tolist(), temps[sel][order][::3].tolist()


# ---------------------------------------------------------------- R node, design T3 line 6 with T4 and T5
HRS = S.HRS
_LP = (abs(HRS['x_tip'] - HRS['x_root']) - (HRS['n_panels'] - 1) * HRS['gap']) / HRS['n_panels']
R_AREA = 3 * HRS['n_panels'] * HRS['width'] * _LP                      # one side, per loop
_M = S.MATERIALS['hrs_pan']
R_CAP = R_AREA * _M['rho'] * _M['cp'] * _M['t'] + 3 * HRS['n_panels'] * 1000.0   # T5: panels plus NH3 nodes, C_f 1 kJ/K each
LOOP_ORUS = {'A': ['A_S1-1', 'A_S1-2', 'A_S1-3'], 'B': ['B_P1-1', 'B_P1-2', 'B_P1-3']}


def r_node(case, ser):
    cs = S.CASES[case]
    z93 = dict(S.OPTICS['z93'])
    z93.update(S.OPTICS_BY_CASE.get(case, {}).get('z93', {}))
    p, q, h, shat = orbit_frame(cs['beta_deg'])
    segs = segments(cs['beta_deg'])

    def q_env(t, lit):
        rh, vh = position(t)
        rhat = rh[0] * p + rh[1] * q
        vhat = vh[0] * p + vh[1] * q
        if not lit:
            normals = (-rhat, rhat)                            # face to Earth in eclipse
        elif cs['hrs_law'] == 'zero':
            normals = (h, -h)                                  # TRRJ zero: normal perpendicular to the orbit plane
        else:
            n = np.cross(vhat, shat)
            n /= np.linalg.norm(n)
            normals = (n, -n)                                  # Sun kept in the panel plane
        g = cs['S_sun'] if lit else 0.0
        val = 0.0
        for n in normals:
            fv, fa = earth_terms(rhat, n, shat)
            g_sun = g * max(0.0, float(n @ shat))
            val += z93['alpha'] * (g_sun + cs['albedo'] * cs['S_sun'] * fa) + z93['eps'] * cs['olr'] * fv
        return val * R_AREA

    tab = env_table(segs, q_env)
    t = ser['t_s']
    out = {}
    for loop, orus in LOOP_ORUS.items():
        tfem = np.mean([ser[o + '_Tmean_C'] for o in orus], axis=0)
        qin = ser['Qrad_' + loop]

        def rhs(tt, y, lit, qin=qin):
            q_emit = 2 * z93['eps'] * SIG * R_AREA * y[0]**4
            return [(np.interp(tt, t, qin) + env_value(tab, tt) - q_emit) / R_CAP]

        ts, temps = integrate(rhs, segs, tfem[0] + 273.15, t[-1])
        temps = temps - 273.15
        fem_t, fem_v = last_orbit_curve(t, tfem)
        lum_t, lum_v = last_orbit_curve(ts, temps)
        out[loop] = dict(q_in_kW=last_orbit_stats(t, qin)[1] / 1e3,
                         fem=last_orbit_stats(t, tfem), lumped=last_orbit_stats(ts, temps),
                         curve_fem=[fem_t, fem_v], curve_lumped=[lum_t[::3], lum_v[::3]])
    return out, z93


def r_spread(ser):
    t = ser['t_s']
    sel = t > t[-1] - T_ORB
    tmin = ser['hrs_Tmin_C']
    i = int(np.argmin(np.where(sel, tmin, 1e9)))
    spread = (ser['hrs_Tmax_C'] - tmin)[sel]
    return dict(coldest_C=float(tmin[i]), mean_same_instant_C=float(ser['hrs_Tmean_C'][i]),
                max_minus_min_K=[float(spread.min()), float(spread.max())])


# ---------------------------------------------------------------- J node on a cold plate held at the coolant, design T3 line 2 and T5
def jc_chain(case):
    items = {}
    with open(ISS / 'out' / case / 'items.csv', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            items[r['name']] = r
    lb = {}
    with open(ISS / 'out' / case / 'loop_breakdown.csv', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            lb[(r['loop'], r['source'])] = float(r['W_mean'])
    kappa = S.MATERIALS['oru_eq']['k']
    h_cp = 60.0
    t_c = 2.78
    share = lb[('A', 'oru')] / (2 * 495 + 3 * 694)             # MBSU and DDCU heat reaching the cold plate

    def face(size, fc):
        ax = 'xyz'.index(fc[1])
        o = [i for i in range(3) if i != ax]
        return size[o[0]] * size[o[1]], size[ax]

    rows = []
    for label, size, q, fc, key, q_cp in (
            ('MBSU', S.ORU_BOXES[0][1], 495.0, '+z', 'MBSU_1', None),
            ('DDCU', S.ORU_BOXES[4][1], 694.0, '-x', 'DDCU_S0_1A', None),
            ('IEA', S.IEA['size'], S.IEA['Q'], '-z', 'IEA_P4', lb[('PVP4', 'iea')])):
        a, depth = face(size, fc)
        p_load = q * share if q_cp is None else q_cp
        r_contact = 1 / (h_cp * a)                              # T5 R_contact: cold-plate face conductance
        r_cond = (depth / 3) / (kappa * a)                       # T5 l/(kappa A) with l = depth/3 for uniform generation
        r_jc = r_contact + r_cond
        rows.append(dict(name=label, Q_W=q, P_load_W=p_load, A_m2=a, R_contact=r_contact, R_cond=r_cond, R_JC=r_jc,
                         lumped_C=t_c + p_load * r_jc, lumped_all_heat_C=t_c + q * r_jc,
                         fem_C=float(items[key]['Tmean_C'])))
    return rows, share


def main():
    res = dict(orbit_period_s=T_ORB, rk=RK, cases={})
    f0, _ = earth_terms(np.array([0, 0, 1.0]), np.array([0, 0, -1.0]), np.array([0, 0, 1.0]))
    res['nadir_view_factor'] = dict(numeric=f0, exact=(R_E / A_ORB)**2)
    res['s_params'] = dict(SAW, pv_fraction=PV_FRACTION)
    res['r_params'] = dict(area_one_side_m2=R_AREA, capacity_J_K=R_CAP)
    for case in CASES:
        ser = read_series(case)
        cs = S.CASES[case]
        s_stats, s_phase, s_temp = s_node(case)
        fem_s = last_orbit_stats(ser['t_s'], ser['saw_Tmean_C'])
        fem_t, fem_v = last_orbit_curve(ser['t_s'], ser['saw_Tmean_C'])
        t0 = ser['t_s'][-1] - T_ORB
        fem_phase = np.array([(t0 + x) % T_ORB for x in fem_t])
        order = np.argsort(fem_phase)
        no_earth = s_node(case, earth=False)[0]
        no_pv = s_node(case, pv=False)[0]
        r_res, z93 = r_node(case, ser)
        res['cases'][case] = dict(
            env=dict(beta_deg=cs['beta_deg'], S_sun=cs['S_sun'], albedo=cs['albedo'], olr=cs['olr'], z93=z93),
            eclipse_s=eclipse_window(cs['beta_deg']), last_orbit_start_s=float(t0),
            S=dict(fem=fem_s, lumped=s_stats, no_earth=no_earth, no_pv=no_pv,
                   curve_fem=[fem_phase[order].tolist(), np.array(fem_v)[order].tolist()],
                   curve_lumped=[s_phase, s_temp]),
            R=r_res, R_spread=r_spread(ser))
        print(case, 'S fem', np.round(fem_s, 1), 'lumped', np.round(s_stats, 1),
              'no_earth', np.round(no_earth, 1), 'no_pv', np.round(no_pv, 1),
              '| R A', np.round(r_res['A']['fem'][1], 1), np.round(r_res['A']['lumped'][1], 1),
              '| R B', np.round(r_res['B']['fem'][1], 1), np.round(r_res['B']['lumped'][1], 1))
    rows, share = jc_chain('nom0')
    res['jc'] = dict(rows=rows, cold_plate_share=share)
    for r in rows:
        print(r['name'], 'P_load', round(r['P_load_W'], 1), 'R_JC', round(r['R_JC'], 5),
              'lumped', round(r['lumped_C'], 2), 'all heat', round(r['lumped_all_heat_C'], 2), 'fem', round(r['fem_C'], 2))
    out = HERE / 'out'
    out.mkdir(exist_ok=True)
    (out / 'fe_compare.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', out / 'fe_compare.json')


if __name__ == '__main__':
    main()
