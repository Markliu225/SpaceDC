"""analyze_layout.py - per-component boxes of the ISS in the ISS analysis frame
(X fwd, Y stbd, Z nadir, metres, origin = S0 truss centre on the truss centre line),
from three independent public NASA models, with cross-model comparison.

  IGOAL : NASA JSC IGOAL glb (root node SSREF_IGOAL).  Child space (a,b,c) is in inches with
          a = X_SSREF, b = Z_SSREF (nadir), c = -Y_SSREF; its origin coincides with the S0
          centre on the truss centre line (Truss_S0 spans c = +-264.1 in, truss segments are
          centred on a = b = 0).  Primary geometry source.
  C     : NASA JSC VCL LightWave scene "ISS complete_2011.lws", frame of null "ISS PIVOT".
          Units inch, +X fwd, +Y stbd, +Z zenith  ->  X = x, Y = y, Z = -z.
  VTAD  : NASA VTAD ISS_stationary.glb (2019).  Units m, +z fwd, -x stbd, +y zenith  ->
          X = z, Y = -x, Z = -y, then a least-squares similarity fit (scale + translation)
          to IGOAL on common module/truss centres (reported).

Output: components_iss_frame.csv, joints_iss_frame.csv, and a printed comparison.
"""
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_bbox import parse_lws, lw_local, glb_rows  # noqa: E402
from lwo2 import read_lwo2, layer_groups  # noqa: E402
import igoal_comps as IG  # noqa: E402

IN = 0.0254


# ------------------------------------------------------------------ helpers
def box(P):
    P = np.asarray(P)
    return P.min(0), P.max(0)


def union(boxes):
    boxes = [b for b in boxes if b is not None]
    return np.min([b[0] for b in boxes], 0), np.max([b[1] for b in boxes], 0)


def igoal_to_iss(P):  # (a,b,c) inch -> (X,Y,Z) m
    P = np.atleast_2d(P)
    return np.column_stack([P[:, 0], -P[:, 2], P[:, 1]]) * IN


def c_to_iss(P):
    P = np.atleast_2d(P)
    return np.column_stack([P[:, 0], P[:, 1], -P[:, 2]]) * IN


def vtad_to_iss_raw(P):
    P = np.atleast_2d(P)
    return np.column_stack([P[:, 2], -P[:, 0], -P[:, 1]])


# ------------------------------------------------------------------ IGOAL
ig_nodes = IG.nodes
ig_children = {i: n.get("children", []) for i, n in enumerate(ig_nodes)}
ig_index = {n.get("name"): i for i, n in enumerate(ig_nodes)}
_ig_cache = {}


def ig_pts(name):
    if name not in _ig_cache:
        Pw, F = IG.mesh_world(name)
        _ig_cache[name] = igoal_to_iss(Pw)
    return _ig_cache[name]


def ig_detail_names(name, exclude=("IROSA",)):
    """node + direct/indirect children whose name starts with '<name>_Details' or equals node."""
    out = [name]
    stack = list(ig_children[ig_index[name]])
    while stack:
        i = stack.pop()
        nm = ig_nodes[i].get("name", "")
        if any(e in nm for e in exclude):
            continue
        if nm.startswith(name + "_Details") or nm.startswith(name.replace("Truss_", "") + "_Details") \
                or (nm.startswith(name) and "Details" in nm):
            if "mesh" in ig_nodes[i]:
                out.append(nm)
            stack.extend(ig_children[i])
    return [n for n in out if "mesh" in ig_nodes[ig_index[n]]]


def ig_box(names, filt=None):
    P = np.vstack([ig_pts(n) for n in names])
    if filt is not None:
        P = P[filt(P)]
    return box(P) if len(P) else None


