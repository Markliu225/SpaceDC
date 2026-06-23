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
SOLAR_REF    = "./assets/solar_panel_3d_model.usdz"
# Panel native (m): long 0.981 (X), wide 0.777 (Y), thick 0.054 (Z); the cell
# face is along ±Z. rotateY=90 stands the panel up: long→Z (wing height),
# wide→Y (deploy), and the cell normal Z→+X (the sun / camera side). The panels
# keep solar_panel_3d_model.usdz's own texture COLOUR — we only sharpen the
# finish in place (roughness 0.9→low, metallic up) so they reflect strongly.
SOLAR_NATIVE = (0.981, 0.777, 0.054)
SOLAR_MAT    = "tripo_mat_a4f32a50_bfaf_4ef6_a7aa_25f0c33672fc"  # asset's material
SOLAR_GLOSS_ROUGH = 0.08    # was 0.9 (very matte) → glossy
SOLAR_GLOSS_METAL = 0.6     # was 0.0 → catches sun/earth reflections
PANEL_RY     = 90.0
# Per-panel scale (height, deploy, thickness) — non-uniform so the panel reads
# oversized and thin. Height 0.978×1.45≈1.42 (≈2.6 m on stage, taller than the
# 1.8 m body); deploy 0.666×1.05≈0.70; thickness 0.068×0.45≈0.031.
PANEL_SCALE  = (1.45, 1.05, 0.45)
N_PANELS     = 2          # two panel clusters chained into one wing per side
PANEL_GAP    = 0.0        # clusters abut — no gap between panels
# Each (formerly single) panel is a 2×2 grid of four smaller panels filling the
# same footprint. SUB_FRAC is each tile's per-axis scale vs the full panel;
# 0.5 makes the four tiles meet exactly edge-to-edge (no seam/gap).
SUB_FRAC     = 0.5

SOLAR_Z      = -0.024     # central-module hub height (boom + panel mid-Z)
SOLAR_X      = 0.030      # boom + panel plane, just off the +X spine face
BOOM_Y0      = 0.07       # boom root (seats inside the bracket)
BOOM_Y1      = 0.42       # boom tip / first-panel inner edge (clear of racks @0.227)
BOOM_THICK   = 0.012      # thin square support-rod cross-section (was 0.030)

# --- Radiator panels --------------------------------------------------------
# A boom off each ±Z end of the spine carries one long radiator. Its large-face
# normal is perpendicular to the solar panels' (solar faces +X; the radiator
# faces ±Y), and its SHORT edge meets the boom so the panel runs out along Z.
# rotateZ=90 then rotateX=90 maps the asset's native long-X → world Z (the long
# axis, up the boom), native wide-Y → world X (short edge), and the native +Z
# normal → world -Y. A single module (no tiling) scaled to a ~1:3 face with the
# thickness held (native-Z ×1).
RAD_REF        = "./assets/radiation_panel_3d_model.usdz"
RAD_NATIVE     = (0.9824, 0.6377, 0.0528)   # long X, wide Y, thick Z (normal Z)
# The radiator asset drives roughness/metallic from textures (can't be tuned in
# place), so each radiator mesh is rebound to a glossy specular RadiatorGlossy.
RAD_NODE       = "tripo_node_592ee2f8_9809_4148_9d8c_fd736a77b899"
RAD_MESH       = "tripo_mesh_592ee2f8_9809_4148_9d8c_fd736a77b899"
RAD_LONG       = 1.55     # world-Z length (backbone-m) — the long axis up the boom
RAD_RATIO      = 2.5      # short : long = 2 : 5
RAD_X          = 0.026    # centred on the spine axis
SPINE_END_Z    = 0.50     # spine ±Z ends (backbone bbox is Z ∈ [-0.5, 0.5])
RAD_BOOM_LEN   = 0.16     # boom reach along Z beyond the spine end
RAD_BOOM_THICK = 0.014    # thin square support rod

SOLAR_MATERIALS = {
    # Brushed-aluminium support boom (panels keep the asset's own materials).
    "SolarFrame": {"diffuse": (0.600, 0.630, 0.700), "metallic": 0.85,
                   "roughness": 0.35, "emissive": (0.0, 0.0, 0.0)},
    # Glossy specular radiator finish (rebinds the texture-driven asset material
    # so the radiators reflect strongly) — bright OSR/quartz-mirror silver.
    "RadiatorGlossy": {"diffuse": (0.720, 0.745, 0.790), "metallic": 0.90,
                       "roughness": 0.06, "emissive": (0.0, 0.0, 0.0)},
}

