"""Independent reference calculations of test case DM-001.

Written from the thermal design report (1.4 node order, 3.2 package tree, 4.2 T2, 4.3 T3 and its battery example,
4.4 T4 with table 5, 4.5 T5, 5.1 table 6, appendix A), plus two name lists for the export checks of step 6: the
public names of the Power design report appendix A and the error and warning classes that Thermal/IMPLEMENTATION.md
allows ``thermal/__init__.py`` to export beyond appendix A. Nothing here imports the ``thermal`` package or
``sdtwin_sim``: the orders, the Stefan-Boltzmann constant and the equations are typed in from the report, scalar
Python arithmetic is used instead of the module's array code, and the attitude rotation is an explicit quaternion
formula instead of SciPy's Rotation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# Design 1.4 and table 6: temperature order, path order and environment/radiation order.
NODES = ("S", "J", "C", "B", "D", "R")
PATHS = ("SR", "JC", "CR", "BR", "DR")
PATH_ENDS = {"SR": ("S", "R"), "JC": ("J", "C"), "CR": ("C", "R"), "BR": ("B", "R"), "DR": ("D", "R")}
EXPOSED = ("S", "R")
# Design table 5.
SIGMA = 5.670374419e-8
# Design table 6 field lists, in the order of the table.
TABLE6_FIELDS = {
    "ThermalParameters": ("C_J_K", "R_K_W", "surfaces", "instance_map", "provenance"),
    "ThermalState": ("run_id", "time_s", "temperature_K"),
    "ThermalInputs": ("run_id", "time_s", "environment", "P_pv_W", "P_load_W", "Q_B_W", "Q_D_W"),
    "ThermalEvaluation": ("run_id", "time_s", "dT_dt_K_s", "q_W", "Q_env_W", "Q_emit_W", "T_B_K", "T_J_K"),
}
TABLE6_SHAPES = {
    "C_J_K": (6,), "R_K_W": (5,), "temperature_K": (6,), "dT_dt_K_s": (6,), "q_W": (5,), "Q_env_W": (2,),
    "Q_emit_W": (2,),
}
# Design 5.1: fields of every surfaces record.
SURFACE_FIELDS = ("surface_id", "node_id", "area_m2", "normal_body", "absorptivity", "emissivity")
# Design 3.2 and 5.1: instances of each node (D shared by Controller01 and PDU01) and the four port instances.
NODE_INSTANCES = {
    "S": {"SolarArray01"}, "J": {"Compute01"}, "C": {"ColdPlate01"}, "B": {"Battery01"},
    "D": {"Controller01", "PDU01"}, "R": {"Radiator01"},
}
PORT_INSTANCES = {"P_pv_W": "SolarArray01", "P_load_W": "Compute01", "Q_B_W": "Battery01", "Q_D_W": "PDU01"}
# Design 3.2 package tree and appendix A.
APPENDIX_A_TYPES = ("ThermalParameters", "ThermalState", "ThermalInputs", "ThermalEvaluation")
APPENDIX_A_FUNCTIONS = {
    "assemble_thermal_parameters": "parameters",
    "prepare_surface_environment": "environment",
    "calculate_surface_heat": "environment",
    "calculate_heat_flows": "model",
    "thermal_derivative": "model",
}
PACKAGE_FILES = ("__init__.py", "types.py", "parameters.py", "environment.py", "model.py")
# Thermal design appendix A, last row: the Power interface that the thermal module references and does not define.
POWER_INTERFACE_NAMES = ("PowerInputs", "PowerState", "PowerResult", "solve_power_allocation")
# Power design report (Power/SDTwin_Power_Design_Report_CN.docx) appendix A table A-1: all 13 public Power names.
POWER_APPENDIX_A_NAMES = (
    "PowerParameters", "PowerEnvironment", "PowerInputs", "PowerState", "SolarPowerResult", "BatteryResponse",
    "PowerResult", "PowerEvent", "load_power_parameters", "battery_response", "solar_power", "solve_power_allocation",
    "apply_power_event",
)
# Thermal/IMPLEMENTATION.md: "__init__.py exports the 4 data types and 5 functions of design appendix A, plus the
# error classes", and its types.py section lists these four under "Errors".
CONTRACT_ERROR_CLASSES = ("ThermalError", "ThermalConfigurationError", "ThermalInputError", "ThermalRangeWarning")
# Design 4.3 battery example: C_B = 1000 J/K, T_B = 303 K, T_R = 300 K, R_BR = 0.5 K/W and Q_B = 10 W give
# q_BR = 3/0.5 = 6 W and dT_B/dt = 4/1000 = 0.004 K/s. The example has no other worked value.
DESIGN_43_BATTERY_EXAMPLE = {
    "C_B_J_K": 1000.0, "T_B_K": 303.0, "T_R_K": 300.0, "R_BR_K_W": 0.5, "Q_B_W": 10.0, "q_BR_W": 6.0,
    "dT_B_dt_K_s": 0.004,
}


def load_scenario() -> dict[str, Any]:
    return json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ T5 (design 4.5)


def capacitance_by_node(components: list[dict[str, Any]]) -> dict[str, float]:
    """C_i = sum over material portions of m c_p, grouped by the node of the owning component."""

    totals = {node: 0.0 for node in NODES}
    for component in components:
        for material in component["materials"]:
            totals[component["node_id"]] += float(material["mass_kg"]) * float(material["cp_J_kgK"])
    return totals


def resistance_by_path(connections: list[dict[str, Any]]) -> dict[str, float]:
    """R_ij = l / (kappa A) + R_contact, or the equivalent total (plus the contact part when it is not included)."""

    result = {}
    for connection in connections:
        if "equivalent_total_resistance_K_W" in connection:
            value = float(connection["equivalent_total_resistance_K_W"])
            if not connection["includes_contact"]:
                value += float(connection["contact_resistance_K_W"])
        else:
            value = float(connection["length_m"]) / (
                float(connection["conductivity_W_mK"]) * float(connection["area_m2"])
            ) + float(connection["contact_resistance_K_W"])
        result[connection["path"]] = value
    return result


# ------------------------------------------------------------------------------------------ geometry (design 5.3)


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def rotate(quaternion_xyzw: list[float], vector: list[float]) -> tuple[float, float, float]:
    """Active rotation of ``vector`` by the unit quaternion (x, y, z, w): v' = v + w t + q x t with t = 2 q x v."""

    x, y, z, w = (float(value) for value in quaternion_xyzw)
    q = (x, y, z)
    v = tuple(float(value) for value in vector)
    t = tuple(2.0 * value for value in _cross(q, v))
    u = _cross(q, t)
    return (v[0] + w * t[0] + u[0], v[1] + w * t[1] + u[1], v[2] + w * t[2] + u[2])


