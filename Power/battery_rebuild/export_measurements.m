function export_measurements
here=fileparts(mfilename('fullpath'));in=fullfile(here,'reference','mathworks_download','testDataBAKcells');
out=fullfile(here,'data');if ~isfolder(out),mkdir(out);end
for T=[0 10 25 35 45]
 path=fullfile(in,sprintf('hppcDataBAKcell%ddegC.mat',T));load(path,'hppcData');
 fprintf('%d C: %d rows\n',T,height(hppcData));disp(hppcData.Properties.VariableNames);disp(hppcData(1:3,:));
 a=table2array(hppcData);writematrix(a,fullfile(out,sprintf('BAK_%dC.csv',T)));
end
end
