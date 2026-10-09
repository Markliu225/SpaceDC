"""Compare saved time histories and retain every acceptance failure."""
from pathlib import Path
import json,sys,hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from battery import Parameters,State,response
RESULT=HERE/'results';FIG=HERE/'figures'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.grid':True,'grid.alpha':.22,'figure.dpi':130,'savefig.dpi':190})
def read(cid,backend='python'):
    suffix='_aligned' if cid=='BT06' and (RESULT/f'{cid}_{backend}_aligned.csv').exists() else ''
    return np.genfromtxt(RESULT/f'{cid}_{backend}{suffix}.csv',delimiter=',',names=True)

def align_reversal():
    """Match event sides, retain the untouched fixed-grid traces and source clocks."""
    a=np.genfromtxt(RESULT/'BT06_python.csv',delimiter=',',names=True)
    raw=np.genfromtxt(RESULT/'BT06_simulink.csv',delimiter=',',names=True);b=raw.copy()
    native=np.loadtxt(RESULT/'BT06_native_event_samples.csv',delimiter=',');post=np.flatnonzero(native[:,1]>0)[0]
    source=native[[post-1,post]];k=np.argmin(abs(a['time_s']-27360.))
    def common(v):
        t=v[0];x=v[1:]
        return np.r_[t,x[:3],x[9],x[3:8],x[10:12],x[16:19],x[12:14],x[19:21],
                     x[27],x[22],0.,x[23:25],0.,x[25],x[9]+x[28],x[28],x[29:32]]
    sides=np.array([common(v) for v in source]);times=sides[:,0].copy();sides[:,0]=27360.
    for j,f in enumerate(b.dtype.names):b[f][k]=sides[1,j]
    pyedges=np.genfromtxt(RESULT/'BT06_python_edges.csv',delimiter=',',names=True)
    edge=np.column_stack([pyedges[f][:2]for f in b.dtype.names]);edge_errors={f:float(max(abs(edge[:,j]-sides[:,j])))for j,f in enumerate(b.dtype.names)}
    for backend,r in [('python',a),('simulink',b)]:
        np.savetxt(RESULT/f'BT06_{backend}_aligned.csv',np.column_stack([r[f]for f in r.dtype.names]),delimiter=',',header=','.join(r.dtype.names),comments='',fmt='%.17g')
    np.savetxt(RESULT/'BT06_event_sides.csv',np.column_stack([[-1,1],times,sides]),delimiter=',',header='side,source_simulink_time_s,'+','.join(b.dtype.names),comments='',fmt='%.17g')
    raw_errors=maxerr(a,raw,list(a.dtype.names));delta=float(times[1]-27360.)
    audit=dict(nominal_event_s=27360.,source_left_s=float(times[0]),source_right_s=float(times[1]),
               time_error_s=delta,time_tolerance_s=1e-4,raw_grid_max_errors=raw_errors,
               event_side_max_errors=edge_errors,voltage_jump_V=float(sides[1,4]-sides[0,4]),
               state_change_soc=float(sides[1,2]-sides[0,2]),state_change_u1_V=float(sides[1,3]-sides[0,3]),
               replaced_sample_index=int(k),method='Only the nominal reversal sample is matched to the native right-side event. Original CSV and MAT remain unchanged; both native source clocks and both sides are saved. No interpolation across a voltage jump.')
    save(RESULT/'BT06_alignment_audit.json',audit)
    return audit
def save(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=lambda x:x.item() if isinstance(x,np.generic) else x),encoding='utf8')
def metrics(x):return dict(rmse=float(np.sqrt(np.mean(x*x))),max_abs=float(np.max(np.abs(x))))
def figsave(fig,name):
    fig.tight_layout();fig.savefig(FIG/f'{name}.png',bbox_inches='tight');fig.savefig(FIG/f'{name}.pdf',bbox_inches='tight');plt.close(fig)