# Closeup camera — a true 3/4 (from +X / -Y / above) so the solar wings (face
# +X) AND the perpendicular radiators (face ±Y, top/bottom) are both readable.
# Pulled far back to hold the full ~7.5 m span × ~5.5 m height.
CAM_EYE   = (1250.0, -1500.0, 1050.0)
CAM_FOCAL = 22.0

# --- Celestial context (Earth + Sun) ---------------------------------------
# In the twin view the Earth + Sun appear at realistic ANGULAR scale and
# position (literal 1:1 distances would wreck the depth buffer): the Earth fills
# ~64° below (the LEO horizon) and the Sun is a ~0.53° disk in the sun
# direction. Authored in absolute cm as siblings of the ×180 Satellite, so they
# sit at their true directions and sweep correctly as the camera orbits.
# Distances are compressed (literal 700 km would wreck the depth buffer) but the
# ANGULAR sizes are kept real: asin(R/D)=64° gives the true LEO Earth horizon,
# and the Sun spans the true ~0.53°. Earth surface sits ~2.5 m below the body.
EARTH_RADIUS_CM = 22_000.0                     # ~49° angular radius from the cam:
EARTH_CENTER    = (0.0, 0.0, -28_000.0)        # a big curved planet across the lower frame
EARTH_TEX       = "./textures/earth_day.jpg"
EARTH_NIGHT_TEX = "./textures/earth_night.jpg"
EARTH_NIGHT_EMIT = (0.95, 0.78, 0.45)          # warm city-light glow on the dark side
CLOUD_TEX       = "./textures/earth_clouds.jpg"
CLOUD_SCALE     = 1.004                         # cloud shell just above the surface
ATMOS_SCALE     = 1.024                         # thin atmosphere shell
ATMOS_COLOR     = (0.35, 0.55, 1.00)           # sky-blue limb glow
ATMOS_OPACITY   = 0.16
SUN_TEX         = "./textures/sun_surface.png"
SUN_EMIT        = (7.0, 5.2, 2.2)              # HDR multiplier on the sun texture → glows
SUN_DIST_CM     = 50_000.0
SUN_RADIUS_CM   = 231.0                        # 50000·tan(0.265°) → ~0.53° disk
SUN_DIR         = (0.643, 0.0, 0.766)          # default Key sun source (+X / +Z)


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


def textured_material(name: str, tex: str, metallic: float, roughness: float,
                      emissive: tuple[float, float, float]) -> str:
    """A diffuse-textured UsdPreviewSurface (UsdUVTexture ← st reader). Used for
    the photovoltaic panels and the equirectangular Earth."""
    return f"""
    def Material "{name}"
    {{
        token outputs:surface.connect = </World/Looks/{name}/Shader.outputs:surface>
        def Shader "Shader"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = </World/Looks/{name}/Tex.outputs:rgb>
            color3f inputs:emissiveColor = {_c3(emissive)}
            float inputs:metallic = {metallic:.3f}
            float inputs:roughness = {roughness:.3f}
            int inputs:useSpecularWorkflow = 0
            token outputs:surface
        }}
        def Shader "Tex"
        {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @{tex}@
            float2 inputs:st.connect = </World/Looks/{name}/St.outputs:result>
            token inputs:wrapS = "repeat"
            token inputs:wrapT = "repeat"
            float3 outputs:rgb
        }}
        def Shader "St"
        {{
            uniform token info:id = "UsdPrimvarReader_float2"
            token inputs:varname = "st"
            float2 outputs:result
        }}
    }}"""


