"""Cut a rectangular hatch opening in the LUMID cubesat bus.

The LUMID assembly (from D:/USD_Exports/LUMID_fullassembly.usdc) is a single
merged mesh of ~129k triangles with no internal sub-structure — we can't
'hollow out' the interior via USD hierarchy alone. This script removes the
faces on one outer panel of the central bus to expose the interior, so our
DGX stack can be placed inside through that real opening.

Strategy:
  * Pick the -Y face of the central bus as the hatch (it's the bus face most
    exposed to the Overview camera eye at (200, -200, 130)).
  * Bus main-body Y bounds in LUMID native mm: roughly [96, 394].
    So the -Y panel sits near Y ≈ 96 mm.
  * Cut a rectangular window X:[30, 280] mm × Z:[-40, 250] mm on that panel.
  * Remove every triangle whose centroid is inside that 3D slab.

Output: usd/assets/LUMID_hollowed.usdc
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom, Vt


SRC = Path("D:/USD_Exports/LUMID_fullassembly.usdc")
DST_DIR = Path("C:/Workspace/SpaceDC/space-compute-demo/usd/assets")
DST = DST_DIR / "LUMID_hollowed.usdc"

# Hatch slab in LUMID native mm coordinates.
# Bus -Y face is around Y ≈ 96 mm; cut a slab that crosses through it so we
# remove both the outer panel and anything mounted just behind it.
HATCH = {
    "y_min":  30.0,
    "y_max": 260.0,      # slab 230 mm deep into the bus
    "x_min":  30.0,
    "x_max": 285.0,      # hatch width in X
    "z_min": -40.0,
    "z_max": 250.0,      # hatch height in Z
}


def main() -> None:
    print(f"[cut] reading {SRC}")
    stage = Usd.Stage.Open(str(SRC))
    mesh_prim = stage.GetPrimAtPath("/LUMIDSatellite/Mesh")
    if not mesh_prim:
        print("[cut] /LUMIDSatellite/Mesh not found", file=sys.stderr)
        sys.exit(1)
    mesh = UsdGeom.Mesh(mesh_prim)

    pts = np.array(mesh.GetPointsAttr().Get(), dtype=np.float32)
    fvc = np.array(mesh.GetFaceVertexCountsAttr().Get(), dtype=np.int32)
    fvi = np.array(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int32)
    n_faces = len(fvc)
    print(f"[cut] {len(pts)} verts, {n_faces} faces (all tris: {np.all(fvc==3)})")

    # Compute face centroids in one shot (assumes all triangles).
    tri_idx = fvi.reshape(-1, 3)
    centroids = pts[tri_idx].mean(axis=1)  # (n_faces, 3)

    # Keep faces whose centroid is OUTSIDE the hatch slab.
    inside = (
        (centroids[:, 0] >= HATCH["x_min"]) & (centroids[:, 0] <= HATCH["x_max"]) &
        (centroids[:, 1] >= HATCH["y_min"]) & (centroids[:, 1] <= HATCH["y_max"]) &
        (centroids[:, 2] >= HATCH["z_min"]) & (centroids[:, 2] <= HATCH["z_max"])
    )
    keep_mask = ~inside
    n_cut = int(inside.sum())
    n_keep = int(keep_mask.sum())
    print(f"[cut] removing {n_cut} faces, keeping {n_keep} (of {n_faces})")

    if n_cut == 0:
        print("[cut] WARNING: no faces matched the hatch region — check HATCH bounds")

    new_tri = tri_idx[keep_mask]
    new_fvi = new_tri.reshape(-1)
    new_fvc = np.full(n_keep, 3, dtype=np.int32)

    # Write to a fresh stage (no inherited metadata drift).
    DST_DIR.mkdir(parents=True, exist_ok=True)
    out = Usd.Stage.CreateNew(str(DST))
    UsdGeom.SetStageMetersPerUnit(out, 0.001)  # mm, matches source
    UsdGeom.SetStageUpAxis(out, UsdGeom.Tokens.z)

    root = UsdGeom.Xform.Define(out, "/LUMIDSatellite")
    out.SetDefaultPrim(root.GetPrim())

    mesh_out = UsdGeom.Mesh.Define(out, "/LUMIDSatellite/Mesh")
    mesh_out.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(pts))
    mesh_out.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(new_fvc))
    mesh_out.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(new_fvi))

    # Preserve display color (same gray as original).
    prim_src = mesh.GetPrim()
    for name in ("primvars:displayColor", "primvars:displayOpacity"):
        a = prim_src.GetAttribute(name)
        if a.IsValid() and a.Get() is not None:
            mesh_out.GetPrim().CreateAttribute(name, a.GetTypeName()).Set(a.Get())

    # Hint to hydra that the mesh is double-sided so the newly-exposed interior
    # edges read from both sides.
    mesh_out.CreateDoubleSidedAttr(True)

    out.GetRootLayer().Save()
    print(f"[cut] wrote {DST}")


if __name__ == "__main__":
    main()
