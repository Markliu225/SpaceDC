"""
============================================================
  earth_builder.py — Build USD Earth + Atmosphere + Sun + Stars
  Migrated from: js/orbit3d.js (Earth, clouds, atmos, sun, stars)
============================================================

  Creates the full orbital scene as USD prims using Omniverse Kit API.
  The scene hierarchy:

  /World
    /Earth              — Mesh sphere with NASA Blue Marble texture (UVs)
    /Clouds             — Slightly larger transparent sphere
    /Atmosphere         — Multi-layer rim-lit spheres
    /OrbitRing          — BasisCurves circle at orbit radius
    /Sun                — Emissive sphere + DistantLight
    /Stars              — Points prim with 5000 star positions
    /InfoLabel          — Billboard text
"""
from __future__ import annotations

import math
import os
import random
from typing import Optional, Tuple, List

try:
    from pxr import Usd, UsdGeom, UsdLux, UsdShade, Sdf, Gf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False


def _get_texture_dir() -> str:
    """Resolve absolute path to extension data/textures/ folder."""
    # Walk up from this file: scene/ → digital_twin/ → spacedc/ → ext root
    this_dir = os.path.dirname(os.path.abspath(__file__))
    ext_root = os.path.normpath(os.path.join(this_dir, "..", "..", ".."))
    tex_dir = os.path.join(ext_root, "data", "textures")
    if os.path.isdir(tex_dir):
        return tex_dir
    # Fallback: try SPACEDC_ROOT env var
    env_root = os.environ.get("SPACEDC_ROOT", "")
    if env_root:
        alt = os.path.join(env_root, "data", "textures")
        if os.path.isdir(alt):
            return alt
    return tex_dir  # return anyway, will just get placeholder material


def _generate_sphere_mesh(
    radius: float,
    rings: int = 64,
    segments: int = 128,
) -> Tuple[
    List[Gf.Vec3f],   # points
    List[Gf.Vec3f],   # normals
    List[Gf.Vec2f],   # uvs (per face-vertex)
    List[int],         # faceVertexCounts
    List[int],         # faceVertexIndices
]:
    """
    Generate a UV-mapped sphere mesh (equirectangular / lat-long mapping).
    Returns points, normals, UVs, face counts and face indices suitable
    for a UsdGeom.Mesh with 'faceVarying' UV interpolation.
    """
    points = []
    normals = []

    # Generate vertex positions (rings+1 rows × segments+1 cols for UV seam)
    for r in range(rings + 1):
        phi = math.pi * r / rings          # 0 → π  (north pole → south pole)
        for s in range(segments + 1):
            theta = 2.0 * math.pi * s / segments  # 0 → 2π
            x = math.sin(phi) * math.cos(theta)
            y = math.cos(phi)
            z = math.sin(phi) * math.sin(theta)
            points.append(Gf.Vec3f(x * radius, y * radius, z * radius))
            normals.append(Gf.Vec3f(x, y, z))

    faceVertexCounts = []
    faceVertexIndices = []
    uvs = []

    cols = segments + 1

    for r in range(rings):
        for s in range(segments):
            # Quad vertex indices (CCW winding)
            v0 = r * cols + s
            v1 = r * cols + (s + 1)
            v2 = (r + 1) * cols + (s + 1)
            v3 = (r + 1) * cols + s

            faceVertexCounts.append(4)
            faceVertexIndices.extend([v0, v1, v2, v3])

            # UV coords (faceVarying — one per face-vertex)
            u0 = s / segments
            u1 = (s + 1) / segments
            v_top = 1.0 - r / rings           # V=1 at north pole, V=0 at south
            v_bot = 1.0 - (r + 1) / rings

            uvs.append(Gf.Vec2f(u0, v_top))
            uvs.append(Gf.Vec2f(u1, v_top))
            uvs.append(Gf.Vec2f(u1, v_bot))
            uvs.append(Gf.Vec2f(u0, v_bot))

    return points, normals, uvs, faceVertexCounts, faceVertexIndices


