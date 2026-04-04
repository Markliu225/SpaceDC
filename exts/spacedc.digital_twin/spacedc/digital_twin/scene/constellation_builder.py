"""
============================================================
  constellation_builder.py - USD builder for TLE constellation markers
============================================================

  Renders a lightweight constellation layer:
    - one colored point marker per satellite
    - one orbit curve per satellite
    - metadata on each prim for selection / detail handoff
"""
from __future__ import annotations

try:
    from pxr import UsdGeom, UsdShade, Sdf, Gf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False

from ..physics.constellation import sample_orbit_scene_points, scene_position_for_satellite


MARKER_RADIUS = 2.1
ORBIT_THICKNESS = 0.9
ORBIT_DOT_SIZE = 1.2
CONSTELLATION_PALETTE = (
    (1.0, 0.08, 0.08),   # red
    (1.0, 0.45, 0.00),   # orange
    (1.0, 0.86, 0.00),   # yellow
    (0.00, 0.82, 0.18),  # green
    (0.00, 0.86, 1.00),  # cyan
    (0.00, 0.38, 1.00),  # blue
    (0.52, 0.18, 1.00),  # violet
    (1.00, 0.00, 0.82),  # magenta
)
PALETTE_STRIDE = 3


def _xform(schema_or_prim, translate=None, rotate=None, scale=None):
    prim = schema_or_prim.GetPrim() if hasattr(schema_or_prim, "GetPrim") else schema_or_prim
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    if translate is not None:
        xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if rotate is not None:
        xf.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
    if scale is not None:
        xf.AddScaleOp().Set(Gf.Vec3d(*scale))


def _clear_children(stage, root_path: str) -> None:
    root = stage.GetPrimAtPath(root_path)
    if not root or not root.IsValid():
        return
    for child in list(root.GetChildren()):
        stage.RemovePrim(child.GetPath())


def _palette_color(index: int) -> tuple[float, float, float]:
    slot = (index * PALETTE_STRIDE) % len(CONSTELLATION_PALETTE)
    return CONSTELLATION_PALETTE[slot]


def _brighten(color: tuple[float, float, float], gain: float = 0.12) -> tuple[float, float, float]:
    return tuple(min(1.0, c + (1.0 - c) * gain) for c in color)


def _create_preview_material(stage, path: str, color, emissive_scale: float):
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(color[0] * emissive_scale, color[1] * emissive_scale, color[2] * emissive_scale)
    )
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.18)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def _set_constellation_metadata(prim, sat) -> None:
    prim.SetDisplayName(sat.label)
    prim.CreateAttribute("spacedc:norad_id", Sdf.ValueTypeNames.String, custom=True).Set(sat.catalog_number)
    prim.CreateAttribute("spacedc:satellite_name", Sdf.ValueTypeNames.String, custom=True).Set(sat.name)
    prim.CreateAttribute("spacedc:source", Sdf.ValueTypeNames.String, custom=True).Set("tle")
    prim.CreateAttribute("spacedc:label", Sdf.ValueTypeNames.String, custom=True).Set(sat.label)
    prim.CreateAttribute("spacedc:detail_target", Sdf.ValueTypeNames.Bool, custom=True).Set(True)
    prim.SetMetadata("comment", sat.label)


