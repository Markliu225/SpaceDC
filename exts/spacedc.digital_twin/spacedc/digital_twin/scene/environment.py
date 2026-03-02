"""
============================================================
  environment.py — Scene lighting & eclipse transitions
  Migrated from: js/orbit3d.js (sunLight, eclipse effects)
============================================================
"""
from __future__ import annotations

try:
    from pxr import Usd, UsdLux, UsdGeom, Gf
    HAS_USD = True
except ImportError:
    HAS_USD = False


# ── Lighting presets ────────────────────────────────────────

SUNLIT_INTENSITY = 5000.0
ECLIPSE_INTENSITY = 50.0
SUNLIT_COLOR = Gf.Vec3f(1.0, 0.96, 0.88) if HAS_USD else (1.0, 0.96, 0.88)
ECLIPSE_COLOR = Gf.Vec3f(0.2, 0.25, 0.5) if HAS_USD else (0.2, 0.25, 0.5)

AMBIENT_SUNLIT = 0.35
AMBIENT_ECLIPSE = 0.05


def setup_environment(stage: "Usd.Stage", root_path: str = "/World") -> None:
    """Create ambient and dome lights for the scene."""
    if not HAS_USD:
        return

    # Ambient light
    amb_path = f"{root_path}/Lights/Ambient"
    amb = UsdLux.DistantLight.Define(stage, amb_path)
    amb.GetIntensityAttr().Set(200.0)
    amb.GetColorAttr().Set(Gf.Vec3f(0.04, 0.08, 0.19))

    # Optional: HDRI dome light for star-field environment
    dome_path = f"{root_path}/Lights/DomeLight"
    dome = UsdLux.DomeLight.Define(stage, dome_path)
    dome.GetIntensityAttr().Set(100.0)
    dome.GetColorAttr().Set(Gf.Vec3f(0.01, 0.02, 0.05))


def update_environment_for_eclipse(
    stage: "Usd.Stage",
    eclipse: bool,
    sun_light_path: str = "/World/Sun/SunLight",
    ambient_path: str = "/World/Lights/Ambient",
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
        amb.GetIntensityAttr().Set(20.0 if eclipse else 200.0)


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
