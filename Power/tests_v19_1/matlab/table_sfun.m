function table_sfun(b)
b.NumDialogPrms=1;b.NumInputPorts=1;b.NumOutputPorts=1;
b.InputPort(1).Dimensions=2;b.InputPort(1).DirectFeedthrough=true;
b.OutputPort(1).Dimensions=6;b.SampleTimes=[0 0];
b.RegBlockMethod('Outputs',@out);
end
function out(b)
x=b.InputPort(1).Data;b.OutputPort(1).Data=asset_eval(b.DialogPrm(1).Data.asset,x(1),x(2));
end
