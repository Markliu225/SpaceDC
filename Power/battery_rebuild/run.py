"""Reproduce calibration, causal battery tests and immutable comparison inputs."""
from pathlib import Path
from dataclasses import replace
import json,hashlib,shutil,sys
import numpy as np
from scipy.optimize import least_squares
from scipy.signal import lfilter
from ecm import Parameters,State,advance,response,safe_current,JointObserver

HERE=Path(__file__).resolve().parent
OUT=HERE/'results';INPUT=HERE/'fixtures'
CON=json.loads((HERE/'contract.json').read_text())
FIELDS=['time_s','current_A','measured_voltage_V','reference_soc','open_loop_voltage_V',
        'prior_voltage_V','posterior_voltage_V','estimated_soc','polarization_V',
        'r0_ohm','r1_ohm','tau_s','c1_F','innovation_V','rls_status','boundary_hits']

def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else x.tolist()),encoding='utf8')
def csv(path,a,header):np.savetxt(path,a,delimiter=',',header=','.join(header),comments='',fmt='%.14g')
def params(d):return Parameters(d['capacity_Ah'],d['r0'],d['r1'],d['tau'],tuple(d['soc_grid']),tuple(d['ocv_grid']))
def metrics(e):return dict(rmse_V=float(np.sqrt(np.mean(e**2))),max_V=float(np.max(abs(e))))
def pulse_data():
    raw=np.loadtxt(HERE/'data/BAK_25C.csv',delimiter=',');t,v,sourcei=raw.T;i=-sourcei
    z=CON['initial_raw_soc']-np.r_[0,np.cumsum(np.diff(t)*(i[1:]+i[:-1])/2)]/(3600*CON['capacity_Ah'])
    starts=np.flatnonzero((i[1:]>3)&(i[:-1]<=3))+1;pulses=[]
    for n,s in enumerate(starts):
        end=np.searchsorted(t,t[s]+120.1);tt=t[s:end]-t[s];ii=i[s:end];vv=v[s:end]
        grid=np.arange(1200)*.1;indices=np.minimum(np.searchsorted(tt,grid,side='right')-1,len(ii)-1)
        # Interpolate voltage only inside the same sign regime; hold at an edge.
        reg=np.sign(np.where(abs(ii)<.05,0,ii));vg=np.empty(len(grid))
        for k,(tk,j) in enumerate(zip(grid,indices)):
            if j+1<len(tt) and reg[j]==reg[j+1]:vg[k]=np.interp(tk,tt[j:j+2],vv[j:j+2])
            else:vg[k]=vv[j]
        ig=ii[indices];zg=z[s]-np.r_[0,np.cumsum(ig[:-1])]*.1/(3600*CON['capacity_Ah'])
        # Median of pre-pulse observations resists a single anomalous last rest sample.
        ocv=float(np.median(v[max(0,s-3):s]))
        pulses.append(dict(number=n+1,soc=float(z[s]),ocv=ocv,t=grid,i=ig,v=vg,z=zg,
            raw_start_index=int(s),raw_start_s=float(t[s]),raw_end_s=float(t[end-1]),
            raw_rows=end-s))
    return pulses

