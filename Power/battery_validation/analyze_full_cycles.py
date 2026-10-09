import json
from pathlib import Path
import numpy as np
from scipy.integrate import quad
from run_battery import ps, state, save

HERE=Path(__file__).resolve().parent;OUT=HERE/'results'/'full_cycles'


def main():
    meta=json.loads((OUT/'python_execution.json').read_text(encoding='utf-8'));c=meta['contract'];tol=c['accuracy']
    p=ps.load_power_parameters(c['parameters'],c['scene']);b=p.battery;checks=[];segments=[];series=[]
    def check(name,val,limit):checks.append(dict(name=name,value=float(val),limit=float(limit),passed=bool(val<=limit)))
    for j,r in enumerate(meta['segments']):
        a=np.genfromtxt(OUT/f'segment_{j+1}_python.csv',delimiter=',',names=True)
        s=np.genfromtxt(OUT/f'segment_{j+1}_simulink.csv',delimiter=',',names=True)
        if len(a)!=len(s):raise RuntimeError('unequal export grids')
        check(f'{j+1} relative branch-time mismatch s',max(abs((a['time_s']-a['time_s'][0])-(s['time_s']-s['time_s'][0]))),1e-5)
        check(f'{j+1} analytic SOC',r['analytic_soc_error'],tol['soc_error'])
        check(f'{j+1} inventory',r['inventory_relative_error'],tol['inventory_relative'])
        check(f'{j+1} Simulink voltage',max(abs(a['voltage_V']-s['voltage_V'])),tol['simulink_voltage_V'])
        check(f'{j+1} Simulink energy',max(abs(a['energy_port_J']-s['energy_port_J'])),tol['simulink_energy_J'])
        check(f'{j+1} maximum step',r['max_accepted_step_s'],1.+1e-10)
        check(f'{j+1} capacity error Ah',abs(r['capacity_Ah']-c['capacity_Ah']),1e-8)
        i=r['current_A'];x0=r['initial_state'];duration=r['end_s']-r['start_s']
        def response(t):return ps.battery_response(i,state(t,x0[0]-i*t/b.Q_n_C,x0[1]+i*t/b.Q_p_C),298.15,p)
        # Independent adaptive quadrature along analytically known mean-concentration trajectory.
        ei=quad(lambda t:response(t).P_B_W,0,duration,epsabs=1e-7,epsrel=1e-11)[0]
        hi=quad(lambda t:response(t).Q_B_W,0,duration,epsabs=1e-8,epsrel=1e-11)[0]
        check(f'{j+1} port energy quadrature J',abs(ei-r['energy_port_J']),1e-5)
        check(f'{j+1} heat quadrature J',abs(hi-r['energy_heat_J']),1e-5)
        rr=dict(r,simulink_max_voltage_error_V=float(max(abs(a['voltage_V']-s['voltage_V']))))
        segments.append(rr);series.append(a)
    cycles=[]
    for k in range(3):
        dis=segments[2*k];ch=segments[2*k+1];eout=dis['energy_port_J'];ein=-ch['energy_port_J'];heat=dis['energy_heat_J']+ch['energy_heat_J']
        cycles.append(dict(cycle=k+1,discharge_capacity_Ah=dis['capacity_Ah'],charge_capacity_Ah=ch['capacity_Ah'],
            output_Wh=eout/3600,input_Wh=ein/3600,energy_efficiency=eout/ein,net_input_J=ein-eout,
            heat_J=heat,unclosed_energy_J=ein-eout-heat,
            max_discharge_difference_from_first_V=float(max(abs(series[2*k]['voltage_V']-series[0]['voltage_V']))),
            max_charge_difference_from_first_V=float(max(abs(series[2*k+1]['voltage_V']-series[1]['voltage_V'])))))
    xn=b.x_n_0+.5*(b.x_n_100-b.x_n_0);xp=c['initial_xp']+b.Q_n_C/b.Q_p_C*(b.x_n_100-xn)
    rr=[ps.battery_response(i,state(0,xn,xp),298.15,p) for i in [-c['current_magnitude_A'],c['current_magnitude_A']]]
    midpoint=dict(soc=.5,charge_voltage_V=rr[0].v_cell_V,discharge_voltage_V=rr[1].v_cell_V,
                  gap_mV=1000*(rr[0].v_cell_V-rr[1].v_cell_V),
                  ohmic_gap_mV=1000*2*c['current_magnitude_A']*b.R_ohm_ohm,
                  reaction_gap_mV=1000*((rr[1].dv_n_V+rr[1].dv_p_V)-(rr[0].dv_n_V+rr[0].dv_p_V)),
                  surface_ocp_gap_mV=1000*((rr[0].U_p_V-rr[0].U_n_V)-(rr[1].U_p_V-rr[1].U_n_V)))
    summary=dict(contract=c,segments=segments,cycles=cycles,midpoint=midpoint,checks=checks,
        numerical_checks_passed=sum(x['passed'] for x in checks),numerical_checks_total=len(checks),
        assessment='Complete capacity/time integration verified. Repeated loops have no cycle-evolution physics. Closed-state energy balance is not closed. No experimental accuracy claim.')
    save(OUT/'summary.json',summary)
    print(json.dumps(dict(checks=[summary['numerical_checks_passed'],len(checks)],cycles=cycles,midpoint=midpoint),indent=2))


if __name__=='__main__':main()
