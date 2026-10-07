"""Freeze independent-comparison fixtures and criteria before executing simulations."""
from pathlib import Path
import sys, json, hashlib, copy
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Thermal'))

HERE=Path(__file__).resolve().parent
OUT=HERE/'results'
FIELDS=['P_pv_max_W','P_pv_W','P_load_W','P_B_W','V_B_V','I_B_A','Q_B_W','Q_D_W',
        'SOC','x_n','x_p','T_B_K','connected','latched','valid','event_required','can_supply',
        'reason','i_A','v_cell_V','dx_n_dt','dx_p_dt','q_reversible_cell_W','min_margin']
# Criteria are engineering verification tolerances, not measured cell accuracy.
TOL={'power_W':1e-3,'voltage_V':1e-4,'current_A':1e-4,'fraction':1e-6,
     'temperature_K':1e-3,'derivative':1e-8,'static_power_W':1e-6,
     'event_time_s':1e-3,'energy_relative':1e-5,'conservation_W':2e-6}
NAMES={
'PV-001':('太阳辐照度与板面姿态','Solar irradiance and panel attitude'),
'BT-001':('电池开路电压与初始电量','Open circuit voltage and initial charge'),
'BT-002':('充放电电压与温度响应','Charge and discharge voltage versus temperature'),
'BT-003':('电池发热与可逆热符号','Battery heat and reversible heat sign'),
'BT-004':('单体到串并联电池组换算','Cell to series and parallel pack scaling'),
'PD-001':('太阳与电池功率分配','Solar and battery power allocation'),
'PD-002':('配电效率与损耗','Distribution efficiency and loss'),
'CT-001':('充电限制与太阳限发','Charge limits and solar curtailment'),
'CT-002':('放电能力与供电不足','Discharge capability and supply shortfall'),
'CT-003':('满电状态下的充电边界','Charging boundary at full state of charge'),
'PR-001':('保护指令与锁存状态','Protection commands and latched states'),
'IV-001':('无效输入与状态边界','Invalid inputs and state boundaries'),
'DY-001':('持续日照充电过程','Charging under continuous sunlight'),
'DY-002':('入影与出影供电过程','Eclipse entry and exit'),
'DY-003':('计算负载阶跃','Compute load steps'),
'DY-004':('充电受限的动态过程','Dynamic charge curtailment'),
'DY-005':('失电锁存与显式重启','Supply loss latch and explicit restart'),
'DY-006':('电池电热反馈','Battery electrothermal feedback'),
'DY-007':('三个轨道周期的能量收支','Energy balance over three orbit cycles'),
'NU-001':('求解器收敛与精度复核','Solver convergence and accuracy review')}

