"""
============================================================
  business_orchestration_builder.py - Business demand links and node states
============================================================
"""
from __future__ import annotations

try:
    from pxr import UsdGeom, UsdShade, Sdf, Gf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False

from ..physics.business_network import BUSINESS_WORKLOADS
from ..physics.constellation import scene_position_for_satellite


DEMAND_LINK_WIDTH = 2.1
BUSINESS_IDLE_COLOR = (0.42, 0.42, 0.54)
COMPUTE_IDLE_COLOR = (0.16, 0.92, 0.44)
COMPUTE_BUSY_COLOR = (1.00, 0.72, 0.04)
COMPUTE_OVERLOADED_COLOR = (1.00, 0.16, 0.22)
COMPUTE_IDLE_RADIUS = 2.1
COMPUTE_BUSY_RADIUS = 3.5
COMPUTE_OVERLOADED_RADIUS = 4.1
BUSINESS_IDLE_RADIUS = 2.1
BUSINESS_ACTIVE_RADIUS = 3.0


def _create_preview_material(stage, path: str, color, emissive_scale: float, roughness: float = 0.18):
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(color[0] * emissive_scale, color[1] * emissive_scale, color[2] * emissive_scale)
    )
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def _marker_prim(stage, root_path: str, sat) -> object | None:
    prim = stage.GetPrimAtPath(f"{root_path}/Markers/{sat.safe_id}/Marker")
    return prim if prim and prim.IsValid() else None


def _status_material(stage, root_path: str, name: str, color, emissive_scale: float):
    return _create_preview_material(stage, f"{root_path}/Materials/{name}", color, emissive_scale)


def apply_business_workload_styles(stage, root_path: str, constellation, business_configs) -> None:
    if not HAS_USD or not constellation:
        return

    unassigned_mat = _status_material(stage, root_path, "BusinessUnassigned", BUSINESS_IDLE_COLOR, 0.18)
    for sat in constellation.satellites:
        marker_prim = _marker_prim(stage, root_path, sat)
        if not marker_prim:
            continue

        config = business_configs.get(sat.catalog_number) if business_configs else None
        if config and config.workload_key in BUSINESS_WORKLOADS:
            workload = BUSINESS_WORKLOADS[config.workload_key]
            mat = _status_material(
                stage,
                root_path,
                f"Business_{workload.key}",
                workload.color,
                0.42,
            )
            radius = BUSINESS_ACTIVE_RADIUS
            marker_prim.SetDisplayName(f"{sat.label} / {workload.name}")
            marker_prim.CreateAttribute("spacedc:workload", Sdf.ValueTypeNames.String, custom=True).Set(workload.key)
        else:
            mat = unassigned_mat
            radius = BUSINESS_IDLE_RADIUS
            marker_prim.SetDisplayName(f"{sat.label} / Unassigned")
            marker_prim.CreateAttribute("spacedc:workload", Sdf.ValueTypeNames.String, custom=True).Set("")

        marker = UsdGeom.Sphere(marker_prim)
        marker.GetRadiusAttr().Set(radius)
        UsdShade.MaterialBindingAPI(marker_prim).Bind(mat)


def apply_compute_node_status(stage, root_path: str, constellation, compute_states) -> None:
    if not HAS_USD or not constellation:
        return

    idle_mat = _status_material(stage, root_path, "ComputeIdle", COMPUTE_IDLE_COLOR, 0.25)
    busy_mat = _status_material(stage, root_path, "ComputeBusy", COMPUTE_BUSY_COLOR, 0.82)
    overloaded_mat = _status_material(stage, root_path, "ComputeOverloaded", COMPUTE_OVERLOADED_COLOR, 1.0)

    for sat in constellation.satellites:
        marker_prim = _marker_prim(stage, root_path, sat)
        if not marker_prim:
            continue

        state = compute_states.get(sat.catalog_number) if compute_states else None
        marker = UsdGeom.Sphere(marker_prim)
        if not state or state.state == "idle":
            marker.GetRadiusAttr().Set(COMPUTE_IDLE_RADIUS)
            UsdShade.MaterialBindingAPI(marker_prim).Bind(idle_mat)
            marker_prim.CreateAttribute("spacedc:compute_state", Sdf.ValueTypeNames.String, custom=True).Set("idle")
        elif state.state == "overloaded":
            marker.GetRadiusAttr().Set(COMPUTE_OVERLOADED_RADIUS)
            UsdShade.MaterialBindingAPI(marker_prim).Bind(overloaded_mat)
            marker_prim.CreateAttribute("spacedc:compute_state", Sdf.ValueTypeNames.String, custom=True).Set("overloaded")
        else:
            marker.GetRadiusAttr().Set(COMPUTE_BUSY_RADIUS)
            UsdShade.MaterialBindingAPI(marker_prim).Bind(busy_mat)
            marker_prim.CreateAttribute("spacedc:compute_state", Sdf.ValueTypeNames.String, custom=True).Set("busy")


def clear_business_demand_links(stage, root_path: str) -> None:
    if not HAS_USD:
        return
    stage.RemovePrim(root_path)


def _link_path(root_path: str, assignment) -> str:
    return f"{root_path}/Demand_{assignment.business_catalog_number}_{assignment.compute_catalog_number}"


