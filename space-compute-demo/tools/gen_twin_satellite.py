"""Generate usd/twin_satellite.usda — the Twin page's single-satellite body.

REBUILT 2026-06 around the SpaceDcBackbone.usdz spine. The previous body
(satellite_body.usdz bus + two solar.usdz wings + gold MLI override +
solar_material/solar_size variantSets) is gone — `delete all structures`.

The new structure is the backbone alone: a vertical spine carrying a thruster
module at each Z end, a central tank/wheel module, and FOUR quadrant racks
(±Y × upper/lower). Each rack is a stack of three open shelf-frames — twelve
server slots in total. This generator references the backbone and drops a
procedural compute-server blade into every slot so the satellite reads as a
populated orbital data center.

Geometry survey (tools/inspect_backbone.py + tools/analyze_slots.py):
    stage: Z-up, metersPerUnit 1.0, defaultPrim /root, bbox 0.18 × 0.45 × 1.0 m
    spine  : tripo_part_1   (Z beam)
    caps   : tripo_part_2 (+Z), tripo_part_8 (-Z)   thruster modules
    centre : tripo_part_6/7  (tank / reaction-wheel pack)
    racks  : tripo_part_0 (+Y up)  tripo_part_4 (-Y up)
             tripo_part_5 (+Y low) tripo_part_3 (-Y low)
    each rack: 3 frames; rails (area peaks) pair into 3 slot openings.

Host stage is metersPerUnit 0.01 (cm) — USD does not auto-convert units on a
reference, so the meters→cm framing scale lives on /World/Satellite. Servers
are authored in the backbone's native metre frame as children of that same
scaled Xform, so their coordinates line up 1:1 with the slot survey.

Preserved contracts (consumed by satellite.usda + space.demo.scene):
    /World                         defaultPrim, Z-up, cm
    /World/Satellite               body root (camera framing target)
    /World/Cameras/Closeup         bound camera (satellite.usda customLayerData)

Run:
    python tools/gen_twin_satellite.py
"""
from __future__ import annotations

import math
from pathlib import Path
from textwrap import indent

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "usd" / "twin_satellite.usda"

# Backbone: Z-up, metres, 1.0 m tall. ×180 frames it at 1.8 m in the cm host
# stage (matches the old body's ~1.7 m so the Closeup camera distances carry
# over). Authored on /World/Satellite so the servers inherit the same scale.
BACKBONE_REF   = "./assets/SpaceDcBackbone.usdz"
BACKBONE_SCALE = 180.0

# --- Server slots -----------------------------------------------------------
# Slot Z-centres are the mid-points of each frame's rail pair (the six area
# peaks per rack from analyze_slots.py group into three openings). Y is the
# cantilever mid of the rack arm; X is centred on the spine. All in backbone
# metres.
SLOT_Z_UPPER = (0.1165, 0.2075, 0.2980)
SLOT_Z_LOWER = (-0.1622, -0.2534, -0.3446)
SLOT_Y_ABS   = 0.135          # |Y| centre of the blade in the cantilever
# (name, y_sign, z-centres) — y_sign also flips the blade's front bezel side.
RACKS = [
    ("UpY", +1.0, SLOT_Z_UPPER),
    ("UnY", -1.0, SLOT_Z_UPPER),
    ("LpY", +1.0, SLOT_Z_LOWER),
    ("LnY", -1.0, SLOT_Z_LOWER),
]

# Blade box (backbone metres): X width, Y depth (cantilever), Z height. Sized
# to seat inside the ~0.045 m frame opening with margin and span most of the
# arm without colliding with the spine-side / tip-side posts.
BLADE_W = 0.130
BLADE_D = 0.155
BLADE_H = 0.034

