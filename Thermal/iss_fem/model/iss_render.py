# -*- coding: utf-8 -*-
"""COMSOL-native figures of the ISS model (headless Image export).

    backend/.venv/Scripts/python iss_render.py out/comsol/iss_beta0.mph [--what geom,mesh,temp] [--times 0,2800]

Geometry and mesh figures work on an unsolved model (a mesh dataset is created);
temperature figures use the orbital-temperature dataset.
Output: out/figures/<model-stem>_<name>.png
"""
import argparse, os, sys, time
import numpy as np
import mph

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(os.path.dirname(HERE), 'out', 'figures'); os.makedirs(FIG, exist_ok=True)

# camera (position, target, up) in the ISS analysis frame (+X fwd, +Y stbd, +Z nadir)
VIEWS = {
    'iso':   ((95.0, 120.0, -85.0), (-5.0, 0.0, 4.0), (0, 0, -1)),     # from fwd-starboard-zenith
    'iso2':  ((-110.0, -95.0, -80.0), (-5.0, 0.0, 4.0), (0, 0, -1)),   # from aft-port-zenith
    'top':   ((-5.0, 0.0, -170.0), (-5.0, 0.0, 0.0), (1, 0, 0)),       # from zenith, fwd up
    'front': ((160.0, 0.0, 0.0), (0.0, 0.0, 3.0), (0, 0, -1)),        # from ahead
    'core':  ((38.0, 42.0, -30.0), (-4.0, 0.0, 4.0), (0, 0, -1)),      # modules + S0/S1/P1
    'hrs':   ((-12.0, 72.0, -14.0), (-12.0, 14.68, 0.0), (0, 0, -1)),  # starboard EATCS radiator wing face-on, zenith up
}


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def make_views(j):
    for tag, (pos, tgt, up) in VIEWS.items():
        try: j.view().remove('v_' + tag)
        except Exception: pass
        v = j.view().create('v_' + tag, 3); c = v.camera()
        c.set('projection', 'perspective'); c.set('position', [str(x) for x in pos]); c.set('target', [str(x) for x in tgt]); c.set('up', [str(x) for x in up])
        try: c.set('viewangle', '28')
        except Exception: pass
        c.set('autoupdate', 'off')
        for k, val in (('showgrid', 'off'), ('showaxisorientation', 'on'), ('scenelight', 'on'), ('showlabels', 'off')):
            try: v.set(k, val)
            except Exception: pass


def export_image(j, pg_tag, path, w=2000, h=1250):
    r = j.result()
    try: r.export().remove('imgx')
    except Exception: pass
    e = r.export().create('imgx', 'Image'); e.set('sourceobject', pg_tag); e.set('pngfilename', path)
    for k, v in (('imagetype', 'png'), ('size', 'manualweb'), ('unit', 'px'), ('width', str(w)), ('height', str(h)), ('antialias', 'on'),
                 ('options', 'on'), ('title', 'on'), ('legend', 'on'), ('axes', 'off'), ('logo', 'off'), ('grid', 'off'), ('background', 'color'), ('transparent', 'off')):
        try: e.set(k, v)
        except Exception: pass
    e.run(); log('wrote', os.path.basename(path))


def plot_group(j, tag, ds, title, view, looplevel=None):
    r = j.result()
    try: r.remove(tag)
    except Exception: pass
    pg = r.create(tag, 'PlotGroup3D'); pg.set('data', ds); pg.set('titletype', 'manual'); pg.set('title', title); pg.set('view', 'v_' + view)
    pg.set('edges', 'off'); pg.set('showlegends', 'on')
    if looplevel is not None:
        try: pg.set('looplevel', [str(looplevel)])
        except Exception as ex: log('looplevel', str(ex)[:80])
    return pg


def surface(pg, tag, expr, sel=None, colortable='HeatCameraLight', rng=None, uniform=None, dataset=None, legend=True):
    s = pg.create(tag, 'Surface'); s.set('expr', expr)
    if not legend:
        try: s.set('colorlegend', 'off')
        except Exception: pass
    if uniform is not None:
        s.set('coloring', 'uniform'); s.set('color', 'custom'); s.set('customcolor', [str(c) for c in uniform])
    else:
        s.set('colortable', colortable)
        if rng:
            s.set('rangecoloractive', 'on'); s.set('rangecolormin', str(rng[0])); s.set('rangecolormax', str(rng[1]))
    if sel is not None:
        try:
            s.create('sel1', 'Selection').selection().named(sel)
        except Exception as ex:
            log('surface selection', sel, str(ex)[:120])
    return s


CLASS_COLORS = {   # geometry figure palette (RGB 0..1)
    'skin_usos': (0.80, 0.80, 0.78), 'skin_rus': (0.62, 0.70, 0.62), 'truss': (0.55, 0.55, 0.60),
    'box': (0.85, 0.62, 0.30), 'payload': (0.85, 0.35, 0.25), 'rack': (0.95, 0.75, 0.20),
    'hrs': (0.95, 0.95, 0.97), 'pvr': (0.88, 0.92, 0.98), 'saw': (0.25, 0.35, 0.65), 'rsa': (0.30, 0.45, 0.60),
}