def _material_path(root_path: str, assignment) -> str:
    return f"{root_path}/Materials/DemandMat_{assignment.business_catalog_number}_{assignment.compute_catalog_number}"


def build_business_demand_links(
    stage,
    root_path: str,
    assignments,
    business_constellation,
    compute_constellation,
    earth_radius_scene_units: float,
    when_utc,
) -> None:
    if not HAS_USD:
        raise RuntimeError("pxr (OpenUSD) not available - run inside Omniverse Kit")

    root = UsdGeom.Xform.Define(stage, root_path)
    for child in list(root.GetPrim().GetChildren()):
        stage.RemovePrim(child.GetPath())

    if not assignments or not business_constellation or not compute_constellation:
        return

    for assignment in assignments:
        business_sat = business_constellation.get(assignment.business_catalog_number)
        compute_sat = compute_constellation.get(assignment.compute_catalog_number)
        if not business_sat or not compute_sat:
            continue

        color = BUSINESS_WORKLOADS.get(assignment.workload_key, BUSINESS_WORKLOADS[next(iter(BUSINESS_WORKLOADS))]).color
        material = _create_preview_material(
            stage,
            _material_path(root_path, assignment),
            color,
            1.05,
            roughness=0.10,
        )
        pos_a = scene_position_for_satellite(business_sat, when_utc, earth_radius_scene_units)
        pos_b = scene_position_for_satellite(compute_sat, when_utc, earth_radius_scene_units)

        curve = UsdGeom.BasisCurves.Define(stage, _link_path(root_path, assignment))
        curve.GetCurveVertexCountsAttr().Set(Vt.IntArray([2]))
        curve.GetTypeAttr().Set(UsdGeom.Tokens.linear)
        curve.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*pos_a), Gf.Vec3f(*pos_b)]))
        curve.CreateWidthsAttr().Set(Vt.FloatArray([DEMAND_LINK_WIDTH, DEMAND_LINK_WIDTH]))
        curve.GetDisplayColorAttr().Set([Gf.Vec3f(*color)])
        curve.GetPrim().CreateAttribute(
            "primvars:doNotCastShadows",
            Sdf.ValueTypeNames.Bool,
            custom=False,
        ).Set(True)
        curve.GetPrim().SetDisplayName(f"{business_sat.name} -> {compute_sat.name}")
        curve.GetPrim().CreateAttribute("spacedc:workload", Sdf.ValueTypeNames.String, custom=True).Set(assignment.workload_key)
        curve.GetPrim().CreateAttribute("spacedc:demand_units", Sdf.ValueTypeNames.Float, custom=True).Set(assignment.demand_units)
        UsdShade.MaterialBindingAPI(curve.GetPrim()).Bind(material)


def update_business_demand_links(
    stage,
    root_path: str,
    assignments,
    business_constellation,
    compute_constellation,
    earth_radius_scene_units: float,
    when_utc,
) -> None:
    if not HAS_USD:
        return
    if not assignments or not business_constellation or not compute_constellation:
        clear_business_demand_links(stage, root_path)
        return

    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        build_business_demand_links(
            stage,
            root_path,
            assignments,
            business_constellation,
            compute_constellation,
            earth_radius_scene_units,
            when_utc,
        )
        return

    expected_paths = {_link_path(root_path, assignment) for assignment in assignments}
    existing_paths = {
        str(child.GetPath())
        for child in root.GetChildren()
        if child.GetName().startswith("Demand_")
    }
    if expected_paths != existing_paths:
        build_business_demand_links(
            stage,
            root_path,
            assignments,
            business_constellation,
            compute_constellation,
            earth_radius_scene_units,
            when_utc,
        )
        return

    for assignment in assignments:
        business_sat = business_constellation.get(assignment.business_catalog_number)
        compute_sat = compute_constellation.get(assignment.compute_catalog_number)
        prim = stage.GetPrimAtPath(_link_path(root_path, assignment))
        if not business_sat or not compute_sat or not prim.IsValid():
            build_business_demand_links(
                stage,
                root_path,
                assignments,
                business_constellation,
                compute_constellation,
                earth_radius_scene_units,
                when_utc,
            )
            return
        pos_a = scene_position_for_satellite(business_sat, when_utc, earth_radius_scene_units)
        pos_b = scene_position_for_satellite(compute_sat, when_utc, earth_radius_scene_units)
        curve = UsdGeom.BasisCurves(prim)
        curve.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*pos_a), Gf.Vec3f(*pos_b)]))
        color = BUSINESS_WORKLOADS.get(assignment.workload_key, BUSINESS_WORKLOADS[next(iter(BUSINESS_WORKLOADS))]).color
        curve.GetDisplayColorAttr().Set([Gf.Vec3f(*color)])
        prim.SetDisplayName(f"{business_sat.name} -> {compute_sat.name}")
        prim.CreateAttribute("spacedc:workload", Sdf.ValueTypeNames.String, custom=True).Set(assignment.workload_key)
        prim.CreateAttribute("spacedc:demand_units", Sdf.ValueTypeNames.Float, custom=True).Set(assignment.demand_units)
        material = _create_preview_material(
            stage,
            _material_path(root_path, assignment),
            color,
            1.05,
            roughness=0.10,
        )
        UsdShade.MaterialBindingAPI(prim).Bind(material)
