"""Generate usd/constellation.usda from a TLE-style constellation preset.

Architecture (per user direction):
  - Constellation is defined in Earth's EQUATORIAL frame. The 23.5 deg
    axial tilt is applied at the overview.usda level via `over Constellation`,
    so this file stays in the natural orbit frame.
  - Each preset captures the parameters that a real TLE would express:
    inclination, altitude, plane count, sats per plane, RAAN spread.
  - Output: 1 BasisCurves per orbital plane (the trajectory) + 1 Sphere
    per satellite. All small, all dim — colored hue-rotated by orbital
    plane so planes are visually distinct.

Run:
    backend/.venv/Scripts/python.exe tools/gen_constellation.py [preset]
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "usd" / "constellation.usda"

# 1 unit = 100 km (matches overview.usda metersPerUnit = 100000).
EARTH_R_UNITS = 63.71

# --- Constellation presets ----------------------------------------------------
# Each entry is one option for `PRESET` below. Numbers are taken from public
# TLE archives + system descriptions, lightly simplified for visual density.

PRESETS: dict[str, dict] = {
    "starlink": {
        "doc":           "Starlink Shell 1 style — LEO 550 km, inc 53°",
        "altitude_km":   550.0,
        "inclination_deg": 53.0,
        "planes":        6,        # real Shell 1 has 72; 6 is enough to read
        "sats_per_plane": 8,       # real has 22; 8 is enough to read motion
        "raan_spread_deg": 360.0,  # planes evenly distributed
        "plane_hue_offset_deg": 0.0,
    },
    "oneweb": {
        "doc":           "OneWeb style — LEO 1200 km, inc 87.4°",
        "altitude_km":   1200.0,
        "inclination_deg": 87.4,
        "planes":        6,
        "sats_per_plane": 6,
        "raan_spread_deg": 180.0,  # OneWeb shells span half the sky
        "plane_hue_offset_deg": 30.0,
    },
    "gps": {
        "doc":           "GPS MEO — alt 20200 km, inc 55°, 6 planes × 4 sats",
        "altitude_km":   20200.0,
        "inclination_deg": 55.0,
        "planes":        6,
        "sats_per_plane": 4,
        "raan_spread_deg": 360.0,
        "plane_hue_offset_deg": 0.0,
    },
}

# Default preset. CLI override: `python gen_constellation.py oneweb`.
DEFAULT_PRESET = "starlink"

# Visual styling.
RING_VERTS         = 96
RING_WIDTH_UNITS   = 0.04        # 4 km — hairline at overview camera distance
SAT_RADIUS_UNITS   = 0.30        # 30 km diameter — small dot

# Emissive levels SAFELY UNDER the bloom threshold (~0.85 in Kit's RTX
# default). Ring emissive stays low because 6 planes can overlap visually
# from any camera angle. Sat dots get a bit more so they punch through.
RING_EMIT_GAIN     = 0.10
SAT_EMIT_GAIN      = 0.55

# Per-plane hue (HSL-ish, cycled around the wheel).
def hsv_to_rgb(h_deg: float, s: float = 0.65, v: float = 0.95) -> tuple[float, float, float]:
    h = (h_deg % 360) / 60.0
    c = v * s
    x = c * (1 - abs((h % 2) - 1))
    m = v - c
    if 0 <= h < 1:  r, g, b = c, x, 0
    elif 1 <= h < 2: r, g, b = x, c, 0
    elif 2 <= h < 3: r, g, b = 0, c, x
    elif 3 <= h < 4: r, g, b = 0, x, c
    elif 4 <= h < 5: r, g, b = x, 0, c
    else:            r, g, b = c, 0, x
    return (r + m, g + m, b + m)


def plane_color(plane_idx: int, n_planes: int, hue_offset: float) -> tuple[float, float, float]:
    """Each orbital plane gets its own hue. Spread evenly around the wheel."""
    h = hue_offset + (plane_idx / n_planes) * 360.0
    return hsv_to_rgb(h)


def transform_point(x, y, z, inc, raan):
    """Apply inclination (rotate around +X) then RAAN (rotate around +Z)."""
    cy, sy = math.cos(inc), math.sin(inc)
    x1, y1, z1 = x, y * cy - z * sy, y * sy + z * cy
    cz, sz = math.cos(raan), math.sin(raan)
    x2 = x1 * cz - y1 * sz
    y2 = x1 * sz + y1 * cz
    z2 = z1
    return x2, y2, z2


def orbit_points(orbit_r_units: float, inc_rad: float, raan_rad: float) -> list[tuple[float, float, float]]:
    pts = []
    for k in range(RING_VERTS):
        theta = (k / (RING_VERTS - 1)) * 2.0 * math.pi
        x = math.cos(theta) * orbit_r_units
        y = math.sin(theta) * orbit_r_units
        pts.append(transform_point(x, y, 0.0, inc_rad, raan_rad))
    return pts


def sat_position(orbit_r_units: float, inc_rad: float, raan_rad: float, phase_rad: float) -> tuple[float, float, float]:
    x = math.cos(phase_rad) * orbit_r_units
    y = math.sin(phase_rad) * orbit_r_units
    return transform_point(x, y, 0.0, inc_rad, raan_rad)


def emit_ring(idx: int, plane_idx: int, pts: list[tuple[float, float, float]], color: tuple[float, float, float]) -> str:
    pts_str = ", ".join(f"({p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f})" for p in pts)
    er, eg, eb = (color[0] * RING_EMIT_GAIN, color[1] * RING_EMIT_GAIN, color[2] * RING_EMIT_GAIN)
    return f"""
        def BasisCurves "Ring_{idx:03d}" (
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
            rel material:binding = </World/Constellation/Looks/PlaneMat_{plane_idx:02d}>
        }}"""


def emit_sat(idx: int, plane_idx: int, pos: tuple[float, float, float]) -> str:
    return f"""
        def Sphere "Sat_{idx:03d}" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {{
            double radius = {SAT_RADIUS_UNITS}
            double3 xformOp:translate = ({pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f})
            uniform token[] xformOpOrder = ["xformOp:translate"]
            uniform bool primvars:doNotCastShadows = 1
            rel material:binding = </World/Constellation/Looks/SatMat_{plane_idx:02d}>
        }}"""


def emit_material(name: str, color: tuple[float, float, float], gain: float) -> str:
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


def build(preset_name: str) -> str:
    if preset_name not in PRESETS:
        raise SystemExit(f"unknown preset '{preset_name}'. options: {list(PRESETS)}")
    p = PRESETS[preset_name]

    orbit_r_units = EARTH_R_UNITS + p["altitude_km"] / 100.0
    inc_rad       = math.radians(p["inclination_deg"])
    n_planes      = int(p["planes"])
    sats_per      = int(p["sats_per_plane"])
    raan_spread   = math.radians(p["raan_spread_deg"])
    hue_offset    = float(p["plane_hue_offset_deg"])

    # Materials: 1 ring material + 1 sat material per plane (so plane is one hue).
    materials: list[str] = []
    plane_colors: list[tuple[float, float, float]] = []
    for plane_idx in range(n_planes):
        c = plane_color(plane_idx, n_planes, hue_offset)
        plane_colors.append(c)
        materials.append(emit_material(f"PlaneMat_{plane_idx:02d}", c, RING_EMIT_GAIN))
        materials.append(emit_material(f"SatMat_{plane_idx:02d}",   c, SAT_EMIT_GAIN))

    rings: list[str] = []
    sats:  list[str] = []
    ring_idx = 0
    sat_idx  = 0
    for plane_idx in range(n_planes):
        raan = (plane_idx / max(1, n_planes - 1)) * raan_spread if n_planes > 1 else 0.0
        pts  = orbit_points(orbit_r_units, inc_rad, raan)
        rings.append(emit_ring(ring_idx, plane_idx, pts, plane_colors[plane_idx]))
        ring_idx += 1
        # Phase-spread sats around this plane.
        for s in range(sats_per):
            phase = (s / sats_per) * 2.0 * math.pi
            pos   = sat_position(orbit_r_units, inc_rad, raan, phase)
            sats.append(emit_sat(sat_idx, plane_idx, pos))
            sat_idx += 1

    body = "\n".join(
        [
            "#usda 1.0",
            "(",
            "    metersPerUnit = 100000",
            "    upAxis = \"Z\"",
            f"    doc = \"Constellation preset='{preset_name}': {p['doc']}. Generated by tools/gen_constellation.py. ALT={p['altitude_km']} km, INC={p['inclination_deg']}°, planes={n_planes}, sats/plane={sats_per}. Defined in Earth's equatorial frame — the 23.5° axial tilt is applied at the overview.usda level.\"",
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
    return body


def main():
    preset = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PRESET
    body = build(preset)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    p = PRESETS[preset]
    print(
        f"wrote {OUT} — preset='{preset}'  "
        f"planes={p['planes']} × sats/plane={p['sats_per_plane']} "
        f"= {p['planes'] * p['sats_per_plane']} sats  "
        f"(inc {p['inclination_deg']}°, alt {p['altitude_km']} km)"
    )


if __name__ == "__main__":
    main()
