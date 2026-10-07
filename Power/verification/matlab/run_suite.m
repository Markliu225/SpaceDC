function run_suite(selected)
if nargin<1,selected='';end
here=fileparts(mfilename('fullpath'));addpath(here);out=fullfile(here,'..','results');
suite=jsondecode(fileread(fullfile(out,'suite.json')));
assignin('base','cfg',struct('kind','static','asset',suite.parameters,'rows',suite.cases(1).rows));
model=build_reference_model(here);
meta=struct('matlab',version,'solver','Simulink ode45','reference','Independent MATLAB P1-P11 S-function',...
    'simscape',false,'cases',{{}});started=tic;
for k=1:numel(suite.cases)
    c=suite.cases(k);if ~isempty(selected)&&~strcmp(c.id,selected),continue;end
    fprintf('START %s\n',c.id);clock=tic;
    try
        if strcmp(c.kind,'static')
            cfg=struct('kind','static','asset',suite.parameters,'rows',c.rows);
            assignin('base','cfg',cfg);
            set_param(model,'SolverType','Fixed-step','Solver','FixedStepDiscrete','FixedStep','1',...
                'StartTime','0','StopTime',num2str(numel(c.rows)-1),'OutputOption','RefineOutputTimes');
            simout=sim(model);r=simout.reference_series;
            data=[r.time,double(r.signals.values)];ev=[];
        else
            [data,ev]=dynamic_case(model,c,suite,false);
            if strcmp(c.id,'NU-001')
                [fine,~]=dynamic_case(model,c,suite,true);
                write_csv(fullfile(out,[c.id '_simulink_fine.csv']),fine,suite.fields);
            end
        end
        write_csv(fullfile(out,[c.id '_simulink.csv']),data,suite.fields);
        fid=fopen(fullfile(out,[c.id '_simulink_events.json']),'w');fwrite(fid,jsonencode(ev),'char');fclose(fid);
        meta.cases{end+1}=struct('id',c.id,'status','executed','seconds',toc(clock),'samples',size(data,1));
        fprintf('DONE %s samples=%d seconds=%.2f\n',c.id,size(data,1),toc(clock));
    catch err
        meta.cases{end+1}=struct('id',c.id,'status','error','message',err.message);
        fprintf('ERROR %s %s\n',c.id,getReport(err,'extended','hyperlinks','off'));
    end
end
meta.seconds=toc(started);fid=fopen(fullfile(out,'simulink_execution.json'),'w');fwrite(fid,jsonencode(meta),'char');fclose(fid);
save_system(model);close_system(model,0);
end

function [data,events]=dynamic_case(model,c,suite,fine)
ini=suite.scene.initial_state;x=[ini.x_n;ini.x_p;ini.T_B_K];if isfield(c,'T0')&&~isempty(c.T0),x(3)=c.T0;end
p=reference_parameters(suite.parameters,c.overrides);connected=1;latched=0;start=0;data=[];events=struct('time_s',{},'action',{},'connected',{},'latched',{});
for j=1:numel(c.segments)
    s=c.segments(j);r=struct('G',s.G,'cosine',s.cosine,'request',s.request,'T',x(3),...
        'connected',connected,'latched',latched,'current',0,'mode','allocate','command',s.command,'bad','none');
    [r,y,action]=protection_reference(r,p,x);
    if y(15)~=1,error('PowerRef:invalid','Invalid segment start');end
    if y(16)==1
        if y(18)~=4,error('PowerRef:boundary','Unexpected device boundary');end
        r.command='supply_loss';[r,~,action]=protection_reference(r,p,x);
    end
    connected=r.connected;latched=r.latched;
    if action~=0,events(end+1)=struct('time_s',start,'action',action,'connected',connected,'latched',latched);end
    cfg=struct('kind','dynamic','row',r,'p',p,'x0',x,'thermal',c.thermal,'C',1,'R',1,'Tsink',x(3));
    if c.thermal,cfg.C=c.C;cfg.R=c.R;cfg.Tsink=c.Tsink;end
    assignin('base','cfg',cfg);times=unique([start:c.step:s.end,s.end]);
    rt=suite.numerics.rtol;at=suite.numerics.atol;mx=suite.numerics.max_step_s;
    if fine,rt=suite.numerics.refinement_rtol;at=suite.numerics.refinement_atol;mx=suite.numerics.refinement_max_step_s;end
    set_param(model,'SolverType','Variable-step','Solver','ode45','RelTol',num2str(rt,17),'AbsTol',num2str(at,17),...
        'MaxStep',num2str(mx),'StartTime',num2str(start),'StopTime',num2str(s.end),...
        'OutputOption','SpecifiedOutputTimes','OutputTimes',mat2str(times,17));
    simout=sim(model);raw=simout.reference_series;d=[raw.time,double(raw.signals.values)];
    % Preserve both sides of a scheduled discontinuity at the same time.
    data=[data;d];x=d(end,[11,12,13])';start=s.end;
end
end
function write_csv(path,data,fields)
names=[{'time_s'};fields(:);{'action'}];T=array2table(data,'VariableNames',names);writetable(T,path);
end
