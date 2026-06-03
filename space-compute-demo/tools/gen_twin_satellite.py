"""Generate usd/twin_satellite.usda — the Twin page's satellite body.

References satellite_compute.usdz (a Tripo compute-sat model). The asset
ships with only one deployed solar panel on the +Y side and a texture-driven
gray bus shell; this generator fixes both:

  * Mirrors the deployed panel across the bus centerline (y ≈ 0.129 m in
    source meters → translate(0, 0.258, 0)) so the satellite has a panel on
    each side. The mirror is authored as a SUB-PRIM reference of
    @asset@</root/ParentNode/tripo_part_new_1> so only the panel sub-tree is
    duplicated, not the whole satellite.
  * Authors a `BusGold` UsdPreviewSurface in /World/Looks (warm MLI gold,
    matching the canonical BusGold from Satellite_v022.usdc) and overrides
    the bus shell mesh (/root/ParentNode/tripo_part_74_0/Mesh_10) binding
    to that gold, replacing the asset's gray texture-driven look.

The `solar_material` variantSet rebinds BOTH panels (original +
MirroredPanel) so the Twin Configurator dropdown drives them together, and
also gives the mirrored panel a defined material (the sub-prim reference
deliberately omits the asset's /root/_materials scope).

Kept:
    /World
        /Looks/Solar_{Si,GaAs,Perovskite}   — recolour the body's panels
        /Looks/BusGold                       — gold MLI shell override
        /Satellite/Bus  ← references @./assets/satellite_compute.usdz@
            xformOp:scale = 230 — converts meters→cm and frames at ~170 cm
            over the bus mesh → rebound to BusGold
            def Xform "MirroredPanel"  ← sub-prim references the panel,
                xformOp:scale = (1, -1, 1), xformOp:translate = (0, 0.258, 0)
            variantSet "solar_material" rebinds both Mesh_8 panels
        /Cameras/Closeup

The satellite-stage Sun (a DistantLight authored in usd/satellite.usda)
is driven at runtime by space.demo.scene from the backend's
satellite.sun_factor, so the lighting tracks the orbit (bright in
sunlight, dark in eclipse).

Run:
    python tools/gen_twin_satellite.py
"""
from __future__ import annotations

import math
from pathlib import Path
from textwrap import indent

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "usd" / "twin_satellite.usda"

# Tripo payload-bay model: metersPerUnit=1.0, Z-up, default prim /root.
# Contains three component groups — payload bay shell, radar dish, and
# seven GPU plates — clickable from the WebRTC viewport (see
# TwinModulePopup on the Twin page).
BUS_REF = "./assets/satellite_body.usdz"
# Host stage is metersPerUnit=0.01 (cm). Source longest dim is ~1.0 m; ×170
# lands at ~170 cm — matches the prior Satellite_v022 framing so the
# Closeup camera (focusDistance=430 cm) keeps working.
BUS_SCALE = 170.0

# Prim paths inside the asset (surveyed via pxr — pinned so a Tripo
# re-bake fails loud instead of silently misbinding).
ASSET_BUS_MESH = "ParentNode/tripo_part_9/Mesh_0"          # payload bay shell mesh
# Selection regexes for TwinModulePopup are exported separately on the web
# side (see web/src/components/twin/TwinModulePopup.tsx); the IDs below are
# the source of truth so the two sides can't drift.
ASSET_SHELL_PART  = "tripo_part_9"
ASSET_RADAR_PART  = "tripo_part_4"
ASSET_GPU_PARTS   = ("tripo_part_1", "tripo_part_11", "tripo_part_12",
                     "tripo_part_13", "tripo_part_14", "tripo_part_15",
                     "tripo_part_16")

