function run_full_cycles_simulink
% Built-in continuous State-Space and Integrator blocks; compiled algebraic Fcn blocks.
% Independent MATLAB construction of material equations. No Python state or voltage input.
here=fileparts(mfilename('fullpath'));root=fileparts(here);out=fullfile(root,'results','full_cycles');
addpath(here);addpath(fullfile(root,'..','verification','matlab'));
Simulink.fileGenControl('set','CacheFolder',fullfile(root,'cache'),'CodeGenFolder',fullfile(root,'cache'),'createDir',true);
c=jsondecode(fileread(fullfile(out,'contract.json')));p=reference_parameters(c.parameters,struct());
model='sdtwin_battery_full_cycles';if bdIsLoaded(model),close_system(model,0);end
new_system(model);load_system('simulink');
assignin('base','command_current',c.current_magnitude_A);
assignin('base','initial_state',[c.initial_xn;c.initial_xp]);assignin('base','initial_energy',[0;0]);
add_block('simulink/Sources/Constant',[model '/Command current'],'Value','command_current','Position',[40 190 95 225]);
add_block('simulink/Continuous/State-Space',[model '/Electrode fractions'],...
 'A','zeros(2)','B',mat2str([-1/p.Qn;1/p.Qp],17),'C','eye(2)','D','zeros(2,1)',...
 'X0','initial_state','Position',[160 95 275 155]);
add_block('simulink/Signal Routing/Mux',[model '/Concentrations and current'],'Inputs','2','Position',[320 110 325 205]);
an=p.n.radius_m^2/(15*p.n.D_ref_m2_s*p.Qn);ap=p.p.radius_m^2/(15*p.p.D_ref_m2_s*p.Qp);
sn=sprintf('(u(1)-%.17g*u(3))',an);sp=sprintf('(u(2)+%.17g*u(3))',ap);
un=polynomial(p.n.b_V,sn);up=polynomial(p.p.b_V,sp);
jn=sprintf('(%.17g*sqrt(%s*(1-%s)))',2*p.n.I0_ref_A,sn,sn);
jp=sprintf('(%.17g*sqrt(%s*(1-%s)))',2*p.p.I0_ref_A,sp,sp);
zn=['(u(3)/(2*' jn '))'];zp=['(u(3)/(2*' jp '))'];
activation=sprintf('(%.17g*(%s+%s))',2*8.314462618*c.temperature_K/96485.33212,inverse_sinh(zn),inverse_sinh(zp));
voltage=sprintf('(%s-%s-%s-%.17g*u(3))',up,un,activation,p.Rohm);
beta=['(' polynomial(p.p.d_V_K,sp) '-' polynomial(p.n.d_V_K,sn) ')'];
heat=sprintf('(u(3)*%s+%.17g*u(3)^2-u(3)*%.17g*%s)',activation,p.Rohm,c.temperature_K,beta);
add_block('simulink/User-Defined Functions/Fcn',[model '/Terminal voltage'],'Expr',voltage,'Position',[375 95 550 140]);
add_block('simulink/User-Defined Functions/Fcn',[model '/Reaction ohmic reversible heat'],'Expr',heat,'Position',[375 195 550 245]);
add_block('simulink/Math Operations/Product',[model '/Terminal power'],'Inputs','**','Position',[590 130 625 175]);
add_block('simulink/Signal Routing/Mux',[model '/Power and heat'],'Inputs','2','Position',[660 135 665 220]);
add_block('simulink/Continuous/Integrator',[model '/Energy integrals'],'InitialCondition','initial_energy','Position',[720 135 790 195]);
add_block('simulink/Signal Routing/Mux',[model '/All outputs'],'Inputs','6','Position',[850 65 855 310]);
add_block('simulink/Sinks/To Workspace',[model '/Time series'],'VariableName','cycle_series',...
 'SaveFormat','Structure With Time','Position',[905 155 1040 205]);
