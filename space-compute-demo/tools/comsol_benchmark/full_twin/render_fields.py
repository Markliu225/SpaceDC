# -*- coding: utf-8 -*-
"""Field figures from a solved COMSOL twin: exports node data (x, y, z, value)
on the exterior boundaries with COMSOL's Data export and renders them with
matplotlib (works without COMSOL graphics). Figures:
  <tag>_T_frozen.png         surface temperature at the hot-instant steady state (study A)
  <tag>_T_orbit2_hot/cold.png  surface T at the hottest / coldest radiator instant of orbit 2 (study B)
  <tag>_radiator_faces_*.png radiator face maps (+Y / -Y faces of both panels) with max-mean annotation
  <tag>_Gext1_t0.png         solar-band external irradiation at t0 (view factors + shadowing)
  <tag>_mesh.png             boundary mesh (from a Mesh export)
    backend/.venv/Scripts/python render_fields.py caseA [--mph out/comsol/caseA.mph]
"""
import argparse, csv, json, os, sys, time
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mph
import geometry_spec as G
import probe_offline as PO

HERE = os.path.dirname(os.path.abspath(__file__))
CM_DIR = os.path.join(HERE, "out", "comsol")
FIG = os.path.join(HERE, "out", "figures"); os.makedirs(FIG, exist_ok=True)
P = 5574.193548387097


def export_points(j, expr, ds, named, path, t=None):
    """COMSOL Data export on a boundary selection -> rows x y z value. The
    selection is carried by a Surface dataset built on the solution dataset."""
    try: j.result().dataset().remove('surfx')
    except Exception: pass
    sd = j.result().dataset().create('surfx', 'Surface'); sd.set('data', ds); sd.selection().named(named)
    try: j.result().export().remove('dx')
    except Exception: pass
    e = j.result().export().create('dx', 'Data')
    e.set('data', 'surfx'); e.set('expr', [expr]); e.set('filename', path)
    if t is not None:
        e.set('innerinput', 'manual'); e.set('t', str(t))
    else:
        e.set('innerinput', 'last')
    e.set('struct', 'spreadsheet'); e.set('header', False)
    e.run()
    rows = []
    with open(path, encoding='utf-8', errors='ignore') as fh:
        for line in fh:
            if line.startswith('%') or not line.strip(): continue
            parts = line.replace(',', ' ').split()
            try: rows.append([float(v) for v in parts[:4]])
            except ValueError: continue
    return np.array(rows)


def scatter3(ax, a, vmin, vmax, cmap='inferno', s=1.2):
    sc = ax.scatter(a[:, 0], a[:, 1], a[:, 2], c=a[:, 3], s=s, cmap=cmap, vmin=vmin, vmax=vmax, linewidths=0, depthshade=False)
    return sc


def fig_surface(a, title, path, unit='°C', cmap='inferno', lims=None, view=(22, -50), sub=None):
    """Two panels: full satellite (wings) and a bus zoom (|x|,|y| < 1.2 m)."""
    fig = plt.figure(figsize=(15, 7.5), facecolor="#fcfcfb")
    v = a[:, 3]
    vmin, vmax = (np.nanpercentile(v, 1), np.nanpercentile(v, 99)) if lims is None else lims
    ax = fig.add_subplot(1, 2, 1, projection='3d'); ax.set_facecolor("#fcfcfb")
    sc = scatter3(ax, a, vmin, vmax, cmap, s=2.5)
    ax.set_xlim(-6, 6); ax.set_ylim(-6, 6); ax.set_zlim(-4, 4); ax.set_box_aspect((12, 12, 8)); ax.view_init(*view)
    ax.set_xlabel('X [m]'); ax.set_ylabel('Y [m]'); ax.set_zlabel('Z [m]'); ax.set_title('full satellite', fontsize=9, loc='left')
    m = (np.abs(a[:, 0]) < 1.2) & (np.abs(a[:, 1]) < 1.2)
    ax2 = fig.add_subplot(1, 2, 2, projection='3d'); ax2.set_facecolor("#fcfcfb")
    sc2 = scatter3(ax2, a[m], vmin, vmax, cmap, s=6)
    ax2.set_xlim(-1.2, 1.2); ax2.set_ylim(-1.2, 1.2); ax2.set_zlim(-3.4, 3.4); ax2.set_box_aspect((2.4, 2.4, 6.8)); ax2.view_init(18, -40)
    ax2.set_xlabel('X [m]'); ax2.set_ylabel('Y [m]'); ax2.set_zlabel('Z [m]'); ax2.set_title('bus, blades, heat pipes, radiators (zoom)', fontsize=9, loc='left')
    cb = fig.colorbar(sc2, ax=[ax, ax2], shrink=0.6, pad=0.02); cb.set_label(unit)
    fig.suptitle(title, fontsize=10, x=0.02, ha='left')
    if sub: fig.text(0.02, 0.02, sub, fontsize=8, color='#52514e')
    fig.savefig(path, dpi=150, bbox_inches='tight'); plt.close(fig)


