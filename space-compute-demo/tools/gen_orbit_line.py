"""Generate usd/orbit_line.usda — a tilted circular great-circle BasisCurve
at altitude 550 km (scene units r=69.21), inclination 60 deg to suggest SSO.

Visualization-only: the actual backend physics traces a more complex ground
track, but a clean tilted ring reads clearly as "orbit" in the Overview view.
"""
from __future__ import annotations

import math
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, Vt  # type: ignore

OUT = Path(__file__).resolve().parent.parent / "usd" / "orbit_line.usda"

RADIUS = 69.21  # 1 scene unit = 100 km; 6371+550 = 6921 km / 100
INCLINATION_DEG = 60.0
N = 96            # segments
WIDTH = 0.22      # scene units (~22 km at our scale) — visible as thin bright line
COLOR = (0.0, 2.2, 2.4)  # very bright cyan — with tonemap it saturates near white/cyan


def build_orbit() -> tuple[list[Gf.Vec3f], list[int], list[int]]:
    # Unified orbit formula (shared with backend + Kit icon):
    #   u = (1, 0, 0), v = (0, cos a, sin a)
    #   P(theta) = R * (cos theta, sin theta * cos a, sin theta * sin a)
    alpha = math.radians(INCLINATION_DEG)
    cos_a, sin_a = math.cos(alpha), math.sin(alpha)
    pts: list[Gf.Vec3f] = []
    for i in range(N + 1):
        theta = 2.0 * math.pi * i / N
        c, s = math.cos(theta), math.sin(theta)
        pts.append(Gf.Vec3f(RADIUS * c, RADIUS * s * cos_a, RADIUS * s * sin_a))
    counts = [N + 1]
    indices = list(range(N + 1))
    return pts, counts, indices


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(OUT))
    UsdGeom.SetStageMetersPerUnit(stage, 100000)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Xform.Define(stage, "/World/Orbit")
    curve = UsdGeom.BasisCurves.Define(stage, "/World/Orbit/OrbitLine")

    pts, counts, _ = build_orbit()
    curve.CreatePointsAttr(Vt.Vec3fArray(pts))
    curve.CreateCurveVertexCountsAttr(Vt.IntArray(counts))
    curve.CreateTypeAttr(UsdGeom.Tokens.linear)
    curve.CreateWidthsAttr(Vt.FloatArray([WIDTH]))
    widths = curve.GetWidthsAttr()
    widths_api = UsdGeom.PrimvarsAPI(curve)
    widths_api.CreatePrimvar(
        "widths", Sdf.ValueTypeNames.FloatArray, interpolation=UsdGeom.Tokens.constant
    ).Set(Vt.FloatArray([WIDTH]))
    pvars = UsdGeom.PrimvarsAPI(curve)
    pvars.CreatePrimvar(
        "displayColor",
        Sdf.ValueTypeNames.Color3fArray,
        interpolation=UsdGeom.Tokens.constant,
    ).Set(Vt.Vec3fArray([Gf.Vec3f(*COLOR)]))

    # do not cast shadows or illuminate other prims
    curve.GetPrim().CreateAttribute(
        "primvars:doNotCastShadows", Sdf.ValueTypeNames.Bool, variability=Sdf.VariabilityUniform
    ).Set(True)

    stage.Save()
    print(f"wrote {OUT} ({N} segments)")


if __name__ == "__main__":
    main()
