"""Compare shared-time results; retain every failure and no-data condition."""
import json,hashlib
import numpy as np
from prepare import OUT,FIELDS,ROOT,save

DISCRETE={'connected','latched','valid','event_required','can_supply','reason','action'}
def read(path):return np.genfromtxt(path,delimiter=',',names=True,encoding='utf-8')
def aligned(a,b):
    if len(a)==len(b) and np.max(np.abs(a['time_s']-b['time_s']))<1e-7:return b
    idx=[]
    for i,t in enumerate(a['time_s']):
        hits=np.flatnonzero(abs(b['time_s']-t)<1e-7)
        if not len(hits):raise ValueError(f'No Simulink output at requested time {t}; no interpolation performed')
        occurrence=np.count_nonzero(abs(a['time_s'][:i]-t)<1e-7)
        idx.append(hits[min(occurrence,len(hits)-1)])
    return b[idx]
def tolerance(name,c,t):
    if name in DISCRETE:return 0.
    if name=='T_B_K':return t['temperature_K']
    if name.endswith('_dt'):return t['derivative']
    if name in ['SOC','x_n','x_p','min_margin']:return t['fraction']
    if name.endswith('_V'):return t['voltage_V']
    if name.endswith('_A'):return t['current_A']
    return t['static_power_W'] if c['kind']=='static' else t['power_W']
