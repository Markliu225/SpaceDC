# -*- coding: utf-8 -*-
"""Build the ISS finite-element thermal model in COMSOL 6.3 through MPh.

    backend/.venv/Scripts/python iss_build.py --case beta0 [--lite] [--no-solve]

The geometry and every number come from iss_layout.build(case), which turns
iss_spec.py (sourced parameters) into primitives:
  cylinders  pressurized-module skins      -> Heat Transfer in Shells (T2)
  blocks     truss segments, external boxes, payload blocks, internal racks
                                              -> Heat Transfer in Solids (T)
  panels     EATCS radiator panels, PVR panels, solar-array blankets
                                              -> Heat Transfer in Shells (T2)
Radiation: one Orbital Thermal Loads interface per articulation group
(API facts from smoke tests s01-s05, see docs/PROGRESS.md):
  otl   body   (+Z nadir, +X velocity)       skins, truss, boxes, payloads
  otl2  hrs    (+Y antinormal, +Z anti-Sun;  EATCS radiators, edge to Sun;
                eclipse: +X nadir)            face to Earth in eclipse
  otl3  sarj   (+Y antinormal, +Z anti-Sun)  PVRs, Russian arrays
  otl4  saw    (+Z anti-Sun, +Y antinormal)  US solar array wings (SARJ + BGA)
Cooling loops (Global Equations): EATCS A/B radiator chains (8 panels per ORU,
3 ORUs per loop, bypass mixing to the 2.8 C set point), PVTCS chains.
"""
import argparse, json, math, os, sys, time
import mph

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import iss_spec as S
import iss_layout as LAY

OUT = os.path.join(os.path.dirname(HERE), 'out')
CM = os.path.join(OUT, 'comsol'); os.makedirs(CM, exist_ok=True)
EPS = 2e-3


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def tryset(obj, name, val, label=''):
    try:
        obj.set(name, val); return True
    except Exception as e:
        log('set FAIL', label, name, '=', val, '->', str(e).replace(chr(10), ' ')[:300]); return False


