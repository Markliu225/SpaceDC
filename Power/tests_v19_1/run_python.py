"""External SciPy integration and power root solve for the current Power equations."""
from pathlib import Path
import sys,json,time
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from battery import Parameters,State,response,EKF
FIELDS=['time_s','current_A','soc','polarization_V','voltage_V','ocv_V','r0_ohm','r1_ohm','tau_s','c1_F',
        'dsoc_dt','du1_dt','pack_voltage_V','pack_current_A','power_W','ohmic_heat_W','polarization_heat_W','heat_W',
        'polarization_energy_J','available_solar_W','actual_solar_W','request_W','load_W','distribution_heat_W',
        'power_residual_W','connected','measured_voltage_V','noise_V','heat_energy_J','port_loss_energy_J','cumulative_Ah']
EKFIELDS=['time_s','prior_voltage_V','estimated_soc','estimated_u1_V','innovation_V','P00','P01','P10','P11','prior_soc','prior_u1_V']
def allocation(p,y,d,c,connected=True):
    a=p.lookup(y[0],d[2]);e=a['ocv']-y[1];n=c['n_series']*c['n_parallel']
    lo=max(c['charge_limit_A'],(e-c['v_max_V'])/a['r0']);hi=min(c['discharge_limit_A'],(e-c['v_min_V'])/a['r0'],e/(2*a['r0']))
    if y[0]<=p.soc_grid[0]:hi=min(hi,0.)
    if y[0]>=p.soc_grid[-1]:lo=max(lo,0.)
    pp=lambda i:n*i*(e-a['r0']*i)
    avail=max(0,d[4])*d[3]*c['area_m2']*c['solar_efficiency'];need=d[5]/c['distribution_efficiency'] if connected else 0.
    shortfall=connected and (lo>hi or pp(hi)<need-avail-1e-8)
    if shortfall:connected=False;need=0.
    desired=need-avail
    if desired<pp(lo):i=lo;actual=need-pp(i)
    else:
        i=brentq(lambda i:pp(i)-desired,lo,hi,xtol=1e-13) if abs(desired)>1e-13 else 0.
        actual=avail
    load=need*c['distribution_efficiency'];qd=need-load
    return i,actual,load,qd,float(connected)
def row(p,y,d,c,connected):
    avail=max(0,d[4])*d[3]*c['area_m2']*c['solar_efficiency']
    if c['kind']=='allocation':i,actual,load,qd,on=allocation(p,y,d,c,connected)
    else:i=d[1];actual=0.;load=0.;qd=0.;on=1.
    r=response(p,State(*y[:2]),float(i),d[2],c['n_series'],c['n_parallel'])
    measured=d[7] if c['project']=='BT07' else r['voltage_V']+d[6]
    residual=actual+r['power_W']-load-qd if c['kind']=='allocation' else 0.
    return [d[0],i,*y[:2],r['voltage_V'],r['ocv'],r['r0'],r['r1'],r['tau'],r['c1'],r['dsoc_dt'],r['du1_dt'],
            r['pack_voltage_V'],r['pack_current_A'],r['power_W'],r['ohmic_heat_W'],r['polarization_heat_W'],r['heat_W'],r['polarization_energy_J'],
            avail,actual,d[5],load,qd,residual,on,measured,d[6],*y[2:]]
def simulate(c,d):
    p=Parameters.from_dict(c['asset']);n=len(d);ys=np.empty((n,5));y=np.r_[c['initial'],0.,0.,0.];ys[0]=y
    # Split every change of physical forcing. Observation noise never advances the plant.
    cols=[1,2,3,4,5];starts=np.r_[0,np.flatnonzero(np.any(np.diff(d[:,cols],axis=0)!=0,axis=1))+1]
    starts=np.unique(np.r_[starts,n-1]);connected=True;on=np.ones(n)
    for k in range(len(starts)-1):
        a,b=starts[k:k+2];inp=d[a].copy()
        if c['kind']=='allocation':connected=bool(allocation(p,y,inp,c,connected)[4])
        on[a:b]=connected
        def rhs(t,y):
            i=allocation(p,y,inp,c,connected)[0] if c['kind']=='allocation' else inp[1]
            r=response(p,State(*y[:2]),float(i),inp[2],c['n_series'],c['n_parallel'])
            return [0 if c['freeze'] else r['dsoc_dt'],0 if c['freeze'] else r['du1_dt'],
                    r['heat_W'],c['n_series']*c['n_parallel']*i*(r['ocv']-r['voltage_V']),abs(i)/3600]
        sol=solve_ivp(rhs,(d[a,0],d[b,0]),y,method='DOP853',t_eval=d[a:b+1,0],max_step=c['max_step_s'],rtol=1e-10,atol=1e-12)
        if not sol.success:raise RuntimeError(sol.message)
        ys[a:b+1]=sol.y.T;y=sol.y[:,-1]
    on[-1]=connected
    out=np.array([row(p,y,x,c,bool(o))for y,x,o in zip(ys,d,on)])
    # Left-side records computed with the same accepted boundary state.
    events=[]
    for k in starts[1:]:
        if np.any(d[k,cols]!=d[k-1,cols]):
            left=d[k-1].copy();left[0]=d[k,0]
            events.extend([[*row(p,ys[k],left,c,bool(on[k-1])),-1],[*out[k],1]])
    return out,np.array(events)
def main():
    ids=json.loads((HERE/'fixtures/index.json').read_text());meta=[]
    for cid in ids:
        tick=time.perf_counter();c=json.loads((HERE/f'fixtures/{cid}.json').read_text());d=np.genfromtxt(HERE/f'fixtures/{cid}.csv',delimiter=',',skip_header=1)
        out,events=simulate(c,d)
        np.savetxt(HERE/f'results/{cid}_python.csv',out,delimiter=',',header=','.join(FIELDS),comments='',fmt='%.17g')
        if len(events):np.savetxt(HERE/f'results/{cid}_python_edges.csv',events,delimiter=',',header=','.join(FIELDS+['side']),comments='',fmt='%.17g')
        if c['kind']=='ekf':
            o=EKF(Parameters.from_dict(c['asset']));est=[]
            for r,x in zip(out,d):est.append([r[0],*o.step(r[1],r[26],x[2])])
            np.savetxt(HERE/'results/EK01_estimator_python.csv',est,delimiter=',',header=','.join(EKFIELDS),comments='',fmt='%.17g')
        meta.append(dict(id=cid,rows=len(out),seconds=time.perf_counter()-tick));print(cid,len(out),'rows',flush=True)
    (HERE/'results/python_execution.json').write_text(json.dumps(meta,indent=2))
if __name__=='__main__':main()
