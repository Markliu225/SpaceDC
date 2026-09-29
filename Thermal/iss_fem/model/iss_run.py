# -*- coding: utf-8 -*-
"""Solve a saved ISS model and write probes (no rebuild).

    backend/.venv/Scripts/python iss_run.py <case> [--orbits 3] [--dt 60] [--cores 3] [--tag nom0] [--t-end s]

Loads out/comsol/iss_<tag>.mph (built by iss_build.py --no-solve), sets the orbital study
time list, solves it with COMSOL's progress log in out/<tag>/progress.log, saves
out/comsol/iss_<tag>_solved.mph and writes the probes of iss_solve.probe().
"""
import argparse, json, os, sys, time
import mph, jpype

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import iss_spec as S
import iss_layout as LAY
import iss_solve as SOL

OUT = os.path.join(os.path.dirname(HERE), 'out')


class Proxy:
    """The attributes of iss_build.Builder that iss_solve.probe() uses, rebuilt from tag conventions."""
    def __init__(self, model, lay, a):
        self.model, self.j, self.lay, self.a = model, model.java, lay, a
        self.comp = self.j.component('comp1')
        classes = set(c['cls'] for c in lay['cylinders']) | set(b['cls'] for b in lay['blocks']) | set(p['cls'] for p in lay['panels'])
        self.cs = {c: {'dom': f'geom1_csel_{c}_dom', 'bnd': f'geom1_csel_{c}_bnd'} for c in sorted(classes)}
        self.grp = {g: 'sel_grp_' + g for g in lay['groups'] if self._exists('sel_grp_' + g)}
        self.block_dom = {b['name']: 'sd_' + b['name'] for b in lay['blocks']}
        self.panel_sel = {p['name']: 'sp_' + p['name'] for p in lay['panels']}
        self.skin_sel = {c['name']: 'ss_' + c['name'] for c in lay['cylinders']}
        bj = os.path.join(OUT, 'comsol', f'iss_{a.tag}_build.json')
        self.mesh_stats = json.load(open(bj)).get('mesh', {}) if os.path.exists(bj) else {}

    def _exists(self, tag):
        try:
            self.comp.selection(tag); return True
        except Exception:
            return False

    def union(self, tag, dim, inputs):
        if not self._exists(tag):
            s = self.comp.selection().create(tag, 'Union'); s.set('entitydim', str(dim)); s.set('input', list(inputs))
        return tag

    def save(self, path):
        if os.path.exists(path):
            try: os.remove(path)
            except OSError: path = path.replace('.mph', f'_{os.getpid()}.mph')
        self.model.save(path); SOL.log('saved', path); return path


def configure_segregated(tfeat, maxseg=25):
    """Merge the solid temperature T into the group of shell temperature T2 + loop ODEs (they are
    coupled through the cold-plate integrals and the loop heat), keep one radiosity group per OTL
    group, and allow more segregated iterations before a step counts as a nonlinear failure."""
    for g in tfeat.feature():
        if str(g.getType()) != 'Segregated': continue
        g.set('maxsegiter', str(maxseg))
        steps = [ss for ss in g.feature() if str(ss.getType()) == 'SegregatedStep']
        tstep = next((ss for ss in steps if [str(x) for x in ss.getStringArray('segvar')] == ['comp1_T']), None)
        t2step = next((ss for ss in steps if 'comp1_T2' in [str(x) for x in ss.getStringArray('segvar')]), None)
        if tstep is not None and t2step is not None:
            merged = ['comp1_T'] + [str(x) for x in t2step.getStringArray('segvar')]
            t2step.set('segvar', merged)
            g.feature().remove(str(tstep.tag()))
            SOL.log('segregated: merged T into', str(t2step.tag()), 'maxsegiter', maxseg)
        SOL.log('segregated groups:', [(str(ss.tag()), len(ss.getStringArray('segvar'))) for ss in g.feature() if str(ss.getType()) == 'SegregatedStep'])


