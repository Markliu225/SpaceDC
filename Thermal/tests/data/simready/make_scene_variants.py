"""Write the Sat01 scene variants used by the SimReady assembly tests from the baseline ``sat01_scene.json``.

Each variant changes only what its name says, so a test can compare it with the baseline:

- ``sat01_scene_display_scaled.json``: display scale ops on three instances; physical parameters must not change.
- ``sat01_scene_overrides.json``: one set of parameter_overrides (material, surface, Power and connection fields).
- ``sat01_scene_two_radiators.json``: invalid on purpose: Radiator02 is a second instance of the radiator asset on
  node R, which holds one temperature; the scene loader must reject it (only D is a shared extent, design table 1).
- ``sat01_scene_invalid_unregistered_model.json``: Controller01 uses an asset whose model_id is not registered.
- ``sat01_scene_invalid_scaled_geometry.json``: Radiator01 uses an asset whose USD part carries a scale op.
- ``sat01_scene_invalid_pv_efficiency.json``: an override sets the PV efficiency above the front absorptivity.

All values are illustrative test values.

    Thermal/.venv/Scripts/python.exe tests/data/simready/make_scene_variants.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _instance(scene: dict, instance_id: str) -> dict:
    return next(x for x in scene["instances"] if x["instance_id"] == instance_id)


def _write(name: str, scene: dict) -> None:
    (HERE / name).write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    base = json.loads((HERE / "sat01_scene.json").read_text(encoding="utf-8"))

    scene = copy.deepcopy(base)
    scene["scene_id"] = "sdtwin.example.sat01.display_scaled"
    scene["description"] = ("Baseline Sat01 with display scale ops on SolarArray01, Compute01 and Radiator01. "
                            "Areas, masses and resistances must equal the baseline.")
    _instance(scene, "SolarArray01")["display_transform"]["scale"] = [3.0, 3.0, 3.0]
    _instance(scene, "Compute01")["display_transform"]["scale"] = [10.0, 10.0, 10.0]
    _instance(scene, "Radiator01")["display_transform"]["scale"] = [2.0, 1.0, 2.0]
    _write("sat01_scene_display_scaled.json", scene)

    scene = copy.deepcopy(base)
    scene["scene_id"] = "sdtwin.example.sat01.overrides"
    scene["description"] = "Baseline Sat01 with one set of parameter_overrides that take precedence over the assets."
    scene["parameter_overrides"] = {
        "source": "illustrative test value: scenario overrides for the assembly tests",
        "instances": {
            "Battery01": {"thermal": {"materials": {"li_ion_cells": {"mass_kg": 0.80}}}},
            "Radiator01": {"thermal": {
                "materials": {"facesheet_al6061": {"density_kg_m3": 2810.0, "cp_J_kgK": 960.0}},
                "surfaces": {"front": {"absorptivity": 0.25}},
            }},
            "ColdPlate01": {"thermal": {"materials": {"plate_al6061": {"solid_fraction": 0.7}}}},
            "SolarArray01": {"power": {"efficiency": 0.28}},
        },
        "connections": {"BR": {"contact_resistance_K_W": 0.5}, "CR": {"equivalent_total_resistance_K_W": 0.15}},
    }
    _write("sat01_scene_overrides.json", scene)

    scene = copy.deepcopy(base)
    scene["scene_id"] = "sdtwin.example.sat01.two_radiators"
    scene["description"] = ("Invalid on purpose: baseline Sat01 plus Radiator02, a second instance of the radiator "
                            "asset on node R; node R holds one temperature, so the scene loader must reject it.")
    scene["instances"].append({
        "instance_id": "Radiator02", "asset_ref": "assets/radiator_panel.json",
        "mounting": {"body_from_asset_xyzw": [-0.7071067811865476, 0.0, 0.0, 0.7071067811865476]},
        "display_transform": {"translate_m": [0.0, 0.2, 0.0]},
    })
    scene["initial_state"]["thermal"]["temperature_K"]["Radiator02"] = 283.15
    scene["parameter_overrides"] = {
        "source": "illustrative test value: degraded paint on the second radiator only",
        "instances": {"Radiator02": {"thermal": {"surfaces": {"front": {"emissivity": 0.80}}}}},
        "connections": {},
    }
    _write("sat01_scene_two_radiators.json", scene)

    scene = copy.deepcopy(base)
    scene["scene_id"] = "sdtwin.example.sat01.invalid_unregistered_model"
    scene["description"] = "Invalid on purpose: Controller01 references an asset whose thermal model_id is unregistered."
    _instance(scene, "Controller01")["asset_ref"] = "assets/invalid_unregistered_model.json"
    _write("sat01_scene_invalid_unregistered_model.json", scene)

    scene = copy.deepcopy(base)
    scene["scene_id"] = "sdtwin.example.sat01.invalid_scaled_geometry"
    scene["description"] = "Invalid on purpose: Radiator01 references an asset whose USD part carries a scale op."
    _instance(scene, "Radiator01")["asset_ref"] = "assets/invalid_scaled_geometry.json"
    _write("sat01_scene_invalid_scaled_geometry.json", scene)

    scene = copy.deepcopy(base)
    scene["scene_id"] = "sdtwin.example.sat01.invalid_pv_efficiency"
    scene["description"] = ("Invalid on purpose: the PV efficiency override exceeds the absorptivity of the same "
                            "front surface (thermal design 9.4).")
    scene["parameter_overrides"] = {
        "source": "illustrative test value: impossible efficiency for the 9.4 check",
        "instances": {"SolarArray01": {"power": {"efficiency": 0.95}}},
        "connections": {},
    }
    _write("sat01_scene_invalid_pv_efficiency.json", scene)


if __name__ == "__main__":
    main()
