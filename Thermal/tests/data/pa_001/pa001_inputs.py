"""PA-001 input data and the independent T5 hand calculation.

The component and connection records follow the input format of ``assemble_thermal_parameters`` in
Thermal/IMPLEMENTATION.md. Three data sets come from the case inputs:

* the design report 4.5 example, 1 kg of material at 1000 J/(kg K), is the single material portion of node J;
* the MBSU block of the ISS thermal FE parameter table (Thermal/iss_fem/model/iss_spec.py, ORU_BOXES MBSU_1 with
  material oru_eq) is the PDU01 portion of node D;
* the EATCS radiator panel of the same table (MATERIALS hrs_pan, HRS panel geometry) is node R.

Every other value is a PA-001 test value and its source string says so. Masses that the case gives through
geometry and density are formed here with exact rational arithmetic and handed to the module as the nearest float.

``exact_reference`` evaluates T5 again with ``fractions.Fraction`` from the decimal inputs, independent of the
thermal package; ``hand_calc_table.json`` holds the reviewed hand calculation of the same inputs.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
THERMAL_DIR = HERE.parents[2]
ISS_SPEC_PATH = THERMAL_DIR / "iss_fem" / "model" / "iss_spec.py"
HAND_CALC_PATH = HERE / "hand_calc_table.json"

NODES = ("S", "J", "C", "B", "D", "R")
PATHS = ("SR", "JC", "CR", "BR", "DR")

# Values stated in the PA-001 case inputs (test report CASES['PA-001'].input).
CASE_DESIGN_EXAMPLE = {"mass_kg": "1", "cp_J_kgK": "1000"}
CASE_MBSU = {"size_m": ("0.94", "0.84", "0.51"), "density_kg_m3": "300", "cp_J_kgK": "900"}
CASE_PANEL = {"areal_mass_kg_m2": "8", "cp_J_kgK": "900"}
# EATCS radiator panel of iss_spec.HRS: width 3.4 m, length (21.99 m - 7 x 0.05 m) / 8 = 2.705 m.
PANEL_WIDTH_M = "3.4"
PANEL_LENGTH_M = "2.705"

OVERRIDE_SOURCE = "PA-001 scene override: battery revision B cells and a thinner BR interface filler"


def q(value: Any) -> Fraction:
    """Exact rational value of a decimal input (a float is read through its shortest decimal repr)."""

    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError(value)
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(repr(value))
    return Fraction(str(value))


def load_iss_spec():
    """Load the ISS thermal FE parameter table as data (it only imports math)."""

    spec = importlib.util.spec_from_file_location("pa001_iss_spec", ISS_SPEC_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def iss_table_values() -> dict[str, Any]:
    """MBSU block and radiator panel values as read from iss_spec.py."""

    iss = load_iss_spec()
    boxes = [box for box in iss.ORU_BOXES if box[0].startswith("MBSU")]
    oru = iss.MATERIALS["oru_eq"]
    panel = iss.MATERIALS["hrs_pan"]
    hrs = iss.HRS
    length_total = abs(hrs["x_tip"] - hrs["x_root"])
    panel_length = (length_total - (hrs["n_panels"] - 1) * hrs["gap"]) / hrs["n_panels"]
    return {
        "mbsu_names": [box[0] for box in boxes],
        "mbsu_sizes_m": [tuple(box[1]) for box in boxes],
        "mbsu_material_classes": list(oru["classes"]),
        "mbsu_density_kg_m3": oru["rho"],
        "mbsu_cp_J_kgK": oru["cp"],
        "panel_density_kg_m3": panel["rho"],
        "panel_thickness_m": panel["t"],
        "panel_areal_mass_kg_m2": panel["rho"] * panel["t"],
        "panel_cp_J_kgK": panel["cp"],
        "panel_width_m": hrs["width"],
        "panel_length_m": panel_length,
        "z93_optics": dict(iss.OPTICS["z93"]),
    }


def mbsu_mass_exact() -> Fraction:
    a, b, c = (q(v) for v in CASE_MBSU["size_m"])
    return a * b * c * q(CASE_MBSU["density_kg_m3"])


def panel_area_exact() -> Fraction:
    return q(PANEL_WIDTH_M) * q(PANEL_LENGTH_M)


def panel_mass_exact() -> Fraction:
    return q(CASE_PANEL["areal_mass_kg_m2"]) * panel_area_exact()


def _material(material_id: str, mass_kg: Any, cp: Any, source: str) -> dict[str, Any]:
    return {"material_id": material_id, "mass_kg": float(q(mass_kg)), "cp_J_kgK": float(q(cp)), "source": source}


def _surface(surface_id: str, area: Any, normal, alpha: float, eps: float, source: str) -> dict[str, Any]:
    return {
        "surface_id": surface_id,
        "area_m2": float(q(area)),
        "normal_body": [float(v) for v in normal],
        "absorptivity": alpha,
        "emissivity": eps,
        "source": source,
    }


def baseline_components() -> list[dict[str, Any]]:
    """The asset parameter sets of the seven Sat01 instances, as fresh mutable records."""

    tv = "PA-001 test value"
    iss_box = "ISS FE parameter table iss_spec.py: ORU_BOXES MBSU 0.94 m x 0.84 m x 0.51 m, oru_eq rho 300 kg/m3"
    iss_panel = "ISS FE parameter table iss_spec.py: hrs_pan rho 3200 kg/m3 x t 2.5 mm = 8 kg/m2, HRS panel 3.4 m x 2.705 m"
    return [
        {
            "instance_id": "SolarArray01",
            "node_id": "S",
            "asset_id": "pa001.solar_array_panel",
            "asset_version": "1.2.0",
            "materials": [
                _material("sa01_cells_coverglass", "0.62", "712", f"{tv}: cells with coverglass"),
                _material("sa01_cfrp_substrate", "1.35", "1050", f"{tv}: CFRP honeycomb substrate"),
                _material("sa01_hinge_bracket", "0.21", "896", f"{tv}: Al 6061 hinge bracket"),
            ],
            "surfaces": [
                _surface("sa01_front", "1.2", (0.6, 0.0, 0.8), 0.91, 0.85, f"{tv}: cell side"),
                _surface("sa01_back", "1.2", (-0.6, 0.0, -0.8), 0.30, 0.80, f"{tv}: substrate side"),
            ],
            "temperature_range_K": [173.15, 393.15],
            "ports": ["P_pv_W"],
        },
        {
            "instance_id": "Compute01",
            "node_id": "J",
            "asset_id": "pa001.compute_board",
            "asset_version": "2.0.1",
            "materials": [
                _material(
                    "cb01_design_example",
                    CASE_DESIGN_EXAMPLE["mass_kg"],
                    CASE_DESIGN_EXAMPLE["cp_J_kgK"],
                    "design report 4.5 example: 1 kg of material at 1000 J/(kg K)",
                ),
            ],
            "surfaces": [],
            "temperature_range_K": [233.15, 358.15],
            "ports": ["P_load_W"],
        },
        {
            "instance_id": "ColdPlate01",
            "node_id": "C",
            "asset_id": "pa001.cold_plate",
            "asset_version": "1.0.0",
            "materials": [
                _material("cp01_al6061_plate", "2.4", "896", f"{tv}: Al 6061 plate"),
                _material("cp01_coolant_water", "0.18", "4180", f"{tv}: coolant inventory in the plate"),
            ],
            "surfaces": [],
            "temperature_range_K": [253.15, 343.15],
            "ports": [],
        },
        {
            "instance_id": "Battery01",
            "node_id": "B",
            "asset_id": "pa001.battery_pack",
            "asset_version": "1.1.0",
            "materials": [
                _material("bt01_li_ion_cells", "3.2", "1040", f"{tv}: lithium-ion cells"),
                _material("bt01_al_case", "0.65", "896", f"{tv}: aluminium case"),
            ],
            "surfaces": [],
            "temperature_range_K": [253.15, 333.15],
            "ports": ["Q_B_W"],
        },
        {
            "instance_id": "Controller01",
            "node_id": "D",
            "asset_id": "pa001.power_controller",
            "asset_version": "1.0.0",
            "materials": [
                _material("pc01_al_chassis", "0.95", "896", f"{tv}: aluminium chassis"),
                _material("pc01_fr4_boards", "0.30", "1150", f"{tv}: FR4 boards"),
            ],
            "surfaces": [],
            "temperature_range_K": [233.15, 358.15],
            "ports": [],
        },
        {
            "instance_id": "PDU01",
            "node_id": "D",
            "asset_id": "pa001.mbsu_block",
            "asset_version": "3.0.2",
            "materials": [
                _material("pdu01_mbsu_block", mbsu_mass_exact(), CASE_MBSU["cp_J_kgK"], f"{iss_box}, cp 900 J/(kg K)"),
            ],
            "surfaces": [],
            "temperature_range_K": [233.15, 343.15],
            "ports": ["Q_D_W"],
        },
        {
            "instance_id": "Radiator01",
            "node_id": "R",
            "asset_id": "pa001.radiator_panel",
            "asset_version": "1.4.0",
            "materials": [
                _material("rd01_hrs_panel", panel_mass_exact(), CASE_PANEL["cp_J_kgK"], f"{iss_panel}, cp 900 J/(kg K)"),
            ],
            "surfaces": [
                _surface("rd01_front", panel_area_exact(), (0.0, 1.0, 0.0), 0.20, 0.91,
                         "ISS FE parameter table iss_spec.py: OPTICS z93 nominal aged"),
                _surface("rd01_back", panel_area_exact(), (0.0, -1.0, 0.0), 0.20, 0.91,
                         "ISS FE parameter table iss_spec.py: OPTICS z93 nominal aged"),
            ],
            "temperature_range_K": [173.15, 343.15],
            "ports": [],
        },
    ]


def baseline_connections() -> list[dict[str, Any]]:
    """The five path records: three solid paths, a heat-pipe and a liquid-cooling equivalent."""

    tv = "PA-001 test value"
    return [
        {"path": "SR", "length_m": 0.12, "conductivity_W_mK": 167.0, "area_m2": 4.0e-4,
         "contact_resistance_K_W": 0.35, "source": f"{tv}: Al 6061-T6 hinge bracket and its bolted interface"},
        {"path": "JC", "length_m": 0.002, "conductivity_W_mK": 3.0, "area_m2": 0.0064,
         "contact_resistance_K_W": 0.05, "source": f"{tv}: 2 mm gap pad between board and cold plate"},
        {"path": "CR", "equivalent_total_resistance_K_W": 0.085, "includes_contact": True,
         "source": f"{tv}: heat-pipe equivalent total from a thermal vacuum test, contact included"},
        {"path": "BR", "length_m": 0.08, "conductivity_W_mK": 167.0, "area_m2": 0.0025,
         "contact_resistance_K_W": 0.12, "source": f"{tv}: battery mounting plate and filler"},
        {"path": "DR", "equivalent_total_resistance_K_W": 0.045, "includes_contact": False,
         "contact_resistance_K_W": 0.021, "source": f"{tv}: liquid-cooling loop equivalent from a loop test, contact separate"},
    ]


def override_set() -> dict[str, Any]:
    """One component material mass and one connection contact resistance changed by the scene."""

    return {
        "components": {"Battery01": {"materials": {"bt01_li_ion_cells": {"mass_kg": 3.45}}}},
        "connections": {"BR": {"contact_resistance_K_W": 0.08}},
        "source": OVERRIDE_SOURCE,
    }


def fresh_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return baseline_components(), baseline_connections()


def apply_overrides_exact(components, connections, overrides) -> tuple[list[dict], list[dict]]:
    """Resolve the scene overrides on deep copies (reference side, written from design 5.2 and 9.4)."""

    components = copy.deepcopy(components)
    connections = copy.deepcopy(connections)
    if overrides:
        by_instance = {c["instance_id"]: c for c in components}
        for instance_id, change in (overrides.get("components") or {}).items():
            component = by_instance[instance_id]
            for material_id, fields in (change.get("materials") or {}).items():
                material = next(m for m in component["materials"] if m["material_id"] == material_id)
                material.update(fields)
            for surface_id, fields in (change.get("surfaces") or {}).items():
                surface = next(s for s in component["surfaces"] if s["surface_id"] == surface_id)
                surface.update(fields)
        by_path = {c["path"]: c for c in connections}
        for path, fields in (overrides.get("connections") or {}).items():
            by_path[path].update(fields)
    return components, connections


def exact_reference(components, connections, overrides=None) -> dict[str, Any]:
    """T5 evaluated with exact rationals: C_i = sum m c_p, R = l/(k A) + R_contact or the equivalent total."""

    components, connections = apply_overrides_exact(components, connections, overrides)
    capacitance = {node: Fraction(0) for node in NODES}
    portions: dict[tuple[str, str], Fraction] = {}
    for component in components:
        for material in component["materials"]:
            value = q(material["mass_kg"]) * q(material["cp_J_kgK"])
            portions[(component["instance_id"], material["material_id"])] = value
            capacitance[component["node_id"]] += value
    resistance: dict[str, Fraction] = {}
    for record in connections:
        if "equivalent_total_resistance_K_W" in record:
            total = q(record["equivalent_total_resistance_K_W"])
            if record["includes_contact"]:
                resistance[record["path"]] = total
            else:
                resistance[record["path"]] = total + q(record["contact_resistance_K_W"])
        else:
            conduction = q(record["length_m"]) / (q(record["conductivity_W_mK"]) * q(record["area_m2"]))
            resistance[record["path"]] = conduction + q(record["contact_resistance_K_W"])
    return {"C_J_K": capacitance, "R_K_W": resistance, "portions": portions}


def load_hand_calc_table() -> dict[str, Any]:
    return json.loads(HAND_CALC_PATH.read_text(encoding="utf-8"))


def table_fraction(text: str) -> Fraction:
    """Read a table entry written as a decimal or as an exact ratio 'a/b'."""

    if not re.fullmatch(r"\s*-?\d+(\.\d+)?(\s*/\s*\d+)?\s*", text):
        raise ValueError(f"hand calculation entry {text!r} is not a decimal or a ratio")
    return Fraction(text.replace(" ", ""))
