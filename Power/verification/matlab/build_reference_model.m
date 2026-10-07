function model=build_reference_model(folder)
model='sdtwin_power_reference';
if bdIsLoaded(model),close_system(model,0);end
new_system(model,'Model');load_system('simulink');
add_block('simulink/User-Defined Functions/Level-2 MATLAB S-Function',[model '/Independent Power equations'],...
    'FunctionName','power_sfun','Parameters','cfg','Position',[170 130 420 235]);
add_block('simulink/Sinks/To Workspace',[model '/Comparison outputs'],...
    'VariableName','reference_series','SaveFormat','Structure With Time','Position',[510 145 650 190]);
add_line(model,'Independent Power equations/1','Comparison outputs/1');
set_param(model,'Solver','ode45','RelTol','1e-8','AbsTol','1e-10','MaxStep','10',...
    'ReturnWorkspaceOutputs','on','SaveTime','on','TimeSaveName','tout','SaveOutput','off');
a=Simulink.Annotation(model,['Independent MATLAB implementation of Power design P1-P11' newline ...
    'Simulink integrates electrode fractions and optional battery temperature' newline ...
    'Shared inputs only. No Python calls. Not a factory Simscape cell model.']);
a.Position=[145 30];
set_param(model,'PostLoadFcn',"addpath(fileparts(get_param('sdtwin_power_reference','FileName'))); initialize_reference;");
save_system(model,fullfile(folder,[model '.slx']));
end
