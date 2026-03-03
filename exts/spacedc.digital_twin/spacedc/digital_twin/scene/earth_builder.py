"""
============================================================
  earth_builder.py — Build USD Earth + Atmosphere + Sun + Stars
  Migrated from: js/orbit3d.js (Earth, clouds, atmos, sun, stars)
============================================================

  Creates the full orbital scene as USD prims using Omniverse Kit API.
  The scene hierarchy:

  /World
    /Earth              — Sphere with NASA Blue Marble material
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
from typing import Optional

try:
    from pxr import Usd, UsdGeom, UsdLux, UsdShade, Sdf, Gf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False

# ── Scene constants ─────────────────────────────────────────
EARTH_RADIUS = 200.0            # scene units (cm in Kit default)
ORBIT_RADIUS = EARTH_RADIUS * 1.7
ORBIT_TILT_DEG = 7.6            # SSO ~97.6° inclination visual tilt
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


def build_earth_scene(stage: "Usd.Stage", root_path: str = "/World") -> None:
    """
    Construct the full Earth orbit scene on the given USD stage.
    """
    if not HAS_USD:
        raise RuntimeError("pxr (OpenUSD) not available — run inside Omniverse Kit")

    # Ensure root Xform
    root = UsdGeom.Xform.Define(stage, root_path)

    # ── Earth Sphere ────────────────────────────────────────
    earth_path = f"{root_path}/Earth"
    earth = UsdGeom.Sphere.Define(stage, earth_path)
    earth.GetRadiusAttr().Set(EARTH_RADIUS)
    earth.GetDisplayColorAttr().Set([Gf.Vec3f(0.1, 0.3, 0.6)])

    # Apply OmniPBR material for Earth (placeholder — real shader needs MDL)
    _create_earth_material(stage, earth_path)

    # ── Clouds ──────────────────────────────────────────────
    clouds_path = f"{root_path}/Clouds"
    clouds = UsdGeom.Sphere.Define(stage, clouds_path)
    clouds.GetRadiusAttr().Set(EARTH_RADIUS * 1.009)
    clouds.GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 1.0, 1.0)])
    clouds.GetPrim().GetAttribute("primvars:displayOpacity").Set(Vt.FloatArray([0.3]))

    # ── Atmosphere glow layers ──────────────────────────────
    atmos_scales = [1.015, 1.04, 1.08, 1.14]
    atmos_colors = [
        Gf.Vec3f(0.55, 0.78, 1.0),
        Gf.Vec3f(0.40, 0.65, 1.0),
        Gf.Vec3f(0.30, 0.55, 1.0),
        Gf.Vec3f(0.20, 0.40, 0.9),
    ]
    atmos_opacities = [0.15, 0.08, 0.04, 0.02]
    for i, (s, c, a) in enumerate(zip(atmos_scales, atmos_colors, atmos_opacities)):
        apath = f"{root_path}/Atmosphere/Layer{i}"
        atmo = UsdGeom.Sphere.Define(stage, apath)
        atmo.GetRadiusAttr().Set(EARTH_RADIUS * s)
        atmo.GetDisplayColorAttr().Set([c])
        atmo.GetPrim().GetAttribute("primvars:displayOpacity").Set(Vt.FloatArray([a]))

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
    # Apply orbit tilt
    xf = UsdGeom.Xformable(curves.GetPrim())
    xf.ClearXformOpOrder()
    xf.AddRotateXOp().Set(ORBIT_TILT_DEG)

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
    # Aim toward origin
    _xform(sun_light, rotate=(160.0, -35.0, 0.0))

    # ── Stars (Points prim) ─────────────────────────────────
    import random
    stars_path = f"{root_path}/Stars"
    star_count = 5000
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
    widths = Vt.FloatArray([1.0 + random.random() * 1.5 for _ in range(star_count)])
    stars.GetWidthsAttr().Set(widths)
    stars.GetDisplayColorAttr().Set([Gf.Vec3f(0.92, 0.94, 1.0)])

    # ── Info label (text) ───────────────────────────────────
    # (Omniverse text requires omni.kit; placeholder Xform with metadata)
    info_path = f"{root_path}/InfoLabel"
    info_xform = UsdGeom.Xform.Define(stage, info_path)
    info_xform.GetPrim().SetMetadata("comment", "SSO 550km · T=95.7min · i=97.6°")


def _create_earth_material(stage: "Usd.Stage", earth_prim_path: str) -> None:
    """
    Create a basic OmniPBR material for Earth and bind it.
    Real deployment should use full MDL with day/night shader.
    """
    mat_path = f"{earth_prim_path}/Material"
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(0.12, 0.38, 0.65)
    )
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.7)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(
        stage.GetPrimAtPath(earth_prim_path)
    ).Bind(mat)


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
    prim = stage.GetPrimAtPath(sat_prim_path)
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
