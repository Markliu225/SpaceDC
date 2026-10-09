function run_battery_simulink
here=fileparts(mfilename('fullpath'));root=fileparts(here);out=fullfile(root,'results');
addpath(here);addpath(fullfile(root,'..','verification','matlab'));
Simulink.fileGenControl('set','CacheFolder',fullfile(root,'cache'),'CodeGenFolder',fullfile(root,'cache'),'createDir',true);
c=jsondecode(fileread(fullfile(out,'contract.json')));
p=reference_parameters(c.parameters,struct());
initial_row=struct('mode','battery','G',0,'cosine',1,'request',0,...
 'connected',1,'latched',0,'bad','none','current',0);
cfg=struct('row',initial_row,'p',p,'T',c.initial.temperature_K,...
 'x0',[c.initial.xn;c.initial.xp;0;0]);
assignin('base','cfg',cfg);
model='sdtwin_battery_time_validation';
if bdIsLoaded(model),close_system(model,0);end
new_system(model);load_system('simulink');
add_block('simulink/User-Defined Functions/Level-2 MATLAB S-Function',[model '/Continuous battery states'],...
 'FunctionName','battery_sfun','Parameters','cfg','Position',[180 130 450 240]);
add_block('simulink/Sinks/To Workspace',[model '/Battery time history'],...
 'VariableName','battery_series','SaveFormat','Structure With Time','Position',[540 145 710 200]);
add_line(model,'Continuous battery states/1','Battery time history/1');
set_param(model,'SolverType','Variable-step','Solver','ode45','RelTol',num2str(c.numerics.rtol,17),...
 'AbsTol',num2str(c.numerics.atol,17),'MaxStep',num2str(c.numerics.max_step_s),...
 'ReturnWorkspaceOutputs','on','SaveTime','on','TimeSaveName','tout','SaveOutput','off');
annotation=Simulink.Annotation(model,['Prescribed current, 25 C, one cell' newline ...
 'Continuous states: negative/positive mean fraction, terminal energy, heat integral' newline ...
 'Independent MATLAB implementation of project equations. Not a Simscape factory cell.']);
annotation.Position=[120 30];
meta=struct('matlab',version,'solver','Simulink ode45','simscape',false,'cases',{{}});
global battery_derivative_times;
for k=1:numel(c.cases)
 test=c.cases(k);data=[];evaluations=[];x=[c.initial.xn;c.initial.xp;0;0];segments={};clock=tic;
 fprintf('START %s\n',test.id);
 for j=1:numel(test.segments)
  s=test.segments(j);row=struct('mode','battery','G',0,'cosine',1,'request',0,...
      'connected',1,'latched',0,'bad','none','current',s.current_A);
  cfg=struct('row',row,'p',p,'T',c.initial.temperature_K,'x0',x);
  assignin('base','cfg',cfg);times=s.start_s:c.numerics.output_interval_s:s.end_s;
  set_param(model,'StartTime',num2str(s.start_s),'StopTime',num2str(s.end_s),...
   'OutputOption','SpecifiedOutputTimes','OutputTimes',mat2str(times,17));
  battery_derivative_times=[];simout=sim(model);r=simout.battery_series;
  vals=double(r.signals.values);data=[data;r.time,repmat(j-1,numel(r.time),1),vals];
  evaluations=[evaluations;repmat(j-1,numel(battery_derivative_times),1),battery_derivative_times];
  next=vals(end,[2 3 8 9])';
  segments{end+1}=struct('segment',j-1,'derivative_evaluations',numel(battery_derivative_times),...
   'start_state',x,'end_state',next);
  x=next;
 end
 names={'time_s','segment','current_A','xn','xp','soc','voltage_V','power_W','heat_W','energy_port_J','energy_heat_J'};
 writetable(array2table(data,'VariableNames',names),fullfile(out,[test.id '_simulink.csv']));
 writetable(array2table(evaluations,'VariableNames',{'segment','evaluation_time_s'}),fullfile(out,[test.id '_simulink_derivatives.csv']));
 meta.cases{end+1}=struct('id',test.id,'output_rows',size(data,1),'segments',{segments},'seconds',toc(clock));
 fprintf('DONE %s rows=%d seconds=%.2f\n',test.id,size(data,1),toc(clock));
end
% Save a reproducible initial configuration, not the last case's terminal state.
cfg.x0=[c.initial.xn;c.initial.xp;0;0];cfg.row.current=-0.5;assignin('base','cfg',cfg);
save(fullfile(here,'initial_config.mat'),'cfg');
set_param(model,'StartTime','0','StopTime','1800','OutputTimes','0:1:1800',...
 'PostLoadFcn',"here=fileparts(get_param(bdroot,'FileName')); addpath(here); addpath(fullfile(here,'..','..','verification','matlab')); load(fullfile(here,'initial_config.mat'),'cfg');");
save_system(model,fullfile(here,[model '.slx']));close_system(model,0);
fid=fopen(fullfile(out,'simulink_execution.json'),'w');fwrite(fid,jsonencode(meta),'char');fclose(fid);
end
