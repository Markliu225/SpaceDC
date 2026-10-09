function battery_sfun(block)
% Real continuous Simulink states. No Python calls or externally precomputed states.
block.NumDialogPrms=1;
block.NumInputPorts=0; block.NumOutputPorts=1;
block.OutputPort(1).Dimensions=9;block.OutputPort(1).DatatypeID=0;
block.OutputPort(1).Complexity='Real';block.OutputPort(1).SamplingMode='Sample';
block.NumContStates=4;block.SampleTimes=[0 0];
block.SimStateCompliance='DefaultSimState';
block.RegBlockMethod('InitializeConditions',@initialize);
block.RegBlockMethod('Outputs',@outputs);
block.RegBlockMethod('Derivatives',@derivatives);
end
function initialize(b)
c=b.DialogPrm(1).Data;b.ContStates.Data=c.x0(:);
end
function outputs(b)
c=b.DialogPrm(1).Data;x=b.ContStates.Data;
y=power_reference(c.row,c.p,[x(1);x(2);c.T]);
b.OutputPort(1).Data=[c.row.current;x(1:2);y(9);y(5);y(4);y(7);x(3:4)];
end
function derivatives(b)
global battery_derivative_times;
c=b.DialogPrm(1).Data;x=b.ContStates.Data;
y=power_reference(c.row,c.p,[x(1);x(2);c.T]);
b.Derivatives.Data=[y(21);y(22);y(4);y(7)];
battery_derivative_times(end+1,1)=b.CurrentTime;
end