def fit(pulses):
    train=[q for q in pulses if q['number'] in CON['training_discharge_pulses_1based']]
    knots=sorted((q['soc'],q['ocv']) for q in train)
    # Include only a small endpoint margin, by explicitly recorded linear extension.
    zg=np.array([x[0] for x in knots]);vg=np.array([x[1] for x in knots])
    slopes=np.diff(vg)/np.diff(zg)
    soc=np.r_[.05,zg,1.];ocv=np.r_[vg[0]+slopes[0]*(.05-zg[0]),vg,vg[-1]+slopes[-1]*(1-zg[-1])]
    fits=[]
    for q in train:
        ii=q['i'][:300];zz=q['z'][:300];vv=q['v'][:300]
        E=np.interp(zz,soc,ocv)
        def pred(x):
            r0,r1,tau=np.exp(x);a=np.exp(-.1/tau)
            u=lfilter([0,r1*(1-a)],[1,-a],ii)
            return E-r0*ii-u
        opt=least_squares(lambda x:pred(x)-vv,np.log([.04,.02,20.]),bounds=(np.log([.001,.001,1.]),np.log([.2,.3,500.])),max_nfev=500)
        r0,r1,tau=np.exp(opt.x)
        fits.append(dict(pulse=q['number'],soc=q['soc'],r0=float(r0),r1=float(r1),tau=float(tau),c1=float(tau/r1),fit=metrics(pred(opt.x)-vv),at_bound=bool(np.any(abs(opt.active_mask)>0))))
    med=np.median([[f['r0'],f['r1'],f['tau']] for f in fits],axis=0)
    d=dict(capacity_Ah=CON['capacity_Ah'],r0=float(med[0]),r1=float(med[1]),tau=float(med[2]),soc_grid=soc.tolist(),ocv_grid=ocv.tolist(),temperature_C=25.,
        fits=fits,initialization='Median of the five load-only positive 1RC fits; RLS may update R0, R1 and tau online.',
        ocv_endpoint_policy='Linear extension from measured knots to SOC 0.05 and 1.0 is unvalidated; empirical tests remain inside measured support.',
        measured_soc_support=[float(zg[0]),float(zg[-1])])
    save(OUT/'parameters.json',d);return params(d)

def run_observer(cid,t,i,v,z,p,z0,adaptive=True):
    o=JointObserver(p,z0,CON['observer'],dt=float(t[1]-t[0]),adaptive=adaptive);s=State(float(z[0]));rows=[]
    for k in range(len(t)):
        if k:s=advance(p,s,float(i[k-1]),float(t[k]-t[k-1]))
        r=o.step(i[k],v[k]);rows.append([t[k],i[k],v[k],z[k],response(p,s,float(i[k]))['voltage_V']]+r)
    a=np.array(rows);csv(OUT/f'{cid}_python.csv',a,FIELDS)
    csv(INPUT/f'{cid}.csv',np.c_[t,i,v,z],['time_s','current_A','measured_voltage_V','reference_soc'])
    cfg=dict(id=cid,initial_soc=z0,initial_open_loop_soc=float(z[0]),adaptive=adaptive,dt_s=float(t[1]-t[0]),parameters=p.__dict__,observer=CON['observer'])
    save(INPUT/f'{cid}.json',cfg)
    m=dict(id=cid,rows=len(t),duration_s=float(t[-1]),open_loop=metrics(a[:,4]-v),prior=metrics(a[:,5]-v),posterior=metrics(a[:,6]-v),
        initial_soc_error=float(z0-z[0]),final_soc_error=float(a[-1,7]-z[-1]),soc_rmse=float(np.sqrt(np.mean((a[:,7]-z)**2))),
        accepted=o.accepted,rejected=o.rejected,frozen=o.frozen,boundary_hits=o.boundary_hits,
        final_parameters=dict(r0=o.r0,r1=o.r1,tau=o.tau,c1=o.tau/o.r1))
    return a,m