def sun_material() -> str:
    """The Sun — a granulated solar-surface texture driving BOTH diffuse and
    (HDR-scaled) emissive, so the disk shows surface detail and glows like a
    star (with Kit bloom). UsdUVTexture inputs:scale lifts the 0..1 texture
    into HDR for the emissive path."""
    sc = SUN_EMIT
    return f"""
    def Material "SunMat"
    {{
        token outputs:surface.connect = </World/Looks/SunMat/Shader.outputs:surface>
        def Shader "Shader"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = </World/Looks/SunMat/Tex.outputs:rgb>
            color3f inputs:emissiveColor.connect = </World/Looks/SunMat/Emit.outputs:rgb>
            float inputs:metallic = 0.0
            float inputs:roughness = 1.0
            int inputs:useSpecularWorkflow = 0
            token outputs:surface
        }}
        def Shader "Tex"
        {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @{SUN_TEX}@
            float2 inputs:st.connect = </World/Looks/SunMat/St.outputs:result>
            float3 outputs:rgb
        }}
        def Shader "Emit"
        {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @{SUN_TEX}@
            float2 inputs:st.connect = </World/Looks/SunMat/St.outputs:result>
            float4 inputs:scale = ({sc[0]:.2f}, {sc[1]:.2f}, {sc[2]:.2f}, 1.0)
            float3 outputs:rgb
        }}
        def Shader "St"
        {{
            uniform token info:id = "UsdPrimvarReader_float2"
            token inputs:varname = "st"
            float2 outputs:result
        }}
    }}"""


def earth_material() -> str:
    """Cinematic Earth — daytime map on diffuse, city-lights map on a warm
    HDR-scaled emissive. Where the sun lights the surface the day map dominates;
    on the dark hemisphere only the emissive city lights show, so the day/night
    terminator sweeps across the limb."""
    e = EARTH_NIGHT_EMIT
    return f"""
    def Material "EarthMat"
    {{
        token outputs:surface.connect = </World/Looks/EarthMat/Shader.outputs:surface>
        def Shader "Shader"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = </World/Looks/EarthMat/Day.outputs:rgb>
            color3f inputs:emissiveColor.connect = </World/Looks/EarthMat/Night.outputs:rgb>
            float inputs:metallic = 0.0
            float inputs:roughness = 0.85
            int inputs:useSpecularWorkflow = 0
            token outputs:surface
        }}
        def Shader "Day"
        {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @{EARTH_TEX}@
            float2 inputs:st.connect = </World/Looks/EarthMat/St.outputs:result>
            float3 outputs:rgb
        }}
        def Shader "Night"
        {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @{EARTH_NIGHT_TEX}@
            float2 inputs:st.connect = </World/Looks/EarthMat/St.outputs:result>
            float4 inputs:scale = ({e[0]:.2f}, {e[1]:.2f}, {e[2]:.2f}, 1.0)
            float3 outputs:rgb
        }}
        def Shader "St"
        {{
            uniform token info:id = "UsdPrimvarReader_float2"
            token inputs:varname = "st"
            float2 outputs:result
        }}
    }}"""


def cloud_material() -> str:
    """A drifting white cloud shell — the cloud map drives BOTH the white diffuse
    and the opacity, so it's opaque where clouds are and clear (sees Earth) where
    not. Lit by the sun so the day side reads bright."""
    return f"""
    def Material "CloudMat"
    {{
        token outputs:surface.connect = </World/Looks/CloudMat/Shader.outputs:surface>
        def Shader "Shader"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor = (1.0, 1.0, 1.0)
            float inputs:opacity.connect = </World/Looks/CloudMat/Tex.outputs:r>
            float inputs:metallic = 0.0
            float inputs:roughness = 1.0
            int inputs:useSpecularWorkflow = 0
            token outputs:surface
        }}
        def Shader "Tex"
        {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @{CLOUD_TEX}@
            float2 inputs:st.connect = </World/Looks/CloudMat/St.outputs:result>
            float outputs:r
        }}
        def Shader "St"
        {{
            uniform token info:id = "UsdPrimvarReader_float2"
            token inputs:varname = "st"
            float2 outputs:result
        }}
    }}"""


def atmos_material() -> str:
    """A thin blue atmosphere shell — soft sky-blue emissive at low opacity, so
    the limb glows with that iconic blue arc (the shell is deeper along grazing
    sightlines, so the edge reads brighter)."""
    c = ATMOS_COLOR
    return f"""
    def Material "AtmosMat"
    {{
        token outputs:surface.connect = </World/Looks/AtmosMat/Shader.outputs:surface>
        def Shader "Shader"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor = ({c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f})
            color3f inputs:emissiveColor = ({c[0]*0.6:.3f}, {c[1]*0.6:.3f}, {c[2]*0.6:.3f})
            float inputs:opacity = {ATMOS_OPACITY:.3f}
            float inputs:metallic = 0.0
            float inputs:roughness = 1.0
            int inputs:useSpecularWorkflow = 0
            token outputs:surface
        }}
    }}"""


