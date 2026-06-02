"""Generate usd/twin_satellite.usda — the Twin page's satellite body.

Pared back to JUST the existing Satellite_v022.usdc body (gold MLI bus,
copper boom, built-in solar panels + dish). The procedural deployable
solar wings / radiator plates / DGX rack from the earlier passes are
removed — a proper articulated model will be re-introduced as USD later.

Kept:
    /World
        /Looks/Solar_{Si,GaAs,Perovskite}   — recolour the body's panels
        /Satellite/Bus  ← references @./assets/Satellite_v022.usdc@
            variantSet "solar_material" overrides the body's Mesh/Panel
            subset material:binding so the built-in panels respond to the
            Configurator's solar-material choice.
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

BUS_REF = "./assets/satellite_v023.usdz"
# satellite_v023.usdz is authored at metersPerUnit=1.0 (meters); the host
# Twin stage is metersPerUnit=0.01 (cm), and USD references don't auto-rescale
# across the unit boundary. Multiply by 100 to land in cm, then by an extra
# 1.7 so the longest dimension (~1 m in the asset) frames at ~170 cm — close
# to the previous Satellite_v022 body so the Closeup camera still works.
BUS_SCALE = 170.0

# Panel materials — recolour the body's built-in solar Panel subset. Tuned
# so the swap reads under the satellite-stage warm Sun; emissive keeps the
# identity from washing out against the warm key light.
SOLAR_MATERIALS = {
    "Si":         {"diffuse": (0.05, 0.15, 0.85), "metallic": 0.30, "roughness": 0.35,
                   "emissive": (0.10, 0.20, 0.85)},
    "GaAs":       {"diffuse": (0.45, 0.10, 0.55), "metallic": 0.75, "roughness": 0.20,
                   "emissive": (0.60, 0.10, 0.80)},
    "Perovskite": {"diffuse": (1.00, 0.35, 0.75), "metallic": 0.50, "roughness": 0.15,
                   "emissive": (1.40, 0.20, 0.90)},
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
    return f"""def Scope "Looks"
{{{''.join(blocks)}
}}"""


def bus_prim() -> str:
    """Satellite body. The `solar_material` variantSet stays authored so the
    backend's set_config({solar_material: ...}) path keeps working end-to-end
    (no UI/state surprises); each variant's `over "Mesh"/over "Panel"` was
    designed for the Satellite_v022 subset hierarchy and is a no-op on this
    asset (which has no `Panel` mesh subset). Visual recolour of solar panels
    on this body will need re-targeting once a panel subset is identified —
    flagged but left wired so the rest of the pipeline doesn't regress."""
    mat_variants = "\n".join(
        f"""        "{mat_id}" {{
            over "Mesh"
            {{
                over "Panel"
                {{
                    rel material:binding = </World/Looks/Solar_{mat_id}>
                }}
            }}
        }}"""
        for mat_id in SOLAR_MATERIALS.keys()
    )
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
        variantSet "solar_material" = {{
{mat_variants}
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
        '    doc = "Twin satellite — bare Satellite_v022 body with a solar_material variant on its built-in panels. Procedural wings/radiators removed; a richer articulated model will be referenced in later. Generated by tools/gen_twin_satellite.py."',
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
