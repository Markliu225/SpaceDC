"""Generate usd/twin_satellite.usda — a procedural satellite assembly with
USD VariantSets for swappable hardware (GPU / Solar Panel / Radiator).

The output is a sublayer for `usd/satellite.usda`. The existing
`components.usda` (LUMID monolith) stays in the tree for reference but
is no longer the primary visible body.

Topology:
    /World
        /Satellite
            /Bus                      — central body (cube)
            /SolarPanelWing_N         — VariantSet 'solar_size' + 'solar_material'
            /SolarPanelWing_S
            /Radiator_East            — VariantSet 'radiator_size' + 'radiator_material'
            /Radiator_West
            /DGX_Rack                 — VariantSet 'gpu'
        /Looks
            /Solar_{Si,GaAs,Perovskite}
            /Rad_{Aluminum,WhitePaint,OSR,Graphite}
            /GPU_{H100,H200,B200,MI300X}
            /BusShell

All values are tied to the data tables in
docs/satellite_twin_implementation.md §3 / web/src/data/satConfigOptions.ts.

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
# Data tables — kept inline so the generator is self-contained.
# ---------------------------------------------------------------------------

# All sizes assume metersPerUnit = 0.01 (satellite.usda) so 1 unit = 1 cm.
# To get satellite-scale visuals at the existing Closeup camera (~280 units
# from origin) we keep the bus ~200 cm = 2 m on its long axis.

GPU_VARIANTS = {
    # color tint roughly matches the design token (tint in satConfigOptions.ts)
    "H100":   {"diffuse": (0.29, 0.33, 0.40), "metallic": 0.7, "roughness": 0.35},
    "H200":   {"diffuse": (0.23, 0.51, 0.99), "metallic": 0.6, "roughness": 0.30},
    "B200":   {"diffuse": (0.06, 0.09, 0.16), "metallic": 0.8, "roughness": 0.20},
    "MI300X": {"diffuse": (0.86, 0.15, 0.15), "metallic": 0.6, "roughness": 0.35},
}

SOLAR_MATERIALS = {
    "Si":         {"diffuse": (0.06, 0.12, 0.40), "metallic": 0.4, "roughness": 0.30},
    "GaAs":       {"diffuse": (0.20, 0.05, 0.32), "metallic": 0.65, "roughness": 0.22},
    "Perovskite": {"diffuse": (0.50, 0.30, 0.85), "metallic": 0.45, "roughness": 0.15,
                   "emissive": (0.30, 0.18, 0.55)},  # thin-film iridescence proxy
}

# Each size — defines how many panel cells per wing and the cell size in cm.
# Two wings on the satellite, mirrored on +Y / -Y. XL doubles the cell rows.
SOLAR_SIZES = {
    "S":  {"cells_per_wing": 2, "cell_w_cm": 200, "cell_h_cm": 100},
    "M":  {"cells_per_wing": 2, "cell_w_cm": 283, "cell_h_cm": 141},
    "L":  {"cells_per_wing": 2, "cell_w_cm": 346, "cell_h_cm": 173},
    "XL": {"cells_per_wing": 4, "cell_w_cm": 400, "cell_h_cm": 200},
}

RADIATOR_MATERIALS = {
    "Aluminum":   {"diffuse": (0.75, 0.76, 0.78), "metallic": 0.95, "roughness": 0.15},
    "WhitePaint": {"diffuse": (0.94, 0.94, 0.94), "metallic": 0.05, "roughness": 0.45},
    "OSR":        {"diffuse": (0.82, 0.85, 0.90), "metallic": 0.70, "roughness": 0.10},
    "Graphite":   {"diffuse": (0.06, 0.06, 0.07), "metallic": 0.15, "roughness": 0.55,
                   "emissive": (0.08, 0.02, 0.00)},  # faint IR red proxy
}

# Each radiator panel mounted vertically on the east/west sides of the bus.
RADIATOR_SIZES = {
    "Compact":  {"w_cm": 100, "h_cm": 100},
    "Standard": {"w_cm": 141, "h_cm": 141},
    "Wide":     {"w_cm": 200, "h_cm": 200},
}

BUS_W_CM = 200     # X — bus length
BUS_D_CM = 150     # Y — bus depth
BUS_H_CM = 120     # Z — bus height
BUS_HALF = (BUS_W_CM / 2, BUS_D_CM / 2, BUS_H_CM / 2)

# Wing root attachment offsets: solar panels stick out along ±Y from bus side.
SOLAR_WING_OFFSETS = {
    "N": ( 0, +BUS_D_CM / 2, 0),
    "S": ( 0, -BUS_D_CM / 2, 0),
}

# Radiator placement on ±X sides.
RADIATOR_OFFSETS = {
    "East": (+BUS_W_CM / 2, 0, 0),
    "West": (-BUS_W_CM / 2, 0, 0),
}


# ---------------------------------------------------------------------------
# USDA snippet helpers — we emit text directly (Pixar's Usd python isn't a
# venv dep in this repo, so the existing tools/gen_*.py all do string prints).
# ---------------------------------------------------------------------------

def _vec3(t: tuple[float, float, float]) -> str:
    return f"({t[0]:.4f}, {t[1]:.4f}, {t[2]:.4f})"


def _color3f(t: tuple[float, float, float]) -> str:
    return f"({t[0]:.3f}, {t[1]:.3f}, {t[2]:.3f})"


def material_block(name: str, params: dict) -> str:
    """One UsdPreviewSurface material definition. Optional emissive."""
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
    blocks.append(material_block("BusShell", {
        "diffuse": (0.82, 0.62, 0.18),  # matches existing LumidShell
        "metallic": 0.9, "roughness": 0.30,
    }))
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
# Geometry blocks — Cubes scaled to component size, then xformed into place.
# UsdGeomCube has size=2 by default (extents [-1,1] on each axis), so we
# scale by half-extents (in cm) to get the desired outer size.
# ---------------------------------------------------------------------------

def bus_prim() -> str:
    sx, sy, sz = BUS_HALF
    return f"""
    def Cube "Bus" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {{
        double size = 2.0
        double3 xformOp:scale = ({sx:.2f}, {sy:.2f}, {sz:.2f})
        uniform token[] xformOpOrder = ["xformOp:scale"]
        rel material:binding = </World/Looks/BusShell>
    }}"""


def solar_panel_cell(cell_idx: int, cell_w: float, cell_h: float, wing_sign: int) -> str:
    """One solar cell, positioned at cell_idx (0..cells-1) along the +Y boom.
    wing_sign = +1 for N, -1 for S. We assume cells stack tip-to-tip along Y.
    Boom length per cell == cell_w (the panel's longest dimension)."""
    # Cell center Y in the wing's local frame: cumulative distance from bus.
    cy = wing_sign * (cell_w / 2 + cell_idx * cell_w)
    # Panel is a thin plate: extends ±cell_w/2 in X, ±cell_h/2 in Y_local, ±2 in Z.
    return f"""
        def Cube "Cell_{cell_idx}" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double size = 2.0
            double3 xformOp:translate = (0, {cy:.2f}, 0)
            double3 xformOp:scale = ({cell_h / 2:.2f}, {cell_w / 2:.2f}, 1.5)
            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
        }}"""


def solar_wing(name: str, wing_sign: int, root_offset: tuple[float, float, float]) -> str:
    """Build the SolarPanelWing_{N,S} prim with two VariantSets.
       - solar_size selects N cells per wing (varies count + cell dimensions)
       - solar_material rebinds material on every cell.

    Crucial: the base def of /Cells must NOT carry its own
    material:binding — if it does, variant `over`s lose the precedence
    fight and the material never visibly changes. So the Cells prim is
    declared with MaterialBindingAPI but no default binding; every
    solar_material variant authors the binding explicitly."""
    size_variants_blocks = []
    for size_id, sd in SOLAR_SIZES.items():
        n  = sd["cells_per_wing"]
        cw = sd["cell_w_cm"]
        ch = sd["cell_h_cm"]
        cells = "\n".join(solar_panel_cell(i, cw, ch, wing_sign) for i in range(n))
        size_variants_blocks.append(f"""        "{size_id}" {{
            over "Cells"
            {{
{indent(cells, '            ').rstrip()}
            }}
        }}""")
    size_variants = "\n".join(size_variants_blocks)

    mat_variants_blocks = []
    for mat_id in SOLAR_MATERIALS.keys():
        mat_variants_blocks.append(f"""        "{mat_id}" {{
            over "Cells"
            {{
                rel material:binding = </World/Looks/Solar_{mat_id}>
            }}
        }}""")
    mat_variants = "\n".join(mat_variants_blocks)

    ox, oy, oz = root_offset
    return f"""
    def Xform "SolarPanelWing_{name}" (
        variants = {{
            string solar_size = "M"
            string solar_material = "Si"
        }}
        prepend variantSets = ["solar_size", "solar_material"]
    )
    {{
        double3 xformOp:translate = ({ox:.2f}, {oy:.2f}, {oz:.2f})
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Xform "Cells" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
        }}

        variantSet "solar_size" = {{
{size_variants}
        }}
        variantSet "solar_material" = {{
{mat_variants}
        }}
    }}"""


def radiator_panel(name: str, root_offset: tuple[float, float, float], face_sign: int) -> str:
    """Radiator_{East,West} — single flat panel mounted perpendicular to the X
    axis. VariantSets:
       - radiator_size: changes the Cube scale
       - radiator_material: rebinds material:binding.

    Same trick as solar — the base def has NO default binding; every
    material variant authors its own, so variant `over`s actually win."""
    size_variants_blocks = []
    for size_id, sd in RADIATOR_SIZES.items():
        w = sd["w_cm"]
        h = sd["h_cm"]
        # The panel is a thin slab; long-axis along ±X but most of its surface
        # lies in the YZ plane facing outward. Scale: very thin in X, w in Y,
        # h in Z.
        size_variants_blocks.append(f"""        "{size_id}" {{
            over "Panel"
            {{
                double3 xformOp:scale = (2.0, {w / 2:.2f}, {h / 2:.2f})
                uniform token[] xformOpOrder = ["xformOp:scale"]
            }}
        }}""")
    size_variants = "\n".join(size_variants_blocks)

    mat_variants_blocks = []
    for mat_id in RADIATOR_MATERIALS.keys():
        mat_variants_blocks.append(f"""        "{mat_id}" {{
            over "Panel"
            {{
                rel material:binding = </World/Looks/Rad_{mat_id}>
            }}
        }}""")
    mat_variants = "\n".join(mat_variants_blocks)

    ox, oy, oz = root_offset
    # Push the panel out by ~half the bus depth + half the smallest radiator
    # so it doesn't intersect.
    return f"""
    def Xform "Radiator_{name}" (
        variants = {{
            string radiator_size = "Standard"
            string radiator_material = "Aluminum"
        }}
        prepend variantSets = ["radiator_size", "radiator_material"]
    )
    {{
        double3 xformOp:translate = ({ox + face_sign * 50:.2f}, {oy:.2f}, {oz:.2f})
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Cube "Panel" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double size = 2.0
            double3 xformOp:scale = (2.0, 70.5, 70.5)
            uniform token[] xformOpOrder = ["xformOp:scale"]
        }}

        variantSet "radiator_size" = {{
{size_variants}
        }}
        variantSet "radiator_material" = {{
{mat_variants}
        }}
    }}"""


def dgx_rack() -> str:
    """Eight GPU cards in a 4-wide × 2-tall grid inside the bus cavity.
    GPU variant only changes the cards' material binding — geometry is the
    same across all four GPU types."""
    cards = []
    # Grid: 4 columns × 2 rows on the X axis, fits within bus envelope.
    card_w = 38  # cm
    card_d = 22
    card_h = 8
    rows = 2
    cols = 4
    spacing_x = 5
    spacing_z = 4
    total_w = cols * card_w + (cols - 1) * spacing_x
    start_x = -total_w / 2 + card_w / 2
    total_h = rows * card_h + (rows - 1) * spacing_z
    start_z = -total_h / 2 + card_h / 2 - 30   # sit low inside bus

    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            cx = start_x + c * (card_w + spacing_x)
            cz = start_z + r * (card_h + spacing_z)
            cards.append(f"""
        def Cube "GPU_{i + 1:02d}" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double size = 2.0
            double3 xformOp:translate = ({cx:.2f}, 0, {cz:.2f})
            double3 xformOp:scale = ({card_w / 2}, {card_d / 2}, {card_h / 2})
            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
        }}""")

    cards_text = "".join(cards)

    gpu_variants_blocks = []
    for gpu_id in GPU_VARIANTS.keys():
        per_card_overrides = "\n".join(
            f"""            over "GPU_{i + 1:02d}" (
                prepend apiSchemas = ["MaterialBindingAPI"]
            )
            {{
                rel material:binding = </World/Looks/GPU_{gpu_id}>
            }}"""
            for i in range(rows * cols)
        )
        gpu_variants_blocks.append(f"""        "{gpu_id}" {{
{per_card_overrides}
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
        double3 xformOp:translate = (0, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
{cards_text}
        variantSet "gpu" = {{
{gpu_variants}
        }}
    }}"""


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

def cameras_scope() -> str:
    """The Closeup camera — same eye/target as the existing components.usda
    so the satellite is framed identically when we swap layers. Hand-rolled
    look-at matrix (eye at +X +Y +Z looking at origin)."""
    eye = (440.0, -480.0, 280.0)
    target = (0.0, 0.0, 0.0)
    # Compute look-at matrix manually.
    fx, fy, fz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
    fn = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
    fx, fy, fz = fx / fn, fy / fn, fz / fn
    # right = forward × world_up
    wux, wuy, wuz = 0.0, 0.0, 1.0
    rx = fy * wuz - fz * wuy
    ry = fz * wux - fx * wuz
    rz = fx * wuy - fy * wux
    rn = math.sqrt(rx * rx + ry * ry + rz * rz) or 1.0
    rx, ry, rz = rx / rn, ry / rn, rz / rn
    # up = right × forward
    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx
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
        float focusDistance = 600
        float2 clippingRange = (1, 4000)
        matrix4d xformOp:transform = (
                {rows_text}
        )
        uniform token[] xformOpOrder = ["xformOp:transform"]
    }}
}}"""


# ---------------------------------------------------------------------------
# Assembler.
# ---------------------------------------------------------------------------

def build_usda() -> str:
    parts: list[str] = []
    parts.append('#usda 1.0')
    parts.append('(')
    parts.append('    defaultPrim = "World"')
    parts.append('    upAxis = "Z"')
    parts.append('    metersPerUnit = 0.01')
    parts.append('    doc = "Procedural satellite assembly with VariantSets for the Twin page swappable hardware. Generated by tools/gen_twin_satellite.py."')
    parts.append(')')
    parts.append('')
    parts.append('def Xform "World"')
    parts.append('{')

    # Looks scope first so variant blocks can reference paths cleanly.
    parts.append(indent(looks_scope(), '    '))
    parts.append('')

    parts.append('    def Xform "Satellite"')
    parts.append('    {')
    parts.append(bus_prim())
    parts.append(solar_wing("N", +1, SOLAR_WING_OFFSETS["N"]))
    parts.append(solar_wing("S", -1, SOLAR_WING_OFFSETS["S"]))
    parts.append(radiator_panel("East", RADIATOR_OFFSETS["East"], +1))
    parts.append(radiator_panel("West", RADIATOR_OFFSETS["West"], -1))
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