def _generate_hemisphere_mesh(
    radius: float,
    rings: int = 40,
    segments: int = 96,
) -> Tuple[
    List[Gf.Vec3f],   # points
    List[Gf.Vec3f],   # normals
    List[int],         # faceVertexCounts
    List[int],         # faceVertexIndices
]:
    """
    Generate an outward-facing hemisphere centered on the origin.

    The hemisphere is aligned so its pole points along +X. This makes it easy
    to rotate toward the anti-sun direction and use it as a stable night-side
    darkening shell around Earth.
    """
    points = []
    normals = []

    for r in range(rings + 1):
        alpha = (0.5 * math.pi) * r / rings  # 0 -> pi/2
        x = math.cos(alpha)
        rr = math.sin(alpha)
        for s in range(segments + 1):
            beta = 2.0 * math.pi * s / segments
            y = rr * math.cos(beta)
            z = rr * math.sin(beta)
            points.append(Gf.Vec3f(x * radius, y * radius, z * radius))
            normals.append(Gf.Vec3f(x, y, z))

    face_vertex_counts = []
    face_vertex_indices = []
    cols = segments + 1

    for r in range(rings):
        for s in range(segments):
            v0 = r * cols + s
            v1 = r * cols + (s + 1)
            v2 = (r + 1) * cols + (s + 1)
            v3 = (r + 1) * cols + s
            face_vertex_counts.append(4)
            face_vertex_indices.extend([v0, v1, v2, v3])

    return points, normals, face_vertex_counts, face_vertex_indices

# ── Scene constants ─────────────────────────────────────────
EARTH_RADIUS = 200.0            # scene units (cm in Kit default)
ORBIT_RADIUS = EARTH_RADIUS * 1.7
ORBIT_INCLINATION_DEG = 97.6    # default SSO inclination (used by RotateX on orbit ring)
ORBIT_TILT_DEG = ORBIT_INCLINATION_DEG   # alias kept for backward compat
SUN_DISTANCE = 1500.0

# NASA texture URLs (to be downloaded or shipped as assets)
TEX_DAY   = "earth_day_blue_marble.jpg"
TEX_NIGHT = "earth_night.jpg"
TEX_BUMP  = "earth_topology.png"


# ── Xform helper (Kit-safe, replaces XformCommonAPI) ───────

def _xform(schema_or_prim, translate=None, rotate=None, scale=None):
    """Set translate / rotate / scale via Xformable ops."""
    prim = schema_or_prim.GetPrim() if hasattr(schema_or_prim, "GetPrim") else schema_or_prim
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    if translate is not None:
        xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if rotate is not None:
        xf.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
    if scale is not None:
        xf.AddScaleOp().Set(Gf.Vec3d(*scale))


def _set_light_shadows(light_schema_or_prim, enabled: bool) -> None:
    """Enable or disable shadow casting for a light prim."""
    prim = light_schema_or_prim.GetPrim() if hasattr(light_schema_or_prim, "GetPrim") else light_schema_or_prim
    if not prim or not prim.IsValid():
        return
    shadow_api = UsdLux.ShadowAPI.Apply(prim)
    shadow_api.CreateShadowEnableAttr().Set(enabled)


def _disable_cast_shadows(prim) -> None:
    """Disable RTX cast shadows on a geometry prim."""
    if hasattr(prim, "GetPrim"):
        prim = prim.GetPrim()
    if not prim or not prim.IsValid():
        return
    prim.CreateAttribute(
        "primvars:doNotCastShadows",
        Sdf.ValueTypeNames.Bool,
        custom=False,
    ).Set(True)


def _set_orient_from_x_axis(prim, direction: Tuple[float, float, float]) -> None:
    """Rotate a prim so its local +X axis points toward ``direction``."""
    if hasattr(prim, "GetPrim"):
        prim = prim.GetPrim()
    if not prim or not prim.IsValid():
        return

    vec = Gf.Vec3d(*direction)
    if vec.GetLength() < 1e-6:
        return
    vec.Normalize()

    rotation = Gf.Rotation(Gf.Vec3d(1.0, 0.0, 0.0), vec)
    quat = rotation.GetQuat()
    orient = Gf.Quatf(
        float(quat.GetReal()),
        Gf.Vec3f(
            float(quat.GetImaginary()[0]),
            float(quat.GetImaginary()[1]),
            float(quat.GetImaginary()[2]),
        ),
    )

    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    xf.AddOrientOp().Set(orient)


