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

# Tripo compute-sat model: metersPerUnit=1.0, Z-up, default prim /root.
BUS_REF = "./assets/satellite_compute.usdz"
# Host stage is metersPerUnit=0.01 (cm) — USD references don't auto-rescale
# across the unit boundary. Source longest dim is ~0.742 m; 0.742 × 230 ≈
# 170 cm physical, matching the previous Satellite_v022 framing so the
# Closeup camera (focusDistance=430 cm) still works.
BUS_SCALE = 230.0

# Prim paths inside the asset (surveyed via pxr — pinned here so a swap to a
# different Tripo bake fails loud instead of silently misbinding).
ASSET_BUS_MESH    = "ParentNode/tripo_part_74_0/Mesh_10"   # ~70% of mesh volume
ASSET_PANEL_XFORM = "ParentNode/tripo_part_new_1"          # the deployed panel
ASSET_PANEL_MESH  = "Mesh_8"                                # mesh under the panel xform

# Mirror geometry: panel centroid (source meters) sits +0.254 m along +Y of
# the bus centroid (0, 0.129, 0.086). Mirroring about the bus centroid
# y = 0.129 means scale(1,-1,1) followed by translate(0, 2*0.129, 0).
MIRROR_TRANSLATE_Y = 0.258

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


def bus_shell_gold_override() -> str:
    """Nested `over` that rebinds the asset's bus shell mesh to BusGold."""
    return _nested_over_for_path(
        ASSET_BUS_MESH,
        "rel material:binding = </World/Looks/BusGold>",
    )


def mirrored_panel_prim() -> str:
    """Child Xform that sub-prim references just the panel sub-tree and
    mirrors it across the bus centerline."""
    return f"""def Xform "MirroredPanel" (
    prepend references = @{BUS_REF}@</root/{ASSET_PANEL_XFORM}>
)
{{
    # USD composes xformOpOrder as M = M_op0 * M_op1 * ... — i.e. the op
    # LAST in the list is applied first to the local point, then the next
    # one up, etc. We want scale(-1) FIRST then translate(+0.258), so the
    # list is ["translate", "scale"]: scale (last) acts on the source y,
    # then translate (first) shifts the mirrored result up by 2 * 0.129 m
    # to land symmetric about the bus centroid.
    double3 xformOp:translate = (0.0, {MIRROR_TRANSLATE_Y}, 0.0)
    double3 xformOp:scale = (1.0, -1.0, 1.0)
    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]

    # Negative-scale flips winding; mark double-sided so lighting is correct
    # on both faces.
    over "{ASSET_PANEL_MESH}"
    {{
        uniform bool doubleSided = 1
    }}
}}"""


def solar_variants() -> str:
    """variantSet body — each variant rebinds the original panel AND the
    mirrored panel to the same Solar_* material so the Configurator dropdown
    drives both panels together. (It also gives the mirrored panel a
    defined material, since its sub-prim reference doesn't bring the
    asset's /root/_materials scope.)"""
    variant_bodies = []
    for mat_id in SOLAR_MATERIALS.keys():
        orig = _nested_over_for_path(
            f"{ASSET_PANEL_XFORM}/{ASSET_PANEL_MESH}",
            f"rel material:binding = </World/Looks/Solar_{mat_id}>",
        )
        mirror = _nested_over_for_path(
            f"MirroredPanel/{ASSET_PANEL_MESH}",
            f"rel material:binding = </World/Looks/Solar_{mat_id}>",
        )
        body = f"{orig}\n{mirror}"
        variant_bodies.append(f'"{mat_id}" {{\n{indent(body, "    ")}\n}}')
    return "\n".join(variant_bodies)


def bus_prim() -> str:
    """The bus: references the new compute-sat asset, scales m→cm with extra
    framing, rebinds the shell to gold, mirrors the missing solar panel, and
    keeps the solar_material variantSet wired to BOTH panels."""
    over_gold = indent(bus_shell_gold_override(), "        ")
    mirror = indent(mirrored_panel_prim(), "        ")
    variants = indent(solar_variants(), "            ")
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

{over_gold}

{mirror}

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
