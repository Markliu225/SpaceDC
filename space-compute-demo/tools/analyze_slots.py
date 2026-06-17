"""Find the server-slot shelves inside the backbone racks.

The four rack parts (tripo_part_0/4 upper, tripo_part_3/5 lower) each carry a
short stack of horizontal open shelf-frames. This script bins each rack's
triangle area by world Z to locate the shelf bands (peaks) and the empty slots
between them, and reports per-rack X/Y footprint so gen_twin_satellite.py can
drop a server blade into every slot.

Run:
    python tools/analyze_slots.py
"""
import json
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "assets_raw" / "SpaceDcBackbone.usdz"

RACKS = {
    "upper_+Y": "tripo_part_0",
    "upper_-Y": "tripo_part_4",
    "lower_+Y": "tripo_part_5",
    "lower_-Y": "tripo_part_3",
}

stage = Usd.Stage.Open(str(PATH))
xfc = UsdGeom.XformCache(Usd.TimeCode.Default())


def part_world_tris(part_name):
    for prim in stage.Traverse():
        if prim.GetName() == part_name and prim.IsA(UsdGeom.Xform):
            # collect child meshes
            pts_all, tris_all = [], []
            base = 0
            for d in Usd.PrimRange(prim):
                if not d.IsA(UsdGeom.Mesh):
                    continue
                m = UsdGeom.Mesh(d)
                pts = m.GetPointsAttr().Get()
                counts = m.GetFaceVertexCountsAttr().Get() or []
                idx = m.GetFaceVertexIndicesAttr().Get() or []
                if not pts:
                    continue
                M = np.array(xfc.GetLocalToWorldTransform(d), dtype=np.float64).reshape(4, 4)
                P = np.array([[p[0], p[1], p[2], 1.0] for p in pts]) @ M
                P = P[:, :3] / P[:, 3:4]
                i = 0
                for c in counts:
                    for k in range(1, c - 1):
                        tris_all.append((base + idx[i], base + idx[i + k], base + idx[i + k + 1]))
                    i += c
                pts_all.append(P)
                base += len(pts)
            if not pts_all:
                return None
            V = np.vstack(pts_all)
            T = np.array(tris_all, dtype=np.int64)
            return V, T
    return None


report = {}
for label, part in RACKS.items():
    res = part_world_tris(part)
    if res is None:
        print(f"{label}: NOT FOUND"); continue
    V, T = res
    tv = V[T]
    cen = tv.mean(axis=1)
    area = 0.5 * np.linalg.norm(np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0]), axis=1)
    zmin, zmax = cen[:, 2].min(), cen[:, 2].max()
    nb = 60
    hist, edges = np.histogram(cen[:, 2], bins=nb, range=(zmin, zmax), weights=area)
    # smooth
    k = np.array([1, 2, 3, 2, 1], dtype=float); k /= k.sum()
    sm = np.convolve(hist, k, mode="same")
    centers = 0.5 * (edges[:-1] + edges[1:])
    # peaks = shelf plates
    peaks = []
    for i in range(1, nb - 1):
        if sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > sm.max() * 0.30:
            peaks.append((centers[i], sm[i]))
    # merge near-duplicate peaks (<2cm apart)
    peaks.sort()
    merged = []
    for z, w in peaks:
        if merged and abs(z - merged[-1][0]) < 0.02:
            if w > merged[-1][1]:
                merged[-1] = (z, w)
        else:
            merged.append((z, w))
    report[label] = {
        "part": part,
        "x_range": [round(float(V[:, 0].min()), 4), round(float(V[:, 0].max()), 4)],
        "y_range": [round(float(V[:, 1].min()), 4), round(float(V[:, 1].max()), 4)],
        "z_range": [round(float(V[:, 2].min()), 4), round(float(V[:, 2].max()), 4)],
        "shelf_z": [round(float(z), 4) for z, _ in merged],
        "n_shelves": len(merged),
    }
    print(f"{label:10s} {part:14s} x={report[label]['x_range']} y={report[label]['y_range']} "
          f"z={report[label]['z_range']}  shelves@Z={report[label]['shelf_z']}")

out = ROOT / "tools" / "slots_report.json"
out.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("[wrote]", out)
