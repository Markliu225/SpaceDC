function ekf_sfun(b)
b.NumDialogPrms=1;b.NumInputPorts=1;b.NumOutputPorts=1;
b.InputPort(1).Dimensions=3;b.InputPort(1).DirectFeedthrough=true;
b.OutputPort(1).Dimensions=10;b.SampleTimes=[b.DialogPrm(1).Data.dt_s 0];
b.RegBlockMethod('PostPropagationSetup',@work);b.RegBlockMethod('InitializeConditions',@init);
b.RegBlockMethod('Outputs',@output);b.RegBlockMethod('Update',@update);
end
function work(b)
b.NumDworks=1;b.Dwork(1).Name='EstimateAndCovariance';b.Dwork(1).Dimensions=8;
b.Dwork(1).DatatypeID=0;b.Dwork(1).Complexity='Real';b.Dwork(1).UsedAsDiscState=true;
end
function init(b),P=diag([.01 .0001]);b.Dwork(1).Data=[.7;0;P(:);0;0];end
function output(b)
if strcmp(b.DialogPrm(1).Data.kind,'ekf')
 [o,~]=ekf_step(b.Dwork(1).Data,b.InputPort(1).Data,b.DialogPrm(1).Data);b.OutputPort(1).Data=o;
else,b.OutputPort(1).Data=zeros(10,1);end
end
function update(b)
if strcmp(b.DialogPrm(1).Data.kind,'ekf')
 [~,s]=ekf_step(b.Dwork(1).Data,b.InputPort(1).Data,b.DialogPrm(1).Data);b.Dwork(1).Data=s;
end
end