def maxerr(a,b,cols):return {k:float(np.max(abs(a[k]-b[k]))) for k in cols}
def analytic(c,d):
    p=Parameters.from_dict(c['asset']);z,u=c['initial'];rows=[];r1=c['asset']['r1_table'][0][0];tau=c['asset']['tau_table'][0][0]
    for k,x in enumerate(d):
        if k:
            dt=d[k,0]-d[k-1,0];i=d[k-1,1];a=np.exp(-dt/tau)
            z-=i*dt/(3600*p.capacity_Ah);u=a*u+r1*(1-a)*i
        r=response(p,State(z,u),float(x[1]),x[2],c['n_series'],c['n_parallel'])
        rows.append([x[0],z,u,r['voltage_V']])
    return np.array(rows)
def main():
    audit=align_reversal()
    con=json.loads((HERE/'contract.json').read_text());comparisons={};byproject={p:[]for p in con['projects']}
    tolerance={'soc':1e-7,'polarization_V':1e-6,'voltage_V':1e-5,'current_A':1e-5,'pack_current_A':2e-5,
               'pack_voltage_V':4e-5,'heat_energy_J':1e-4,'port_loss_energy_J':1e-4,'cumulative_Ah':1e-6}
    for cid in con['cases']:
        c=json.loads((HERE/f'fixtures/{cid}.json').read_text());a=read(cid);b=read(cid,'simulink')
        if a.shape!=b.shape or np.max(abs(a['time_s']-b['time_s']))>1e-7:raise ValueError(f'Time alignment failed: {cid}')
        errors={};fail=[]
        diff=np.empty(a.shape,dtype=a.dtype)
        for field in a.dtype.names:
            diff[field]=a[field]-b[field]
            if not np.isfinite(a[field]).all() or not np.isfinite(b[field]).all():fail.append(field+': nonfinite')
            e=float(np.max(abs(diff[field])));errors[field]=e
            if field=='time_s':limit=1e-7
            elif field.endswith('_W'):limit=1e-4
            elif field in ('connected',):limit=0.
            else:limit=tolerance.get(field,1e-10+1e-10*float(np.max(abs(b[field]))))
            if e>limit:fail.append(f'{field}: {e:.7g} > {limit:.7g}')
        np.savetxt(RESULT/f'{cid}_difference.csv',np.column_stack([diff[f]for f in diff.dtype.names]),delimiter=',',header=','.join(diff.dtype.names),comments='',fmt='%.17g')
        comparisons[cid]=dict(pass_=not fail,rows=len(a),max_errors=errors,failures=fail);byproject[c['project']].append(cid)
    results={p:dict(pass_=all(comparisons[cid]['pass_']for cid in cases),runs=cases,checks={}) for p,cases in byproject.items()}
    def check(project,key,value,passed):
        results[project]['checks'][key]=dict(value=value,pass_=bool(passed));results[project]['pass_']&=bool(passed)
    # PV analytical values including area scaling.
    for angle,expected in [(0,500),(60,250),(90,0),(180,0)]:
        x=read(f'PV01_ANGLE_{angle}','simulink')['available_solar_W'][0]
        check('PV01',f'angle_{angle}_W',float(x),abs(x-expected)<=1e-10+1e-10*abs(expected))
    check('PV01','double_area_W',float(read('PV01_AREA','simulink')['available_solar_W'][0]),abs(read('PV01_AREA','simulink')['available_solar_W'][0]-1000)<1e-7)
    pv=read('PV01_TIME','simulink');pvref=np.select([pv['time_s']<10,pv['time_s']<20,pv['time_s']<40],[500,250,0],default=500)
    check('PV01','time_profile_max_error_W',float(max(abs(pv['available_solar_W']-pvref))),np.all(abs(pv['available_solar_W']-pvref)<=1e-8))
    # Independent static hand calculation.
    static=[]
    for ns,np_ in [(1,1),(4,2)]:
        for i in [0,2,-2]:
            cid=f'BT01_{ns}S{np_}P_I{i:+d}';r=read(cid,'simulink')[0];N=ns*np_
            hand=dict(voltage_V=3.8-.05*i-.02,power_W=N*i*(3.8-.05*i-.02),heat_W=N*(.05*i*i+.02),
                      polarization_energy_J=N*.1,dsoc_dt=-i/7200,du1_dt=-.002+.002*i,pack_current_A=np_*i,pack_voltage_V=ns*(3.8-.05*i-.02))
            errs={k:float(abs(r[k]-v))for k,v in hand.items()};ok=all(errs[k]<=1e-10+1e-10*abs(v)for k,v in hand.items())
            check('BT01',cid,errs,ok);static.append(dict(id=cid,expected=hand,actual={k:float(r[k])for k in hand}))
    save(RESULT/'BT01_hand_calculations.json',static)
    for cid in ['BT02','BT03']:
        c=json.loads((HERE/f'fixtures/{cid}.json').read_text());d=np.loadtxt(HERE/f'fixtures/{cid}.csv',delimiter=',',skiprows=1);truth=analytic(c,d)
        np.savetxt(RESULT/f'{cid}_analytic.csv',truth,delimiter=',',header='time_s,soc,polarization_V,voltage_V',comments='',fmt='%.17g')
        b=read(cid,'simulink');err=maxerr(b,dict(soc=truth[:,1],polarization_V=truth[:,2],voltage_V=truth[:,3]),['soc','polarization_V','voltage_V'])
        check(cid,'analytic_max_errors',err,err['soc']<=1e-7 and err['polarization_V']<=1e-6 and err['voltage_V']<=1e-5)
    fine=read('BT02_FINE','simulink');ref=read('BT02_REFINE','simulink');e=maxerr(ref,fine[::2],['soc','polarization_V','voltage_V'])
    check('BT02','refinement_005_vs_0025',e,e['soc']<=2.5e-8 and e['polarization_V']<=2.5e-7 and e['voltage_V']<=2.5e-6)
    # Analytic event limits use accepted continuous states, without interpolating voltage across a jump.
    edges=[]
    for cid,times in [('BT02',[10.,30.]),('BT03',[10.,30.,50.])]:
        c=json.loads((HERE/f'fixtures/{cid}.json').read_text());p=Parameters.from_dict(c['asset']);r=read(cid,'simulink')
        for t in times:
            k=int(np.argmin(abs(r['time_s']-t)));s=State(r['soc'][k],r['polarization_V'][k]);ip=float(r['current_A'][k-1]);ir=float(r['current_A'][k])
            left=response(p,s,ip);right=response(p,s,ir);delta=right['voltage_V']-left['voltage_V'];expected=-.05*(ir-ip)
            edges.append(dict(case=cid,time_s=t,current_left_A=ip,current_right_A=ir,voltage_left_V=left['voltage_V'],voltage_right_V=right['voltage_V'],jump_V=delta,expected_jump_V=expected))
            check(cid,f'voltage_jump_{t:g}s',delta,abs(delta-expected)<1e-10)
    save(RESULT/'pulse_edge_limits.json',edges)
    # Explicit bilinear table oracle.
    tab=np.genfromtxt(RESULT/'BT04_lookup_matlab.csv',delimiter=',',names=True);z=tab['soc'];T=tab['temperature_C']
    expected={'ocv_V':3.2+z-.001*(T-25)+.002*z*(T-25),'r0_ohm':.05+.01*(.5-z)-.0002*(T-25),
              'r1_ohm':.02+.004*(.5-z)-.00005*(T-25),'tau_s':10+2*(.5-z)-.02*(T-25)}
    expected['c1_F']=expected['tau_s']/expected['r1_ohm'];lookup_error=maxerr(tab,expected,list(expected))
    check('BT04','bilinear_max_errors',lookup_error,all(lookup_error[k]<=1e-10+1e-10*max(abs(expected[k]))for k in expected))
    p=Parameters.from_dict(json.loads((HERE/'fixtures/asset_B.json').read_text()));rejected=0
    for z,T in [(.1-1e-8,298.15),(.9+1e-8,298.15),(.6,273.15-1e-8),(.6,323.15+1e-8)]:
        try:p.lookup(z,T)
        except ValueError:rejected+=1
    check('BT04','out_of_domain_rejections',rejected,rejected==4)
    for backend in ['python','simulink']:
        b=read('BT05',backend);residual=b['port_loss_energy_J']-b['heat_energy_J']-(b['polarization_energy_J']-b['polarization_energy_J'][0])
        limit=1e-5+1e-6*np.max(abs(b['port_loss_energy_J']))
        check('BT05',backend+'_energy_residual_J',float(np.max(abs(residual))),np.max(abs(residual))<=limit)
        check('BT05',backend+'_nonnegative_heat',float(np.min(b['heat_W'])),np.min(b['heat_W'])>=0)
    b=read('BT06','simulink');k=np.argmin(abs(b['time_s']-27360));charge=float(b['cumulative_Ah'][k]);discharge=float(b['cumulative_Ah'][-1]-b['cumulative_Ah'][k])
    check('BT06','charge_Ah',charge,abs(charge-1.52)<=1e-6);check('BT06','discharge_Ah',discharge,abs(discharge-1.52)<=1e-6)
    check('BT06','soc_at_reversal',float(b['soc'][k]),abs(b['soc'][k]-.88)<=1e-8)
    check('BT06','final_soc',float(b['soc'][-1]),abs(b['soc'][-1]-.12)<=1e-8)
    check('BT06','event_time_error_s',audit['time_error_s'],abs(audit['time_error_s'])<=1e-4)
    ee=audit['event_side_max_errors']
    check('BT06','matched_event_sides',ee,ee['soc']<=1e-7 and ee['polarization_V']<=1e-6 and ee['voltage_V']<=1e-5 and ee['current_A']<=1e-5)
    measured={}
    for cid in byproject['BT07']:
        r=read(cid,'simulink');err=r['voltage_V']-r['measured_voltage_V'];m=metrics(err);segments={}
        for label,lo,hi in [('discharge',0,30),('rest_after_discharge',30,70),('charge',70,80),('rest_after_charge',80,120)]:
            mask=(r['time_s']>=lo)&(r['time_s']<hi);segments[label]=metrics(err[mask])
        measured[cid]=dict(**m,segments=segments)
        check('BT07',cid,measured[cid],m['rmse']<=.03 and m['max_abs']<=.1)
    e=read('EK01_estimator','simulink');ep=read('EK01_estimator','python');truth=read('EK01','simulink');se=e['estimated_soc']-truth['soc'];last=e['time_s']>=270
    em=metrics(se[last]);final=float(abs(se[-1]));outside=np.flatnonzero(abs(se)>.02);settle=float(e['time_s'][outside[-1]+1]) if len(outside) and outside[-1]<len(se)-1 else (0. if not len(outside) else None)
    ev=metrics(e['prior_voltage_V']-truth['measured_voltage_V']);cov=np.stack([e['P00'],e['P01'],e['P10'],e['P11']],axis=-1).reshape(-1,2,2)
    eig=float(np.min(np.linalg.eigvalsh(cov)));ekcross=maxerr(e,ep,['estimated_soc','estimated_u1_V','prior_voltage_V'])
    check('EK01','soc_accuracy',dict(last_30s_rmse=em['rmse'],final_abs=final,settling_s=settle,prior_voltage=ev),em['rmse']<=.02 and final<=.02)
    check('EK01','covariance',dict(min_eigenvalue=eig,max_asymmetry=float(np.max(abs(e['P01']-e['P10'])))),eig>=-1e-12 and np.max(abs(e['P01']-e['P10']))<=1e-12)
    check('EK01','independent_estimator',ekcross,ekcross['estimated_soc']<=1e-7 and ekcross['estimated_u1_V']<=1e-6 and ekcross['prior_voltage_V']<=1e-5)
    np.savetxt(RESULT/'EK01_estimator_difference.csv',np.column_stack([e[k]-ep[k]for k in e.dtype.names]),delimiter=',',header=','.join(e.dtype.names),comments='',fmt='%.17g')
    a=read('PA01','simulink');scale=np.maximum.reduce([abs(a[k])for k in ['actual_solar_W','power_W','load_W','distribution_heat_W']]);res=abs(a['power_residual_W'])
    check('PA01','max_balance_residual_W',float(max(res)),np.all(res<=1e-6+1e-9*scale))
    stage=[]
    for lo,hi,expect in [(0,20,'balance'),(20,40,'discharge'),(40,60,'charge'),(60,80,'curtailed'),(80,101,'disconnected')]:
        m=(a['time_s']>=lo)&(a['time_s']<hi);ii=a['current_A'][m]
        if expect=='balance':ok=max(abs(ii))<1e-8
        elif expect=='discharge':ok=np.all(ii>0)
        elif expect=='charge':ok=np.all(ii<0)
        elif expect=='curtailed':ok=np.all(a['actual_solar_W'][m]<a['available_solar_W'][m]) and np.all(abs(ii+3)<1e-8)
        else:ok=np.all(a['load_W'][m]==0) and np.all(a['connected'][m]==0)
        stage.append(dict(start_s=lo,mode=expect,current_min_A=float(min(ii)),current_max_A=float(max(ii)),pass_=bool(ok)))
    check('PA01','five_operating_stages',stage,all(s['pass_']for s in stage))
    check('PA01','operating_bounds',dict(min_i_A=float(min(a['current_A'])),max_i_A=float(max(a['current_A'])),min_v_V=float(min(a['voltage_V'])),max_v_V=float(max(a['voltage_V']))),np.all((a['current_A']>=-3-1e-8)&(a['current_A']<=5+1e-8)&(a['voltage_V']>=2.8)&(a['voltage_V']<=4.3)))
    q=a[np.argmin(abs(a['time_s']-80))];emax=q['ocv_V']-q['polarization_V'];imax=min(5.,(emax-2.8)/.05,emax/.1);capacity=.9*8*imax*(emax-.05*imax)
    check('PA01','maximum_load_before_disconnect_W',float(capacity),capacity<180.)
    summary=dict(projects=results,comparisons=comparisons,passed=sum(x['pass_']for x in results.values()),total=10,
                 all_pass=all(x['pass_']for x in results.values()),compared_samples=sum(x['rows']for x in comparisons.values()),
                 plan_sha256=con['plan_sha256'],scope='10 model projects; artificial temperature table; measured voltage only at 25 C; no full spacecraft thermal integration')
    save(RESULT/'summary.json',summary);make_figures(summary)
    print(json.dumps({k:v for k,v in summary.items()if k not in ('projects','comparisons')},indent=2))
    for p,m in results.items():print(p,'PASS'if m['pass_']else'FAIL')