def apply_overrides(j, lay):
    """Push the current iss_spec parameters, loop initial values and class initial temperatures into a
    model built with older values (so a model file does not have to be rebuilt for such changes)."""
    for k, (v, d) in S.PARAMS.items():
        j.param().set(k, v, d)
    comp = j.component('comp1'); ge = comp.physics('ge')
    rows = {r[0]: r for r in lay['ge_rows']}
    for g in ge.feature():
        if str(g.getType()) != 'GlobalEquations': continue
        names = [str(x) for x in g.getStringArray('name')]
        for i, n in enumerate(names):
            if n in rows:
                g.setIndex('initialValueU', rows[n][2], i)
                g.setIndex('equation', rows[n][1], i)
    for k, v in lay['global_vars'].items():
        comp.variable('var_loops').set(k, v)
    # optics of every class-specific diffuse surface, from the current spec
    for gname, ocs in lay['optics_by_group'].items():
        try: o = comp.physics('otl_' + gname)
        except Exception: continue
        for oc in ocs:
            try: d = o.feature('ds_' + oc['name'])
            except Exception: continue
            if oc.get('two_sided'):
                d.set('epsilon_radu_bandSolAmb', oc['up']); d.set('epsilon_radd_bandSolAmb', oc['down'])
            else:
                d.set('epsilon_rad_bandSolAmb', oc['both'])
    for cls, T0 in S.T_INIT.items():
        for iface in ('ht', 'htlsh'):
            try:
                comp.physics(iface).feature('init_' + cls).set('Tinit', f'{T0}[K]')
            except Exception:
                pass
    # materials (thermal conductivity etc.) from the spec
    for mname, mm in S.MATERIALS.items():
        try:
            pg = comp.material('mat_' + mname).propertyGroup('def')
            pg.set('thermalconductivity', [str(mm['k'])]); pg.set('density', str(mm['rho'])); pg.set('heatcapacity', str(mm['cp']))
        except Exception:
            pass
    # cold plates that the current layout no longer has (JEM-EF) are switched off
    cooled = set(b['name'] for b in lay['blocks'] if b.get('cool'))
    ht = comp.physics('ht')
    for f in ht.feature():
        tg = str(f.tag())
        if tg.startswith('cp_') and tg[3:] not in cooled:
            f.active(False); SOL.log('cold plate switched off:', tg)
    # LT racks get their own initial temperature
    lt = [b['name'] for b in lay['blocks'] if b['cls'] == 'rack' and b['cool']['T'] == 'T_LTL']
    if lt:
        try: f = ht.feature('init_rack_lt')
        except Exception:
            u = comp.selection().create('sel_rack_lt', 'Union'); u.set('entitydim', '3'); u.set('input', ['sd_' + n for n in lt])
            f = ht.create('init_rack_lt', 'init', 3); f.selection().named('sel_rack_lt')
        f.set('Tinit', f'{S.T_INIT_RACK_LT}[K]')
    SOL.log('overrides applied: k_c', S.PARAMS['k_c'][0], 'f_init A', rows['f_A'][2], 'T_init hrs', S.T_INIT['hrs'], 'LT racks', len(lt))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('case'); ap.add_argument('--tag', default=None); ap.add_argument('--orbits', type=float, default=3.0)
    ap.add_argument('--dt', type=float, default=60.0); ap.add_argument('--cores', type=int, default=3)
    ap.add_argument('--t-end', dest='t_end', type=float, default=None); ap.add_argument('--lite', action='store_true')
    ap.add_argument('--probe-only', dest='probe_only', action='store_true', help='load the solved model and only write probes')
    a = ap.parse_args()
    a.tag = a.tag or a.case
    lay = LAY.build(a.case, lite=a.lite)
    per = lay['period']
    t_end = a.t_end if a.t_end else a.orbits * per
    outdir = os.path.join(OUT, a.tag); os.makedirs(outdir, exist_ok=True)
    client = mph.start(cores=a.cores)
    if a.probe_only:
        import glob
        cands = sorted(glob.glob(os.path.join(OUT, 'comsol', f'iss_{a.tag}_*.mph')) + [os.path.join(OUT, 'comsol', f'iss_{a.tag}.mph')],
                       key=os.path.getmtime)
        cands = [c_ for c_ in cands if not c_.endswith('_failed.mph') and os.path.getsize(c_) > 50e6] or cands
        SOL.log('probe-only: loading', cands[-1])
        model = client.load(cands[-1])
        b = Proxy(model, lay, a)
        summ = dict(tag=a.tag, case=a.case, mesh=b.mesh_stats, orbit=lay['orbit_info'], probe_only=True)
        SOL.probe(b, a, a.tag, outdir, summ)
        return
    jpype.JClass('com.comsol.model.util.ModelUtil').showProgress(os.path.join(outdir, 'progress.log'))
    model = client.load(os.path.join(OUT, 'comsol', f'iss_{a.tag}.mph'))
    j = model.java
    tl = f'range(0,{a.dt},{t_end:.1f})'
    for s in ('otl', 'ot'):
        j.study('stdO').feature(s).set('tlist', tl)
    for sol in j.sol():
        if str(sol.study()) != 'stdO': continue
        for f in sol.feature():
            if str(f.getType()) == 'Time':
                f.set('tstepsbdf', 'manual'); f.set('timestepbdf', str(a.dt)); f.set('maxorder', '1')
                for g in f.feature():
                    if str(g.getType()) == 'Segregated':
                        g.set('maxsegiter', '25')
    apply_overrides(j, lay)
    SOL.log('case', a.case, 'tag', a.tag, 'period %.1f s' % per, 'tlist', tl)
    b = Proxy(model, lay, a)
    a.lite = a.lite
    SOL.run(b, a, a.tag)


if __name__ == '__main__':
    main()
