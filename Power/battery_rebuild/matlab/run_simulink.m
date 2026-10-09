function run_simulink
here=fileparts(mfilename('fullpath'));root=fileparts(here);addpath(here);
Simulink.fileGenControl('set','CacheFolder',fullfile(root,'cache'),'CodeGenFolder',fullfile(root,'cache'),'createDir',true);
files=dir(fullfile(root,'fixtures','*.json'));model='sdtwin_battery_ekf_rls_1rc';
if bdIsLoaded(model),close_system(model,0);end
new_system(model);load_system('simulink');
cfg=jsondecode(fileread(fullfile(files(1).folder,files(1).name)));
cfg.data=readmatrix(fullfile(root,'fixtures',[cfg.id '.csv']));assignin('base','cfg',cfg);
add_block('simulink/User-Defined Functions/Level-2 MATLAB S-Function',[model '/One RC and joint EKF RLS'],...
 'FunctionName','ecm_observer_sfun','Parameters','cfg','Position',[180 120 480 250]);
add_block('simulink/Sinks/To Workspace',[model '/Recorded predictions and states'],...
 'VariableName','series','SaveFormat','Structure With Time','Position',[570 150 800 220]);
add_line(model,'One RC and joint EKF RLS/1','Recorded predictions and states/1');
set_param(model,'SolverType','Fixed-step','Solver','FixedStepDiscrete','FixedStep','0.1',...
 'ReturnWorkspaceOutputs','on','SaveTime','on','SaveOutput','off');
ann=Simulink.Annotation(model,sprintf('First-order ECM, EKF at 0.1 s, RLS at 1 s\nInput: measured current and voltage; output: prior voltage, SOC and parameters\nIndependent MATLAB equations. Custom Simulink model, not a Simscape Battery factory block.'));
ann.Position=[150 20];
meta=struct('matlab',version,'solver','FixedStepDiscrete','cases',{{}});
names={'time_s','current_A','measured_voltage_V','reference_soc','open_loop_voltage_V','prior_voltage_V',...
 'posterior_voltage_V','estimated_soc','polarization_V','r0_ohm','r1_ohm','tau_s','c1_F','innovation_V','rls_status','boundary_hits'};
for k=1:numel(files)
 cfg=jsondecode(fileread(fullfile(files(k).folder,files(k).name)));
 cfg.data=readmatrix(fullfile(root,'fixtures',[cfg.id '.csv']));assignin('base','cfg',cfg);
 set_param(model,'StopTime',num2str(cfg.data(end,1),17));tic;simout=sim(model);
 r=simout.series;out=[r.time,cfg.data(:,2:4),r.signals.values];
 writetable(array2table(out,'VariableNames',names),fullfile(root,'results',[cfg.id '_simulink.csv']));
 meta.cases{end+1}=struct('id',cfg.id,'rows',size(out,1),'seconds',toc);
 fprintf('%s %d rows\n',cfg.id,size(out,1));
end
cfg=jsondecode(fileread(fullfile(root,'fixtures','MEASURED_04.json')));
cfg.data=readmatrix(fullfile(root,'fixtures','MEASURED_04.csv'));assignin('base','cfg',cfg);
set_param(model,'StopTime',num2str(cfg.data(end,1),17));save(fullfile(here,'initial_config.mat'),'cfg');
set_param(model,'PostLoadFcn',"here=fileparts(get_param(bdroot,'FileName'));addpath(here);load(fullfile(here,'initial_config.mat'),'cfg');");
save_system(model,fullfile(here,[model '.slx']));close_system(model,0);
fid=fopen(fullfile(root,'results','simulink_execution.json'),'w');fwrite(fid,jsonencode(meta));fclose(fid);
end