def make_figures(summary):
    # Same stored arrays provide upper curves and lower residuals.
    for cid in ['BT02','BT03','BT04_T0','BT04_T25','BT04_T50','BT07_P04','BT07_P06','BT07_P08']:
        p=read(cid);s=read(cid,'simulink');measured=cid.startswith('BT07')
        fig,ax=plt.subplots(4,1,figsize=(8.8,9.2),sharex=True)
        ax[0].step(s['time_s'],s['current_A'],where='post',color='black');ax[0].set_ylabel('Current (A)')
        ax[1].plot(p['time_s'],p['voltage_V'],label='Python ECM',color='#236cc4',lw=2)
        ax[1].plot(s['time_s'],s['voltage_V'],'--',label='Simulink ECM',color='#ed7d31',lw=1.4)
        if measured:ax[1].plot(s['time_s'],s['measured_voltage_V'],label='Measured',color='black',alpha=.65,lw=1)
        else:ax[1].plot(s['time_s'],s['ocv_V'],':',label='OCV',color='gray')
        ax[1].legend(ncol=3,fontsize=9);ax[1].set_ylabel('Voltage (V)')
        if measured:
            ax[2].plot(s['time_s'],1000*(s['voltage_V']-s['measured_voltage_V']),color='#7c4895');ax[2].set_ylabel('Simulink - measured\n(mV)')
        else:
            ax[2].plot(s['time_s'],s['soc'],label='SOC');ay=ax[2].twinx();ay.plot(s['time_s'],s['polarization_V'],color='#7c4895',label='u1');ay.set_ylabel('Polarization (V)');ax[2].set_ylabel('SOC')
        ax[3].plot(s['time_s'],p['voltage_V']-s['voltage_V'],color='#345b47');ax[3].set_ylabel('Python - Simulink\n(V)');ax[3].set_xlabel('Time (s)')
        ax[0].set_title(cid+' | complete time integration');figsave(fig,cid)
    r=read('PV01_TIME','simulink');fig,ax=plt.subplots(2,1,figsize=(8.8,5.4))
    ax[0].step(r['time_s'],r['available_solar_W'],where='post',label='Simulink');ax[0].plot(r['time_s'],read('PV01_TIME')['available_solar_W'],'--',label='Python');ax[0].set(xlabel='Time (s)',ylabel='Available power (W)',title='PV01 | eclipse-adjusted irradiance');ax[0].legend()
    angles=[0,60,90,180];ax[1].plot(angles,[read(f'PV01_ANGLE_{a}','simulink')['available_solar_W'][0]for a in angles],'o-',label='Simulink');ax[1].set(xlabel='Incidence angle (degree)',ylabel='Available power (W)');figsave(fig,'PV01')
    table=json.loads((RESULT/'BT01_hand_calculations.json').read_text());fig,ax=plt.subplots(figsize=(10,4.3));ax.axis('off')
    rows=[[x['id'],f"{x['actual']['voltage_V']:.6f}",f"{x['actual']['power_W']:.6f}",f"{x['actual']['heat_W']:.6f}",f"{x['actual']['dsoc_dt']:.8f}",f"{x['actual']['du1_dt']:.6f}"]for x in table]
    tb=ax.table(cellText=rows,colLabels=['Configuration','Cell V','Pack W','Heat W','dSOC/dt','du1/dt'],loc='center',cellLoc='center');tb.auto_set_font_size(False);tb.set_fontsize(9);tb.scale(1,2);ax.set_title('BT01 | independent hand calculations agree with Simulink');figsave(fig,'BT01')
    fig,ax=plt.subplots(2,1,figsize=(8.8,6.2),sharex=True)
    for T in [0,25,50]:
        r=read(f'BT04_T{T}','simulink');ax[0].plot(r['time_s'],r['voltage_V'],label=f'{T} degC');ax[1].plot(r['time_s'],r['polarization_V'],label=f'{T} degC')
    ax[0].set(ylabel='Terminal voltage (V)',title='BT04 | synthetic temperature tables, not measured cell data');ax[0].legend();ax[1].set(xlabel='Time (s)',ylabel='Polarization (V)');figsave(fig,'BT04')
    r=read('BT05','simulink');fig,ax=plt.subplots(3,1,figsize=(8.8,8),sharex=True)
    ax[0].plot(r['time_s'],r['ohmic_heat_W'],label='R0 dissipation');ax[0].plot(r['time_s'],r['polarization_heat_W'],label='R1 dissipation');ax[0].set_ylabel('Heat (W)');ax[0].legend()
    ax[1].plot(r['time_s'],r['port_loss_energy_J'],label='Integral i(OCV-V)');ax[1].plot(r['time_s'],r['heat_energy_J'],label='Heat integral');ax[1].plot(r['time_s'],r['polarization_energy_J'],label='RC storage');ax[1].legend();ax[1].set_ylabel('Energy (J)')
    er=r['port_loss_energy_J']-r['heat_energy_J']-r['polarization_energy_J'];ax[2].plot(r['time_s'],er);ax[2].set(xlabel='Time (s)',ylabel='Balance residual (J)');ax[0].set_title('BT05 | dissipated heat versus stored polarization energy');figsave(fig,'BT05')
    r=read('BT06','simulink');p=read('BT06');k=np.argmin(abs(r['time_s']-27360));fig,ax=plt.subplots(2,1,figsize=(8.8,7))
    edges=np.genfromtxt(RESULT/'BT06_event_sides.csv',delimiter=',',names=True)
    charge_v=r['voltage_V'][:k+1].copy();charge_v[-1]=edges['voltage_V'][0]
    ax[0].plot(r['cumulative_Ah'][:k+1],charge_v,label='Charge 0.1C');ax[0].plot(r['cumulative_Ah'][k:]-r['cumulative_Ah'][k],r['voltage_V'][k:],label='Discharge 0.1C');ax[0].set(xlabel='Charge transferred within branch (Ah)',ylabel='Voltage (V)',title='BT06 | SOC 0.12 to 0.88 and back; no accelerated physical time');ax[0].legend()
    ax[1].plot(r['time_s'],r['soc'],label='Simulink');ax[1].plot(p['time_s'],p['soc'],'--',label='Python');ax[1].set(xlabel='Time (s)',ylabel='SOC');ax[1].legend();figsave(fig,'BT06')
    fig,ax=plt.subplots(3,1,figsize=(8.8,7.5),sharex=True)
    ax[0].step(r['time_s'],r['current_A'],where='post');ax[0].set_ylabel('Current (A)')
    ax[1].plot(p['time_s'],p['voltage_V'],label='Python');ax[1].plot(r['time_s'],r['voltage_V'],'--',label='Simulink, event-side aligned');ax[1].set_ylabel('Voltage (V)');ax[1].legend()
    ax[2].plot(r['time_s'],p['voltage_V']-r['voltage_V']);ax[2].set(xlabel='Time (s)',ylabel='Python - Simulink (V)');ax[0].set_title('BT06 | complete voltage comparison with matched reversal sides');figsave(fig,'BT06_comparison')
    for cid in ['BT02','BT03']:
        r=read(cid,'simulink');fig,ax=plt.subplots(figsize=(8.8,4.2));t=r['time_s'];base=r['ocv_V'][0]
        ax.plot(t,r['ocv_V']-base,label='OCV change');ax.plot(t,-r['current_A']*r['r0_ohm'],label='Ohmic term -iR0');ax.plot(t,-r['polarization_V'],label='Polarization term -u1');ax.plot(t,r['voltage_V']-base,'--',color='black',label='Sum = terminal change')
        ax.set(xlabel='Time (s)',ylabel='Voltage contribution (V)',title=cid+' | V = OCV - iR0 - u1');ax.legend(ncol=2,fontsize=9);figsave(fig,cid+'_voltage_terms')
    r=read('EK01','simulink');e=read('EK01_estimator','simulink');p=read('EK01_estimator');fig,ax=plt.subplots(4,1,figsize=(8.8,9),sharex=True)
    ax[0].step(r['time_s'],r['current_A'],where='post');ax[0].set_ylabel('Current (A)')
    ax[1].plot(r['time_s'],r['soc'],label='True SOC',color='black');ax[1].plot(e['time_s'],e['estimated_soc'],label='EKF Simulink');ax[1].plot(p['time_s'],p['estimated_soc'],'--',label='EKF Python');ax[1].legend();ax[1].set_ylabel('SOC')
    ax[1].scatter([0],[.7],marker='x',color='#9e2d2d',zorder=5);ax[1].annotate('Initial prior SOC = 0.70',xy=(0,.7),xytext=(25,.687),arrowprops=dict(arrowstyle='->'),fontsize=9)
    ax[1].plot([0,0],[.7,e['estimated_soc'][0]],':',color='#9e2d2d')
    ax[2].plot(e['time_s'],100*(e['estimated_soc']-r['soc']));ax[2].set_ylabel('SOC error (pp)')
    ax[3].plot(e['time_s'],1000*(e['prior_voltage_V']-r['measured_voltage_V']));ax[3].set(xlabel='Time (s)',ylabel='Prior - measured (mV)');ax[0].set_title('EK01 | initial estimate +10 pp, measurement noise 3 mV');figsave(fig,'EK01')
    r=read('PA01','simulink');p=read('PA01');fig,ax=plt.subplots(4,1,figsize=(9.5,9),sharex=True)
    for field,label in [('available_solar_W','Available solar'),('actual_solar_W','Actual solar'),('power_W','Battery port')]:ax[0].plot(r['time_s'],r[field],label=label)
    ax[0].legend(ncol=3);ax[0].set_ylabel('Power (W)')
    for field,label in [('request_W','Requested'),('load_W','Delivered'),('distribution_heat_W','Distribution heat')]:ax[1].plot(r['time_s'],r[field],label=label)
    ax[1].legend(ncol=3);ax[1].set_ylabel('Power (W)')
    ax[2].plot(r['time_s'],r['current_A']);ax[2].set_ylabel('Cell current (A)')
    ax[3].plot(r['time_s'],r['power_residual_W'],label='Port balance');ax[3].plot(r['time_s'],p['power_W']-r['power_W'],'--',label='Python - Simulink battery power');ax[3].legend();ax[3].set(xlabel='Time (s)',ylabel='Residual (W)');ax[0].set_title('PA01 | balance, discharge, charge, curtailment, supply loss');figsave(fig,'PA01')
if __name__=='__main__':main()
