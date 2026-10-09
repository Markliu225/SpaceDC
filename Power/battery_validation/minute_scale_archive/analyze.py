"""Independent audit: coulomb counting, polynomial-energy quadrature and sphere series."""
import json
from pathlib import Path
import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq
from run_battery import independent_voltage, mean_ocv, save, csv

HERE=Path(__file__).resolve().parent
OUT=HERE/'results'


def read(cid,kind):
    return np.genfromtxt(OUT/f'{cid}_{kind}.csv',delimiter=',',names=True)


def sphere_series(case,c,times):
    # Eigenvalues of zero-flux radial spherical diffusion: tan(lambda)=lambda.
    # Unit mean-rate step surface response h(t). Superposition preserves memory.
    roots=np.array([brentq(lambda x:np.tan(x)-x,k*np.pi+1e-8,(k+.5)*np.pi-1e-8)
                    for k in range(1,201)])
    result=[]
    for pole,sign in [('n',-1),('p',1)]:
        e=c['parameters']['battery']['electrodes'][pole]
        a=e['D_ref_m2_s']/e['radius_m']**2
        surf=np.full(len(times),c['initial']['x'+pole])
        previous=0.
        for s in case['segments']:
            dm=sign*(s['current_A']-previous)/c['electrode_capacity_C'][pole]
            previous=s['current_A'];dt=times-s['start_s'];mask=dt>0;z=dt[mask]
            h=z+1/(15*a)-2/(3*a)*np.sum(np.exp(-a*roots[:,None]**2*z[None,:])/roots[:,None]**2,axis=0)
            surf[mask]+=dm*h
        result.append(surf)
    return result