class Builder:
    def __init__(self, args, lay):
        self.a = args; self.lay = lay
        self.client = mph.start(cores=args.cores)
        self.model = self.client.create('iss_' + args.case)
        self.j = self.model.java
        self.comp = self.j.component().create('comp1', True)
        self.geom = self.comp.geom().create('geom1', 3); self.geom.lengthUnit('m')
        self.csel = set()

    # ------------------------------------------------------------ geometry
    def _csel(self, name):
        if name not in self.csel:
            s = self.geom.selection().create('csel_' + name, 'CumulativeSelection'); s.label(name); self.csel.add(name)
        return 'csel_' + name

    def geometry(self):
        g = self.geom; lay = self.lay
        # module skins: solid cylinders converted to CLOSED surfaces (a surface-type Cylinder has no end caps)
        by_cls = {}
        for c in lay['cylinders']:
            f = g.feature().create('cy_' + c['name'], 'Cylinder')
            f.set('r', str(c['R'])); f.set('h', str(c['L']))
            f.set('pos', [float(v) for v in c['p0']]); f.set('axistype', c['axis']); f.label(c['label'])
            by_cls.setdefault(c['cls'], []).append('cy_' + c['name'])
        for cls, objs in by_cls.items():
            cv = g.feature().create('cv_' + cls, 'ConvertToSurface'); cv.selection('input').set(objs)
            cv.set('contributeto', self._csel(cls)); cv.label('closed skins ' + cls)
        for b in lay['blocks']:
            f = g.feature().create('bk_' + b['name'], 'Block')
            f.set('base', 'center'); f.set('pos', [float(v) for v in b['center']]); f.set('size', [float(v) for v in b['size']])
            f.set('contributeto', self._csel(b['cls'])); f.label(b['label'])
        for p in lay['panels']:
            wp = g.feature().create('wp_' + p['name'], 'WorkPlane'); wp.set('planetype', 'quick'); wp.set('quickplane', p['plane'])
            wp.set({'xy': 'quickz', 'yz': 'quickx', 'zx': 'quicky'}[p['plane']], str(p['offset']))
            r = wp.geom().create('r1', 'Rectangle'); r.set('pos', [float(p['u0']), float(p['v0'])]); r.set('size', [float(p['du']), float(p['dv'])])
            wp.set('contributeto', self._csel(p['cls'])); wp.label(p['label'])
        t0 = time.time(); g.run()
        log(f"geometry: {g.getNDomains()} domains, {g.getNBoundaries()} boundaries, {g.getNEdges()} edges ({time.time()-t0:.0f}s)")

    # ------------------------------------------------------------ selections
    def box(self, tag, dim, lo, hi, cond='inside'):
        s = self.comp.selection().create(tag, 'Box'); s.set('entitydim', str(dim))
        for k, v in zip(('xmin', 'ymin', 'zmin'), lo): s.set(k, float(v))
        for k, v in zip(('xmax', 'ymax', 'zmax'), hi): s.set(k, float(v))
        s.set('condition', cond); s.label(tag); return tag

    def inter(self, tag, dim, inputs):
        s = self.comp.selection().create(tag, 'Intersection'); s.set('entitydim', str(dim)); s.set('input', list(inputs)); return tag

    def union(self, tag, dim, inputs):
        s = self.comp.selection().create(tag, 'Union'); s.set('entitydim', str(dim)); s.set('input', list(inputs)); return tag

    def adj(self, tag, inputs, exterior=True, interior=False):
        s = self.comp.selection().create(tag, 'Adjacent'); s.set('entitydim', '3'); s.set('outputdim', '2'); s.set('input', list(inputs))
        s.set('exterior', exterior); s.set('interior', interior); return tag

    def n_ent(self, tag, dim):
        try: return len(self.comp.selection(tag).entities(dim))
        except Exception: return -1

    def selections(self):
        lay = self.lay; cls_used = sorted(self.csel)
        self.cs = {c: {'dom': f'geom1_csel_{c}_dom', 'bnd': f'geom1_csel_{c}_bnd'} for c in cls_used}
        # per-block domain + faces
        self.block_dom = {}; self.block_face = {}
        for b in lay['blocks']:
            lo = [b['center'][k] - b['size'][k] / 2 - EPS for k in range(3)]; hi = [b['center'][k] + b['size'][k] / 2 + EPS for k in range(3)]
            self.block_dom[b['name']] = self.inter('sd_' + b['name'], 3, [self.box('bd_' + b['name'], 3, lo, hi), self.cs[b['cls']]['dom']])
            for fc in [b.get('cool', {}).get('face')] + ([b['air']['exclude']] if b.get('air') else []):
                if not fc or (b['name'], fc) in self.block_face: continue
                ax = 'xyz'.index(fc[1]); sgn = 1 if fc[0] == '+' else -1
                flo, fhi = list(lo), list(hi)
                pos = b['center'][ax] + sgn * b['size'][ax] / 2
                flo[ax], fhi[ax] = pos - EPS, pos + EPS
                self.block_face[(b['name'], fc)] = self.inter('sf_' + b['name'] + fc.replace('+', 'p').replace('-', 'm'), 2,
                                                              [self.box('bf_' + b['name'] + fc.replace('+', 'p').replace('-', 'm'), 2, flo, fhi), self.cs[b['cls']]['bnd']])
        # per-panel boundary selections
        self.panel_sel = {}
        for p in lay['panels']:
            lo, hi = LAY.panel_bbox(p, EPS)
            self.panel_sel[p['name']] = self.inter('sp_' + p['name'], 2, [self.box('bp_' + p['name'], 2, lo, hi), self.cs[p['cls']]['bnd']])
        # per-module skin selections
        self.skin_sel = {}
        for c in lay['cylinders']:
            lo, hi = LAY.cyl_bbox(c, EPS)
            self.skin_sel[c['name']] = self.inter('ss_' + c['name'], 2, [self.box('bs_' + c['name'], 2, lo, hi), self.cs[c['cls']]['bnd']])
        # group-level selections
        solid_ext = [c for c in cls_used if c in LAY.SOLID_BODY_CLASSES]
        self.ext_solid_bnd = self.adj('sel_ext_solid', [self.cs[c]['dom'] for c in solid_ext]) if solid_ext else None
        self.grp = {}
        body_in = [self.cs[c]['bnd'] for c in cls_used if c in LAY.SHELL_BODY_CLASSES] + ([self.ext_solid_bnd] if self.ext_solid_bnd else [])
        self.grp['body'] = self.union('sel_grp_body', 2, body_in)
        for gname, classes in LAY.GROUP_CLASSES.items():
            ins = [self.cs[c]['bnd'] for c in classes if c in self.cs]
            if ins: self.grp[gname] = self.union('sel_grp_' + gname, 2, ins)
        shells = [self.cs[c]['bnd'] for c in cls_used if c in LAY.SHELL_CLASSES]
        solids = [self.cs[c]['dom'] for c in cls_used if c in LAY.SOLID_CLASSES]
        self.sel_shell = self.union('sel_shells', 2, shells); self.sel_solid = self.union('sel_solids', 3, solids)
        log('selections: shells', self.n_ent('sel_shells', 2), 'bnds; solids', self.n_ent('sel_solids', 3), 'doms;',
            ' '.join(f"{k}={self.n_ent(v, 2)}" for k, v in self.grp.items()))
        bad = [k for k, v in self.panel_sel.items() if self.n_ent(v, 2) != 1]
        if bad: log('WARNING panels whose selection is not exactly one boundary:', bad[:10], len(bad))
        badb = [k for k, v in self.block_dom.items() if self.n_ent(v, 3) != 1]
        if badb: log('WARNING blocks whose selection is not exactly one domain:', badb[:10], len(badb))

    # ------------------------------------------------------------ materials
    def materials(self):
        for mname, m in S.MATERIALS.items():
            classes = [c for c in m['classes'] if c in self.cs]
            if not classes: continue
            mt = self.comp.material().create('mat_' + mname, 'Common'); mt.label(m['label'])
            pg = mt.propertyGroup('def')
            pg.set('thermalconductivity', [str(m['k'])]); pg.set('density', str(m['rho'])); pg.set('heatcapacity', str(m['cp']))
            if m['kind'] == 'shell':
                mt.selection().geom('geom1', 2); mt.selection().named(self.union('sm_' + mname, 2, [self.cs[c]['bnd'] for c in classes]))
                mt.propertyGroup().create('shell', 'Shell').set('lth', f"{m['t']}[m]")
            else:
                mt.selection().named(self.union('sm_' + mname, 3, [self.cs[c]['dom'] for c in classes]))

    # ------------------------------------------------------------ physics
    def physics(self):
        j, comp, lay, P = self.j, self.comp, self.lay, S.PARAMS
        for k, (v, d) in P.items():
            j.param().set(k, v, d)
        for k, v in lay['params'].items():
            j.param().set(k, v[0], v[1])
        # orbit: analytic circular orbit in ECS, Sun direction for the case beta
        for nm, expr in lay['orbit_funcs'].items():
            fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')

        # --- heat transfer in solids
        ht = comp.physics().create('ht', 'HeatTransfer', 'geom1'); ht.selection().named(self.sel_solid); ht.label('Heat Transfer in Solids: truss, boxes, payloads, racks')
        ht.feature('init1').set('Tinit', 'T_init_solid')
        # --- heat transfer in shells
        sh = comp.physics().create('htlsh', 'HeatTransferInShellsLM', 'geom1'); sh.selection().named(self.sel_shell); sh.label('Heat Transfer in Shells: skins, radiators, PVRs, arrays')
        sh.feature('init1').set('Tinit', 'T_init_shell')
        self.ht, self.sh = ht, sh
        for cls, T0 in S.T_INIT.items():
            if cls not in self.cs: continue
            if cls in LAY.SOLID_CLASSES:
                f = ht.create('init_' + cls, 'init', 3); f.selection().named(self.cs[cls]['dom'])
            else:
                f = sh.create('init_' + cls, 'init', 2); f.selection().named(self.cs[cls]['bnd'])
            f.set('Tinit', f'{T0}[K]'); f.label(f'initial T {cls}')

        # --- block heat sources and cooling
        for b in lay['blocks']:
            if b.get('Q', 0) > 0:
                hs = ht.create('hs_' + b['name'], 'HeatSource', 3); hs.selection().named(self.block_dom[b['name']])
                hs.set('heatSourceType', 'HeatRate'); hs.set('P0', b['Qexpr']); hs.label(f"{b['label']} heat {b['Q']:.0f} W")
            cl = b.get('cool')
            if cl:
                hf = ht.create('cp_' + b['name'], 'HeatFluxBoundary', 2)
                hf.selection().named(self.block_face[(b['name'], cl['face'])])
                hf.set('HeatFluxType', 'ConvectiveHeatFlux'); hf.set('h', cl['h']); hf.set('Text', cl['T'])
                hf.label(f"{b['label']} cold plate -> {cl['T']}")
        # cabin air convection on all rack faces except the cold-plate face (one feature per module)
        for mod, racks in lay['racks_by_module'].items():
            faces = []
            for rn in racks:
                b = lay['block_by_name'][rn]
                dom = self.block_dom[rn]
                allf = self.adj('sra_' + rn, [dom])
                faces.append(self.comp.selection().create('sar_' + rn, 'Difference').tag())
                self.comp.selection('sar_' + rn).set('entitydim', '2'); self.comp.selection('sar_' + rn).set('add', [allf])
                self.comp.selection('sar_' + rn).set('subtract', [self.block_face[(rn, b['cool']['face'])]])
            u = self.union('sair_' + mod, 2, faces)
            hf = ht.create('air_' + mod, 'HeatFluxBoundary', 2); hf.selection().named(u)
            hf.set('HeatFluxType', 'ConvectiveHeatFlux'); hf.set('h', 'h_air'); hf.set('Text', 'T_cab'); hf.label(f'{mod}: rack faces to cabin air')
        # module skins: MLI leak from the cabin (all modules pressurised at T_cab)
        hfm = sh.create('mli', 'HeatFluxInterface', 2); hfm.selection().named(self.union('sel_skins', 2, [self.cs[c]['bnd'] for c in self.cs if c.startswith('skin')]))
        hfm.set('HeatFluxType', 'ConvectiveHeatFlux'); hfm.set('h', 'h_mli'); hfm.set('Text', 'T_cab'); hfm.label('MLI blanket: cabin -> MMOD shield')
        # radiator / PVR fluid exchange: one surface source per panel, q = g*(Tf_mean - T2)
        for p in lay['panels']:
            if not p.get('fluid'): continue
            hsp = sh.create('fx_' + p['name'], 'HeatSource', 2); hsp.selection().named(self.panel_sel[p['name']])
            t_sh = next(m['t'] for m in S.MATERIALS.values() if p['cls'] in m['classes'])
            hsp.set('Q0', f"({p['fluid']['qexpr']})/{t_sh}[m]")      # layer source W/m3 = surface flux / layer thickness
            hsp.label(f"{p['label']}: NH3 exchange")
            op = comp.cpl().create('ip_' + p['name'], 'Integration'); op.selection().geom('geom1', 2); op.selection().named(self.panel_sel[p['name']]); op.set('opname', 'ip_' + p['name'])
        # integration operators for loop pick-up
        for opname, sel in lay['int_ops'](self):
            op = comp.cpl().create(opname, 'Integration'); dim = sel[1]
            op.selection().geom('geom1', dim); op.selection().named(sel[0]); op.set('opname', opname)
        # global variables (loop heat pick-up etc.)
        gv = comp.variable().create('var_loops'); gv.label('loop heat pick-up and derived loop quantities')
        for k, v in lay['global_vars'].items():
            gv.set(k, v)
        # --- global equations: fluid chains + bypass mixing
        ge = comp.physics().create('ge', 'GlobalEquations'); ge.label('Cooling loops (EATCS A/B, PVTCS)')
        # one Global Equations feature per physical kind: each becomes its own solver field with its own scale
        kinds = {'Q': ('power', 'power', 'collected heat Qc (W)'), 'T': ('temperature', 'power', 'NH3 panel outlet temperatures (K)'),
                 'f': ('dimensionless', 'temperature', 'radiator flow fractions')}
        self.ge_fields = {}
        for ki, (kind, (dq, sq, lbl)) in enumerate(kinds.items()):
            rows = [r for r in lay['ge_rows'] if r[4] == kind]
            g1 = ge.feature('ge1') if ki == 0 else ge.create(f'ge{ki + 1}', 'GlobalEquations', -1)
            g1.label(lbl)
            for i, (name, eq, init, descr, _k) in enumerate(rows):
                g1.setIndex('name', name, i); g1.setIndex('equation', eq, i); g1.setIndex('initialValueU', init, i); g1.setIndex('initialValueUt', '0', i)
                g1.setIndex('description', descr, i)
            tryset(g1, 'DependentVariableQuantity', dq, 'ge'); tryset(g1, 'SourceTermQuantity', sq, 'ge')
            self.ge_fields[kind] = str(g1.tag())
        log('global equations:', len(lay['ge_rows']), 'unknowns')

        # --- orbital thermal loads, one interface per articulation group
        self.otl_names = {}
        for gi, (gname, ginfo) in enumerate(lay['groups'].items()):
            if gname not in self.grp: continue
            tag = 'otl_' + gname
            o = comp.physics().create(tag, 'OrbitalThermalLoadsEvents', 'geom1'); o.selection().named(self.grp[gname]); o.label(ginfo['label'])
            rs = o.prop('RadiationSettings'); rs.set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient'); rs.set('radiationMethod', 'hemicube')
            rs.set('radiationResolution', str(self.a.hemicube)); rs.set('viewFactorsUpdateTolerance', str(self.a.vf_tol))
            op = o.feature('op1'); op.set('orbitType', 'userDefined'); op.set('orbitDefinition', 'FromFunction')
            for ax in 'XYZ':
                op.set(f'functionType_{ax}_ECS', 'userDefined'); op.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(tt)')
            sup = o.feature('sup1'); sup.set('sunDirection', 'userdef'); sup.set('SV_ECS', lay['sun_rays_ecs'])
            sup.set('solarFluxSolAmb', 'userdefBand'); sup.set('q0s_bandSolAmb', ['S_sun', '0'])
            plp = o.feature('plp1'); plp.set('nRings', str(self.a.planet_rings)); plp.set('nPointsRing', str(self.a.planet_points))
            plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['albedo', '0'])
            plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', 'q_olr'])
            sa, so = o.feature('sa1'), o.feature('so1')
            sa.set('primaryAxis', ginfo['axes'][0]); sa.set('secondaryAxis', ginfo['axes'][1])
            so.set('primaryOrientation', ginfo['orient'][0]); so.set('secondaryOrientation', ginfo['orient'][1])
            et = o.feature('et1')
            if ginfo.get('eclipse'):
                sa2 = o.create('sa2', 'SpacecraftAxes', -1); sa2.set('primaryAxis', ginfo['eclipse']['axes'][0]); sa2.set('secondaryAxis', ginfo['eclipse']['axes'][1])
                so2 = o.create('so2', 'SpacecraftOrientation', -1); so2.set('primaryOrientation', ginfo['eclipse']['orient'][0]); so2.set('secondaryOrientation', ginfo['eclipse']['orient'][1])
                et.set('eventType', ['inEclipse', 'outEclipse']); et.set('implicitAxesFeatures', ['sa2', 'sa1']); et.set('implicitOrientationFeatures', ['so2', 'so1'])
                et.set('implicitFastTumbling', ['0', '0']); et.set('implicitDescription', ['face to Earth', 'edge to Sun'])
            else:
                et.set('eventType', ['inEclipse', 'outEclipse']); et.set('implicitAxesFeatures', ['sa1', 'sa1']); et.set('implicitOrientationFeatures', ['so1', 'so1'])
                et.set('implicitFastTumbling', ['0', '0']); et.set('implicitDescription', ['into eclipse', 'out of eclipse'])
            # default optics then class-specific diffuse surfaces
            d0 = o.feature('dsurf1'); d0.set('epsilon_radSolAmb_mat', 'userdefBand'); d0.set('epsilon_rad_bandSolAmb', ginfo['default_optics']); d0.set('Tamb', 'T_space')
            for oc in lay['optics_by_group'][gname]:
                sels = [self.cs[c]['bnd'] if c in LAY.SHELL_CLASSES else self.adj(f'sx_{gname}_{c}', [self.cs[c]['dom']]) for c in oc['classes'] if c in self.cs]
                if not sels: continue
                d = o.create(f"ds_{oc['name']}", 'DiffuseSurface', 2); d.selection().named(self.union(f"so_{gname}_{oc['name']}", 2, sels))
                d.set('Tamb', 'T_space'); d.label(oc['label'])
                if oc.get('direction'):
                    # radiate from one side only (module skins: outward normal = RadiationDirectionPlus, checked
                    # in smoke s10c); no radiosity unknowns inside the closed skin, no singular reflecting enclosure
                    d.set('radDirectionTypeSolAmb', oc['direction'])
                    d.set('epsilon_radSolAmb_mat', 'userdefBand'); d.set('epsilon_rad_bandSolAmb', oc['both'])
                elif oc.get('two_sided'):
                    d.set('defineSurfaceEmissivityOnEachSide', '1')
                    d.set('epsilon_raduSolAmb_mat', 'userdefBand'); d.set('epsilon_raddSolAmb_mat', 'userdefBand')
                    d.set('epsilon_radu_bandSolAmb', oc['up']); d.set('epsilon_radd_bandSolAmb', oc['down'])
                else:
                    d.set('epsilon_radSolAmb_mat', 'userdefBand'); d.set('epsilon_rad_bandSolAmb', oc['both'])
            self.otl_names[gname] = tag
            for hp, need in (('ht', any(c in self.cs for c in LAY.SOLID_BODY_CLASSES) and gname == 'body'), ('htlsh', True)):
                if not need: continue
                mp = comp.multiphysics().create(f'rad_{gname}_{hp}', 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mp.set('Heat_physics', hp); mp.set('Rad_physics', tag)
        # switchable time variable: tt = t (orbit) or tt = t*1e-3 (frozen environment, slow motion)
        comp.variable().create('var_frozen').set('tt', f"t0_frozen+t*1e-3")
        comp.variable().create('var_orbit').set('tt', 't')

    # ------------------------------------------------------------ mesh
    def mesh(self):
        m = self.comp.mesh().create('mesh1'); a = self.a
        m.feature('size').set('custom', True); m.feature('size').set('hmax', str(a.h_default)); m.feature('size').set('hmin', '0.05')
        m.feature('size').set('hgrad', '1.6')
        for cls, h in LAY.mesh_sizes(a).items():
            if cls not in self.cs: continue
            dim = 2 if cls in LAY.SHELL_CLASSES else 3
            s = m.create('sz_' + cls, 'Size'); s.selection().geom('geom1', dim); s.selection().named(self.cs[cls]['bnd' if dim == 2 else 'dom'])
            s.set('custom', True); s.set('hmaxactive', True); s.set('hmax', str(h)); s.set('hminactive', True); s.set('hmin', str(min(h / 4, 0.05)))
        ft = m.create('ftri', 'FreeTri'); ft.selection().geom('geom1', 2); ft.selection().named(self.sel_shell)
        tt = m.create('ftet', 'FreeTet'); tt.selection().geom('geom1', 3); tt.selection().named(self.sel_solid)
        t0 = time.time(); m.run()
        stats = {}
        for et in ('tri', 'tet'):
            try: stats[et] = int(m.getNumElem(et))
            except Exception: pass
        log(f"mesh {time.time()-t0:.0f}s", stats)
        self.mesh_stats = stats

    # ------------------------------------------------------------ studies
    def studies(self):
        j, a = self.j, self.a
        per = self.lay['period']
        def step(st, typ, ftag, tlist, disabled):
            s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist)
            s.set('useadvanceddisable', True); s.set('disabledvariables', [disabled]); return s
        # L: loads only over one orbit (absorbed-flux maps, energy balance)
        st = j.study().create('stdL'); st.label('L: orbital loads only (one orbit)')
        step(st, 'OrbitThermalLoads', 'otl', f"range(0,{a.dt_loads},{per:.1f})", 'var_frozen')
        # F: frozen environment at orbit angle u0 -> near steady state (slow motion)
        st = j.study().create('stdF'); st.label('F: frozen environment -> steady state')
        step(st, 'OrbitThermalLoads', 'otl', f"range(0,{a.dt_frozen},{a.t_frozen})", 'var_orbit')
        s = step(st, 'OrbitalTemperature', 'ot', f"range(0,{a.dt_frozen},{a.t_frozen})", 'var_orbit')
        # O: orbital transient
        st = j.study().create('stdO'); st.label(f'O: orbital transient, {a.orbits} orbits')
        tl = f"range(0,{a.dt_out},{a.orbits*per:.1f})"
        step(st, 'OrbitThermalLoads', 'otl', tl, 'var_frozen')
        step(st, 'OrbitalTemperature', 'ot', tl, 'var_frozen')

    def solver_scaling(self):
        """Generate the solver sequences and set manual scales: temperatures 300 K, loop heat 2e4 W,
        loop temperatures 300 K, flow fractions 1 (automatic scaling mixed them into one 2e4 scale)."""
        j = self.j
        scale = {'comp1_T': '300', 'comp1_T2': '300'}
        for st in ('stdL', 'stdF', 'stdO'):
            try:
                j.study(st).createAutoSequences('all')
            except Exception as e:
                log('createAutoSequences', st, str(e)[:150]); continue
        for sol in j.sol():
            for f in sol.feature():
                if str(f.getType()) != 'Variables': continue
                for c in f.feature():
                    tag = str(c.tag())
                    val = None
                    if tag in scale: val = scale[tag]
                    elif tag.startswith('comp1_ODE'):
                        val = None
                    if tag.startswith('comp1_ODE'):
                        # field order follows the ge features: ge1 = Q, ge2 = T, ge3 = f
                        try: descr = str(c.getString('fieldname')) if 'fieldname' in [str(x) for x in c.properties()] else ''
                        except Exception: descr = ''
                        idx = int(tag.replace('comp1_ODE', '') or '1')
                        val = {1: '2e4', 2: '300', 3: '1'}.get(idx)
                    if val:
                        try:
                            c.set('scalemethod', 'manual'); c.set('scaleval', val)
                        except Exception as e:
                            log('scale', tag, str(e)[:120])
            # time stepping: strict steps no longer than the output interval, BDF order 1 (backward Euler).
            # The OTL loads change piecewise (view-factor updates, eclipse) and a free BDF stepper crawls
            # through those kinks (lite model: 264 s of orbit in 10 min with 41 nonlinear failures).
            for f in sol.feature():
                if str(f.getType()) != 'Time': continue
                # fixed backward-Euler steps (manual): error-controlled stepping stalls on the sampled OTL loads
                for k, v in (('tstepsbdf', 'manual'), ('timestepbdf', str(self.a.dt_out)), ('maxorder', '1')):
                    tryset(f, k, v, f'{sol.tag()}/{f.tag()}')

    def save(self, path):
        if os.path.exists(path):
            try: os.remove(path)
            except OSError: path = path.replace('.mph', f'_{os.getpid()}.mph')
        self.model.save(path); log('saved', path); return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', default='beta0')
    ap.add_argument('--cores', type=int, default=6)
    ap.add_argument('--lite', action='store_true')
    ap.add_argument('--no-solve', dest='no_solve', action='store_true')
    ap.add_argument('--hemicube', type=int, default=128)
    ap.add_argument('--vf-tol', dest='vf_tol', type=float, default=0.02)
    ap.add_argument('--planet-rings', dest='planet_rings', type=int, default=2)
    ap.add_argument('--planet-points', dest='planet_points', type=int, default=6)
    ap.add_argument('--h-default', dest='h_default', type=float, default=2.0)
    ap.add_argument('--dt-loads', dest='dt_loads', type=float, default=60.0)
    ap.add_argument('--dt-frozen', dest='dt_frozen', type=float, default=2000.0)
    ap.add_argument('--t-frozen', dest='t_frozen', type=float, default=40000.0)
    ap.add_argument('--dt-out', dest='dt_out', type=float, default=120.0)
    ap.add_argument('--orbits', type=float, default=3.0)
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    lay = LAY.build(a.case, lite=a.lite)
    log('layout:', {k: len(v) for k, v in lay.items() if isinstance(v, list)})
    b = Builder(a, lay)
    b.geometry(); b.selections(); b.materials(); b.physics(); b.mesh(); b.studies(); b.solver_scaling()
    tag = a.tag or (a.case + ('_lite' if a.lite else ''))
    path = b.save(os.path.join(CM, f'iss_{tag}.mph'))
    json.dump(dict(case=a.case, lite=a.lite, mesh=getattr(b, 'mesh_stats', {}), args=vars(a), mph=path),
              open(os.path.join(CM, f'iss_{tag}_build.json'), 'w'), indent=1)
    if a.no_solve:
        return
    import iss_solve
    iss_solve.run(b, a, tag)


if __name__ == '__main__':
    main()
