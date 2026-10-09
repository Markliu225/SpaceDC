"""One-RC battery plant and a causal EKF/RLS observer. SI units except Ah.

The plant never reads measured voltage. The observer never reads true SOC.
Parameters are constant within a step. Temperature is supplied by the caller;
only the calibrated 25 C data set is supported by this parameterization.
"""
from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class Parameters:
    capacity_Ah: float
    r0: float
    r1: float
    tau: float
    soc_grid: tuple
    ocv_grid: tuple
    temperature_C: float = 25.0

    def __post_init__(self):
        if not all(math.isfinite(x) and x > 0 for x in (self.capacity_Ah,self.r0,self.r1,self.tau)):
            raise ValueError('Capacity, resistance and time constant must be positive and finite')
        if len(self.soc_grid)<2 or len(self.soc_grid)!=len(self.ocv_grid):raise ValueError('Invalid OCV table')
        if not np.all(np.diff(self.soc_grid)>0) or not np.all(np.diff(self.ocv_grid)>0):raise ValueError('OCV table must be strictly increasing')

    @property
    def c1(self):return self.tau/self.r1

    def ocv(self,z):
        if not math.isfinite(z) or not self.soc_grid[0]-1e-10<=z<=self.soc_grid[-1]+1e-10:
            raise ValueError('SOC outside calibrated OCV domain')
        return float(np.interp(z,self.soc_grid,self.ocv_grid))

    def slope(self,z):
        self.ocv(z)
        k=int(np.clip(np.searchsorted(self.soc_grid,z,side='right')-1,0,len(self.soc_grid)-2))
        return (self.ocv_grid[k+1]-self.ocv_grid[k])/(self.soc_grid[k+1]-self.soc_grid[k])


@dataclass(frozen=True)
class State:
    soc: float
    polarization_V: float = 0.0


def advance(p,s,current_A,dt_s,temperature_C=25.0):
    if not all(math.isfinite(x) for x in (current_A,dt_s,temperature_C,s.polarization_V)) or dt_s<=0:raise ValueError('Invalid step input')
    if abs(temperature_C-p.temperature_C)>1e-8:raise ValueError('Temperature outside calibrated domain')
    p.ocv(s.soc)
    z=s.soc-current_A*dt_s/(3600*p.capacity_Ah)
    p.ocv(z)  # Reject crossing; do not clip inventory.
    a=math.exp(-dt_s/p.tau)
    return State(z,a*s.polarization_V+p.r1*(1-a)*current_A)


def response(p,s,current_A,ns=1,np_=1):
    if not isinstance(ns,int) or not isinstance(np_,int) or min(ns,np_)<1:raise ValueError('Invalid pack topology')
    if not math.isfinite(current_A) or not math.isfinite(s.polarization_V):raise ValueError('Nonfinite state/input')
    v=p.ocv(s.soc)-current_A*p.r0-s.polarization_V
    heat=current_A**2*p.r0+s.polarization_V**2/p.r1
    return dict(voltage_V=v,pack_voltage_V=ns*v,pack_current_A=np_*current_A,
                power_W=ns*np_*current_A*v,heat_W=ns*np_*heat,
                polarization_energy_J=ns*np_*.5*p.c1*s.polarization_V**2)


def safe_current(p,s,request_A,dt_s,v_min=3.,v_max=4.2,i_max=6.5):
    """Bounds the next inventory and instantaneous voltage. Caller checks future V."""
    if not all(math.isfinite(x) for x in (request_A,dt_s,v_min,v_max,i_max)) or dt_s<=0 or i_max<=0 or v_min>=v_max:raise ValueError('Invalid protection input')
    e=p.ocv(s.soc)-s.polarization_V
    lo=max(-i_max,(e-v_max)/p.r0,(s.soc-p.soc_grid[-1])*3600*p.capacity_Ah/dt_s)
    hi=min(i_max,(e-v_min)/p.r0,(s.soc-p.soc_grid[0])*3600*p.capacity_Ah/dt_s)
    if lo>hi:raise ValueError('No feasible current')
    return float(np.clip(request_A,lo,hi))