def looks_scope() -> str:
    blocks = [material_block(k, v) for k, v in SERVER_MATERIALS.items()]
    blocks += [material_block(k, v) for k, v in SOLAR_MATERIALS.items()]
    blocks.append(earth_material())
    blocks.append(cloud_material())
    blocks.append(atmos_material())
    blocks.append(sun_material())
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


def solar_panel(name: str, cx: float, cy: float, cz: float,
                scale: tuple[float, float, float]) -> str:
    """One solar_panel_3d_model.usdz panel referenced + stood upright
    (rotateY=90) and scaled. Op order applies scale, then rotateY, then
    translate (USD reads the list last-first), so the scale is in the asset's
    native axes. Keeps the asset's texture COLOUR but sharpens the finish in
    place (low roughness + metallic) so the cells reflect strongly."""
    sx, sy, sz = scale
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
        f'    over "_materials"\n'
        f'    {{\n'
        f'        over "{SOLAR_MAT}"\n'
        f'        {{\n'
        f'            over "Principled_BSDF"\n'
        f'            {{\n'
        f'                float inputs:roughness = {SOLAR_GLOSS_ROUGH}\n'
        f'                float inputs:metallic = {SOLAR_GLOSS_METAL}\n'
        f'            }}\n'
        f'        }}\n'
        f'    }}\n'
        f'}}'
    )


def solar_cluster(prefix: str, cx: float, cy: float, cz: float) -> list[str]:
    """A 2×2 grid of four small panels filling one full-panel footprint. The
    big panel spanned H (along Z) × D (along Y); the four tiles sit at the
    quadrant centres (±H/4, ±D/4) scaled to SUB_FRAC of the full panel."""
    H = SOLAR_NATIVE[0] * PANEL_SCALE[0]      # full-panel height along Z
    D = SOLAR_NATIVE[1] * PANEL_SCALE[1]      # full-panel deploy along Y
    sub = (PANEL_SCALE[0] * SUB_FRAC, PANEL_SCALE[1] * SUB_FRAC, PANEL_SCALE[2])
    tiles = []
    for r, zs in enumerate((1.0, -1.0)):          # two rows (Z)
        for c, ys in enumerate((-1.0, 1.0)):      # two columns (Y)
            tiles.append(solar_panel(f"{prefix}_{r}{c}",
                                     cx, cy + ys * D / 4.0, cz + zs * H / 4.0, sub))
    return tiles


def solar_wing(side: float) -> str:
    """One deployed solar wing: a thin support boom from the central bracket
    out along `side`·Y, carrying N_PANELS chained panel clusters. Each cluster
    is a 2×2 grid of four small panels, standing upright with the cell face
    toward +X (sun side) on both wings."""
    s = side
    by0, by1 = BOOM_Y0 * s, BOOM_Y1 * s
    deploy = SOLAR_NATIVE[1] * PANEL_SCALE[1]          # per-cluster span along Y
    parts = [box_mesh("Boom", SOLAR_X, (by0 + by1) / 2.0, SOLAR_Z,
                      BOOM_THICK, abs(by1 - by0), BOOM_THICK, "SolarFrame")]
    for i in range(N_PANELS):
        cy = (BOOM_Y1 + deploy / 2.0 + i * (deploy + PANEL_GAP)) * s
        parts.extend(solar_cluster(f"Cluster{i}", SOLAR_X, cy, SOLAR_Z))
    name = "WingPosY" if side > 0 else "WingNegY"
    body = "\n".join(parts)
    return f'def Xform "{name}"\n{{\n{indent(body, "    ")}\n}}'


def solar_group() -> str:
    body = solar_wing(1.0) + "\n" + solar_wing(-1.0)
    return f'def Xform "SolarArray"\n{{\n{indent(body, "    ")}\n}}'


