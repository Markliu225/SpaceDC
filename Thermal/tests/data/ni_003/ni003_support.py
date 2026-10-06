"""NI-003 support code: hand calculation, independent USD text parse, scene file helpers and the two-satellite runs.

Nothing in the reference functions calls the code under test. ``reference_values`` evaluates the face areas of the
documented part boxes and both lines of T5 from ``hand_calc.json``; ``parse_usda`` reads ``metersPerUnit``, extents
and transform ops from the ``.usda`` text with regular expressions; ``quaternion_matrix`` is the textbook active
rotation matrix of a unit quaternion in xyzw order; ``reference_display_bbox`` builds the world-aligned display box
of an instance from those three pieces and the scene's display scale.

The run helpers build one satellite from its scene file (``sdtwin_sim.scene.assemble_scene`` and
``thermal.assemble_thermal_parameters``), give the Power stand-in the Power capabilities of the same scene instances
and run ``sdtwin_sim.coupled.run_coupled`` over one orbit. ``run_alone.py`` calls :func:`run_satellite` in a fresh
interpreter so that a satellite can be rerun with nothing else in the process.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
THERMAL_DIR = HERE.parents[2]
DATA_DIR = HERE.parent
SIMREADY = DATA_DIR / "simready"
SCENES = HERE / "scenes"
ASSETS = HERE / "assets"
GEOMETRY = HERE / "geometry"
SAT01_SCENE = SIMREADY / "sat01_scene.json"
SAT02_SCENE = SCENES / "sat02_scene.json"

NODES = ("S", "J", "C", "B", "D", "R")
PATHS = ("SR", "JC", "CR", "BR", "DR")
PORTS = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")
FARADAY_C_MOL = 96485.33212

# Two-satellite scenario: circular 400 km orbit at 51.6 deg starting at true anomaly 150 deg (in the Earth shadow, so
# one run holds an eclipse exit and an eclipse entry), sun pointing with +X tilted 45 deg from the Sun direction
# towards the orbit plane, Earth albedo 0.30 and OLR 237 W/m^2 (illustrative mean values), 5600 s, about one orbit.
# The phase keeps both batteries inside their declared range [263.15, 318.15] K and the stand-in range
# [253.15, 333.15] K and away from both lithium bounds, so no Power event or device boundary is needed.
EPOCH = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
SEMI_MAJOR_AXIS_M = 6378137.0 + 400.0e3
INCLINATION_DEG = 51.6
TRUE_ANOMALY_DEG = 150.0
TILT_DEG = 45.0
ALBEDO = 0.30
OLR_W_M2 = 237.0
SOLAR_CONSTANT_W_M2 = 1361.0
EARTH_FLUX_RESOLUTION = (24, 48)
DURATION_S = 5600.0
RUNS = {
    "Sat01": {"scene": SAT01_SCENE, "run_id": "ni003-sat01", "instance_id": "Sat01"},
    "Sat02": {"scene": SAT02_SCENE, "run_id": "ni003-sat02", "instance_id": "Sat02"},
}


# ------------------------------------------------------------------------------------------------ hand calculation


def load_hand_calc() -> dict:
    return json.loads((HERE / "hand_calc.json").read_text(encoding="utf-8"))


def face_area(size_m: list[float], face: str) -> float:
    """Area of a box face: the product of the two sizes across the face normal axis."""

    axis = "XYZ".index(face[1])
    others = [float(v) for k, v in enumerate(size_m) if k != axis]
    return others[0] * others[1]


def reference_values(table: dict) -> dict:
    """Masses, node capacitances (T5 line 1), areas, normals, optics and resistances (T5 line 2) by hand formulas."""

    parts = table["parts"]
    masses: dict[str, float] = {}
    material_cp: dict[str, float] = {}
    node_mass = {n: 0.0 for n in NODES}
    capacitance = {n: 0.0 for n in NODES}
    areas: dict[str, float] = {}
    normals: dict[str, list[float]] = {}
    optics: dict[str, tuple[float, float]] = {}
    for iid, inst in table["instances"].items():
        geometry = inst["geometry"]
        for material in inst["materials"]:
            if "mass_kg" in material:
                mass = float(material["mass_kg"])
            else:
                sx, sy, sz = parts[f"{geometry}/{material['part']}"]["size_m"]
                mass = float(material["density_kg_m3"]) * sx * sy * sz * float(material["solid_fraction"])
            key = f"{iid}/{material['material_id']}"
            masses[key] = mass
            material_cp[key] = float(material["cp_J_kgK"])
            node_mass[inst["node"]] += mass
            capacitance[inst["node"]] += mass * float(material["cp_J_kgK"])
        for surface in inst["surfaces"]:
            key = f"{iid}/{surface['surface_id']}"
            areas[key] = face_area(parts[f"{geometry}/{surface['part']}"]["size_m"], surface["face"])
            normals[key] = [float(v) for v in surface["normal_body"]]
            optics[key] = (float(surface["absorptivity"]), float(surface["emissivity"]))
    resistance: dict[str, float] = {}
    for path, c in table["connections"].items():
        if "equivalent_total_resistance_K_W" in c:
            extra = 0.0 if c["includes_contact"] else float(c["contact_resistance_K_W"])
            resistance[path] = float(c["equivalent_total_resistance_K_W"]) + extra
        else:
            resistance[path] = float(c["length_m"]) / (float(c["conductivity_W_mK"]) * float(c["area_m2"])) + float(
                c["contact_resistance_K_W"])
    return {"masses": masses, "cp": material_cp, "node_mass": node_mass, "capacitance": capacitance,
            "areas": areas, "normals": normals, "optics": optics, "resistance": resistance,
            "total_mass": math.fsum(masses.values())}


def rel_err(value: float, reference: float) -> float:
    value, reference = float(value), float(reference)
    if not math.isfinite(value):
        return math.inf
    if reference == 0.0:
        return abs(value)
    return abs(value - reference) / abs(reference)


# ---------------------------------------------------------------------------------------------------- USD text


_EXTENT = re.compile(r"float3\[\]\s+extent\s*=\s*\[\(([^)]*)\),\s*\(([^)]*)\)\]")
_VEC3 = r"\(([^)]*)\)"


def _floats(text: str) -> list[float]:
    return [float(v) for v in text.split(",")]


def parse_usda(path: str | Path) -> dict:
    """metersPerUnit, defaultPrim, the extents of each Mesh and the transform ops written in a simple .usda file."""

    text = Path(path).read_text(encoding="utf-8")
    found = re.search(r"metersPerUnit\s*=\s*([-0-9.eE+]+)", text)
    default = re.search(r'defaultPrim\s*=\s*"(\w+)"', text)
    meshes: dict[str, dict] = {}
    root_ops: dict[str, Any] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r'def\s+Mesh\s+"(\w+)"', stripped)
        if match:
            current = match.group(1)
            meshes[current] = {}
            continue
        target = meshes[current] if current else root_ops
        match = _EXTENT.search(stripped)
        if match:
            target["extent"] = [_floats(match.group(1)), _floats(match.group(2))]
        match = re.match(r"double\s+xformOp:rotateZ\s*=\s*([-0-9.eE+]+)", stripped)
        if match:
            target["rotate_z_deg"] = float(match.group(1))
        match = re.match(r"double3\s+xformOp:translate\s*=\s*" + _VEC3, stripped)
        if match:
            target["translate"] = _floats(match.group(1))
        match = re.match(r"double3\s+xformOp:scale\s*=\s*" + _VEC3, stripped)
        if match:
            target["scale"] = _floats(match.group(1))
    return {"meters_per_unit": float(found.group(1)) if found else None,
            "default_prim": default.group(1) if default else None, "root_ops": root_ops, "meshes": meshes}


def quaternion_matrix(q_xyzw: list[float]) -> np.ndarray:
    """Active rotation matrix of a unit quaternion (x, y, z, w)."""

    x, y, z, w = (float(v) for v in q_xyzw)
    return np.array([
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
    ])


def asset_box_m(usd: dict) -> np.ndarray:
    """Size in metres of the asset-axis box that holds every mesh after its own transform ops."""

    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for mesh in usd["meshes"].values():
        extent = np.array(mesh["extent"], dtype=float)
        corners = np.array([[x, y, z] for x in extent[:, 0] for y in extent[:, 1] for z in extent[:, 2]])
        if "rotate_z_deg" in mesh:
            a = math.radians(mesh["rotate_z_deg"])
            rz = np.array([[math.cos(a), -math.sin(a), 0.0], [math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]])
            corners = corners @ rz.T
        if "translate" in mesh:
            corners = corners + np.array(mesh["translate"], dtype=float)
        lo = np.minimum(lo, corners.min(axis=0))
        hi = np.maximum(hi, corners.max(axis=0))
    return (hi - lo) * float(usd["meters_per_unit"])


def reference_display_bbox(usd: dict, quaternion_xyzw: list[float], display_scale: list[float]) -> np.ndarray:
    """World-aligned display box size: the asset box scaled by the display scale in asset axes, then mounted."""

    size = asset_box_m(usd) * np.asarray(display_scale, dtype=float)
    return np.abs(quaternion_matrix(quaternion_xyzw)) @ size


# ------------------------------------------------------------------------------------------------ scene files


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def referenced_files(scene_path: str | Path) -> list[Path]:
    """The scene file, every asset file it references and every geometry file those assets reference."""

    scene_path = Path(scene_path).resolve()
    files = [scene_path]
    for item in read_json(scene_path)["instances"]:
        asset_path = (scene_path.parent / item["asset_ref"]).resolve()
        if asset_path not in files:
            files.append(asset_path)
        geometry = (asset_path.parent / read_json(asset_path)["geometry_uri"]).resolve()
        if geometry not in files:
            files.append(geometry)
    return files


def folder_listing(folder: Path) -> list[tuple[str, int]]:
    return sorted((p.name, p.stat().st_size) for p in folder.iterdir() if p.is_file())


# ------------------------------------------------------------------------------------------- two-satellite runs


def electrode_charge_C(electrode: dict) -> float:
    """Q = active fraction x electrode area x thickness x c_max x F (Power design P5 notation), in C."""

    return (float(electrode["active_fraction"]) * float(electrode["electrode_area_m2"])
            * float(electrode["thickness_m"]) * float(electrode["c_max_mol_m3"]) * FARADAY_C_MOL)


def power_setup(assembly: Any, scene_path: str | Path, run_id: str, instance_id: str,
                links_override: dict | None = None) -> tuple[Any, Any, float, dict]:
    """Power stand-in parameters and initial state of one satellite from the Power capabilities of its scene.

    The array area, efficiency and normal, the series and parallel counts and the PDU efficiency come from the scene
    instances; the links come from their Power roles (``links_override`` replaces them for the mismatch check); the
    initial lithium fractions and load flags from the scene initial state and the battery temperature from the scene's
    thermal initial state (Thermal owns it). The Power loader rejects an initial lithium inventory incompatible
    with the cell parameter pack; this helper never replaces the scene's lithium fractions.
    """

    from sdtwin_sim import power_stand_in as ps

    scene = read_json(scene_path)
    instances = assembly.power["instances"]
    roles = {entry["role"]: iid for iid, entry in instances.items()}
    links = {"P_pv_W": roles["solar_array"], "P_load_W": roles["load"], "Q_B_W": roles["battery"],
             "Q_D_W": roles["pdu"]}
    solar, battery = instances[roles["solar_array"]], instances[roles["battery"]]
    pdu, load = instances[roles["pdu"]], instances[roles["load"]]
    asset_record, scene_record = ps.example_power_records()
    scene_record["instance_id"] = instance_id
    scene_record["links"] = dict(links if links_override is None else links_override)
    scene_record["overrides"] = {
        "solar": {"area_m2": float(solar["parameter_set"]["cell_area_m2"]),
                  "efficiency": float(solar["parameter_set"]["efficiency"]),
                  "normal_body": [float(v) for v in solar["surface"]["normal_body"]]},
        "battery": {"N_s": int(battery["parameter_set"]["N_s"]), "N_p": int(battery["parameter_set"]["N_p"])},
        "pdu": {"eta_D": float(pdu["parameter_set"]["eta_D"])},
        "source": f"{assembly.scene_id} Power capabilities of SolarArray01, Battery01 and PDU01",
    }
    initial_power = scene["initial_state"]["power"]
    battery_state = initial_power[roles["battery"]]
    load_state = initial_power[roles["load"]]
    x_n = float(battery_state["x_n"])
    x_p_scene = float(battery_state["x_p"])
    cell = asset_record["battery"]
    q_n = electrode_charge_C(cell["electrodes"]["n"])
    q_p = electrode_charge_C(cell["electrodes"]["p"])
    reference = cell["x_n_100"] * q_n + cell["x_p_100"] * q_p
    inventory_rel = abs(x_n * q_n + x_p_scene * q_p - reference) / reference
    rtol = float(scene_record["numerics"]["inventory_rtol"])
    # Invalid scene values must be rejected by the Power parameter loader, never repaired here.
    x_p = x_p_scene
    t_b = float(assembly.initial_temperature_K[NODES.index("B")])
    scene_record["initial_state"].update(time_s=0.0, x_n=x_n, x_p=x_p, T_B_K=t_b,
                                         load_connected=bool(load_state["load_connected"]),
                                         trip_latched=bool(load_state["trip_latched"]))
    parameters = ps.load_power_parameters(asset_record, scene_record)
    state = ps.power_state_from_scene(scene_record, run_id)
    request = float(load["parameter_set"]["rated_power_W"])
    info = {"x_n": x_n, "x_p_scene": x_p_scene, "x_p_used": x_p, "inventory_rel_diff_scene": inventory_rel,
            "x_p_replaced": x_p != x_p_scene, "T_B_K": t_b, "links": links, "request_W": request,
            "Q_n_C": q_n, "Q_p_C": q_p, "N_s": scene_record["overrides"]["battery"]["N_s"],
            "N_p": scene_record["overrides"]["battery"]["N_p"]}
    return parameters, state, request, info


def environment_provider(run_id: str, parameters: Any, duration_s: float) -> Any:
    from ntu_space_dynamics import (
        AttitudeEphemeris, ClassicalElements, OrbitState, TwoBodyPropagator, oe_to_rv, sun_position_ephemeris,
    )
    from ntu_space_dynamics.time import time_grid
    from scipy.spatial.transform import Rotation

    from sdtwin_sim import coupled as cp

    elements = ClassicalElements.from_degrees(SEMI_MAJOR_AXIS_M, 0.0, INCLINATION_DEG, 0.0, 0.0, TRUE_ANOMALY_DEG,
                                              epoch=EPOCH)
    r0, v0 = oe_to_rv(elements)
    times = time_grid(EPOCH, EPOCH + timedelta(seconds=duration_s + 300.0), 30.0)
    ephemeris = TwoBodyPropagator().propagate(OrbitState(EPOCH, r0, v0, "GCRS"), times)
    sun = np.array([sun_position_ephemeris(t) for t in times])
    quaternions = []
    tilt = math.radians(TILT_DEG)
    for r, v, s in zip(ephemeris.positions_m, ephemeris.velocities_m_s, sun):
        u = (s - r) / np.linalg.norm(s - r)
        h = np.cross(r, v)
        z = h - np.dot(h, u) * u
        z /= np.linalg.norm(z)
        w = np.cross(z, u)
        x = math.cos(tilt) * u - math.sin(tilt) * w
        quaternions.append(Rotation.from_matrix(np.column_stack([x, np.cross(z, x), z])).as_quat())
    attitude = AttitudeEphemeris(ephemeris.elapsed_seconds, np.array(quaternions), np.zeros((len(times), 3)))
    earth = cp.EarthFluxModel(albedo=ALBEDO, olr_W_m2=OLR_W_M2, solar_constant_W_m2=SOLAR_CONSTANT_W_M2,
                              resolution=EARTH_FLUX_RESOLUTION)
    return cp.EnvironmentProvider.from_orbit(run_id=run_id, epoch=EPOCH, parameters=parameters, ephemeris=ephemeris,
                                             attitude=attitude, sun_positions_m=sun, earth_flux=earth)


def run_satellite(scene_path: str | Path, run_id: str, instance_id: str, duration_s: float = DURATION_S) -> dict:
    """Assemble one satellite from its scene file and run the coupled procedure with Power over ``duration_s``.

    Every Power call and every trial is logged: ``("power", time_s, T_B_K, inputs.run_id, inputs.instance_id,
    state.run_id, state.instance_id, x_n, x_p)`` and ``("trial", time_s, T_B of the trial state, run_id, context)``.
    """

    from sdtwin_sim import coupled as cp
    from sdtwin_sim import power_stand_in as ps
    from sdtwin_sim import scene as sc
    from thermal import ThermalRangeWarning, ThermalState, assemble_thermal_parameters

    assembly = sc.assemble_scene(scene_path)
    parameters = assemble_thermal_parameters(*assembly.thermal_inputs())
    power_parameters, power_state, request, info = power_setup(assembly, scene_path, run_id, instance_id)
    log: list[tuple] = []

    def recording_solve(inputs: Any, state: Any, params: Any) -> Any:
        log.append(("power", float(inputs.time_s), float(inputs.T_B_K), inputs.run_id, inputs.instance_id,
                    state.run_id, state.instance_id, float(state.x_n), float(state.x_p)))
        return ps.solve_power_allocation(inputs, state, params)

    def trial_hook(record: Any) -> None:
        log.append(("trial", float(record.time_s), float(record.state[NODES.index("B")]), record.run_id,
                    record.context))

    coupling = cp.PowerCoupling(parameters=power_parameters, initial_state=power_state, request_W=request,
                                solve=recording_solve)
    initial = ThermalState(run_id, 0.0, assembly.initial_temperature_K)
    provider = environment_provider(run_id, parameters, duration_s)
    caller = {"test_case": "NI-003", "scene_id": assembly.scene_id,
              "scene_sha256": assembly.provenance["scene"]["sha256"], "power_instance_id": instance_id}
    error = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ThermalRangeWarning)
        try:
            archive = cp.run_coupled(parameters, initial, provider, duration_s, power=coupling, trial_hook=trial_hook,
                                     provenance=caller)
        except cp.CoupledRunError as exc:
            archive = exc.archive
            error = str(exc)
    range_warnings = sum(1 for item in caught if issubclass(item.category, ThermalRangeWarning))
    return {"assembly": assembly, "parameters": parameters, "archive": archive, "power_info": info, "log": log,
            "initial_state": initial, "power_initial_state": power_state, "error": error,
            "range_warning_messages": range_warnings}


def fingerprint(archive: Any) -> dict[str, str]:
    """Canonical JSON text per archive field; float repr round-trips, so equal text means bitwise equal values.

    ``provenance`` (software and caller metadata) and the wall time are left out; everything the run computed is in.
    """

    data = archive.as_dict()
    data.pop("provenance", None)
    statistics = dict(data.get("statistics") or {})
    statistics.pop("wall_time_s", None)
    data["statistics"] = statistics
    return {key: json.dumps(value, sort_keys=True) for key, value in data.items()}


def main_arrays(archive: Any) -> dict[str, np.ndarray]:
    """The state arrays compared byte for byte between runs."""

    arrays = {
        "time_s": archive.time_s,
        "temperature_K": archive.temperature_K,
        "x_n": archive.lithium["x_n"],
        "x_p": archive.lithium["x_p"],
        "q_W": archive.q_W,
        "accepted_time_s": archive.accepted["time_s"],
        "accepted_state": archive.accepted["state"],
        "final_temperature_K": archive.final_thermal_state.temperature_K,
        "final_lithium": np.array([archive.final_power_state.x_n, archive.final_power_state.x_p]),
    }
    for port in PORTS:
        arrays["port_" + port] = archive.ports_W[port]
    return {name: np.ascontiguousarray(np.asarray(value, dtype=float)) for name, value in arrays.items()}


def analyse_log(log: list[tuple], run_id: str, instance_id: str) -> dict:
    """Power calls of one run: identifiers, and pairing of each call with the trial state it was made for."""

    power = [entry for entry in log if entry[0] == "power"]
    trials = [entry for entry in log if entry[0] == "trial"]
    wrong_ids = sum(1 for e in power if not (e[3] == run_id and e[4] == instance_id and e[5] == run_id
                                              and e[6] == instance_id))
    wrong_trial_ids = sum(1 for e in trials if e[3] != run_id)
    paired = 0
    unpaired = 0
    mismatched = 0
    pending = None
    for entry in log:
        if entry[0] == "power":
            if pending is not None:
                unpaired += 1
            pending = entry
        elif pending is not None:
            if entry[1] == pending[1] and entry[2] == pending[2]:
                paired += 1
            else:
                mismatched += 1
            pending = None
    if pending is not None:
        unpaired += 1
    first = power[0] if power else None
    return {"power_calls": len(power), "trials": len(trials), "wrong_ids": wrong_ids,
            "wrong_trial_ids": wrong_trial_ids, "paired": paired, "unpaired": unpaired, "mismatched": mismatched,
            "first_T_B_K": first[2] if first else None, "first_x_n": first[7] if first else None,
            "first_x_p": first[8] if first else None,
            "T_B_K_min": min(e[2] for e in power) if power else None,
            "T_B_K_max": max(e[2] for e in power) if power else None}


def deep_copy_table(table: dict) -> dict:
    return copy.deepcopy(table)