def synthetic(p,kind):
    t=np.arange(6001)*.1;i=np.zeros(len(t))
    # Independent deterministic excitation; every plateau is resolved at 0.1 s.
    pattern=[0,1.5,0,-1.0,2.,0,-1.5,0,1.,-.5]
    for k,tt in enumerate(t):i[k]=pattern[int(tt//10)%len(pattern)] if kind!='REST' else 0
    z=np.zeros(len(t));v=np.zeros(len(t));truth=[];s=State(.65)
    for k,tt in enumerate(t):
        factor=1.0 if kind!='DRIFT' or tt<300 else 1.3
        actual=replace(p,r0=p.r0*factor,r1=p.r1*factor,tau=p.tau*factor)
        if k:
            prevfactor=1.0 if kind!='DRIFT' or t[k-1]<300 else 1.3
            previous=replace(p,r0=p.r0*prevfactor,r1=p.r1*prevfactor,tau=p.tau*prevfactor)
            s=advance(previous,s,float(i[k-1]),.1)
        z[k]=s.soc;v[k]=response(actual,s,float(i[k]))['voltage_V'];truth.append([actual.r0,actual.r1,actual.tau])
    if kind in ('NOISE','DRIFT'):v=v+np.random.default_rng(20261008).normal(0,.003,len(v))
    return t,i,v,z,np.array(truth)

def checks(p):
    rows=[]
    # Analytic recovery and energy accounting include RC storage, not only heat.
    s=State(.65);i=1.;dt=.1
    for k in range(1001):
        t=k*dt;exact_u=i*p.r1*(1-np.exp(-min(t,10)/p.tau))*np.exp(-max(0,t-10)/p.tau)
        cur=i if t<10 else 0.;r=response(p,s,cur)
        rows.append([t,s.polarization_V,exact_u,r['voltage_V'],r['heat_W'],r['polarization_energy_J']])
        if k<1000:s=advance(p,s,cur,dt)
    a=np.array(rows);csv(OUT/'ANALYTIC_python.csv',a,['time_s','u1_V','analytic_u1_V','voltage_V','heat_W','stored_energy_J'])
    # Exact per-step integrals of i*u and u^2/R for constant coefficients.
    energy=[];s=State(.65);source=heat=0.
    for k in range(1000):
        i=1. if k<100 else 0.;u=s.polarization_V;aa=np.exp(-dt/p.tau);b=i*p.r1;d=u-b
        loss=i*i*p.r0*dt+i*(b*dt+d*p.tau*(1-aa))
        q=i*i*p.r0*dt+(b*b*dt+2*b*d*p.tau*(1-aa)+d*d*p.tau/2*(1-aa*aa))/p.r1
        source+=loss;heat+=q;s=advance(p,s,i,dt)
        energy.append([k*dt+dt,source,heat,.5*p.c1*s.polarization_V**2,source-heat-.5*p.c1*s.polarization_V**2])
    csv(OUT/'ENERGY_python.csv',energy,['time_s','ocv_minus_terminal_energy_J','heat_J','rc_storage_J','residual_J'])
    upper=State(p.soc_grid[-1]);lower=State(p.soc_grid[0])
    tests={'analytic_rc_max_error_V':float(np.max(abs(a[:,1]-a[:,2]))),
        'energy_max_residual_J':float(np.max(abs(np.array(energy)[:,-1]))),
        'charge_at_upper_soc_A':safe_current(p,upper,-1,.1),
        'discharge_at_lower_soc_A':safe_current(p,lower,1,.1),
        'temperature_rejection':False,'soc_crossing_rejection':False,'pack_scaling_error':0.}
    try:advance(p,s,1,.1,0)
    except ValueError:tests['temperature_rejection']=True
    try:advance(p,upper,-1,.1)
    except ValueError:tests['soc_crossing_rejection']=True
    cell=response(p,State(.6,.01),1);pack=response(p,State(.6,.01),1,10,2)
    tests['pack_scaling_error']=abs(pack['power_W']-20*cell['power_W'])+abs(pack['heat_W']-20*cell['heat_W'])
    tests['pass']=tests['analytic_rc_max_error_V']<1e-9 and tests['energy_max_residual_J']<1e-9 and abs(tests['charge_at_upper_soc_A'])<1e-12 and abs(tests['discharge_at_lower_soc_A'])<1e-12 and tests['temperature_rejection'] and tests['soc_crossing_rejection'] and tests['pack_scaling_error']<1e-12
    return tests

def cycles(p):
    # Characterization across measured SOC support, not extrapolated full capacity.
    low=.12;high=.96;current=.1*p.capacity_Ah;s=State(low);rows=[];t=0.
    for seg in range(6):
        i=-current if seg%2==0 else current;target=high if i<0 else low;q=0.
        while abs(s.soc-target)>1e-10:
            r=response(p,s,i);rows.append([t,seg//2+1,seg%2,q,s.soc,i,r['voltage_V']])
            step=min(1.,abs(s.soc-target)*3600*p.capacity_Ah/current)
            s=advance(p,s,i,step);t+=step;q+=current*step/3600
        r=response(p,s,i);rows.append([t,seg//2+1,seg%2,q,s.soc,i,r['voltage_V']])
    csv(OUT/'CYCLES_python.csv',rows,['time_s','cycle','direction','capacity_Ah','soc','current_A','voltage_V'])
    a=np.array(rows);expected=(high-low)*p.capacity_Ah;errors=[]
    for cy in (1,2,3):
        for direction in (0,1):
            b=a[(a[:,1]==cy)&(a[:,2]==direction)]
            errors.append(abs(b[-1,3]-expected))
    return dict(soc_low=low,soc_high=high,current_A=current,capacity_per_branch_Ah=expected,duration_s=t,max_step_s=1.,rows=len(rows),aging=False,measurement_validation=False,
        capacity_max_error_Ah=float(max(errors)),voltage_min_V=float(a[:,6].min()),voltage_max_V=float(a[:,6].max()),
        pass_=bool(max(errors)<1e-9 and a[:,6].min()>3 and a[:,6].max()<4.2))

def main():
    OUT.mkdir(exist_ok=True);INPUT.mkdir(exist_ok=True)
    shutil.copy2(HERE/'reference/mathworks_download/testDataBAKcells/testDataBAKcells.rights',HERE/'data/LICENSE.txt')
    pulses=pulse_data();p=fit(pulses);records=[]
    save(OUT/'preprocessing.json',[{k:v for k,v in q.items() if k not in ('t','i','v','z')} for q in pulses])
    for kind in ['EXACT','NOISE','DRIFT','REST']:
        t,i,v,z,truth=synthetic(p,kind)
        initial=p if kind=='REST' else replace(p,r0=p.r0*1.2,r1=p.r1*.8,tau=p.tau*1.2)
        z0=float(z[0]) if kind in ('EXACT','REST') else float(z[0]+.1)
        a,m=run_observer(kind,t,i,v,z,initial,z0)
        m['reference']='synthetic known truth';m['parameter_relative_error']={name:float(abs(m['final_parameters'][name]/truth[-1,j]-1)) for j,name in enumerate(['r0','r1','tau'])}
        m['pass']=abs(m['final_soc_error'])<=CON['criteria']['synthetic_final_soc_error'] and max(m['parameter_relative_error'].values())<=CON['criteria']['synthetic_parameter_relative_error'] and m['accepted']>0
        if kind=='REST':m['pass']=m['accepted']==0 and m['rejected']==0 and m['frozen']==len(t)
        csv(OUT/f'{kind}_truth.csv',np.c_[t,truth],['time_s','r0_ohm','r1_ohm','tau_s'])
        records.append(m)
        if kind=='NOISE':
            _,fixed=run_observer('FIXED_EKF',t,i,v,z,initial,z0,False);fixed['reference']='synthetic known truth';fixed['pass']=abs(fixed['final_soc_error'])<=.02;records.append(fixed)
    for q in pulses:
        if q['number'] not in CON['validation_discharge_pulses_1based']+[3]:continue
        cid=f"MEASURED_{q['number']:02d}"
        _,m=run_observer(cid,q['t'],q['i'],q['v'],q['z'],p,q['soc'])
        m.update(reference='measured voltage; SOC is coulomb-count reference, not independent truth',pulse=q['number'],anomaly_case=q['number']==3)
        m['pass']=m['open_loop']['rmse_V']<=.03 and m['open_loop']['max_V']<=.1 and m['prior']['rmse_V']<=.03
        records.append(m)
    summary=dict(contract=CON,checks=checks(p),cycles=cycles(p),cases=records,environment=dict(python=sys.version),
        hashes={str(f.relative_to(HERE.parent)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [HERE/'contract.json',HERE.parent/'battery.py',HERE/'run.py']+list((HERE/'data').glob('*.csv'))},
        sources=['Provided PDF pages 3-7','https://www.mathworks.com/help/simscape-battery/ug/estimate-battery-model-parameters-from-hppc-data.html','https://www.mathworks.com/help/ident/ref/recursiveleastsquaresestimator.html','https://www.mathworks.com/help/simscape-battery/ref/socestimatorkalmanfilter.html'])
    save(OUT/'summary.json',summary)
    print(json.dumps(dict(parameters=p.__dict__,checks=summary['checks'],cases=[{k:m[k] for k in ('id','pass','prior','final_soc_error','accepted','rejected')} for m in records]),indent=2))

if __name__=='__main__':main()