def radiator_panel(name: str, cx: float, cy: float, cz: float) -> str:
    """One radiation_panel_3d_model.usdz panel: rotateZ=90 then rotateX=90 so
    the native long-X runs along world Z (the long axis), native wide-Y along
    world X (short edge), and the +Z normal → world -Y (⊥ solar +X). Scaled to
    a ~1:3 face with thickness held (native-Z ×1). Ops apply scale, rotateZ,
    rotateX, then translate. The mesh is rebound to the glossy RadiatorGlossy
    so it reflects strongly (its asset roughness/metallic are texture-driven and
    can't be tuned in place)."""
    sx = RAD_LONG / RAD_NATIVE[0]                 # native X → world Z (long)
    sy = (RAD_LONG / RAD_RATIO) / RAD_NATIVE[1]   # native Y → world X (short)
    return (
        f'def Xform "{name}" (\n'
        f'    prepend references = @{RAD_REF}@\n'
        f')\n'
        f'{{\n'
        f'    double3 xformOp:translate = ({cx:.4f}, {cy:.4f}, {cz:.4f})\n'
        f'    float xformOp:rotateX = 90\n'
        f'    float xformOp:rotateZ = 90\n'
        f'    double3 xformOp:scale = ({sx:.4f}, {sy:.4f}, 1.0)\n'
        f'    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateX", "xformOp:rotateZ", "xformOp:scale"]\n'
        f'\n'
        f'    over "{RAD_NODE}"\n'
        f'    {{\n'
        f'        over "{RAD_MESH}"\n'
        f'        {{\n'
        f'            rel material:binding = </World/Looks/RadiatorGlossy>\n'
        f'        }}\n'
        f'    }}\n'
        f'}}'
    )


def radiator_group() -> str:
    """A boom off each ±Z spine end with one long radiator beyond it — the
    radiator's short edge meets the boom tip, the long axis runs out along Z."""
    parts = []
    for tag, dirn in (("Top", 1.0), ("Bot", -1.0)):
        end_z = SPINE_END_Z * dirn
        boom_far = end_z + dirn * RAD_BOOM_LEN
        parts.append(box_mesh(f"RadBoom{tag}", RAD_X, 0.0, (end_z + boom_far) / 2.0,
                              RAD_BOOM_THICK, RAD_BOOM_THICK, RAD_BOOM_LEN, "SolarFrame"))
        parts.append(radiator_panel(f"Radiator{tag}", RAD_X, 0.0,
                                    boom_far + dirn * RAD_LONG / 2.0))
    body = "\n".join(parts)
    return f'def Xform "RadiatorArray"\n{{\n{indent(body, "    ")}\n}}'


def uv_sphere(name: str, center: tuple[float, float, float], radius: float,
              material: str, stacks: int = 36, slices: int = 72,
              double_sided: bool = False) -> str:
    """An equirectangular-UV sphere Mesh (lon→u, lat→v) so a lon/lat texture
    maps cleanly and every renderer draws it as real geometry."""
    cx, cy, cz = center
    pts, sts = [], []
    for j in range(stacks + 1):
        phi = -math.pi / 2 + math.pi * j / stacks
        cphi, sphi = math.cos(phi), math.sin(phi)
        for i in range(slices + 1):
            th = 2 * math.pi * i / slices
            pts.append((cx + radius * cphi * math.cos(th),
                        cy + radius * cphi * math.sin(th),
                        cz + radius * sphi))
            sts.append((i / slices, j / stacks))
    row = slices + 1
    idx, counts = [], []
    for j in range(stacks):
        for i in range(slices):
            a = j * row + i
            idx += [a, a + 1, a + row + 1, a + row]
            counts.append(4)
    pstr = ", ".join(f"({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f})" for p in pts)
    ststr = ", ".join(f"({s[0]:.4f}, {s[1]:.4f})" for s in sts)
    return (
        f'def Mesh "{name}" (\n'
        f'    prepend apiSchemas = ["MaterialBindingAPI"]\n'
        f')\n'
        f'{{\n'
        f'    float3[] extent = [({cx-radius:.1f}, {cy-radius:.1f}, {cz-radius:.1f}), '
        f'({cx+radius:.1f}, {cy+radius:.1f}, {cz+radius:.1f})]\n'
        f'    int[] faceVertexCounts = [{", ".join(map(str, counts))}]\n'
        f'    int[] faceVertexIndices = [{", ".join(map(str, idx))}]\n'
        f'    point3f[] points = [{pstr}]\n'
        f'    texCoord2f[] primvars:st = [{ststr}] (interpolation = "vertex")\n'
        f'    uniform token subdivisionScheme = "none"\n'
        f'    uniform bool doubleSided = {1 if double_sided else 0}\n'
        f'    rel material:binding = </World/Looks/{material}>\n'
        f'}}'
    )


