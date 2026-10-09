function v=asset_eval(a,z,TK)
% Independent MATLAB implementation of P8, no Python calls.
T=TK-273.15;zg=a.soc_grid(:);tg=a.temperature_grid(:);
if z<zg(1)||z>zg(end)||~isfinite(z),error('Power:SOC','SOC outside asset');end
if numel(tg)==1
 if abs(T-tg)>1e-10,error('Power:Temperature','Temperature outside asset');end
 j=1;b=0;
else
 if T<tg(1)||T>tg(end),error('Power:Temperature','Temperature outside asset');end
 j=min(find(tg<=T,1,'last'),numel(tg)-1);b=(T-tg(j))/(tg(j+1)-tg(j));
end
k=min(find(zg<=z,1,'last'),numel(zg)-1);f=(z-zg(k))/(zg(k+1)-zg(k));
keys={'ocv_table','r0_table','r1_table','tau_table'};v=zeros(6,1);
for m=1:4
 tab=reshape(a.(keys{m}),numel(tg),numel(zg));
 low=(1-f)*tab(j,k)+f*tab(j,k+1);high=low;
 if numel(tg)>1,high=(1-f)*tab(j+1,k)+f*tab(j+1,k+1);end
 v(m)=(1-b)*low+b*high;
end
tab=reshape(a.ocv_table,numel(tg),numel(zg));
s0=(tab(j,k+1)-tab(j,k))/(zg(k+1)-zg(k));s1=s0;
if numel(tg)>1,s1=(tab(j+1,k+1)-tab(j+1,k))/(zg(k+1)-zg(k));end
v(5)=v(4)/v(3);v(6)=(1-b)*s0+b*s1;
end
