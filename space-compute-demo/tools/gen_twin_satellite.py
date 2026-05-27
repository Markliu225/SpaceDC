"""Generate usd/twin_satellite.usda — the Twin page's reconfigurable
satellite assembly.

Topology:
    /World
        /Looks                                      — 11 swappable materials
        /Satellite
            /Bus  ← references @./assets/Satellite_v022.usdc@
                — has built-in Mesh subsets Bus/Panel/Dish/Boom
                — variantSet "solar_material" overrides Mesh/Panel material:binding
            /DeployableSolar_N                      — extra solar wing, +Y
                — variantSet "solar_size"     (S/M/L/XL — geometry scale)
                — variantSet "solar_material" (Si/GaAs/Perovskite — material)
            /DeployableSolar_S                      — extra solar wing, -Y (mirror)
            /Radiator_East / _West                  — thin plate augments, ±X
                — variantSet "radiator_size"     (Compact/Standard/Wide)
                — variantSet "radiator_material" (Aluminum/WhitePaint/OSR/Graphite)
            /DGX_Rack                               — 8 GPU cards inside the bus
                — variantSet "gpu" (H100/H200/B200/MI300X — material)
        /Cameras/Closeup

Visual policy:
    - The body is the existing v022 STL — already PBR-shaded, no cubes.
    - Deployable solar wings are THIN (5 cm) plates ~2 m on a side, slightly
      tilted, with edge stiffeners so they read as panels not slabs.
    - Radiators are even thinner (3 cm) plates with edge frames.
    - GPU cards sit in a 4×2 grid inside the bus envelope, invisible until
      the future "interior" cutaway view is wired up but the variant still
      drives the backend physics through the SatelliteConfig contract.

Run:
    python tools/gen_twin_satellite.py
"""
from __future__ import annotations

import math
from pathlib import Path
from textwrap import indent

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "usd" / "twin_satellite.usda"

# ---------------------------------------------------------------------------
# Reference asset — used as the satellite Bus body.
# ---------------------------------------------------------------------------
BUS_REF = "./assets/Satellite_v022.usdc"
# Bus extents in cm (probed from Usd.Stage): ~106 × 168 × 168, centered on
# origin with min y ≈ -89. Use these to attach deployable wings + radiators
# at the right offsets.
BUS_X_MAX_CM = 53.0
BUS_X_MIN_CM = -67.0
BUS_Y_MAX_CM = 80.0
BUS_Y_MIN_CM = -89.0
BUS_Z_HALF_CM = 84.0
BUS_X_HALF_CM = max(abs(BUS_X_MAX_CM), abs(BUS_X_MIN_CM))
BUS_Y_HALF_CM = max(abs(BUS_Y_MAX_CM), abs(BUS_Y_MIN_CM))

# ---------------------------------------------------------------------------
# Materials — kept in /World/Looks. The Bus prim's solar_material variant
# rebinds /World/Satellite/Bus/Mesh/Panel to one of the Solar_* entries here.
# ---------------------------------------------------------------------------

GPU_VARIANTS = {
    "H100":   {"diffuse": (0.29, 0.33, 0.40), "metallic": 0.7, "roughness": 0.35},
    "H200":   {"diffuse": (0.23, 0.51, 0.99), "metallic": 0.6, "roughness": 0.30},
    "B200":   {"diffuse": (0.06, 0.09, 0.16), "metallic": 0.8, "roughness": 0.20},
    "MI300X": {"diffuse": (0.86, 0.15, 0.15), "metallic": 0.6, "roughness": 0.35},
}

SOLAR_MATERIALS = {
    # Each material's diffuse + emissive is hand-tuned for an UNMISTAKABLE
    # color swap under the satellite-stage warm Sun (Key light intensity
    # 2800, color 1.0/0.96/0.88). The emissive lifts every panel above the
    # diffuse-only response which can wash out cool tones against the warm
    # key — we deliberately push emissive ≥ 0.7 on at least one channel so
    # the panel reads in its own colour regardless of lighting.
    "Si":         {"diffuse": (0.05, 0.15, 0.85), "metallic": 0.30, "roughness": 0.35,
                   "emissive": (0.10, 0.20, 0.85)},                    # bright vivid blue
    "GaAs":       {"diffuse": (0.45, 0.10, 0.55), "metallic": 0.75, "roughness": 0.20,
                   "emissive": (0.60, 0.10, 0.80)},                    # deep violet
    "Perovskite": {"diffuse": (1.00, 0.35, 0.75), "metallic": 0.50, "roughness": 0.15,
                   "emissive": (1.40, 0.20, 0.90)},                    # magenta/iridescent
}