# Server materials (UsdPreviewSurface).
SERVER_MATERIALS = {
    # Dark gunmetal chassis.
    "ServerChassis":  {"diffuse": (0.060, 0.065, 0.078), "metallic": 0.55,
                       "roughness": 0.50, "emissive": (0.010, 0.011, 0.014)},
    # Cyan status bezel on the blade's outward face — the "compute is live"
    # signal; emissive so it reads in eclipse.
    "ServerBezel":    {"diffuse": (0.020, 0.050, 0.060), "metallic": 0.0,
                       "roughness": 0.30, "emissive": (0.00, 0.85, 1.05)},
    # Brushed-aluminium heat-spreader strip on top of each blade.
    "ServerHeatsink": {"diffuse": (0.560, 0.580, 0.610), "metallic": 0.80,
                       "roughness": 0.42, "emissive": (0.0, 0.0, 0.0)},
}

# --- Solar array ------------------------------------------------------------
# The backbone's mid-section deliberately carries no server racks: each ±Y face
# of the central module (tripo_part_6/7) instead presents a deployment bracket
# with a rotary hinge. A thin support boom reaches out from each bracket and
# carries oversized solar wings built from the real solar.usdz panel — far
# larger than the backbone itself — one wing per side.
#
# All lengths in backbone metres (the solar group is a child of the ×180
# /World/Satellite Xform, so 1 unit here = BACKBONE_SCALE cm = 1.8 m on stage).
SOLAR_REF    = "./assets/solar.usdz"
# Mesh prim inside solar.usdz (surveyed via pxr) — pinned so a re-bake fails
# loud. Each panel rebinds this mesh to a glossy metallic look (see below).
SOLAR_NODE   = "tripo_node_f428be0e_6763_4c3c_adc0_48f9e995f063"
SOLAR_MESH   = "tripo_mesh_f428be0e_6763_4c3c_adc0_48f9e995f063"
# solar.usdz native (m): long 0.978 (X), wide 0.666 (Y), thick 0.068 (Z); the
# cell face is along ±Z. rotateY=90 stands the panel up: long→Z (wing height),
# wide→Y (deploy), and the cell normal Z→+X (the sun / camera side).
SOLAR_NATIVE = (0.978, 0.666, 0.068)
PANEL_RY     = 90.0
# Per-panel scale (height, deploy, thickness) — non-uniform so the panel reads
# oversized and thin. Height 0.978×1.45≈1.42 (≈2.6 m on stage, taller than the
# 1.8 m body); deploy 0.666×1.05≈0.70; thickness 0.068×0.45≈0.031.
PANEL_SCALE  = (1.45, 1.05, 0.45)
N_PANELS     = 2          # "几块" — two panels chained into one wing per side
PANEL_GAP    = 0.05       # gap between chained panels

SOLAR_Z      = -0.024     # central-module hub height (boom + panel mid-Z)
SOLAR_X      = 0.030      # boom + panel plane, just off the +X spine face
BOOM_Y0      = 0.07       # boom root (seats inside the bracket)
BOOM_Y1      = 0.42       # boom tip / first-panel inner edge (clear of racks @0.227)
BOOM_THICK   = 0.012      # thin square support-rod cross-section (was 0.030)

SOLAR_MATERIALS = {
    # Brushed-aluminium support boom.
    "SolarFrame": {"diffuse": (0.600, 0.630, 0.700), "metallic": 0.85,
                   "roughness": 0.35, "emissive": (0.0, 0.0, 0.0)},
    # Glossy metallic solar cell — deep blue with a high metallic + low
    # roughness so the panels catch a bright specular sheen (金属光泽). Rebinds
    # solar.usdz's own texture-driven mesh. Faint emissive keeps a little
    # colour in eclipse.
    "SolarCellMetallic": {"diffuse": (0.040, 0.105, 0.420), "metallic": 0.90,
                          "roughness": 0.14, "emissive": (0.010, 0.030, 0.110)},
}

# Closeup camera — pulled far back along +X so the whole solar sail reads
# face-on, with a slight -Y / +Z 3/4 tilt. Wide enough to hold the full
# wingspan (~6 m) plus the body.
CAM_EYE   = (1150.0, -160.0, 280.0)
CAM_FOCAL = 30.0


# ---------------------------------------------------------------------------
def _c3(t: tuple[float, float, float]) -> str:
    return f"({t[0]:.3f}, {t[1]:.3f}, {t[2]:.3f})"