def main():
    c=json.loads((OUT/'contract.json').read_text(encoding='utf-8'))
    pmeta=json.loads((OUT/'python_execution.json').read_text())
    smeta=json.loads((OUT/'simulink_execution.json').read_text())
    checks=[];cases=[];tol=c['acceptance'];q=c['electrode_capacity_C'];ini=c['initial']
    b=c['parameters']['battery'];span=b['x_n_100']-b['x_n_0'];inv0=q['n']*ini['xn']+q['p']*ini['xp']
    def check(cid,name,error,limit):
        checks.append(dict(case=cid,check=name,value=float(error),limit=float(limit),passed=bool(error<=limit)))
    for case in c['cases']:
        cid=case['id'];p=read(cid,'python');s=read(cid,'simulink');f=read(cid,'diffusion_256');coarse=read(cid,'diffusion_128')
        if len(s)!=len(p) or not np.array_equal(p['time_s'],s['time_s']) or not np.array_equal(p['segment'],s['segment']):
            raise RuntimeError(f'{cid}: unequal time/segment grids')
        charge=np.zeros(len(p));total=0.;energy_quad=0.;heat_quad=0.;input_energy=0.;output_energy=0.;segment_metrics=[]
        mean_surface_integral=0.;rev_integral=0.
        for j,seg in enumerate(case['segments']):
            mask=p['segment']==j;dt=p['time_s'][mask]-seg['start_s'];i=seg['current_A'];duration=seg['end_s']-seg['start_s']
            charge[mask]=total+i*dt
            xn0=ini['xn']-total/q['n'];xp0=ini['xp']+total/q['p']
            en=b['electrodes']['n'];ep=b['electrodes']['p']
            an=en['radius_m']**2/(15*en['D_ref_m2_s']*q['n']);ap=ep['radius_m']**2/(15*ep['D_ref_m2_s']*q['p'])
            def v_at(t):
                return independent_voltage(xn0-i*t/q['n']-an*i,xp0+i*t/q['p']+ap*i,i,c)
            def heat_at(t):
                xn=xn0-i*t/q['n']-an*i;xp=xp0+i*t/q['p']+ap*i
                surf=mean_ocv(xn,xp,c)
                beta=np.polynomial.polynomial.polyval(xp,ep['d_V_K'])-np.polynomial.polynomial.polyval(xn,en['d_V_K'])
                return i*(surf-v_at(t))-i*ini['temperature_K']*beta
            energy=quad(lambda t:i*v_at(t),0,duration,epsabs=1e-10,epsrel=1e-12)[0]
            energy_quad+=energy;heat_quad+=quad(heat_at,0,duration,epsabs=1e-10,epsrel=1e-12)[0]
            def gap_at(t):
                xn=xn0-i*t/q['n'];xp=xp0+i*t/q['p']
                return i*(mean_ocv(xn,xp,c)-mean_ocv(xn-an*i,xp+ap*i,c))
            def reversible_at(t):
                xn=xn0-i*t/q['n']-an*i;xp=xp0+i*t/q['p']+ap*i
                beta=np.polynomial.polynomial.polyval(xp,ep['d_V_K'])-np.polynomial.polynomial.polyval(xn,en['d_V_K'])
                return -i*ini['temperature_K']*beta
            mean_surface_integral+=quad(gap_at,0,duration,epsabs=1e-10)[0]
            rev_integral+=quad(reversible_at,0,duration,epsabs=1e-10)[0]
            input_energy+=max(-energy,0);output_energy+=max(energy,0)
            segment_metrics.append(dict(segment=j,start_s=seg['start_s'],end_s=seg['end_s'],current_A=i,
                voltage_start_V=float(p['voltage_V'][mask][0]),voltage_end_V=float(p['voltage_V'][mask][-1]),
                soc_start=float(p['soc'][mask][0]),soc_end=float(p['soc'][mask][-1]),energy_port_J=energy))
            if i<0:check(cid,f'charge voltage monotonic segment {j}',max(0.,float(-np.min(np.diff(p['voltage_V'][mask])))),1e-10)
            if i>0:check(cid,f'discharge voltage monotonic segment {j}',max(0.,float(np.max(np.diff(p['voltage_V'][mask])))),1e-10)
            total+=i*duration
        analytic_soc=.5-charge/(3600*c['capacity_Ah'])
        check(cid,'analytic SOC',np.max(abs(p['soc']-analytic_soc)),tol['analytic_soc'])
        check(cid,'lithium inventory relative',np.max(abs(q['n']*p['xn']+q['p']*p['xp']-inv0))/inv0,tol['inventory_relative'])
        check(cid,'voltage decomposition V',np.max(abs(p['voltage_V']-(p['ocp_surface_V']-p['activation_V']-p['ohmic_V']))),tol['decomposition'])
        check(cid,'heat decomposition W',np.max(abs(p['heat_W']-(p['heat_reaction_W']+p['heat_ohmic_W']+p['heat_reversible_W']))),tol['decomposition'])
        check(cid,'negative irreversible heat W',max(0.,float(-np.min(p['heat_reaction_W']+p['heat_ohmic_W']))),tol['decomposition'])
        check(cid,'charge/discharge polarization sign W',max(0.,float(-np.min(p['current_A']*(p['ocv_mean_V']-p['voltage_V'])))),tol['decomposition'])
        check(cid,'negative operating margin',max(0.,float(-np.min(p['min_margin']))),0)
        check(cid,'port energy independent quadrature J',abs(p['energy_port_J'][-1]-energy_quad),tol['energy_quadrature_J'])
        check(cid,'heat energy independent quadrature J',abs(p['energy_heat_J'][-1]-heat_quad),tol['energy_quadrature_J'])
        check(cid,'Simulink voltage V',np.max(abs(p['voltage_V']-s['voltage_V'])),tol['simulink_voltage_V'])
        for field in ['xn','xp','soc']:
            check(cid,f'Simulink {field}',np.max(abs(p[field]-s[field])),tol['simulink_fraction'])
        for field in ['energy_port_J','energy_heat_J']:
            check(cid,f'Simulink {field}',np.max(abs(p[field]-s[field])),tol['simulink_energy_J'])
        mesh=np.max(abs(f['voltage_V']-coarse['voltage_V']))
        check(cid,'FV 128 to 256 shells V',mesh,tol['fv_mesh_voltage_V'])
        check(cid,'FV mean fractions',max(np.max(abs(f['xn_mean']-(ini['xn']-charge/q['n']))),np.max(abs(f['xp_mean']-(ini['xp']+charge/q['p'])))),tol['fv_mean_fraction'])
        sn,sp=sphere_series(case,c,p['time_s']);series_v=independent_voltage(sn,sp,p['current_A'],c)
        # Extra analytical verification at the same predeclared mesh accuracy.
        check(cid,'FV versus exact sphere series V',np.max(abs(f['voltage_V']-series_v)),tol['fv_mesh_voltage_V'])
        csv(OUT/f'{cid}_analytic.csv',['time_s','segment','soc','xn_surface_series','xp_surface_series','voltage_series_V'],
            np.column_stack([p['time_s'],p['segment'],analytic_soc,sn,sp,series_v]))
        transitions=[]
        for j in range(1,len(case['segments'])):
            left=np.flatnonzero(p['segment']==j-1)[-1];right=left+1
            jump=max(abs(p['xn'][right]-p['xn'][left]),abs(p['xp'][right]-p['xp'][left]))
            check(cid,f'mean state continuity event {j}',jump,1e-12)
            transitions.append(dict(time_s=float(p['time_s'][right]),current_before_A=float(p['current_A'][left]),
                current_after_A=float(p['current_A'][right]),project_left_V=float(p['voltage_V'][left]),
                project_right_V=float(p['voltage_V'][right]),diffusion_left_V=float(series_v[left]),diffusion_right_V=float(series_v[right])))
        record=dict(id=cid,title=case['title'],segments=segment_metrics,transitions=transitions,
            soc_initial=float(p['soc'][0]),soc_final=float(p['soc'][-1]),
            voltage_min_V=float(np.min(p['voltage_V'])),voltage_max_V=float(np.max(p['voltage_V'])),
            heat_min_W=float(np.min(p['heat_W'])),heat_max_W=float(np.max(p['heat_W'])),
            charge_in_Ah=sum(max(-s['current_A'],0)*(s['end_s']-s['start_s'])/3600 for s in case['segments']),
            charge_out_Ah=sum(max(s['current_A'],0)*(s['end_s']-s['start_s'])/3600 for s in case['segments']),
            energy_input_Wh=input_energy/3600,energy_output_Wh=output_energy/3600,heat_integral_J=float(p['energy_heat_J'][-1]),
            max_project_diffusion_mV=float(1000*np.max(abs(p['voltage_V']-series_v))),mesh_change_mV=float(mesh*1000),
            python_accepted_steps=sum(x['accepted_steps'] for x in pmeta['cases'][len(cases)]['segments']),
            python_derivative_evaluations=sum(x['derivative_evaluations'] for x in pmeta['cases'][len(cases)]['segments']),
            simulink_derivative_evaluations=sum(x['derivative_evaluations'] for x in smeta['cases'][len(cases)]['segments']),
            output_rows=len(p),max_simulink_voltage_error_V=float(np.max(abs(p['voltage_V']-s['voltage_V']))))
        if cid=='BAT-T03':
            record['cycle_energy_audit']=dict(
                input_J=input_energy, output_J=output_energy, net_electrical_input_J=input_energy-output_energy,
                heat_reported_J=heat_quad, unclosed_energy_J=input_energy-output_energy-heat_quad,
                integral_mean_to_surface_voltage_loss_J=mean_surface_integral,
                reversible_heat_integral_J=rev_integral,
                expected='For a closed isothermal cycle of the declared physical states, net electrical input equals total heat.',
                status='not_closed',
                qualification='Post-run physical diagnostic, not part of the predeclared numerical checks. No fabricated acceptance threshold.')
        if cid=='BAT-T04':
            ix=np.flatnonzero(p['segment']==2)[0]
            record['rest_recovery']=dict(start_s=360,end_s=1560,project_mV=float(1000*(p['voltage_V'][-1]-p['voltage_V'][ix])),
                diffusion_mV=float(1000*(series_v[-1]-series_v[ix])),diffusion_start_V=float(series_v[ix]),
                diffusion_end_V=float(series_v[-1]),project_start_V=float(p['voltage_V'][ix]))
        record['checks_passed']=all(x['passed'] for x in checks if x['case']==cid)
        cases.append(record)
    result=dict(contract=c,checks=checks,cases=cases,checks_count=len(checks),checks_passed=sum(x['passed'] for x in checks),
        interpretation='Numerical implementation checks are separate from physical transient adequacy; model has no diffusion memory.',
        analytical_reference='Spherical constant-flux diffusion eigenfunction series, 200 nonzero roots tan(lambda)=lambda; t=0 exact limit.')
    save(OUT/'summary.json',result)
    print(json.dumps(dict(checks=len(checks),passed=result['checks_passed'],failures=[x for x in checks if not x['passed']],cases=cases),ensure_ascii=True,indent=2))


if __name__=='__main__':main()
