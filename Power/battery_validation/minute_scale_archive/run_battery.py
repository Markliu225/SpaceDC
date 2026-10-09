"""Four time-domain battery experiments, with independent conservation and diffusion checks.

The repository model is never modified. Freeze contract.json before running MATLAB.
Run with Thermal/.venv/Scripts/python.exe for SciPy.
"""
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import eigh_tridiagonal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'results'
sys.path.insert(0, str(ROOT / 'Thermal'))
from sdtwin_sim import power_stand_in as ps

FIELDS = ['time_s', 'segment', 'current_A', 'xn', 'xp', 'soc', 'voltage_V',
          'power_W', 'heat_W', 'energy_port_J', 'energy_heat_J', 'ocv_mean_V',
          'ocp_surface_V', 'activation_V', 'ohmic_V', 'heat_reaction_W',
          'heat_ohmic_W', 'heat_reversible_W', 'xn_surface', 'xp_surface', 'min_margin']


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def csv(path, names, rows):
    np.savetxt(path, rows, delimiter=',', header=','.join(names), comments='', fmt='%.17g')


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    asset, scene = ps.example_power_records()
    asset = copy.deepcopy(asset)
    scene = copy.deepcopy(scene)
    asset['battery']['N_s'] = asset['battery']['N_p'] = 1
    p0 = ps.example_power_parameters().battery
    xn = (p0.x_n_0 + p0.x_n_100) / 2
    # Inventory follows the original supplied example; no fitted parameters.
    xp = scene['initial_state']['x_p'] + p0.Q_n_C / p0.Q_p_C * (scene['initial_state']['x_n'] - xn)
    scene['initial_state'].update(x_n=xn, x_p=xp, T_B_K=298.15)
    def case(cid, title, segments):
        start = 0
        ss = []
        for end, current in segments:
            ss.append(dict(start_s=start, end_s=end, current_A=current))
            start = end
        return dict(id=cid, title=title, segments=ss)
    contract = dict(version=1, date='2026-10-08', parameters=asset, scene=scene,
        initial=dict(xn=xn, xp=xp, soc=0.5, temperature_K=298.15, uniform_particle_profiles=True),
        capacity_Ah=p0.Q_n_C*(p0.x_n_100-p0.x_n_0)/3600,
        electrode_capacity_C=dict(n=p0.Q_n_C, p=p0.Q_p_C),
        numerics=dict(output_interval_s=1, max_step_s=2, rtol=1e-9, atol=1e-11,
                      scipy_solver='DOP853', simulink_solver='ode45', diffusion_shells=[128,256]),
        acceptance=dict(simulink_voltage_V=1e-6, simulink_fraction=1e-9, simulink_energy_J=1e-5,
                        analytic_soc=1e-9, inventory_relative=1e-10, decomposition=1e-10,
                        fv_mean_fraction=1e-8, fv_mesh_voltage_V=1e-4, energy_quadrature_J=1e-5),
        scope='Illustrative single cell, prescribed current, isothermal; no calibrated cell, charger, PDU or orbit.',
        cases=[case('BAT-T01','恒流充电',[(60,0),(1860,-0.5)]),
               case('BAT-T02','恒流放电',[(60,0),(1860,0.5)]),
               case('BAT-T03','等电量充放电循环',[(60,0),(960,-0.5),(1260,0),(2160,0.5),(3060,0)]),
               case('BAT-T04','放电脉冲与静置恢复',[(60,0),(360,1),(1560,0)])])
    save(OUT/'contract.json', contract)
    return contract, ps.load_power_parameters(asset, scene)


def state(t, xn, xp):
    return ps.PowerState('battery_validation', 'Cell01', float(t), float(xn), float(xp), True, False, ())


def mean_ocv(xn, xp, c):
    e = c['parameters']['battery']['electrodes']
    return np.polynomial.polynomial.polyval(xp, e['p']['b_V']) - np.polynomial.polynomial.polyval(xn, e['n']['b_V'])


def project(case, c, p):
    initial = c['initial']
    z = np.array([initial['xn'], initial['xp'], 0., 0.])
    data, steps, execution = [], [], []
    for j, seg in enumerate(case['segments']):
        i = seg['current_A']
        def rhs(t, x):
            b = ps.battery_response(i, state(t, x[0], x[1]), initial['temperature_K'], p)
            return [b.dx_n_dt, b.dx_p_dt, b.P_B_W, b.Q_B_W]
        tic = time.perf_counter()
        sol = solve_ivp(rhs, (seg['start_s'], seg['end_s']), z, method='DOP853',
                        rtol=c['numerics']['rtol'], atol=c['numerics']['atol'],
                        max_step=c['numerics']['max_step_s'], dense_output=True)
        if not sol.success:
            raise RuntimeError(sol.message)
        steps.extend([[j, t, *x] for t, x in zip(sol.t, sol.y.T)])
        ts = np.arange(seg['start_s'], seg['end_s']+0.5, 1.)
        for t, x in zip(ts, sol.sol(ts).T):
            b = ps.battery_response(i, state(t, x[0], x[1]), initial['temperature_K'], p)
            data.append([t,j,i,x[0],x[1],p.battery.soc(x[0]),b.v_cell_V,b.P_B_W,b.Q_B_W,x[2],x[3],
                         mean_ocv(x[0],x[1],c),b.U_p_V-b.U_n_V,b.dv_n_V+b.dv_p_V,i*p.battery.R_ohm_ohm,
                         i*(b.dv_n_V+b.dv_p_V),i*i*p.battery.R_ohm_ohm,b.q_reversible_cell_W,
                         b.x_n_surface,b.x_p_surface,min(b.constraint_margins.values())])
        execution.append(dict(segment=j, accepted_steps=len(sol.t)-1, derivative_evaluations=sol.nfev,
                              max_accepted_step_s=float(np.max(np.diff(sol.t))), seconds=time.perf_counter()-tic,
                              start_state=z.tolist(), end_state=sol.y[:,-1].tolist()))
        z = sol.y[:,-1]  # carry integrated state, including energy, across scheduled current events
    a = np.asarray(data)
    csv(OUT/f'{case["id"]}_python.csv',FIELDS,a)
    csv(OUT/f'{case["id"]}_accepted_steps.csv',['segment','time_s','xn','xp','energy_port_J','energy_heat_J'],steps)
    return a, execution