def _set_orient_from_neg_z_axis(prim, direction: Tuple[float, float, float]) -> None:
    """Rotate a prim so its local -Z axis points toward ``direction``."""
    if hasattr(prim, "GetPrim"):
        prim = prim.GetPrim()
    if not prim or not prim.IsValid():
        return

    vec = Gf.Vec3d(*direction)
    if vec.GetLength() < 1e-6:
        return
    vec.Normalize()

    rotation = Gf.Rotation(Gf.Vec3d(0.0, 0.0, -1.0), vec)
    quat = rotation.GetQuat()
    orient = Gf.Quatf(
        float(quat.GetReal()),
        Gf.Vec3f(
            float(quat.GetImaginary()[0]),
            float(quat.GetImaginary()[1]),
            float(quat.GetImaginary()[2]),
        ),
    )

    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    xf.AddOrientOp().Set(orient)


def build_earth_scene(stage: "Usd.Stage", root_path: str = "/World") -> None:
    """
    Construct the full Earth orbit scene on the given USD stage.
    """
    if not HAS_USD:
        raise RuntimeError("pxr (OpenUSD) not available — run inside Omniverse Kit")

    # Ensure root Xform
    root = UsdGeom.Xform.Define(stage, root_path)

    # ── Earth Mesh (with UV coordinates for texture mapping) ──
    earth_path = f"{root_path}/Earth"
    pts, nrm, uvs, fvc, fvi = _generate_sphere_mesh(EARTH_RADIUS, rings=64, segments=128)

    earth_mesh = UsdGeom.Mesh.Define(stage, earth_path)
    earth_mesh.GetPointsAttr().Set(Vt.Vec3fArray(pts))
    earth_mesh.GetNormalsAttr().Set(Vt.Vec3fArray(nrm))
    earth_mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
    earth_mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(fvc))
    earth_mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(fvi))
    earth_mesh.GetSubdivisionSchemeAttr().Set("none")   # don't subdivide

    # Set UV primvar 'st' as faceVarying so texture mapping works
    pv_api = UsdGeom.PrimvarsAPI(earth_mesh.GetPrim())
    st_pv = pv_api.CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray,
                                  UsdGeom.Tokens.faceVarying)
    st_pv.Set(Vt.Vec2fArray(uvs))

    # NOTE: No DisplayColor — the material texture will provide the color.
    # Apply Blue Marble material
    _create_earth_material(stage, earth_path)
    stage.RemovePrim(f"{root_path}/EarthNightMask")

    # ── Clouds (disabled — implicit Sphere has no transparency in RTX) ──
    # clouds_path = f"{root_path}/Clouds"
    # clouds = UsdGeom.Sphere.Define(stage, clouds_path)
    # clouds.GetRadiusAttr().Set(EARTH_RADIUS * 1.009)
    # clouds.GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 1.0, 1.0)])
    # clouds.GetPrim().GetAttribute("primvars:displayOpacity").Set(Vt.FloatArray([0.3]))

    # ── Atmosphere glow layers (disabled — would obscure textured Earth) ──
    # atmos_scales = [1.015, 1.04, 1.08, 1.14]
    # atmos_colors = [
    #     Gf.Vec3f(0.55, 0.78, 1.0),
    #     Gf.Vec3f(0.40, 0.65, 1.0),
    #     Gf.Vec3f(0.30, 0.55, 1.0),
    #     Gf.Vec3f(0.20, 0.40, 0.9),
    # ]
    # atmos_opacities = [0.15, 0.08, 0.04, 0.02]
    # for i, (s, c, a) in enumerate(zip(atmos_scales, atmos_colors, atmos_opacities)):
    #     apath = f"{root_path}/Atmosphere/Layer{i}"
    #     atmo = UsdGeom.Sphere.Define(stage, apath)
    #     atmo.GetRadiusAttr().Set(EARTH_RADIUS * s)
    #     atmo.GetDisplayColorAttr().Set([c])
    #     atmo.GetPrim().GetAttribute("primvars:displayOpacity").Set(Vt.FloatArray([a]))

    # ── Orbit ring (BasisCurves) ────────────────────────────
    orbit_path = f"{root_path}/OrbitRing"
    n_pts = 256
    points = []
    for i in range(n_pts + 1):
        a = (i / n_pts) * math.pi * 2.0
        x = math.cos(a) * ORBIT_RADIUS
        z = math.sin(a) * ORBIT_RADIUS
        points.append(Gf.Vec3f(x, 0, z))

    curves = UsdGeom.BasisCurves.Define(stage, orbit_path)
    curves.GetPointsAttr().Set(Vt.Vec3fArray(points))
    curves.GetCurveVertexCountsAttr().Set(Vt.IntArray([n_pts + 1]))
    curves.GetTypeAttr().Set(UsdGeom.Tokens.linear)
    curves.GetDisplayColorAttr().Set([Gf.Vec3f(0.0, 0.55, 1.0)])
    _disable_cast_shadows(curves)
    # Apply orbit tilt — must match get_orbit_position() which uses
    # inclination directly as RotateX angle in the XZ plane.
    xf = UsdGeom.Xformable(curves.GetPrim())
    xf.ClearXformOpOrder()
    xf.AddRotateXOp().Set(ORBIT_INCLINATION_DEG)

    # ── Sun ─────────────────────────────────────────────────
    sun_path = f"{root_path}/Sun"
    sun_xform = UsdGeom.Xform.Define(stage, sun_path)
    _xform(sun_xform,
           translate=(-SUN_DISTANCE, SUN_DISTANCE * 0.33, SUN_DISTANCE * 0.53))

    sun_sphere = UsdGeom.Sphere.Define(stage, f"{sun_path}/Sphere")
    sun_sphere.GetRadiusAttr().Set(42.0)
    sun_sphere.GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 0.97, 0.86)])

    # Distant light for sun illumination
    sun_light = UsdLux.DistantLight.Define(stage, f"{sun_path}/SunLight")
    sun_light.GetIntensityAttr().Set(5000.0)
    sun_light.GetColorAttr().Set(Gf.Vec3f(1.0, 0.96, 0.88))
    _set_light_shadows(sun_light, False)
    # Aim toward the Earth origin so the illumination direction matches the
    # visible Sun sphere position in the scene.
    _set_orient_from_neg_z_axis(
        sun_light,
        (SUN_DISTANCE, -SUN_DISTANCE * 0.33, -SUN_DISTANCE * 0.53),
    )

    # ── Stars (Points prim) ─────────────────────────────────
    import random
    stars_path = f"{root_path}/Stars"
    star_count = 1200
    star_pts = []
    for _ in range(star_count):
        r = 8000.0 + random.random() * 8000.0
        theta = random.random() * math.pi * 2
        phi = math.acos(2 * random.random() - 1)
        x = r * math.sin(phi) * math.cos(theta)
        y = r * math.sin(phi) * math.sin(theta)
        z = r * math.cos(phi)
        star_pts.append(Gf.Vec3f(x, y, z))

    stars = UsdGeom.Points.Define(stage, stars_path)
    stars.GetPointsAttr().Set(Vt.Vec3fArray(star_pts))
    widths = Vt.FloatArray([0.45 + random.random() * 0.65 for _ in range(star_count)])
    stars.GetWidthsAttr().Set(widths)
    stars.GetDisplayColorAttr().Set([Gf.Vec3f(0.52, 0.54, 0.60)])

    # ── Info label (text) ───────────────────────────────────
    # (Omniverse text requires omni.kit; placeholder Xform with metadata)
    info_path = f"{root_path}/InfoLabel"
    info_xform = UsdGeom.Xform.Define(stage, info_path)
    info_xform.GetPrim().SetMetadata("comment", "SSO 550km · T=95.7min · i=97.6°")


