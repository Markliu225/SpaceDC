# -*- coding: utf-8 -*-
"""Phase 3 — build, solve and probe the COMSOL twin (re-runnable).

    backend/.venv/Scripts/python build_comsol.py caseA            # full run
    backend/.venv/Scripts/python build_comsol.py caseB --orbits 3
    backend/.venv/Scripts/python build_comsol.py caseA --lite     # quick smoke (coarse, 0.3 orbit)

Pipeline
  1. read the OrbitWiz 1-s trace (run_orbitwiz.py export) and write COMSOL
     interpolation tables starting at the "hot instant" t0 (sunlit, sun most
     normal to a radiator face, peak payload block)
  2. geometry (geometry_spec.py) -> COMSOL blocks / line segments with
     cumulative selections
  3. Heat Transfer in Solids (ht) + Orbital Thermal Loads (otl) with the
     Surface-to-Surface coupling; user-defined orbit = OrbitWiz SGP4 ECI
     positions; user-defined Sun vector = OrbitWiz analytic Sun; two-band
     (solar / ambient) surface optics; hemicube 128; deep space 2.7 K
  4. study A  "frozen" = environment and power held at t0 (tt = 0), transient
     to steady state (OTL refuses a Stationary step) -> magnitude + energy
     balance check;  study B = orbital transient over N orbits from A
  5. probes -> CSV, summary JSON, .mph saved.

Physics/API notes learned in smoke tests (see smoke2/3.py): OTL needs
`timestepspec` on every study step (no Stationary); the global variable `tt`
is switched per study step via `useadvanceddisable` + `disabledvariables`;
per-band emissivities need `userDefinitionTypeSolAmb = userDefinedForEachBand`
and `epsilon_radSolAmb_mat = userdef`; Thin Rod uses rl/kl/rhol/Cp_l; the
S2S coupling is a boundary-level (edim 2) multiphysics node.
"""
import argparse, csv, json, math, os, sys, time
import mph
import geometry_spec as G

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
OW_DIR = os.path.join(OUT, "orbitwiz")
CM_DIR = os.path.join(OUT, "comsol"); os.makedirs(CM_DIR, exist_ok=True)

CASES = {"caseA": "V100", "caseB": "A100"}
T0_HOT_S = 2051.0            # from the Case A trace (same timeline for B): sunlit, sun 0.86 along -Y (radiator face), peak block
PERIOD_S = 5574.193548387097  # single_iss TLE (constellations.py)


# --------------------------------------------------------------------------
# 1. input tables
# --------------------------------------------------------------------------
def write_inputs(case, orbits):
    gpu = CASES[case]
    rows = list(csv.DictReader(open(os.path.join(OW_DIR, f"{case}_{gpu}_1s.csv"), encoding="utf-8")))
    f = lambda r, k: float(r[k])
    t_end = orbits * PERIOD_S + 60.0
    # 120 s of lead-in BEFORE the hot instant: OTL differentiates the position
    # table for the velocity axis, and a table starting exactly at tau=0 has a
    # zero left-hand derivative ("spacecraft velocity is zero")
    sel = [r for r in rows if T0_HOT_S - 120.0 <= f(r, 't_s') <= T0_HOT_S + t_end]
    r0 = next(r for r in sel if abs(f(r, 't_s') - T0_HOT_S) < 0.5)
    path = os.path.join(CM_DIR, f"{case}_input.txt")
    S_mean = sum(f(r, 'solar_flux_w_m2') for r in sel) / len(sel)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("% tau_s heat_per_gpu_W heat_platform_W rx_m ry_m rz_m sunx suny sunz\n")
        for r in sel:
            tau = f(r, 't_s') - T0_HOT_S
            fh.write("%.1f %.4f %.4f %.3f %.3f %.3f %.8f %.8f %.8f\n" % (
                tau, f(r, 'heat_per_gpu_w'), f(r, 'heat_platform_w'),
                f(r, 'r_eci_x_km') * 1e3, f(r, 'r_eci_y_km') * 1e3, f(r, 'r_eci_z_km') * 1e3,
                f(r, 'sun_eci_x'), f(r, 'sun_eci_y'), f(r, 'sun_eci_z')))
    peak = max(f(r, 'heat_per_gpu_w') for r in rows)
    info = dict(case=case, gpu=gpu, n_rows=len(sel), t0_hot_s=T0_HOT_S, S_mean_w_m2=S_mean,
                peak_heat_per_gpu_w=peak, heat_per_gpu_at_t0=f(r0, 'heat_per_gpu_w'),
                heat_platform_w=f(r0, 'heat_platform_w'), sun_eci_t0=[f(r0, k) for k in ('sun_eci_x', 'sun_eci_y', 'sun_eci_z')],
                T_struct_at_t0_c=f(r0, 'T_struct_c'))
    return path, info, sel


