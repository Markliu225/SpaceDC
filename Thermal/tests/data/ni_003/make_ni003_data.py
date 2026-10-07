"""Write the NI-003 assets, USD geometry and scene variants from the shared Sat01 example data.

Run once with the Thermal interpreter; the test reads the written files and never regenerates them:

    Thermal/.venv/Scripts/python.exe tests/data/ni_003/make_ni003_data.py

Every scene is a copy of ``tests/data/simready/sat01_scene.json`` whose ``asset_ref`` paths point back to the shared
example assets, so the second satellite and every variant use the same asset files as Sat01. Each variant changes only
what its name says. All values are illustrative test values, not selected devices.

Geometry written here (USD, via pxr):
- ``radiator_panel_display_scaled.usda``: the example radiator panel with a display scale of 2 on its default prim, as
  a viewer export may leave it; the scaled bounding box is not the physical size (thermal design 9.4).
- ``radiator_panel_mm.usda``: the same 0.8 m x 0.6 m x 2 mm panel authored in millimetres (metersPerUnit 0.001).
- ``radiator_panel_large.usda``: revision 0.2.0 of the radiator with a 1.0 m x 0.6 m x 2 mm facesheet.
- ``power_controller_payload.usda``: the example controller housing plus Python source text in a custom attribute and
  in the layer metadata; loading must not execute it (thermal design 9.3).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, Vt

HERE = Path(__file__).resolve().parent
SIMREADY = HERE.parent / "simready"
ASSETS = HERE / "assets"
GEOMETRY = HERE / "geometry"
SCENES = HERE / "scenes"
SHARED_ASSETS = "../../simready/assets/"
SHARED_GEOMETRY = "../../simready/geometry/"

# Python source placed in the payload USD file; executing it would write the marker into the file named by the
# environment variable NI003_SENTINEL (set only by the probe).
USD_PAYLOAD_MARKER = "NI003-USD-PAYLOAD-EXECUTED"
USD_PAYLOAD_CODE = (
    "import os, pathlib; pathlib.Path(os.environ['NI003_SENTINEL']).write_text('" + USD_PAYLOAD_MARKER + "')"
)


# ------------------------------------------------------------------------------------------------------------ USD


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


def _stage(name: str, root: str, meters_per_unit: float, doc: str) -> tuple[Usd.Stage, Usd.Prim]:
    path = GEOMETRY / name
    if path.exists():
        path.unlink()
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    prim = UsdGeom.Xform.Define(stage, Sdf.Path(f"/{root}")).GetPrim()
    stage.SetDefaultPrim(prim)
    stage.GetRootLayer().documentation = doc
    return stage, prim


def write_geometry() -> None:
    GEOMETRY.mkdir(exist_ok=True)
    note = "NI-003 test geometry, illustrative values, not a selected device. "

    stage, root = _stage("radiator_panel_display_scaled.usda", "RadiatorPanel", 1.0,
                         note + "Example radiator facesheet 0.8 m x 0.6 m x 2 mm with a display scale of 2 on the "
                         "default prim; the scaled bounding box is 1.6 m x 1.2 m x 4 mm and is not the physical size.")
    UsdGeom.Xformable(root).AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(2.0, 2.0, 2.0))
    _box(stage, "/RadiatorPanel/Panel", (0.8, 0.6, 0.002))
    stage.Save()

    stage, _ = _stage("radiator_panel_mm.usda", "RadiatorPanel", 0.001,
                      note + "Example radiator facesheet authored in millimetres: 800 x 600 x 2 mm.")
    _box(stage, "/RadiatorPanel/Panel", (800.0, 600.0, 2.0))
    stage.Save()

    stage, _ = _stage("radiator_panel_large.usda", "RadiatorPanel", 1.0,
                      note + "Radiator revision 0.2.0: larger aluminium facesheet 1.0 m x 0.6 m x 2 mm.")
    _box(stage, "/RadiatorPanel/Panel", (1.0, 0.6, 0.002))
    stage.Save()

    stage, _ = _stage("power_controller_payload.usda", "PowerController", 1.0,
                      note + "Example controller housing 160 x 120 x 50 mm carrying Python source text in a custom "
                      "attribute and in the layer metadata; a loader must never execute it.")
    mesh = _box(stage, "/PowerController/Housing", (0.16, 0.12, 0.05))
    attribute = mesh.GetPrim().CreateAttribute("sdtwin:thermal_model_code", Sdf.ValueTypeNames.String, custom=True)
    attribute.Set(USD_PAYLOAD_CODE)
    stage.GetRootLayer().customLayerData = {"sdtwin:model_id": "ni003_payload:execute",
                                            "sdtwin:on_load": USD_PAYLOAD_CODE}
    stage.Save()


# --------------------------------------------------------------------------------------------------------- assets


def _asset(name: str) -> dict:
    return json.loads((SIMREADY / "assets" / name).read_text(encoding="utf-8"))


def _capability(asset: dict, domain: str) -> dict:
    return next(c for c in asset["capabilities"] if c["domain"] == domain)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _ni003_provenance(note: str) -> dict:
    return {"status": "illustrative_test_value", "note": "NI-003 test asset. " + note, "references": []}


def write_assets() -> None:
    ASSETS.mkdir(exist_ok=True)

    asset = _asset("radiator_panel.json")
    asset["asset_id"] = "ni003.radiator_panel_display_scaled"
    asset["description"] = ("Display-scaled asset: the example radiator panel whose default prim carries a display "
                            "scale of 2. The scaled bounding box must not be taken as the physical size.")
    asset["geometry_uri"] = "../geometry/radiator_panel_display_scaled.usda"
    asset["provenance"] = _ni003_provenance("Display scale on the default prim, design 9.4.")
    _write_json(ASSETS / "radiator_panel_display_scaled.json", asset)

    asset = _asset("radiator_panel.json")
    asset["asset_id"] = "ni003.radiator_panel_mm"
    asset["description"] = "The example radiator panel with its geometry authored in millimetres."
    asset["geometry_uri"] = "../geometry/radiator_panel_mm.usda"
    asset["provenance"] = _ni003_provenance("Same panel as sdtwin.example.radiator_panel, length unit millimetre.")
    _write_json(ASSETS / "radiator_panel_mm.json", asset)

    asset = _asset("radiator_panel.json")
    asset["asset_version"] = "0.2.0"
    asset["description"] = ("Revision 0.2.0 of the example radiator: larger aluminium facesheet 1.0 m x 0.6 m x 2 mm, "
                            "same materials and coatings.")
    asset["geometry_uri"] = "../geometry/radiator_panel_large.usda"
    asset["provenance"] = _ni003_provenance("Geometry change of the radiator for the NI-003 recalculation check.")
    _write_json(ASSETS / "radiator_panel_large.json", asset)

    asset = _asset("power_controller.json")
    asset["asset_id"] = "ni003.power_controller_unregistered_power"
    asset["description"] = "Invalid on purpose: the power model_id names a version that is not in the registry."
    asset["geometry_uri"] = SHARED_GEOMETRY + "power_controller.usda"
    _capability(asset, "power")["model_id"] = "sdtwin.power.controller.ideal_mppt/2"
    asset["provenance"] = _ni003_provenance("Unregistered power model_id.")
    _write_json(ASSETS / "power_controller_unregistered_power.json", asset)

    asset = _asset("power_controller.json")
    asset["asset_id"] = "ni003.power_controller_cross_domain"
    asset["description"] = "Invalid on purpose: the thermal capability names a model_id of the power registry."
    asset["geometry_uri"] = SHARED_GEOMETRY + "power_controller.usda"
    _capability(asset, "thermal")["model_id"] = "sdtwin.power.controller.ideal_mppt/1"
    asset["provenance"] = _ni003_provenance("Model id registered only in another domain.")
    _write_json(ASSETS / "power_controller_cross_domain.json", asset)

    asset = _asset("power_controller.json")
    asset["asset_id"] = "ni003.power_controller_payload_model"
    asset["description"] = ("Invalid on purpose: the thermal model_id is a plug-in style import path to the module "
                            "payload/ni003_payload.py; the loader must reject it without importing anything.")
    asset["geometry_uri"] = SHARED_GEOMETRY + "power_controller.usda"
    _capability(asset, "thermal")["model_id"] = "ni003_payload:execute"
    asset["provenance"] = _ni003_provenance("Import path as model_id.")
    _write_json(ASSETS / "power_controller_payload_model.json", asset)

    asset = _asset("power_controller.json")
    asset["asset_id"] = "ni003.power_controller_payload_usd"
    asset["description"] = ("The example controller with registered models; its USD file carries Python source text "
                            "that a loader must never execute.")
    asset["geometry_uri"] = "../geometry/power_controller_payload.usda"
    asset["provenance"] = _ni003_provenance("Python source text inside the USD file.")
    _write_json(ASSETS / "power_controller_payload_usd.json", asset)

    asset = _asset("solar_array_panel.json")
    asset["asset_id"] = "ni003.solar_array_back_cells"
    asset["description"] = ("The example panel with its Power capability bound to the back surface: efficiency 0.89 "
                            "exceeds the back absorptivity 0.88 but not the front absorptivity 0.91.")
    asset["geometry_uri"] = SHARED_GEOMETRY + "solar_array_panel.usda"
    _capability(asset, "power")["parameter_set"] = {"cell_area_m2": 0.51, "efficiency": 0.89, "surface_id": "back"}
    asset["provenance"] = _ni003_provenance("Efficiency checked against the absorptivity of the same surface.")
    _write_json(ASSETS / "solar_array_back_cells.json", asset)

    asset = _asset("battery_pack.json")
    asset["asset_id"] = "ni003.battery_pack_duplicate_material"
    asset["description"] = "Invalid on purpose: the cell mass is listed twice under one material_id."
    asset["geometry_uri"] = SHARED_GEOMETRY + "battery_pack.usda"
    materials = _capability(asset, "thermal")["parameter_set"]["materials"]
    materials.append(copy.deepcopy(materials[0]))
    asset["provenance"] = _ni003_provenance("Duplicate material portion.")
    _write_json(ASSETS / "battery_pack_duplicate_material.json", asset)


# --------------------------------------------------------------------------------------------------------- scenes


def _base() -> dict:
    scene = json.loads((SIMREADY / "sat01_scene.json").read_text(encoding="utf-8"))
    for item in scene["instances"]:
        item["asset_ref"] = SHARED_ASSETS + item["asset_ref"].split("/")[-1]
    return scene


def _instance(scene: dict, instance_id: str) -> dict:
    return next(x for x in scene["instances"] if x["instance_id"] == instance_id)


def _overrides(source: str, instances: dict | None = None, connections: dict | None = None) -> dict:
    return {"source": source, "instances": instances or {}, "connections": connections or {}}


def _consistent_x_p(x_n: float) -> float:
    """x_p with the lithium inventory of the SOC 100 point of the stand-in cell parameter pack (Power design P5)."""

    from sdtwin_sim import power_stand_in as ps

    asset_record, scene_record = ps.example_power_records()
    battery = ps.load_power_parameters(asset_record, scene_record).battery
    return battery.x_p_100 + (battery.x_n_100 - x_n) * battery.Q_n_C / battery.Q_p_C


def write_scenes() -> None:
    SCENES.mkdir(exist_ok=True)

    def write(name: str, scene_id: str, description: str, scene: dict) -> None:
        scene["scene_id"] = scene_id
        scene["description"] = description
        _write_json(SCENES / name, scene)

    scene = _base()
    scene["initial_state"]["thermal"]["temperature_K"] = {
        "SolarArray01": 300.0, "Battery01": 288.15, "Controller01": 290.15, "PDU01": 290.15,
        "Compute01": 295.15, "ColdPlate01": 291.15, "Radiator01": 275.15,
    }
    scene["initial_state"]["power"]["Battery01"] = {"x_n": 0.55, "x_p": _consistent_x_p(0.55)}
    scene["provenance"]["note"] = ("Second satellite built from the same asset files as Sat01, with its own initial "
                                   "temperatures and lithium state; illustrative test values.")
    write("sat02_scene.json", "sdtwin.example.sat02",
          "Second satellite of NI-003: the Sat01 assets and connections with other initial temperatures and another "
          "initial lithium state. The loader accepts only the root /World/Sat01, so the root path is kept.", scene)

    scene = _base()
    scene["root_prim_path"] = "/World/Sat02"
    write("sat02_root_sat02.json", "sdtwin.example.sat02.root",
          "Observation only: the second satellite under its own root /World/Sat02.", scene)

    scene = _base()
    scales = {"SolarArray01": [3.0, 3.0, 3.0], "Battery01": [1.0, 2.0, 4.0], "Controller01": [5.0, 1.0, 1.0],
              "PDU01": [0.5, 0.5, 0.5], "Compute01": [10.0, 10.0, 10.0], "ColdPlate01": [1.0, 4.0, 0.5],
              "Radiator01": [2.0, 1.0, 2.0]}
    for iid, scale in scales.items():
        _instance(scene, iid)["display_transform"]["scale"] = scale
    write("sat01_display_scaled_all.json", "sdtwin.example.sat01.ni003_display_scaled_all",
          "Sat01 with display scale ops on all seven instances; physical parameters must equal Sat01.", scene)

    scene = _base()
    _instance(scene, "Radiator01")["asset_ref"] = "../assets/radiator_panel_display_scaled.json"
    write("sat01_display_scaled_asset.json", "sdtwin.example.sat01.ni003_display_scaled_asset",
          "Radiator01 uses the display-scaled asset whose default prim carries a scale op.", scene)

    scene = _base()
    _instance(scene, "Radiator01")["asset_ref"] = "../assets/radiator_panel_mm.json"
    write("sat01_radiator_mm.json", "sdtwin.example.sat01.ni003_radiator_mm",
          "Radiator01 uses the same panel authored in millimetres.", scene)

    scene = _base()
    _instance(scene, "Radiator01")["asset_ref"] = "../assets/radiator_panel_large.json"
    write("sat01_geometry_change.json", "sdtwin.example.sat01.ni003_geometry_change",
          "Radiator01 uses revision 0.2.0 with a 1.0 m x 0.6 m facesheet.", scene)

    scene = _base()
    _instance(scene, "Radiator01")["mounting"]["body_from_asset_xyzw"] = [0.0, 0.0, 0.0, 1.0]
    scene["parameter_overrides"] = _overrides(
        "illustrative test value: NI-003 installation change, radiator remounted with its front to +Z, longer BR "
        "bracket, wider SR hinge bracket and a dry DR mounting interface",
        connections={"BR": {"length_m": 0.08}, "SR": {"area_m2": 4.0e-4}, "DR": {"contact_resistance_K_W": 0.4}})
    write("sat01_installation_change.json", "sdtwin.example.sat01.ni003_installation_change",
          "Installation change: Radiator01 mounting and three connection overrides.", scene)

    scene = _base()
    scene["parameter_overrides"] = _overrides(
        "illustrative test value: NI-003 material change of five portions and one coating",
        instances={
            "Compute01": {"thermal": {"materials": {"copper_spreader": {"cp_J_kgK": 390.0}}}},
            "Controller01": {"thermal": {"materials": {"electronics_pcb": {"mass_kg": 0.20}}}},
            "ColdPlate01": {"thermal": {"materials": {"plate_al6061": {"density_kg_m3": 2810.0}}}},
            "SolarArray01": {"thermal": {"surfaces": {"back": {"emissivity": 0.80}}}},
            "Radiator01": {"thermal": {"materials": {"embedded_heat_pipes": {"mass_kg": 0.40}}}},
        })
    write("sat01_material_change.json", "sdtwin.example.sat01.ni003_material_change",
          "Material change: overrides of one specific heat, two masses, one density and one emissivity.", scene)

    scene = _base()
    scene["instances"].append({"instance_id": "Battery02", "asset_ref": SHARED_ASSETS + "battery_pack.json",
                               "mounting": {"body_from_asset_xyzw": [0.0, 0.0, 0.0, 1.0]},
                               "display_transform": {"translate_m": [-0.15, 0.3, -0.1]}})
    scene["initial_state"]["thermal"]["temperature_K"]["Battery02"] = 293.15
    write("sat01_second_battery.json", "sdtwin.example.sat01.ni003_second_battery",
          "Invalid on purpose: a second instance of the battery asset on node B.", scene)

    scene = _base()
    scene["instances"].append({"instance_id": "PDU02", "asset_ref": SHARED_ASSETS + "pdu.json",
                               "mounting": {"body_from_asset_xyzw": [0.0, 0.0, 0.0, 1.0]},
                               "display_transform": {"translate_m": [-0.15, -0.3, 0.0]}})
    scene["initial_state"]["thermal"]["temperature_K"]["PDU02"] = 293.15
    write("sat01_second_pdu.json", "sdtwin.example.sat01.ni003_second_pdu",
          "Invalid on purpose: a second instance of the PDU asset on the shared node D.", scene)

    scene = _base()
    next(c for c in scene["connections"]["thermal"] if c["path"] == "BR")["to_instance"] = "Controller01"
    write("sat01_br_to_controller.json", "sdtwin.example.sat01.ni003_br_to_controller",
          "Invalid on purpose: the BR thermal path ends at Controller01 instead of the radiator.", scene)

    for name, asset in (("sat01_unregistered_power_model.json", "power_controller_unregistered_power.json"),
                        ("sat01_cross_domain_model.json", "power_controller_cross_domain.json"),
                        ("sat01_payload_model.json", "power_controller_payload_model.json"),
                        ("sat01_payload_usd.json", "power_controller_payload_usd.json")):
        scene = _base()
        _instance(scene, "Controller01")["asset_ref"] = "../assets/" + asset
        write(name, "sdtwin.example.sat01.ni003_" + name.removeprefix("sat01_").removesuffix(".json"),
              f"Controller01 uses {asset}.", scene)

    scene = _base()
    _instance(scene, "SolarArray01")["asset_ref"] = "../assets/solar_array_back_cells.json"
    write("sat01_pv_back_cells.json", "sdtwin.example.sat01.ni003_pv_back_cells",
          "Invalid on purpose: PV efficiency 0.89 on the back surface of absorptivity 0.88.", scene)

    scene = _base()
    _instance(scene, "SolarArray01")["asset_ref"] = "../assets/solar_array_back_cells.json"
    scene["parameter_overrides"] = _overrides("illustrative test value: NI-003 back cell efficiency 0.87",
                                              instances={"SolarArray01": {"power": {"efficiency": 0.87}}})
    write("sat01_pv_back_cells_override.json", "sdtwin.example.sat01.ni003_pv_back_cells_override",
          "PV efficiency 0.87 on the back surface of absorptivity 0.88.", scene)

    for name, overrides, text in (
        ("sat01_pv_absorptivity_override.json",
         {"SolarArray01": {"thermal": {"surfaces": {"front": {"absorptivity": 0.25}}}}},
         "Invalid on purpose: the front absorptivity override 0.25 falls below the PV efficiency 0.295."),
        ("sat01_pv_equal.json", {"SolarArray01": {"power": {"efficiency": 0.91}}},
         "PV efficiency 0.91 equal to the front absorptivity 0.91."),
        ("sat01_pv_slightly_above.json", {"SolarArray01": {"power": {"efficiency": 0.9101}}},
         "Invalid on purpose: PV efficiency 0.9101 just above the front absorptivity 0.91."),
    ):
        scene = _base()
        scene["parameter_overrides"] = _overrides("illustrative test value: NI-003 design 9.4 efficiency check",
                                                  instances=overrides)
        write(name, "sdtwin.example.sat01.ni003_" + name.removeprefix("sat01_").removesuffix(".json"), text, scene)

    scene = _base()
    _instance(scene, "Battery01")["asset_ref"] = "../assets/battery_pack_duplicate_material.json"
    write("sat01_duplicate_material.json", "sdtwin.example.sat01.ni003_duplicate_material",
          "Invalid on purpose: Battery01 uses an asset that lists its cell mass twice.", scene)

    scene = _base()
    scene["initial_state"]["power"]["Battery01"]["T_B_K"] = 293.15
    write("sat01_battery_temperature_in_power_state.json", "sdtwin.example.sat01.ni003_battery_temperature_power",
          "Invalid on purpose: a battery temperature in the Power initial state; Thermal owns it.", scene)


def main() -> None:
    import sys

    sys.path.insert(0, str(HERE.parents[2]))
    write_geometry()
    write_assets()
    write_scenes()


if __name__ == "__main__":
    main()
