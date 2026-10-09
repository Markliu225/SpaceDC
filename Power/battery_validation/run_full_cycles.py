"""Three full 0.1C cycles, <=1 s integration steps, capacity from integrated current."""
import hashlib
import json
import sys
import time
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from run_battery import ps, state, save, csv

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1];OUT=HERE/'results'/'full_cycles'
FIELDS=['time_s','segment','cycle','current_A','capacity_Ah','soc','xn','xp','voltage_V',
        'power_W','heat_W','energy_port_J','energy_heat_J','mean_ocv_V','surface_ocp_V','activation_V','ohmic_V']


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    a,scene=ps.example_power_records();a['battery']['N_s']=a['battery']['N_p']=1
    base=ps.example_power_parameters().battery
    xn=base.x_n_100;xp=scene['initial_state']['x_p']+base.Q_n_C/base.Q_p_C*(scene['initial_state']['x_n']-xn)
    scene['initial_state'].update(x_n=xn,x_p=xp,T_B_K=298.15)
    p=ps.load_power_parameters(a,scene);b=p.battery;cap=b.Q_n_C*(b.x_n_100-b.x_n_0)/3600;current=.1*cap
    contract=dict(date='2026-10-08',parameters=a,scene=scene,temperature_K=298.15,capacity_Ah=cap,
        current_magnitude_A=current,c_rate=.1,initial_soc=1.,initial_xn=xn,initial_xp=xp,cycles=3,
        numerics=dict(max_step_s=1.,output_interval_s=1.,rtol=1e-9,atol=1e-11),
        protocol='Start fully charged; discharge to SOC=0, then charge to SOC=1; repeat 3 times. Stop early if voltage hits 3 or 4.2 V.',
        axis='Integrated branch charge magnitude Ah; reset only plotted branch-capacity origin; all physical states remain continuous.',
        accuracy=dict(soc_error=1e-8,simulink_voltage_V=1e-6,simulink_energy_J=1e-4,inventory_relative=1e-9),
        material_mass_known=False,aging_model=False,hysteresis_state=False)
    save(OUT/'contract.json',contract)
    z=np.array([xn,xp,0.,0.]);start=0.;segments=[];step_records=[]
    for j in range(6):
        i=current if j%2==0 else -current;cycle=j//2+1;target=0. if i>0 else 1.
        calls=0
        def response(t,z):return ps.battery_response(i,state(t,z[0],z[1]),298.15,p)
        def rhs(t,z):
            nonlocal calls
            calls+=1;r=response(t,z)
            return [r.dx_n_dt,r.dx_p_dt,r.P_B_W,r.Q_B_W]
        def reached_soc(t,z):return b.soc(z[0])-target
        reached_soc.terminal=True;reached_soc.direction=-1 if i>0 else 1
        def reached_voltage(t,z):return response(t,z).v_cell_V-(3. if i>0 else 4.2)
        reached_voltage.terminal=True;reached_voltage.direction=-1 if i>0 else 1
        print('START',j,'discharge' if i>0 else 'charge',flush=True);tic=time.perf_counter()
        sol=solve_ivp(rhs,(start,start+36001),z,method='RK45',rtol=1e-9,atol=1e-11,max_step=1.,dense_output=True,
                      events=[reached_soc,reached_voltage])
        if not sol.success:raise RuntimeError(sol.message)
        end=float(sol.t[-1]);reason='soc_limit' if len(sol.t_events[0]) else 'voltage_limit' if len(sol.t_events[1]) else 'timeout'
        if reason=='timeout':raise RuntimeError('No stopping event')
        # Include exact event time while avoiding a duplicate due only to rounding.
        ts=start+np.arange(0,math_floor(end-start)+1,dtype=float)
        if end-ts[-1]>1e-7:ts=np.r_[ts,end]
        else:ts[-1]=end
        states=sol.sol(ts).T;rows=[];minmargin=1e10
        e=a['battery']['electrodes']
        for t,x in zip(ts,states):
            r=response(t,x);ocv=np.polynomial.polynomial.polyval(x[1],e['p']['b_V'])-np.polynomial.polynomial.polyval(x[0],e['n']['b_V'])
            rows.append([t,j,cycle,i,abs(i)*(t-start)/3600,b.soc(x[0]),x[0],x[1],r.v_cell_V,r.P_B_W,r.Q_B_W,
                         x[2],x[3],ocv,r.U_p_V-r.U_n_V,r.dv_n_V+r.dv_p_V,i*b.R_ohm_ohm])
            minmargin=min(minmargin,min(r.constraint_margins.values()))
        csv(OUT/f'segment_{j+1}_python.csv',FIELDS,rows)
        csv(OUT/f'segment_{j+1}_accepted_steps.csv',['time_s'],sol.t[:,None])
        expected_soc=b.soc(z[0])-i*(ts-start)/(3600*cap)
        inventory=b.Q_n_C*states[:,0]+b.Q_p_C*states[:,1];inventory0=b.Q_n_C*xn+b.Q_p_C*xp
        record=dict(segment=j,cycle=cycle,mode='discharge' if i>0 else 'charge',current_A=i,start_s=start,end_s=end,
            initial_state=z.tolist(),final_state=states[-1].tolist(),accepted_steps=len(sol.t)-1,derivative_evaluations=calls,
            max_accepted_step_s=float(max(np.diff(sol.t))),output_rows=len(ts),stop_reason=reason,
            capacity_Ah=abs(i)*(end-start)/3600,voltage_start_V=rows[0][8],voltage_end_V=rows[-1][8],
            energy_port_J=states[-1,2]-z[2],energy_heat_J=states[-1,3]-z[3],
            analytic_soc_error=float(max(abs(np.asarray(rows)[:,5]-expected_soc))),
            inventory_relative_error=float(max(abs(inventory-inventory0))/inventory0),
            min_constraint_margin=minmargin,seconds=time.perf_counter()-tic)
        segments.append(record);z=states[-1];start=end
        print('DONE',j,reason,'Q',record['capacity_Ah'],'V',record['voltage_start_V'],record['voltage_end_V'],'wall',record['seconds'],flush=True)
    summary=dict(contract=contract,segments=segments,python=sys.version,
        source_sha256=hashlib.sha256((ROOT/'Thermal/sdtwin_sim/power_stand_in.py').read_bytes()).hexdigest())
    save(OUT/'python_execution.json',summary)


def math_floor(x):return int(np.floor(x+1e-8))


if __name__=='__main__':main()
