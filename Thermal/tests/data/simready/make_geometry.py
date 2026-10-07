"""Write the USD geometry of the illustrative Sat01 SimReady assets (run with the Thermal interpreter).

Every file authors ``metersPerUnit`` and a ``defaultPrim``; each physical part is a box mesh whose authored extent,
times ``metersPerUnit``, is its physical size. The compute board is authored in millimetres and the cold plate in
centimetres to exercise unit handling. ``invalid_scaled_panel.usda`` puts a scale op on a part and must be rejected.
All dimensions are illustrative test values for a small computing satellite.

    Thermal/.venv/Scripts/python.exe tests/data/simready/make_geometry.py
"""

from __future__ import annotations

from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, Vt

HERE = Path(__file__).resolve().parent / "geometry"


def _box(stage: Usd.Stage, path: str, size: tuple[float, float, float]) -> UsdGeom.Mesh:
    sx, sy, sz = (0.5 * v for v in size)
    points = [Gf.Vec3f(x, y, z) for z in (-sz, sz) for y in (-sy, sy) for x in (-sx, sx)]
    faces = [0, 2, 3, 1, 4, 5, 7, 6, 0, 1, 5, 4, 2, 6, 7, 3, 0, 4, 6, 2, 1, 3, 7, 5]
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(Vt.Vec3fArray(points))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray([4] * 6))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(faces))
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    mesh.CreateExtentAttr(UsdGeom.Boundable.ComputeExtentFromPlugins(mesh, Usd.TimeCode.Default()))
    return mesh


def _stage(name: str, root: str, meters_per_unit: float, doc: str) -> Usd.Stage:
    path = HERE / name
    if path.exists():
        path.unlink()
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    prim = UsdGeom.Xform.Define(stage, Sdf.Path(f"/{root}")).GetPrim()
    stage.SetDefaultPrim(prim)
    stage.GetRootLayer().documentation = doc
    return stage


def main() -> None:
    HERE.mkdir(exist_ok=True)
    note = "Illustrative test geometry for the SDTwin thermal scene tests; not a selected device. "

    stage = _stage("solar_array_panel.usda", "SolarArrayPanel", 1.0, note + "Two-sided panel 1.0 m x 0.6 m x 25 mm.")
    _box(stage, "/SolarArrayPanel/Panel", (1.0, 0.6, 0.025))
    stage.Save()

    stage = _stage("compute_board.usda", "ComputeBoard", 0.001,
                   note + "Authored in millimetres: board 160 x 100 x 1.6 mm, copper spreader 150 x 90 x 4 mm.")
    _box(stage, "/ComputeBoard/Board", (160.0, 100.0, 1.6))
    spreader = _box(stage, "/ComputeBoard/Spreader", (90.0, 150.0, 4.0))
    spreader.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(0.0, 0.0, 2.8))
    spreader.AddRotateZOp(UsdGeom.XformOp.PrecisionDouble).Set(90.0)
    stage.Save()

    stage = _stage("cold_plate.usda", "ColdPlate", 0.01, note + "Authored in centimetres: plate 20 x 15 x 1.2 cm.")
    _box(stage, "/ColdPlate/Plate", (20.0, 15.0, 1.2))
    stage.Save()

    stage = _stage("battery_pack.usda", "BatteryPack", 1.0, note + "Pack envelope 190 x 120 x 75 mm.")
    _box(stage, "/BatteryPack/Pack", (0.19, 0.12, 0.075))
    stage.Save()

    stage = _stage("power_controller.usda", "PowerController", 1.0, note + "Housing 160 x 120 x 50 mm.")
    _box(stage, "/PowerController/Housing", (0.16, 0.12, 0.05))
    stage.Save()

    stage = _stage("pdu.usda", "PDU", 1.0, note + "Housing 140 x 100 x 45 mm.")
    _box(stage, "/PDU/Housing", (0.14, 0.10, 0.045))
    stage.Save()

    stage = _stage("radiator_panel.usda", "RadiatorPanel", 1.0, note + "Aluminium facesheet 0.8 m x 0.6 m x 2 mm.")
    _box(stage, "/RadiatorPanel/Panel", (0.8, 0.6, 0.002))
    stage.Save()

    stage = _stage("invalid_scaled_panel.usda", "RadiatorPanel", 1.0,
                   note + "Invalid on purpose: the part carries a scale op, so its extent is not its physical size.")
    panel = _box(stage, "/RadiatorPanel/Panel", (0.4, 0.3, 0.002))
    panel.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(2.0, 2.0, 1.0))
    stage.Save()


if __name__ == "__main__":
    main()
