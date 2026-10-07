"""Execute the actual repository Power implementation, with SciPy state integration."""
import copy, dataclasses as dc, json, sys, time
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from prepare import ROOT,OUT,FIELDS,prepare,save
sys.path.insert(0,str(ROOT/'Thermal'))
from sdtwin_sim import power_stand_in as ps

REASON={'supplied':1,'charge_limited':2,'load_disconnected':3,'supply_shortfall':4,
        'device_boundary':5,'temperature_out_of_range':6,'invalid_input':7,'numerical_failure':8}
def parameters(suite,o):
    a=copy.deepcopy(suite['parameters']);scene=copy.deepcopy(suite['scene'])
    mapping={'Ns':('N_s',),'Np':('N_p',),'imin':('limits','i_min_A'),'imax':('limits','i_max_A'),
             'vmin':('limits','v_min_V'),'vmax':('limits','v_max_V')}
    for k,v in o.items():
        if k=='eta':a['pdu']['eta_D']=v;continue
        loc=a['battery'];path=mapping[k]
        for part in path[:-1]:loc=loc[part]
        loc[path[-1]]=v
    return ps.load_power_parameters(a,scene)

def state(x,t=0,connected=True,latched=False,handled=()):
    return ps.PowerState('power_comparison','Sat01',float(t),float(x[0]),float(x[1]),bool(connected),bool(latched),handled)
def inputs(r,x,t=0):
    # Rotate the panel normal about body y; Sun lies along inertial +z.
    theta=np.arccos(np.clip(r['cosine'],-1,1));q=[0.,np.sin(theta/2),0.,np.cos(theta/2)]
    pos=np.array([6778137.,0.,0.]);sun=pos+np.array([0.,0.,1.5e11])
    if r['bad']=='zero_sun':sun=pos.copy()
    env=ps.PowerEnvironment(r['G'],pos,sun,q,'ITRS' if r['bad']=='frame' else 'GCRS')
    return ps.PowerInputs('mismatch' if r['bad']=='identity' else 'power_comparison','Sat01',
        float(t)+(1 if r['bad']=='time' else 0),env,r['request'],240. if r['bad']=='temperature' else float(x[2]))
def evaluate(r,x,p,t=0,s=None):
    x=np.asarray(x,float);s=s or state(x,t,r['connected'],r['latched'])
    if r['bad']=='mean_boundary':s=dc.replace(s,x_n=p.battery.limits.x_n_range[1]+.01)
    y=np.full(25,np.nan);y[8:18]=[p.battery.soc(x[0]),*x,s.load_connected,s.trip_latched,1,0,1,1]
    u=inputs(r,x,t)
    if r['mode']=='solar':y[0]=ps.solar_power(u.environment,p).P_pv_max_W;return y,None
    if r['mode']=='battery':
        y[0]=ps.solar_power(u.environment,p).P_pv_max_W;b=ps.battery_response(r['current'],s,x[2],p);res=None
    else:
        res=ps.solve_power_allocation(u,s,p)
        if res.solar:y[0]=res.solar.P_pv_max_W
        y[14:18]=[res.valid,res.event_required,res.can_supply_request,REASON[res.reason_code]]
        b=res.battery
        if b is None:return y,res
        y[[1,2,7]]=[res.P_pv_W,res.P_load_W,res.Q_D_W]
    y[[3,4,5,6,18,19,20,21,22,23]]=[b.P_B_W,b.V_B_V,b.I_B_A,b.Q_B_W,b.i_A,b.v_cell_V,
        b.dx_n_dt,b.dx_p_dt,b.q_reversible_cell_W,min(b.constraint_margins.values())]
    return y,res

def transition(r,x,p,t=0,s=None):
    s=s or state(x,t,r['connected'],r['latched']);y,decision=evaluate(r,x,p,t,s);action=0
    cmd=r['command']
    if cmd=='none':y[24]=0;return s,y,action
    kinds=['stop','start'] if cmd=='stop_start' else ['stop' if cmd=='repeat_stop' else 'supply_loss' if cmd=='trial_supply_loss' else cmd]
    events=[ps.PowerEvent(k,f'{t}:{i}:{k}',cmd!='trial_supply_loss',s.run_id,s.instance_id,s.time_s) for i,k in enumerate(kinds)]
    try:
        new=ps.apply_power_event(s,events,decision)
        if cmd=='repeat_stop':new=ps.apply_power_event(new,events,decision)
        if cmd in ['stop','stop_start','repeat_stop']:action=1
        elif cmd=='supply_loss':action=2
        elif cmd=='start' and decision.can_supply_request:action=3
        s=new;y,_=evaluate(r,x,p,t,s)
    except ps.PowerInputError:action=-1
    y[24]=action
    return s,y,action

