"""
============================================================
  environment.py — Scene lighting & eclipse transitions
  Migrated from: js/orbit3d.js (sunLight, eclipse effects)
============================================================
"""
from __future__ import annotations

import os

try:
    from pxr import Usd, UsdLux, UsdGeom, Gf, Sdf
    HAS_USD = True
except ImportError:
    HAS_USD = False


def _get_texture_dir() -> str:
    """Resolve absolute path to extension data/textures/ folder."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    ext_root = os.path.normpath(os.path.join(this_dir, "..", "..", ".."))
    tex_dir = os.path.join(ext_root, "data", "textures")
    if os.path.isdir(tex_dir):
        return tex_dir
    env_root = os.environ.get("SPACEDC_ROOT", "")
    if env_root:
        alt = os.path.join(env_root, "data", "textures")
        if os.path.isdir(alt):
            return alt
    return tex_dir


# ── Lighting presets ────────────────────────────────────────

SUNLIT_INTENSITY = 5000.0
ECLIPSE_INTENSITY = 50.0
SUNLIT_COLOR = Gf.Vec3f(1.0, 0.96, 0.88) if HAS_USD else (1.0, 0.96, 0.88)
ECLIPSE_COLOR = Gf.Vec3f(0.2, 0.25, 0.5) if HAS_USD else (0.2, 0.25, 0.5)

# Keep macro lighting as close as possible to a single solar key light so the
# terminator stays crisp and the night side does not pick up stray HDRI fill.
ORBIT_AMBIENT_INTENSITY = 0.0
ORBIT_DOME_INTENSITY = 0.0

# Micro view still benefits from environment reflections on metallic surfaces.
MICRO_DOME_INTENSITY = 260.0
ECLIPSE_AMBIENT_INTENSITY = 0.0
ECLIPSE_DOME_INTENSITY = 8.0


def _set_light_shadows(light_schema_or_prim, enabled: bool) -> None:
    """Enable or disable shadow casting for a light prim."""
    prim = light_schema_or_prim.GetPrim() if hasattr(light_schema_or_prim, "GetPrim") else light_schema_or_prim
    if not prim or not prim.IsValid():
        return
    shadow_api = UsdLux.ShadowAPI.Apply(prim)
    shadow_api.CreateShadowEnableAttr().Set(enabled)


def setup_environment(stage: "Usd.Stage", root_path: str = "/World") -> None:
    """Create ambient and dome lights for the scene."""
    if not HAS_USD:
        return

    # Ambient light
    amb_path = f"{root_path}/Lights/Ambient"
    amb = UsdLux.DistantLight.Define(stage, amb_path)
    amb.GetIntensityAttr().Set(ORBIT_AMBIENT_INTENSITY)
    amb.GetColorAttr().Set(Gf.Vec3f(0.08, 0.08, 0.09))
    _set_light_shadows(amb, False)

    # Dome light with starfield HDRI for space background
    dome_path = f"{root_path}/Lights/DomeLight"
    dome = UsdLux.DomeLight.Define(stage, dome_path)
    dome.GetIntensityAttr().Set(ORBIT_DOME_INTENSITY)
    dome.GetColorAttr().Set(Gf.Vec3f(1.0, 1.0, 1.0))

    # Bind starfield HDR texture
    tex_dir = _get_texture_dir()
    hdr_path = os.path.join(tex_dir, "starfield.hdr")
    if os.path.isfile(hdr_path):
        # Use forward slashes for USD asset paths
        hdr_asset = hdr_path.replace("\\", "/")
        dome.GetTextureFileAttr().Set(hdr_asset)
        dome.GetTextureFormatAttr().Set("latlong")
        print(f"[SpaceDC] Starfield HDRI bound: {hdr_asset}")
    else:
        # Fallback: very dark blue — no starfield
        dome.GetColorAttr().Set(Gf.Vec3f(0.01, 0.02, 0.05))
        print(f"[SpaceDC] Starfield HDR not found at {hdr_path}, using dark color")


def update_environment_for_eclipse(
    stage: "Usd.Stage",
    eclipse: bool,
    sun_light_path: str = "/World/Sun/SunLight",
    ambient_path: str = "/World/Lights/Ambient",
    dome_path: str = "/World/Lights/DomeLight",
) -> None:
    """
    Transition lighting between eclipse and sunlit states.
    Mirrors the JS ``sunLight.intensity = eclipse ? 0.06 : 2.2`` logic.
    """
    if not HAS_USD:
        return

    # Sun
    sun_prim = stage.GetPrimAtPath(sun_light_path)
    if sun_prim.IsValid():
        sun = UsdLux.DistantLight(sun_prim)
        sun.GetIntensityAttr().Set(ECLIPSE_INTENSITY if eclipse else SUNLIT_INTENSITY)
        color = ECLIPSE_COLOR if eclipse else SUNLIT_COLOR
        sun.GetColorAttr().Set(color)

    # Ambient
    amb_prim = stage.GetPrimAtPath(ambient_path)
    if amb_prim.IsValid():
        amb = UsdLux.DistantLight(amb_prim)
        amb.GetIntensityAttr().Set(ECLIPSE_AMBIENT_INTENSITY if eclipse else ORBIT_AMBIENT_INTENSITY)

    dome_prim = stage.GetPrimAtPath(dome_path)
    if dome_prim.IsValid():
        dome = UsdLux.DomeLight(dome_prim)
        dome.GetIntensityAttr().Set(ECLIPSE_DOME_INTENSITY if eclipse else ORBIT_DOME_INTENSITY)


def set_view_lighting_mode(
    stage: "Usd.Stage",
    micro_view: bool,
    ambient_path: str = "/World/Lights/Ambient",
    dome_path: str = "/World/Lights/DomeLight",
) -> None:
    """Switch lighting balance between crisp macro Earth view and reflective micro detail view."""
    if not HAS_USD:
        return

    amb_prim = stage.GetPrimAtPath(ambient_path)
    if amb_prim.IsValid():
        amb = UsdLux.DistantLight(amb_prim)
        amb.GetIntensityAttr().Set(0.0)

    dome_prim = stage.GetPrimAtPath(dome_path)
    if dome_prim.IsValid():
        dome = UsdLux.DomeLight(dome_prim)
        dome.GetIntensityAttr().Set(MICRO_DOME_INTENSITY if micro_view else ORBIT_DOME_INTENSITY)


def update_earth_rotation(
    stage: "Usd.Stage",
    earth_path: str = "/World/Earth",
    clouds_path: str = "/World/Clouds",
    rotation_y: float = 0.0,
) -> None:
    """Rotate Earth and clouds meshes (called each tick)."""
    if not HAS_USD:
        return

    earth_prim = stage.GetPrimAtPath(earth_path)
    if earth_prim.IsValid():
        xf = UsdGeom.Xformable(earth_prim)
        ops = xf.GetOrderedXformOps()
        if ops and ops[0].GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            ops[0].Set(Gf.Vec3f(0, rotation_y, 0))
        else:
            xf.ClearXformOpOrder()
            xf.AddRotateXYZOp().Set(Gf.Vec3f(0, rotation_y, 0))

    clouds_prim = stage.GetPrimAtPath(clouds_path)
    if clouds_prim.IsValid():
        xf = UsdGeom.Xformable(clouds_prim)
        ops = xf.GetOrderedXformOps()
        if ops and ops[0].GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            ops[0].Set(Gf.Vec3f(0, rotation_y * 1.06 + 17, 0))
        else:
            xf.ClearXformOpOrder()
            xf.AddRotateXYZOp().Set(Gf.Vec3f(0, rotation_y * 1.06 + 17, 0))