# New solar wing asset (replaces the bus's built-in deployed panel on both
# sides of the payload bay). Standalone Tripo bake — Z-up, meters,
# bbox 0.978 × 0.666 × 0.068 m, single mesh under tripo_node_<uuid>.
SOLAR_REF       = "./assets/solar.usdz"
SOLAR_NODE      = "tripo_node_f428be0e_6763_4c3c_adc0_48f9e995f063"
SOLAR_MESH      = "tripo_mesh_f428be0e_6763_4c3c_adc0_48f9e995f063"
# After rotateY=-90: source X (0.978m long) → +Z (up), source Y (0.666m) →
# Y (deploy axis), source Z (0.068m thick) → -X. Scaled to 0.5 so the panel
# height (~112 cm post-scale, post-Bus-scale) fits comfortably in the
# Closeup camera frame next to the 170 cm body. Panel half-Y after scale =
# 0.167 m; body centroid is at y=0.129 m with body half-Y ≈ 0.30 m. Offset
# 0.47 / -0.21 puts each panel's inner edge ~5 cm from the body's side
# face (in source meters) so they read as wings on the payload bay.
PANEL_SCALE     = 0.95
# Panels lie FLAT on the bus's ±X sides (the "east/west" faces), normal
# parallel to the body's large (X-Y) face normal (= stage Z) so the cell
# face points up at the same direction as the radar mast. solar.usdz's
# source axes have the long edge along source X; we add rotateZ=90 so the
# long edge swings to stage Y and the deploy direction (source Y) lands on
# stage -X. The wing therefore spans the bay's Y dimension and extends
# outward along X. Shell's X face is at ±0.47 m in source meters; offset
# 0.72 lands the wing inner edge ~8 cm past the shell face.
PANEL_LEFT_X    = 0.77
PANEL_RIGHT_X   = -0.77
# Shell centroid in source Z is ~-0.22 m (the shell sits in the lower half
# of the asset, with the radar mast above). Drop the wings to the shell's
# mid-height so they read as deployed tabs emerging from the bay's ±X
# sides, not floating above the bay.
PANEL_Z         = -0.17
# Rotate the wing 90° about its local Z (the thin / normal axis) so it
# turns from the previous N/S layout to E/W — long source-X edge points
# along stage Y instead of stage X.
PANEL_ROTATE_Z  = 90.0

# Panel materials — recolour the body's solar panels. Tuned so the swap
# reads under the satellite-stage warm Sun; emissive keeps the identity
# from washing out against the warm key light.
SOLAR_MATERIALS = {
    "Si":         {"diffuse": (0.05, 0.15, 0.85), "metallic": 0.30, "roughness": 0.35,
                   "emissive": (0.10, 0.20, 0.85)},
    "GaAs":       {"diffuse": (0.45, 0.10, 0.55), "metallic": 0.75, "roughness": 0.20,
                   "emissive": (0.60, 0.10, 0.80)},
    "Perovskite": {"diffuse": (1.00, 0.35, 0.75), "metallic": 0.50, "roughness": 0.15,
                   "emissive": (1.40, 0.20, 0.90)},
}

# Bus shell — warm MLI gold. Sits in the same family as Satellite_v022's
# canonical BusGold (0.78, 0.58, 0.18 / 0.85 / 0.30) and satellite.usda's
# LumidShell (0.82, 0.62, 0.18 / 0.90 / 0.30) so the new body reads in the
# same identity as the rest of the demo. Faint warm emissive keeps the body
# from going pitch black at low sun_factor.
BUS_GOLD = {
    "diffuse":   (0.80, 0.60, 0.20),
    "metallic":  0.88,
    "roughness": 0.32,
    "emissive":  (0.06, 0.04, 0.01),
}


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
    blocks = [material_block(f"Solar_{k}", v) for k, v in SOLAR_MATERIALS.items()]
    blocks.append(material_block("BusGold", BUS_GOLD))
    return f"""def Scope "Looks"
{{{''.join(blocks)}
}}"""


def _nested_over_for_path(path: str, payload: str) -> str:
    """Build a chain of nested USD `over` blocks for a slash-separated prim
    path, with `payload` (already-indented) authored on the innermost prim."""
    parts = path.split("/")
    inner = payload
    for name in reversed(parts):
        inner = f'over "{name}"\n{{\n{indent(inner, "    ")}\n}}'
    return inner