def geometry_figures(j, stem, classes):
    r = j.result()
    try: r.dataset().remove('dmesh')
    except Exception: pass
    ds = r.dataset().create('dmesh', 'Mesh'); ds.set('mesh', 'mesh1')
    for view in ('iso', 'iso2', 'top', 'front', 'core', 'hrs'):
        pg = plot_group(j, 'pg_geom_' + view, 'dmesh', '国际空间站有限元热模型几何，按部件类别着色', view)
        for c in classes:
            sel = f'geom1_csel_{c}_bnd'
            dsn = 'dm_' + c
            try: r.dataset().remove(dsn)
            except Exception: pass
            dsc = r.dataset().create(dsn, 'Mesh'); dsc.set('mesh', 'mesh1')
            dsc.selection().geom('geom1', 2); dsc.selection().named(sel)
            m = pg.create('m_' + c, 'Mesh'); m.set('data', dsn)
            for k, v in (('elemcolor', 'custom'), ('customelemcolor', [str(x) for x in CLASS_COLORS.get(c, (0.7, 0.7, 0.7))]), ('meshdomain', 'surface'),
                         ('wireframecolor', 'custom'), ('customwireframecolor', ['0.2', '0.2', '0.2']), ('elemscale', '1'), ('wireframe', 'off')):
                try: m.set(k, v)
                except Exception: pass
        pg.run(); export_image(j, 'pg_geom_' + view, os.path.join(FIG, f'{stem}_geom_{view}.png'))
    for view in ('iso', 'core'):
        pg = plot_group(j, 'pg_mesh_' + view, 'dmesh', '国际空间站有限元热模型表面网格', view)
        m = pg.create('m1', 'Mesh')
        for k, v in (('elemcolor', 'custom'), ('customelemcolor', ['0.78', '0.84', '0.92']), ('wireframe', 'on'), ('wireframecolor', 'custom'), ('customwireframecolor', ['0.15', '0.15', '0.2'])):
            try: m.set(k, v)
            except Exception: pass
        pg.run(); export_image(j, 'pg_mesh_' + view, os.path.join(FIG, f'{stem}_mesh_{view}.png'))


def temperature_figures(j, stem, ds, times, period, rng=None):
    t = []
    try:
        n = j.result().numerical().create('evt', 'Global'); n.set('data', ds); n.set('expr', ['t'])
        t = [float(v) for v in n.getReal()[0]]; j.result().numerical().remove('evt')
    except Exception:
        pass
    rng = rng or (-80.0, 80.0)
    for item in times:
        name, want = item if isinstance(item, tuple) else (str(int(item)), item)
        k = int(np.argmin(np.abs(np.array(t) - want))) if t else -1
        lvl = k + 1 if k >= 0 else None
        tt = t[k] if t else want
        for view in ('iso', 'core', 'hrs', 'top'):
            title = f'表面温度，t = {tt:.0f} s，第 {int(tt // period) + 1} 圈，轨道角 {360*(tt % period)/period:.0f}°'
            pg = plot_group(j, f'pg_T_{view}_{name}', ds, title, view, lvl)
            # Plasma matches matplotlib's 'plasma': the COMSOL legend (ASCII minus signs) is switched off and
            # iss_plots.py --colorbar appends a colour bar with true minus signs
            surface(pg, 's_shell', 'T2-273.15', sel='sel_shells', rng=rng, colortable='Plasma', legend=False)
            surface(pg, 's_solid', 'T-273.15', sel='sel_ext_solid', rng=rng, colortable='Plasma', legend=False)
            pg.run(); export_image(j, pg.tag(), os.path.join(FIG, f'{stem}_T_{view}_{name}.png'))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('mph'); ap.add_argument('--what', default='geom')
    ap.add_argument('--times', default=''); ap.add_argument('--cores', type=int, default=2); ap.add_argument('--dataset', default=None)
    ap.add_argument('--period', type=float, default=5554.0); ap.add_argument('--range', default='')
    ap.add_argument('--prefix', default=None, help='file-name stem of the figures (default: model file stem)')
    a = ap.parse_args()
    stem = a.prefix or os.path.splitext(os.path.basename(a.mph))[0]
    client = mph.start(cores=a.cores); model = client.load(a.mph); j = model.java
    make_views(j)
    classes = [c for c in CLASS_COLORS if c != 'rack']
    have = set()
    for c in classes:
        try:
            if len(j.component('comp1').selection(f'geom1_csel_{c}_bnd').entities(2)) > 0: have.add(c)
        except Exception:
            pass
    if 'geom' in a.what:
        geometry_figures(j, stem, [c for c in classes if c in have])
    if 'temp' in a.what:
        times = []
        for x in a.times.split(','):
            if not x: continue
            if ':' in x:
                nm, v = x.split(':'); times.append((nm, float(v)))
            else:
                times.append((str(int(float(x))), float(x)))
        rng = [float(x) for x in a.range.split(',')] if a.range else None
        ds = a.dataset
        if not ds:
            import iss_solve as SOL
            ds, _ = SOL.pick_temperature_dataset(j, 'stdO', 'sel_grp_hrs', 'T2')
            log('temperature dataset', ds)
        temperature_figures(j, stem, ds, times, a.period, rng)


if __name__ == '__main__':
    main()