def material_block(name: str, p: dict) -> str:
    em = p.get("emissive", (0.0, 0.0, 0.0))
    return f"""
    def Material "{name}"
    {{
        token outputs:surface.connect = </World/Looks/{name}/Shader.outputs:surface>
        def Shader "Shader"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor = {_c3(p['diffuse'])}
            color3f inputs:emissiveColor = {_c3(em)}
            float inputs:metallic = {p['metallic']:.3f}
            float inputs:roughness = {p['roughness']:.3f}
            int inputs:useSpecularWorkflow = 0
            token outputs:surface
        }}
    }}"""


def looks_scope() -> str:
    blocks = [material_block(k, v) for k, v in SERVER_MATERIALS.items()]
    blocks += [material_block(k, v) for k, v in SOLAR_MATERIALS.items()]
    return f"""def Scope "Looks"
{{{''.join(blocks)}
}}"""


# 6 outward-wound quad faces for an axis-aligned box.
_BOX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
              (2, 3, 7, 6), (1, 2, 6, 5), (0, 4, 7, 3))


def box_mesh(name: str, cx: float, cy: float, cz: float,
             sx: float, sy: float, sz: float, material: str) -> str:
    """An axis-aligned box authored as an explicit Mesh so every renderer
    (Kit + tools/render_usd.py) draws it. doubleSided guards against any
    winding/backface surprises in the host viewport."""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    pts = [
        (cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz),
    ]
    pstr = ", ".join(f"({p[0]:.5f}, {p[1]:.5f}, {p[2]:.5f})" for p in pts)
    idx  = ", ".join(str(i) for f in _BOX_FACES for i in f)
    return f"""def Mesh "{name}" (
    prepend apiSchemas = ["MaterialBindingAPI"]
)
{{
    uniform bool doubleSided = 1
    float3[] extent = [({cx-hx:.5f}, {cy-hy:.5f}, {cz-hz:.5f}), ({cx+hx:.5f}, {cy+hy:.5f}, {cz+hz:.5f})]
    int[] faceVertexCounts = [4, 4, 4, 4, 4, 4]
    int[] faceVertexIndices = [{idx}]
    point3f[] points = [{pstr}]
    uniform token subdivisionScheme = "none"
    rel material:binding = </World/Looks/{material}>
}}"""


def server_blade(name: str, cx: float, cy: float, cz: float, y_sign: float) -> str:
    """One compute-server blade: dark chassis + outward cyan status bezel +
    aluminium heat-spreader strip on top. Front bezel sits on the y_sign face
    so it points out of the rack opening toward deep space."""
    bezel_y = cy + y_sign * (BLADE_D / 2)
    parts = [
        box_mesh("Chassis", cx, cy, cz, BLADE_W, BLADE_D, BLADE_H, "ServerChassis"),
        box_mesh("Bezel", cx, bezel_y, cz, BLADE_W * 0.90, 0.010, BLADE_H * 0.78,
                 "ServerBezel"),
        box_mesh("Heatsink", cx, cy, cz + BLADE_H / 2, BLADE_W * 0.70,
                 BLADE_D * 0.86, 0.006, "ServerHeatsink"),
    ]
    body = "\n".join(parts)
    return f'def Xform "{name}"\n{{\n{indent(body, "    ")}\n}}'


def servers_group() -> str:
    blades = []
    for rack_name, y_sign, zs in RACKS:
        cy = y_sign * SLOT_Y_ABS
        for i, cz in enumerate(zs):
            blades.append(server_blade(f"Server_{rack_name}_{i}", 0.0, cy, cz, y_sign))
    body = "\n".join(blades)
    return f'def Xform "Servers"\n{{\n{indent(body, "    ")}\n}}'