def celestial_group() -> str:
    """Earth (day + night-lights), a drifting cloud shell, a blue atmosphere rim,
    and the HDR-emissive Sun. Siblings of the ×180 Satellite, in absolute cm, so
    they hold realistic angular scale + position and sweep as the camera orbits."""
    sun_c = tuple(SUN_DIR[i] * SUN_DIST_CM for i in range(3))
    earth = uv_sphere("Earth", EARTH_CENTER, EARTH_RADIUS_CM, "EarthMat", 48, 96)
    clouds = uv_sphere("Clouds", EARTH_CENTER, EARTH_RADIUS_CM * CLOUD_SCALE,
                       "CloudMat", 48, 96)
    atmos = uv_sphere("Atmosphere", EARTH_CENTER, EARTH_RADIUS_CM * ATMOS_SCALE,
                      "AtmosMat", 40, 80, double_sided=True)
    sun = uv_sphere("Sun", sun_c, SUN_RADIUS_CM, "SunMat", 20, 32)
    body = "\n".join([earth, clouds, atmos, sun])
    return f'def Xform "Celestial"\n{{\n{indent(body, "    ")}\n}}'


def satellite_prim() -> str:
    backbone = (
        f'def Xform "Backbone" (\n'
        f'    prepend references = @{BACKBONE_REF}@\n'
        f')\n'
        f'{{\n'
        f'}}'
    )
    inner = "\n\n".join([backbone, servers_group(), solar_group(), radiator_group()])
    return f"""def Xform "Satellite"
{{
    double3 xformOp:scale = ({BACKBONE_SCALE}, {BACKBONE_SCALE}, {BACKBONE_SCALE})
    uniform token[] xformOpOrder = ["xformOp:scale"]

{indent(inner, "    ")}
}}"""


def _frame_radius_cm() -> float:
    """Largest deployed extent (solar tip along Y, radiator tip along Z) in cm,
    so the camera distance scales with whatever geometry is configured."""
    solar_tip = (BOOM_Y1 + N_PANELS * (SOLAR_NATIVE[1] * PANEL_SCALE[1])) * BACKBONE_SCALE
    rad_tip   = (SPINE_END_Z + RAD_BOOM_LEN + RAD_LONG) * BACKBONE_SCALE
    return max(solar_tip, rad_tip)


def cameras_scope() -> str:
    """Closeup camera — a far 3/4 view (CAM_EYE direction) auto-pulled back to
    the configured frame radius, so any solar count / radiator size stays in
    frame after a regenerate."""
    dn = math.sqrt(sum(c * c for c in CAM_EYE)) or 1.0
    dist = _frame_radius_cm() * 5.5
    eye = tuple(c / dn * dist for c in CAM_EYE)
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
        float2 clippingRange = (1, 90000)
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
        indent(celestial_group(), '    '),
        '',
        indent(cameras_scope(), '    '),
        '}',
        '',
    ]
    return "\n".join(parts)


def _load_params() -> dict:
    """Optional runtime geometry overrides written by the backend
    (usd/twin_params.json): solar_clusters_per_side, radiator_long,
    radiator_ratio. Absent file → built-in defaults."""
    import json
    pf = ROOT / "usd" / "twin_params.json"
    if pf.exists():
        try:
            return json.loads(pf.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 — never let a bad file break gen
            print(f"[gen] WARN ignoring bad twin_params.json: {e}")
    return {}


def main() -> None:
    global N_PANELS, RAD_LONG, RAD_RATIO
    p = _load_params()
    N_PANELS  = max(1, min(8, int(p.get("solar_clusters_per_side", N_PANELS))))
    RAD_LONG  = max(0.3, min(3.0, float(p.get("radiator_long", RAD_LONG))))
    RAD_RATIO = max(1.2, min(6.0, float(p.get("radiator_ratio", RAD_RATIO))))
    if p:
        print(f"[gen] params: solar/side={N_PANELS} rad_long={RAD_LONG} rad_ratio={RAD_RATIO}")
    out = build_usda()
    OUT.write_text(out, encoding="utf-8")
    print(f"[gen] wrote {OUT} ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