def build_constellation(
    stage,
    root_path: str,
    satellites,
    earth_radius_scene_units: float,
    selected_catalog_number: str | None = None,
) -> None:
    if not HAS_USD:
        raise RuntimeError("pxr (OpenUSD) not available - run inside Omniverse Kit")

    root = UsdGeom.Xform.Define(stage, root_path)
    markers_root = UsdGeom.Xform.Define(stage, f"{root_path}/Markers")
    orbits_root = UsdGeom.Xform.Define(stage, f"{root_path}/Orbits")

    _clear_children(stage, f"{root_path}/Markers")
    _clear_children(stage, f"{root_path}/Orbits")

    mats_root = f"{root_path}/Materials"
    for index, sat in enumerate(satellites):
        base_color = _palette_color(index)
        selected_color = _brighten(base_color)
        marker_default = _create_preview_material(
            stage,
            f"{mats_root}/Marker_{sat.catalog_number}",
            base_color,
            0.9,
        )
        marker_selected = _create_preview_material(
            stage,
            f"{mats_root}/Marker_{sat.catalog_number}_Selected",
            selected_color,
            1.05,
        )
        orbit_default = _create_preview_material(
            stage,
            f"{mats_root}/Orbit_{sat.catalog_number}",
            base_color,
            0.42,
        )
        orbit_selected = _create_preview_material(
            stage,
            f"{mats_root}/Orbit_{sat.catalog_number}_Selected",
            selected_color,
            0.58,
        )

        sat_path = f"{root_path}/Markers/{sat.safe_id}"
        sat_root = UsdGeom.Xform.Define(stage, sat_path)
        marker = UsdGeom.Sphere.Define(stage, f"{sat_path}/Marker")
        marker.GetRadiusAttr().Set(MARKER_RADIUS * (1.3 if sat.catalog_number == selected_catalog_number else 1.0))
        marker.GetDisplayColorAttr().Set([
            Gf.Vec3f(*(selected_color if sat.catalog_number == selected_catalog_number else base_color))
        ])
        marker.GetPrim().CreateAttribute(
            "primvars:doNotCastShadows",
            Sdf.ValueTypeNames.Bool,
            custom=False,
        ).Set(True)
        UsdShade.MaterialBindingAPI(marker.GetPrim()).Bind(
            marker_selected if sat.catalog_number == selected_catalog_number else marker_default
        )
        _set_constellation_metadata(sat_root.GetPrim(), sat)
        _set_constellation_metadata(marker.GetPrim(), sat)

        orbit_points = sample_orbit_scene_points(sat, earth_radius_scene_units, samples=241)
        orbit_color = (
            Gf.Vec3f(*selected_color)
            if sat.catalog_number == selected_catalog_number
            else Gf.Vec3f(*base_color)
        )
        orbit = UsdGeom.BasisCurves.Define(stage, f"{root_path}/Orbits/Orbit_{sat.catalog_number}")
        orbit.GetCurveVertexCountsAttr().Set(Vt.IntArray([len(orbit_points)]))
        orbit.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        orbit.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*p) for p in orbit_points]))
        orbit.CreateWidthsAttr().Set(Vt.FloatArray([ORBIT_THICKNESS] * len(orbit_points)))
        orbit.GetDisplayColorAttr().Set([orbit_color])
        orbit.GetPrim().CreateAttribute(
            "primvars:doNotCastShadows",
            Sdf.ValueTypeNames.Bool,
            custom=False,
        ).Set(True)
        UsdShade.MaterialBindingAPI(orbit.GetPrim()).Bind(
            orbit_selected if sat.catalog_number == selected_catalog_number else orbit_default
        )
        _set_constellation_metadata(orbit.GetPrim(), sat)

        orbit_points_prim = UsdGeom.Points.Define(stage, f"{root_path}/Orbits/OrbitDots_{sat.catalog_number}")
        orbit_points_prim.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*p) for p in orbit_points]))
        orbit_points_prim.GetWidthsAttr().Set(Vt.FloatArray([ORBIT_DOT_SIZE] * len(orbit_points)))
        orbit_points_prim.GetDisplayColorAttr().Set([orbit_color])
        orbit_points_prim.GetPrim().CreateAttribute(
            "primvars:doNotCastShadows",
            Sdf.ValueTypeNames.Bool,
            custom=False,
        ).Set(True)
        UsdShade.MaterialBindingAPI(orbit_points_prim.GetPrim()).Bind(
            orbit_selected if sat.catalog_number == selected_catalog_number else orbit_default
        )
        _set_constellation_metadata(orbit_points_prim.GetPrim(), sat)


def update_constellation_positions(stage, root_path: str, satellites, earth_radius_scene_units: float, when_utc) -> None:
    if not HAS_USD:
        return
    for sat in satellites:
        sat_prim = stage.GetPrimAtPath(f"{root_path}/Markers/{sat.safe_id}")
        if not sat_prim.IsValid():
            continue
        position = scene_position_for_satellite(sat, when_utc, earth_radius_scene_units)
        _xform(sat_prim, translate=position)


def get_selected_catalog_number_from_path(prim_path: str) -> str | None:
    parts = [part for part in prim_path.split("/") if part]
    if "Markers" in parts:
        idx = parts.index("Markers")
        if idx + 1 < len(parts):
            leaf = parts[idx + 1]
            if leaf.startswith("Sat_"):
                return leaf.replace("Sat_", "", 1)
    if "/World/Constellation/Orbits/Orbit_" in prim_path:
        leaf = parts[-1] if parts else ""
        if leaf.startswith("Orbit_"):
            return leaf.replace("Orbit_", "", 1)
    if "/World/Constellation/Orbits/OrbitDots_" in prim_path:
        leaf = parts[-1] if parts else ""
        if leaf.startswith("OrbitDots_"):
            return leaf.replace("OrbitDots_", "", 1)
    return None
