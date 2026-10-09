function run_worker
here=fileparts(mfilename('fullpath'));root=fileparts(here);addpath(here);
queue=fullfile(root,'jobs');if ~isfolder(queue),mkdir(queue);end
idle=tic;fprintf('MATLAB worker ready\n');
while toc(idle)<600 && ~isfile(fullfile(queue,'STOP'))
 jobs=dir(fullfile(queue,'job_*.m'));
 for j=1:numel(jobs)
  marker=fullfile(queue,[jobs(j).name '.done.json']);if isfile(marker),continue;end
  idle=tic;fprintf('JOB %s\n',jobs(j).name);
  try
   eval(fileread(fullfile(jobs(j).folder,jobs(j).name)));result=struct('ok',true);
  catch err
   result=struct('ok',false,'message',getReport(err,'extended','hyperlinks','off'));
   fprintf('%s\n',result.message);bdclose('all');
  end
  f=fopen(marker,'w','n','UTF-8');fwrite(f,unicode2native(jsonencode(result),'UTF-8'));fclose(f);
 end
 pause(.5);
end
bdclose('all');fprintf('MATLAB worker stopped\n');
end