def _create_earth_material(stage: "Usd.Stage", earth_prim_path: str) -> None:
    """
    Create a UsdPreviewSurface material with Blue Marble texture for Earth.
    Falls back to solid color if texture file is not found.
    """
    mat_path = f"{earth_prim_path}/Material"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.98)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("specularColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.0, 0.0, 0.0))
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    # Try to bind Blue Marble texture
    tex_dir = _get_texture_dir()
    day_path = os.path.join(tex_dir, "earth_day.jpg")

    if os.path.isfile(day_path):
        # Create UsdUVTexture reader node
        tex_reader = UsdShade.Shader.Define(stage, f"{mat_path}/DayTexture")
        tex_reader.CreateIdAttr("UsdUVTexture")
        tex_reader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(day_path.replace("\\", "/"))
        tex_reader.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
        tex_reader.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("repeat")
        tex_reader.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)

        # Create ST (UV) reader — sphere prims have built-in UVs
        st_reader = UsdShade.Shader.Define(stage, f"{mat_path}/UVReader")
        st_reader.CreateIdAttr("UsdPrimvarReader_float2")
        st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
        st_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

        # Connect UV → texture → shader
        tex_reader.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            st_reader.ConnectableAPI(), "result"
        )
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
            tex_reader.ConnectableAPI(), "rgb"
        )
        print(f"[SpaceDC] Earth texture bound: {day_path}")
    else:
        # Fallback: solid ocean blue
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(0.12, 0.38, 0.65)
        )
        print(f"[SpaceDC] Earth texture not found at {day_path}, using solid color")

    UsdShade.MaterialBindingAPI(
        stage.GetPrimAtPath(earth_prim_path)
    ).Bind(mat)


