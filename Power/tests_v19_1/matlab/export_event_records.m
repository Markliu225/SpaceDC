function export_event_records
root=fileparts(fileparts(mfilename('fullpath')));
for id={'BT02','BT03'}
 s=load(fullfile(root,'results',[id{1} '_raw_simulink.mat']),'simout');a=s.simout.accepted;
 ix=find(abs(diff(a.signals.values(:,1)))>1)+1;out=[];
 for k=ix'
  out=[out; a.time(k-1),-1,a.signals.values(k-1,1:3),a.signals.values(k-1,10);...
            a.time(k),1,a.signals.values(k,1:3),a.signals.values(k,10)];
 end
 writetable(array2table(out,'VariableNames',{'source_time_s','side','current_A','soc','polarization_V','voltage_V'}),fullfile(root,'results',[id{1} '_native_edges.csv']));
end
end
