function allocation_sfun(b)
b.NumDialogPrms=1;b.NumInputPorts=3;b.NumOutputPorts=1;
for k=1:3,b.InputPort(k).DirectFeedthrough=true;end
b.InputPort(1).Dimensions=7;b.InputPort(2).Dimensions=2;b.InputPort(3).Dimensions=1;
b.OutputPort(1).Dimensions=6;b.SampleTimes=[0 0];
b.RegBlockMethod('PostPropagationSetup',@work);b.RegBlockMethod('InitializeConditions',@init);
b.RegBlockMethod('Outputs',@output);b.RegBlockMethod('Update',@update);
end
function work(b)
b.NumDworks=1;b.Dwork(1).Name='AcceptedLoadConnected';b.Dwork(1).Dimensions=1;
b.Dwork(1).DatatypeID=0;b.Dwork(1).Complexity='Real';b.Dwork(1).UsedAsDiscState=true;
end
function init(b),b.Dwork(1).Data=1;end
function output(b)
b.OutputPort(1).Data=allocate_external(b.DialogPrm(1).Data,b.InputPort(2).Data,b.InputPort(1).Data,b.InputPort(3).Data,logical(b.Dwork(1).Data));
end
function update(b)
o=allocate_external(b.DialogPrm(1).Data,b.InputPort(2).Data,b.InputPort(1).Data,b.InputPort(3).Data,logical(b.Dwork(1).Data));
b.Dwork(1).Data=o(5);
end