class SphericalDiffusion:
    """Conservative shell FV; exact-in-time propagation for constant imposed flux.

    v_j = integral rho^2 d rho. d< x >/dt = m, surface dx/d rho = m R^2/(3D).
    Matrix is self-adjoint under shell-volume weighting. No repository function is called.
    """
    def __init__(self, electrode, capacity, shells, initial):
        self.q = capacity
        self.DR2 = electrode['D_ref_m2_s']/electrode['radius_m']**2
        e = np.linspace(0,1,shells+1)
        self.v = np.diff(e**3)/3
        self.sqrtv = np.sqrt(self.v)
        centers = (e[:-1]+e[1:])/2
        k = self.DR2 * e[1:-1]**2 / np.diff(centers)
        diag = np.zeros(shells)
        diag[:-1] -= k/self.v[:-1]
        diag[1:] -= k/self.v[1:]
        off = k/np.sqrt(self.v[:-1]*self.v[1:])
        self.lam, self.V = eigh_tridiagonal(diag, off)
        self.lam[-1] = 0.0
        self.profile = np.full(shells, initial)
        # Surface reconstruction from two outer volume averages plus imposed derivative.
        mu1 = .75*np.diff(e**4)/np.diff(e**3)
        mu2 = .6*np.diff(e**5)/np.diff(e**3)
        mat = np.array([[1,mu1[-2],mu2[-2]], [1,mu1[-1],mu2[-1]], [0,1,2]])
        self.surface_weights = np.array([1.,1.,1.]) @ np.linalg.inv(mat)

    def advance(self, offsets, mean_rate):
        a0 = self.V.T @ (self.sqrtv*self.profile)
        force = np.zeros_like(a0)
        force[-1] = mean_rate/(3*self.v[-1])
        f = self.V.T @ (self.sqrtv*force)
        lt = self.lam[:,None]*offsets[None,:]
        factors = np.empty_like(lt)
        factors[:-1] = np.expm1(lt[:-1])/self.lam[:-1,None]
        factors[-1] = offsets
        modes = np.exp(lt)*a0[:,None] + factors*f[:,None]
        profiles = (self.V @ modes)/self.sqrtv[:,None]
        self.profile = profiles[:,-1].copy()
        g = mean_rate/(3*self.DR2)
        w = self.surface_weights
        surface = w[0]*profiles[-2]+w[1]*profiles[-1]+w[2]*g
        mean = 3*self.v @ profiles
        return mean, surface


def independent_voltage(xn, xp, current, c):
    # Direct, separate formulation; same material inputs isolate diffusion-model effects.
    b=c['parameters']['battery']; n=b['electrodes']['n']; p=b['electrodes']['p']
    up=np.polynomial.polynomial.polyval(xp,p['b_V'])
    un=np.polynomial.polynomial.polyval(xn,n['b_V'])
    jn=2*n['I0_ref_A']*np.sqrt(xn*(1-xn)); jp=2*p['I0_ref_A']*np.sqrt(xp*(1-xp))
    activation=2*8.314462618*298.15/96485.33212*(np.arcsinh(current/(2*jn))+np.arcsinh(current/(2*jp)))
    return up-un-activation-current*b['R_ohm_ohm']


def diffusion(case,c,shells):
    es=c['parameters']['battery']['electrodes'];qs=c['electrode_capacity_C'];ini=c['initial']
    dn=SphericalDiffusion(es['n'],qs['n'],shells,ini['xn'])
    dp=SphericalDiffusion(es['p'],qs['p'],shells,ini['xp'])
    rows=[]
    for j,s in enumerate(case['segments']):
        dt=np.arange(0,s['end_s']-s['start_s']+.5,1.)
        i=s['current_A'];mn,sn=dn.advance(dt,-i/qs['n']);mp,sp=dp.advance(dt,i/qs['p'])
        vv=independent_voltage(sn,sp,i,c)
        rows.extend(np.column_stack([dt+s['start_s'],np.full_like(dt,j),np.full_like(dt,i),mn,mp,sn,sp,vv]))
    a=np.asarray(rows)
    csv(OUT/f'{case["id"]}_diffusion_{shells}.csv',
        ['time_s','segment','current_A','xn_mean','xp_mean','xn_surface','xp_surface','voltage_V'],a)
    return a


def main():
    c,p=freeze()
    metadata=dict(source_sha256=hashlib.sha256((ROOT/'Thermal/sdtwin_sim/power_stand_in.py').read_bytes()).hexdigest(),
                  python=sys.version, cases=[])
    for case in c['cases']:
        print('START',case['id'],flush=True)
        a,ex=project(case,c,p)
        for shells in c['numerics']['diffusion_shells']:
            diffusion(case,c,shells)
        metadata['cases'].append(dict(id=case['id'],segments=ex,output_rows=len(a)))
        print('DONE',case['id'],'SOC',a[-1,5],'V',a[-1,6],flush=True)
    save(OUT/'python_execution.json',metadata)


if __name__=='__main__':
    main()
