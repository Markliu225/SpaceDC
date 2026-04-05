from __future__ import annotations

import math
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "exts" / "spacedc.digital_twin" / "data" / "models" / "compute_satellite_hero_blender.usda"
BLEND_PATH = ROOT / "tools" / "blender" / "compute_satellite_hero.blend"

BODY_X = 4.4
BODY_Y = 3.5
BODY_Z = 2.7
WING_SEGMENTS = 15
WING_SEG_LEN = 5.8
WING_GAP = 0.35
WING_CHORD = 4.8
WING_THICK = 0.07
WING_ROOT_START = 4.6


def rgba(hex_rgb: str, alpha: float = 1.0):
    hex_rgb = hex_rgb.strip().lstrip("#")
    return tuple(int(hex_rgb[i:i + 2], 16) / 255.0 for i in range(0, 6, 2)) + (alpha,)


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 16
    scene.world = bpy.data.worlds.new("SpaceWorld")
    scene.world.color = (0.0, 0.0, 0.0)


def ensure_dirs() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    BLEND_PATH.parent.mkdir(parents=True, exist_ok=True)


def make_material(
    name: str,
    base: str,
    metallic: float,
    roughness: float,
    coat: float = 0.0,
    coat_roughness: float = 0.03,
    emission: str | None = None,
    emission_strength: float = 0.0,
    alpha: float = 1.0,
):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (260, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    bsdf.inputs["Base Color"].default_value = rgba(base, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Coat Weight"].default_value = coat
    bsdf.inputs["Coat Roughness"].default_value = coat_roughness
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = rgba(emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    bsdf.inputs["Alpha"].default_value = alpha
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    if alpha < 1.0:
        mat.blend_method = "BLEND"
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
    return mat


def assign_material(obj, mat) -> None:
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def activate(obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def finish_object(obj, material, bevel: float = 0.0, bevel_segments: int = 3, smooth: bool = False):
    if bevel > 0.0:
        activate(obj)
        mod = obj.modifiers.new(name="Bevel", type="BEVEL")
        mod.width = bevel
        mod.segments = bevel_segments
        mod.limit_method = "ANGLE"
        bpy.ops.object.modifier_apply(modifier=mod.name)
    if smooth:
        activate(obj)
        bpy.ops.object.shade_smooth()
    assign_material(obj, material)
    return obj


def parent_to(obj, parent):
    obj.parent = parent
    return obj


def cube(name, size, location, rotation_deg=(0.0, 0.0, 0.0), material=None, bevel=0.0, smooth=False, parent=None):
    rotation = tuple(math.radians(v) for v in rotation_deg)
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size[0] * 0.5, size[1] * 0.5, size[2] * 0.5)
    activate(obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if parent is not None:
        parent_to(obj, parent)
    if material is not None:
        finish_object(obj, material, bevel=bevel, smooth=smooth)
    return obj


def cylinder(name, radius, depth, location, rotation_deg=(0.0, 0.0, 0.0), material=None, bevel=0.0, vertices=32, smooth=True, parent=None):
    rotation = tuple(math.radians(v) for v in rotation_deg)
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    if parent is not None:
        parent_to(obj, parent)
    if material is not None:
        finish_object(obj, material, bevel=bevel, smooth=smooth)
    return obj


def sphere(name, radius, location, scale=(1.0, 1.0, 1.0), material=None, smooth=True, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=radius, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    activate(obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if parent is not None:
        parent_to(obj, parent)
    if material is not None:
        finish_object(obj, material, bevel=0.0, smooth=smooth)
    return obj


def make_root(name: str):
    root = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(root)
    return root


def build_materials():
    return {
        "kapton": make_material("Kapton", "#EC8714", 0.36, 0.18, coat=0.65, coat_roughness=0.06),
        "kapton_dark": make_material("KaptonDark", "#B96F12", 0.32, 0.24, coat=0.45, coat_roughness=0.08),
        "frame": make_material("FrameMetal", "#B8BDC6", 0.88, 0.18, coat=0.08, coat_roughness=0.03),
        "shell": make_material("ShellDark", "#1E232B", 0.62, 0.28, coat=0.06, coat_roughness=0.05),
        "solar": make_material("SolarBlue", "#0B3B60", 0.55, 0.12, coat=0.18, coat_roughness=0.04),
        "solar_line": make_material("SolarBlueLine", "#2C6C96", 0.22, 0.18),
        "radiator": make_material("RadiatorWhite", "#E7ECF0", 0.06, 0.42),
        "server": make_material("ServerDark", "#11161D", 0.38, 0.46),
        "server_face": make_material("ServerFace", "#232A33", 0.28, 0.34),
        "glass": make_material("ServerGlass", "#375163", 0.03, 0.08, alpha=0.45),
        "led": make_material("LedCyan", "#5CD5FF", 0.02, 0.18, emission="#53D7FF", emission_strength=3.2),
        "cable": make_material("CableBlue", "#5A88AE", 0.18, 0.38),
        "black": make_material("BlackDetail", "#0A0D11", 0.24, 0.58),
    }


def build_body(root, mats):
    cube("BodyFloor", (BODY_X, 0.18, BODY_Z), (0.0, 0.0, -BODY_Z * 0.46), material=mats["frame"], bevel=0.035, parent=root)
    cube("BodyRoof", (BODY_X * 0.84, 0.16, BODY_Z * 0.86), (0.0, 0.12, BODY_Z * 0.48), material=mats["kapton"], bevel=0.05, parent=root)
    cube("AftBulkhead", (BODY_X * 0.92, BODY_Y * 0.16, BODY_Z * 0.86), (0.0, BODY_Y * 0.42, -0.02), material=mats["shell"], bevel=0.04, parent=root)
    cube("SideRailLeft", (0.18, BODY_Y * 0.92, BODY_Z * 0.90), (-BODY_X * 0.47, 0.02, -0.02), material=mats["frame"], bevel=0.03, parent=root)
    cube("SideRailRight", (0.18, BODY_Y * 0.92, BODY_Z * 0.90), (BODY_X * 0.47, 0.02, -0.02), material=mats["frame"], bevel=0.03, parent=root)
    cube("FrontSill", (BODY_X * 0.92, 0.16, 0.20), (0.0, -BODY_Y * 0.46, -BODY_Z * 0.32), material=mats["frame"], bevel=0.02, parent=root)
    cube("FrontLintel", (BODY_X * 0.92, 0.18, 0.22), (0.0, -BODY_Y * 0.46, BODY_Z * 0.32), material=mats["frame"], bevel=0.02, parent=root)
    cube("FrontPostLeft", (0.16, 0.16, BODY_Z * 0.72), (-BODY_X * 0.38, -BODY_Y * 0.46, -0.02), material=mats["frame"], bevel=0.02, parent=root)
    cube("FrontPostRight", (0.16, 0.16, BODY_Z * 0.72), (BODY_X * 0.38, -BODY_Y * 0.46, -0.02), material=mats["frame"], bevel=0.02, parent=root)
    cube("FrontMullionLeft", (0.08, 0.10, BODY_Z * 0.64), (-BODY_X * 0.12, -BODY_Y * 0.45, -0.02), material=mats["frame"], bevel=0.012, parent=root)
    cube("FrontMullionRight", (0.08, 0.10, BODY_Z * 0.64), (BODY_X * 0.12, -BODY_Y * 0.45, -0.02), material=mats["frame"], bevel=0.012, parent=root)

    cube("TopPortBlanket", (BODY_X * 0.96, BODY_Y * 0.74, 0.16), (0.0, 0.05, BODY_Z * 0.72), rotation_deg=(0.0, 18.0, 0.0), material=mats["kapton"], bevel=0.05, parent=root)
    cube("TopStarboardBlanket", (BODY_X * 0.96, BODY_Y * 0.74, 0.16), (0.0, 0.05, BODY_Z * 0.72), rotation_deg=(0.0, -18.0, 0.0), material=mats["kapton"], bevel=0.05, parent=root)
    cube("PortShoulderBlanket", (0.18, BODY_Y * 0.92, BODY_Z * 0.84), (-BODY_X * 0.52, 0.04, BODY_Z * 0.08), rotation_deg=(0.0, 16.0, 0.0), material=mats["kapton_dark"], bevel=0.03, parent=root)
    cube("StarboardShoulderBlanket", (0.18, BODY_Y * 0.92, BODY_Z * 0.84), (BODY_X * 0.52, 0.04, BODY_Z * 0.08), rotation_deg=(0.0, -16.0, 0.0), material=mats["kapton_dark"], bevel=0.03, parent=root)

    cube("PayloadDeck", (BODY_X * 0.82, BODY_Y * 0.76, 0.08), (0.0, 0.02, -BODY_Z * 0.38), material=mats["shell"], bevel=0.018, parent=root)
    cube("PayloadCatwalk", (BODY_X * 0.72, 0.18, 0.06), (0.0, -BODY_Y * 0.18, -BODY_Z * 0.05), material=mats["frame"], bevel=0.014, parent=root)
    cube("PayloadOverhead", (BODY_X * 0.76, 0.16, 0.08), (0.0, 0.18, BODY_Z * 0.22), material=mats["frame"], bevel=0.014, parent=root)

    for x in (-BODY_X * 0.26, 0.0, BODY_X * 0.26):
        cube(f"DeckRail_{x:.2f}", (0.07, BODY_Y * 0.82, 0.08), (x, 0.06, -BODY_Z * 0.28), material=mats["frame"], bevel=0.01, parent=root)

    for z in (-0.78, -0.22, 0.34):
        cylinder(f"CoolantSpine_{z:.2f}", 0.05, BODY_Y * 0.86, (0.0, 0.05, z), rotation_deg=(90.0, 0.0, 0.0), material=mats["cable"], bevel=0.008, parent=root)


def build_server_rack(name: str, location, root, mats):
    x, y, z = location
    group = make_root(name)
    parent_to(group, root)
    cube(f"{name}_Body", (0.62, 0.72, 1.64), (x, y, z), material=mats["server"], bevel=0.018, parent=group)
    cube(f"{name}_Face", (0.56, 0.03, 1.54), (x, y - 0.345, z), material=mats["server_face"], bevel=0.012, parent=group)
    cube(f"{name}_Glass", (0.48, 0.012, 1.42), (x, y - 0.358, z + 0.04), material=mats["glass"], bevel=0.006, parent=group)
    cube(f"{name}_TopPlenum", (0.58, 0.44, 0.14), (x, y, z + 0.83), material=mats["shell"], bevel=0.01, parent=group)
    cube(f"{name}_BottomPdu", (0.58, 0.44, 0.12), (x, y, z - 0.84), material=mats["shell"], bevel=0.01, parent=group)
    cube(f"{name}_HandleL", (0.03, 0.05, 0.34), (x - 0.22, y - 0.36, z + 0.02), material=mats["frame"], bevel=0.004, parent=group)
    cube(f"{name}_HandleR", (0.03, 0.05, 0.34), (x + 0.22, y - 0.36, z + 0.02), material=mats["frame"], bevel=0.004, parent=group)
    cube(f"{name}_LedStrip", (0.018, 0.008, 1.18), (x - 0.27, y - 0.366, z), material=mats["led"], bevel=0.002, parent=group)

    for idx, z_off in enumerate((-0.56, -0.28, 0.0, 0.28, 0.56)):
        cube(f"{name}_Vent_{idx}", (0.42, 0.016, 0.018), (x, y - 0.354, z + z_off), material=mats["black"], bevel=0.001, parent=group)

    cube(f"{name}_SkidL", (0.05, 0.38, 0.06), (x - 0.18, y, z - 0.86), material=mats["frame"], bevel=0.004, parent=group)
    cube(f"{name}_SkidR", (0.05, 0.38, 0.06), (x + 0.18, y, z - 0.86), material=mats["frame"], bevel=0.004, parent=group)
    cube(f"{name}_Umbilical", (0.10, 0.12, 0.08), (x, y + 0.30, z + 0.72), material=mats["cable"], bevel=0.004, parent=group)


def build_servers(root, mats):
    x_positions = (-1.35, -0.45, 0.45, 1.35)
    y_positions = (-0.70, 0.18)
    z_center = -0.02
    for row_idx, y in enumerate(y_positions):
        for col_idx, x in enumerate(x_positions):
            build_server_rack(f"Rack_{row_idx}_{col_idx}", (x, y, z_center), root, mats)

    cube("ServerBridge", (3.3, 0.10, 0.12), (0.0, -0.12, 0.92), material=mats["frame"], bevel=0.01, parent=root)
    cube("ServerBridgeRear", (3.3, 0.10, 0.12), (0.0, 0.58, 0.92), material=mats["frame"], bevel=0.01, parent=root)
    cylinder("CoolantManifoldFront", 0.055, 3.4, (0.0, -0.32, 1.20), rotation_deg=(0.0, 90.0, 0.0), material=mats["cable"], bevel=0.006, parent=root)
    cylinder("CoolantManifoldRear", 0.055, 3.4, (0.0, 0.36, 1.20), rotation_deg=(0.0, 90.0, 0.0), material=mats["cable"], bevel=0.006, parent=root)


def build_root_and_wings(root, mats):
    pitch = WING_SEG_LEN + WING_GAP
    wing_total = WING_SEGMENTS * WING_SEG_LEN + (WING_SEGMENTS - 1) * WING_GAP
    wing_center_offset = WING_ROOT_START + wing_total * 0.5

    for side, label in ((-1.0, "Left"), (1.0, "Right")):
        x_sign = side
        root_x = x_sign * (BODY_X * 0.5 + 0.90)

        cube(f"{label}RootFairing", (1.65, 1.25, 3.10), (root_x, 0.20, 0.02), material=mats["kapton_dark"], bevel=0.05, parent=root)
        cube(f"{label}RootDeck", (1.10, 0.56, 2.70), (x_sign * (BODY_X * 0.5 + 0.34), 0.10, 0.00), material=mats["shell"], bevel=0.03, parent=root)
        cylinder(f"{label}HingeDrum", 0.28, 1.05, (x_sign * (BODY_X * 0.5 + 1.36), 0.06, 0.0), rotation_deg=(0.0, 90.0, 0.0), material=mats["frame"], bevel=0.01, parent=root)

        for brace_idx, z in enumerate((-0.82, 0.0, 0.82)):
            cube(
                f"{label}YokeSpine_{brace_idx}",
                (2.15, 0.24, 0.26),
                (x_sign * (BODY_X * 0.5 + 1.95), 0.00, z),
                material=mats["frame"],
                bevel=0.015,
                parent=root,
            )

        for z in (-1.02, 1.02):
            cube(
                f"{label}RootBrace_{z:.2f}",
                (1.65, 0.12, 0.12),
                (x_sign * (BODY_X * 0.5 + 1.24), -0.22, z),
                rotation_deg=(0.0, 0.0, 18.0 * -x_sign),
                material=mats["frame"],
                bevel=0.008,
                parent=root,
            )

        center_x = x_sign * wing_center_offset
        cube(f"{label}WingSpine", (wing_total + 2.2, 0.16, 0.26), (center_x, 0.00, 0.0), material=mats["frame"], bevel=0.008, parent=root)
        cube(f"{label}WingEdgeUpper", (wing_total + 2.2, 0.11, 0.16), (center_x, 0.02, WING_CHORD * 0.5 - 0.10), material=mats["frame"], bevel=0.004, parent=root)
        cube(f"{label}WingEdgeLower", (wing_total + 2.2, 0.11, 0.16), (center_x, 0.02, -WING_CHORD * 0.5 + 0.10), material=mats["frame"], bevel=0.004, parent=root)

        for rib_idx in range(12):
            x = x_sign * (WING_ROOT_START + 1.6 + rib_idx * ((wing_total - 3.2) / 11.0))
            cube(
                f"{label}SpanRib_{rib_idx}",
                (0.08, 0.14, WING_CHORD - 0.16),
                (x, 0.01, 0.0),
                material=mats["frame"],
                bevel=0.002,
                parent=root,
            )

        for idx in range(WING_SEGMENTS):
            center = x_sign * (WING_ROOT_START + idx * pitch + WING_SEG_LEN * 0.5)
            cube(
                f"{label}WingFrame_{idx:02d}",
                (WING_SEG_LEN, WING_THICK, WING_CHORD),
                (center, 0.00, 0.0),
                material=mats["frame"],
                bevel=0.004,
                parent=root,
            )
            cube(
                f"{label}SolarFace_{idx:02d}",
                (WING_SEG_LEN - 0.22, 0.012, WING_CHORD - 0.28),
                (center, 0.055, 0.0),
                material=mats["solar"],
                bevel=0.001,
                parent=root,
            )
            cube(
                f"{label}RadiatorBack_{idx:02d}",
                (WING_SEG_LEN - 0.28, 0.014, WING_CHORD - 0.34),
                (center, -0.055, 0.0),
                material=mats["radiator"],
                bevel=0.001,
                parent=root,
            )

            for stripe_idx in range(7):
                z = -WING_CHORD * 0.5 + 0.38 + stripe_idx * ((WING_CHORD - 0.76) / 6.0)
                cube(
                    f"{label}SolarStripe_{idx:02d}_{stripe_idx}",
                    (WING_SEG_LEN - 0.30, 0.004, 0.035),
                    (center, 0.062, z),
                    material=mats["solar_line"],
                    bevel=0.0,
                    parent=root,
                )

            for pipe_idx in range(4):
                z = -WING_CHORD * 0.5 + 0.60 + pipe_idx * ((WING_CHORD - 1.20) / 3.0)
                cube(
                    f"{label}HeatPipe_{idx:02d}_{pipe_idx}",
                    (WING_SEG_LEN - 0.46, 0.006, 0.05),
                    (center, -0.064, z),
                    material=mats["frame"],
                    bevel=0.0,
                    parent=root,
                )


def build_roof_details(root, mats):
    cube("RoofBase", (1.55, 0.22, 1.55), (0.0, 0.10, BODY_Z * 0.78), material=mats["frame"], bevel=0.03, parent=root)
    cube("RoofEquipmentA", (0.55, 0.42, 0.42), (-0.86, 0.18, BODY_Z * 0.98), material=mats["shell"], bevel=0.02, parent=root)
    cube("RoofEquipmentB", (0.40, 0.34, 0.34), (0.92, 0.12, BODY_Z * 0.94), material=mats["frame"], bevel=0.02, parent=root)
    cylinder("RoofCanA", 0.11, 0.44, (-0.15, 0.10, BODY_Z * 1.02), material=mats["frame"], bevel=0.01, parent=root)
    cylinder("RoofCanB", 0.09, 0.38, (0.38, 0.10, BODY_Z * 1.00), material=mats["frame"], bevel=0.01, parent=root)
    sphere("MainRadome", 0.36, (0.78, -0.02, BODY_Z * 1.18), scale=(1.0, 1.0, 0.85), material=mats["frame"], parent=root)
    cylinder("RadomePedestal", 0.08, 0.42, (0.78, -0.02, BODY_Z * 0.98), material=mats["frame"], bevel=0.006, parent=root)
    sphere("TrackerPod", 0.12, (-0.42, -0.22, BODY_Z * 1.06), scale=(1.0, 1.0, 0.75), material=mats["glass"], parent=root)


def build_thrusters(root, mats):
    for x in (-1.45, 1.45):
        for y in (1.30,):
            for z in (-1.10, 1.10):
                cylinder(f"ThrusterSkirt_{x:.2f}_{z:.2f}", 0.10, 0.22, (x, y, z), rotation_deg=(90.0, 0.0, 0.0), material=mats["frame"], bevel=0.004, parent=root)
                cube(f"ThrusterMount_{x:.2f}_{z:.2f}", (0.18, 0.20, 0.18), (x, y - 0.12, z), material=mats["shell"], bevel=0.008, parent=root)


def build_satellite():
    reset_scene()
    ensure_dirs()
    mats = build_materials()
    root = make_root("ComputeSatellite")
    build_body(root, mats)
    build_servers(root, mats)
    build_root_and_wings(root, mats)
    build_roof_details(root, mats)
    build_thrusters(root, mats)
    return root


def export_asset() -> None:
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    bpy.ops.wm.usd_export(
        filepath=str(OUT_PATH),
        selected_objects_only=False,
        visible_objects_only=False,
        export_materials=True,
        generate_preview_surface=True,
        export_meshes=True,
        export_lights=False,
        export_cameras=False,
        export_animation=False,
        export_uvmaps=False,
        export_normals=True,
        triangulate_meshes=False,
        root_prim_path="/ComputeSatelliteHero",
        convert_orientation=True,
        export_global_up_selection="Y",
        export_global_forward_selection="NEGATIVE_Z",
    )


def main() -> None:
    build_satellite()
    export_asset()
    print(f"Wrote {OUT_PATH}")
    print(f"Saved {BLEND_PATH}")


if __name__ == "__main__":
    main()
