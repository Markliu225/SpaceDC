"""
============================================================
  topology_builder.py - USD visualization for constellation links
============================================================
"""
from __future__ import annotations

try:
    from pxr import UsdGeom, UsdShade, Sdf, Gf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False

from ..physics.constellation import scene_position_for_satellite


LINK_WIDTH = 0.8
LINK_COLOR = (1.0, 0.78, 0.18)
LINK_SELECTED_COLOR = (0.2, 1.0, 0.92)


def _create_preview_material(stage, path: str, color, emissive_scale: float):
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(color[0] * emissive_scale, color[1] * emissive_scale, color[2] * emissive_scale)
    )
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.22)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def _link_path(root_path: str, link) -> str:
    return f"{root_path}/Link_{link.source_catalog_number}_{link.target_catalog_number}"


def clear_topology_links(stage, root_path: str) -> None:
    if not HAS_USD:
        return
    stage.RemovePrim(root_path)


def build_topology_links(stage, root_path: str, links, constellation, earth_radius_scene_units: float, when_utc, selected_catalog_number: str | None = None) -> None:
    if not HAS_USD:
        raise RuntimeError("pxr (OpenUSD) not available - run inside Omniverse Kit")

    root = UsdGeom.Xform.Define(stage, root_path)
    for child in list(root.GetPrim().GetChildren()):
        stage.RemovePrim(child.GetPath())

    if not links or not constellation:
        return

    mats_root = f"{root_path}/Materials"
    default_mat = _create_preview_material(stage, f"{mats_root}/Default", LINK_COLOR, 0.3)
    selected_mat = _create_preview_material(stage, f"{mats_root}/Selected", LINK_SELECTED_COLOR, 0.45)

    for link in links:
        sat_a = constellation.get(link.source_catalog_number)
        sat_b = constellation.get(link.target_catalog_number)
        if not sat_a or not sat_b:
            continue
        pos_a = scene_position_for_satellite(sat_a, when_utc, earth_radius_scene_units)
        pos_b = scene_position_for_satellite(sat_b, when_utc, earth_radius_scene_units)
        selected = selected_catalog_number in {link.source_catalog_number, link.target_catalog_number}
        color = LINK_SELECTED_COLOR if selected else LINK_COLOR

        curve = UsdGeom.BasisCurves.Define(stage, _link_path(root_path, link))
        curve.GetCurveVertexCountsAttr().Set(Vt.IntArray([2]))
        curve.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        curve.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*pos_a), Gf.Vec3f(*pos_b)]))
        curve.CreateWidthsAttr().Set(Vt.FloatArray([LINK_WIDTH, LINK_WIDTH]))
        curve.GetDisplayColorAttr().Set([Gf.Vec3f(*color)])
        curve.GetPrim().CreateAttribute(
            "primvars:doNotCastShadows",
            Sdf.ValueTypeNames.Bool,
            custom=False,
        ).Set(True)
        curve.GetPrim().SetDisplayName(f"{sat_a.name} ↔ {sat_b.name}")
        curve.GetPrim().CreateAttribute("spacedc:link_a", Sdf.ValueTypeNames.String, custom=True).Set(link.source_catalog_number)
        curve.GetPrim().CreateAttribute("spacedc:link_b", Sdf.ValueTypeNames.String, custom=True).Set(link.target_catalog_number)
        UsdShade.MaterialBindingAPI(curve.GetPrim()).Bind(selected_mat if selected else default_mat)


def update_topology_links(stage, root_path: str, links, constellation, earth_radius_scene_units: float, when_utc, selected_catalog_number: str | None = None) -> None:
    if not HAS_USD:
        return
    if not links or not constellation:
        clear_topology_links(stage, root_path)
        return

    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        build_topology_links(stage, root_path, links, constellation, earth_radius_scene_units, when_utc, selected_catalog_number)
        return

    for link in links:
        prim = stage.GetPrimAtPath(_link_path(root_path, link))
        if not prim.IsValid():
            build_topology_links(stage, root_path, links, constellation, earth_radius_scene_units, when_utc, selected_catalog_number)
            return

    for link in links:
        sat_a = constellation.get(link.source_catalog_number)
        sat_b = constellation.get(link.target_catalog_number)
        prim = stage.GetPrimAtPath(_link_path(root_path, link))
        if not sat_a or not sat_b or not prim.IsValid():
            continue
        pos_a = scene_position_for_satellite(sat_a, when_utc, earth_radius_scene_units)
        pos_b = scene_position_for_satellite(sat_b, when_utc, earth_radius_scene_units)
        curve = UsdGeom.BasisCurves(prim)
        curve.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*pos_a), Gf.Vec3f(*pos_b)]))