# ------------------------------------------------------------------ model C
C_SCENE = os.path.join(HERE, "C_HighRes", "Scenes", "ISS complete_2011.lws")
C_DIR = os.path.join(HERE, "C_HighRes")
c_items = parse_lws(C_SCENE)
c_by_id = {it["id"]: it for it in c_items}
c_frame = next(it for it in c_items if it["name"] == "ISS PIVOT")
_c_world = {}


def c_W(it):
    if it["id"] in _c_world:
        return _c_world[it["id"]]
    if it is c_frame:
        M = np.eye(4)
    else:
        par = c_by_id.get(it.get("parent"))
        M = (c_W(par) if par is not None else np.eye(4)) @ lw_local(it)
    _c_world[it["id"]] = M
    return M


_c_cache = {}


def c_item(name):
    """name = '<lwo basename>#L<n>' ; returns (P_iss, surface groups {name: idx})."""
    if name in _c_cache:
        return _c_cache[name]
    it = next(i for i in c_items if i.get("kind") == "object" and i["name"] == name)
    tags, layers = read_lwo2(os.path.join(C_DIR, it["path"].replace("/", os.sep)))
    L = [l for l in layers if l.number == it["layer"] - 1][0]
    M = c_W(it)
    Pw = L.points @ M[:3, :3].T + M[:3, 3]
    res = (c_to_iss(Pw), layer_groups(tags, L, "SURF"))
    _c_cache[name] = res
    return res


def c_box(name, surf=None, exclude_surf=None, filt=None):
    P, g = c_item(name)
    if surf is not None:
        P = P[g[surf]]
    elif exclude_surf is not None:
        keep = np.ones(len(P), bool)
        keep[g[exclude_surf]] = False
        # keep vertices shared with other surfaces
        other = np.unique(np.concatenate([v for k, v in g.items() if k != exclude_surf]))
        keep[other] = True
        P = P[keep]
    if filt is not None:
        P = P[filt(P)]
    return box(P) if len(P) else None


# ------------------------------------------------------------------ VTAD
vt_rows = glb_rows("VTAD", os.path.join(HERE, "ISS_stationary_VTAD.glb"))
vt_mesh = {r["name"]: r["box"] for r in vt_rows if r["scope"] == "mesh"}


def vt_box_raw(name):
    b = vt_mesh[name]
    P = vtad_to_iss_raw(np.array([b[0], b[1]]))
    return P.min(0), P.max(0)


# ------------------------------------------------------------------ component table
PVR_Z = 3.8  # m below truss centre line: PVR panel region (truss envelope ends at Z ~ 2.5 m)
not_pvr = lambda P: P[:, 2] < 2.8  # noqa: E731
is_pvr = lambda P: P[:, 2] > PVR_Z  # noqa: E731
aft = lambda P: P[:, 0] < 0  # noqa: E731
fwd = lambda P: P[:, 0] > 0  # noqa: E731

COMP = []  # (group, component, config note, igoal_fn, c_fn, vtad_fn)


def add(group, comp, note, ig=None, c=None, vt=None):
    COMP.append((group, comp, note, ig, c, vt))


seg_ig = {"S0": "Truss_S0", "S1": "Truss_S1", "P1": "Truss_P1", "S3": "Truss_S3", "P3": "Truss_P3",
          "S4": "Truss_S4", "P4": "Truss_P4", "S5": "Truss_S5", "P5": "Truss_P5", "S6": "Truss_S6",
          "P6": "Truss_P6", "Z1": "Z1"}
seg_c = {"S0": "s0-ani.lwo#L1", "S1": "s1-ani.lwo#L1", "P1": "p1-ani.lwo#L1", "S3": "s3-ani.lwo#L1",
         "P3": "p3-ani.lwo#L1", "S4": "s4-ani.lwo#L1", "P4": "p4-ani.lwo#L1", "S5": "S5.lwo#L1",
         "P5": "P5.lwo#L1", "S6": "s6-ani.lwo#L1", "P6": "p6-ani.lwo#L1", "Z1": "z1-ext_01.lwo#L1"}
