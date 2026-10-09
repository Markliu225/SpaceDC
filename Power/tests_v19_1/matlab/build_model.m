function model=build_model
model='sdtwin_power_v191';if bdIsLoaded(model),close_system(model,0);end
new_system(model);load_system('simulink');
add(model,'Sources/From Workspace','Physical inputs',[30 160 170 210],'VariableName','input_data','SampleTime','cfg.dt_s','Interpolate','off','OutputAfterFinalValue','Holding final value');
add(model,'Signal Routing/Demux','Input channels',[205 130 210 440],'Outputs','7');
wire(model,'Physical inputs/1','Input channels/1');
add(model,'Signal Routing/Mux','Solar input',[250 485 255 535],'Inputs','2');
wire(model,'Input channels/3','Solar input/1');wire(model,'Input channels/4','Solar input/2');
add(model,'User-Defined Functions/Fcn','Solar upper power P2',[290 485 490 535],...
 'Expr','u(1)*0.5*(u(2)+abs(u(2)))*solar_gain');wire(model,'Solar input/1','Solar upper power P2/1');
add(model,'User-Defined Functions/Level-2 MATLAB S-Function','External power solver',[330 50 570 120],...
 'FunctionName','allocation_sfun','Parameters','cfg');
wire(model,'Physical inputs/1','External power solver/1');wire(model,'Solar upper power P2/1','External power solver/3');
add(model,'Signal Routing/Demux','Allocation channels',[600 30 605 130],'Outputs','6');wire(model,'External power solver/1','Allocation channels/1');
add(model,'Ports & Subsystems/Subsystem','Battery ECM equations',[680 200 900 350]);
s=[model '/Battery ECM equations'];delete_line(s,'In1/1','Out1/1');delete_block([s '/In1']);delete_block([s '/Out1']);
build_cell(s);
add(model,'User-Defined Functions/Fcn','SOC for cycle reversal',[350 290 500 325],'Expr','u(1)');
wire(model,'Battery ECM equations/2','SOC for cycle reversal/1');
add(model,'Discontinuities/Relay','SOC triggered cycle current',[360 355 535 400],...
 'OnSwitchValue','0.88','OffSwitchValue','0.1','OnOutputValue','0.2','OffOutputValue','-0.2');
wire(model,'SOC for cycle reversal/1','SOC triggered cycle current/1');
add(model,'Sources/Constant','Cycle case',[420 235 480 265],'Value',"double(strcmp(cfg.project,'BT06'))");
add(model,'Signal Routing/Switch','Applied cell current',[580 210 625 275],'Threshold','0.5');
wire(model,'SOC triggered cycle current/1','Applied cell current/1');wire(model,'Cycle case/1','Applied cell current/2');wire(model,'Allocation channels/1','Applied cell current/3');
wire(model,'Applied cell current/1','Battery ECM equations/1');wire(model,'Input channels/2','Battery ECM equations/2');
wire(model,'Battery ECM equations/2','External power solver/2');
add(model,'User-Defined Functions/Fcn','Cell voltage',[950 390 1090 420],'Expr','u(10)');wire(model,'Battery ECM equations/1','Cell voltage/1');
add(model,'Math Operations/Sum','Measured voltage',[1140 400 1160 435],'Inputs','++');
wire(model,'Cell voltage/1','Measured voltage/1');wire(model,'Input channels/6','Measured voltage/2');
add(model,'Signal Routing/Mux','Estimator measurement only',[1210 345 1215 440],'Inputs','3');
wire(model,'Allocation channels/1','Estimator measurement only/1');wire(model,'Measured voltage/1','Estimator measurement only/2');wire(model,'Input channels/2','Estimator measurement only/3');
add(model,'User-Defined Functions/Level-2 MATLAB S-Function','EKF P11 P12',[1260 350 1450 430],'FunctionName','ekf_sfun','Parameters','cfg');
wire(model,'Estimator measurement only/1','EKF P11 P12/1');
add(model,'Sinks/To Workspace','Estimator history',[1510 365 1680 415],'VariableName','estimator','SaveFormat','Structure With Time','SampleTime','cfg.dt_s');wire(model,'EKF P11 P12/1','Estimator history/1');
% Native continuous integration of heat and source-to-port energy difference.
names={'Pack heat','Internal power difference','Absolute current Ah rate'};
expr={'u(20)','pack_count*u(1)*(u(4)-u(10))','abs(u(1))/3600'};
for k=1:3
 y=580+80*(k-1);add(model,'User-Defined Functions/Fcn',names{k},[700 y 940 y+35],'Expr',expr{k});wire(model,'Battery ECM equations/1',[names{k} '/1']);
 add(model,'Continuous/Integrator',['Integral ' num2str(k)],[1000 y 1050 y+40],'InitialCondition','0');wire(model,[names{k} '/1'],['Integral ' num2str(k) '/1']);
