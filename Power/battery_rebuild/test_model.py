"""Regression checks beyond comparing two copies of the same equations."""
import unittest,json
import numpy as np
from scipy.integrate import solve_ivp
from run import HERE,params,CON
from ecm import State,advance,response,JointObserver

class BatteryTests(unittest.TestCase):
 def setUp(self):self.p=params(json.loads((HERE/'results/parameters.json').read_text()))
 def test_random_steps_against_independent_ode(self):
  p=self.p;rng=np.random.default_rng(71);s=State(.65,.015)
  for _ in range(50):
   i=float(rng.uniform(-2,2));dt=float(rng.uniform(.01,1))
   solution=solve_ivp(lambda t,x:[-i/(3600*p.capacity_Ah),i/p.c1-x[1]/(p.r1*p.c1)],(0,dt),[s.soc,s.polarization_V],rtol=1e-11,atol=1e-13)
   s=advance(p,s,i,dt);np.testing.assert_allclose([s.soc,s.polarization_V],solution.y[:,-1],rtol=1e-10,atol=1e-12)
 def test_observer_is_causal(self):
  data=np.loadtxt(HERE/'fixtures/NOISE.csv',delimiter=',',skiprows=1)[:250]
  altered=data.copy();altered[150:,2]+=.2
  outputs=[]
  for d in (data,altered):
   o=JointObserver(self.p,.75,CON['observer']);outputs.append(np.array([o.step(i,v) for _,i,v,_ in d]))
  np.testing.assert_array_equal(outputs[0][:150],outputs[1][:150])
 def test_state_covariance_stays_psd(self):
  data=np.loadtxt(HERE/'fixtures/NOISE.csv',delimiter=',',skiprows=1)
  o=JointObserver(self.p,.75,CON['observer'])
  for _,i,v,_ in data:
   o.step(i,v);self.assertGreater(np.min(np.linalg.eigvalsh(o.P)),-1e-12);self.assertGreater(np.min(np.linalg.eigvalsh(o.S)),-1e-10)
 def test_parameter_update_does_not_change_past_prediction(self):
  a=JointObserver(self.p,.65,CON['observer'],adaptive=True);b=JointObserver(self.p,.65,CON['observer'],adaptive=False)
  for k in range(100):
   i=0 if k<99 else 1.;v=self.p.ocv(.65)-self.p.r0*i
   aa=a.step(i,v);bb=b.step(i,v)
   self.assertEqual(aa[0],bb[0])
 def test_invalid_values_rejected(self):
  for x in (float('nan'),float('inf')):
   with self.assertRaises(ValueError):advance(self.p,State(.6),x,.1)
   with self.assertRaises(ValueError):JointObserver(self.p,.6,CON['observer']).step(0,x)
 def test_recovery_requires_a_state(self):
  initial=advance(self.p,State(.6),1,5);later=advance(self.p,initial,0,5)
  self.assertGreater(response(self.p,later,0)['voltage_V'],response(self.p,initial,0)['voltage_V'])
 def test_rest_is_not_parameter_identification(self):
  o=JointObserver(self.p,.6,CON['observer']);before=o.theta.copy()
  for k in range(500):o.step(0,self.p.ocv(.6))
  np.testing.assert_array_equal(o.theta,before);self.assertEqual(o.accepted,0)
 def test_voltage_step_preserves_state(self):
  s=State(.6,.015);v0=response(self.p,s,0)['voltage_V'];v1=response(self.p,s,1)['voltage_V']
  self.assertAlmostEqual(v0-v1,self.p.r0);self.assertEqual(s,State(.6,.015))

if __name__=='__main__':unittest.main(verbosity=2)
