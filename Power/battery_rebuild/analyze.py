from pathlib import Path
import json,hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
HERE=Path(__file__).resolve().parent;OUT=HERE/'results';FIG=HERE/'figures';FIG.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.25,'savefig.dpi':180})
def data(name):return np.genfromtxt(OUT/name,delimiter=',',names=True)
def finish(fig,name):fig.tight_layout();fig.savefig(FIG/(name+'.png'));plt.close(fig)

def main():
 s=json.loads((OUT/'summary.json').read_text()); comparisons=[]
 for m in s['cases']:
  cid=m['id'];a=data(cid+'_python.csv');b=data(cid+'_simulink.csv')
  assert len(a)==len(b) and np.max(abs(a['time_s']-b['time_s']))<1e-9
  errors={k:float(np.max(abs(a[k]-b[k]))) for k in a.dtype.names}
  # Compare all physical/observer outputs, including covariance-dependent parameters.
  passed=all(e<1e-6 for e in errors.values())
  comparisons.append(dict(id=cid,max_errors=errors,pass_=passed))
  np.savetxt(OUT/(cid+'_difference.csv'),np.c_[[a[k]-b[k] for k in a.dtype.names]].T,delimiter=',',header=','.join(a.dtype.names),comments='')
  fig,ax=plt.subplots(3,1,figsize=(8,6),sharex=True)
  ax[0].plot(a['time_s'],a['measured_voltage_V'],color='black',lw=1,label='Measured' if cid.startswith('MEASURED') else 'Synthetic truth + noise' if cid in ('NOISE','DRIFT','FIXED_EKF') else 'Synthetic truth')
  ax[0].plot(a['time_s'],a['open_loop_voltage_V'],lw=1,label='Open-loop ECM')
  ax[0].plot(a['time_s'],a['prior_voltage_V'],lw=.8,label='EKF prior prediction')
  ax[0].set_ylabel('Cell voltage (V)');ax[0].legend(fontsize=8,ncol=2)
  # These residuals are direct subtraction of the curves shown above.
  ax[1].plot(a['time_s'],1000*(a['open_loop_voltage_V']-a['measured_voltage_V']),label='Open loop minus reference')
  ax[1].plot(a['time_s'],1000*(a['prior_voltage_V']-a['measured_voltage_V']),label='Prior minus reference');ax[1].set_ylabel('Residual (mV)');ax[1].legend(fontsize=8)
  ax[2].step(a['time_s'],a['current_A'],where='post');ax[2].set_ylabel('Current (A)');ax[2].set_xlabel('Time (s), positive current = discharge')
  finish(fig,cid)
  if cid in ('EXACT','NOISE','DRIFT'):
   truth=data(cid+'_truth.csv');fig,axs=plt.subplots(2,2,figsize=(8,5.5))
   for ax,name,label in zip(axs.flat[:3],['r0_ohm','r1_ohm','tau_s'],['R0 (ohm)','R1 (ohm)','Time constant (s)']):
    ax.plot(a['time_s'],a[name],label='RLS');ax.plot(truth['time_s'],truth[name],'k--',label='Known truth');ax.set_ylabel(label);ax.set_xlabel('Time (s)');ax.legend(fontsize=8)
   axs.flat[3].plot(a['time_s'],100*(a['estimated_soc']-a['reference_soc']));axs.flat[3].set_ylabel('SOC error (percentage points)');axs.flat[3].set_xlabel('Time (s)')
   finish(fig,cid+'_parameters')
 s['simulink_comparison']=comparisons;s['simulink_all_pass']=all(m['pass_'] for m in comparisons)
 (OUT/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf8')
 a=data('ANALYTIC_python.csv');fig,ax=plt.subplots(2,1,figsize=(8,4.7),sharex=True)
 ax[0].plot(a['time_s'],a['voltage_V']);ax[0].set_ylabel('Cell voltage (V)')
 ax[1].plot(a['time_s'],1000*a['u1_V'],label='Model');ax[1].plot(a['time_s'],1000*a['analytic_u1_V'],'--',label='Exact solution');ax[1].set_ylabel('RC polarization (mV)');ax[1].set_xlabel('Time (s)');ax[1].legend();finish(fig,'ANALYTIC')
 a=data('ENERGY_python.csv');fig,ax=plt.subplots(figsize=(8,3.6))
 for k,label in [('ocv_minus_terminal_energy_J','OCV work minus terminal work'),('heat_J','Dissipated heat'),('rc_storage_J','Stored RC energy')]:ax.plot(a['time_s'],a[k],label=label)
 ax.set_xlabel('Time (s)');ax.set_ylabel('Energy (J)');ax.legend(fontsize=8);finish(fig,'ENERGY')
 a=data('CYCLES_python.csv');fig,ax=plt.subplots(figsize=(8,4.5))
 for cy,color in [(1,'black'),(2,'#dd6868'),(3,'#275dc2')]:
  for direction in (0,1):
   b=a[(a['cycle']==cy)&(a['direction']==direction)];ax.plot(b['capacity_Ah'],b['voltage_V'],color=color,lw=1.5,label=f'Cycle {cy}' if direction==0 else None)
 ax.set_xlabel('Integrated branch capacity (Ah)');ax.set_ylabel('Cell voltage (V)');ax.legend();ax.text(.03,.05,'0.1 C, 25 C, SOC 0.12 to 0.96\nNo aging state; repeated cycles overlap.',transform=ax.transAxes);finish(fig,'CYCLES')
 p=json.loads((OUT/'parameters.json').read_text());fig,ax=plt.subplots(1,2,figsize=(8,3.5))
 ax[0].plot(p['soc_grid'],p['ocv_grid'],'o-');ax[0].axvspan(.05,p['measured_soc_support'][0],color='grey',alpha=.2);ax[0].axvspan(p['measured_soc_support'][1],1,color='grey',alpha=.2);ax[0].set_xlabel('SOC');ax[0].set_ylabel('Pseudo OCV (V)')
 ax[1].plot([x['soc']for x in p['fits']],[1000*x['r0']for x in p['fits']],'o',label='R0 fit');ax[1].plot([x['soc']for x in p['fits']],[1000*x['r1']for x in p['fits']],'s',label='R1 fit');ax[1].set_xlabel('SOC');ax[1].set_ylabel('Resistance (milliohm)');ax[1].legend();finish(fig,'CALIBRATION')
 for name,texts in [('FLOW',['Current, temperature\nand plant state','One-RC plant\nSOC and RC voltage','Terminal voltage\npower and heat','Measured I and V','RLS parameter update\nEKF state estimate','Prior prediction\nSOC and diagnostics']),('RUNTIME',['Read parameters\nand initialize states','Advance plant\nwith held current','Predict voltage\nbefore measurement','EKF correction\nusing measured V','RLS at 1 s\nphysical guard','Log prediction, states\nand rejected updates'])]:
  fig,ax=plt.subplots(figsize=(9,3.1));ax.set_axis_off()
  for j,txt in enumerate(texts):
   row=j//3;col=j%3;x=.16+col*.34;y=.77-row*.53
   ax.text(x,y,txt,ha='center',va='center',bbox=dict(boxstyle='round,pad=.6',fc='#eef3f6',ec='#354d60'),fontsize=10)
   if col<2:ax.annotate('',xy=(x+.21,y),xytext=(x+.13,y),arrowprops={'arrowstyle':'->'})
  finish(fig,name)
 print('Simulink comparisons',len(comparisons),'all pass',s['simulink_all_pass'])
if __name__=='__main__':main()