add_line(model,'Command current/1','Electrode fractions/1','autorouting','on');
add_line(model,'Electrode fractions/1','Concentrations and current/1','autorouting','on');
add_line(model,'Command current/1','Concentrations and current/2','autorouting','on');
add_line(model,'Concentrations and current/1','Terminal voltage/1','autorouting','on');
add_line(model,'Concentrations and current/1','Reaction ohmic reversible heat/1','autorouting','on');
add_line(model,'Terminal voltage/1','Terminal power/1','autorouting','on');
add_line(model,'Command current/1','Terminal power/2','autorouting','on');
add_line(model,'Terminal power/1','Power and heat/1','autorouting','on');
add_line(model,'Reaction ohmic reversible heat/1','Power and heat/2','autorouting','on');
add_line(model,'Power and heat/1','Energy integrals/1','autorouting','on');
sources={'Electrode fractions/1','Command current/1','Terminal voltage/1','Reaction ohmic reversible heat/1','Terminal power/1','Energy integrals/1'};
for n=1:numel(sources),add_line(model,sources{n},['All outputs/' num2str(n)],'autorouting','on');end
add_line(model,'All outputs/1','Time series/1');
set_param(model,'SolverType','Variable-step','Solver','ode45','RelTol','1e-9','AbsTol','1e-11',...
 'MaxStep','1','ReturnWorkspaceOutputs','on','SaveTime','on','TimeSaveName','tout','SaveOutput','off');
annotation=Simulink.Annotation(model,['Single cell, 25 C, 0.1C; maximum integration step 1 s' newline ...
 'Continuous states: electrode fractions and energy integrals' newline ...
 'Same material equations independently assembled with built-in Simulink blocks']);
annotation.Position=[70 5];
meta=struct('matlab',version,'solver','Simulink ode45','maximum_step_s',1,'simscape',false,'segments',{{}});
x=[c.initial_xn;c.initial_xp];energy=[0;0];
for j=0:5
 start=j*36000;stop=(j+1)*36000;current=c.current_magnitude_A*(-1)^j;
 assignin('base','command_current',current);assignin('base','initial_state',x);assignin('base','initial_energy',energy);
 set_param(model,'StartTime',num2str(start),'StopTime',num2str(stop),'OutputOption','SpecifiedOutputTimes',...
  'OutputTimes',sprintf('%d:1:%d',start,stop));
 fprintf('START full-cycle segment %d\n',j+1);clock=tic;simout=sim(model);r=simout.cycle_series;v=double(r.signals.values);
 soc=(v(:,1)-p.xn0)/(p.xn100-p.xn0);capacity=abs(current)*(r.time-start)/3600;
 data=[r.time,repmat(j,numel(r.time),1),repmat(floor(j/2)+1,numel(r.time),1),v(:,3),capacity,soc,v(:,1:2),v(:,4),v(:,6),v(:,5),v(:,7:8)];
 names={'time_s','segment','cycle','current_A','capacity_Ah','soc','xn','xp','voltage_V','power_W','heat_W','energy_port_J','energy_heat_J'};
 writetable(array2table(data,'VariableNames',names),fullfile(out,sprintf('segment_%d_simulink.csv',j+1)));
 meta.segments{end+1}=struct('segment',j,'initial_state',x,'final_state',v(end,1:2)',...
  'output_rows',size(data,1),'seconds',toc(clock));
 x=v(end,1:2)';energy=v(end,7:8)';
 fprintf('DONE segment %d rows=%d seconds=%.2f\n',j+1,size(data,1),toc(clock));
end
command_current=c.current_magnitude_A;initial_state=[c.initial_xn;c.initial_xp];initial_energy=[0;0];
save(fullfile(here,'full_cycle_initial_config.mat'),'command_current','initial_state','initial_energy');
set_param(model,'StartTime','0','StopTime','36000','OutputTimes','0:1:36000',...
 'PostLoadFcn',"load(fullfile(fileparts(get_param(bdroot,'FileName')),'full_cycle_initial_config.mat'));");
save_system(model,fullfile(here,[model '.slx']));close_system(model,0);
fid=fopen(fullfile(out,'simulink_execution.json'),'w');fwrite(fid,jsonencode(meta),'char');fclose(fid);
end
function out=polynomial(coeff,x)
out=num2str(coeff(end),17);
for j=numel(coeff)-1:-1:1,out=['(' out '*' x '+' num2str(coeff(j),17) ')'];end
end
function out=inverse_sinh(x)
out=['log(' x '+sqrt(' x '^2+1))'];
end
