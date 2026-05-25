"""Import the SATELLITE.stl mesh from Inventor and write a USD asset.

The user's STL is at:
  D:/BaiduNetdiskDownload/022-卫星空间站-卫星空间站 STEP/.../Satellite/SATELLITE.stl
in millimetres, exported with the VisCAM/SolidView per-face color extension
(2-byte attribute = 5-5-5 RGB + valid bit). Each unique color becomes a
GeomSubset bound to a UsdPreviewSurface material.

If per-face colors are absent or trivial (single color), fall back to a
spatial-region classifier: bus body, solar panels (the wing extents),
dish/antenna (forward cylinder cap), structural masts.

Output: usd/assets/Satellite_v022.usdc
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom, UsdShade, Sdf, Vt


SRC = Path(r"D:/BaiduNetdiskDownload/022-卫星空间站-卫星空间站 STEP/022-卫星空间站-卫星空间站 STEP/Satellite/SATELLITE.stl")
DST = Path("C:/Workspace/SpaceDC/space-compute-demo/usd/assets/Satellite_v022.usdc")


def read_binary_stl(path: Path):
    """Return (points Nx3, fvi Mx3, attr M) — vertices, triangle indices, per-face attribute."""
    raw = path.read_bytes()
    header = raw[:80]
    ntri = struct.unpack('<I', raw[80:84])[0]
    print(f"[stl] header head bytes: {header[:32]!r}")
    print(f"[stl] triangles: {ntri}")
    # Each triangle = 12 (normal) + 36 (3 verts) + 2 (attr) = 50 bytes
    expected = 84 + ntri * 50
    if len(raw) != expected:
        raise RuntimeError(f"size mismatch: got {len(raw)}, expected {expected}")
    body = np.frombuffer(raw[84:], dtype=np.uint8).reshape(ntri, 50)
    # Vertices: bytes 12..48 = 9 floats
    verts = body[:, 12:48].copy().view('<f4').reshape(ntri, 3, 3)
    attr = body[:, 48:50].copy().view('<u2').reshape(ntri)
    # Build unique vertex array via lex-sort
    flat = verts.reshape(-1, 3)
    keys = (flat * 1e3).round().astype(np.int64)
    # Hash each vertex into a unique key
    key1d = keys[:, 0] * 1_000_000_000_017 + keys[:, 1] * 1_000_003 + keys[:, 2]
    uniq, inv = np.unique(key1d, return_inverse=True)
    # Build the unique vertex positions
    points = np.zeros((len(uniq), 3), dtype=np.float32)
    # For each unique key take the first occurrence's vertex
    first_idx = np.full(len(uniq), -1, dtype=np.int64)
    for i, k in enumerate(key1d):
        u = inv[i]
        if first_idx[u] == -1:
            first_idx[u] = i
            points[u] = flat[i]
    fvi = inv.reshape(ntri, 3).astype(np.int32)
    print(f"[stl] unique vertices: {len(points)}")
    return points, fvi, attr


def decode_viscam_color(attr: np.ndarray) -> np.ndarray | None:
    """Decode VisCAM 5-5-5 RGB color from attribute. Returns Nx3 float in [0,1] or None."""
    valid_bit = (attr >> 15) & 1
    if valid_bit.sum() < len(attr) * 0.1:
        # fewer than 10% have valid color bit — probably not VisCAM colors
        return None
    r = ((attr >> 10) & 0x1F) / 31.0
    g = ((attr >> 5) & 0x1F) / 31.0
    b = (attr & 0x1F) / 31.0
    return np.stack([r, g, b], axis=-1).astype(np.float32)


def make_preview_material(stage, path, *, diffuse, metallic, roughness, ior=1.5):
    mat = UsdShade.Material.Define(stage, path)
    sh = UsdShade.Shader.Define(stage, f"{path}/Shader")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(diffuse)
    sh.CreateInput("metallic",  Sdf.ValueTypeNames.Float).Set(metallic)
    sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    sh.CreateInput("ior",       Sdf.ValueTypeNames.Float).Set(ior)
    sh.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    return mat


# Spatial classification: based on the assembly preview, the satellite has:
#   * Central cylindrical bus body (the brightly-coloured drum in the middle)
#   * Two big circular dish reflectors (front & back along bus axis)
#   * Solar panels extending out as wings (XY plane far from bus center)
#   * Booms / masts (long thin members between bus and panels)
# The STL is in mm. We orient with bus axis = X (largest dim usually).

def classify_faces(points: np.ndarray, fvi: np.ndarray) -> np.ndarray:
    """Return per-face class index: 0=bus, 1=panel, 2=dish, 3=boom."""
    centroids = points[fvi].mean(axis=1)
    bbox_min = points.min(axis=0)
    bbox_max = points.max(axis=0)
    bbox_center = (bbox_min + bbox_max) * 0.5
    bbox_size = bbox_max - bbox_min
    # Identify the longest axis = solar panel wing-span axis
    span_axis = int(np.argmax(bbox_size))
    bus_axis_candidates = [i for i in range(3) if i != span_axis]
    # Among the other two axes, the bus axis is the one with the larger
    # extent (the bus cylinder is long along that axis).
    bus_axis = max(bus_axis_candidates, key=lambda i: bbox_size[i])
    short_axis = [i for i in (0, 1, 2) if i not in (span_axis, bus_axis)][0]
    print(f"[classify] span_axis={span_axis} bus_axis={bus_axis} short_axis={short_axis}")
    print(f"[classify] bbox_size mm: {bbox_size}")

    # Distance from bus center along span axis
    s = np.abs(centroids[:, span_axis] - bbox_center[span_axis])
    # Distance from bus axis (perpendicular)
    a = centroids[:, bus_axis] - bbox_center[bus_axis]
    b = centroids[:, short_axis] - bbox_center[short_axis]
    radial = np.sqrt(a * a + b * b)
    # Bus radius rough estimate: 25% of the smaller of (bus_axis_extent, short_axis_extent)
    bus_radius_est = 0.30 * min(bbox_size[bus_axis], bbox_size[short_axis])
    panel_inner_dist = 0.30 * bbox_size[span_axis]   # panels start 30% out from center

    cls = np.zeros(len(fvi), dtype=np.int32)  # default = bus
    is_panel = (s > panel_inner_dist) & (radial < 0.5 * bbox_size[short_axis])
    is_dish  = (np.abs(centroids[:, bus_axis] - bbox_center[bus_axis]) > 0.40 * bbox_size[bus_axis]) & (s < panel_inner_dist)
    is_boom  = (s > 0.10 * bbox_size[span_axis]) & (s <= panel_inner_dist) & (radial < 0.10 * bbox_size[short_axis])
    cls[is_dish]  = 2
    cls[is_panel] = 1
    cls[is_boom]  = 3
    bus = (cls == 0).sum()
    pnl = (cls == 1).sum()
    dsh = (cls == 2).sum()
    bom = (cls == 3).sum()
    print(f"[classify] faces  bus={bus}  panel={pnl}  dish={dsh}  boom={bom}")
    return cls


def main() -> None:
    if not SRC.exists():
        print(f"[err] STL not found: {SRC}", file=sys.stderr); sys.exit(1)

    points, fvi, attr = read_binary_stl(SRC)
    print(f"[stl] bbox min: {points.min(axis=0)}")
    print(f"[stl] bbox max: {points.max(axis=0)}")

    colors = decode_viscam_color(attr)
    use_colors = colors is not None and len(np.unique(colors.view('V12'))) > 1
    print(f"[stl] per-face VisCAM colors found: {use_colors}")

    cls = classify_faces(points, fvi)

    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists():
        DST.unlink()
    out = Usd.Stage.CreateNew(str(DST))
    UsdGeom.SetStageMetersPerUnit(out, 0.001)   # STL is in mm
    UsdGeom.SetStageUpAxis(out, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(out, "/Satellite")
    out.SetDefaultPrim(root.GetPrim())

    # Materials matching the assembly preview (gold bus, dark-blue solar
    # panels, polished aluminum dish, aluminum booms).
    looks = UsdGeom.Scope.Define(out, "/Satellite/Looks")
    mat_bus   = make_preview_material(out, "/Satellite/Looks/BusGold",
                                      diffuse=(0.78, 0.58, 0.18), metallic=0.85, roughness=0.30)
    mat_panel = make_preview_material(out, "/Satellite/Looks/SolarPanel",
                                      diffuse=(0.04, 0.07, 0.20), metallic=0.10, roughness=0.18, ior=1.55)
    mat_dish  = make_preview_material(out, "/Satellite/Looks/DishAlu",
                                      diffuse=(0.78, 0.80, 0.84), metallic=0.92, roughness=0.18)
    mat_boom  = make_preview_material(out, "/Satellite/Looks/BoomAlu",
                                      diffuse=(0.62, 0.64, 0.68), metallic=0.85, roughness=0.40)

    mesh = UsdGeom.Mesh.Define(out, "/Satellite/Mesh")
    counts = np.full(len(fvi), 3, dtype=np.int32)
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(counts))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(fvi.flatten().astype(np.int32)))
    mesh.CreateDoubleSidedAttr(True)
    mesh.GetPrim().ApplyAPI(UsdShade.MaterialBindingAPI)

    def add_subset(name: str, idx: np.ndarray, mat) -> None:
        if len(idx) == 0:
            return
        ss = UsdGeom.Subset.Define(out, f"/Satellite/Mesh/{name}")
        ss.CreateElementTypeAttr().Set(UsdGeom.Tokens.face)
        ss.CreateFamilyNameAttr().Set("materialBind")
        ss.CreateIndicesAttr().Set(Vt.IntArray.FromNumpy(idx.astype(np.int32)))
        UsdShade.MaterialBindingAPI(ss.GetPrim()).Bind(mat)

    add_subset("Bus",   np.nonzero(cls == 0)[0], mat_bus)
    add_subset("Panel", np.nonzero(cls == 1)[0], mat_panel)
    add_subset("Dish",  np.nonzero(cls == 2)[0], mat_dish)
    add_subset("Boom",  np.nonzero(cls == 3)[0], mat_boom)

    out.GetRootLayer().Save()
    print(f"[ok] wrote {DST}")


if __name__ == "__main__":
    main()