def dynamic(c,suite,fine=False):
    ini=suite['scene']['initial_state'];x=np.array([ini['x_n'],ini['x_p'],c['T0']],float)
    p=parameters(suite,c['overrides']);connected=True;latched=False;handled=();start=0.;data=[];events=[]
    num=suite['numerics'];rt=num['refinement_rtol' if fine else 'rtol'];at=num['refinement_atol' if fine else 'atol'];mx=num['refinement_max_step_s' if fine else 'max_step_s']
    for seg in c['segments']:
        r=dict(seg,connected=connected,latched=latched,current=0.,mode='allocate',bad='none')
        s,y,action=transition(r,x,p,start,state(x,start,connected,latched,handled))
        if y[14]!=1:raise RuntimeError(f'invalid start {start}: {y[17]}')
        if y[15]:
            if y[17]!=4:raise RuntimeError(f'unexpected device boundary at {start}')
            r['command']='supply_loss';s,y,action=transition(r,x,p,start,s)
        connected=s.load_connected;latched=s.trip_latched;handled=s.handled_command_ids
        r.update(connected=connected,latched=latched)
        if action:events.append(dict(time_s=start,action=action,connected=int(connected),latched=int(latched)))
        def rhs(t,z):
            v,_=evaluate(r,z,p,t)
            if v[14]!=1 or v[15]!=0:raise RuntimeError(f'unexpected dynamic boundary at {t}: {v[17]}')
            dT=(v[6]-(z[2]-c['Tsink'])/c['R'])/c['C'] if c['thermal'] else 0.
            return [v[20],v[21],dT]
        grid=np.unique(np.r_[np.arange(start,seg['end']+1e-8,c['step']),seg['end']])
        sol=solve_ivp(rhs,(start,seg['end']),x,method='DOP853',rtol=rt,atol=at,max_step=mx,t_eval=grid)
        if not sol.success:raise RuntimeError(sol.message)
        for t,z in zip(sol.t,sol.y.T):
            yy,_=evaluate(r,z,p,t);yy[24]=0;data.append([t,*yy])
        x=sol.y[:,-1];start=seg['end']
    return np.array(data),events

def write_csv(path,data):np.savetxt(path,data,delimiter=',',header=','.join(['time_s',*FIELDS,'action']),comments='',fmt='%.17g')
def run(selected=None):
    if not (OUT/'suite.json').exists():prepare()
    suite=json.loads((OUT/'suite.json').read_text(encoding='utf-8'));meta={'cases':[],'solver':'SciPy DOP853','source':str(ROOT/'Thermal/sdtwin_sim/power_stand_in.py')}
    for c in suite['cases']:
        if selected and c['id']!=selected:continue
        print('START',c['id'],flush=True);tic=time.perf_counter()
        try:
            if c['kind']=='static':
                data=[];events=[]
                for i,r in enumerate(c['rows']):
                    p=parameters(suite,r['overrides']);x=[r['xn'],r['xp'],r['T']]
                    if r['command']=='none':y,_=evaluate(r,x,p);y[24]=0
                    else:_,y,_=transition(r,x,p)
                    data.append([i,*y])
                data=np.array(data)
            else:
                data,events=dynamic(c,suite)
                if c['id']=='NU-001':
                    refined,_=dynamic(c,suite,True);write_csv(OUT/f'{c["id"]}_python_fine.csv',refined)
            write_csv(OUT/f'{c["id"]}_python.csv',data);save(OUT/f'{c["id"]}_python_events.json',events)
            item=dict(id=c['id'],status='executed',seconds=time.perf_counter()-tic,samples=len(data));meta['cases'].append(item)
            print('DONE',item,flush=True)
        except Exception as e:
            import traceback;traceback.print_exc();meta['cases'].append(dict(id=c['id'],status='error',message=str(e)))
        save(OUT/'python_execution.json',meta)
if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else None)
