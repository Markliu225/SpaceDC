"""Color the full LUMID assembly using PBR materials.

Loads D:/USD_Exports/LUMID_fullassembly.usdc and writes a copy with three
UsdPreviewSurface materials bound via UsdGeomSubset:

    bus body     -> brushed gold MLI (metallic 0.85, low-mid roughness)
    solar panels -> monocrystalline silicon — very dark base, glass-like
                    (metallic 0.0, very low roughness so the sun produces a
                    sharp specular highlight; subtle blue diffuse)
    masts        -> brushed aluminum (metallic 0.9, mid roughness)

Output: usd/assets/LUMID_colored.usdc
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom, UsdShade, Sdf, Vt


SRC = Path("D:/USD_Exports/LUMID_fullassembly.usdc")
DST = Path("C:/Workspace/SpaceDC/space-compute-demo/usd/assets/LUMID_colored.usdc")

BUS_X = (-101.0, 325.0)
BUS_Y = (  96.0, 394.0)
BUS_Z = ( -78.0, 306.0)


def make_preview_material(stage, path, *, diffuse, metallic, roughness, ior=1.5,
                          spec_color=None) -> UsdShade.Material:
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(diffuse)
    shader.CreateInput("metallic",  Sdf.ValueTypeNames.Float).Set(metallic)
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("ior",       Sdf.ValueTypeNames.Float).Set(ior)
    shader.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)
    if spec_color is not None:
        shader.CreateInput("specularColor", Sdf.ValueTypeNames.Color3f).Set(spec_color)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def main() -> None:
    print(f"[color] reading {SRC}")
    src_stage = Usd.Stage.Open(str(SRC))
    src_mesh_prim = src_stage.GetPrimAtPath("/LUMIDSatellite/Mesh")
    if not src_mesh_prim:
        print("[color] /LUMIDSatellite/Mesh not found", file=sys.stderr); sys.exit(1)
    src_mesh = UsdGeom.Mesh(src_mesh_prim)

    pts = np.array(src_mesh.GetPointsAttr().Get(), dtype=np.float32)
    fvc = np.array(src_mesh.GetFaceVertexCountsAttr().Get(), dtype=np.int32)
    fvi = np.array(src_mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int32)
    tri = fvi.reshape(-1, 3)
    cent = pts[tri].mean(axis=1)
    x, y, z = cent[:, 0], cent[:, 1], cent[:, 2]
    n = len(tri)

    in_bus = (
        (x > BUS_X[0]) & (x < BUS_X[1]) &
        (y > BUS_Y[0]) & (y < BUS_Y[1]) &
        (z > BUS_Z[0]) & (z < BUS_Z[1])
    )
    is_xpanel = (x < -460) | (x > 460)
    is_zpanel = (z < -300) | (z > 530)
    is_panel  = (~in_bus) & (is_xpanel | is_zpanel)
    is_mast   = (~in_bus) & (~is_panel)

    bus_idx   = np.nonzero(in_bus)[0].astype(np.int32)
    panel_idx = np.nonzero(is_panel)[0].astype(np.int32)
    mast_idx  = np.nonzero(is_mast)[0].astype(np.int32)
    print(f"[color] faces: {n}  bus={len(bus_idx)} panel={len(panel_idx)} mast={len(mast_idx)}")

    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists():
        DST.unlink()
    out = Usd.Stage.CreateNew(str(DST))
    UsdGeom.SetStageMetersPerUnit(out, 0.001)
    UsdGeom.SetStageUpAxis(out, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(out, "/LUMIDSatellite")
    out.SetDefaultPrim(root.GetPrim())

    # Materials — store under /LUMIDSatellite/Looks
    looks = UsdGeom.Scope.Define(out, "/LUMIDSatellite/Looks")
    mat_bus = make_preview_material(
        out, "/LUMIDSatellite/Looks/MLIGold",
        diffuse=(0.78, 0.58, 0.18), metallic=0.85, roughness=0.35,
    )
    # Monocrystalline silicon: not actually metal, but the glass cover gives
    # a strong specular reflection.  Model as low-metallic, low-roughness
    # dielectric with a deep navy base color.  IOR ~1.5 (glass).
    mat_panel = make_preview_material(
        out, "/LUMIDSatellite/Looks/MonoSi",
        diffuse=(0.018, 0.025, 0.055), metallic=0.10, roughness=0.12, ior=1.55,
        spec_color=(0.55, 0.65, 0.85),
    )
    mat_mast = make_preview_material(
        out, "/LUMIDSatellite/Looks/Aluminum",
        diffuse=(0.62, 0.64, 0.68), metallic=0.90, roughness=0.30,
    )

    # Mesh
    mesh = UsdGeom.Mesh.Define(out, "/LUMIDSatellite/Mesh")
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(pts))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(fvc))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(fvi))
    mesh.CreateDoubleSidedAttr(True)
    # Apply MaterialBindingAPI so subset bindings work.
    mesh.GetPrim().ApplyAPI(UsdShade.MaterialBindingAPI)

    def add_subset(name: str, idx: np.ndarray, mat: UsdShade.Material) -> None:
        ss = UsdGeom.Subset.Define(out, f"/LUMIDSatellite/Mesh/{name}")
        ss.CreateElementTypeAttr().Set(UsdGeom.Tokens.face)
        ss.CreateFamilyNameAttr().Set("materialBind")
        ss.CreateIndicesAttr().Set(Vt.IntArray.FromNumpy(idx))
        UsdShade.MaterialBindingAPI(ss.GetPrim()).Bind(mat)

    add_subset("Bus",   bus_idx,   mat_bus)
    add_subset("Panel", panel_idx, mat_panel)
    add_subset("Mast",  mast_idx,  mat_mast)

    out.GetRootLayer().Save()
    print(f"[color] wrote {DST}  (3 PBR materials via subsets)")


if __name__ == "__main__":
    main()