seg_vt = {"S0": "14 S0 Truss", "S1": "16 S1 Truss", "P1": "17 P1 Truss", "S3": "22 S3 Truss",
          "P3": "19 P3 Truss", "S4": "23 S4 Truss", "P4": "20 P4 Truss", "S5": "24 S5 Truss",
          "P5": "21 P5 Truss", "S6": "32 S6 Truss", "P6": "08 P6 Truss", "Z1": "06 Z1 Truss"}
def main_cluster_y(P, gap=3.0):
    """drop vertex clusters separated from the main body by a gap > `gap` m along Y (stray parts)."""
    y = np.sort(P[:, 1])
    cuts = np.where(np.diff(y) > gap)[0]
    if len(cuts) == 0:
        return np.ones(len(P), bool)
    edges = np.concatenate([[y[0] - 1], (y[cuts] + y[cuts + 1]) / 2, [y[-1] + 1]])
    lab = np.digitize(P[:, 1], edges)
    best = np.bincount(lab).argmax()
    return lab == best


def c_truss_filter(pv):
    def f(P):
        keep = main_cluster_y(P)
        if pv:
            keep &= P[:, 2] < 2.8
        return keep
    return f


for s in ["P6", "P5", "P4", "P3", "P1", "S0", "S1", "S3", "S4", "S5", "S6", "Z1"]:
    pv = s in ("S4", "P4", "S6", "P6")
    add("truss", f"{s} truss segment", "main structure mesh; PVR panels excluded" if pv else "main structure mesh",
        ig=(lambda s=s, pv=pv: ig_box([seg_ig[s]], not_pvr if pv else None)),
        c=(lambda s=s, pv=pv: c_box(seg_c[s], filt=c_truss_filter(pv))),
        vt=(lambda s=s: vt_box_raw(seg_vt[s])))

for s in ["P6", "P4", "S4", "S6"]:
    add("PVR", f"{s} PVR (photovoltaic radiator) panels", "panel region only (Z > 3.8 m)",
        ig=(lambda s=s: ig_box([seg_ig[s]], is_pvr)),
        c=(lambda s=s: c_box(seg_c[s], surf="iearad")))

# solar array wings: IGOAL names; C and VTAD split by X sign of the PVM pair
wings = [("P6", "P6_4B_Array", "4B", "aft", "papo-ani_w_goldcells.lwo#L1", "08 P6 Truss_01"),
         ("P6", "P6_2B_Array", "2B", "fwd", "papo-ani_w_goldcells.lwo#L1", "08 P6 Truss_02"),
         ("P4", "P4_Array_2A", "2A", "aft", "papi-ani_w_goldcells.lwo#L1", "20 P4 Truss_01"),
         ("P4", "P4_Array_4A", "4A", "fwd", "papi-ani_w_goldcells.lwo#L1", "20 P4 Truss_02"),
         ("S4", "S4_Array_3A", "3A", "aft", "pasi-ani_w_goldcells.lwo#L1", "23 S4 Truss_01"),
         ("S4", "S4_Array_1A", "1A", "fwd", "pasi-ani_w_goldcells.lwo#L1", "23 S4 Truss_02"),
         ("S6", "S6_1B_Array", "1B", "aft", "paso-ani_w_goldcells.lwo#L1", "32 S6 Truss_01"),
         ("S6", "S6_3B_Array", "3B", "fwd", "paso-ani_w_goldcells.lwo#L1", "32 S6 Truss_02")]
for seg, ign, ch, side, cn, vtn in wings:
    add("solar array wing", f"{seg} SAW {ch} ({side})", "legacy wing only, iROSA excluded; pose = model state",
        ig=(lambda ign=ign: ig_box(ig_detail_names(ign))),
        c=(lambda cn=cn, side=side: c_box(cn, filt=aft if side == "aft" else fwd)),
        vt=None)  # VTAD wing nodes are tilted by a 60 deg SARJ pose; kept only in parts_bbox.csv