end
add(model,'Signal Routing/Mux','Complete trace',[1170 560 1175 800],'Inputs','7');
wire(model,'Battery ECM equations/1','Complete trace/1');wire(model,'External power solver/1','Complete trace/2');
wire(model,'Solar upper power P2/1','Complete trace/3');wire(model,'Input channels/6','Complete trace/4');
for k=1:3,wire(model,['Integral ' num2str(k) '/1'],['Complete trace/' num2str(k+4)]);end
add(model,'Sinks/To Workspace','Full physical history',[1290 600 1480 650],'VariableName','series','SaveFormat','Structure With Time','SampleTime','cfg.dt_s');wire(model,'Complete trace/1','Full physical history/1');
add(model,'Sinks/To Workspace','Accepted solver steps',[1290 700 1480 750],'VariableName','accepted','SaveFormat','Structure With Time','SampleTime','-1');wire(model,'Complete trace/1','Accepted solver steps/1');
add(model,'Sinks/Scope','Battery voltage and states',[1000 220 1080 290],'NumInputPorts','3');
wire(model,'Applied cell current/1','Battery voltage and states/1');wire(model,'Cell voltage/1','Battery voltage and states/2');wire(model,'Battery ECM equations/2','Battery voltage and states/3');
sc=get_param([model '/Battery voltage and states'],'ScopeConfiguration');sc.LayoutDimensions=[3 1];
add(model,'Sinks/Scope','Power allocation',[670 55 750 105]);wire(model,'External power solver/1','Power allocation/1');
set_param(model,'SolverType','Variable-step','Solver','ode45','MaxStep','cfg.max_step_s','RelTol','1e-10','AbsTol','1e-12',...
 'StopTime','cfg.stop_s','ReturnWorkspaceOutputs','on','SaveOutput','off','SaveTime','on',...
 'PostLoadFcn',"addpath(fileparts(get_param(bdroot,'FileName')));load_case('BT02');");
a=Simulink.Annotation(model,sprintf('Power design v19.1: 1RC ECM + read-only asset tables + EKF\nContinuous physical states: native Simulink Integrators, ode45. EKF: 0.1 s. No RLS.\nInput columns: current, temperature, irradiance, incidence cosine, requested power, voltage noise, measured voltage.\nOpen Battery ECM equations to inspect P5-P9. Independent MATLAB reference; no Python callbacks.'));
a.Position=[30 850];set_param(model,'ZoomFactor','FitSystem');
end
function build_cell(s)
add(s,'Ports & Subsystems/In1','Current A',[25 60 55 80],'Port','1');
add(s,'Ports & Subsystems/In1','Temperature K',[25 170 55 190],'Port','2');
add(s,'Continuous/Integrator','SOC z',[280 55 325 95],'InitialCondition','cfg.initial(1)');
add(s,'Continuous/Integrator','Polarization u1',[280 290 325 330],'InitialCondition','cfg.initial(2)');
add(s,'Signal Routing/Mux','SOC and temperature',[380 115 385 170],'Inputs','2');wire(s,'SOC z/1','SOC and temperature/1');wire(s,'Temperature K/1','SOC and temperature/2');
add(s,'User-Defined Functions/Level-2 MATLAB S-Function','Read only table P8',[430 110 620 170],'FunctionName','table_sfun','Parameters','cfg');wire(s,'SOC and temperature/1','Read only table P8/1');
add(s,'Signal Routing/Mux','Equation inputs',[670 50 675 330],'Inputs','4');
wire(s,'Current A/1','Equation inputs/1');wire(s,'SOC z/1','Equation inputs/2');wire(s,'Polarization u1/1','Equation inputs/3');wire(s,'Read only table P8/1','Equation inputs/4');
names={'SOC derivative P5','Polarization derivative P6','Terminal voltage P7','Ohmic heat','Polarization heat','RC stored energy'};
expr={'-u(1)/(3600*capacity_Ah)','-u(3)/u(7)+u(1)*u(6)/u(7)','u(4)-u(5)*u(1)-u(3)','u(1)^2*u(5)','u(3)^2/u(6)','0.5*u(8)*u(3)^2'};
for k=1:6
 y=45+70*(k-1);add(s,'User-Defined Functions/Fcn',names{k},[750 y 970 y+35],'Expr',expr{k});wire(s,'Equation inputs/1',[names{k} '/1']);