# Deployable wing dimensions: width along Y (away from bus), height along Z.
# panel_count duplicates the panel cells along Y for the bigger sizes.
SOLAR_SIZES = {
    "S":  {"length_cm": 0,   "height_cm": 0,  "panel_count": 0},     # no extra wing
    "M":  {"length_cm": 250, "height_cm": 90,  "panel_count": 1},    # one panel each side
    "L":  {"length_cm": 380, "height_cm": 110, "panel_count": 1},
    "XL": {"length_cm": 540, "height_cm": 140, "panel_count": 2},    # two stacked panels
}

RADIATOR_MATERIALS = {
    "Aluminum":   {"diffuse": (0.75, 0.76, 0.78), "metallic": 0.95, "roughness": 0.15},
    "WhitePaint": {"diffuse": (0.94, 0.94, 0.94), "metallic": 0.05, "roughness": 0.45},
    "OSR":        {"diffuse": (0.82, 0.85, 0.90), "metallic": 0.70, "roughness": 0.10},
    "Graphite":   {"diffuse": (0.07, 0.07, 0.08), "metallic": 0.15, "roughness": 0.55,
                   "emissive": (0.08, 0.02, 0.00)},
}

RADIATOR_SIZES = {
    "Compact":  {"width_cm": 120, "height_cm": 90},
    "Standard": {"width_cm": 170, "height_cm": 120},
    "Wide":     {"width_cm": 240, "height_cm": 160},
}

# ---------------------------------------------------------------------------
# USDA string helpers.
# ---------------------------------------------------------------------------

def _color3f(t: tuple[float, float, float]) -> str:
    return f"({t[0]:.3f}, {t[1]:.3f}, {t[2]:.3f})"


def material_block(name: str, params: dict) -> str:
    emissive = params.get("emissive", (0.0, 0.0, 0.0))
    return f"""
    def Material "{name}"
    {{
        token outputs:surface.connect = </World/Looks/{name}/Shader.outputs:surface>
        def Shader "Shader"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor = {_color3f(params['diffuse'])}
            color3f inputs:emissiveColor = {_color3f(emissive)}
            float inputs:metallic = {params['metallic']:.3f}
            float inputs:roughness = {params['roughness']:.3f}
            int inputs:useSpecularWorkflow = 0
            token outputs:surface
        }}
    }}"""


def looks_scope() -> str:
    blocks = []
    for k, v in SOLAR_MATERIALS.items():
        blocks.append(material_block(f"Solar_{k}", v))
    for k, v in RADIATOR_MATERIALS.items():
        blocks.append(material_block(f"Rad_{k}", v))
    for k, v in GPU_VARIANTS.items():
        blocks.append(material_block(f"GPU_{k}", v))
    return f"""def Scope "Looks"
{{{''.join(blocks)}
}}"""


# ---------------------------------------------------------------------------
# /World/Satellite/Bus — references Satellite_v022, exposes solar_material.
#
# To override the LUMID Panel subset's material, the variant authors a
# nested `over Mesh { over Panel { rel material:binding = … } }` — this is
# the same pattern verified via pxr.UsdShade.MaterialBindingAPI.
# ---------------------------------------------------------------------------

def bus_prim() -> str:
    mat_variants_blocks = []
    for mat_id in SOLAR_MATERIALS.keys():
        mat_variants_blocks.append(f"""        "{mat_id}" {{
            over "Mesh"
            {{
                over "Panel"
                {{
                    rel material:binding = </World/Looks/Solar_{mat_id}>
                }}
            }}
        }}""")
    mat_variants = "\n".join(mat_variants_blocks)
    return f"""
    def Xform "Bus" (
        prepend references = @{BUS_REF}@
        variants = {{
            string solar_material = "Si"
        }}
        prepend variantSets = ["solar_material"]
    )
    {{
        variantSet "solar_material" = {{
{mat_variants}
        }}
    }}"""