# HRS radiator ORUs (3 per wing), split along Y bands (IGOAL) / Z bands (model C)
def ig_oru(side, k):
    nm = "S1_Radiator" if side == "S" else "P1_Radiator"
    P = ig_pts(nm)
    P = P[(P[:, 0] < -1.0) & (np.abs(P[:, 2]) < 0.5)]  # panel stack only: no beam/TRRJ hardware, no small fittings
    y = np.abs(P[:, 1])
    bands = [(8.85, 12.75), (12.9, 16.45), (16.6, 20.5)]  # |Y| bands in m (inboard, middle, outboard)
    lo, hi = bands[k]
    Q = P[(y > lo) & (y < hi)]
    return box(Q)


def c_oru(side, k):
    nm = "tcs-s-ani.lwo#L1" if side == "S" else "tcs-p-ani.lwo#L1"
    P, g = c_item(nm)
    Q = P[g["tcsrad"]]
    bands = [(-6.0, -2.0), (-1.6, 1.6), (2.0, 6.0)]  # model C stacks the 3 ORUs along Z
    lo, hi = bands[k]
    return box(Q[(Q[:, 2] > lo) & (Q[:, 2] < hi)])


for side, lab in (("P", "P1"), ("S", "S1")):
    for k, pos in enumerate(("inboard", "middle", "outboard")):
        add("HRS radiator ORU", f"{lab} HRS radiator ORU {pos}",
            "IGOAL: ORUs side by side along Y; model C stacks them along Z (see notes)",
            ig=(lambda side=side, k=k: ig_oru(side, k)),
            c=(lambda side=side, k=k: c_oru(side, k)))
    add("HRS radiator wing", f"{lab} HRS radiator wing (3 ORUs + beam)", "whole radiator node",
        ig=(lambda side=side: ig_box(["S1_Radiator" if side == "S" else "P1_Radiator"])),
        c=(lambda side=side: c_box("tcs-s-ani.lwo#L1" if side == "S" else "tcs-p-ani.lwo#L1")),
        vt=(lambda side=side: vt_box_raw("16 S1 Truss_02" if side == "S" else "17 P1 Truss_02")))

