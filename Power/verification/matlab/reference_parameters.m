function p=reference_parameters(a,o)
b=a.battery;p.n=b.electrodes.n;p.p=b.electrodes.p;
p.Ns=b.N_s;p.Np=b.N_p;p.Rohm=b.R_ohm_ohm;p.Tref=b.T_ref_K;
p.area=a.solar.area_m2;p.eff=a.solar.efficiency;p.eta=a.pdu.eta_D;
p.xn0=b.x_n_0;p.xn100=b.x_n_100;
p.Qn=96485.33212*p.n.active_fraction*p.n.electrode_area_m2*p.n.thickness_m*p.n.c_max_mol_m3;
p.Qp=96485.33212*p.p.active_fraction*p.p.electrode_area_m2*p.p.thickness_m*p.p.c_max_mol_m3;
p.imin=b.limits.i_min_A;p.imax=b.limits.i_max_A;p.vmin=b.limits.v_min_V;p.vmax=b.limits.v_max_V;
p.xnlo=b.limits.x_n_range(1);p.xnhi=b.limits.x_n_range(2);
p.xplo=b.limits.x_p_range(1);p.xphi=b.limits.x_p_range(2);
p.Tlo=b.limits.T_range_K(1);p.Thi=b.limits.T_range_K(2);
if ~isempty(o),f=fieldnames(o);for k=1:numel(f),p.(f{k})=o.(f{k});end,end
end