end
add(s,'Math Operations/Gain','Enable SOC dynamics',[140 30 215 65],'Gain','double(~cfg.freeze)');wire(s,'SOC derivative P5/1','Enable SOC dynamics/1');wire(s,'Enable SOC dynamics/1','SOC z/1');
add(s,'Math Operations/Gain','Enable RC dynamics',[140 260 215 295],'Gain','double(~cfg.freeze)');wire(s,'Polarization derivative P6/1','Enable RC dynamics/1');wire(s,'Enable RC dynamics/1','Polarization u1/1');
add(s,'Math Operations/Sum','Cell heat P9',[1030 275 1060 310],'Inputs','++');wire(s,'Ohmic heat/1','Cell heat P9/1');wire(s,'Polarization heat/1','Cell heat P9/2');
add(s,'Math Operations/Gain','Pack voltage',[1100 60 1200 90],'Gain','cfg.n_series');wire(s,'Terminal voltage P7/1','Pack voltage/1');
add(s,'Math Operations/Gain','Pack current',[1100 120 1200 150],'Gain','cfg.n_parallel');wire(s,'Current A/1','Pack current/1');
add(s,'Math Operations/Product','Pack power P4',[1240 85 1270 125]);wire(s,'Pack voltage/1','Pack power P4/1');wire(s,'Pack current/1','Pack power P4/2');
add(s,'Math Operations/Gain','Pack heat P9',[1100 280 1200 310],'Gain','cfg.n_series*cfg.n_parallel');wire(s,'Cell heat P9/1','Pack heat P9/1');
add(s,'Math Operations/Gain','Pack stored energy',[1100 365 1200 400],'Gain','cfg.n_series*cfg.n_parallel');wire(s,'RC stored energy/1','Pack stored energy/1');
add(s,'Signal Routing/Mux','Response vector',[1340 40 1345 470],'Inputs','13');
ports={'Equation inputs/1','Terminal voltage P7/1','SOC derivative P5/1','Polarization derivative P6/1','Ohmic heat/1','Polarization heat/1','Cell heat P9/1','RC stored energy/1','Pack voltage/1','Pack current/1','Pack power P4/1','Pack heat P9/1','Pack stored energy/1'};
for k=1:numel(ports),wire(s,ports{k},['Response vector/' num2str(k)]);end
% Equation inputs has 9 elements, so response vector is 21 elements.
add(s,'Ports & Subsystems/Out1','Physical outputs',[1400 200 1430 220],'Port','1');wire(s,'Response vector/1','Physical outputs/1');
add(s,'Signal Routing/Mux','Continuous states',[380 380 385 430],'Inputs','2');wire(s,'SOC z/1','Continuous states/1');wire(s,'Polarization u1/1','Continuous states/2');
add(s,'Ports & Subsystems/Out1','States for allocation',[430 395 460 415],'Port','2');wire(s,'Continuous states/1','States for allocation/1');
a=Simulink.Annotation(s,sprintf('SOC and u1 are continuous states. No state clipping or reset at current reversals.\nTable output order: OCV, R0, R1, tau, C1, dOCV/dSOC.\nAll voltage, derivative, heat and pack calculations below are native Simulink arithmetic blocks.'));a.Position=[30 520];
end
function add(m,lib,name,pos,varargin),add_block(['simulink/' lib],[m '/' name],'Position',pos,varargin{:});end
function wire(m,a,b),add_line(m,a,b,'autorouting','on');end