# --------------------------------------------------------------------------
# 2-3. model
# --------------------------------------------------------------------------
def build(case, input_path, info, args):
    client = mph.start(cores=args.cores)
    model = client.create(case); j = model.java
    comp = j.component().create('comp1', True)
    geom = comp.geom().create('geom1', 3); geom.lengthUnit('m')
    csel = {}
    for name in ('bus', 'blades', 'pkgs', 'rads', 'booms', 'wings', 'hp'):
        csel[name] = geom.selection().create('csel_' + name, 'CumulativeSelection'); csel[name].label(name)

    def block(b, sel, extra=()):
        f = geom.feature().create(b['name'], 'Block')
        f.set('pos', [float(v) for v in b['min']]); f.set('size', [float(v) for v in b['size']]); f.set('base', 'corner')
        f.set('contributeto', 'csel_' + sel)
        f.label(b['name'])
        return f
    for b in G.BUS:
        block(b, 'bus')
    blades = G.blades()
    for b, p in blades:
        block(b, 'blades'); block(p, 'pkgs')
    for r in G.radiators():
        if r.get('boom'):
            # shorten by 5 mm so the boom does NOT touch the panel (heat pipes are the coupling)
            r = dict(r)
            if r['sign'] > 0: r['size'] = [r['size'][0], r['size'][1], r['size'][2] - 0.005]
            else: r['min'] = [r['min'][0], r['min'][1], r['min'][2] + 0.005]; r['size'] = [r['size'][0], r['size'][1], r['size'][2] - 0.005]
            block(r, 'booms')
        else:
            block(r, 'rads'); geom.feature(r['name']).set('contributeto', 'csel_rads')
    for w in G.wings():
        block(w, 'wings')
    # heat pipes as slender solid blocks (Thin Rod edges made the transient ~10x
    # slower in smoke tests): one merged network domain per radiator face
    hp_blocks, n_tr = G.heat_pipe_blocks(400 * 0.95)      # same hardware in both cases: sized for the A100 bay
    for hb in hp_blocks:
        f = geom.feature().create(hb['name'], 'Block'); f.set('pos', [float(v) for v in hb['min']]); f.set('size', [float(v) for v in hb['size']])
        f.set('base', 'corner'); f.set('contributeto', 'csel_hp'); f.label(hb['name'])
    geom.run()
    nd, nb, ne = geom.getNDomains(), geom.getNBoundaries(), geom.getNEdges()
    print(f"geometry: {nd} domains, {nb} boundaries, {ne} edges")

    # ---- box selections for faces that need distinct optics / probes
    def boxsel(tag, dim, lo, hi, cond='inside'):
        s = comp.selection().create(tag, 'Box'); s.set('entitydim', str(dim))
        s.set('xmin', lo[0]); s.set('xmax', hi[0]); s.set('ymin', lo[1]); s.set('ymax', hi[1]); s.set('zmin', lo[2]); s.set('zmax', hi[2])
        s.set('condition', cond); s.label(tag); return s
    e = 2e-3
    wing_faces = {}
    for w in G.wings():
        mn, sz = w['min'], w['size']
        xf, xb = mn[0] + sz[0], mn[0]           # +X face (cells), -X face (back)
        wing_faces[w['name'] + '_front'] = boxsel(w['name'] + '_front', 2, (xf - e, mn[1] - e, mn[2] - e), (xf + e, mn[1] + sz[1] + e, mn[2] + sz[2] + e))
        wing_faces[w['name'] + '_back'] = boxsel(w['name'] + '_back', 2, (xb - e, mn[1] - e, mn[2] - e), (xb + e, mn[1] + sz[1] + e, mn[2] + sz[2] + e))
    rad_faces = {}
    for r in G.radiators():
        if r.get('boom'): continue
        mn, sz = r['min'], r['size']
        for side, y in (('p', mn[1] + sz[1]), ('n', mn[1])):
            rad_faces[f"{r['name']}_{side}"] = boxsel(f"{r['name']}_{side}", 2, (mn[0] - e, y - e, mn[2] - e), (mn[0] + sz[0] + e, y + e, mn[2] + sz[2] + e))
    # TIM boundaries: package bottom faces (interior, shared with blade top)
    tim_sels = []
    for b, p in blades:
        mn, sz = p['min'], p['size']
        tim_sels.append(boxsel(p['name'] + '_tim', 2, (mn[0] - e, mn[1] - e, mn[2] - e), (mn[0] + sz[0] + e, mn[1] + sz[1] + e, mn[2] + e)))
    tim_union = comp.selection().create('sel_tim', 'Union'); tim_union.set('entitydim', '2'); tim_union.set('input', [s.tag() for s in tim_sels])

    # ---- materials
    def material(tag, k, rho, cp, sel_named):
        m = comp.material().create(tag, 'Common'); m.label(tag)
        m.propertyGroup('def').set('thermalconductivity', [str(k)]); m.propertyGroup('def').set('density', str(rho)); m.propertyGroup('def').set('heatcapacity', str(cp))
        m.selection().named(sel_named); return m
    material('mat_al', G.AL['k'], G.AL['rho'], G.AL['cp'], 'geom1_csel_bus_dom')
    for nm in ('blades', 'pkgs', 'booms'):
        mm = comp.material().create('mat_al_' + nm, 'Common'); mm.label('Aluminum ' + nm)
        mm.propertyGroup('def').set('thermalconductivity', [str(G.AL['k'])]); mm.propertyGroup('def').set('density', str(G.AL['rho'])); mm.propertyGroup('def').set('heatcapacity', str(G.AL['cp']))
        mm.selection().named(f'geom1_csel_{nm}_dom')
    material('mat_rad', G.RAD_SHELL['k'], G.RAD_SHELL['rho'], G.RAD_SHELL['cp'], 'geom1_csel_rads_dom')
    material('mat_sol', G.SOL_SHELL['k'], G.SOL_SHELL['rho'], G.SOL_SHELL['cp'], 'geom1_csel_wings_dom')

    # ---- functions: interpolation table (dimensionless args; units applied in expressions)
    fi = j.func().create('tab', 'Interpolation'); fi.set('source', 'file'); fi.set('filename', input_path); fi.set('nargs', '1')
    for i, nm in enumerate(('Pgpu', 'Pplat', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz')):
        fi.setIndex('funcs', nm, i, 0); fi.setIndex('funcs', str(i + 1), i, 1)
    fi.set('interp', 'linear'); fi.set('extrap', 'const'); fi.importData()
    # switchable time variable
    comp.variable().create('var_stat').set('tt', 't*1e-3')   # 1000x slow motion: OTL needs a non-zero velocity for the ram axis
    comp.variable().create('var_trans').set('tt', 't')
    # parameters
    j.param().set('S_sun', f"{info['S_mean_w_m2']:.2f}[W/m^2]", 'solar irradiance at the date (1361/d_AU^2)')
    j.param().set('T_space', '2.7[K]'); j.param().set('R_tim', f"{G.TIM_R_M2K_W}[m^2*K/W]")
    j.param().set('n_tr', str(n_tr)); j.param().set('k_hp', f"{G.HP_K_EFF:.4g}[W/(m*K)]")

    # ---- heat transfer in solids
    ht = comp.physics().create('ht', 'HeatTransfer', 'geom1'); ht.label('Heat Transfer in Solids')
    ht.feature('init1').set('Tinit', f"{info['T_struct_at_t0_c'] + 273.15:.2f}[K]")
    # Platform 600 W x 0.95: one HeatRate over the whole bus selection (COMSOL
    # distributes a heat rate uniformly over the selected volume).
    hp = ht.create('hs_plat', 'HeatSource', 3); hp.selection().named('geom1_csel_bus_dom'); hp.set('heatSourceType', 'HeatRate'); hp.set('P0', 'Pplat(tt/1[s])*1[W]'); hp.label('platform 600 W x 0.95 (whole bus)')
    # GPU heat: ONE HeatRate feature per package domain (a single feature over
    # 12 domains would split P0 among them). Per-domain Box selections.
    for b, p in blades:
        mn, sz = p['min'], p['size']
        sdom = boxsel(p['name'] + '_dom', 3, (mn[0] - e, mn[1] - e, mn[2] - e), (mn[0] + sz[0] + e, mn[1] + sz[1] + e, mn[2] + sz[2] + e))
        hsi = ht.create('hs_' + p['name'], 'HeatSource', 3); hsi.selection().named(sdom.tag()); hsi.set('heatSourceType', 'HeatRate'); hsi.set('P0', 'Pgpu(tt/1[s])*1[W]'); hsi.label('GPU heat ' + p['name'])
    tl = ht.create('tim', 'SolidLayeredShell', 2); tl.selection().named('sel_tim'); tl.set('LayerType', 'Resistive'); tl.set('ThermalResistanceType', 'ThermalResistance'); tl.set('R_s', 'R_tim'); tl.label('TIM (thin thermally resistive layer)')
    # the layer must be fully user-defined (no Layered Material link): nominal 0.25 mm bond line,
    # k = lth/R for consistency, aluminium rho/cp (capacity ~20 J/K per package: negligible)
    tl.set('lth_mat', 'userdef'); tl.set('lth', '2.5e-4[m]'); tl.set('k_mat', 'userdef'); tl.set('k', ['2.5e-4[m]/R_tim'])
    tl.set('rho_mat', 'userdef'); tl.set('rho', str(G.AL['rho'])); tl.set('Cp_mat', 'userdef'); tl.set('Cp', str(G.AL['cp']))
    if args.hp_mode == 'isothermal':
        pm = ht.prop('PhysicalModel')
        for cand in ('isothermalDomain', 'IsothermalDomain', 'useIsothermalDomain'):
            try: pm.set(cand, True); break
            except Exception: pass
        idom = ht.create('hp_iso', 'IsothermalDomain', 3); idom.selection().named('geom1_csel_hp_dom'); idom.label('heat pipes (isothermal domains)')
        adj = comp.selection().create('sel_hp_int', 'Adjacent'); adj.set('entitydim', '2'); adj.set('input', ['geom1_csel_hp_dom']); adj.set('exterior', False); adj.set('interior', True)
        idi = ht.create('hp_int', 'IsothermalDomainInterface', 2); idi.selection().named('sel_hp_int'); idi.set('InterfaceType', 'ThermalContact'); idi.set('h', 'h_hp'); idi.label('evaporator/condenser film coefficient')
        j.param().set('h_hp', f"{2.0/(G.HP_R_K_W*6.45e-4):.4g}[W/(m^2*K)]", 'ACT CCHP: 2/(R x evaporator area 6.45 cm2)')
    else:
        mhp = comp.material().create('mat_hp', 'Common'); mhp.label('heat pipe (solid, k_eff)')
        mhp.propertyGroup('def').set('thermalconductivity', [f"{G.HP_K_EFF:.4g}"]); mhp.propertyGroup('def').set('density', str(G.AL['rho'])); mhp.propertyGroup('def').set('heatcapacity', str(G.AL['cp']))
        mhp.selection().named('geom1_csel_hp_dom')

    # ---- orbital thermal loads
    otl = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1'); otl.label('Orbital Thermal Loads')
    rs = otl.prop('RadiationSettings'); rs.set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient'); rs.set('radiationMethod', 'hemicube'); rs.set('radiationResolution', '128')
    # external (sun/planet) view factors are recomputed only when the source
    # directions change by more than this tolerance (smoke6: 2.7x faster with
    # 0.05; 0.02 ~ every 1.1 deg of orbit ~ 18 s). Mutual view factors: fixed geometry.
    rs.set('viewFactorsUpdateTolerance', str(args.vf_tol))
    op = otl.feature('op1'); op.set('orbitType', 'userDefined'); op.set('orbitDefinition', 'FromFunction')
    for ax in 'XYZ':
        op.set(f'functionType_{ax}_ECS', 'userDefined'); op.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(tt/1[s])*1[m]')
    sup = otl.feature('sup1'); sup.set('sunDirection', 'userdef')
    sup.set('SV_ECS', ['-sx(tt/1[s])', '-sy(tt/1[s])', '-sz(tt/1[s])'])     # SV = direction of the rays (Sun -> Earth)
    sup.set('solarFluxSolAmb', 'userdefBand'); sup.set('q0s_bandSolAmb', ['S_sun', '0'])
    plp = otl.feature('plp1'); plp.set('planetProperties', 'earth')
    # planet discretisation 2 rings x 6 = 13 point sources (default 5x10 = 51):
    # every external view-factor update costs ~1.2 s per source per step on the
    # lite mesh (smoke12), and the 13-point disc changes the integrated planet
    # loads by < 1 % (reported in the solve log)
    plp.set('nRings', str(args.planet_rings)); plp.set('nPointsRing', str(args.planet_points))
    plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['0.3', '0'])
    plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', '237[W/m^2]'])
    otl.feature('sa1').set('primaryAxis', 'z'); otl.feature('sa1').set('secondaryAxis', 'y')
    otl.feature('so1').set('primaryOrientation', 'nadir'); otl.feature('so1').set('secondaryOrientation', 'velocity')
    # eclipse entry/exit as implicit events: the solver restarts at the load
    # discontinuity instead of failing its error test there (smoke9)
    et = otl.feature('et1'); et.set('eventType', ['inEclipse', 'outEclipse'])
    et.set('implicitAxesFeatures', ['sa1', 'sa1']); et.set('implicitOrientationFeatures', ['so1', 'so1'])
    et.set('implicitFastTumbling', ['0', '0']); et.set('implicitDescription', ['into eclipse', 'out of eclipse'])

    def diffuse(tag, named_sel, alpha, eps, label):
        d = otl.create(tag, 'DiffuseSurface', 2) if tag != 'dsurf1' else otl.feature('dsurf1')
        if tag != 'dsurf1':
            d.selection().named(named_sel)
        d.set('epsilon_radSolAmb_mat', 'userdefBand')   # per-band user values (NOT 'userdef' = scalar all-bands value, which left every surface at eps = alpha = 0)
        d.set('epsilon_rad_bandSolAmb', [str(alpha), str(eps)]); d.set('Tamb', 'T_space'); d.label(label); return d
    diffuse('dsurf1', None, G.OPT_BARE_AL['alpha'], G.OPT_BARE_AL['eps'], 'bare aluminium (default, all other surfaces)')
    # radiator panels AND the surface-mounted heat-pipe blocks wear the white paint
    # (embedded pipes sit under the painted facesheet in reality; covering 13 %
    # of the panel with bare aluminium would be a modelling artefact)
    radsel = comp.selection().create('sel_rad_paint', 'Union'); radsel.set('entitydim', '2'); radsel.set('input', ['geom1_csel_rads_bnd', 'geom1_csel_hp_bnd'])
    diffuse('ds_rad', 'sel_rad_paint', G.OPT_WHITEPAINT['alpha'], G.OPT_WHITEPAINT['eps'], 'radiator white paint (panels + pipe blocks)')
    wf = comp.selection().create('sel_wing_front', 'Union'); wf.set('entitydim', '2'); wf.set('input', [k for k in wing_faces if k.endswith('_front')])
    wb = comp.selection().create('sel_wing_back', 'Union'); wb.set('entitydim', '2'); wb.set('input', [k for k in wing_faces if k.endswith('_back')])
    diffuse('ds_cell', 'sel_wing_front', G.OPT_CELL_FRONT['alpha'], G.OPT_CELL_FRONT['eps'], 'solar cells (+X): alpha - eta_elec')
    diffuse('ds_back', 'sel_wing_back', G.OPT_CELL_BACK['alpha'], G.OPT_CELL_BACK['eps'], 'array back (-X)')
    mp = comp.multiphysics().create('htrad1', 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mp.set('Heat_physics', 'ht'); mp.set('Rad_physics', 'otl')

    # ---- mesh: coarse globally, finer on packages/blades, swept 1-layer on the thin panels
    mesh = comp.mesh().create('mesh1')
    mesh.feature('size').set('hauto', '9' if args.lite else '6')
    sz_fine = mesh.create('size_gpu', 'Size'); sz_fine.selection().geom('geom1', 3)
    sz_fine.selection().named('geom1_csel_pkgs_dom'); sz_fine.set('hauto', '7' if args.lite else str(args.h_pkg))
    sz_bl = mesh.create('size_blade', 'Size'); sz_bl.selection().geom('geom1', 3); sz_bl.selection().named('geom1_csel_blades_dom'); sz_bl.set('hauto', '8' if args.lite else str(args.h_blade))
    for nm, hmax in (('rads', 0.12 if args.lite else args.h_rad), ('wings', 0.6 if args.lite else args.h_wing), ('hp', 0.08 if args.lite else args.h_hp)):
        s = mesh.create('size_' + nm, 'Size'); s.selection().geom('geom1', 3); s.selection().named(f'geom1_csel_{nm}_dom')
        s.set('custom', True); s.set('hmaxactive', True); s.set('hmax', str(hmax))
    # sweep source faces: free triangles first (mapped quads fail on faces with imprinted heat-pipe edges)
    src = comp.selection().create('sel_sweep_src', 'Union'); src.set('entitydim', '2')
    src.set('input', [k for k in wing_faces if k.endswith('_front')])   # radiators carry heat-pipe edges on both faces -> free tets instead of a sweep
    ftri = mesh.create('ftri_src', 'FreeTri'); ftri.selection().geom('geom1', 2); ftri.selection().named('sel_sweep_src')
    for nm in ('wings',):
        swe = mesh.create('swe_' + nm, 'Sweep'); swe.selection().geom('geom1', 3); swe.selection().named(f'geom1_csel_{nm}_dom')
        dis = swe.create('dis', 'Distribution'); dis.set('numelem', '1')
    ftet = mesh.create('ftet', 'FreeTet'); ftet.selection().geom('geom1', 3); ftet.selection().remaining()
    t0 = time.time(); mesh.run(); print("mesh OK %.0fs" % (time.time() - t0))
    try:
        print("mesh elements:", mesh.getNumElem('tet'), "tets;", mesh.getNumElem('prism'), "prisms;", mesh.getNumElem('tri'), "tris")
    except Exception as e:
        print("mesh stat n/a", e)

    # ---- studies. Temperature studies evaluate the loads LIVE (one study with
    # an Orbit Thermal Loads step + an Orbital Temperature step); the orbital
    # one is integrated with STRICT BDF-1 steps equal to the output interval —
    # the only stepping that passed the eclipse switch in the smoke tests
    # (smoke9-12). Separate loads-only studies (LA, LB) exist solely so the
    # absorbed external power can be integrated explicitly (otl.Gext2 can only
    # be evaluated on a loads-study dataset in this build).
    def loads_study(tag, tlist, disabled, label):
        st = j.study().create(tag); st.label(label); s = st.create('otl', 'OrbitThermalLoads')
        s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', [disabled]); return st
    def temp_study(tag, tlist, disabled, label, init=None):
        st = j.study().create(tag); st.label(label)
        for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
            s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', [disabled])
            if typ == 'OrbitalTemperature':
                s.set('rtol', str(args.rtol))
                if init:
                    s.set('initmethod', 'sol'); s.set('initstudy', init); s.set('initstudystep', 'ot'); s.set('solnum', 'last')
        return st
    tlist_A = f"range(0,{args.dt_frozen},{args.t_frozen})"
    loads_study('stdLA', f"range(0,{args.t_frozen},{args.t_frozen})", 'var_trans', 'LA: frozen loads (for the energy balance)')
    temp_study('stdA', tlist_A, 'var_trans', 'A: frozen environment -> steady state (1000x slow motion)')
    t_end = args.orbits * PERIOD_S
    tlist_B = f"range(0,{args.dt_out},{t_end:.1f})"
    loads_study('stdLB', tlist_B, 'var_stat', 'LB: orbital loads (for the absorbed-power series)')
    temp_study('stdB', tlist_B, 'var_stat', 'B: orbital transient, strict BDF-1 steps (init from A)', init='stdA')
    return client, model, dict(rad_faces=list(rad_faces), wing_faces=list(wing_faces), blades=[b['name'] for b, p in blades], pkgs=[p['name'] for b, p in blades], n_tr=n_tr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('case', choices=list(CASES))
    ap.add_argument('--orbits', type=float, default=3.0)
    ap.add_argument('--dt-out', dest='dt_out', type=float, default=60.0)   # strict solver step = output interval
    ap.add_argument('--t-frozen', dest='t_frozen', type=float, default=60000.0)
    ap.add_argument('--dt-frozen', dest='dt_frozen', type=float, default=2000.0)
    ap.add_argument('--rtol', type=float, default=0.005)
    ap.add_argument('--cores', type=int, default=6)
    ap.add_argument('--lite', action='store_true')
    ap.add_argument('--no-solve', dest='no_solve', action='store_true')
    ap.add_argument('--hp-mode', dest='hp_mode', choices=['solid', 'isothermal'], default='solid')
    ap.add_argument('--vf-tol', dest='vf_tol', type=float, default=0.02)
    ap.add_argument('--planet-rings', dest='planet_rings', type=int, default=2)
    ap.add_argument('--planet-points', dest='planet_points', type=int, default=6)
    ap.add_argument('--log', default=None)
    # radiation cost scales with the boundary-triangle count (~quadratically for the radiosity solve):
    # production v3 defaults keep the radiator panels fine (the probe of interest) and coarsen the rest
    ap.add_argument('--h-pkg', dest='h_pkg', type=int, default=6)       # COMSOL size preset: 4 fine .. 6 coarse .. 7 coarser
    ap.add_argument('--h-blade', dest='h_blade', type=int, default=7)
    ap.add_argument('--h-rad', dest='h_rad', type=float, default=0.08)   # m
    ap.add_argument('--h-wing', dest='h_wing', type=float, default=0.50)
    ap.add_argument('--h-hp', dest='h_hp', type=float, default=0.10)
    args = ap.parse_args()
    if args.lite:
        args.orbits = min(args.orbits, 0.3); args.t_frozen = 6000.0; args.dt_frozen = 1000.0; args.dt_out = 60.0
    input_path, info, rows = write_inputs(args.case, args.orbits)
    print(json.dumps(info, indent=1))
    client, model, meta = build(args.case, input_path, info, args)
    tag = args.case + ('_lite' if args.lite else '')
    mph_path = os.path.join(CM_DIR, tag + '.mph')
    if os.path.exists(mph_path):
        try:
            os.remove(mph_path)
        except OSError:
            tag = tag + '_' + str(os.getpid()); mph_path = os.path.join(CM_DIR, tag + '.mph')   # stale COMSOL lock from a killed run
    model.save(mph_path); print("saved", mph_path, flush=True)
    if args.no_solve:
        return
    import solve_and_probe as SP
    SP.run(model, args, info, meta, tag)


if __name__ == '__main__':
    main()