def solar_panel(name: str, cx: float, cy: float, cz: float) -> str:
    """One solar.usdz panel referenced + stood upright (rotateY=90) and scaled.
    Op order applies scale, then rotateY, then translate (USD reads the list
    last-first), so the scale is in the asset's native axes. A local `over`
    rebinds the asset's mesh to the glossy SolarCellMetallic look — the local
    opinion beats the referenced binding."""
    sx, sy, sz = PANEL_SCALE
    return (
        f'def Xform "{name}" (\n'
        f'    prepend references = @{SOLAR_REF}@\n'
        f')\n'
        f'{{\n'
        f'    double3 xformOp:translate = ({cx:.4f}, {cy:.4f}, {cz:.4f})\n'
        f'    float xformOp:rotateY = {PANEL_RY}\n'
        f'    double3 xformOp:scale = ({sx:.4f}, {sy:.4f}, {sz:.4f})\n'
        f'    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY", "xformOp:scale"]\n'
        f'\n'
        f'    over "{SOLAR_NODE}"\n'
        f'    {{\n'
        f'        over "{SOLAR_MESH}"\n'
        f'        {{\n'
        f'            rel material:binding = </World/Looks/SolarCellMetallic>\n'
        f'        }}\n'
        f'    }}\n'
        f'}}'
    )


def solar_wing(side: float) -> str:
    """One deployed solar wing: a thin support boom from the central bracket
    out along `side`·Y, carrying N_PANELS chained solar.usdz panels. The panels
    stand upright with the cell face toward +X (sun side) on both wings."""
    s = side
    by0, by1 = BOOM_Y0 * s, BOOM_Y1 * s
    deploy = SOLAR_NATIVE[1] * PANEL_SCALE[1]          # per-panel span along Y
    parts = [box_mesh("Boom", SOLAR_X, (by0 + by1) / 2.0, SOLAR_Z,
                      BOOM_THICK, abs(by1 - by0), BOOM_THICK, "SolarFrame")]
    for i in range(N_PANELS):
        cy = (BOOM_Y1 + deploy / 2.0 + i * (deploy + PANEL_GAP)) * s
        parts.append(solar_panel(f"Panel_{i}", SOLAR_X, cy, SOLAR_Z))
    name = "WingPosY" if side > 0 else "WingNegY"
    body = "\n".join(parts)
    return f'def Xform "{name}"\n{{\n{indent(body, "    ")}\n}}'


def solar_group() -> str:
    body = solar_wing(1.0) + "\n" + solar_wing(-1.0)
    return f'def Xform "SolarArray"\n{{\n{indent(body, "    ")}\n}}'


def satellite_prim() -> str:
    backbone = (
        f'def Xform "Backbone" (\n'
        f'    prepend references = @{BACKBONE_REF}@\n'
        f')\n'
        f'{{\n'
        f'}}'
    )
    inner = "\n\n".join([backbone, servers_group(), solar_group()])
    return f"""def Xform "Satellite"
{{
    double3 xformOp:scale = ({BACKBONE_SCALE}, {BACKBONE_SCALE}, {BACKBONE_SCALE})
    uniform token[] xformOpOrder = ["xformOp:scale"]

{indent(inner, "    ")}
}}"""


def cameras_scope() -> str:
    """Closeup camera — front-on from far +X (with a slight -Y/+Z tilt) so the
    deployed solar sail and the backbone both fit. The wings dominate the frame
    (~5 m span vs the 1.8 m body), exactly the over-sized look intended."""
    eye = CAM_EYE
    target = (0.0, 0.0, 0.0)
    fx, fy, fz = (target[i] - eye[i] for i in range(3))
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
    focus = math.sqrt(sum((eye[i]-target[i])**2 for i in range(3)))
    return f"""def Xform "Cameras"
{{
    def Camera "Closeup"
    {{
        float focalLength = {CAM_FOCAL:.1f}
        float focusDistance = {focus:.0f}
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
        '    doc = "Twin satellite — SpaceDcBackbone.usdz spine: a compute-server blade in each of the 12 rack slots, plus two oversized solar wings on booms off the central deployment brackets. Generated by tools/gen_twin_satellite.py."',
        ')',
        '',
        'def Xform "World"',
        '{',
        indent(looks_scope(), '    '),
        '',
        indent(satellite_prim(), '    '),
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