def canonical(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
def save(path,obj):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(canonical(obj),encoding='utf-8')
def prepare():
    from sdtwin_sim import power_stand_in as ps
    a,s=ps.example_power_records(); p=ps.load_power_parameters(a,s)
    base={'G':1361.,'cosine':1.,'request':200.,'T':293.15,'xn':s['initial_state']['x_n'],
          'xp':s['initial_state']['x_p'],'connected':1,'latched':0,'current':0.,
          'mode':'allocate','command':'none','bad':'none','overrides':{}}
    def row(**kw):return dict(copy.deepcopy(base),**kw)
    def pair(x):return p.battery.x_p_100+(p.battery.x_n_100-x)*p.battery.Q_n_C/p.battery.Q_p_C
    cases=[]
    def add(cid,rows=None,segments=None,**kw):
        defaults=dict(step=10.,thermal=False,overrides={},T0=293.15,C=5000.,R=.8,Tsink=283.15)
        defaults.update(kw)
        cases.append(dict(id=cid,name_cn=NAMES[cid][0],name_en=NAMES[cid][1],
                          kind='dynamic' if segments else 'static',rows=rows or [],segments=segments or [],**defaults))
    add('PV-001',[row(mode='solar',G=g,cosine=c) for g in [0.,680.5,1361.] for c in [-1.,-.5,0.,.25,.5,.866025403784,1.]])
    add('BT-001',[row(mode='battery',xn=x,xp=pair(x)) for x in [.10,.20,.30,.40,.50,.60,.70,.80,.88]])
    add('BT-002',[row(mode='battery',T=t,current=i) for t in [273.15,293.15,313.15] for i in [-1.,-.5,0.,.5,1.,2.]])
    add('BT-003',[row(mode='battery',T=t,current=i) for t in [283.15,303.15] for i in [-.5,-.1,0.,.1,.5,1.]])
    add('BT-004',[row(mode='battery',current=.5,overrides={'Ns':ns,'Np':np}) for ns,np in [(1,1),(8,1),(1,6),(8,6),(12,4)]])
    add('PD-001',[row(G=g,request=q) for g in [0.,300.,800.,1361.] for q in [0.,50.,200.,400.,900.,2500.]])
    add('PD-002',[row(G=0.,request=q,overrides={'eta':eta}) for eta in [.8,.95,1.] for q in [0.,100.,300.]])
    add('CT-001',[row(G=1800.,request=25.,overrides=o,T=t) for o,t in [
        ({'imin':-.2},293.15),({'vmax':4.03},293.15),({},253.15),({},273.15),({},313.15),({},293.15)]])
    add('CT-002',[row(G=0.,request=q,overrides=o,T=t) for o,t in [({},293.15),({'imax':.25},293.15),({'vmin':3.9},293.15),({},253.15)]
                    for q in [20.,100.,1000.]])
    add('CT-003',[row(G=g,request=25.,xn=.90,xp=.27) for g in [800.,1361.,1800.]])
    add('PR-001',[row(G=g,request=q,connected=c,latched=l,command=cmd) for g,q,c,l,cmd in [
        (1361.,200.,1,0,'stop'),(1361.,200.,0,0,'start'),(0.,2500.,0,1,'start'),
        (1361.,200.,0,1,'start'),(0.,2500.,1,0,'supply_loss'),(1361.,200.,1,0,'stop_start'),
        (1361.,200.,1,0,'repeat_stop'),(0.,2500.,1,0,'trial_supply_loss')]])
    add('IV-001',[row(bad=b) for b in ['temperature','identity','time','frame','zero_sun','mean_boundary']])
    def seg(end,G,q,**kw):return dict(end=end,G=G,cosine=1.,request=q,T=293.15,command='none',**kw)
    add('DY-001',segments=[seg(900.,1361.,200.)],step=10.,thermal=False,overrides={})
    add('DY-002',segments=[seg(1800.,1361.,200.),seg(3800.,0.,200.),seg(5400.,1361.,200.)],step=20.,thermal=False,overrides={})
    add('DY-003',segments=[seg(200.,800.,100.),seg(400.,800.,350.),seg(600.,800.,550.),seg(800.,800.,100.)],step=5.,thermal=False,overrides={})
    add('DY-004',segments=[seg(900.,1800.,25.)],step=10.,thermal=False,overrides={'imin':-.2})
    add('DY-005',segments=[seg(100.,1361.,200.),seg(200.,0.,2500.),seg(300.,1361.,200.),
        dict(seg(400.,1361.,200.),command='start'),dict(seg(500.,1361.,200.),command='stop'),
        dict(seg(600.,1361.,200.),command='start')],step=5.,thermal=False,overrides={})
    add('DY-006',segments=[seg(1800.,0.,200.)],step=10.,thermal=True,overrides={},T0=283.15,C=5000.,R=.8,Tsink=273.15)
    add('DY-007',segments=[seg(k*5400.+t,g,200.) for k in range(3) for t,g in [(1800.,1361.),(3800.,0.),(5400.,1361.)]],step=30.,thermal=False,overrides={})
    add('NU-001',segments=[seg(1200.,0.,200.)],step=10.,thermal=True,overrides={},T0=293.15,C=5000.,R=.8,Tsink=283.15)
    suite={'contract_version':'1.1','parameters':a,'scene':s,'fields':FIELDS,'tolerances':TOL,'cases':cases,
           'contract_revision':'Coverage review added the full-SOC design requirement and CT-003 after an overcharge was observed. All numerical comparison tolerances remain unchanged. Earlier frozen inputs are retained in history.',
           'numerics':{'python':'DOP853','simulink':'ode45','rtol':1e-8,'atol':1e-10,'max_step_s':10.,
                       'refinement_rtol':1e-10,'refinement_atol':1e-12,'refinement_max_step_s':2.},
           'provenance':'Illustrative 8s6p battery and 1.8 m2 array from existing Thermal Power stand-in; no measured cell.'}
    if (OUT/'suite.json').exists():
        old=json.loads((OUT/'suite.json').read_text(encoding='utf-8'))
        if old.get('contract_version')!=suite['contract_version']:
            save(OUT/'history'/('suite_'+old.get('contract_version','unknown')+'.json'),old)
            save(OUT/'history'/('criteria_'+old.get('contract_version','unknown')+'.json'),json.loads((OUT/'frozen_contract.json').read_text()))
    save(OUT/'suite.json',suite)
    digest=hashlib.sha256((OUT/'suite.json').read_bytes()).hexdigest()
    save(OUT/'frozen_contract.json',{'suite_sha256':digest,'tolerances':TOL,'case_count':len(cases)})
    print('Frozen',len(cases),'cases',digest)
    return suite
if __name__=='__main__':prepare()
