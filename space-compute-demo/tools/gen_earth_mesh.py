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


# Mirror gen_twin_satellite's cloud constants — the overview must read
# exactly like the twin close-up.
CLOUD_SCALE = 1.008
CLOUD_OPACITY = 0.55


def _tex_shader(stage, mat_path: str, name: str, file: str,
                scale=None, bias=None) -> UsdShade.Shader:
    """A UsdUVTexture reader wired to the shared St primvar reader —
    the SAME graph shape the twin stage's EarthMat/CloudMat use."""
    tex = UsdShade.Shader.Define(stage, f"{mat_path}/{name}")
    tex.CreateIdAttr("UsdUVTexture")
    tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(file)
    if scale is not None:
        tex.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*scale))
    if bias is not None:
        tex.CreateInput("bias", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*bias))
    st = UsdShade.Shader.Define(stage, f"{mat_path}/St")
    st.CreateIdAttr("UsdPrimvarReader_float2")
    st.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    tex.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
        st.CreateOutput("result", Sdf.ValueTypeNames.Float2))
    return tex


def _build_material(stage: Usd.Stage) -> UsdShade.Material:
    """The SAME UsdPreviewSurface stack as the twin close-up's EarthMat
    (which is proven to render correctly in this project's RTX viewport):
    8K day diffuse, no emissive (dark side goes dark), ocean-specular mask
    inverted into roughness for sun glints on water."""
    mat_path = "/World/Earth/Looks/EarthMaterial"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, mat_path + "/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)

    day = _tex_shader(stage, mat_path, "Day", "./textures/earth_day.jpg")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        day.CreateOutput("rgb", Sdf.ValueTypeNames.Float3))
    rough = _tex_shader(stage, mat_path, "Rough", "./textures/earth_spec.jpg",
                        scale=(-0.75, -0.75, -0.75, 1.0),
                        bias=(0.95, 0.95, 0.95, 0.0))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).ConnectToSource(
        rough.CreateOutput("r", Sdf.ValueTypeNames.Float))

    mat.CreateSurfaceOutput().ConnectToSource(
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token))
    return mat


def _build_cloud_material(stage: Usd.Stage) -> UsdShade.Material:
    """Cloud shell — the twin's CloudMat verbatim: white diffuse with the
    cloud map (scaled to CLOUD_OPACITY) driving UsdPreviewSurface opacity."""
    mat_path = "/World/Earth/Looks/CloudMaterial"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, mat_path + "/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(1.0, 1.0, 1.0))
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
    shader.CreateInput("opacityThreshold", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)

    tex = _tex_shader(stage, mat_path, "Tex", "./textures/earth_clouds.jpg",
                      scale=(CLOUD_OPACITY, CLOUD_OPACITY, CLOUD_OPACITY, 1.0))
    shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).ConnectToSource(
        tex.CreateOutput("r", Sdf.ValueTypeNames.Float))

    mat.CreateSurfaceOutput().ConnectToSource(
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token))
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