# pressurised modules and main external carriers
mods = [
    ("module", "Destiny US Lab", "", ["USLab"], "lab-ext.lwo#L1", "09 Destiny Space Laboratory"),
    ("module", "Unity Node 1", "", ["Node1"], "node1.lwo#L1", "02 Unity Node 1"),
    ("module", "Harmony Node 2", "", ["Node2"], "node2_wdoors.lwo#L1", "26 Harmony Node 2"),
    ("module", "Tranquility Node 3", "", ["Node3"], "node3-ani.lwo#L1", "37 Tranquility Node 3"),
    ("module", "Columbus", "", ["Columbus"], "columbus.lwo#L1", "27 Columbus Space Laboratory"),
    ("module", "Kibo JEM PM", "", ["JEM_PM"], "jem_layers.lwo#L1", "30 Kibo Space Laboratory (PSM) Pressurized Module"),
    ("module", "Kibo JEM ELM-PS", "", ["JEM_PS"], "jem_layers.lwo#L2", "28 Kibo Space Laboratory (PSM) Pressurized Stowage Module"),
    ("module", "Kibo JEM EF", "", ["JEM_EF"], "jem_layers.lwo#L5", "33 Kibo Space Laboratory Exposed Platform"),
    ("module", "Cupola", "", ["Cupola"], "cupola_open.lwo#L1", "38 Cupola"),
    ("module", "Quest airlock", "", ["Airlock"], "al-ext.lwo#L1", "12 Quest Airlock"),
    ("module", "PMA-1", "", ["PMA1"], "pma1-ext.lwo#L1", "03 (PMA) Pressurized Mating Adapter 1"),
    ("module", "PMA-2", "", ["PMA2"], "pma2-ext.lwo#L1", "04 (PMA) Pressurized Mating Adapter 2"),
    ("module", "PMA-3", "position differs by epoch", ["PMA3"], "pma3-ext.lwo#L1", "07 (PMA) Pressurized Mating Adapter 3"),
    ("module", "Leonardo PMM", "Node1 nadir 2011-2015 (C, VTAD); Node3 fwd 2015+ (IGOAL)", ["PMM"], "PMM.lwo#L1",
     "40 Leonardo_Raffaello Perm Multi-Purpose Logistics Module (PMM)"),
    ("module", "Zarya FGB body", "body only |Y| < 2.6 m", ["Zarya_FGB"], "fgb-ext_layers.lwo#L1", "01 Zarya - (FGB) Funtional Cargo Block"),
    ("module", "Zvezda SM body", "body only |Y| < 2.6 m", ["Zvezda_SM"], "sm-ext.lwo#L1", "05 Zvezda (SM) Service Module"),
    ("module", "Poisk MRM-2", "", ["MRM2"], "MRM2_lo.lwo#L1", "34 Poisk (MRM-2) Mini Research Module"),
    ("module", "Rassvet MRM-1", "", ["MRM1"], "MRM1_no airlock-radiator.lwo#L1", "39 Rassvet (MRM-1) Mini Research Module"),
    ("module", "Pirs DC-1", "2001-2021 only; present in VTAD only", None, None, "13 Pirs Docking Compartment (DC) and Airlock"),
    ("module", "BEAM", "2016+ only; IGOAL only", ["BEAM"], None, None),
    ("carrier", "ELC-1", "", ["ELC_1"], "ELC1.lwo#L1", "35 Express Logistics Carrier (ELC) 1"),
    ("carrier", "ELC-2", "", ["ELC_2"], "ELC2.lwo#L1", "36 Express Logistics Carrier (ELC) 2"),
    ("carrier", "ELC-3", "", ["ELC_3"], "ELC3.lwo#L1", "43 Express Logistics Carrier (ELC) 3"),
    ("carrier", "ELC-4", "", ["ELC_4"], "ELC4.lwo#L1", "41 Express Logistics Carrier (ELC) 4"),
    ("carrier", "ESP-2", "", ["ESP2"], "esp2_lo.lwo#L1", "18 ESP External Stowage Platform 2"),
    ("carrier", "ESP-3", "", ["ESP3"], "ESP3.lwo#L1", "25 (ESP) External Stowage Platform 3"),
    ("carrier", "AMS-02", "2011+", ["AMS"], "AMS2.lwo#L1", "42 Alpha Magnetic Spectrometer (AMS 2)"),
]
sm_body = lambda P: np.abs(P[:, 1]) < 2.6  # noqa: E731
for grp, comp, note, ign, cn, vtn in mods:
    body = comp in ("Zvezda SM body", "Zarya FGB body")
    add(grp, comp, note,
        ig=(lambda ign=ign, body=body: ig_box(ign, sm_body if body else None)) if ign else None,
        c=(lambda cn=cn: c_box(cn)) if cn else None,
        vt=(lambda vtn=vtn: vt_box_raw(vtn)) if vtn else None)


def evaluate():
    res = []
    for grp, comp, note, fi, fc, fv in COMP:
        r = dict(group=grp, component=comp, note=note)
        for key, f in (("IGOAL", fi), ("C", fc), ("VTADraw", fv)):
            r[key] = f() if f is not None else None
        res.append(r)
    return res


