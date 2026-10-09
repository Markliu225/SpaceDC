function out=ecm_state_codec(value,cfg)
names={'x','P','theta','S','r0','r1','tau','fdy','fdi','n','dE','hits','plant','rlsE'};
packing=isstruct(value);k=1;
if packing,s=value;out=zeros(256,1);else,s=ecm_reference_init(cfg);end
for j=1:numel(names)
 name=names{j};n=numel(s.(name));
 if packing,out(k:k+n-1)=s.(name)(:);else,s.(name)=reshape(value(k:k+n-1),size(s.(name)));end
 k=k+n;
end
for name={'prev','rprev'}
 field=name{1};
 if packing
  out(k)=~isempty(s.(field));if out(k),out(k+1:k+2)=s.(field);end
 else
  if value(k),s.(field)=value(k+1:k+2)';else,s.(field)=[];end
 end
 k=k+3;
end
if packing
 out(k)=numel(s.currents);out(k+1:k+numel(s.currents))=s.currents;
else
 s.currents=value(k+1:k+round(value(k)))';out=s;
end
end