def _create_earth_night_mask(stage: "Usd.Stage", root_path: str) -> None:
    """
    Add a stable night-side overlay so Earth keeps a clean terminator without
    looking like a flat gray shell. The overlay uses the shipped night texture
    plus a dark blue base to suggest city lights and true night color.
    """
    mask_path = f"{root_path}/EarthNightMask"
    pts, nrm, uvs, fvc, fvi = _generate_sphere_mesh(EARTH_RADIUS * 1.0002, rings=64, segments=128)

    mask = UsdGeom.Mesh.Define(stage, mask_path)
    mask.GetPointsAttr().Set(Vt.Vec3fArray(pts))
    mask.GetNormalsAttr().Set(Vt.Vec3fArray(nrm))
    mask.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
    mask.GetFaceVertexCountsAttr().Set(Vt.IntArray(fvc))
    mask.GetFaceVertexIndicesAttr().Set(Vt.IntArray(fvi))
    mask.GetSubdivisionSchemeAttr().Set("none")
    mask.GetDoubleSidedAttr().Set(False)
    _disable_cast_shadows(mask)

    pv_api = UsdGeom.PrimvarsAPI(mask.GetPrim())
    st_pv = pv_api.CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    st_pv.Set(Vt.Vec2fArray(uvs))

    sun_dir = (-SUN_DISTANCE, SUN_DISTANCE * 0.33, SUN_DISTANCE * 0.53)
    sun_vec = Gf.Vec3f(*sun_dir)
    sun_len = max(sun_vec.GetLength(), 1e-6)
    sun_vec = Gf.Vec3f(sun_vec[0] / sun_len, sun_vec[1] / sun_len, sun_vec[2] / sun_len)

    opacities = []
    for normal in nrm:
        ndotl = (normal[0] * sun_vec[0]) + (normal[1] * sun_vec[1]) + (normal[2] * sun_vec[2])
        # Sharper twilight band so the lit hemisphere reads clearly.
        t = max(0.0, min(1.0, (-ndotl + 0.04) / 0.42))
        smooth = t * t * (3.0 - 2.0 * t)
        alpha = 0.72 * smooth
        opacities.append(alpha)
    opacity_pv = pv_api.CreatePrimvar("nightMaskOpacity", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex)
    opacity_pv.Set(Vt.FloatArray(opacities))

    mat_path = f"{mask_path}/Material"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.015, 0.025, 0.06))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("specularColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.0, 0.0, 0.0))

    op_reader = UsdShade.Shader.Define(stage, f"{mat_path}/OpacityReader")
    op_reader.CreateIdAttr("UsdPrimvarReader_float")
    op_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("nightMaskOpacity")
    op_reader.CreateOutput("result", Sdf.ValueTypeNames.Float)
    shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).ConnectToSource(
        op_reader.ConnectableAPI(), "result"
    )

    tex_dir = _get_texture_dir()
    night_path = os.path.join(tex_dir, "earth_night.jpg")
    if os.path.isfile(night_path):
        st_reader = UsdShade.Shader.Define(stage, f"{mat_path}/UVReader")
        st_reader.CreateIdAttr("UsdPrimvarReader_float2")
        st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
        st_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

        tex_reader = UsdShade.Shader.Define(stage, f"{mat_path}/NightTexture")
        tex_reader.CreateIdAttr("UsdUVTexture")
        tex_reader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(night_path.replace("\\", "/"))
        tex_reader.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
        tex_reader.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("repeat")
        tex_reader.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            st_reader.ConnectableAPI(), "result"
        )
        tex_reader.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)

        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
            tex_reader.ConnectableAPI(), "rgb"
        )
        print(f"[SpaceDC] Earth night texture bound: {night_path}")
    else:
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.0, 0.0, 0.0))
        print(f"[SpaceDC] Earth night texture not found at {night_path}, using dark night mask")

    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(mask.GetPrim()).Bind(mat)


