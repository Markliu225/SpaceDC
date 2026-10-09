function [out,s]=ecm_reference_step(s,i,v,cfg)
% Independent MATLAB equations; no Python call or Python result is loaded.
p=cfg.parameters;c=cfg.observer;dt=cfg.dt_s;
ocv=@(z) interp1(p.soc_grid,p.ocv_grid,z,'linear');
lastE=ocv(s.x(1));a=exp(-dt/s.tau);
if ~isempty(s.prev)
 ip=s.prev(1);s.x=[s.x(1)-ip*dt/(3600*p.capacity_Ah);a*s.x(2)+s.r1*(1-a)*ip];
 A=diag([1,a]);s.P=A*s.P*A'+dt*diag(c.process_variance_per_s);
 ap=exp(-dt/p.tau);s.plant=[s.plant(1)-ip*dt/(3600*p.capacity_Ah);ap*s.plant(2)+p.r1*(1-ap)*ip];
end
openv=ocv(s.plant(1))-s.plant(2)-p.r0*i;
z=min(max(s.x(1),p.soc_grid(1)),p.soc_grid(end));s.hits=s.hits+(z~=s.x(1));s.x(1)=z;
E=ocv(z);vp=E-s.x(2)-s.r0*i;
j=find(p.soc_grid<=z,1,'last');j=min(j,numel(p.soc_grid)-1);
slope=(p.ocv_grid(j+1)-p.ocv_grid(j))/(p.soc_grid(j+1)-p.soc_grid(j));
H=[slope,-1];rv=c.measurement_std_V^2;K=s.P*H'/(H*s.P*H'+rv);innovation=v-vp;
s.x=s.x+K*innovation;M=eye(2)-K*H;s.P=M*s.P*M'+rv*(K*K');
z2=min(max(s.x(1),p.soc_grid(1)),p.soc_grid(end));s.hits=s.hits+(z2~=s.x(1));s.x(1)=z2;
post=ocv(z2)-s.x(2)-s.r0*i;s.dE=s.dE+E-lastE;s.rlsE=s.rlsE+E-lastE;
s.currents=[s.currents,i];s.currents=s.currents(max(1,end-c.excitation_window_samples+1):end);
excited=numel(s.currents)>=10 && std(s.currents,1)>c.minimum_current_std_A;
status=0;due=mod(s.n,round(c.rls_interval_s/dt))==0;rdt=c.rls_interval_s;
if due
 f=exp(-rdt/c.rls_prefilter_tau_s);
 if isempty(s.rprev),ndy=s.rlsE-v;ndi=i;else,ndy=f*s.fdy+(1-f)*(s.rlsE-v);ndi=f*s.fdi+(1-f)*i;end
end
if due && ~isempty(s.rprev) && cfg.adaptive && excited
 phi=[s.fdy;ndi;s.fdi;1];gain=s.S*phi/(c.forgetting_factor+phi'*s.S*phi);
 th=s.theta+gain*(ndy-phi'*s.theta);aa=th(1);b0=th(2);b1=th(3);
 valid=aa>0 && aa<1;
 if valid,tau=-rdt/log(aa);r1=(b1+aa*b0)/(1-aa);else,tau=-1;r1=-1;end
 valid=valid && b0>=c.R0_bounds_ohm(1) && b0<=c.R0_bounds_ohm(2) && r1>=c.R1_bounds_ohm(1) && r1<=c.R1_bounds_ohm(2) && tau>=c.tau_bounds_s(1) && tau<=c.tau_bounds_s(2);
 s.theta=th;s.S=(s.S-gain*phi'*s.S)/c.forgetting_factor;s.S=(s.S+s.S')/2;
 if valid,s.r0=b0;s.r1=r1;s.tau=tau;status=1;else,status=-1;end
end
if due,s.fdy=ndy;s.fdi=ndi;s.rprev=[i,v];s.dE=0;end
s.prev=[i,v];s.n=s.n+1;
out=[openv,vp,post,s.x(1),s.x(2),s.r0,s.r1,s.tau,s.tau/s.r1,innovation,status,s.hits];
end
