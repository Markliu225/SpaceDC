from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "exts" / "spacedc.digital_twin" / "data" / "models" / "compute_satellite_mesh.usda"


def apply_transform(
    mesh: trimesh.Trimesh,
    translate=(0.0, 0.0, 0.0),
    rotate_deg=(0.0, 0.0, 0.0),
    scale=(1.0, 1.0, 1.0),
) -> trimesh.Trimesh:
    mesh = mesh.copy()
    mesh.apply_scale(scale)
    rx, ry, rz = [math.radians(v) for v in rotate_deg]
    mesh.apply_transform(trimesh.transformations.euler_matrix(rx, ry, rz, "sxyz"))
    mesh.apply_translation(np.array(translate, dtype=float))
    return mesh


def box(extents, translate=(0.0, 0.0, 0.0), rotate_deg=(0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    return apply_transform(trimesh.creation.box(extents=extents), translate, rotate_deg)


def sphere(radius, subdivisions=2, translate=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)) -> trimesh.Trimesh:
    return apply_transform(
        trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius),
        translate=translate,
        scale=scale,
    )


def tapered_prism(length, width, height_a, height_b, translate=(0.0, 0.0, 0.0), rotate_deg=(0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    lx = length * 0.5
    wz = width * 0.5
    ha = height_a * 0.5
    hb = height_b * 0.5
    vertices = np.array(
        [
            [-lx, -ha, -wz],
            [-lx, -ha, wz],
            [-lx, ha, wz],
            [-lx, ha, -wz],
            [lx, -hb, -wz],
            [lx, -hb, wz],
            [lx, hb, wz],
            [lx, hb, -wz],
        ],
        dtype=float,
    )
    faces = np.array(
        [
            [0, 1, 2], [0, 2, 3],
            [4, 7, 6], [4, 6, 5],
            [0, 4, 5], [0, 5, 1],
            [1, 5, 6], [1, 6, 2],
            [2, 6, 7], [2, 7, 3],
            [3, 7, 4], [3, 4, 0],
        ],
        dtype=int,
    )
    return apply_transform(trimesh.Trimesh(vertices=vertices, faces=faces, process=False), translate, rotate_deg)


def concat(meshes: Iterable[trimesh.Trimesh]) -> trimesh.Trimesh:
    items = [m for m in meshes if m is not None]
    if not items:
        raise ValueError("No meshes to concatenate")
    return trimesh.util.concatenate(items)


def fmt_num(n: float) -> str:
    text = f"{float(n):.4f}"
    return text.rstrip("0").rstrip(".")


def fmt_vec(v) -> str:
    return f"({fmt_num(v[0])}, {fmt_num(v[1])}, {fmt_num(v[2])})"


def material_block(name: str, diffuse, metallic: float, roughness: float, specular=None, emissive=None, opacity=None) -> str:
    lines = [
        f'        def Material "{name}"',
        "        {",
        f"            token outputs:surface.connect = </ComputeSatelliteMesh/_Materials/{name}/Shader.outputs:surface>",
        '            def Shader "Shader"',
        "            {",
        '                uniform token info:id = "UsdPreviewSurface"',
        f"                color3f inputs:diffuseColor = {fmt_vec(diffuse)}",
        f"                float inputs:metallic = {fmt_num(metallic)}",
        f"                float inputs:roughness = {fmt_num(roughness)}",
    ]
    if specular is not None:
        lines.append(f"                color3f inputs:specularColor = {fmt_vec(specular)}")
    if emissive is not None:
        lines.append(f"                color3f inputs:emissiveColor = {fmt_vec(emissive)}")
    if opacity is not None:
        lines.append(f"                float inputs:opacity = {fmt_num(opacity)}")
    lines.extend(
        [
            "                token outputs:surface",
            "            }",
            "        }",
        ]
    )
    return "\n".join(lines)


def mesh_block(name: str, material: str, mesh: trimesh.Trimesh) -> str:
    mesh = mesh.copy()
    mesh.merge_vertices()
    points = ", ".join(fmt_vec(p) for p in mesh.vertices)
    counts = ", ".join("3" for _ in mesh.faces)
    indices = ", ".join(str(int(i)) for tri in mesh.faces for i in tri)
    return (
        f'    def Mesh "{name}"\n'
        "    {\n"
        f'        rel material:binding = </ComputeSatelliteMesh/_Materials/{material}>\n'
        '        uniform token subdivisionScheme = "none"\n'
        f"        int[] faceVertexCounts = [{counts}]\n"
        f"        int[] faceVertexIndices = [{indices}]\n"
        f"        point3f[] points = [{points}]\n"
        "    }\n"
    )


def build_body_shell() -> trimesh.Trimesh:
    parts = [
        box((188, 12, 150), (0, -54, 0)),
        box((170, 10, 140), (0, 52, 0)),
        box((188, 106, 10), (0, -1, -72)),
        box((12, 106, 140), (-92, -1, 0)),
        box((12, 106, 140), (92, -1, 0)),
        box((152, 14, 12), (0, 10, 70)),
        box((144, 12, 12), (0, -30, 69)),
        tapered_prism(188, 150, 26, 10, (0, 44, 0)),
        apply_transform(tapered_prism(46, 140, 76, 36), (-115, 8, 0), (0, 0, 180)),
        tapered_prism(46, 140, 76, 36, (115, 8, 0)),
        box((158, 3, 138), (0, 38, 0)),
        box((164, 2, 148), (0, 57, 0)),
    ]
    return concat(parts)


def build_payload_frame() -> trimesh.Trimesh:
    parts = [
        box((160, 6, 130), (0, -46, 0)),
        box((160, 6, 130), (0, 16, 0)),
        box((6, 62, 130), (-74, -15, 0)),
        box((6, 62, 130), (74, -15, 0)),
        box((160, 5, 6), (0, -15, 62)),
        box((160, 5, 6), (0, -15, -62)),
        box((170, 8, 16), (0, -52, 0)),
        box((126, 2, 6), (0, 7, 60)),
        box((126, 2, 6), (0, 7, -60)),
        box((136, 2, 12), (0, -37, 52)),
        box((136, 2, 12), (0, -37, -52)),
    ]
    for x in (-52, -18, 18, 52):
        parts.append(box((2, 28, 116), (x, -11, 0)))
    for z in (-38, -14, 14, 38):
        parts.append(box((132, 1.8, 2.4), (0, 8, z)))
        parts.append(box((132, 1.2, 2.4), (0, -31, z)))
    return concat(parts)


def build_racks():
    dark = []
    glass = []
    leds = []
    for z in (36, 12, -12, -36):
        for x in (-42, 0, 42):
            dark.append(box((25, 46, 20), (x, -10, z)))
            dark.append(box((22, 2, 18), (x, 13, z)))
            dark.append(box((22, 2, 18), (x, -33, z)))
            dark.append(box((21, 42, 1.5), (x, -10, z - 9)))
            dark.append(box((21, 42, 1.5), (x, -10, z + 9)))
            for y in (-21, -9, 3, 15):
                dark.append(box((20, 1, 16), (x, y, z)))
            glass.append(box((22, 42, 0.8), (x, -10, z + 9.6)))
            leds.append(box((0.6, 36, 0.25), (x - 10.5, -10, z + 10.1)))
            leds.append(box((0.6, 36, 0.25), (x + 10.5, -10, z + 10.1)))
    return concat(dark), concat(glass), concat(leds)


def build_service_modules():
    dark = [
        box((32, 18, 28), (0, 26, -60)),
        box((22, 12, 22), (-30, 28, -54), (0, 0, 8)),
        box((22, 12, 22), (30, 28, -54), (0, 0, -8)),
        box((18, 28, 48), (-82, 6, -20)),
        box((18, 28, 48), (82, 6, -20)),
    ]
    frame = [
        box((86, 2.2, 130), (0, 13, 0)),
        box((58, 2.0, 130), (0, -4, 0)),
    ]
    return concat(dark), concat(frame)


def build_root_module(sign: int):
    shell = [
        apply_transform(tapered_prism(132, 132, 82, 34), (sign * 142, 4, 0), (0, 180 if sign < 0 else 0, 0)),
        box((88, 14, 122), (sign * 120, -2, 0)),
        box((78, 4, 116), (sign * 126, 14, 0)),
        box((74, 4, 108), (sign * 126, -15, 0)),
    ]
    frame = [
        box((126, 12, 44), (sign * 236, 0, 0)),
        box((126, 4.5, 120), (sign * 236, 5, 0)),
        box((126, 4.5, 112), (sign * 236, -5, 0)),
        box((26, 12, 118), (sign * 98, 0, 0)),
        box((56, 12, 22), (sign * 300, 0, 0)),
    ]
    cable = [
        box((126, 1.2, 10), (sign * 236, 3, 20)),
        box((126, 1.2, 10), (sign * 236, -3, -20)),
    ]
    return concat(shell), concat(frame), concat(cable)


def build_wing(sign: int):
    frame = []
    solar_dark = []
    solar_light = []
    radiator = []

    segment_len = 134.0
    segment_gap = 10.0
    pitch = segment_len + segment_gap
    centers = [212.0 + i * pitch for i in range(18)]
    start = centers[0] - segment_len * 0.5 - 6
    end = centers[-1] + segment_len * 0.5 + 6
    width = 338.0
    center = sign * ((start + end) * 0.5)
    wing_len = end - start

    frame.append(box((wing_len, 8, 30), (center, 0, 0)))
    frame.append(box((wing_len, 4.5, width - 16), (center, 3.0, 0)))
    frame.append(box((wing_len, 6.0, 10), (center, 1.0, width * 0.5 - 7)))
    frame.append(box((wing_len, 6.0, 10), (center, 1.0, -width * 0.5 + 7)))
    frame.append(box((172, 14, width - 20), (sign * 176, 0, 0)))
    frame.append(box((104, 12, width - 44), (sign * 124, 0, 0)))

    for x_local in centers:
        x = sign * x_local
        solar_dark.append(box((segment_len, 1.05, 146), (x, 4.05, -92)))
        solar_dark.append(box((segment_len, 1.05, 146), (x, 4.05, 92)))
        solar_light.append(box((segment_len - 10, 0.35, 138), (x, 4.45, -92)))
        solar_light.append(box((segment_len - 10, 0.35, 138), (x, 4.45, 92)))
        radiator.append(box((segment_len, 0.85, 144), (x, -3.55, -92)))
        radiator.append(box((segment_len, 0.85, 144), (x, -3.55, 92)))

    for x_local in np.linspace(start + 60, end - 60, 12):
        frame.append(box((8, 6.0, width - 18), (sign * float(x_local), 1.0, 0)))
    return concat(frame), concat(solar_dark), concat(solar_light), concat(radiator)


def build_top_detail():
    dark = [
        box((30, 6, 24), (-28, 55, -18)),
        box((18, 6, 18), (26, 55, 16)),
        box((12, 12, 12), (48, 57, -30)),
        box((12, 12, 12), (-50, 57, 32)),
    ]
    metal = [
        box((80, 1.8, 80), (0, 53, 0)),
        box((32, 1.8, 18), (0, 54, 40)),
    ]
    glass = [
        sphere(4.8, subdivisions=2, translate=(0, 58, 0), scale=(1.0, 0.45, 1.0)),
        sphere(7.2, subdivisions=2, translate=(54, 60, -38), scale=(1.0, 0.55, 1.0)),
    ]
    return concat(dark), concat(metal), concat(glass)


def build_scene():
    meshes: list[tuple[str, str, trimesh.Trimesh]] = []
    meshes.append(("BodyShell", "Kapton", build_body_shell()))
    meshes.append(("PayloadFrame", "FrameMetal", build_payload_frame()))

    racks_dark, racks_glass, racks_led = build_racks()
    meshes.append(("RackBodies", "ServerDark", racks_dark))
    meshes.append(("RackGlass", "ServerGlass", racks_glass))
    meshes.append(("RackLeds", "LedCyan", racks_led))

    svc_dark, svc_frame = build_service_modules()
    meshes.append(("ServiceModules", "ShellDark", svc_dark))
    meshes.append(("ServiceFrames", "FrameMetal", svc_frame))

    for sign, side in ((-1, "Left"), (1, "Right")):
        root_shell, root_frame, root_cable = build_root_module(sign)
        wing_frame, wing_dark, wing_light, wing_radiator = build_wing(sign)
        meshes.append((f"{side}RootShell", "Kapton", root_shell))
        meshes.append((f"{side}RootFrame", "FrameMetal", root_frame))
        meshes.append((f"{side}RootCable", "CableBlue", root_cable))
        meshes.append((f"{side}WingFrame", "FrameMetal", wing_frame))
        meshes.append((f"{side}WingSolarDark", "SolarBlueDark", wing_dark))
        meshes.append((f"{side}WingSolarLight", "SolarBlueLight", wing_light))
        meshes.append((f"{side}WingRadiator", "RadiatorWhite", wing_radiator))

    top_dark, top_metal, top_glass = build_top_detail()
    meshes.append(("TopDetailDark", "ShellDark", top_dark))
    meshes.append(("TopDetailMetal", "FrameMetal", top_metal))
    meshes.append(("TopDetailGlass", "ServerGlass", top_glass))
    return meshes


def build_usda(meshes):
    materials = [
        material_block("Kapton", (0.925, 0.645, 0.08), 0.38, 0.18, specular=(1.0, 0.94, 0.68)),
        material_block("ShellDark", (0.11, 0.12, 0.15), 0.58, 0.26),
        material_block("FrameMetal", (0.70, 0.73, 0.78), 0.88, 0.16),
        material_block("SolarBlueDark", (0.03, 0.13, 0.31), 0.84, 0.09, specular=(0.18, 0.38, 0.62)),
        material_block("SolarBlueLight", (0.10, 0.28, 0.52), 0.62, 0.12, specular=(0.32, 0.54, 0.82)),
        material_block("RadiatorWhite", (0.92, 0.94, 0.97), 0.08, 0.42),
        material_block("ServerDark", (0.09, 0.10, 0.12), 0.28, 0.54),
        material_block("ServerGlass", (0.15, 0.24, 0.30), 0.02, 0.08, opacity=0.38),
        material_block("LedCyan", (0.20, 0.82, 0.98), 0.02, 0.18, emissive=(0.10, 0.72, 0.98)),
        material_block("CableBlue", (0.20, 0.55, 0.84), 0.20, 0.34),
    ]
    mesh_text = "\n".join(mesh_block(name, mat, mesh) for name, mat, mesh in meshes)
    return (
        '#usda 1.0\n'
        '(\n'
        '    defaultPrim = "ComputeSatelliteMesh"\n'
        '    metersPerUnit = 0.01\n'
        '    upAxis = "Y"\n'
        ')\n\n'
        'def Xform "ComputeSatelliteMesh"\n'
        '{\n'
        '    def Scope "_Materials"\n'
        '    {\n'
        + "\n\n".join(materials) +
        '\n    }\n\n'
        + mesh_text +
        '}\n'
    )


def main() -> None:
    meshes = build_scene()
    OUT_PATH.write_text(build_usda(meshes), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
