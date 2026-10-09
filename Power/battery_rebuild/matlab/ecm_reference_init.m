function s=ecm_reference_init(cfg)
p=cfg.parameters;c=cfg.observer;dt=cfg.dt_s;
s.x=[cfg.initial_soc;0];s.P=diag(c.initial_state_variance);
a=exp(-c.rls_interval_s/p.tau);s.theta=[a;p.r0;p.r1*(1-a)-a*p.r0;0];
s.S=diag(c.rls_covariance);s.r0=p.r0;s.r1=p.r1;s.tau=p.tau;
s.prev=[];s.currents=[];s.fdy=0;s.fdi=0;s.n=0;s.rprev=[];s.dE=0;s.hits=0;
s.plant=[cfg.initial_open_loop_soc;0];
s.rlsE=interp1(p.soc_grid,p.ocv_grid,cfg.initial_soc,'linear');
end
