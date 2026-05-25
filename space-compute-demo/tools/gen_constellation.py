"""Generate usd/constellation.usda — fancy Omniverse-side equivalent of the
Three.js fallback Earth: 24 multi-colored orbit rings + 24 emissive satellites
+ a Fresnel-style atmosphere shell.

Matches the web fallback's geometry:
  ring i:  inclination = 50 + (i % 4) * 8 deg   (50, 58, 66, 74)
           RAAN        = (i / 24) * 360 deg     (15 deg spacing)
           hue         = i % 6                  (magenta/cyan/amber/emerald/violet/rose)
  sat i sits on ring i at phase = (i/24)*2*pi.

Output is sublayered into usd/overview.usda alongside earth_mesh.usda.
Units match the rest of the overview stage: metersPerUnit=100000, 1 unit=100km.

Run:
    backend/.venv/Scripts/python.exe tools/gen_constellation.py
"""
from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "usd" / "constellation.usda"

EARTH_R_UNITS    = 63.71     # 6371 km
ORBIT_R_UNITS    = 69.21     # 550 km altitude
ATMO_R_UNITS     = 65.20     # ~150 km above surface — fits "scattering" thickness
RING_COUNT       = 24
RING_VERTS       = 96         # smoothness of the orbit polyline
SAT_RADIUS_UNITS = 0.85       # 85 km diameter ball; small but visible at overview FOV
RING_WIDTH_UNITS = 0.30       # thickness for BasisCurves stroke

# 6-hue palette matching web/src/design/tokens.ts colors.ribbons.
# Emissive value = base * EMIT_GAIN so Bloom (in Kit's RTX post stack) lights up.
EMIT_GAIN = 2.8
PALETTE_HEX = [
    "E879F9",   # magenta
    "22D3EE",   # cyan
    "FBBF24",   # amber
    "34D399",   # emerald
    "A78BFA",   # violet
    "FB7185",   # rose
]


def hex_to_rgb01(hexstr: str) -> tuple[float, float, float]:
    return (
        int(hexstr[0:2], 16) / 255.0,
        int(hexstr[2:4], 16) / 255.0,
        int(hexstr[4:6], 16) / 255.0,
    )


def ring_orient(i: int) -> tuple[float, float]:
    """Return (inclination_rad, raan_rad) for ring `i`."""
    inc = math.radians(50.0 + (i % 4) * 8.0)
    raan = math.radians((i / RING_COUNT) * 360.0)
    return inc, raan


def transform_point(
    x: float, y: float, z: float, inc: float, raan: float,
) -> tuple[float, float, float]:
    """Apply ring's inclination (about X) then RAAN (about Z)."""
    # Rotate about X by inclination
    cy, sy = math.cos(inc), math.sin(inc)
    x1, y1, z1 = x, y * cy - z * sy, y * sy + z * cy
    # Rotate about Z by RAAN
    cz, sz = math.cos(raan), math.sin(raan)
    x2 = x1 * cz - y1 * sz
    y2 = x1 * sz + y1 * cz
    z2 = z1
    return x2, y2, z2


def orbit_points(i: int) -> list[tuple[float, float, float]]:
    inc, raan = ring_orient(i)
    pts: list[tuple[float, float, float]] = []
    for k in range(RING_VERTS):
        theta = (k / (RING_VERTS - 1)) * 2.0 * math.pi
        x = math.cos(theta) * ORBIT_R_UNITS
        y = math.sin(theta) * ORBIT_R_UNITS
        z = 0.0
        pts.append(transform_point(x, y, z, inc, raan))
    return pts


def sat_position(i: int) -> tuple[float, float, float]:
    """Phase-locked sat position on its ring."""
    inc, raan = ring_orient(i)
    phase = (i / RING_COUNT) * 2.0 * math.pi
    x = math.cos(phase) * ORBIT_R_UNITS
    y = math.sin(phase) * ORBIT_R_UNITS
    return transform_point(x, y, 0.0, inc, raan)