def sun_direction(position_m: list[float], sun_position_m: list[float]) -> tuple[float, float, float]:
    d = [float(s) - float(p) for s, p in zip(sun_position_m, position_m)]
    norm = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    return (d[0] / norm, d[1] / norm, d[2] / norm)


def cos_incidence(orbit_input: dict[str, Any], normal_body: list[float]) -> float:
    n = rotate(orbit_input["quaternion_xyzw"], normal_body)
    u = sun_direction(orbit_input["position_m"], orbit_input["sun_position_m"])
    return n[0] * u[0] + n[1] * u[1] + n[2] * u[2]


def surfaces_in_asset_order(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Surface records with their node, in component order and then surface order (the asset surface order)."""

    records = []
    for component in components:
        for surface in component.get("surfaces", []):
            records.append({**surface, "node_id": component["node_id"]})
    return records


# --------------------------------------------------------------------------------------- T2, T3, T4 (design 4.2 to 4.4)


def surface_heat(
    temperature: dict[str, float],
    surfaces: list[dict[str, Any]],
    G_W_m2: float,
    cosines: list[float],
    albedo: list[float],
    infrared: list[float],
) -> tuple[dict[str, float], dict[str, float], float]:
    """T4: Q_env and Q_emit per exposed node and the direct sunlight absorbed by the S surfaces."""

    q_env = {node: 0.0 for node in EXPOSED}
    q_emit = {node: 0.0 for node in EXPOSED}
    direct_s = 0.0
    for surface, cosine, g_alb, g_ir in zip(surfaces, cosines, albedo, infrared):
        node = surface["node_id"]
        area = float(surface["area_m2"])
        alpha = float(surface["absorptivity"])
        eps = float(surface["emissivity"])
        g_sun = G_W_m2 * max(0.0, cosine)
        q_env[node] += area * (alpha * (g_sun + g_alb) + eps * g_ir)
        q_emit[node] += eps * SIGMA * area * temperature[node] ** 4
        if node == "S":
            direct_s += area * alpha * g_sun
    return q_env, q_emit, direct_s


def heat_flows(temperature: dict[str, float], resistance: dict[str, float]) -> dict[str, float]:
    """T2: q_ij = (T_i - T_j) / R_ij, positive from the first node of the path name to the second."""

    return {path: (temperature[a] - temperature[b]) / resistance[path] for path, (a, b) in PATH_ENDS.items()}


def derivatives(
    temperature: dict[str, float],
    capacitance: dict[str, float],
    resistance: dict[str, float],
    q_env: dict[str, float],
    q_emit: dict[str, float],
    ports: dict[str, float],
) -> dict[str, float]:
    """T3, node by node, divided by the capacitances."""

    q = heat_flows(temperature, resistance)
    net = {
        "S": q_env["S"] - ports["P_pv_W"] - q["SR"] - q_emit["S"],
        "J": ports["P_load_W"] - q["JC"],
        "C": q["JC"] - q["CR"],
        "B": ports["Q_B_W"] - q["BR"],
        "D": ports["Q_D_W"] - q["DR"],
        "R": q["SR"] + q["CR"] + q["BR"] + q["DR"] + q_env["R"] - q_emit["R"],
    }
    return {node: net[node] / capacitance[node] for node in NODES}


def make_rhs(scenario: dict[str, Any]):
    """Right-hand side f(t, T) of the thermal-only coupled case with constant environment and prescribed ports."""

    components = scenario["components"]
    capacitance = capacitance_by_node(components)
    resistance = resistance_by_path(scenario["connections"])
    surfaces = surfaces_in_asset_order(components)
    orbit = scenario["orbit_input"]
    cosines = [cos_incidence(orbit, surface["normal_body"]) for surface in surfaces]
    albedo = [scenario["earth_flux_W_m2"]["albedo"][surface["surface_id"]] for surface in surfaces]
    infrared = [scenario["earth_flux_W_m2"]["infrared"][surface["surface_id"]] for surface in surfaces]
    ports = dict(scenario["ports_W"])
    G = float(orbit["G_W_m2"])

    def rhs(_t: float, y: Any) -> list[float]:
        temperature = {node: float(value) for node, value in zip(NODES, y)}
        q_env, q_emit, _ = surface_heat(temperature, surfaces, G, cosines, albedo, infrared)
        rates = derivatives(temperature, capacitance, resistance, q_env, q_emit, ports)
        return [rates[node] for node in NODES]

    return rhs