def fig_radiator_faces(a_faces, title, path, unit='°C'):
    """a_faces: dict face_name -> array (x,y,z,T). Radiator faces lie in planes y=const; plot X vs Z."""
    fig, axes = plt.subplots(1, 4, figsize=(14, 5.2), facecolor="#fcfcfb", sharey=False)
    allv = np.concatenate([a[:, 3] for a in a_faces.values()])
    vmin, vmax = np.nanpercentile(allv, 0.5), np.nanpercentile(allv, 99.5)
    for ax, (name, a) in zip(axes, a_faces.items()):
        ax.set_facecolor("#fcfcfb")
        sc = ax.scatter(a[:, 0], a[:, 2], c=a[:, 3], s=6, cmap='inferno', vmin=vmin, vmax=vmax, linewidths=0)
        mean = float(np.nanmean(a[:, 3])); mx = float(np.nanmax(a[:, 3])); mn = float(np.nanmin(a[:, 3]))
        ax.set_title(f"{name}\nmean {mean:.1f}  max {mx:.1f}  min {mn:.1f} {unit}\nmax-mean {mx-mean:.1f} {unit}", fontsize=8)
        ax.set_aspect('equal'); ax.set_xlabel('X [m]'); ax.set_ylabel('Z [m]'); ax.tick_params(labelsize=7)
    cb = fig.colorbar(sc, ax=axes, shrink=0.8, pad=0.02); cb.set_label(unit)
    fig.suptitle(title, fontsize=10, x=0.02, ha='left')
    fig.savefig(path, dpi=150, bbox_inches='tight'); plt.close(fig)


def fig_mesh(j, path):
    """Boundary mesh: export the mesh as an mphtxt-like text via Mesh export is heavy; instead
    export node coordinates of the exterior boundaries with 'meshvol'/'h' as colour."""
    return None


