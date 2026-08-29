# -*- coding: utf-8 -*-
"""COMSOL-native renders (Image export from PlotGroup3D, works headless via
the mph server) for the modelling figures: mesh, optical-property map, solar /
planet irradiation at t0, surface temperature at the frozen steady state and
at the hottest / coldest radiator instants of orbit 2, bus zooms.
    backend/.venv/Scripts/python render_comsol.py caseA [--cores 2]
Outputs out/figures/<case>_cm_*.png
"""
import argparse, os, sys, time
import numpy as np
import mph
import probe_offline as PO

HERE = os.path.dirname(os.path.abspath(__file__))
CM_DIR = os.path.join(HERE, "out", "comsol")
FIG = os.path.join(HERE, "out", "figures"); os.makedirs(FIG, exist_ok=True)
P = 5574.193548387097
VIEWS = {   # camera position (m), target, up  — body frame +X orbit normal, +Y ram, +Z nadir
    'iso':  ((-13.0, -17.0, 9.5), (0.0, 0.0, 0.0), (0, 0, 1)),
    'bus':  ((-3.6, -4.6, 2.4), (0.0, 0.0, 0.0), (0, 0, 1)),
    'rad':  ((-1.5, -12.0, 0.0), (0.0, 0.0, 0.0), (0, 0, 1)),     # looking at the -Y (wake) radiator faces
    'top':  ((0.0, -0.01, -9.0), (0.0, 0.0, 0.0), (0, 1, 0)),     # from nadir (-Z) side
}


def make_views(j):
    for tag, (pos, tgt, up) in VIEWS.items():
        try: j.view().remove('v_' + tag)
        except Exception: pass
        v = j.view().create('v_' + tag, 3); c = v.camera()
        c.set('projection', 'perspective'); c.set('position', [str(x) for x in pos]); c.set('target', [str(x) for x in tgt]); c.set('up', [str(x) for x in up])
        c.set('autoupdate', 'off')
        v.set('showgrid', 'off'); v.set('showaxisorientation', 'on'); v.set('scenelight', 'on')
        try: v.set('showlabels', 'off')
        except Exception: pass


def export_image(j, pg_tag, path, w=1800, h=1100):
    r = j.result()
    try: r.export().remove('imgx')
    except Exception: pass
    e = r.export().create('imgx', 'Image'); e.set('sourceobject', pg_tag); e.set('pngfilename', path)
    for k, v in (('imagetype', 'png'), ('size', 'manualweb'), ('unit', 'px'), ('width', str(w)), ('height', str(h)), ('antialias', 'on'),
                 ('options', 'on'), ('title', 'on'), ('legend', 'on'), ('axes', 'off'), ('logo', 'off'), ('grid', 'off'), ('background', 'color'), ('transparent', 'off')):
        try: e.set(k, v)
        except Exception: pass
    e.run()


def surface_plot(j, tag, ds, expr, title, view, path, colortable='HeatCameraLight', rng=None, unit_lbl='', t_index=None, edges='on'):
    r = j.result()
    try: r.remove(tag)
    except Exception: pass
    pg = r.create(tag, 'PlotGroup3D'); pg.set('data', ds); pg.set('titletype', 'manual'); pg.set('title', title)
    pg.set('view', 'v_' + view); pg.set('edges', edges); pg.set('showlegends', 'on')
    if t_index is not None:
        try: pg.set('looplevel', [str(t_index + 1)])      # 1-based index into the dataset's time list
        except Exception as ex: print("looplevel:", str(ex)[:80])
    s = pg.create('s1', 'Surface'); s.set('expr', expr); s.set('colortable', colortable)
    try: s.set('descr', unit_lbl)
    except Exception: pass
    if rng:
        try: s.set('rangecoloractive', 'on'); s.set('rangecolormin', str(rng[0])); s.set('rangecolormax', str(rng[1]))
        except Exception as ex: print("range:", str(ex)[:80])
    pg.run()
    export_image(j, tag, path)
    return pg


