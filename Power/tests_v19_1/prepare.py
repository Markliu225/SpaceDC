"""Freeze the accepted ten-project plan and inputs before either simulation."""
from pathlib import Path
import json,hashlib,shutil
import numpy as np
HERE=Path(__file__).resolve().parent
def save(p,v):p.write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    accepted=HERE/'fixtures/accepted_test_plan.md'
    if not accepted.exists():shutil.copy2(HERE.parent/'TEST_PLAN.md',accepted)
    z=np.array([.1,.5,.9]);T=np.array([0.,25.,50.]);zz,tt=np.meshgrid(z,T)
    A=dict(capacity_Ah=2.,soc_grid=z.tolist(),temperature_grid=[25.],ocv_table=[[3.3,3.7,4.1]],
           r0_table=[[.05]*3],r1_table=[[.02]*3],tau_table=[[10.]*3],provenance='Analytical test asset A')
    B=dict(capacity_Ah=2.,soc_grid=z.tolist(),temperature_grid=T.tolist(),
           ocv_table=(3.2+zz-.001*(tt-25)+.002*zz*(tt-25)).tolist(),
           r0_table=(.05+.01*(.5-zz)-.0002*(tt-25)).tolist(),
           r1_table=(.02+.004*(.5-zz)-.00005*(tt-25)).tolist(),
           tau_table=(10+2*(.5-zz)-.02*(tt-25)).tolist(),provenance='Synthetic bilinear test asset B')
    old=HERE.parent/'battery_rebuild';raw=json.loads((old/'results/parameters.json').read_text())
    C=dict(capacity_Ah=2.84,soc_grid=raw['soc_grid'][1:-1],temperature_grid=[25.],
           ocv_table=[raw['ocv_grid'][1:-1]],r0_table=[[raw['r0']]*5],r1_table=[[raw['r1']]*5],
           tau_table=[[raw['tau']]*5],provenance='BAK 25 C; pulses 1,2,5,7,9 load-only offline fits; frozen median RC, no online identification')
    for name,asset in [('A',A),('B',B),('C',C)]:save(HERE/'fixtures'/f'asset_{name}.json',asset)
    cases=[]
    def add(cid,project,end,dt=.1,asset=A,initial=(.6,0),temp=25.,ns=1,np_=1,freeze=False,kind='current',profile=None):
        t=np.round(np.arange(round(end/dt)+1)*dt,10)
        data=np.zeros((len(t),8));data[:,0]=t;data[:,2]=temp+273.15;data[:,4]=1
        if profile:
            for start,i in profile:data[t>=start,1]=i
        c=dict(id=cid,project=project,asset=asset,initial=list(initial),dt_s=dt,stop_s=end,
               max_step_s=dt,n_series=ns,n_parallel=np_,freeze=freeze,kind=kind,
               area_m2=2.,solar_efficiency=.25,distribution_efficiency=.9,
               charge_limit_A=-3.,discharge_limit_A=5.,v_min_V=2.8,v_max_V=4.3)
        cases.append((c,data));return data,c
    d,c=add('PV01_TIME','PV01',60)
    for start,g in [(0,1000),(10,500),(20,0),(40,1000)]:d[d[:,0]>=start,3]=g
    for idx,angle in enumerate([0,60,90,180]):
        d,c=add(f'PV01_ANGLE_{angle}','PV01',.1,freeze=True);d[:,3]=1000;d[:,4]=np.cos(np.deg2rad(angle))
    d,c=add('PV01_AREA','PV01',.1,freeze=True);d[:,3]=1000;c['area_m2']=4.
    for ns,np_ in [(1,1),(4,2)]:
        for i in [0,2,-2]:add(f'BT01_{ns}S{np_}P_I{i:+d}','BT01',.1,initial=(.6,.02),ns=ns,np_=np_,freeze=True,profile=[(0,i)])
    for dt,suffix in [(.1,''),(.05,'_REFINE'),(.025,'_FINE')]:add('BT02'+suffix,'BT02',60,dt=dt,profile=[(0,0),(10,2),(30,0)])
    for project in ['BT03','BT05']:add(project,project,80,profile=[(0,0),(10,-2),(30,2),(50,0)])
    for temp in [0,25,50]:add(f'BT04_T{temp}','BT04',60,asset=B,temp=temp,profile=[(0,0),(10,2),(30,0)])
    add('BT06','BT06',54720,dt=1.,initial=(.12,0),profile=[(0,-.2),(27360,.2)])
    for n in [4,6,8]:
        oldcfg=json.loads((old/f'fixtures/MEASURED_{n:02d}.json').read_text())
        measured=np.genfromtxt(old/f'fixtures/MEASURED_{n:02d}.csv',delimiter=',',names=True)
        d,c=add(f'BT07_P{n:02d}','BT07',119.9,asset=C,initial=(oldcfg['initial_open_loop_soc'],0))
        d[:,1]=measured['current_A'];d[:,7]=measured['measured_voltage_V']
        c['source_fixture_sha256']=sha(old/f'fixtures/MEASURED_{n:02d}.csv')
    d,c=add('EK01','EK01',300,kind='ekf')
    pattern=np.array([0,1.5,0,-1,2,0,-1.5,0,1,-.5]);d[:,1]=pattern[(np.floor((d[:,0]+1e-9)/10).astype(int))%10]
    d[:,6]=np.random.default_rng(20261008).normal(0,.003,len(d))
    d,c=add('PA01','PA01',100,kind='allocation',ns=4,np_=2)
    for start,g,r in [(0,1000,450),(20,1000,540),(40,1000,405),(60,1000,90),(80,0,180)]:
        d[d[:,0]>=start,3]=g;d[d[:,0]>=start,5]=r
    index=[]
    for c,d in cases:
        path=HERE/'fixtures'/f"{c['id']}.csv"
        np.savetxt(path,d,delimiter=',',header='time_s,current_A,temperature_K,irradiance_W_m2,cos_incidence,request_W,noise_V,measured_voltage_V',comments='',fmt='%.17g')
        c['input_sha256']=sha(path);save(HERE/'fixtures'/f"{c['id']}.json",c);index.append(c['id'])
    save(HERE/'fixtures/index.json',index)
    shutil.copy2(old/'data/LICENSE.txt',HERE/'fixtures/BAK_DATA_LICENSE.txt')
    save(HERE/'contract.json',dict(revision='19.1',projects=['PV01']+[f'BT{i:02d}'for i in range(1,8)]+['EK01','PA01'],
         plan_sha256=sha(accepted),design_sha256=sha(HERE.parent/'SDTwin_Power_Design_Report_CN_v19.1.docx'),
         criteria=dict(static_atol=1e-10,static_rtol=1e-10,soc=1e-7,polarization_V=1e-6,voltage_V=1e-5,current_A=1e-5,power_W=1e-4,
                       residual_atol_W=1e-6,residual_rtol=1e-9,measured_rmse_V=.03,measured_max_V=.1,ekf_soc=.02),
         cases=index,parameter_policy='Read-only tables; no RLS; external physical solver; EKF only',
         reference_policy='Independent MATLAB equations and native Simulink Integrators; shared input arrays, no Python callback',
         raw_data_sha256=sha(old/'data/BAK_25C.csv'),calibration_record_sha256=sha(old/'results/parameters.json')))
    print(f'Frozen {len(index)} runs for 10 projects.')
if __name__=='__main__':main()