def parentnode_overrides() -> str:
    """Single `over "ParentNode"` block that rebinds the payload bay shell
    mesh to BusGold so it reads as warm MLI gold rather than the asset's
    texture-driven look. (Earlier passes also had to hide an asset-internal
    panel here; satellite_body.usdz ships without one so that override is
    gone.)"""
    return f'''over "ParentNode"
{{
    over "{ASSET_SHELL_PART}"
    {{
        over "Mesh_0"
        {{
            rel material:binding = </World/Looks/BusGold>
        }}
    }}
}}'''


def solar_wing_prim(name: str, x_offset: float) -> str:
    """A solar wing — references solar.usdz with a rotateZ=90 spin so the
    long edge runs across the bay's Y axis and the deploy direction is X.
    Lies FLAT on the bus's ±X face with the cell side facing +Z (the same
    direction the radar mast points).

    xformOpOrder = ["translate","scale","rotateZ"] — USD composes M = M_op0
    * M_op1 * … so the LAST op (rotateZ) is applied first to the local
    point, then scale, then translate."""
    return f"""def Xform "{name}" (
    prepend references = @{SOLAR_REF}@
)
{{
    double3 xformOp:translate = ({x_offset}, 0.0, {PANEL_Z})
    double3 xformOp:scale = ({PANEL_SCALE}, {PANEL_SCALE}, {PANEL_SCALE})
    float xformOp:rotateZ = {PANEL_ROTATE_Z}
    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale", "xformOp:rotateZ"]
}}"""


def solar_variants() -> str:
    """variantSet body — kept wired so the backend's set_config({solar_material:
    ...}) round-trip and the Twin Configurator dropdown continue to work, but
    each variant is now a visual no-op: the panels keep solar.usdz's own
    texture-driven look regardless of the selection."""
    return "\n".join(f'"{m}" {{ }}' for m in SOLAR_MATERIALS.keys())


def bus_prim() -> str:
    """The bus: references the compute-sat asset, scales m→cm with extra
    framing, rebinds the shell to gold, HIDES the built-in deployed panel
    and adds two solar.usdz wings on the +Y / -Y sides of the payload bay
    so the Configurator's solar_material variant drives both panels."""
    parent_overs = indent(parentnode_overrides(),       "        ")
    left_wing    = indent(solar_wing_prim("PanelLeft",  PANEL_LEFT_X),  "        ")
    right_wing   = indent(solar_wing_prim("PanelRight", PANEL_RIGHT_X), "        ")
    variants     = indent(solar_variants(),             "            ")
    return f"""
    def Xform "Bus" (
        prepend references = @{BUS_REF}@
        variants = {{
            string solar_material = "Si"
        }}
        prepend variantSets = ["solar_material"]
    )
    {{
        double3 xformOp:scale = ({BUS_SCALE}, {BUS_SCALE}, {BUS_SCALE})
        uniform token[] xformOpOrder = ["xformOp:scale"]

{parent_overs}

{left_wing}

{right_wing}

        variantSet "solar_material" = {{
{variants}
        }}
    }}"""


def cameras_scope() -> str:
    # Framed for the bare v022 body (~1.6 m across) — closer than the
    # earlier wing-spread camera since there are no deployable panels now.
    eye = (260.0, -300.0, 170.0)
    target = (0.0, 0.0, 0.0)
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
        float focusDistance = 430
        float2 clippingRange = (1, 5000)
        matrix4d xformOp:transform = (
                {rows_text}
        )
        uniform token[] xformOpOrder = ["xformOp:transform"]
    }}
}}"""


def build_usda() -> str:
    parts = [
        '#usda 1.0',
        '(',
        '    defaultPrim = "World"',
        '    upAxis = "Z"',
        '    metersPerUnit = 0.01',
        '    doc = "Twin satellite — Tripo compute-sat body (satellite_compute.usdz) with the missing solar panel mirrored in and the bus shell repainted gold. Generated by tools/gen_twin_satellite.py."',
        ')',
        '',
        'def Xform "World"',
        '{',
        indent(looks_scope(), '    '),
        '',
        '    def Xform "Satellite"',
        '    {',
        bus_prim(),
        '    }',
        '',
        indent(cameras_scope(), '    '),
        '}',
        '',
    ]
    return "\n".join(parts)


def main() -> None:
    out = build_usda()
    OUT.write_text(out, encoding="utf-8")
    print(f"[gen] wrote {OUT} ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