def update_satellite_position(
    stage: "Usd.Stage",
    sat_prim_path: str,
    sim_time: float,
    orbit_radius: float = ORBIT_RADIUS,
    orbit_inclination: float = 97.6,
    orbit_period: float = 5742.0,
) -> None:
    """
    Move the satellite prim along its orbit based on sim_time and dynamic parameters.
    Call each tick from the simulation engine.
    """
    if not HAS_USD:
        return
    from ..physics.orbital_mechanics import get_orbit_position

    x, y, z = get_orbit_position(sim_time, orbit_radius=orbit_radius, tilt_deg=orbit_inclination, orbit_period=orbit_period)
    set_prim_translation(stage, sat_prim_path, x, y, z)


def set_prim_translation(
    stage: "Usd.Stage",
    prim_path: str,
    x: float,
    y: float,
    z: float,
) -> None:
    """Set or replace the first translate op on a prim."""
    if not HAS_USD:
        return
    prim = stage.GetPrimAtPath(prim_path)
    if prim.IsValid():
        xf = UsdGeom.Xformable(prim)
        ops = xf.GetOrderedXformOps()
        if ops and ops[0].GetOpType() == UsdGeom.XformOp.TypeTranslate:
            ops[0].Set(Gf.Vec3d(x, y, z))
        else:
            xf.ClearXformOpOrder()
            xf.AddTranslateOp().Set(Gf.Vec3d(x, y, z))


def update_eclipse_lighting(
    stage: "Usd.Stage",
    eclipse: bool,
    sun_light_path: str = "/World/Sun/SunLight",
) -> None:
    """Dim/brighten sun light for eclipse/sunlit transitions."""
    if not HAS_USD:
        return
    prim = stage.GetPrimAtPath(sun_light_path)
    if prim.IsValid():
        light = UsdLux.DistantLight(prim)
        light.GetIntensityAttr().Set(50.0 if eclipse else 5000.0)


def update_orbit_ring(
    stage: "Usd.Stage",
    altitude_km: float,
    inclination_deg: float,
    root_path: str = "/World",
) -> None:
    """
    Rebuild the orbit ring BasisCurves to match new altitude & inclination.
    altitude_km → scene radius   (EARTH_RADIUS * (Re+alt)/Re)
    inclination_deg → tilt angle (visual = inclination - 90)
    """
    if not HAS_USD:
        return

    orbit_path = f"{root_path}/OrbitRing"
    prim = stage.GetPrimAtPath(orbit_path)
    if not prim or not prim.IsValid():
        return

    # Convert altitude to visual scene units
    re = 6371.0
    visual_radius = EARTH_RADIUS * (re + altitude_km) / re

    # Rebuild points
    n_pts = 256
    points = []
    for i in range(n_pts + 1):
        a = (i / n_pts) * math.pi * 2.0
        x = math.cos(a) * visual_radius
        z = math.sin(a) * visual_radius
        points.append(Gf.Vec3f(x, 0, z))

    curves = UsdGeom.BasisCurves(prim)
    curves.GetPointsAttr().Set(Vt.Vec3fArray(points))

    # Update tilt — RotateX must match get_orbit_position() which uses
    # inclination_deg directly: sin(incl) → Y component, cos(incl) → Z component.
    # 0° = equatorial (ring flat in XZ), 90° = polar, 97.6° = SSO.
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    xf.AddRotateXOp().Set(inclination_deg)