# ---------------------------------------------------------------------------
# Deployable solar wings — augmenting the bus's built-in panels.
#
# Geometry: thin Cube scaled to (length, height, 5) cm — flat plate.
# Edge stiffener: a slimmer Cube alongside as a frame.
#
# Variant authoring trick: the base def hides the wing geometry (visibility =
# invisible) and zero-extent the cube. Each solar_size variant overlays the
# actual scale + translate + visibility = inherited. The "S" variant simply
# does NOT author visibility, so it stays invisible — no wing rendered.
# ---------------------------------------------------------------------------

def solar_wing(name: str, wing_sign: int) -> str:
    """name = 'N' or 'S'; wing_sign = +1 for +Y, -1 for -Y."""
    size_variants_blocks = []
    for size_id, sd in SOLAR_SIZES.items():
        length = sd["length_cm"]
        height = sd["height_cm"]
        count  = sd["panel_count"]
        if count == 0:
            # No wing at this size — leave the prim hidden.
            size_variants_blocks.append(f"""        "{size_id}" {{
            over "Wing"
            {{
                token visibility = "invisible"
            }}
        }}""")
            continue
        # Panel center is offset out along the wing's Y so its near edge
        # tucks against the bus's far Y face.
        panel_offset_y = BUS_Y_HALF_CM + length / 2
        # The visible plate sits at panel_offset_y; with count>1 we stack
        # additional plates along Z (tile vertically rather than further out).
        panel_x_half = length / 2     # panel "long" axis along Y (away from bus)
        panel_z_half = height / 2
        plate_overrides = [
            f"""                over "Plate"
                {{
                    token visibility = "inherited"
                    double3 xformOp:translate = (0, {wing_sign * panel_offset_y:.2f}, 0)
                    double3 xformOp:scale = ({panel_z_half:.2f}, {panel_x_half:.2f}, 2.5)
                    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
                }}"""
        ]
        # Edge stiffener — a thin bar along the panel's outer Y edge.
        plate_overrides.append(f"""                over "EdgeStiffener"
                {{
                    token visibility = "inherited"
                    double3 xformOp:translate = (0, {wing_sign * (panel_offset_y + panel_x_half - 2):.2f}, 0)
                    double3 xformOp:scale = ({panel_z_half + 3:.2f}, 2.0, 4.0)
                    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
                }}""")
        if count >= 2:
            # Second plate stacked above (along +Z) the first.
            plate_overrides.append(f"""                over "Plate2"
                {{
                    token visibility = "inherited"
                    double3 xformOp:translate = (0, {wing_sign * panel_offset_y:.2f}, {panel_z_half * 2 + 4:.2f})
                    double3 xformOp:scale = ({panel_z_half:.2f}, {panel_x_half:.2f}, 2.5)
                    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
                }}""")
        overrides_text = "\n".join(plate_overrides)
        size_variants_blocks.append(f"""        "{size_id}" {{
            over "Wing"
            {{
                token visibility = "inherited"
{overrides_text}
            }}
        }}""")
    size_variants = "\n".join(size_variants_blocks)

    mat_variants_blocks = []
    for mat_id in SOLAR_MATERIALS.keys():
        mat_variants_blocks.append(f"""        "{mat_id}" {{
            over "Wing"
            {{
                over "Plate"
                {{
                    rel material:binding = </World/Looks/Solar_{mat_id}>
                }}
                over "Plate2"
                {{
                    rel material:binding = </World/Looks/Solar_{mat_id}>
                }}
            }}
        }}""")
    mat_variants = "\n".join(mat_variants_blocks)

    return f"""
    def Xform "DeployableSolar_{name}" (
        variants = {{
            string solar_size = "M"
            string solar_material = "Si"
        }}
        prepend variantSets = ["solar_size", "solar_material"]
    )
    {{
        def Xform "Wing"
        {{
            def Cube "Plate" (
                prepend apiSchemas = ["MaterialBindingAPI"]
            )
            {{
                double size = 2.0
            }}
            def Cube "Plate2" (
                prepend apiSchemas = ["MaterialBindingAPI"]
            )
            {{
                double size = 2.0
            }}
            def Cube "EdgeStiffener" (
                prepend apiSchemas = ["MaterialBindingAPI"]
            )
            {{
                double size = 2.0
                rel material:binding = </World/Bus/Looks/BoomAlu>
            }}
        }}

        variantSet "solar_size" = {{
{size_variants}
        }}
        variantSet "solar_material" = {{
{mat_variants}
        }}
    }}"""