def fit_vtad(res):
    """Similarity fit (uniform scale s, translation t) VTAD_raw -> IGOAL on box centres."""
    use = [r for r in res if r["IGOAL"] is not None and r["VTADraw"] is not None
           and r["group"] in ("truss", "module") and r["component"] not in
           ("PMA-3", "Leonardo PMM", "Zarya FGB body", "S4 truss segment", "P4 truss segment", "S6 truss segment",
            "P6 truss segment", "S5 truss segment", "P5 truss segment", "Zvezda SM body", "Z1 truss segment")]
    A = np.array([(r["VTADraw"][0] + r["VTADraw"][1]) / 2 for r in use])
    B = np.array([(r["IGOAL"][0] + r["IGOAL"][1]) / 2 for r in use])
    Am, Bm = A.mean(0), B.mean(0)
    s = float(np.sum((A - Am) * (B - Bm)) / np.sum((A - Am) ** 2))
    t = Bm - s * Am
    resid = np.linalg.norm(s * A + t - B, axis=1)
    return s, t, [r["component"] for r in use], resid


def main():
    res = evaluate()
    s, t, used, resid = fit_vtad(res)
    print(f"VTAD similarity fit on {len(used)} components: scale={s:.4f}  t={np.round(t, 3)}  "
          f"rms resid={np.sqrt(np.mean(resid ** 2)):.3f} m  max={resid.max():.3f} m")
    for u, e in zip(used, resid):
        print(f"    {u:28s} {e:6.3f}")
    s1 = 1.0  # also report pure translation fit
    use = [r for r in res if r["component"] in used]
    A = np.array([(r["VTADraw"][0] + r["VTADraw"][1]) / 2 for r in use])
    B = np.array([(r["IGOAL"][0] + r["IGOAL"][1]) / 2 for r in use])
    t1 = (B - A).mean(0)
    r1 = np.linalg.norm(A + t1 - B, axis=1)
    print(f"VTAD translation-only fit: t={np.round(t1, 3)} rms={np.sqrt(np.mean(r1 ** 2)):.3f} m")
    # C vs IGOAL (no fit: both native origins at the S0 centre)
    cols = ["group", "component", "note"]
    for m in ("IGOAL", "C", "VTAD"):
        cols += [f"{m}_cx", f"{m}_cy", f"{m}_cz", f"{m}_sx", f"{m}_sy", f"{m}_sz"]
    cols += ["dC_center_m", "dVTAD_center_m"]
    out = os.path.join(HERE, "components_iss_frame.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in res:
            row = [r["group"], r["component"], r["note"]]
            cen = {}
            for m in ("IGOAL", "C", "VTAD"):
                b = r["VTADraw"] if m == "VTAD" else r[m]
                if b is None:
                    row += [""] * 6
                    continue
                mn, mx = b
                if m == "VTAD":
                    mn, mx = s * mn + t, s * mx + t
                c = (mn + mx) / 2
                cen[m] = c
                row += [f"{v:.3f}" for v in c] + [f"{v:.3f}" for v in (mx - mn)]
            d = lambda k: f"{np.linalg.norm(cen[k] - cen['IGOAL']):.3f}" if k in cen and "IGOAL" in cen else ""  # noqa: E731
            row += [d("C"), d("VTAD")]
            w.writerow(row)
            print(f"{r['component'][:40]:40s} " + "  ".join(
                f"{m}: c=({cen[m][0]:7.2f},{cen[m][1]:7.2f},{cen[m][2]:6.2f})" for m in ("IGOAL", "C", "VTAD") if m in cen))
    print("wrote", out)
    # joints (IGOAL)
    jout = os.path.join(HERE, "joints_iss_frame.csv")
    with open(jout, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["joint", "node", "origin_X_m", "origin_Y_m", "origin_Z_m", "axis_X", "axis_Y", "axis_Z", "note"])
        for i, n in enumerate(ig_nodes):
            nm = n.get("name", "")
            if not any(k in nm for k in ("ALPHA_ROT", "BETA_ROT", "GAMMA_ROT")):
                continue
            W = IG.world(i)
            o = igoal_to_iss(W[:3, 3])[0]
            R = W[:3, :3] / np.linalg.norm(W[:3, :3], axis=0)
            if "ALPHA" in nm:
                ax = np.array([0.0, 1.0, 0.0])
                note = "SARJ: axis = Y axis (X=0,Z=0); node origin Y is arbitrary on the axis; S3/S4 interface at |Y|~25.9 m"
            elif "GAMMA" in nm:
                ax = np.array([0.0, 1.0, 0.0])
                note = ("TRRJ rig node of IGOAL (origin 6.8 m aft of truss, not a physical hinge line); "
                        "radiator beam centre line is at X~-0.6 m, Z~0 (see HRS rows)")
            else:
                ax = np.array([1.0, 0.0, 0.0])
                note = "BGA: mast axis parallel to X through (Y,Z) of node origin"
            w.writerow([nm.split("_ROT")[0], nm, *[f"{v:.3f}" for v in o], *ax, note])
        # model C pivots of the rotating radiator items (LightWave PivotPosition, inch -> m)
        for it in c_items:
            if it.get("kind") == "object" and it["name"].startswith("tcs-"):
                pv = c_to_iss(it.get("pivot", np.zeros(3)))[0]
                w.writerow(["C " + it["name"], "model C scene pivot", *[f"{v:.3f}" for v in pv], 0, 1, 0,
                            "model C radiator pivot on the truss centre line"])
        # IGOAL radiator beam centre line (two longerons + frames of S1/P1_Radiator)
        for nm in ("S1_Radiator", "P1_Radiator"):
            P = ig_pts(nm)
            B = P[(P[:, 0] > -1.0) & (P[:, 0] < -0.3)]
            c = (B.min(0) + B.max(0)) / 2
            w.writerow([nm + " beam", "IGOAL beam vertices -1.0<X<-0.3 m", f"{c[0]:.3f}", f"{c[1]:.3f}", f"{c[2]:.3f}",
                        0, 1, 0, f"beam box X {B[:, 0].min():.2f}..{B[:, 0].max():.2f} Y {B[:, 1].min():.2f}..{B[:, 1].max():.2f} "
                              f"Z {B[:, 2].min():.2f}..{B[:, 2].max():.2f} m"])
    print("wrote", jout)
    # solar array wing blanket regions (IGOAL; split at the BGA axis +-0.6 m)
    bout = os.path.join(HERE, "saw_blankets_iss_frame.csv")
    beta = {"P4_Array_2A": "PORT_BETA_ROT_2A", "P4_Array_4A": "PORT_BETA_ROT_4A", "P6_2B_Array": "PORT_BETA_ROT_2B",
            "P6_4B_Array": "PORT_BETA_ROT_4B", "S4_Array_1A": "STBD_BETA_ROT_1A", "S4_Array_3A": "STBD_BETA_ROT_3A",
            "S6_1B_Array": "STBD_BETA_ROT_1B", "S6_3B_Array": "STBD_BETA_ROT_3B"}
    with open(bout, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["wing", "part", "Xmin", "Xmax", "Ymin", "Ymax", "Zmin", "Zmax", "BGA_axis_Y", "BGA_axis_Z"])
        for wing, bn in beta.items():
            o = igoal_to_iss(IG.world(ig_index[bn])[:3, 3])[0]
            P = ig_pts(wing)
            dz = P[:, 2] - o[2]
            for part, m in (("blanket +Z", dz > 0.6), ("blanket -Z", dz < -0.6), ("mast band", np.abs(dz) <= 0.6),
                            ("whole wing", np.ones(len(P), bool))):
                Q = P[m]
                w.writerow([wing, part, *[f"{v:.3f}" for v in (Q[:, 0].min(), Q[:, 0].max(), Q[:, 1].min(), Q[:, 1].max(),
                                                                Q[:, 2].min(), Q[:, 2].max())], f"{o[1]:.3f}", f"{o[2]:.3f}"])
    print("wrote", bout)


if __name__ == "__main__":
    main()
