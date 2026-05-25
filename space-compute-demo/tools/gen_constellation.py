"""Generate usd/constellation.usda — minimal orbital-dynamics layer:
24 THIN orbit lines + 24 small bright satellite points.

Design intent (per user feedback): no atmosphere shell, no fat ribbons,
no bloom-washout. Orbit lines are subtle hairlines that just define the
trajectory geometry; satellites are small but bright emissive points
that read as moving dots against the earth.

  ring i:  inclination = 50 + (i % 4) * 8 deg   (50, 58, 66, 74)
           RAAN        = (i / 24) * 360 deg     (15 deg spacing)
           hue         = i % 6                  (magenta/cyan/amber/emerald/violet/rose)
  sat i sits on ring i at phase = (i / 24) * 2*pi.

Run:
    backend/.venv/Scripts/python.exe tools/gen_constellation.py
"""
from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "usd" / "constellation.usda"

EARTH_R_UNITS    = 63.71
ORBIT_R_UNITS    = 69.21
RING_COUNT       = 24
RING_VERTS       = 96

# Thin orbit line + small but bright sat point.
RING_WIDTH_UNITS = 0.04        # 4 km — hairline at overview camera distance
SAT_RADIUS_UNITS = 0.35        # 35 km diameter — small dot that still picks up bloom

# Two-tier emissive. Rings stay well under 1.0 so 24 overlapping crossings
# in the foreground don't accumulate past the bloom threshold (0.85) and
# bleach out to white. Sats are discrete points so they can sit a bit
# higher without flooding nearby pixels.
RING_EMIT_GAIN   = 0.22
SAT_EMIT_GAIN    = 1.8

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
    inc = math.radians(50.0 + (i % 4) * 8.0)
    raan = math.radians((i / RING_COUNT) * 360.0)
    return inc, raan


def transform_point(x, y, z, inc, raan):
    cy, sy = math.cos(inc), math.sin(inc)
    x1, y1, z1 = x, y * cy - z * sy, y * sy + z * cy
    cz, sz = math.cos(raan), math.sin(raan)
    x2 = x1 * cz - y1 * sz
    y2 = x1 * sz + y1 * cz
    z2 = z1
    return x2, y2, z2


def orbit_points(i):
    inc, raan = ring_orient(i)
    pts = []
    for k in range(RING_VERTS):
        theta = (k / (RING_VERTS - 1)) * 2.0 * math.pi
        x = math.cos(theta) * ORBIT_R_UNITS
        y = math.sin(theta) * ORBIT_R_UNITS
        pts.append(transform_point(x, y, 0.0, inc, raan))
    return pts


def sat_position(i):
    inc, raan = ring_orient(i)
    phase = (i / RING_COUNT) * 2.0 * math.pi
    x = math.cos(phase) * ORBIT_R_UNITS
    y = math.sin(phase) * ORBIT_R_UNITS
    return transform_point(x, y, 0.0, inc, raan)


def emit_ring(i, color):
    pts = orbit_points(i)
    pts_str = ", ".join(f"({p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f})" for p in pts)
    er, eg, eb = (color[0] * RING_EMIT_GAIN, color[1] * RING_EMIT_GAIN, color[2] * RING_EMIT_GAIN)
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


def emit_sat(i):
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


def emit_material(name, color, gain):
    er, eg, eb = color[0] * gain, color[1] * gain, color[2] * gain
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


def main():
    palette = [hex_to_rgb01(h) for h in PALETTE_HEX]

    materials = []
    for hue in range(len(PALETTE_HEX)):
        materials.append(emit_material(f"RingMat_{hue}", palette[hue], RING_EMIT_GAIN))
        materials.append(emit_material(f"SatMat_{hue}",  palette[hue], SAT_EMIT_GAIN))

    rings = [emit_ring(i, palette[i % len(PALETTE_HEX)]) for i in range(RING_COUNT)]
    sats  = [emit_sat(i) for i in range(RING_COUNT)]

    body = "\n".join(
        [
            "#usda 1.0",
            "(",
            "    metersPerUnit = 100000",
            "    upAxis = \"Z\"",
            "    doc = \"Constellation: 24 hairline orbit rings + 24 small bright sat points. Generated by tools/gen_constellation.py.\"",
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
    print(f"wrote {OUT} - {RING_COUNT} hairline rings + {RING_COUNT} sat points (no atmo shell)")


if __name__ == "__main__":
    main()
