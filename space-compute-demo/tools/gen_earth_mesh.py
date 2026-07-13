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


# Mirror gen_twin_satellite's cloud shell size; the 0.55 airiness is BAKED
# into earth_clouds.jpg (single source of truth for both stages).
CLOUD_SCALE = 1.008


def _build_material(stage: Usd.Stage) -> UsdShade.Material:
    """OmniPBR MDL — the material stack that is PROVEN in this stage (the
    UsdPreviewSurface rewrite rendered black-grey here): 8K day diffuse
    plus a DIM self-emissive of the same day map so the night side stays
    readable without city lights."""
    mat_path = "/World/Earth/Looks/EarthMaterial"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, mat_path + "/Shader")
    shader.SetSourceAsset("OmniPBR.mdl", "mdl")
    shader.SetSourceAssetSubIdentifier("OmniPBR", "mdl")

    # Day texture (albedo)
    shader.CreateInput("diffuse_texture", Sdf.ValueTypeNames.Asset).Set("./textures/earth_day.jpg")
    shader.CreateInput("diffuse_tint", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(1.0, 1.0, 1.0))
    shader.CreateInput("metallic_constant", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(0.85)

    # Dim self-emissive of the day map — night-side readability (the same
    # role EARTH_EMIT plays in the twin stage), NOT the city-lights map.
    shader.CreateInput("enable_emission", Sdf.ValueTypeNames.Bool).Set(True)
    shader.CreateInput("emissive_color_texture", Sdf.ValueTypeNames.Asset).Set("./textures/earth_day.jpg")
    shader.CreateInput("emissive_color", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(1.0, 1.0, 1.0))
    shader.CreateInput("emissive_intensity", Sdf.ValueTypeNames.Float).Set(1.0)

    out = shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput("mdl").ConnectToSource(out)
    mat.CreateDisplacementOutput("mdl").ConnectToSource(out)
    mat.CreateVolumeOutput("mdl").ConnectToSource(out)

    return mat


def _build_cloud_material(stage: Usd.Stage) -> UsdShade.Material:
    """Cloud shell — OmniPBR with the opacity TEXTURE actually enabled
    (enable_opacity alone ignores opacity_texture and rendered the shell
    as an opaque white ball — the earlier 'white Earth'). The airiness is
    baked into the texture, so no multiplier semantics are involved."""
    mat_path = "/World/Earth/Looks/CloudMaterial"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, mat_path + "/Shader")
    shader.SetSourceAsset("OmniPBR.mdl", "mdl")
    shader.SetSourceAssetSubIdentifier("OmniPBR", "mdl")

    shader.CreateInput("diffuse_tint", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(1.0, 1.0, 1.0))
    shader.CreateInput("metallic_constant", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(1.0)
    shader.CreateInput("enable_opacity", Sdf.ValueTypeNames.Bool).Set(True)
    shader.CreateInput("enable_opacity_texture", Sdf.ValueTypeNames.Bool).Set(True)
    shader.CreateInput("opacity_texture", Sdf.ValueTypeNames.Asset).Set("./textures/earth_clouds.jpg")
    shader.CreateInput("opacity_constant", Sdf.ValueTypeNames.Float).Set(1.0)

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

    # Cloud shell — a slightly larger sphere as a CHILD of the Earth mesh
    # (inherits any Earth rotation), cloud map as opacity, same look as the
    # twin close-up.
    cpts, cuvs, cfvc, cfvi = build_sphere(RADIUS * CLOUD_SCALE, 64, 128)
    cloud_prim = UsdGeom.Mesh.Define(stage, "/World/Earth/Clouds")
    cloud_prim.CreatePointsAttr(Vt.Vec3fArray(cpts))
    cloud_prim.CreateFaceVertexCountsAttr(Vt.IntArray(cfvc))
    cloud_prim.CreateFaceVertexIndicesAttr(Vt.IntArray(cfvi))
    r_c = RADIUS * CLOUD_SCALE
    cloud_prim.CreateExtentAttr([(-r_c, -r_c, -r_c), (r_c, r_c, r_c)])
    cloud_prim.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    cst = UsdGeom.PrimvarsAPI(cloud_prim).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray,
        interpolation=UsdGeom.Tokens.vertex)
    cst.Set(Vt.Vec2fArray(cuvs))
    cloud_mat = _build_cloud_material(stage)
    UsdShade.MaterialBindingAPI.Apply(cloud_prim.GetPrim()).Bind(cloud_mat)

    stage.Save()
    print(f"wrote {OUT}  verts={len(points)}+{len(cpts)}  tris={len(fvc)}+{len(cfvc)}")


if __name__ == "__main__":
    main()
