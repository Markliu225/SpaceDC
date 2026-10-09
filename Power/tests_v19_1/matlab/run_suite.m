function run_suite(selected)
here=fileparts(mfilename('fullpath'));root=fileparts(here);addpath(here);
Simulink.fileGenControl('set','CacheFolder',fullfile(root,'cache'),'CodeGenFolder',fullfile(root,'cache'),'createDir',true);
if nargin,ids=cellstr(selected);execution_file='simulink_execution_selected.json';else,ids=jsondecode(fileread(fullfile(root,'fixtures/index.json')));execution_file='simulink_execution.json';end
load_case(ids{1});model=build_model;
meta=struct('matlab',version,'simulink',ver('simulink'),'solver','ode45','relative_tolerance',1e-10,'absolute_tolerance',1e-12,'cases',{{}});
names={'time_s','current_A','soc','polarization_V','voltage_V','ocv_V','r0_ohm','r1_ohm','tau_s','c1_F',...
 'dsoc_dt','du1_dt','pack_voltage_V','pack_current_A','power_W','ohmic_heat_W','polarization_heat_W','heat_W',...
 'polarization_energy_J','available_solar_W','actual_solar_W','request_W','load_W','distribution_heat_W',...
 'power_residual_W','connected','measured_voltage_V','noise_V','heat_energy_J','port_loss_energy_J','cumulative_Ah'};
representatives={'PV01_TIME','BT01_4S2P_I+2','BT02','BT03','BT04_T25','BT05','BT06','BT07_P04','EK01','PA01'};
for k=1:numel(ids)
 id=ids{k};[c,data]=load_case(id);cb=sprintf("addpath(fileparts(get_param(bdroot,'FileName')));load_case('%s');",id);set_param(model,'PostLoadFcn',cb,'InitFcn',sprintf("load_case('%s');",id));tic;
 fprintf('START %s stop %.1f maxstep %.3g\n',id,c.stop_s,c.max_step_s);
 simout=sim(model);r=simout.series;t=r.time;x=r.signals.values;
 if size(x,1)~=size(data,1),error('Power:Rows','Saved time grid differs from input grid');end
 if max(abs(t-data(:,1)))>1e-7,error('Power:Time','Saved samples not aligned');end
 N=c.n_series*c.n_parallel;req=data(:,6);noise=x(:,29);
 if strcmp(c.project,'BT07'),measured=data(:,8);else,measured=x(:,10)+noise;end
 residual=zeros(size(t));if strcmp(c.kind,'allocation'),residual=x(:,23)+x(:,19)-x(:,24)-x(:,25);end
 out=[t,x(:,1:3),x(:,10),x(:,4:8),x(:,11:12),x(:,17:19),N*x(:,13:14),x(:,20:21),...
      x(:,28),x(:,23),req,x(:,24:25),residual,x(:,26),measured,noise,x(:,30:32)];
 writetable(array2table(out,'VariableNames',names),fullfile(root,'results',[id '_simulink.csv']));
 if strcmp(c.kind,'ekf')
  e=simout.estimator;en={'time_s','prior_voltage_V','estimated_soc','estimated_u1_V','innovation_V','P00','P01','P10','P11','prior_soc','prior_u1_V'};
  writetable(array2table([e.time,e.signals.values],'VariableNames',en),fullfile(root,'results/EK01_estimator_simulink.csv'));
 end
 save(fullfile(root,'results',[id '_raw_simulink.mat']),'simout','c','data','-v7');
 if strcmp(c.project,'BT06')
  ac=simout.accepted;ix=find(diff(ac.signals.values(:,1))>.3)+1;
  ev=struct('switch_time_s',ac.time(ix),'soc_at_switch',ac.signals.values(ix,2),'method','Native Simulink Relay zero crossing at SOC 0.88; polarization continuous');
  writejson(fullfile(root,'results/BT06_reversal_event.json'),ev);
  near=find(abs(ac.time-27360)<1e-4);
  writematrix([ac.time(near),ac.signals.values(near,:)],fullfile(root,'results/BT06_native_event_samples.csv'));
 end
 meta.cases{end+1}=struct('id',id,'rows',numel(t),'seconds',toc,'max_step_s',c.max_step_s,'stop_s',c.stop_s,'continuous_integrators',5);
 writejson(fullfile(root,'results',execution_file),meta);
 if ismember(id,representatives)
  save_system(model,fullfile(here,[model '.slx']));copyfile(fullfile(here,[model '.slx']),fullfile(here,[c.project '.slx']));
 end
 fprintf('DONE %s %d rows in %.1f s\n',id,numel(t),meta.cases{end}.seconds);
end
% Default interactive model is the short discharge pulse.
load_case('BT02');cb="addpath(fileparts(get_param(bdroot,'FileName')));load_case('BT02');";set_param(model,'PostLoadFcn',cb,'InitFcn',cb);save_system(model,fullfile(here,[model '.slx']));
print(['-s' model],'-dpng','-r130',fullfile(root,'figures/simulink_system.png'));
print(['-s' model '/Battery ECM equations'],'-dpng','-r150',fullfile(root,'figures/simulink_ecm.png'));
close_system(model,0);
% Table nodes and centres evaluated independently in MATLAB.
asset=jsondecode(fileread(fullfile(root,'fixtures/asset_B.json')));tab=[];
for T=[0 12.5 25 37.5 50]
 for z=[.1 .3 .5 .7 .9],tab(end+1,:)=[z,T,asset_eval(asset,z,T+273.15)'];end
end
writetable(array2table(tab,'VariableNames',{'soc','temperature_C','ocv_V','r0_ohm','r1_ohm','tau_s','c1_F','slope'}),fullfile(root,'results/BT04_lookup_matlab.csv'));
end
function writejson(path,value)
f=fopen(path,'w');fwrite(f,jsonencode(value));fclose(f);
end