class JointObserver:
    """RLS: y[k]=a*y[k-1]+b0*i[k]+b1*i[k-1]; EKF: x=[SOC,u1].

    RLS uses filtered levels y and i plus a DC offset. Its OCV baseline follows
    predicted increments, excluding EKF correction jumps. The nuisance offset
    absorbs an initial OCV bias locally; it is not a new physical ECM state.
    RLS is committed after the voltage update; accepted parameters are used on
    the next sample. This avoids fitting and scoring the same observation.
    RLS works at 1 s while EKF runs at 0.1 s. Unconstrained RLS coefficients
    continue updating; only physical coefficients are committed to the ECM.
    OCV and capacity are calibrated inputs, not identified by this RLS.
    """
    def __init__(self,p,soc,config,dt=0.1,adaptive=True):
        p.ocv(soc)
        if not math.isfinite(dt) or dt<=0 or config['rls_interval_s']<dt or not math.isclose(config['rls_interval_s']/dt,round(config['rls_interval_s']/dt)):
            raise ValueError('RLS interval must be a positive integer multiple of EKF interval')
        if not 0<config['forgetting_factor']<=1 or config['measurement_std_V']<=0:
            raise ValueError('Invalid estimator configuration')
        self.p=p;self.x=np.array([soc,0.]);self.P=np.diag(config['initial_state_variance'])
        self.c=config;self.dt=dt;self.adaptive=adaptive
        a=math.exp(-config['rls_interval_s']/p.tau)
        self.theta=np.array([a,p.r0,p.r1*(1-a)-a*p.r0,0.])
        self.S=np.diag(config['rls_covariance']);self.prev=None;self.currents=[]
        self.r0=p.r0;self.r1=p.r1;self.tau=p.tau
        self.accepted=0;self.rejected=0;self.frozen=0;self.boundary_hits=0
        self.filtered_dy=0.;self.filtered_di=0.
        self.n=0;self.rls_prev=None;self.ocv_increment=0.
        self.rls_ocv=p.ocv(soc)

    def step(self,current_A,voltage_V):
        if not np.isfinite([current_A,voltage_V]).all():raise ValueError('Nonfinite measurement')
        i=float(current_A);v=float(voltage_V);dt=self.dt
        a=math.exp(-dt/self.tau)
        previous_ocv=self.p.ocv(float(self.x[0]))
        if self.prev is not None:
            ip=self.prev[0]
            self.x=np.array([self.x[0]-ip*dt/(3600*self.p.capacity_Ah),a*self.x[1]+self.r1*(1-a)*ip])
            A=np.diag([1.,a]);self.P=A@self.P@A.T+dt*np.diag(self.c['process_variance_per_s'])
        prior_soc=float(self.x[0])
        # A state estimate may reach a constrained boundary; log this, never hide it.
        z=float(np.clip(prior_soc,self.p.soc_grid[0],self.p.soc_grid[-1]))
        self.boundary_hits+=int(z!=prior_soc);self.x[0]=z
        ocv=self.p.ocv(z);prior_v=ocv-self.x[1]-self.r0*i
        H=np.array([self.p.slope(z),-1.]);rv=self.c['measurement_std_V']**2
        K=self.P@H/(H@self.P@H+rv);innovation=v-prior_v
        self.x=self.x+K*innovation
        M=np.eye(2)-np.outer(K,H);self.P=M@self.P@M.T+rv*np.outer(K,K)
        z2=float(np.clip(self.x[0],self.p.soc_grid[0],self.p.soc_grid[-1]));self.boundary_hits+=int(z2!=self.x[0]);self.x[0]=z2
        posterior_v=self.p.ocv(z2)-self.x[1]-self.r0*i
        # OCV change due to Coulomb propagation only, never the EKF correction.
        self.ocv_increment+=ocv-previous_ocv
        self.rls_ocv+=ocv-previous_ocv
        self.currents.append(i);self.currents=self.currents[-self.c['excitation_window_samples']:]
        excited=len(self.currents)>=10 and np.std(self.currents)>self.c['minimum_current_std_A']
        status=0
        due=self.n%int(round(self.c['rls_interval_s']/dt))==0
        rdt=self.c['rls_interval_s']
        if due:
            f=math.exp(-rdt/self.c['rls_prefilter_tau_s'])
            new_dy=f*self.filtered_dy+(1-f)*(self.rls_ocv-v) if self.rls_prev is not None else self.rls_ocv-v
            new_di=f*self.filtered_di+(1-f)*i if self.rls_prev is not None else i
        if due and self.rls_prev is not None and self.adaptive and excited:
            phi=np.array([self.filtered_dy,new_di,self.filtered_di,1.])
            gain=self.S@phi/(self.c['forgetting_factor']+phi@self.S@phi)
            th=self.theta+gain*(new_dy-phi@self.theta)
            aa,b0,b1=th[:3]
            valid=0<aa<1
            tau=-rdt/math.log(aa) if valid else -1
            r1=(b1+aa*b0)/(1-aa) if valid else -1
            valid=valid and self.c['R0_bounds_ohm'][0]<=b0<=self.c['R0_bounds_ohm'][1] and self.c['R1_bounds_ohm'][0]<=r1<=self.c['R1_bounds_ohm'][1] and self.c['tau_bounds_s'][0]<=tau<=self.c['tau_bounds_s'][1]
            self.theta=th;self.S=(self.S-np.outer(gain,phi)@self.S)/self.c['forgetting_factor'];self.S=(self.S+self.S.T)/2
            if valid:
                self.r0=float(b0);self.r1=float(r1);self.tau=float(tau);self.accepted+=1;status=1
            else:self.rejected+=1;status=-1
        else:self.frozen+=1
        if due:
            self.filtered_dy=new_dy;self.filtered_di=new_di;self.rls_prev=(i,v);self.ocv_increment=0.
        self.prev=(i,v)
        self.n+=1
        return [prior_v,posterior_v,self.x[0],self.x[1],self.r0,self.r1,self.tau,self.tau/self.r1,innovation,status,self.boundary_hits]