def emit_orbit_curve(i: int, color: tuple[float, float, float]) -> str:
    pts = orbit_points(i)
    pts_str = ", ".join(f"({p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f})" for p in pts)
    er, eg, eb = (color[0] * EMIT_GAIN, color[1] * EMIT_GAIN, color[2] * EMIT_GAIN)
    return f"""
        def BasisCurves "Ring_{i:02d}" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            int[] curveVertexCounts = [{RING_VERTS}]
            point3f[] points = [{pts_str}]
            color3f[] primvars:displayColor = [({er:.4f}, {eg:.4f}, {eb:.4f})] (
                interpolation = "constant"
            )
            custom uniform bool primvars:doNotCastShadows = 1
            float[] primvars:widths = [{RING_WIDTH_UNITS}] (
                interpolation = "constant"
            )
            uniform token type = "linear"
            float[] widths = [{RING_WIDTH_UNITS}]
            rel material:binding = </World/Constellation/Looks/RingMat_{i % len(PALETTE_HEX)}>
        }}"""


def emit_sat(i: int, color: tuple[float, float, float]) -> str:
    x, y, z = sat_position(i)
    return f"""
        def Sphere "Sat_{i:02d}" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double radius = {SAT_RADIUS_UNITS}
            double3 xformOp:translate = ({x:.4f}, {y:.4f}, {z:.4f})
            uniform token[] xformOpOrder = ["xformOp:translate"]
            uniform bool primvars:doNotCastShadows = 1
            rel material:binding = </World/Constellation/Looks/SatMat_{i % len(PALETTE_HEX)}>
        }}"""


def emit_material(name: str, color: tuple[float, float, float]) -> str:
    er, eg, eb = color[0] * EMIT_GAIN, color[1] * EMIT_GAIN, color[2] * EMIT_GAIN
    path = f"/World/Constellation/Looks/{name}"
    return f"""
        def Material "{name}"
        {{
            token outputs:surface.connect = <{path}/Shader.outputs:surface>
            def Shader "Shader"
            {{
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = (0.02, 0.02, 0.025)
                color3f inputs:emissiveColor = ({er:.4f}, {eg:.4f}, {eb:.4f})
                float inputs:metallic = 0.0
                float inputs:roughness = 1.0
                int inputs:useSpecularWorkflow = 0
                token outputs:surface
            }}
        }}"""


def emit_atmo_material() -> str:
    return """
        def Material "AtmoMat"
        {
            token outputs:surface.connect = </World/Constellation/Looks/AtmoMat/Shader.outputs:surface>
            def Shader "Shader"
            {
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = (0.0, 0.0, 0.0)
                color3f inputs:emissiveColor = (0.20, 0.65, 1.20)
                float inputs:opacity = 0.06
                float inputs:metallic = 0.0
                float inputs:roughness = 1.0
                int inputs:useSpecularWorkflow = 0
                token outputs:surface
            }
        }"""


def emit_atmo_shell() -> str:
    return f"""
        def Sphere "AtmosphereShell" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double radius = {ATMO_R_UNITS}
            uniform bool primvars:doNotCastShadows = 1
            rel material:binding = </World/Constellation/Looks/AtmoMat>
        }}"""


def main() -> None:
    palette = [hex_to_rgb01(h) for h in PALETTE_HEX]

    # Materials reused across rings + sats of the same hue (6 total + atmo).
    materials = []
    for hue in range(len(PALETTE_HEX)):
        materials.append(emit_material(f"RingMat_{hue}", palette[hue]))
        materials.append(emit_material(f"SatMat_{hue}", palette[hue]))
    materials.append(emit_atmo_material())

    # Curves + sats.
    rings = [emit_orbit_curve(i, palette[i % len(PALETTE_HEX)]) for i in range(RING_COUNT)]
    sats  = [emit_sat(i, palette[i % len(PALETTE_HEX)]) for i in range(RING_COUNT)]

    body = "\n".join(
        [
            "#usda 1.0",
            "(",
            "    metersPerUnit = 100000",
            "    upAxis = \"Z\"",
            "    doc = \"Constellation: 24 colored orbit rings + 24 emissive sats + atmosphere shell. Generated by tools/gen_constellation.py.\"",
            ")",
            "",
            "def Xform \"World\"",
            "{",
            "    def Xform \"Constellation\"",
            "    {",
            "        def Scope \"Looks\"",
            "        {",
            "".join(materials),
            "        }",
            emit_atmo_shell(),
            "".join(rings),
            "",
            "".join(sats),
            "    }",
            "}",
            "",
        ]
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} — {RING_COUNT} rings × {RING_VERTS} verts + {RING_COUNT} sats + 1 atmosphere shell + {2*len(PALETTE_HEX)} mats")


if __name__ == "__main__":
    main()
