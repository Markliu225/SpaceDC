function ecm_observer_sfun(block)
block.NumDialogPrms=1;block.NumInputPorts=0;block.NumOutputPorts=1;
block.OutputPort(1).Dimensions=12;block.SampleTimes=[block.DialogPrm(1).Data.dt_s,0];
block.SimStateCompliance='DefaultSimState';
block.RegBlockMethod('PostPropagationSetup',@dwork);
block.RegBlockMethod('InitializeConditions',@initialize);
block.RegBlockMethod('Outputs',@outputs);block.RegBlockMethod('Update',@update);
end
function initialize(block)
block.Dwork(1).Data=ecm_state_codec(ecm_reference_init(block.DialogPrm(1).Data),block.DialogPrm(1).Data);
end
function dwork(block)
block.NumDworks=1;block.Dwork(1).Name='CausalState';block.Dwork(1).Dimensions=256;
block.Dwork(1).DatatypeID=0;block.Dwork(1).Complexity='Real';block.Dwork(1).UsedAsDiscState=true;
end
function outputs(block)
c=block.DialogPrm(1).Data;k=min(round(block.CurrentTime/c.dt_s)+1,size(c.data,1));
[out,~]=ecm_reference_step(ecm_state_codec(block.Dwork(1).Data,c),c.data(k,2),c.data(k,3),c);
block.OutputPort(1).Data=out;
end
function update(block)
c=block.DialogPrm(1).Data;k=min(round(block.CurrentTime/c.dt_s)+1,size(c.data,1));
[~,s]=ecm_reference_step(ecm_state_codec(block.Dwork(1).Data,c),c.data(k,2),c.data(k,3),c);block.Dwork(1).Data=ecm_state_codec(s,c);
end
