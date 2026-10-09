function [out,new]=ekf_step(old,input,c)
% Measurement input contains only current, voltage and temperature.
x=old(1:2);P=reshape(old(3:6),2,2);previous_i=old(7);has=old(8);
i=input(1);voltage=input(2);TK=input(3);par=asset_eval(c.asset,x(1),TK);a=exp(-.1/par(4));
if has
 x=[x(1)-previous_i*.1/(3600*c.asset.capacity_Ah);a*x(2)+par(3)*(1-a)*previous_i];
 A=diag([1 a]);P=A*P*A'+diag([1e-9 1e-7]);
end
v=asset_eval(c.asset,x(1),TK);prior=v(1)-par(2)*i-x(2);H=[v(6) -1];R=9e-6;
K=P*H'/(H*P*H'+R);innovation=voltage-prior;posterior=x+K*innovation;
M=eye(2)-K*H;Pn=M*P*M'+K*R*K';asset_eval(c.asset,posterior(1),TK);
out=[prior;posterior;innovation;Pn(1,1);Pn(1,2);Pn(2,1);Pn(2,2);x];
new=[posterior;Pn(:);i;1];
end
