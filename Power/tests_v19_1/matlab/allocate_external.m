function out=allocate_external(c,state,d,available,connected)
% External power solver: P13 is solved outside the pure battery equations.
if ~strcmp(c.kind,'allocation'),out=[d(1);0;0;0;1;0];return;end
a=asset_eval(c.asset,state(1),d(2));e=a(1)-state(2);N=c.n_series*c.n_parallel;
low=max(c.charge_limit_A,(e-c.v_max_V)/a(2));
high=min([c.discharge_limit_A,(e-c.v_min_V)/a(2),e/(2*a(2))]);
if state(1)<=c.asset.soc_grid(1),high=min(high,0);end
if state(1)>=c.asset.soc_grid(end),low=max(low,0);end
power=@(i) N*i*(e-a(2)*i);need=d(5)/c.distribution_efficiency*connected;
if connected && (low>high || power(high)<need-available-1e-8),connected=false;need=0;end
target=need-available;
if target<power(low)
 i=low;actual=need-power(i);
else
 if abs(target)<1e-13,i=0;else,i=fzero(@(i)power(i)-target,[low,high],optimset('TolX',1e-12));end
 actual=available;
end
load=need*c.distribution_efficiency;out=[i;actual;load;need-load;double(connected);need];
end
