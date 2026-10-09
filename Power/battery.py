"""Design v19.1: table-driven 1RC equations and separate EKF. No plant solver or RLS."""
from dataclasses import dataclass
import math
import numpy as np

@dataclass(frozen=True)
class Parameters:
    capacity_Ah: float
    soc_grid: tuple
    temperature_grid: tuple
    ocv_table: tuple
    r0_table: tuple
    r1_table: tuple
    tau_table: tuple

    @classmethod
    def from_dict(cls, d):
        names=cls.__dataclass_fields__
        a={k:d[k] for k in names}
        for k in names:
            if k.endswith('_table'):a[k]=tuple(tuple(float(x) for x in r) for r in a[k])
            elif k.endswith('_grid'):a[k]=tuple(float(x) for x in a[k])
        return cls(**a)

    def __post_init__(self):
        if not math.isfinite(self.capacity_Ah) or self.capacity_Ah<=0:raise ValueError('Invalid capacity')
        for g in (self.soc_grid,self.temperature_grid):
            if not len(g) or not np.isfinite(g).all() or np.any(np.diff(g)<=0):raise ValueError('Invalid grid')
        if len(self.soc_grid)<2:raise ValueError('At least two SOC knots required')
        for key in ('ocv_table','r0_table','r1_table','tau_table'):
            a=np.asarray(getattr(self,key))
            if a.shape!=(len(self.temperature_grid),len(self.soc_grid)) or not np.isfinite(a).all():raise ValueError('Invalid table')
            if key!='ocv_table' and np.any(a<=0):raise ValueError('Nonpositive RC parameter')

    def lookup(self,z,T_K):
        T=T_K-273.15
        if not math.isfinite(z) or not math.isfinite(T):raise ValueError('Nonfinite query')
        if not self.soc_grid[0]<=z<=self.soc_grid[-1]:raise ValueError('SOC outside table')
        if len(self.temperature_grid)==1:
            if abs(T-self.temperature_grid[0])>1e-10:raise ValueError('Temperature outside table')
            j=0;b=0.
        else:
            if not self.temperature_grid[0]<=T<=self.temperature_grid[-1]:raise ValueError('Temperature outside table')
            j=min(np.searchsorted(self.temperature_grid,T,side='right')-1,len(self.temperature_grid)-2)
            b=(T-self.temperature_grid[j])/(self.temperature_grid[j+1]-self.temperature_grid[j])
        k=min(np.searchsorted(self.soc_grid,z,side='right')-1,len(self.soc_grid)-2)
        dz=self.soc_grid[k+1]-self.soc_grid[k];a=(z-self.soc_grid[k])/dz
        out={}
        for key in ('ocv','r0','r1','tau'):
            v=getattr(self,key+'_table');lo=(1-a)*v[j][k]+a*v[j][k+1]
            hi=lo if len(self.temperature_grid)==1 else (1-a)*v[j+1][k]+a*v[j+1][k+1]
            out[key]=(1-b)*lo+b*hi
        v=self.ocv_table
        slope0=(v[j][k+1]-v[j][k])/dz
        slope1=slope0 if len(self.temperature_grid)==1 else (v[j+1][k+1]-v[j+1][k])/dz
        out['slope']=(1-b)*slope0+b*slope1;out['c1']=out['tau']/out['r1']
        return out

@dataclass(frozen=True)
class State:
    soc: float
    polarization_V: float=0.

def response(p,s,current_A,T_B_K=298.15,ns=1,np_=1):
    if not np.isfinite([current_A,s.polarization_V]).all():raise ValueError('Nonfinite state/current')
    if not isinstance(ns,int) or not isinstance(np_,int) or min(ns,np_)<1:raise ValueError('Invalid topology')
    a=p.lookup(s.soc,T_B_K);i=float(current_A);u=s.polarization_V
    v=a['ocv']-i*a['r0']-u;q0=i*i*a['r0'];q1=u*u/a['r1'];n=ns*np_
    return dict(**a,voltage_V=v,pack_voltage_V=ns*v,pack_current_A=np_*i,power_W=n*i*v,
                ohmic_heat_W=n*q0,polarization_heat_W=n*q1,heat_W=n*(q0+q1),
                polarization_energy_J=n*.5*a['c1']*u*u,dsoc_dt=-i/(3600*p.capacity_Ah),
                du1_dt=-u/a['tau']+a['r1']*i/a['tau'])

class EKF:
    """P11/P12, 0.1 s measurement clock. State is never shared with the plant."""
    def __init__(self,p,soc=.7,u1=0.,dt=.1):
        self.p=p;self.x=np.array([soc,u1]);self.P=np.diag([.01,.0001]);self.dt=dt
        self.Q=np.diag([1e-9,1e-7]);self.R=9e-6;self.previous_current=None
    def step(self,current_A,measured_voltage_V,T_B_K=298.15):
        par=self.p.lookup(self.x[0],T_B_K);a=math.exp(-self.dt/par['tau'])
        x=self.x.copy();P=self.P.copy()
        if self.previous_current is not None:
            x+=np.array([-self.previous_current*self.dt/(3600*self.p.capacity_Ah),
                         (a-1)*x[1]+par['r1']*(1-a)*self.previous_current])
            A=np.diag([1.,a]);P=A@P@A.T+self.Q
        # No boundary clipping: an invalid estimate is visible to the caller.
        pred=self.p.lookup(x[0],T_B_K);vp=pred['ocv']-par['r0']*current_A-x[1]
        H=np.array([pred['slope'],-1.]);K=P@H/(H@P@H+self.R);innovation=measured_voltage_V-vp
        xp=x+K*innovation;M=np.eye(2)-np.outer(K,H);Pn=M@P@M.T+self.R*np.outer(K,K)
        self.p.lookup(xp[0],T_B_K)
        self.x=xp;self.P=Pn;self.previous_current=current_A
        return [vp,xp[0],xp[1],innovation,Pn[0,0],Pn[0,1],Pn[1,0],Pn[1,1],x[0],x[1]]

JointObserver=EKF