def mesh_plot(j, tag, ds, title, view, path):
    r = j.result()
    try: r.remove(tag)
    except Exception: pass
    pg = r.create(tag, 'PlotGroup3D'); pg.set('data', ds); pg.set('titletype', 'manual'); pg.set('title', title); pg.set('view', 'v_' + view)
    m = pg.create('m1', 'Mesh')
    for k, v in (('elemcolor', 'custom'), ('customelemcolor', ['0.72', '0.80', '0.90']), ('colortable', 'GrayScale')):
        try: m.set(k, v)
        except Exception: pass
    pg.run(); export_image(j, tag, path)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('case'); ap.add_argument('--cores', type=int, default=2)
    a = ap.parse_args(); tag = a.case
    client = mph.start(cores=a.cores); model = client.load(os.path.join(CM_DIR, a.case + '.mph')); j = model.java; comp = j.component('comp1')
    PO.ensure_selections(comp, dict(rad_faces=['RadiatorTop_p', 'RadiatorTop_n', 'RadiatorBot_p', 'RadiatorBot_n']))
    dm = PO.dataset_map(j); print("datasets:", dm, flush=True)
    dsA, dsB, dsLA = dm.get('stdA'), dm.get('stdB'), dm.get('stdLA')
    make_views(j)
    r = j.result(); ev = PO.SP._ev
    # bus-without-wings boundaries: exterior faces of (all domains - wing domains); probe_offline's
    # sel_rest_ext also drops the radiators and keeps the wing side faces, so it is not usable here
    for t_ in ('sel_nw_ext', 'sel_nw_dom'):
        try: comp.selection().remove(t_)
        except Exception: pass
    d_ = comp.selection().create('sel_nw_dom', 'Difference'); d_.set('entitydim', '3'); d_.set('add', ['sel_alldom']); d_.set('subtract', ['geom1_csel_wings_dom'])
    e_ = comp.selection().create('sel_nw_ext', 'Adjacent'); e_.set('entitydim', '3'); e_.set('outputdim', '2'); e_.set('input', ['sel_nw_dom']); e_.set('exterior', True)

    def rng_at(ds, i=None):   # colour range for bus zooms at time index i (None = last): radiator min .. max(bus, packages)
        # (the bare-Al radiator booms reach ~118 C in sunlight and would otherwise stretch the scale)
        lo = ev(j, 'MinSurface', 'T-273.15', named='sel_rad_faces', data=ds)
        hi1 = ev(j, 'MaxVolume', 'T-273.15', named='geom1_csel_blades_dom', data=ds); hi2 = ev(j, 'MaxVolume', 'T-273.15', named='geom1_csel_pkgs_dom', data=ds)
        k = -1 if i is None else i
        # top = hottest package/blade + 5 C; the spine root next to the hot booms may saturate (white)
        return (float(np.floor(lo[k] / 5.0) * 5), float(np.ceil(max(hi1[k], hi2[k]) / 5.0) * 5 + 5))

    def rng_rad(ds, i=None):  # colour range for radiator views: the radiator faces alone
        lo = ev(j, 'MinSurface', 'T-273.15', named='sel_rad_faces', data=ds); hi = ev(j, 'MaxSurface', 'T-273.15', named='sel_rad_faces', data=ds)
        k = -1 if i is None else i
        return (float(np.floor(lo[k])), float(np.ceil(hi[k])))

    def surf_ds(name, base, sel):   # Surface dataset restricted to the bus so bus plots get their own colour range
        try: r.dataset().remove(name)
        except Exception: pass
        sd = r.dataset().create(name, 'Surface'); sd.set('data', base); sd.selection().named(sel); return name

    out = lambda n: os.path.join(FIG, f"{tag}_cm_{n}.png")
    t0 = time.time()
    if dsA:
        busA = surf_ds('sbusA', dsA, 'sel_nw_ext'); rA = rng_at(dsA)
        mesh_plot(j, 'pg_mesh', dsA, f"{tag}: finite-element mesh (full satellite)", 'iso', out('mesh_full'))
        mesh_plot(j, 'pg_mesh2', dsA, f"{tag}: mesh — bus, blade packages, heat-pipe blocks, radiators", 'bus', out('mesh_bus'))
        try:
            surface_plot(j, 'pg_eps', dsA, 'otl.epsilon_rad', f"{tag}: ambient-band emissivity as assigned (white paint 0.85 / bare Al 0.10 / cells 0.85)", 'iso', out('eps_map'), colortable='GrayScale', rng=(0, 1), unit_lbl='eps')
        except Exception as ex: print("eps_map skipped:", str(ex)[:100])
        surface_plot(j, 'pg_TA', dsA, 'T-273.15', f"{tag}: surface temperature (degC), frozen hot-instant steady state (study A)", 'iso', out('T_frozen_full'), unit_lbl='degC', rng=(10, 100))
        surface_plot(j, 'pg_TA2', busA, 'T-273.15', f"{tag}: bus / packages / heat pipes / radiators (degC), frozen steady state", 'bus', out('T_frozen_bus'), unit_lbl='degC', edges='off', rng=rA)
        surface_plot(j, 'pg_TA3', busA, 'T-273.15', f"{tag}: radiator -Y (wake) faces and heat-pipe spreaders (degC), frozen steady state", 'rad', out('T_frozen_rad'), unit_lbl='degC', edges='off', rng=rng_rad(dsA))
        print("frozen figures %.0fs" % (time.time() - t0), flush=True)
    if dsLA:
        tL = np.array(ev(j, 'AvSurface', 't', named='sel_rad_faces', data=dsLA)); i0 = int(np.argmin(np.abs(tL)))
        for expr, nm, ttl in (('otl.Gext1', 'Gext1_t0', 'solar-band irradiation Gext1 (W/m2) at the hot instant t0: direct Sun + albedo, hemicube 128 shadowing'),
                              ('otl.Gext2', 'Gext2_t0', 'ambient-band irradiation Gext2 (W/m2) at t0: Earth IR 237 W/m2 x view factor')):
            try:
                surface_plot(j, 'pg_' + nm, dsLA, expr, f"{tag}: {ttl}", 'iso', out(nm), colortable='Cividis', unit_lbl='W/m2', t_index=i0)
                surface_plot(j, 'pg_' + nm + 'b', dsLA, expr, f"{tag}: {ttl} - bus zoom", 'bus', out(nm + '_bus'), colortable='Cividis', unit_lbl='W/m2', t_index=i0, edges='off')
            except Exception as ex: print(nm, "skipped:", str(ex)[:120])
        print("irradiation figures %.0fs" % (time.time() - t0), flush=True)
    if dsB:
        busB = surf_ds('sbusB', dsB, 'sel_nw_ext')
        t = np.array(ev(j, 'AvSurface', 't', named='sel_rad_faces', data=dsB)); Tr = np.array(ev(j, 'AvSurface', 'T', named='sel_rad_faces', data=dsB))
        w = (t >= P) & (t <= 2 * P); i_hot = int(np.argmax(np.where(w, Tr, -np.inf))); i_cold = int(np.argmin(np.where(w, Tr, np.inf)))
        for lab, i in (('hot', i_hot), ('cold', i_cold)):
            surface_plot(j, f'pg_TB_{lab}', dsB, 'T-273.15', f"{tag}: surface temperature (degC) at the {lab}test radiator instant of orbit 2 (tau = {t[i]:.0f} s)", 'iso', out(f'T_orbit2_{lab}_full'), unit_lbl='degC', t_index=i)
            surface_plot(j, f'pg_TB2_{lab}', busB, 'T-273.15', f"{tag}: bus zoom (degC) at the {lab}test radiator instant of orbit 2 (tau = {t[i]:.0f} s)", 'bus', out(f'T_orbit2_{lab}_bus'), unit_lbl='degC', t_index=i, edges='off', rng=rng_at(dsB, i))
        print("orbit figures %.0fs" % (time.time() - t0), flush=True)
    print("done ->", FIG, flush=True)


if __name__ == '__main__':
    main()