# ---------------------------------------------------------------------------
# Radiator augments — thin plates on ±X sides of the bus.
# ---------------------------------------------------------------------------

def radiator(name: str, face_sign: int) -> str:
    """face_sign = +1 for east (+X) / -1 for west (-X)."""
    size_variants_blocks = []
    for size_id, sd in RADIATOR_SIZES.items():
        w = sd["width_cm"]
        h = sd["height_cm"]
        # Panel mounted on the side of the bus, facing outward.
        # Cube scaled to (very thin in X, w in Y, h in Z).
        offset_x = BUS_X_HALF_CM + 8  # 8 cm gap from bus
        size_variants_blocks.append(f"""        "{size_id}" {{
            over "Plate"
            {{
                token visibility = "inherited"
                double3 xformOp:translate = ({face_sign * offset_x:.2f}, 0, 0)
                double3 xformOp:scale = (1.5, {w / 2:.2f}, {h / 2:.2f})
                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
            }}
            over "Frame"
            {{
                token visibility = "inherited"
                double3 xformOp:translate = ({face_sign * (offset_x + 1.5):.2f}, 0, 0)
                double3 xformOp:scale = (0.8, {w / 2 + 2:.2f}, {h / 2 + 2:.2f})
                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
            }}
        }}""")
    size_variants = "\n".join(size_variants_blocks)

    mat_variants_blocks = []
    for mat_id in RADIATOR_MATERIALS.keys():
        mat_variants_blocks.append(f"""        "{mat_id}" {{
            over "Plate"
            {{
                rel material:binding = </World/Looks/Rad_{mat_id}>
            }}
        }}""")
    mat_variants = "\n".join(mat_variants_blocks)

    return f"""
    def Xform "Radiator_{name}" (
        variants = {{
            string radiator_size = "Standard"
            string radiator_material = "Aluminum"
        }}
        prepend variantSets = ["radiator_size", "radiator_material"]
    )
    {{
        def Cube "Plate" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double size = 2.0
        }}
        def Cube "Frame" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double size = 2.0
            rel material:binding = </World/Bus/Looks/BoomAlu>
        }}

        variantSet "radiator_size" = {{
{size_variants}
        }}
        variantSet "radiator_material" = {{
{mat_variants}
        }}
    }}"""


# ---------------------------------------------------------------------------
# DGX_Rack — 8 GPU cards in 4×2 grid. Default invisible (sits inside the
# bus envelope — a future "interior" view will reveal them). gpu variant
# rebinds material on every card.
# ---------------------------------------------------------------------------

def dgx_rack() -> str:
    card_w, card_d, card_h = 25, 16, 6  # cm
    rows, cols = 2, 4
    sx = card_w + 3
    sz = card_h + 3
    cards = []
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            cx = (c - (cols - 1) / 2) * sx
            cz = (r - (rows - 1) / 2) * sz
            # Cards stay invisible by default — they live inside the bus and
            # are only revealed by a future "interior" view (not P1). The
            # variant still rebinds materials so the backend stays in sync.
            cards.append(f"""
        def Cube "GPU_{i + 1:02d}" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double size = 2.0
            token visibility = "invisible"
            double3 xformOp:translate = ({cx:.2f}, 0, {cz:.2f})
            double3 xformOp:scale = ({card_w / 2}, {card_d / 2}, {card_h / 2})
            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
        }}""")
    cards_text = "".join(cards)

    gpu_variants_blocks = []
    for gpu_id in GPU_VARIANTS.keys():
        per_card = "\n".join(
            f"""            over "GPU_{i + 1:02d}"
            {{
                rel material:binding = </World/Looks/GPU_{gpu_id}>
            }}"""
            for i in range(rows * cols)
        )
        gpu_variants_blocks.append(f"""        "{gpu_id}" {{
{per_card}
        }}""")
    gpu_variants = "\n".join(gpu_variants_blocks)

    return f"""
    def Xform "DGX_Rack" (
        variants = {{
            string gpu = "H100"
        }}
        prepend variantSets = ["gpu"]
    )
    {{
        double3 xformOp:translate = (0, 0, -10)
        uniform token[] xformOpOrder = ["xformOp:translate"]
{cards_text}
        variantSet "gpu" = {{
{gpu_variants}
        }}
    }}"""


