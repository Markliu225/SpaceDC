function [cfg,input_data]=load_case(id)
root=fileparts(fileparts(mfilename('fullpath')));
cfg=jsondecode(fileread(fullfile(root,'fixtures',[id '.json'])));
input_data=readmatrix(fullfile(root,'fixtures',[id '.csv']));
assignin('base','cfg',cfg);assignin('base','input_data',input_data);
assignin('base','capacity_Ah',cfg.asset.capacity_Ah);
assignin('base','pack_count',cfg.n_series*cfg.n_parallel);
assignin('base','solar_gain',cfg.area_m2*cfg.solar_efficiency);
end
