function power_sfun(block)
% Continuous derivatives are integrated by Simulink, never by an M-file ODE call.
block.NumDialogPrms=1;cfg=block.DialogPrm(1).Data;
block.NumInputPorts=0;block.NumOutputPorts=1;
block.OutputPort(1).Dimensions=25;block.OutputPort(1).DatatypeID=0;
block.OutputPort(1).Complexity='Real';block.OutputPort(1).SamplingMode='Sample';
if strcmp(cfg.kind,'static')
    block.NumContStates=0;block.SampleTimes=[1 0];
else
    block.NumContStates=3;block.SampleTimes=[0 0];
    block.RegBlockMethod('InitializeConditions',@initialize);
    block.RegBlockMethod('Derivatives',@derivatives);
end
block.SimStateCompliance='DefaultSimState';
block.RegBlockMethod('Outputs',@outputs);
end
function initialize(b),c=b.DialogPrm(1).Data;b.ContStates.Data=c.x0(:);end
function outputs(b)
c=b.DialogPrm(1).Data;
if strcmp(c.kind,'static')
    k=min(numel(c.rows),floor(b.CurrentTime+1e-8)+1);r=c.rows(k);
    p=reference_parameters(c.asset,r.overrides);x=[r.xn;r.xp;r.T];
    if strcmp(r.command,'none'),y=power_reference(r,p,x);a=0;
    else,[~,y,a]=protection_reference(r,p,x);end
else
    y=power_reference(c.row,c.p,b.ContStates.Data);a=0;
end
b.OutputPort(1).Data=[y;a];
end
function derivatives(b)
c=b.DialogPrm(1).Data;x=b.ContStates.Data;y=power_reference(c.row,c.p,x);
if y(15)~=1 || y(16)~=0,error('PowerRef:unexpectedBoundary','Unexpected dynamic boundary at %.12g s',b.CurrentTime);end
dT=0;if c.thermal,dT=(y(7)-(x(3)-c.Tsink)/c.R)/c.C;end
b.Derivatives.Data=[y(21);y(22);dT];
end
