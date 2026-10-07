function [r,y,action]=protection_reference(r,p,x)
% Called only at an accepted test point / scheduled input boundary.
y=power_reference(r,p,x);action=0;
if strcmp(r.command,'trial_supply_loss')
    action=-1;return; % A trial command must not mutate the protection state.
end
if any(strcmp(r.command,{'stop','stop_start','repeat_stop'}))
    r.connected=0;action=1;
elseif strcmp(r.command,'supply_loss')
    if y(15)==1 && y(16)==1 && y(18)==4,r.connected=0;r.latched=1;action=2;
    else,action=-1;end
elseif strcmp(r.command,'start') && y(17)==1
    r.connected=1;r.latched=0;action=3;
end
if action>0,y=power_reference(r,p,x);end
end
