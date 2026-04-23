"""Generate a high-poly UV sphere as usd/earth_mesh.usda with explicit `st` primvar
so UsdPreviewSurface + UsdUVTexture can apply the NASA Blue Marble equirectangular
textures correctly.

Usage (from repo root):
    backend/.venv/Scripts/python.exe tools/gen_earth_mesh.py
"""
from __future__ import annotations

import math
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt  # type: ignore

OUT = Path(__file__).resolve().parent.parent / "usd" / "earth_mesh.usda"

RADIUS = 63.71      # km-scaled (matches root.usda metersPerUnit = 100000, 1 unit = 100 km)
LAT_SEGMENTS = 96   # vertical slices
LON_SEGMENTS = 192  # horizontal slices


def build_sphere(radius: float, lat_n: int, lon_n: int):
    points: list[Gf.Vec3f] = []
    uvs: list[Gf.Vec2f] = []

    # duplicate the seam column so UVs map correctly without wrap
    for i in range(lat_n + 1):
        v = i / lat_n
        theta = v * math.pi           # 0..pi, from north pole to south pole
        sin_t = math.sin(theta)
        cos_t = math.cos(theta)
        for j in range(lon_n + 1):
            u = j / lon_n
            phi = u * 2.0 * math.pi   # 0..2pi
            # Z-up: x = r * sin(theta) * cos(phi), y = r * sin(theta) * sin(phi), z = r * cos(theta)
            x = radius * sin_t * math.cos(phi)
            y = radius * sin_t * math.sin(phi)
            z = radius * cos_t
            points.append(Gf.Vec3f(x, y, z))
            # Equirectangular UVs matching NASA Blue Marble layout:
            #   u  -> longitude left to right
            #   v  -> 0 at south pole (bottom) to 1 at north pole (top)
            uvs.append(Gf.Vec2f(u, 1.0 - v))

    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    for i in range(lat_n):
        for j in range(lon_n):
            a = i * (lon_n + 1) + j
            b = a + 1
            c = a + (lon_n + 1)
            d = c + 1
            face_vertex_counts.append(4)
            face_vertex_indices.extend([a, c, d, b])
    return points, uvs, face_vertex_counts, face_vertex_indices


def _build_material(stage: Usd.Stage) -> UsdShade.Material:
    """OmniPBR MDL material with NASA Blue Marble day texture + night-side emissive.

    Omniverse RTX renders via MDL; UsdPreviewSurface texture inputs aren't reliably
    picked up by RTX, so we use the stock OmniPBR.mdl shipped with Omniverse.
    """
    mat_path = "/World/Earth/Looks/EarthMaterial"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, mat_path + "/Shader")
    shader.GetPrim().GetAttribute("info:implementationSource").Set("sourceAsset") if shader.GetPrim().HasAttribute("info:implementationSource") else None
    shader.SetSourceAsset("OmniPBR.mdl", "mdl")
    shader.SetSourceAssetSubIdentifier("OmniPBR", "mdl")

    # Day texture (albedo)
    shader.CreateInput("diffuse_texture", Sdf.ValueTypeNames.Asset).Set("./textures/earth_day.jpg")
    shader.CreateInput("diffuse_tint", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(1.0, 1.0, 1.0))
    shader.CreateInput("metallic_constant", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(0.85)

    # Night-side lights as emissive
    shader.CreateInput("enable_emission", Sdf.ValueTypeNames.Bool).Set(True)
    shader.CreateInput("emissive_color_texture", Sdf.ValueTypeNames.Asset).Set("./textures/earth_night.jpg")
    shader.CreateInput("emissive_color", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(1.0, 0.85, 0.55))
    shader.CreateInput("emissive_intensity", Sdf.ValueTypeNames.Float).Set(3.0)

    # Connect MDL surface output to material (Omniverse RTX queries via 'mdl' render context)
    out = shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput("mdl").ConnectToSource(out)
    mat.CreateDisplacementOutput("mdl").ConnectToSource(out)
    mat.CreateVolumeOutput("mdl").ConnectToSource(out)

    return mat


def main() -> None:
    points, uvs, fvc, fvi = build_sphere(RADIUS, LAT_SEGMENTS, LON_SEGMENTS)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(OUT))
    UsdGeom.SetStageMetersPerUnit(stage, 100000)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)

    # Parent scope so sublayering into root.usda composes at /World/Earth
    UsdGeom.Xform.Define(stage, "/World")

    mesh_prim = UsdGeom.Mesh.Define(stage, "/World/Earth")
    mesh_prim.CreatePointsAttr(Vt.Vec3fArray(points))
    mesh_prim.CreateFaceVertexCountsAttr(Vt.IntArray(fvc))
    mesh_prim.CreateFaceVertexIndicesAttr(Vt.IntArray(fvi))
    mesh_prim.CreateExtentAttr([(-RADIUS, -RADIUS, -RADIUS), (RADIUS, RADIUS, RADIUS)])
    mesh_prim.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)

    pvars = UsdGeom.PrimvarsAPI(mesh_prim)
    st = pvars.CreatePrimvar(
        "st",
        Sdf.ValueTypeNames.TexCoord2fArray,
        interpolation=UsdGeom.Tokens.vertex,
    )
    st.Set(Vt.Vec2fArray(uvs))

    # Attach material + bind to the mesh
    UsdGeom.Scope.Define(stage, "/World/Earth/Looks")
    material = _build_material(stage)
    UsdShade.MaterialBindingAPI.Apply(mesh_prim.GetPrim()).Bind(material)

    stage.Save()
    print(f"wrote {OUT}  verts={len(points)}  tris={len(fvc)}")


if __name__ == "__main__":
    main()