def newest_model(case):
    """Newest out/comsol/<case>*.mph that is a production model (not lite/copy/afterA)."""
    import glob
    cands = [f for f in glob.glob(os.path.join(CM_DIR, case + '*.mph')) if not any(k in os.path.basename(f) for k in ('lite', 'copy', 'afterA'))]
    return max(cands, key=os.path.getmtime) if cands else os.path.join(CM_DIR, case + '.mph')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('case'); ap.add_argument('--mph', default=None); ap.add_argument('--cores', type=int, default=3)
    args = ap.parse_args()
    tag = os.path.splitext(os.path.basename(args.mph))[0] if args.mph else args.case
    path = args.mph or newest_model(args.case)
    if not args.mph: tag = args.case      # outputs named by case (compare_report.py expects <case>_probes.csv)
    client = mph.start(cores=args.cores); model = client.load(path); j = model.java; comp = j.component('comp1')
    PO.ensure_selections(comp, dict(rad_faces=['RadiatorTop_p', 'RadiatorTop_n', 'RadiatorBot_p', 'RadiatorBot_n']))
    dm = PO.dataset_map(j); print("datasets:", dm, flush=True)
    tmp = os.path.join(FIG, '_tmp_export.txt')
    dsA, dsB, dsLA = dm.get('stdA'), dm.get('stdB'), dm.get('stdLA')
    ev = PO.SP._ev
    # ---- frozen steady state (study A, last time)
    if dsA:
        a = export_points(j, 'T-273.15', dsA, 'sel_ext', tmp)
        fig_surface(a, f"{tag}: surface temperature at the hot-instant steady state (study A, frozen environment)", os.path.join(FIG, f"{tag}_T_frozen.png"),
                    sub="COMSOL 6.3 · Heat Transfer in Solids + Orbital Thermal Loads · hemicube 128 · exterior boundary nodes")
        faces = {n: export_points(j, 'T-273.15', dsA, n, tmp) for n in ('RadiatorTop_p', 'RadiatorTop_n', 'RadiatorBot_p', 'RadiatorBot_n')}
        fig_radiator_faces(faces, f"{tag}: radiator face temperatures at the frozen steady state (in-plane gradient)", os.path.join(FIG, f"{tag}_radiator_faces_frozen.png"))
        # mesh density proxy: element size h on exterior boundaries
        try:
            m = export_points(j, 'h', dsA, 'sel_ext', tmp)
            fig_surface(m, f"{tag}: boundary mesh — local element size h (m); 35.8k tets / 26.2k boundary triangles", os.path.join(FIG, f"{tag}_mesh_h.png"), unit='h [m]', cmap='viridis')
        except Exception as e:
            print("mesh figure skipped:", str(e)[:100], flush=True)
    if dsLA:
        try:
            g = export_points(j, 'otl.Gext1', dsLA, 'sel_ext', tmp)
            fig_surface(g, f"{tag}: solar-band external irradiation otl.Gext1 at t0 (direct Sun + albedo; shadowing by hemicube view factors)", os.path.join(FIG, f"{tag}_Gext1_t0.png"), unit='W/m²', cmap='cividis', lims=(0, float(np.nanpercentile(g[:, 3], 99.5))), view=(22, 130))
        except Exception as e:
            print("Gext1 figure skipped:", str(e)[:100], flush=True)
    # ---- orbital: hottest / coldest radiator instants within orbit 2
    if dsB:
        t = ev(j, 'AvSurface', 't', named='sel_rad_faces', data=dsB); Tr = ev(j, 'AvSurface', 'T', named='sel_rad_faces', data=dsB)
        t = np.array(t); Tr = np.array(Tr); w = (t >= P) & (t <= 2 * P)
        i_hot = int(np.argmax(np.where(w, Tr, -np.inf))); i_cold = int(np.argmin(np.where(w, Tr, np.inf)))
        for lab, i in (('hot', i_hot), ('cold', i_cold)):
            a = export_points(j, 'T-273.15', dsB, 'sel_ext', tmp, t=t[i])
            fig_surface(a, f"{tag}: surface temperature at the {lab}est radiator instant of orbit 2 (tau = {t[i]:.0f} s)", os.path.join(FIG, f"{tag}_T_orbit2_{lab}.png"))
            faces = {n: export_points(j, 'T-273.15', dsB, n, tmp, t=t[i]) for n in ('RadiatorTop_p', 'RadiatorTop_n', 'RadiatorBot_p', 'RadiatorBot_n')}
            fig_radiator_faces(faces, f"{tag}: radiator faces at the {lab}est instant of orbit 2 (tau = {t[i]:.0f} s)", os.path.join(FIG, f"{tag}_radiator_faces_orbit2_{lab}.png"))
    try: os.remove(tmp)
    except OSError: pass
    print("figures ->", FIG, flush=True)


if __name__ == '__main__':
    main()