def main():
    suite=json.loads((OUT/'suite.json').read_text(encoding='utf-8'));frozen=json.loads((OUT/'frozen_contract.json').read_text())
    assert hashlib.sha256((OUT/'suite.json').read_bytes()).hexdigest()==frozen['suite_sha256'],'Frozen input contract changed'
    summary={'scope':'Python Power implementation versus independently implemented Simulink P1-P11 model',
             'suite_sha256':frozen['suite_sha256'],'cases':[],'tolerances':suite['tolerances']}
    for c in suite['cases']:
        cid=c['id'];res={'id':cid,'checks':[],'metrics':[],'name_cn':c['name_cn'],'name_en':c['name_en']}
        def check(name,passed,actual,limit=None):res['checks'].append(dict(name=name,pass_=bool(passed),actual=actual,limit=limit))
        try:
            a=read(OUT/f'{cid}_python.csv');raw=read(OUT/f'{cid}_simulink.csv');b=aligned(a,raw)
            check('common_time_grid',len(a)==len(b) and np.max(abs(a['time_s']-b['time_s']))<1e-7,len(a))
            delta=np.zeros((len(a),len(FIELDS)+2));delta[:,0]=a['time_s']
            if c['kind']=='dynamic':
                required=['P_pv_W','P_load_W','P_B_W','V_B_V','I_B_A','Q_B_W','Q_D_W','SOC','T_B_K']
            elif c['rows'][0]['mode']=='battery':required=['V_B_V','I_B_A','Q_B_W','dx_n_dt','dx_p_dt']
            elif c['rows'][0]['mode']=='solar':required=['P_pv_max_W']
            else:required=[]
            for who,v in [('python',a),('simulink',b)]:
                for n in required:check(who+'_'+n+'_required_finite',np.isfinite(v[n]).all(),int(np.count_nonzero(~np.isfinite(v[n]))),0)
            for k,name in enumerate(FIELDS+['action']):
                av=a[name];bv=b[name];ma=np.isfinite(av);mb=np.isfinite(bv)
                check(name+'_availability',np.array_equal(ma,mb),int(np.count_nonzero(ma!=mb)),0)
                mask=ma&mb;d=av[mask]-bv[mask];lim=tolerance(name,c,suite['tolerances'])
                mx=float(np.max(abs(d))) if len(d) else 0.;rms=float(np.sqrt(np.mean(d*d))) if len(d) else 0.
                if len(d):
                    check(name+'_difference',mx<=lim,mx,lim)
                    res['metrics'].append(dict(signal=name,max_abs=mx,rmse=rms,threshold=lim,samples=len(d)))
                delta[:,k+1]=av-bv
            np.savetxt(OUT/f'{cid}_difference.csv',delta,delimiter=',',header=','.join(['time_s',*FIELDS,'action']),comments='',fmt='%.17g')
            # Save exactly the plotted / compared reference values, preserving raw output separately.
            np.savetxt(OUT/f'{cid}_simulink_aligned.csv',np.column_stack([b[n] for n in b.dtype.names]),delimiter=',',header=','.join(b.dtype.names),comments='',fmt='%.17g')
            comparison_check_count=len(res['checks'])
            for who,v in [('python',a),('simulink',b)]:
                ports=np.isfinite(v['P_pv_W'])&np.isfinite(v['P_load_W'])
                if ports.any():
                    residual=v['P_pv_W'][ports]+v['P_B_W'][ports]-v['P_load_W'][ports]-v['Q_D_W'][ports]
                    rr=float(np.max(abs(residual)));check(who+'_port_conservation',rr<=suite['tolerances']['conservation_W'],rr,suite['tolerances']['conservation_W'])
                    curtail=v['P_pv_max_W'][ports]-v['P_pv_W'][ports]
                    check(who+'_solar_feasibility',np.min(curtail)>-1e-6 and np.min(v['P_pv_W'][ports])>-1e-6,float(np.min(curtail)),0)
                    check(who+'_device_constraints',np.min(v['min_margin'][ports])>=-1e-8,float(np.min(v['min_margin'][ports])),-1e-8)
                if c['kind']=='dynamic':
                    z=suite['parameters']['battery']['electrodes'];q=[]
                    for k in ['n','p']:
                        e=z[k];q.append(96485.33212*e['active_fraction']*e['electrode_area_m2']*e['thickness_m']*e['c_max_mol_m3'])
                    inventory=q[0]*v['x_n']+q[1]*v['x_p'];err=float(np.max(abs(inventory-inventory[0]))/abs(inventory[0]))
                    check(who+'_lithium_conservation',err<=1e-10,err,1e-10)
                    check(who+'_SOC_within_usable_range',np.min(v['SOC'])>=-1e-6 and np.max(v['SOC'])<=1+1e-6,
                          {'min':float(np.min(v['SOC'])),'max':float(np.max(v['SOC']))},'0 to 1, rounding allowance 1e-6')
                    if not c['thermal']:check(who+'_prescribed_temperature',float(np.ptp(v['T_B_K']))<1e-10,float(np.ptp(v['T_B_K'])),1e-10)
            if c['kind']=='dynamic':
                ea=json.loads((OUT/f'{cid}_python_events.json').read_text());eb=json.loads((OUT/f'{cid}_simulink_events.json').read_text())
                if isinstance(eb,dict):eb=[eb]
                check('event_sequence',ea==eb,{'python':ea,'simulink':eb})
                res['events']=ea;res['energy']={}
                for n in ['P_pv_W','P_load_W','P_B_W','Q_B_W','Q_D_W']:
                    e1=float(np.trapezoid(a[n],a['time_s']));e2=float(np.trapezoid(b[n],b['time_s']));rel=abs(e1-e2)/max(1.,abs(e2))
                    res['energy'][n]={'python_J':e1,'simulink_J':e2,'relative_error':rel}
                    check(n+'_energy',rel<=suite['tolerances']['energy_relative'],rel,suite['tolerances']['energy_relative'])
            if cid=='PR-001':
                expect=[1,3,0,3,2,1,1,-1]
                for who,v in [('python',a),('simulink',b)]:check(who+'_command_outcomes',list(v['action'])==expect,list(v['action']))
            if cid=='DY-005':
                expect=[(100.,2),(300.,3),(400.,1),(500.,3)]
                check('expected_trip_restart_times',[(e['time_s'],e['action']) for e in res['events']]==expect,res['events'])
            if cid=='IV-001':
                for who,v in [('python',a),('simulink',b)]:
                    check(who+'_invalid_is_not_shortfall',list(v['valid'])==[0,0,0,0,0,1] and list(v['event_required'])==[0,0,0,0,0,1],list(v['reason']))
            if cid=='CT-003':
                for who,v in [('python',a),('simulink',b)]:
                    check(who+'_no_charging_at_full_SOC',np.min(v['i_A'])>=-1e-8,float(np.min(v['i_A'])),-1e-8)
            if cid=='BT-003':
                for who,v in [('python',a),('simulink',b)]:
                    check(who+'_signed_heat_retained',np.min(v['Q_B_W'])<0 and np.max(v['Q_B_W'])>0,
                          {'min':float(np.min(v['Q_B_W'])),'max':float(np.max(v['Q_B_W']))})
            if cid=='PV-001':
                expected=np.array([r['G']*max(0,r['cosine'])*suite['parameters']['solar']['area_m2']*suite['parameters']['solar']['efficiency'] for r in c['rows']])
                for who,v in [('python',a),('simulink',b)]:
                    err=float(np.max(abs(v['P_pv_max_W']-expected)));check(who+'_analytical_solar',err<=1e-6,err,1e-6)
            if cid=='NU-001':
                res['convergence']=[]
                for who,base in [('python',a),('simulink',b)]:
                    fine=aligned(base,read(OUT/f'{cid}_{who}_fine.csv'))
                    for n in ['SOC','V_B_V','I_B_A','Q_B_W','T_B_K']:
                        err=float(np.max(abs(base[n]-fine[n])));lim=tolerance(n,c,suite['tolerances'])/10
                        check(who+'_'+n+'_convergence',err<=lim,err,lim);res['convergence'].append(dict(solver=who,signal=n,max_abs=err,threshold=lim))
            res['comparison_status']='pass' if all(v['pass_'] for v in res['checks'][:comparison_check_count]) else 'fail'
            res['samples']=len(a);res['status']='pass' if all(v['pass_'] for v in res['checks']) else 'fail'
        except Exception as e:res.update(status='not_completed',error=str(e));check('execution_complete',False,str(e))
        save(OUT/f'{cid}.json',res);summary['cases'].append(res)
        print(cid,res['status'],[(z['name'],z['actual']) for z in res['checks'] if not z['pass_']],flush=True)
    summary['counts']={s:sum(c['status']==s for c in summary['cases']) for s in ['pass','fail','not_completed']}
    summary['execution_complete']=all(c['status']!='not_completed' for c in summary['cases'])
    summary['all_acceptance_criteria_pass']=all(c['status']=='pass' for c in summary['cases'])
    files=[p for p in (ROOT/'Power'/'verification').rglob('*') if p.is_file() and p.suffix in ['.py','.m','.slx','.json','.csv'] and p.name!='summary.json' and '__pycache__' not in str(p)]
    summary['evidence_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    save(OUT/'summary.json',summary)
if __name__=='__main__':main()
