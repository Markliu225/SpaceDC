function y = power_reference(r, p, x)
% Independent MATLAB implementation of design P1-P11. No Python calls.
% x = [negative mean fraction; positive mean fraction; battery temperature].
y=nan(24,1); y(9:18)=[(x(1)-p.xn0)/(p.xn100-p.xn0);x(:);r.connected;r.latched;1;0;1;1];
g=r.G*max(0,r.cosine); available=p.area*p.eff*g; y(1)=available;
if strcmp(r.bad,'temperature'), x(3)=240; end
if any(strcmp(r.bad,{'identity','time','frame','zero_sun'})), y(1)=nan;y(15:18)=[0;0;0;7];return;end
if x(3)<p.Tlo || x(3)>p.Thi, y(15:18)=[0;0;0;6];return;end
if strcmp(r.bad,'mean_boundary'),x(1)=p.xnhi+.01;end
if strcmp(r.mode,'solar'),return;end
if strcmp(r.mode,'battery')
    b=cell_eval(r.current,x,p);y=pack(y,b,p);return;
end
if x(1)<p.xnlo || x(1)>p.xnhi || x(2)<p.xplo || x(2)>p.xphi
    y(15:18)=[1;1;0;5];return;
end
zero=cell_eval(0,x,p);
if zero.v<p.vmin || zero.v>p.vmax,y(15:18)=[1;1;0;5];return;end
need=r.request/p.eta*r.connected;
[b,kind]=allocate(need-available,x,p);
if r.connected,can=kind~=4;
elseif r.request/p.eta<=available,can=true;
else,[~,other]=allocate(r.request/p.eta-available,x,p);can=other~=4;
end
y(17)=can;
if kind==4,y(16)=1;y(18)=4;return;end
y=pack(y,b,p);
if need-available>0,pv=available;bus=pv+y(4);
else,pv=need-y(4);bus=need;
end
y(2)=pv;y(3)=p.eta*bus;y(8)=(1-p.eta)*bus;
if kind==2,y(18)=2;elseif ~r.connected,y(18)=3;end
end

function y=pack(y,b,p)
y([4 5 6 7 19 20 21 22 23 24])=[p.Ns*p.Np*b.i*b.v;p.Ns*b.v;p.Np*b.i;p.Ns*p.Np*b.heat;...
    b.i;b.v;-b.i/p.Qn;b.i/p.Qp;b.rev;min(b.margin)];
end

function b=cell_eval(i,x,p)
T=x(3); xn=x(1);xp=x(2); Rg=8.314462618;F=96485.33212;
Dn=p.n.D_ref_m2_s*exp(p.n.E_D_J_mol/Rg*(1/p.Tref-1/T));
Dp=p.p.D_ref_m2_s*exp(p.p.E_D_J_mol/Rg*(1/p.Tref-1/T));
sn=xn-p.n.radius_m^2*i/(15*Dn*p.Qn);sp=xp+p.p.radius_m^2*i/(15*Dp*p.Qp);
cn=(5*xn-3*sn)/2;cp=(5*xp-3*sp)/2;
if min([sn sp])<=0 || max([sn sp])>=1,error('PowerRef:surface','Surface fraction outside open unit interval');end
kn=2*p.n.I0_ref_A*sqrt(sn*(1-sn))*exp(p.n.E_I_J_mol/Rg*(1/p.Tref-1/T));
kp=2*p.p.I0_ref_A*sqrt(sp*(1-sp))*exp(p.p.E_I_J_mol/Rg*(1/p.Tref-1/T));
beta=polyval(flip(p.p.d_V_K(:)),sp)-polyval(flip(p.n.d_V_K(:)),sn);
un=polyval(flip(p.n.b_V(:)),sn)+(T-p.Tref)*polyval(flip(p.n.d_V_K(:)),sn);
up=polyval(flip(p.p.b_V(:)),sp)+(T-p.Tref)*polyval(flip(p.p.d_V_K(:)),sp);
activation=2*Rg*T/F*(asinh(i/(2*kn))+asinh(i/(2*kp)));
b.v=up-un-activation-i*p.Rohm;b.i=i;
b.rev=-i*T*beta;b.heat=i*activation+i*i*p.Rohm+b.rev;
b.margin=[i-p.imin,p.imax-i,b.v-p.vmin,p.vmax-b.v,...
 xn-p.xnlo,p.xnhi-xn,xp-p.xplo,p.xphi-xp,sn-p.xnlo,p.xnhi-sn,...
 sp-p.xplo,p.xphi-sp,cn-p.xnlo,p.xnhi-cn,cp-p.xplo,p.xphi-cp];
end

function [b,kind]=allocate(target,x,p)
% Derive fraction limits analytically, independently bracket voltage and power.
b=cell_eval(0,x,p);kind=1;if target==0,return;end
d=sign(target);Rg=8.314462618;T=x(3);
an=p.n.radius_m^2/(15*p.n.D_ref_m2_s*exp(p.n.E_D_J_mol/Rg*(1/p.Tref-1/T))*p.Qn);
ap=p.p.radius_m^2/(15*p.p.D_ref_m2_s*exp(p.p.E_D_J_mol/Rg*(1/p.Tref-1/T))*p.Qp);
starts=[x(1),x(2),x(1),x(2)];rates=d*[-an,ap,1.5*an,-1.5*ap];
lo=[p.xnlo,p.xplo,p.xnlo,p.xplo];hi=[p.xnhi,p.xphi,p.xnhi,p.xphi];
dist=zeros(1,4);
for k=1:4
    if rates(k)>0,dist(k)=(hi(k)-starts(k))/rates(k);else,dist(k)=(lo(k)-starts(k))/rates(k);end
end
if d>0,limit=p.imax;else,limit=-p.imin;end
limit=max(0,min([limit,dist]))*(1-1e-12);
endb=cell_eval(d*limit,x,p);
if endb.v<p.vmin || endb.v>p.vmax
    vl=p.vmin;if d<0,vl=p.vmax;end
    f=@(z) voltage_residual(d*z,x,p,vl);
    limit=fzero(f,[0 limit],optimset('TolX',1e-12))*(1-1e-12);
end
% Search from zero, retaining the first root on a nonmonotone power curve.
z=linspace(0,limit,65); previous=0; prev=-target;
for k=2:numel(z)
    here=power_residual(d*z(k),x,p,target);
    if sign(here)~=sign(prev) || here==0
        root=fzero(@(j) power_residual(j,x,p,target),sort(d*[previous z(k)]),optimset('TolX',1e-12));
        b=cell_eval(root,x,p);return;
    end
    previous=z(k);prev=here;
end
if limit>0
    best=fminbnd(@(z) -d*power_residual(d*z,x,p,0),0,limit,optimset('TolX',1e-12));
    capacity=d*power_residual(d*best,x,p,0);
    if capacity>=abs(target)
        root=fzero(@(z) power_residual(d*z,x,p,target),[0 best],optimset('TolX',1e-12));
        b=cell_eval(d*root,x,p);return;
    end
end
if d>0,kind=4;else,kind=2;b=cell_eval(-limit,x,p);end
end
function v=voltage_residual(i,x,p,lim),b=cell_eval(i,x,p);v=b.v-lim;end
function v=power_residual(i,x,p,target),b=cell_eval(i,x,p);v=p.Ns*p.Np*i*b.v-target;end