# ---------------------------------------------------------------------------
# Camera.
# ---------------------------------------------------------------------------

def cameras_scope() -> str:
    # Pulled WAY back compared to the original Closeup — the XL solar
    # config extends ±620 cm along Y, so the camera at ~250 cm would
    # have the wing tips falling outside the frame. From ~1700 cm out
    # at this 35 mm focal length, the visible width is ~1700 cm — enough
    # for the 1260 cm full-XL extent with comfortable headroom.
    eye = (1100.0, -1100.0, 700.0)
    target = (0.0, 0.0, 50.0)
    fx, fy, fz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
    fn = math.sqrt(fx*fx + fy*fy + fz*fz) or 1.0
    fx, fy, fz = fx/fn, fy/fn, fz/fn
    wux, wuy, wuz = 0.0, 0.0, 1.0
    rx, ry, rz = fy*wuz - fz*wuy, fz*wux - fx*wuz, fx*wuy - fy*wux
    rn = math.sqrt(rx*rx + ry*ry + rz*rz) or 1.0
    rx, ry, rz = rx/rn, ry/rn, rz/rn
    ux, uy, uz = ry*fz - rz*fy, rz*fx - rx*fz, rx*fy - ry*fx
    rows = [
        (rx, ry, rz, 0.0),
        (ux, uy, uz, 0.0),
        (-fx, -fy, -fz, 0.0),
        (eye[0], eye[1], eye[2], 1.0),
    ]
    rows_text = ",\n                ".join(
        f"({r[0]:.5f}, {r[1]:.5f}, {r[2]:.5f}, {r[3]:.5f})" for r in rows
    )
    return f"""def Xform "Cameras"
{{
    def Camera "Closeup"
    {{
        float focalLength = 35.0
        float focusDistance = 1700
        float2 clippingRange = (1, 8000)
        matrix4d xformOp:transform = (
                {rows_text}
        )
        uniform token[] xformOpOrder = ["xformOp:transform"]
    }}
}}"""


def build_usda() -> str:
    parts: list[str] = []
    parts.append('#usda 1.0')
    parts.append('(')
    parts.append('    defaultPrim = "World"')
    parts.append('    upAxis = "Z"')
    parts.append('    metersPerUnit = 0.01')
    parts.append('    doc = "Twin satellite assembly — references the existing Satellite_v022 body and decorates it with reconfigurable solar wings + radiator panels + GPU rack. Generated by tools/gen_twin_satellite.py."')
    parts.append(')')
    parts.append('')
    parts.append('def Xform "World"')
    parts.append('{')
    parts.append(indent(looks_scope(), '    '))
    parts.append('')
    parts.append('    def Xform "Satellite"')
    parts.append('    {')
    parts.append(bus_prim())
    parts.append(solar_wing("N", +1))
    parts.append(solar_wing("S", -1))
    parts.append(radiator("East", +1))
    parts.append(radiator("West", -1))
    parts.append(dgx_rack())
    parts.append('    }')
    parts.append('')
    parts.append(indent(cameras_scope(), '    '))
    parts.append('}')
    parts.append('')
    return "\n".join(parts)


def main() -> None:
    out = build_usda()
    OUT.write_text(out, encoding="utf-8")
    print(f"[gen] wrote {OUT} ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
