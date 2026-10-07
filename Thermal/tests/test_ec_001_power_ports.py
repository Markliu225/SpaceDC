"""EC-001 electro-thermal coupling: the four Power ports in T3 (thermal design 4.1, 4.3, 5.6, 6.1; requirement TH-02).

The case checks that ``P_pv_W``, ``P_load_W``, ``Q_B_W`` and ``Q_D_W`` enter T3 at S, J, B and D with their signs, that
``thermal_derivative`` enforces the sign limits and the ``absorbed_solar_S_W`` bound, that a Power result with
``valid=False`` or ``event_required=True`` never reaches the thermal derivative (Thermal repairs no power and decides no
load restart), and that the battery temperature has one owner, Thermal, and is returned to Power as ``T_B_K``.

Power results come from ``sdtwin_sim.power_stand_in``, a stand-in written from the Power design report (it is not the
production Power module); the one-orbit joint run uses ``sdtwin_sim.coupled``. Case data:
``tests/data/ec_001/ec001_inputs.json``. References are independent of the module under test: capacitances and
resistances are hand calculations of T5 from the case data, and T2, T3 and T4 are re-implemented in this file with
their own quaternion rotation and sums. The precondition HT-002 is taken from its evidence file
``tests/results/HT-002.json``, written by its own test module. The Chinese summary is built from the recorded check
outcomes: a statement of success is written only when every check behind it passed.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import math
import numbers
import time
import typing
import warnings
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from ntu_space_dynamics import (
    AttitudeEphemeris,
    ClassicalElements,
    OrbitState,
    TwoBodyPropagator,
    oe_to_rv,
    sun_position_ephemeris,
)
from ntu_space_dynamics.constants import MU_EARTH
from ntu_space_dynamics.time import time_grid
from sdtwin_sim import coupled as cp
from sdtwin_sim import power_stand_in as ps
from thermal import (
    ThermalEvaluation,
    ThermalInputError,
    ThermalInputs,
    ThermalState,
    assemble_thermal_parameters,
    calculate_surface_heat,
    prepare_surface_environment,
    thermal_derivative,
)

pytestmark = pytest.mark.case("EC-001")

DATA_FILE = Path(__file__).resolve().parent / "data" / "ec_001" / "ec001_inputs.json"
PRECONDITION_FILE = Path(__file__).resolve().parent / "results" / "HT-002.json"  # evidence of the precondition case
SIGMA_W_M2_K4 = 5.670374419e-8  # design table 5, written here independently of the module constant
REL_TOL = 1e-12  # acceptance: relative error of the derivative changes against the hand calculation
OVER_BOUND_W = 50.0  # step 4: P_pv this far above absorbed_solar_S_W (besides a relative excess of 1e-9)
NODES = ("S", "J", "C", "B", "D", "R")  # design 1.4 temperature order
PATHS = {"SR": ("S", "R"), "JC": ("J", "C"), "CR": ("C", "R"), "BR": ("B", "R"), "DR": ("D", "R")}  # design 4.2
PORTS = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")
PORT_NODE = {"P_pv_W": "S", "P_load_W": "J", "Q_B_W": "B", "Q_D_W": "D"}  # T3
PORT_SIGN = {"P_pv_W": -1.0, "P_load_W": 1.0, "Q_B_W": 1.0, "Q_D_W": 1.0}  # sign of each port in T3 and T1
PORT_INSTANCE = {"P_pv_W": "SolarArray01", "P_load_W": "Compute01", "Q_B_W": "Battery01", "Q_D_W": "PDU01"}  # 5.1
NODE_CN = {"S": "太阳能板", "J": "计算节点", "C": "冷板", "B": "电池", "D": "电源设备", "R": "散热板"}
EVALUATION_FIELDS = {"run_id", "time_s", "dT_dt_K_s", "q_W", "Q_env_W", "Q_emit_W", "T_B_K", "T_J_K"}  # table 6
# Evaluation contexts of the coupled procedure. Integration and event location are solver trials; boundary decisions,
# output samples and energy audit points evaluate accepted states or the accepted solution and are not trials
# (thermal design 5.1 keeps trial and accepted states as separate records; table 8 samples outputs on the accepted
# solution).
TRIAL_CONTEXTS = ("integration", "event_location")
ACCEPTED_CONTEXTS = ("boundary", "output", "energy_audit")
NATURAL_CODES = (("temperature_out_of_range", "valid"), ("invalid_input", "valid"), ("supply_shortfall", "event"),
                 ("device_boundary", "event"))  # stand-in results without ports (Power design 5.1, 5.5)


def step1_names(port: str) -> tuple[str, str, str]:
    """Names of the three step 1 checks of one port: other nodes unchanged, change against hand, T1."""

    node = NODE_CN[PORT_NODE[port]]
    return (f"第1步：{port} 只改变{node}导数", f"第1步：{port} 导数变化与手算一致", f"第1步：{port} 变化满足 T1 整体热平衡")


def step4_natural_names(code: str, kind: str) -> tuple[str, str, str]:
    """Names of the three step 4 checks of one unusable stand-in result."""

    label = "valid 为假" if kind == "valid" else "event_required 为真"
    return (f"第4步：{label}的 {code} 结果不含功率端口", f"第4步：{label}的 {code} 结果不能构成 ThermalInputs",
            f"第4步：{label}的 {code} 结果不进入 thermal_derivative")


# ----------------------------------------------------------------------------------------------------------- helpers


class Checks:
    """Records every check in the case record; the test fails at the end when any check failed."""

    def __init__(self, record: Any) -> None:
        self.record = record
        self.failed: list[str] = []

    def __call__(self, name: str, expected: str, actual: str, passed: Any) -> bool:
        passed = bool(passed)
        self.record.check(name, expected, actual, passed)
        if not passed:
            self.failed.append(name)
        return passed

    def finish(self) -> None:
        assert not self.failed, "failed checks: " + "; ".join(self.failed)


def rel(actual: float, expected: float) -> float:
    """Relative error of ``actual`` against a non-zero hand value."""

    return abs(actual - expected) / abs(expected)


def worst_of(*values: Any) -> float:
    """Largest value; NaN when any value is NaN or when there is none, so a failed term never drops out of a maximum."""

    array = np.asarray(values, dtype=float)
    return float(np.max(array)) if array.size else float("nan")


def least_of(*values: Any) -> float:
    """Smallest value; NaN when any value is NaN or when there is none."""

    array = np.asarray(values, dtype=float)
    return float(np.min(array)) if array.size else float("nan")


def find_keys(record: Any, match: Any, path: str = "") -> list[tuple[str, Any]]:
    """(path, value) of every key of a nested mapping or sequence whose name satisfies ``match``."""

    found: list[tuple[str, Any]] = []
    if isinstance(record, Mapping):
        for key, value in record.items():
            where = f"{path}.{key}" if path else str(key)
            if match(str(key)):
                found.append((where, value))
            found.extend(find_keys(value, match, where))
    elif isinstance(record, (list, tuple)):
        for index, value in enumerate(record):
            found.extend(find_keys(value, match, f"{path}[{index}]"))
    return found


def temperature_fields(cls: type, prefix: str, seen: frozenset = frozenset()) -> list[str]:
    """Temperature-like field names of a dataclass and of the dataclasses nested in its field types."""

    hints = typing.get_type_hints(cls)
    names = []
    for item in dataclasses.fields(cls):
        where = f"{prefix}.{item.name}"
        if "T_" in item.name or "temperature" in item.name.lower():
            names.append(where)
        for inner in typing.get_args(hints[item.name]) or (hints[item.name],):
            if dataclasses.is_dataclass(inner) and isinstance(inner, type) and inner not in seen:
                names.extend(temperature_fields(inner, where, seen | {cls, inner}))
    return names


def fmt(value: float, digits: int = 6) -> str:
    return f"{value:.{digits}g}"


def axis_angle_quaternion(axis: Any, angle_deg: float) -> np.ndarray:
    """Unit quaternion, SciPy scalar-last xyzw order, of an active rotation about ``axis``."""

    unit = np.asarray(axis, dtype=float)
    unit = unit / math.sqrt(float(unit @ unit))
    half = math.radians(angle_deg) / 2.0
    return np.array([*(unit * math.sin(half)), math.cos(half)])


def rotation_matrix_xyzw(q: Any) -> np.ndarray:
    """Matrix of the active rotation of a unit quaternion (x, y, z, w); independent of SciPy."""

    x, y, z, w = (float(v) for v in q)
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ]
    )


def outcome(function: Any) -> tuple[type | None, str, Any]:
    """(exception class, message, value) of one call."""

    try:
        value = function()
    except Exception as exc:  # noqa: BLE001  (the class and message are the handling result under test)
        return type(exc), str(exc), None
    return None, "", value


@dataclasses.dataclass(frozen=True)
class FlaggedPorts:
    """A Power-result-shaped input that carries the four ports together with the Power flags (test injection)."""

    run_id: str
    time_s: float
    environment: Any
    P_pv_W: float
    P_load_W: float
    Q_B_W: float
    Q_D_W: float
    valid: bool
    event_required: bool


@dataclasses.dataclass
class Instant:
    run_id: str
    time_s: float
    quaternion: np.ndarray
    position: np.ndarray
    sun: np.ndarray
    G: float
    albedo: list[float]
    infrared: list[float]
    temperature: dict[str, float]
    environment: Any
    state: ThermalState
    power_environment: Any


def make_instant(case: dict, hand: SimpleNamespace, params: Any, *, G: float | None = None,
                 eclipse: bool = False) -> Instant:
    """Synchronized orbit_input, earth_flux, surface environment, ThermalState and PowerEnvironment of one instant."""

    data = case["instant"]
    q = axis_angle_quaternion(data["rotation_axis_body"], data["rotation_angle_deg"])
    position = np.array(data["eclipse_position_m"] if eclipse else data["position_m"], dtype=float)
    sun = np.array(data["sun_position_m"], dtype=float)
    irradiance = 0.0 if eclipse else float(data["G_W_m2"] if G is None else G)
    ids = [surface["surface_id"] for surface in hand.surfaces]
    albedo = [0.0 if eclipse else float(data["albedo_W_m2"][sid]) for sid in ids]
    infrared = [float(data["infrared_W_m2"][sid]) for sid in ids]
    run_id, t = data["run_id"], float(data["time_s"])
    orbit_input = {
        "run_id": run_id, "time_s": t, "epoch": datetime.fromisoformat(data["epoch_utc"]), "position_m": position,
        "sun_position_m": sun, "frame": "GCRS", "quaternion_xyzw": q, "G_W_m2": irradiance,
    }
    earth_flux = {"run_id": run_id, "time_s": t, "surface_ids": ids, "albedo_W_m2": albedo, "infrared_W_m2": infrared}
    temperature = {node: float(data["temperature_K"][node]) for node in NODES}
    return Instant(
        run_id=run_id, time_s=t, quaternion=q, position=position, sun=sun, G=irradiance, albedo=albedo,
        infrared=infrared, temperature=temperature,
        environment=prepare_surface_environment(orbit_input, earth_flux, params),
        state=ThermalState(run_id, t, [temperature[node] for node in NODES]),
        power_environment=ps.PowerEnvironment(G_W_m2=irradiance, position_m=position, sun_position_m=sun,
                                              quaternion_xyzw=q, frame="GCRS"),
    )


def reference_surface(hand: SimpleNamespace, instant: Instant) -> dict[str, Any]:
    """Independent T4: absorbed and emitted powers of S and R and the direct sunlight absorbed by S."""

    matrix = rotation_matrix_xyzw(instant.quaternion)
    direction = instant.sun - instant.position
    direction = direction / math.sqrt(float(direction @ direction))
    absorbed = {"S": [], "R": []}
    emitted = {"S": [], "R": []}
    direct_s = []
    cosines = []
    for surface, albedo, infrared in zip(hand.surfaces, instant.albedo, instant.infrared, strict=True):
        normal = matrix @ np.array(surface["normal_body"], dtype=float)
        cosine = float(normal @ direction)
        cosines.append(cosine)
        g_sun = instant.G * max(0.0, cosine)
        area, alpha, eps, node = surface["area_m2"], surface["absorptivity"], surface["emissivity"], surface["node"]
        absorbed[node].append(area * (alpha * (g_sun + albedo) + eps * infrared))
        emitted[node].append(eps * SIGMA_W_M2_K4 * area * instant.temperature[node] ** 4)
        if node == "S":
            direct_s.append(area * alpha * g_sun)
    return {
        "Q_env": {node: math.fsum(values) for node, values in absorbed.items()},
        "Q_emit": {node: math.fsum(values) for node, values in emitted.items()},
        "absorbed_S": math.fsum(direct_s),
        "cos": cosines,
    }


def reference_terms(hand: SimpleNamespace, temperature: dict[str, float], q_env: dict[str, float],
                    q_emit: dict[str, float], ports: dict[str, float]) -> dict[str, tuple[float, ...]]:
    """Independent T2 and T3: the signed power terms of every node balance."""

    q = {path: (temperature[a] - temperature[b]) / hand.R[path] for path, (a, b) in PATHS.items()}
    return {
        "S": (q_env["S"], -ports["P_pv_W"], -q["SR"], -q_emit["S"]),
        "J": (ports["P_load_W"], -q["JC"]),
        "C": (q["JC"], -q["CR"]),
        "B": (ports["Q_B_W"], -q["BR"]),
        "D": (ports["Q_D_W"], -q["DR"]),
        "R": (q["SR"], q["CR"], q["BR"], q["DR"], q_env["R"], -q_emit["R"]),
    }


def reference_check(hand: SimpleNamespace, instant: Instant, surface_ref: dict[str, Any], ports: dict[str, float],
                    evaluation: ThermalEvaluation) -> float:
    """Largest |C_i dT_i(module) - net_i(reference)| / gross_i over the six nodes."""

    terms = reference_terms(hand, instant.temperature, surface_ref["Q_env"], surface_ref["Q_emit"], ports)
    errors = []
    for index, node in enumerate(NODES):
        net = math.fsum(terms[node])
        gross = math.fsum(abs(value) for value in terms[node])
        errors.append(abs(hand.C[node] * float(evaluation.dT_dt_K_s[index]) - net) / gross)
    return worst_of(*errors)


def evaluate(instant: Instant, params: Any, ports: dict[str, float]) -> ThermalEvaluation:
    inputs = ThermalInputs(instant.run_id, instant.time_s, instant.environment,
                           ports["P_pv_W"], ports["P_load_W"], ports["Q_B_W"], ports["Q_D_W"])
    return thermal_derivative(instant.state, inputs, params)


def result_ports(result: Any) -> dict[str, float]:
    return {name: getattr(result, name) for name in PORTS}


def power_at(power: SimpleNamespace, instant: Instant, *, x_n: float, request_W: float, T_B_K: float | None = None,
             instance_id: str = "Sat01") -> Any:
    """Power stand-in evaluation at one instant; T_B_K is the battery temperature of the thermal state."""

    state = ps.PowerState(run_id=instant.run_id, instance_id="Sat01", time_s=instant.time_s, x_n=x_n,
                          x_p=power.x_p_for(x_n), load_connected=True, trip_latched=False, handled_command_ids=())
    inputs = ps.PowerInputs(run_id=instant.run_id, instance_id=instance_id, time_s=instant.time_s,
                            environment=instant.power_environment, P_request_W=request_W,
                            T_B_K=float(instant.state.temperature_K[3]) if T_B_K is None else T_B_K)
    return ps.solve_power_allocation(inputs, state, power.parameters)


def orbit_period_s(case: dict) -> float:
    a = 6378137.0 + case["orbit"]["altitude_m"]
    return 2.0 * math.pi * math.sqrt(a ** 3 / MU_EARTH)


def orbit_provider(case: dict, params: Any, run_id: str, duration_s: float) -> cp.EnvironmentProvider:
    """Orbit environment of the joint run: two-body 400 km orbit, Sun-tracking attitude tilted 45 degrees."""

    o = case["orbit"]
    epoch = datetime.fromisoformat(o["epoch_utc"])
    elements = ClassicalElements.from_degrees(6378137.0 + o["altitude_m"], o["eccentricity"], o["inclination_deg"],
                                              o["raan_deg"], o["argument_of_perigee_deg"], o["true_anomaly_deg"],
                                              epoch=epoch)
    r0, v0 = oe_to_rv(elements)
    times = time_grid(epoch, epoch + timedelta(seconds=duration_s + o["ephemeris_margin_s"]), o["ephemeris_step_s"])
    ephemeris = TwoBodyPropagator().propagate(OrbitState(epoch, r0, v0, "GCRS"), times)
    sun = np.array([sun_position_ephemeris(moment) for moment in times])
    tilt = math.radians(o["sun_tilt_deg"])
    quaternions = []
    for r, v, s in zip(ephemeris.positions_m, ephemeris.velocities_m_s, sun, strict=True):
        u = (s - r) / np.linalg.norm(s - r)
        h = np.cross(r, v)
        z = h - np.dot(h, u) * u
        z /= np.linalg.norm(z)
        w = np.cross(z, u)
        x = math.cos(tilt) * u - math.sin(tilt) * w
        quaternions.append(Rotation.from_matrix(np.column_stack([x, np.cross(z, x), z])).as_quat())
    attitude = AttitudeEphemeris(ephemeris.elapsed_seconds, np.array(quaternions), np.zeros((len(times), 3)))
    m = o["earth_flux_model"]
    earth = cp.EarthFluxModel(albedo=m["albedo"], olr_W_m2=m["olr_W_m2"], solar_constant_W_m2=m["solar_constant_W_m2"],
                              resolution=tuple(m["resolution"]))
    return cp.EnvironmentProvider.from_orbit(run_id=run_id, epoch=epoch, parameters=params, ephemeris=ephemeris,
                                             attitude=attitude, sun_positions_m=sun, earth_flux=earth)


class CallLog:
    """Ordered log of Power calls, thermal_derivative calls and evaluation records of one coupled run.

    The coupled procedure passes one evaluation record (``TrialRecord``) to ``trial_hook`` after every evaluation, in
    every context: solver trials of integration and event location, accepted states of boundary decisions and the
    accepted solution at output samples and energy audit points. Entries of kind ``"record"`` hold these records.
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def power_spy(self, inner: Any) -> Any:
        def solve(inputs: Any, state: Any, parameters: Any) -> Any:
            result = inner(inputs, state, parameters)
            battery = getattr(result, "battery", None)
            self.entries.append({
                "kind": "power", "time_s": float(inputs.time_s), "T_B_K": float(inputs.T_B_K),
                "x_n": float(state.x_n), "x_p": float(state.x_p), "load_connected": bool(state.load_connected),
                "valid": bool(result.valid), "event_required": bool(result.event_required),
                "can_supply": bool(result.can_supply_request), "reason": str(result.reason),
                "ports": tuple(getattr(result, name) for name in PORTS),
                "battery_T_B_K": None if battery is None else float(battery.T_B_K),
            })
            return result

        return solve

    def thermal_spy(self, inner: Any) -> Any:
        def derivative(state: Any, inputs: Any, parameters: Any) -> Any:
            evaluation = inner(state, inputs, parameters)
            self.entries.append({
                "kind": "thermal", "time_s": float(state.time_s), "T_B_K": float(state.temperature_K[3]),
                "T_J_K": float(state.temperature_K[1]), "ports": tuple(float(getattr(inputs, name)) for name in PORTS),
                "evaluation_T_B_K": float(evaluation.T_B_K), "evaluation_T_J_K": float(evaluation.T_J_K),
            })
            return evaluation

        return derivative

    def hook(self, record: Any) -> None:
        self.entries.append({"kind": "record", "time_s": float(record.time_s), "context": record.context,
                             "outcome": record.outcome, "state": np.array(record.state, dtype=float)})

    def _record_after(self, index: int) -> dict[str, Any] | None:
        """Evaluation record that closes the Power call at ``index`` (after its thermal call, if any)."""

        following = index + 1
        while following < len(self.entries) and self.entries[following]["kind"] == "thermal":
            following += 1
        if following < len(self.entries) and self.entries[following]["kind"] == "record":
            return self.entries[following]
        return None

    def analyse(self) -> dict[str, int]:
        """Pairing of every Power call with the state it evaluates and of every thermal call with its Power result."""

        entries = self.entries
        counts = {"power_calls": 0, "thermal_calls": 0, "evaluation_records": 0, "power_state_mismatch": 0,
                  "unusable_power_calls": 0, "unusable_reaching_thermal": 0, "thermal_without_usable_power": 0,
                  "thermal_port_mismatch": 0, "thermal_T_B_mismatch": 0, "evaluation_copy_mismatch": 0,
                  "battery_echo_mismatch": 0, "record_without_power": 0}
        for index, entry in enumerate(entries):
            kind = entry["kind"]
            if kind == "power":
                counts["power_calls"] += 1
                record = self._record_after(index)
                if (record is None or record["time_s"] != entry["time_s"]
                        or record["state"][3] != entry["T_B_K"] or record["state"][6] != entry["x_n"]
                        or record["state"][7] != entry["x_p"]):
                    counts["power_state_mismatch"] += 1
                if not entry["valid"] or entry["event_required"]:
                    counts["unusable_power_calls"] += 1
                    if index + 1 < len(entries) and entries[index + 1]["kind"] == "thermal":
                        counts["unusable_reaching_thermal"] += 1
                if entry["battery_T_B_K"] is not None and entry["battery_T_B_K"] != entry["T_B_K"]:
                    counts["battery_echo_mismatch"] += 1
            elif kind == "thermal":
                counts["thermal_calls"] += 1
                previous = entries[index - 1] if index > 0 else None
                if (previous is None or previous["kind"] != "power" or previous["time_s"] != entry["time_s"]
                        or not previous["valid"] or previous["event_required"]):
                    counts["thermal_without_usable_power"] += 1
                    continue
                if previous["ports"] != entry["ports"]:
                    counts["thermal_port_mismatch"] += 1
                if previous["T_B_K"] != entry["T_B_K"]:
                    counts["thermal_T_B_mismatch"] += 1
                if entry["evaluation_T_B_K"] != entry["T_B_K"] or entry["evaluation_T_J_K"] != entry["T_J_K"]:
                    counts["evaluation_copy_mismatch"] += 1
            else:
                counts["evaluation_records"] += 1
                previous = index - 1
                while previous >= 0 and entries[previous]["kind"] == "thermal":
                    previous -= 1
                if previous < 0 or entries[previous]["kind"] != "power" or entries[previous]["time_s"] != entry["time_s"]:
                    counts["record_without_power"] += 1
        return counts

    def power_calls(self) -> list[dict[str, Any]]:
        """Power calls in call order, each with the context of the evaluation record that closes it."""

        calls = []
        for index, entry in enumerate(self.entries):
            if entry["kind"] == "power":
                record = self._record_after(index)
                calls.append(dict(entry, context=None if record is None else record["context"]))
        return calls

    def power_contexts(self) -> Counter:
        """Number of Power calls per evaluation context; ``None`` counts calls without an evaluation record."""

        return Counter(call["context"] for call in self.power_calls())


def injected_result(inputs: Any, *, valid: bool, reason: str) -> Any:
    """Power result without ports: valid=False (input or numerical error) or valid=True with event_required=True."""

    return ps.PowerResult(
        run_id=inputs.run_id, instance_id=inputs.instance_id, time_s=inputs.time_s, P_pv_W=None, P_load_W=None,
        Q_B_W=None, Q_D_W=None, dx_n_dt=None, dx_p_dt=None, battery=None, valid=valid, event_required=valid,
        can_supply_request=False, reason=reason, solar=None, P_bus_W=None,
        diagnostics={"injected_by": "EC-001 test through PowerCoupling.solve"},
    )


def coupled_run(case: dict, params: Any, power: SimpleNamespace, monkeypatch: Any, run_id: str, duration_s: float,
                solve: Any, *, commands: tuple = (), energy_audit: bool = False) -> SimpleNamespace:
    """One coupled run with spies on Power and on thermal_derivative; returns the archive and the call log."""

    log = CallLog()
    provider = orbit_provider(case, params, run_id, duration_s)
    initial = ThermalState(run_id, 0.0, [case["thermal"]["initial_temperature_K"][node] for node in NODES])
    coupling = cp.PowerCoupling(parameters=power.parameters, initial_state=ps.power_state_from_scene(power.scene, run_id),
                                request_W=case["power"]["request_W"], solve=log.power_spy(solve), commands=commands)
    error = None
    started = time.perf_counter()
    with monkeypatch.context() as patch, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        patch.setattr(cp, "thermal_derivative", log.thermal_spy(thermal_derivative))
        try:
            archive = cp.run_coupled(params, initial, provider, duration_s, power=coupling, trial_hook=log.hook,
                                     energy_audit=energy_audit)
        except cp.CoupledRunError as exc:
            archive, error = exc.archive, exc
    return SimpleNamespace(archive=archive, error=error, log=log, provider=provider, initial=initial,
                           wall_s=time.perf_counter() - started, warnings=[str(item.message) for item in caught])


# ---------------------------------------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def case() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def hand(case: dict) -> SimpleNamespace:
    """Hand calculation of T5 from the case data: node capacitances, path resistances and the surface records."""

    components = case["thermal"]["components"]
    capacitance = {
        node: math.fsum(m["mass_kg"] * m["cp_J_kgK"] for c in components if c["node_id"] == node for m in c["materials"])
        for node in NODES
    }
    resistance = {}
    for connection in case["thermal"]["connections"]:
        if "equivalent_total_resistance_K_W" in connection:
            extra = 0.0 if connection["includes_contact"] else connection["contact_resistance_K_W"]
            resistance[connection["path"]] = connection["equivalent_total_resistance_K_W"] + extra
        else:
            resistance[connection["path"]] = (connection["length_m"] / (connection["conductivity_W_mK"]
                                                                        * connection["area_m2"])
                                              + connection["contact_resistance_K_W"])
    surfaces = [dict(surface, node=c["node_id"]) for c in components for surface in c.get("surfaces", [])]
    overrides = case["power"]["overrides"]
    return SimpleNamespace(C=capacitance, R=resistance, surfaces=surfaces,
                           cell_area_m2=overrides["solar"]["area_m2"], efficiency=overrides["solar"]["efficiency"],
                           eta_D=overrides["pdu"]["eta_D"])


@pytest.fixture(scope="module")
def params(case: dict) -> Any:
    return assemble_thermal_parameters(case["thermal"]["components"], case["thermal"]["connections"], None)


@pytest.fixture(scope="module")
def instant(case: dict, hand: SimpleNamespace, params: Any) -> Instant:
    return make_instant(case, hand, params)


@pytest.fixture(scope="module")
def power(case: dict) -> SimpleNamespace:
    """Power stand-in parameters with the case overrides and the initial lithium state of the joint run.

    The battery initial temperature has one owner, the ThermalState (thermal design 9.4: all initial temperatures
    enter ThermalState and there is only this one battery initial temperature; Power design: the battery initial
    temperature is kept by Thermal). The stand-in's scene record requires ``initial_state.T_B_K`` for its own initial
    check of the zero-current voltage and the temperature range, a field that the Power design's initial_state_fields
    do not list; the test fills it with the ThermalState value, so the joint configuration holds one value only.
    """

    asset_record, scene_record = ps.example_power_records()
    data = case["power"]
    scene_record["overrides"] = json.loads(json.dumps(data["overrides"]))
    battery = ps.load_power_parameters(asset_record, scene_record).battery

    def x_p_for(x_n: float) -> float:
        # same cyclable lithium inventory as the SOC 100 point of the parameter set (Power design 4.4.5)
        return battery.x_p_100 + (battery.x_n_100 - x_n) * battery.Q_n_C / battery.Q_p_C

    scene_record["initial_state"].update(x_n=data["initial_x_n"], x_p=x_p_for(data["initial_x_n"]),
                                         T_B_K=case["thermal"]["initial_temperature_K"]["B"])
    return SimpleNamespace(parameters=ps.load_power_parameters(asset_record, scene_record), scene=scene_record,
                           x_p_for=x_p_for)


# ------------------------------------------------------------------------------------------------------------- tests


def test_precondition_ht_002(case_record: Any) -> None:
    """Precondition of the case: HT-002 has passed, as recorded in the evidence file written by its own test module.

    Evidence files are written when a pytest session ends, so this reads the HT-002 result of the latest session
    that ran HT-002; the file time is recorded with it.
    """

    check = Checks(case_record)
    record: Any = None
    problem = ""
    for _ in range(5):
        try:
            record = json.loads(PRECONDITION_FILE.read_text(encoding="utf-8"))
            problem = ""
            break
        except FileNotFoundError:
            problem = "file not found"
            break
        except (json.JSONDecodeError, OSError) as exc:  # another session may be writing the file at this moment
            problem = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)
    record = record if isinstance(record, dict) else {}
    checks = [item for item in record.get("checks", []) if isinstance(item, dict)]
    n_passed = sum(1 for item in checks if item.get("passed") is True)
    status = record.get("status")
    modified = (datetime.fromtimestamp(PRECONDITION_FILE.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
                if PRECONDITION_FILE.exists() else None)
    passed = record.get("case_id") == "HT-002" and status == "pass" and bool(checks) and n_passed == len(checks)
    check("前提：HT-002 已通过",
          "tests/results/HT-002.json, written by tests/test_ht_002_derivative_balance.py, has case_id HT-002, status "
          "pass and every recorded check passed (precondition of EC-001)",
          f"case_id {record.get('case_id')!r}, status {status!r}, {n_passed} of {len(checks)} checks passed, file "
          f"written {modified}" + (f", {problem}" if problem else ""), passed)
    case_record.metric("precondition_HT_002_status", status)
    case_record.metric("precondition_HT_002_checks_passed", n_passed)
    case_record.metric("precondition_HT_002_checks", len(checks))
    case_record.metric("precondition_HT_002_file_written_utc", modified)
    check.finish()


def test_step1_single_port_changes(case: dict, hand: SimpleNamespace, params: Any, instant: Instant,
                                   power: SimpleNamespace, case_record: Any) -> None:
    """Step 1: each port changes only the derivative of its node, by the power change divided by the capacitance."""

    check = Checks(case_record)
    worst_c = worst_of(*(rel(float(params.C_J_K[i]), hand.C[node]) for i, node in enumerate(NODES)))
    check("前提：装配热容与 T5 手算一致", "six capacitances equal m cp sums, relative error <= 1e-12",
          f"C_J_K {[fmt(float(v), 9) for v in params.C_J_K]} J/K, largest relative error {worst_c:.3g}",
          worst_c <= REL_TOL)
    worst_r = worst_of(*(rel(float(params.R_K_W[i]), hand.R[path]) for i, path in enumerate(PATHS)))
    check("前提：装配热阻与 T5 手算一致", "five resistances equal l/(k A) + R_contact or the equivalent total",
          f"R_K_W {[fmt(float(v), 9) for v in params.R_K_W]} K/W, largest relative error {worst_r:.3g}",
          worst_r <= REL_TOL)
    case_record.metric("premise_C_max_relative_error", worst_c)
    case_record.metric("premise_R_max_relative_error", worst_r)
    order_ok = [s.surface_id for s in params.surfaces] == [s["surface_id"] for s in hand.surfaces]
    ports_map = dict(params.instance_map["ports"])
    links = dict(power.parameters.links)
    check("前提：四个功率端口的实例对应一致",
          f"thermal port instances and Power links both equal {PORT_INSTANCE}; Power PORT_NAMES {PORTS}",
          f"thermal {ports_map}; Power links {links}; Power PORT_NAMES {ps.PORT_NAMES}; surface order kept {order_ok}",
          ports_map == PORT_INSTANCE and links == PORT_INSTANCE and tuple(ps.PORT_NAMES) == PORTS and order_ok)
    swapped = dict(PORT_INSTANCE, Q_B_W="PDU01", Q_D_W="Battery01")
    wrong_power = dataclasses.replace(power.parameters, links=swapped)
    run_id = "ec001.links"
    coupling = cp.PowerCoupling(parameters=wrong_power, initial_state=ps.power_state_from_scene(power.scene, run_id),
                                request_W=case["power"]["request_W"])
    initial = ThermalState(run_id, 0.0, [case["thermal"]["initial_temperature_K"][node] for node in NODES])
    provider = orbit_provider(case, params, run_id, 600.0)
    swapped_run = outcome(lambda: cp.run_coupled(params, initial, provider, 600.0, power=coupling))
    check("第1步：端口与实例错配的联合配置被拒绝",
          "Power links Q_B_W to PDU01 and Q_D_W to Battery01: CoupledConfigurationError naming Q_B_W before any "
          "integration; array position alone must not connect a value to the wrong device (design 5.1)",
          f"{getattr(swapped_run[0], '__name__', 'no error')}: {swapped_run[1][:200]}",
          swapped_run[0] is cp.CoupledConfigurationError and "Q_B_W" in swapped_run[1])

    surface_ref = reference_surface(hand, instant)
    module_surface = calculate_surface_heat(instant.state, instant.environment, params)
    absorbed = surface_ref["absorbed_S"]
    error_abs = rel(module_surface["absorbed_solar_S_W"], absorbed)
    check("前提：absorbed_solar_S_W 与手算一致", "A alpha G max(0, cos) of the S surfaces, relative error <= 1e-12",
          f"module {module_surface['absorbed_solar_S_W']!r} W, hand {absorbed!r} W, relative error {error_abs:.3g}",
          error_abs <= REL_TOL)

    rated = case["thermal"]["rated_load_W"]
    base_data = case["instant"]["base_ports"]
    base = {"P_pv_W": base_data["P_pv_fraction_of_absorbed"] * absorbed, "P_load_W": base_data["P_load_W"],
            "Q_B_W": base_data["Q_B_W"], "Q_D_W": base_data["Q_D_W"]}
    variations = case["instant"]["variations"]
    values = {
        "P_pv_W": [fraction * absorbed for fraction in variations["P_pv_fraction_of_absorbed"]],
        "P_load_W": list(variations["P_load_W"]),
        "Q_B_W": list(variations["Q_B_W"]),
        "Q_D_W": list(variations["Q_D_W"]),
    }
    domain_ok = (all(0.0 <= v <= absorbed for v in values["P_pv_W"]) and all(0.0 <= v <= rated for v in values["P_load_W"])
                 and min(values["Q_B_W"]) < 0.0 < max(values["Q_B_W"]) and all(v > 0.0 for v in values["Q_D_W"]))
    check("第1步：功率取值覆盖用例输入范围",
          "P_pv in [0, absorbed_solar_S_W], P_load in [0, rated], Q_B positive and negative, Q_D positive",
          f"absorbed_solar_S_W {absorbed:.6f} W, rated {rated} W, values {values}", domain_ok)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        base_eval = evaluate(instant, params, base)
    base_ref = reference_check(hand, instant, surface_ref, base, base_eval)
    full_worst = base_ref
    change_worst = 0.0
    other_worst = 0.0
    t1_worst = 0.0
    sign_kept = True
    n_cases = 0
    for port in PORTS:
        node = PORT_NODE[port]
        node_index = NODES.index(node)
        port_rel = 0.0
        port_other = 0.0
        port_t1 = 0.0
        details = []
        for value in values[port]:
            ports = dict(base, **{port: value})
            inputs = ThermalInputs(instant.run_id, instant.time_s, instant.environment, ports["P_pv_W"],
                                   ports["P_load_W"], ports["Q_B_W"], ports["Q_D_W"])
            sign_kept = sign_kept and getattr(inputs, port) == value
            evaluation = thermal_derivative(instant.state, inputs, params)
            n_cases += 1
            full_worst = worst_of(full_worst, reference_check(hand, instant, surface_ref, ports, evaluation))
            change = np.array(evaluation.dT_dt_K_s) - np.array(base_eval.dT_dt_K_s)
            delta_power = value - base[port]
            expected = PORT_SIGN[port] * delta_power / hand.C[node]
            port_rel = worst_of(port_rel, rel(float(change[node_index]), expected))
            others = [abs(float(change[i])) for i in range(len(NODES)) if i != node_index]
            port_other = worst_of(port_other, *others)
            stored = math.fsum(hand.C[n] * float(change[i]) for i, n in enumerate(NODES))
            port_t1 = worst_of(port_t1, rel(stored, PORT_SIGN[port] * delta_power))
            details.append(f"{port}={value:.6g} W: dT_{node} change {float(change[node_index]):.12g} K/s, "
                           f"hand {expected:.12g} K/s")
        change_worst = worst_of(change_worst, port_rel)
        other_worst = worst_of(other_worst, port_other)
        t1_worst = worst_of(t1_worst, port_t1)
        case_record.metric(f"step1_{port}_max_relative_error", port_rel)
        name_other, name_change, name_t1 = step1_names(port)
        check(name_other,
              f"the other five derivatives do not change (0 K/s, at most 1e-12 of the {node} change)",
              f"largest change of the other five nodes {port_other!r} K/s over {len(values[port])} values",
              port_other <= REL_TOL * min(abs(PORT_SIGN[port] * (v - base[port]) / hand.C[node]) for v in values[port]))
        check(name_change,
              f"change of dT_{node} = {'-' if PORT_SIGN[port] < 0 else '+'}delta {port} / C_{node}, "
              "relative error <= 1e-12",
              f"largest relative error {port_rel:.3g}; " + "; ".join(details), port_rel <= REL_TOL)
        check(name_t1,
              f"sum C_i change of dT_i = {'-' if PORT_SIGN[port] < 0 else '+'}delta {port}, relative error <= 1e-12",
              f"largest relative error {port_t1:.3g}", port_t1 <= REL_TOL)
    check("第1步：六个组件导数与独立实现一致",
          "|C_i dT_i - net_i| / gross_i <= 1e-12 for all six nodes, independent T2 to T4",
          f"largest {full_worst:.3g} over {n_cases + 1} evaluations, base dT {np.array(base_eval.dT_dt_K_s).tolist()} K/s",
          full_worst <= REL_TOL)
    check("第1步：ThermalInputs 保留端口数值与符号", "every port value is stored unchanged, Q_B_W keeps its sign",
          f"all stored values identical {sign_kept}", sign_kept)
    range_warnings = [str(item.message) for item in caught]
    check("第1步：同一时刻的输入不产生温区警告", "no ThermalRangeWarning at temperatures inside the declared ranges",
          f"{len(range_warnings)} warning(s)", not range_warnings)

    nominal = power_at(power, instant, x_n=case["power"]["initial_x_n"], request_W=case["power"]["request_W"])
    nominal_ports = result_ports(nominal)
    nominal_eval = evaluate(instant, params, nominal_ports)
    nominal_ref = reference_check(hand, instant, surface_ref, nominal_ports, nominal_eval)
    check("第1步：替代程序 Power 结果进入 T3 与独立实现一致",
          "valid Power stand-in result without event; its four ports give |C_i dT_i - net_i| / gross_i <= 1e-12",
          f"valid {nominal.valid}, event_required {nominal.event_required}, reason {nominal.reason[:60]!r}, ports "
          f"{ {k: round(v, 6) for k, v in nominal_ports.items()} } W, largest {nominal_ref:.3g}",
          nominal.valid and not nominal.event_required and nominal_ref <= REL_TOL)

    case_record.metric("absorbed_solar_S_W", absorbed)
    case_record.metric("step1_variations", n_cases)
    case_record.metric("step1_max_relative_error", change_worst)
    case_record.metric("step1_max_other_node_change_K_s", other_worst)
    case_record.metric("step1_max_T1_relative_error", t1_worst)
    case_record.metric("step1_max_full_derivative_relative_error", worst_of(full_worst, nominal_ref))
    case_record.metric("rated_load_W", rated)
    check.finish()


def test_step2_negative_battery_heat(case: dict, hand: SimpleNamespace, params: Any, instant: Instant,
                                     power: SimpleNamespace, case_record: Any) -> None:
    """Step 2: a negative Q_B lowers the battery temperature derivative by |Q_B| / C_B; the sign is kept."""

    check = Checks(case_record)
    surface_ref = reference_surface(hand, instant)
    base = {"P_pv_W": 0.5 * surface_ref["absorbed_S"], "P_load_W": 30.0, "Q_B_W": 0.0, "Q_D_W": 3.0}
    b = NODES.index("B")
    reference_rate = float(evaluate(instant, params, base).dT_dt_K_s[b])
    heats = sorted(case["instant"]["negative_battery_heat_W"], reverse=True)  # -0.5, -2, -8
    rates = []
    worst = 0.0
    kept = True
    for heat in heats:
        inputs = ThermalInputs(instant.run_id, instant.time_s, instant.environment, base["P_pv_W"], base["P_load_W"],
                               heat, base["Q_D_W"])
        kept = kept and inputs.Q_B_W == heat
        rate = float(thermal_derivative(instant.state, inputs, params).dT_dt_K_s[b])
        rates.append(rate)
        worst = worst_of(worst, rel(rate - reference_rate, heat / hand.C["B"]))
    ordered = all(a > c for a, c in zip([reference_rate] + rates, rates, strict=False))
    check("第2步：Q_B 取负值时电池温度导数依次减小",
          f"dT_B(0) > dT_B({heats[0]}) > dT_B({heats[1]}) > dT_B({heats[2]})",
          f"dT_B {[fmt(reference_rate, 12)] + [fmt(r, 12) for r in rates]} K/s", ordered)
    check("第2步：负 Q_B 引起的导数减小量与手算一致", "dT_B(Q_B) - dT_B(0) = Q_B / C_B, relative error <= 1e-12",
          f"largest relative error {worst:.3g}; decreases {[fmt(r - reference_rate, 12) for r in rates]} K/s, hand "
          f"{[fmt(h / hand.C['B'], 12) for h in heats]} K/s", worst <= REL_TOL)
    big = abs(heats[-1])
    plus = float(evaluate(instant, params, dict(base, Q_B_W=big)).dT_dt_K_s[b])
    minus = float(evaluate(instant, params, dict(base, Q_B_W=-big)).dT_dt_K_s[b])
    symmetric = rel(plus - minus, 2.0 * big / hand.C["B"])
    check("第2步：Q_B 保留符号不被截断", f"ThermalInputs keeps Q_B_W < 0 and dT_B(+{big}) - dT_B(-{big}) = 2 {big} / C_B",
          f"stored values kept {kept}; difference {plus - minus!r} K/s, relative error {symmetric:.3g}",
          kept and symmetric <= REL_TOL)

    # Stand-in case: the request equals the rated load of Compute01 and the irradiance is chosen so that P_pv_max
    # exceeds the distribution input power P_need = P_req / eta_D by a small surplus (Power design P3, P11); the battery
    # absorbs that surplus with a small charging current, which makes the net battery heat negative.
    data = case["power"]
    rated = case["thermal"]["rated_load_W"]
    request = data["small_charge_request_W"]
    surplus = data["small_charge_surplus_W"]
    need = request / hand.eta_D
    cos_front = surface_ref["cos"][0]
    G_small = (need + surplus) / (hand.efficiency * hand.cell_area_m2 * cos_front)
    charging = make_instant(case, hand, params, G=G_small)
    result = power_at(power, charging, x_n=data["small_charge_x_n"], request_W=request)
    usable = result.valid and not result.event_required
    battery = result.battery
    residual_tol = float(power.parameters.numerics.power_residual_tol_W)
    absorbed_surplus = -battery.P_B_W if usable else float("nan")
    check("第2步：替代程序在额定负载下小电流充电给出负 Q_B",
          f"request {request} W equal to the rated load {rated} W; G chosen so that P_pv_max exceeds P_need = request / "
          f"eta_D by {surplus} W; valid result without event, P_load_W equal to the request, the battery port absorbs "
          f"the {surplus} W surplus within power_residual_tol_W {residual_tol} W, charging current i < 0 and net "
          "battery heat Q_B_W < 0 (reversible heat)",
          f"G {G_small:.6f} W/m2, reason {result.reason[:40]!r}, P_pv_W {result.P_pv_W!r} W, P_pv_max "
          f"{getattr(result.solar, 'P_pv_max_W', None)!r} W, P_need {need!r} W, P_load_W {result.P_load_W!r} W, P_B_W "
          f"{getattr(battery, 'P_B_W', None)!r} W, Q_B_W {result.Q_B_W!r} W, i {getattr(battery, 'i_A', None)!r} A per "
          f"cell, reversible heat {getattr(battery, 'q_reversible_cell_W', None)!r} W per cell",
          usable and request == rated and abs(result.P_load_W - request) <= 1e-9 * request
          and abs(absorbed_surplus - surplus) <= residual_tol and result.Q_B_W < 0.0 and battery.i_A < 0.0)
    charging_ref = reference_surface(hand, charging)
    charging_ports = result_ports(result)
    charging_eval = evaluate(charging, params, charging_ports)
    zero_eval = evaluate(charging, params, dict(charging_ports, Q_B_W=0.0))
    q_br = (charging.temperature["B"] - charging.temperature["R"]) / hand.R["BR"]
    expected_rate = (charging_ports["Q_B_W"] - q_br) / hand.C["B"]
    rate_error = (abs(float(charging_eval.dT_dt_K_s[b]) - expected_rate) * hand.C["B"]
                  / (abs(charging_ports["Q_B_W"]) + abs(q_br)))
    drop_error = rel(float(charging_eval.dT_dt_K_s[b] - zero_eval.dT_dt_K_s[b]), charging_ports["Q_B_W"] / hand.C["B"])
    full_error = reference_check(hand, charging, charging_ref, charging_ports, charging_eval)
    check("第2步：替代程序的负 Q_B 进入电池方程与手算一致",
          "dT_B = (Q_B - q_BR) / C_B and dT_B(Q_B) - dT_B(0) = Q_B / C_B, relative errors <= 1e-12",
          f"dT_B {float(charging_eval.dT_dt_K_s[b])!r} K/s, hand {expected_rate!r} K/s, error {rate_error:.3g}; "
          f"decrease error {drop_error:.3g}; six nodes {full_error:.3g}",
          rate_error <= REL_TOL and drop_error <= REL_TOL and full_error <= REL_TOL)
    case_record.metric("step2_negative_Q_B_W", heats)
    case_record.metric("step2_dT_B_K_s", [reference_rate] + rates)
    case_record.metric("step2_fixed_max_relative_error", worst)
    case_record.metric("step2_symmetry_Q_B_W", big)
    case_record.metric("step2_symmetry_relative_error", symmetric)
    case_record.metric("step2_stand_in_request_W", request)
    case_record.metric("step2_stand_in_surplus_W", surplus)
    case_record.metric("step2_stand_in_reason", result.reason_code)
    case_record.metric("step2_stand_in_P_B_W", float(battery.P_B_W) if usable else None)
    case_record.metric("step2_stand_in_cell_current_A", float(battery.i_A) if usable else None)
    case_record.metric("step2_stand_in_Q_B_W", float(result.Q_B_W) if usable else None)
    case_record.metric("step2_stand_in_G_W_m2", G_small)
    case_record.metric("step2_stand_in_rate_relative_error", rate_error)
    case_record.metric("step2_stand_in_drop_relative_error", drop_error)
    case_record.metric("step2_stand_in_full_relative_error", full_error)
    case_record.metric("step2_max_relative_error", worst_of(worst, symmetric, rate_error, drop_error, full_error))
    check.finish()


def test_step3_curtailed_pv_stays_in_panel(case: dict, hand: SimpleNamespace, params: Any, instant: Instant,
                                           power: SimpleNamespace, case_record: Any) -> None:
    """Step 3: a curtailed P_pv leaves the unexported power in the energy balance of the solar array."""

    check = Checks(case_record)
    surface_ref = reference_surface(hand, instant)
    cos_front = surface_ref["cos"][0]
    p_max_hand = hand.efficiency * hand.cell_area_m2 * instant.G * max(0.0, cos_front)
    solar = ps.solar_power(instant.power_environment, power.parameters)
    error_max = rel(solar.P_pv_max_W, p_max_hand)
    check("第3步：Power 替代程序最大可发功率与手算一致", "P_pv_max = eta A G max(0, cos), relative error <= 1e-12",
          f"stand-in {solar.P_pv_max_W!r} W, hand {p_max_hand!r} W, error {error_max:.3g}", error_max <= REL_TOL)

    base = {"P_pv_W": p_max_hand, "P_load_W": 30.0, "Q_B_W": 1.5, "Q_D_W": 3.0}
    full = evaluate(instant, params, base)
    s = NODES.index("S")
    worst_s = 0.0
    worst_other = 0.0
    worst_t1 = 0.0
    lines = []
    for fraction in case["instant"]["curtailed_fraction_of_P_pv_max"]:
        reduced = fraction * p_max_hand
        evaluation = evaluate(instant, params, dict(base, P_pv_W=reduced))
        change = np.array(evaluation.dT_dt_K_s) - np.array(full.dT_dt_K_s)
        unexported = p_max_hand - reduced
        retained = hand.C["S"] * float(change[s])
        worst_s = worst_of(worst_s, rel(retained, unexported))
        worst_other = worst_of(worst_other, *(abs(float(change[i])) for i in range(len(NODES)) if i != s))
        stored = math.fsum(hand.C[n] * float(change[i]) for i, n in enumerate(NODES))
        worst_t1 = worst_of(worst_t1, rel(stored, unexported))
        lines.append(f"P_pv {reduced:.6f} W: C_S change {retained:.12g} W, unexported {unexported:.12g} W")
    check("第3步：降低 P_pv 后未输出功率留在太阳能板",
          "C_S (dT_S(reduced) - dT_S(P_pv_max)) = P_pv_max - P_pv, relative error <= 1e-12",
          f"largest relative error {worst_s:.3g}; " + "; ".join(lines), worst_s <= REL_TOL)
    check("第3步：降低 P_pv 时其余组件导数不变", "J, C, B, D and R derivatives unchanged",
          f"largest change {worst_other!r} K/s", worst_other == 0.0)
    check("第3步：降低 P_pv 后整体储热速率增加量等于少输出的电功率",
          "sum C_i change of dT_i = P_pv_max - P_pv (T1), relative error <= 1e-12",
          f"largest relative error {worst_t1:.3g}", worst_t1 <= REL_TOL)

    data = case["power"]
    limited = power_at(power, instant, x_n=data["charge_limited_x_n"], request_W=data["charge_limited_request_W"])
    usable = limited.valid and not limited.event_required
    code = limited.reason.split(":", 1)[0]
    curtailed_hand = p_max_hand - limited.P_pv_W if usable else float("nan")
    check("第3步：替代程序限充时降低实际 P_pv",
          "valid result with reason charge_limited and P_pv_W < P_pv_max (Power design 4.2, 5.5)",
          f"reason {code!r}, P_pv_W {limited.P_pv_W!r} W, P_pv_max {p_max_hand!r} W, curtailed {curtailed_hand!r} W, "
          f"stand-in diagnostics curtailed_W {limited.diagnostics.get('curtailed_W')!r} W",
          usable and code == "charge_limited" and curtailed_hand > 0.0)
    limited_ports = result_ports(limited)
    actual = evaluate(instant, params, limited_ports)
    uncurtailed = evaluate(instant, params, dict(limited_ports, P_pv_W=p_max_hand))
    retained = hand.C["S"] * float(actual.dT_dt_K_s[s] - uncurtailed.dT_dt_K_s[s])
    retained_error = rel(retained, curtailed_hand)
    full_error = reference_check(hand, instant, surface_ref, limited_ports, actual)
    check("第3步：限充少输出的电功率留在太阳能板能量收支中",
          "C_S (dT_S(actual P_pv) - dT_S(P_pv_max)) = P_pv_max - P_pv, relative error <= 1e-12; six nodes match",
          f"retained {retained!r} W, unexported {curtailed_hand!r} W, error {retained_error:.3g}; six nodes "
          f"{full_error:.3g}", retained_error <= REL_TOL and full_error <= REL_TOL)
    case_record.metric("step3_P_pv_max_W", p_max_hand)
    case_record.metric("step3_curtailed_fractions", list(case["instant"]["curtailed_fraction_of_P_pv_max"]))
    case_record.metric("step3_fixed_panel_relative_error", worst_s)
    case_record.metric("step3_fixed_T1_relative_error", worst_t1)
    case_record.metric("step3_fixed_other_node_change_K_s", worst_other)
    case_record.metric("step3_stand_in_relative_error", retained_error)
    case_record.metric("step3_stand_in_full_relative_error", full_error)
    case_record.metric("step3_max_relative_error", worst_of(worst_s, worst_t1, retained_error))
    case_record.metric("step3_stand_in_P_pv_W", float(limited.P_pv_W) if usable else None)
    case_record.metric("step3_stand_in_curtailed_W", curtailed_hand)
    check.finish()


def test_step4_abnormal_inputs_thermal(case: dict, hand: SimpleNamespace, params: Any, instant: Instant,
                                       power: SimpleNamespace, case_record: Any) -> None:
    """Step 4 at the thermal derivative: each abnormal input gets a definite rejection; nothing is repaired."""

    check = Checks(case_record)
    surface_ref = reference_surface(hand, instant)
    absorbed = surface_ref["absorbed_S"]
    eclipse = make_instant(case, hand, params, eclipse=True)
    base = {"P_pv_W": 0.5 * absorbed, "P_load_W": 30.0, "Q_B_W": 1.5, "Q_D_W": 3.0}
    rejected_total = 0
    repeat_same = True

    def rejected(name: str, call: Any, needles: tuple[str, ...], expected: str) -> None:
        nonlocal rejected_total, repeat_same
        first = outcome(call)
        second = outcome(call)
        same = first[:2] == second[:2]
        repeat_same = repeat_same and same
        ok = (first[0] is not None and issubclass(first[0], ThermalInputError) and first[2] is None
              and all(needle in first[1] for needle in needles) and same)
        rejected_total += int(ok)
        check(name, expected + "; no ThermalEvaluation returned; a repeated call gives the same class and message",
              f"{getattr(first[0], '__name__', None)}: {first[1][:220]}; repeated identical {same}", ok)

    negative = [("第4步：P_pv_W 为负被拒绝", "P_pv_W", -1.0), ("第4步：P_load_W 为负被拒绝", "P_load_W", -1.0),
                ("第4步：Q_D_W 为负被拒绝", "Q_D_W", -0.5)]
    for name, port, value in negative:
        ports = dict(base, **{port: value})
        rejected(name, lambda ports=ports: evaluate(instant, params, ports), (f"inputs.{port}", ">= 0"),
                 f"ThermalInputError naming inputs.{port} >= 0 (design 5.6)")
    bound = (("第4步：P_pv 略大于 absorbed_solar_S_W 被拒绝", instant, absorbed * (1.0 + 1e-9)),
             ("第4步：P_pv 大于 absorbed_solar_S_W 被拒绝", instant, absorbed + OVER_BOUND_W),
             ("第4步：日食时 P_pv 大于零被拒绝", eclipse, 1e-3))
    for name, moment, value in bound:
        ports = dict(base, P_pv_W=value)
        rejected(name, lambda moment=moment, ports=ports: evaluate(moment, params, ports),
                 ("P_pv_W", "exceeds absorbed_solar_S_W"),
                 f"ThermalInputError: P_pv_W {value!r} W exceeds absorbed_solar_S_W (design 4.4, 5.6)")
    at_bound = outcome(lambda: evaluate(instant, params, dict(base, P_pv_W=absorbed)))
    at_zero = outcome(lambda: evaluate(eclipse, params, dict(base, P_pv_W=0.0)))
    check("第4步：P_pv 等于 absorbed_solar_S_W 时正常计算",
          "P_pv = absorbed_solar_S_W and, in eclipse, P_pv = 0 are inside the bound and return a ThermalEvaluation",
          f"at the bound {getattr(at_bound[0], '__name__', 'evaluated')}; eclipse zero "
          f"{getattr(at_zero[0], '__name__', 'evaluated')}",
          isinstance(at_bound[2], ThermalEvaluation) and isinstance(at_zero[2], ThermalEvaluation))

    data = case["power"]
    natural = {
        "temperature_out_of_range": ("valid", power_at(power, instant, x_n=data["initial_x_n"],
                                                       request_W=data["request_W"], T_B_K=data["out_of_range_T_B_K"]),
                                     instant),
        "invalid_input": ("valid", power_at(power, instant, x_n=data["initial_x_n"], request_W=data["request_W"],
                                            instance_id="Sat02"), instant),
        "supply_shortfall": ("event", power_at(power, eclipse, x_n=data["empty_x_n"], request_W=data["request_W"]),
                             eclipse),
        "device_boundary": ("event", power_at(power, instant, x_n=data["out_of_range_x_n"],
                                              request_W=data["request_W"]), instant),
    }
    assert tuple((code, kind) for code, (kind, _, _) in natural.items()) == NATURAL_CODES
    for code, (kind, result, moment) in natural.items():
        flags_ok = ((not result.valid and not result.event_required) if kind == "valid"
                    else (result.valid and result.event_required))
        name_ports, name_inputs, name_derivative = step4_natural_names(code, kind)
        ports = result_ports(result)
        check(name_ports,
              f"stand-in result {'valid=False' if kind == 'valid' else 'valid=True, event_required=True'} with "
              f"reason {code}, all four ports None (Power design 5.1)",
              f"valid {result.valid}, event_required {result.event_required}, reason {result.reason[:120]!r}, ports "
              f"{ports}", flags_ok and result.reason_code == code and all(v is None for v in ports.values()))
        rejected(name_inputs,
                 lambda moment=moment, ports=ports: ThermalInputs(moment.run_id, moment.time_s, moment.environment,
                                                                  ports["P_pv_W"], ports["P_load_W"], ports["Q_B_W"],
                                                                  ports["Q_D_W"]),
                 ("P_pv_W is missing (None)", "must not reach the thermal derivative"),
                 "ThermalInputError: a missing port of an unusable Power result is not replaced by zero")
        rejected(name_derivative,
                 lambda moment=moment, result=result: thermal_derivative(moment.state, result, params),
                 ("invalid or requires an event",),
                 "ThermalInputError: such a result must not reach the thermal derivative (design 5.6)")
    for label, valid, event in (("第4步：带完整端口但 valid 为假的输入被拒绝", False, False),
                                ("第4步：带完整端口但 event_required 为真的输入被拒绝", True, True)):
        flagged = FlaggedPorts(instant.run_id, instant.time_s, instant.environment, base["P_pv_W"], base["P_load_W"],
                               base["Q_B_W"], base["Q_D_W"], valid, event)
        rejected(label, lambda flagged=flagged: thermal_derivative(instant.state, flagged, params),
                 ("invalid or requires an event",),
                 f"ThermalInputError for valid={valid}, event_required={event} even with four numeric ports")
    usable = FlaggedPorts(instant.run_id, instant.time_s, instant.environment, base["P_pv_W"], base["P_load_W"],
                          base["Q_B_W"], base["Q_D_W"], True, False)
    control = outcome(lambda: thermal_derivative(instant.state, usable, params))
    same_as_inputs = (isinstance(control[2], ThermalEvaluation)
                      and np.array_equal(control[2].dT_dt_K_s, evaluate(instant, params, base).dT_dt_K_s))
    check("第4步：有效且无事件的同类输入正常计算",
          "valid=True, event_required=False with the same ports gives the ThermalInputs evaluation",
          f"result {getattr(control[0], '__name__', 'evaluated')}, identical derivatives {same_as_inputs}", same_as_inputs)
    later = outcome(lambda: ThermalInputs(instant.run_id, instant.time_s + 1.0, instant.environment, *base.values()))
    shifted = ThermalState(instant.run_id, instant.time_s + 1.0, [instant.temperature[n] for n in NODES])
    other_state = outcome(lambda: evaluate(SimpleNamespace(**{**instant.__dict__, "state": shifted}), params, base))
    check("第4步：功率与热状态不在同一时刻时被拒绝",
          "ThermalInputs and thermal_derivative reject a time_s that differs from the environment or the state (6.1)",
          f"inputs {getattr(later[0], '__name__', None)}: {later[1][:100]}; state "
          f"{getattr(other_state[0], '__name__', None)}: {other_state[1][:100]}",
          later[0] is ThermalInputError and other_state[0] is ThermalInputError and "differs" in later[1]
          and "differs" in other_state[1])
    fields = {item.name for item in dataclasses.fields(ThermalEvaluation)}
    signature = list(inspect.signature(thermal_derivative).parameters)
    check("第4步：热模块输出不含负载启停字段",
          f"ThermalEvaluation fields are exactly {sorted(EVALUATION_FIELDS)}; thermal_derivative(state, inputs, "
          "parameters) receives no Power protection state",
          f"fields {sorted(fields)}; parameters {signature}",
          fields == EVALUATION_FIELDS and signature == ["state", "inputs", "parameters"])
    case_record.metric("step4_thermal_rejections", rejected_total)
    case_record.metric("step4_thermal_repeat_identical", repeat_same)
    check.finish()


def test_step4_abnormal_inputs_coupled(case: dict, params: Any, power: SimpleNamespace, monkeypatch: Any,
                                       case_record: Any) -> None:
    """Step 4 in the coupled procedure: valid=False stops the run, event_required is located and handled by Power."""

    check = Checks(case_record)
    injection = case["injection"]
    tolerance = float(power.parameters.numerics.event_time_tol_s)

    # valid=False: reported, the run stops, no protection rule, no derivative from the invalid result
    spec = injection["invalid"]

    def invalid_solve(inputs: Any, state: Any, parameters: Any) -> Any:
        if inputs.time_s >= spec["from_s"]:
            return injected_result(inputs, valid=False, reason="numerical_failure: injected by the EC-001 test")
        return ps.solve_power_allocation(inputs, state, parameters)

    runs = [coupled_run(case, params, power, monkeypatch, "ec001.invalid", spec["run_duration_s"], invalid_solve)
            for _ in range(2)]
    run = runs[0]
    archive, error = run.archive, dict(run.archive.error or {})
    counts = run.log.analyse()
    last_accepted = float(np.max(archive.accepted["time_s"]))
    check("第4步联合运行：valid 为假时报告错误并停止",
          f"CoupledRunError, archive status stopped, error kind power_invalid in a trial evaluation (context "
          f"{' or '.join(TRIAL_CONTEXTS)}) at a time >= {spec['from_s']} s, every accepted state before {spec['from_s']} s",
          f"error {type(run.error).__name__ if run.error else None}, status {archive.status}, kind {error.get('kind')}, "
          f"context {error.get('context')!r}, time {error.get('time_s')!r} s, last accepted {last_accepted!r} s, power "
          f"reason {error.get('power_reason')!r}",
          run.error is not None and archive.status == "stopped" and error.get("kind") == "power_invalid"
          and error.get("context") in TRIAL_CONTEXTS and error.get("time_s", -1.0) >= spec["from_s"]
          and last_accepted < spec["from_s"])
    final = archive.final_power_state
    check("第4步联合运行：valid 为假时不执行保护规则",
          "no Power event applied, load stays connected and not latched (Power design 5.5, thermal design 5.6)",
          f"events {len(archive.events)}, load_connected {final.load_connected}, trip_latched {final.trip_latched}",
          len(archive.events) == 0 and final.load_connected and not final.trip_latched)
    check("第4步联合运行：valid 为假的结果没有进入热导数",
          "every thermal_derivative call follows a valid Power result without event at the same instant with "
          "identical ports; the injected invalid result is followed by no thermal call",
          f"{counts}", counts["unusable_power_calls"] >= 1 and counts["unusable_reaching_thermal"] == 0
          and counts["thermal_without_usable_power"] == 0 and counts["thermal_port_mismatch"] == 0)
    invalid_same = (dict(runs[1].archive.error or {}) == error
                    and np.array_equal(runs[1].archive.accepted["state"], archive.accepted["state"]))
    case_record.metric("step4_invalid_from_s", spec["from_s"])
    case_record.metric("step4_invalid_stop_time_s", error.get("time_s"))
    case_record.metric("step4_invalid_context", error.get("context"))
    case_record.metric("step4_invalid_last_accepted_s", last_accepted)

    # event_required=True with a confirmed supply shortfall: located, supply_loss applied, recomputed; no restart
    spec = injection["shortfall"]
    window = spec["window_s"]

    def shortfall_solve(inputs: Any, state: Any, parameters: Any) -> Any:
        if window[0] <= inputs.time_s < window[1] and state.load_connected:
            return injected_result(inputs, valid=True, reason="supply_shortfall: injected by the EC-001 test")
        return ps.solve_power_allocation(inputs, state, parameters)

    command = cp.LoadCommand(spec["start_command_s"], "start", spec["start_command_id"])
    runs = [coupled_run(case, params, power, monkeypatch, "ec001.event", spec["run_duration_s"], shortfall_solve,
                        commands=(command,)) for _ in range(2)]
    run = runs[0]
    archive = run.archive
    events = [dict(event) for event in archive.events]
    counts = run.log.analyse()
    loss = events[0] if events else {}
    start = events[1] if len(events) > 1 else {}
    t_loss = float(loss.get("time_s", float("nan")))
    bracket = loss.get("bracket_s", [float("nan"), float("nan")])
    located = (archive.status == "completed" and len(events) == 2 and loss.get("kind") == "supply_loss"
               and loss.get("source") == "located" and 0.0 <= t_loss - window[0] <= tolerance
               and bracket[1] - bracket[0] <= tolerance)
    check("第4步联合运行：供电不足事件在容限内定位",
          f"run completes; supply_loss located by bisection at window start {window[0]} s within event_time_tol_s "
          f"{tolerance} s, bracket width <= tolerance",
          f"status {archive.status}, events {[(e['time_s'], e['kind'], e['source']) for e in events]}, located at "
          f"{t_loss!r} s, offset {t_loss - window[0]!r} s, bracket {bracket}", located)
    decision = loss.get("decision", {})
    recomputed = loss.get("recomputed", {})
    handled = (decision.get("valid") is True and decision.get("event_required") is True
               and decision.get("can_supply_request") is False
               and str(decision.get("reason", "")).startswith("supply_shortfall")
               and loss.get("before") == {"load_connected": True, "trip_latched": False}
               and loss.get("after") == {"load_connected": False, "trip_latched": True}
               and recomputed.get("P_load_W") == 0.0 and recomputed.get("Q_D_W") == 0.0)
    check("第4步联合运行：供电不足事件按失电保护处理并重算",
          "decision valid and event_required with reason supply_shortfall; apply_power_event disconnects and latches; "
          "Power recomputed at the same instant gives P_load_W = 0 and Q_D_W = 0",
          f"decision {decision}; before {loss.get('before')}; after {loss.get('after')}; recomputed {recomputed}", handled)
    times = archive.time_s
    p_load = archive.ports_W["P_load_W"]
    connected = archive.power_diagnostics["load_connected"]
    t_start = float(spec["start_command_s"])
    off = (times > t_loss) & (times < t_start)
    off_ok = bool(off.any()) and bool(np.all(p_load[off] == 0.0)) and not bool(np.any(connected[off]))
    recovered = [e for e in run.log.power_calls()
                 if window[1] <= e["time_s"] < t_start and not e["load_connected"] and e["valid"]
                 and not e["event_required"]]
    recovered_ok = bool(recovered) and all(e["can_supply"] for e in recovered)
    check("第4步联合运行：失电后热模块不重启负载",
          f"between {t_loss:.4f} s and the start command at {t_start} s every output sample has load_connected False "
          "and P_load_W = 0, although Power reports can_supply_request True after the window closes",
          f"{int(off.sum())} samples, P_load_W max {float(np.max(p_load[off])) if off.any() else None}, any connected "
          f"{bool(np.any(connected[off])) if off.any() else None}; {len(recovered)} Power calls after the window with "
          f"can_supply_request all True {recovered_ok}", off_ok and recovered_ok)
    after = times > t_start
    before = times < window[0]
    request = case["power"]["request_W"]
    start_ok = (start.get("kind") == "start" and start.get("source") == "command" and start.get("time_s") == t_start
                and start.get("decision", {}).get("can_supply_request") is True
                and start.get("after") == {"load_connected": True, "trip_latched": False}
                and bool(after.any()) and bool(np.all(connected[after]))
                and float(np.max(np.abs(p_load[after] - request))) <= 1e-9 * request
                and float(np.max(np.abs(p_load[before] - request))) <= 1e-9 * request)
    check("第4步联合运行：启动指令由 Power 接通负载",
          f"the start command at {t_start} s reconnects through apply_power_event with can_supply_request True; "
          f"P_load_W = {request} W before the event and after the command",
          f"start event {start.get('time_s')!r} s source {start.get('source')}, decision {start.get('decision')}, "
          f"after {start.get('after')}; P_load_W after the command "
          f"{sorted(set(np.round(p_load[after], 9).tolist())) if after.any() else None}", start_ok)
    state_event = np.array(loss.get("state", []), dtype=float)
    accepted_at = [np.array(y) for t, y in zip(archive.accepted["time_s"], archive.accepted["state"], strict=True)
                   if t == t_loss]
    continuous = (state_event.size == 8 and bool(accepted_at)
                  and all(np.array_equal(y, state_event) for y in accepted_at)
                  and np.array_equal(archive.state_at(t_loss), state_event))
    check("第4步联合运行：事件前后温度不跳变",
          "the accepted state at the event instant, the state of the event record and the state just after the "
          "event are identical; the event changes no temperature and no lithium fraction",
          f"accepted states at the instant {len(accepted_at)}, identical {continuous}, T_B {state_event[3] if state_event.size else None!r} K",
          continuous)
    check("第4步联合运行：event_required 为真的结果没有进入热导数",
          "no thermal_derivative call follows a Power result with event_required True; every thermal call follows a "
          "usable Power result at the same instant with identical ports",
          f"{counts}", counts["unusable_power_calls"] >= 1 and counts["unusable_reaching_thermal"] == 0
          and counts["thermal_without_usable_power"] == 0 and counts["thermal_port_mismatch"] == 0)
    event_same = ([(e["time_s"], e["kind"]) for e in runs[1].archive.events] == [(e["time_s"], e["kind"]) for e in events]
                  and np.array_equal(runs[1].archive.accepted["state"], archive.accepted["state"]))
    case_record.metric("step4_shortfall_window_start_s", window[0])
    case_record.metric("step4_supply_loss_time_s", t_loss)
    case_record.metric("step4_supply_loss_offset_s", t_loss - window[0])
    case_record.metric("step4_restart_command_s", t_start)
    case_record.metric("step4_event_tolerance_s", tolerance)

    # event_required=True with a device boundary: no protection rule, stop at the last accepted state inside the bound
    spec = injection["device_boundary"]

    def boundary_solve(inputs: Any, state: Any, parameters: Any) -> Any:
        if inputs.time_s >= spec["from_s"]:
            return injected_result(inputs, valid=True, reason="device_boundary: injected by the EC-001 test")
        return ps.solve_power_allocation(inputs, state, parameters)

    runs_b = [coupled_run(case, params, power, monkeypatch, "ec001.boundary", spec["run_duration_s"], boundary_solve)
              for _ in range(2)]
    run = runs_b[0]
    archive, error = run.archive, dict(run.archive.error or {})
    counts = run.log.analyse()
    last_accepted = float(np.max(archive.accepted["time_s"]))
    stop_time = float(error.get("time_s", float("nan")))
    bracket = error.get("bracket_s", [float("nan"), float("nan")])
    final = archive.final_power_state
    boundary_ok = (run.error is not None and archive.status == "stopped" and error.get("kind") == "device_boundary"
                   and stop_time == last_accepted and spec["from_s"] - tolerance <= stop_time < spec["from_s"]
                   and bracket[1] - bracket[0] <= tolerance and len(archive.events) == 0 and final.load_connected
                   and counts["unusable_reaching_thermal"] == 0 and counts["thermal_without_usable_power"] == 0)
    check("第4步联合运行：器件边界在最后一个已接受状态停止",
          f"device_boundary stop at the last accepted state inside the bound, within {tolerance} s before "
          f"{spec['from_s']} s; no event applied; no thermal call from an event result",
          f"status {archive.status}, kind {error.get('kind')}, time {stop_time!r} s, last accepted {last_accepted!r} s, "
          f"bracket {bracket}, events {len(archive.events)}, load_connected {final.load_connected}, log {counts}",
          boundary_ok)
    boundary_same = (dict(runs_b[1].archive.error or {}) == error
                     and np.array_equal(runs_b[1].archive.accepted["state"], archive.accepted["state"]))
    check("第4步联合运行：重复运行得到相同的处理结果",
          "a second run of each injection gives the same error record or the same events and accepted states",
          f"invalid {invalid_same}, supply shortfall {event_same}, device boundary {boundary_same}",
          invalid_same and event_same and boundary_same)
    case_record.metric("step4_device_boundary_from_s", spec["from_s"])
    case_record.metric("step4_device_boundary_stop_s", stop_time)
    check.finish()


def test_step5_one_orbit_joint_run(case: dict, hand: SimpleNamespace, params: Any, power: SimpleNamespace,
                                   monkeypatch: Any, case_record: Any) -> None:
    """Step 5: one orbit with Power; the battery temperature is updated only by Thermal and returned as T_B_K."""

    check = Checks(case_record)
    period = orbit_period_s(case)
    run = coupled_run(case, params, power, monkeypatch, "ec001.orbit", period, ps.solve_power_allocation,
                      energy_audit=True)
    archive = run.archive
    check("第5步：联合运行一圈完成", f"status completed from 0 s to one orbital period {period:.3f} s, no Power event",
          f"status {archive.status}, error {dict(archive.error) if archive.error else None}, end "
          f"{archive.final_thermal_state.time_s!r} s, events {len(archive.events)}, wall {run.wall_s:.2f} s",
          run.error is None and archive.status == "completed" and archive.final_thermal_state.time_s == period
          and len(archive.events) == 0)

    b = NODES.index("B")
    limits = tuple(power.parameters.battery.limits.T_range_K)
    states = np.asarray(archive.accepted["state"], dtype=float)
    accepted_b = states[:, b]
    sampled_b = np.asarray(archive.temperature_K, dtype=float)[:, b]
    finite_b = bool(np.all(np.isfinite(accepted_b))) and bool(np.all(np.isfinite(sampled_b)))
    low = least_of(*accepted_b, *sampled_b)
    high = worst_of(*accepted_b, *sampled_b)
    check("第5步：电池温度保持在替代程序温度范围内",
          f"every accepted state and every output sample of T_B is finite and inside {limits} K (Power stand-in "
          "battery.limits.T_range_K)",
          f"{accepted_b.size} accepted states and {sampled_b.size} output samples, all finite {finite_b}, T_B from "
          f"{low:.3f} K to {high:.3f} K",
          finite_b and accepted_b.size > 0 and sampled_b.size > 0 and limits[0] <= low and high <= limits[1])

    # The integrated state itself: six node temperatures and the two lithium fractions, one battery temperature.
    vector = list(archive.provenance["procedure"]["state_vector"])
    lithium = states[:, len(NODES):]
    lithium_ok = (lithium.shape[1] == 2 and bool(np.all(np.isfinite(lithium)))
                  and bool(np.all((lithium >= 0.0) & (lithium <= 1.0))))
    final_power = archive.final_power_state
    final_lithium = (getattr(final_power, "x_n", None), getattr(final_power, "x_p", None))
    last_lithium = tuple(states[-1, len(NODES):].tolist()) if states.shape[0] else None
    check("第5步：状态向量只含一个电池温度",
          "every accepted state of the coupled integration has 8 components: the six node temperatures S, J, C, B, D, "
          "R in K, of which component 4 is the only battery temperature, and the two lithium fractions, "
          "dimensionless in [0, 1], that Power reads as x_n and x_p (see the evaluation check); the final Power state "
          "holds the x_n and x_p of the last accepted state; the archived state vector label agrees",
          f"accepted states {states.shape}, components 7 and 8 from {least_of(*lithium.ravel()):.6g} to "
          f"{worst_of(*lithium.ravel()):.6g}, final Power state x_n, x_p {final_lithium}, last accepted state "
          f"{last_lithium}; output temperatures {archive.temperature_K.shape}; label {vector}",
          states.shape[1] == len(NODES) + 2 and states.shape[0] > 0 and lithium_ok and final_lithium == last_lithium
          and archive.temperature_K.shape[1] == len(NODES) and vector == list(NODES) + ["x_n", "x_p"])
    state_fields = temperature_fields(ps.PowerState, "PowerState")
    result_fields = temperature_fields(ps.PowerResult, "PowerResult")
    check("第5步：Power 状态不含电池温度，Power 结果只返回输入温度",
          "PowerState has no temperature field and the final Power state of the run has none; the only temperature "
          "field of PowerResult, including its nested BatteryResponse and SolarPowerResult, is "
          "PowerResult.battery.T_B_K, the input temperature returned with the battery response, which the check "
          "'第5步：电池响应不更新温度' compares with the input of every call",
          f"PowerState temperature fields {state_fields}; PowerResult temperature fields {result_fields}; final Power "
          f"state {type(final_power).__name__} has T_B_K {hasattr(final_power, 'T_B_K')}",
          not state_fields and result_fields == ["PowerResult.battery.T_B_K"] and not hasattr(final_power, "T_B_K"))

    # Every Power evaluation, by context: solver trials, accepted states and the accepted solution.
    counts = run.log.analyse()
    calls = run.log.power_calls()
    contexts = run.log.power_contexts()
    n_trial = sum(contexts.get(name, 0) for name in TRIAL_CONTEXTS)
    n_on_accepted = sum(contexts.get(name, 0) for name in ACCEPTED_CONTEXTS)
    unknown = counts["power_calls"] - n_trial - n_on_accepted
    archived_contexts = dict(archive.statistics.get("power_calls_by_context") or {})
    check("第5步：每次 Power 求值读取所用状态的电池温度",
          "every solve_power_allocation call reads T_B_K, x_n and x_p bit for bit from the state of its evaluation "
          "record at the same instant: solver trials in integration and event location, accepted states in boundary "
          "decisions and the accepted solution at output samples and energy audit points; every evaluation record "
          "follows a Power call and every Power call is closed by a record of one of these contexts",
          f"{counts['power_calls']} Power calls: solver trials {n_trial} "
          f"({', '.join(f'{name} {contexts.get(name, 0)}' for name in TRIAL_CONTEXTS)}), on accepted states or the "
          f"accepted solution {n_on_accepted} "
          f"({', '.join(f'{name} {contexts.get(name, 0)}' for name in ACCEPTED_CONTEXTS)}), other {unknown}; "
          f"{counts['power_state_mismatch']} state mismatches, {counts['record_without_power']} records without a "
          f"Power call; archive statistics power_calls_by_context {archived_contexts}",
          counts["power_calls"] > 0 and unknown == 0 and counts["power_state_mismatch"] == 0
          and counts["record_without_power"] == 0)
    first = calls[0] if calls else {}
    initial_b = float(run.initial.temperature_K[b])
    check("第5步：0 s 的首次 Power 求值读取 ThermalState 的电池初温",
          f"the first Power call is the boundary decision at 0 s on the initial accepted state and reads T_B_K = "
          f"{case['thermal']['initial_temperature_K']['B']} K, the battery temperature of the initial ThermalState",
          f"first call time {first.get('time_s')!r} s, context {first.get('context')!r}, T_B_K {first.get('T_B_K')!r} K; "
          f"initial ThermalState T_B {initial_b!r} K",
          first.get("time_s") == 0.0 and first.get("context") == "boundary" and first.get("T_B_K") == initial_b
          and initial_b == case["thermal"]["initial_temperature_K"]["B"])

    # Configuration level: the joint configuration and its archive hold one battery initial temperature (thermal
    # design 9.4, outside the listed basis of the case, and the Power design: Thermal keeps the battery initial
    # temperature). Every key starting with T_B in the Power scene record, the Power parameter provenance and the
    # archive provenance is collected, together with the initial accepted state.
    def battery_key(key: str) -> bool:
        return key.startswith("T_B")

    copies = [("ThermalState.temperature_K[3]", initial_b),
              ("archive.accepted.state[0][3]", float(states[0, b]) if states.shape[0] else None)]
    copies += [(f"Power scene record.{path}", value) for path, value in find_keys(power.scene, battery_key)]
    copies += [(f"PowerParameters.provenance.{path}", value)
               for path, value in find_keys(power.parameters.provenance, battery_key)]
    copies += [(f"archive.provenance.{path}", value) for path, value in find_keys(archive.provenance, battery_key)]
    numeric = [(path, value) for path, value in copies
               if isinstance(value, numbers.Real) and not isinstance(value, bool)]
    distinct = sorted({float(value) for _, value in numeric})
    initial_power_state = ps.power_state_from_scene(power.scene, archive.run_id)
    archived_initial = dict(archive.provenance["power"]["initial_state"])
    check("第5步：联合配置中电池初温只有一份",
          f"one battery initial temperature, the {case['thermal']['initial_temperature_K']['B']} K of the initial "
          "ThermalState, in the joint configuration (thermal design 9.4, outside the listed basis of EC-001; Power "
          "design: the battery initial temperature is kept by Thermal): the initial accepted state and every T_B "
          "entry of the Power scene record, the Power parameter provenance and the archive provenance hold this value "
          "bit for bit; PowerState and the archived Power initial state carry no battery temperature",
          f"entries {copies}; distinct values {distinct}; PowerState fields "
          f"{[item.name for item in dataclasses.fields(initial_power_state)]}; archived Power initial state keys "
          f"{sorted(archived_initial)}; the stand-in scene record requires initial_state.T_B_K for its own initial "
          "check of the zero-current voltage and the temperature range, a field that the Power design's "
          "initial_state_fields do not list, and the test fills it with the ThermalState value",
          len(numeric) == len(copies) and distinct == [initial_b]
          and initial_b == case["thermal"]["initial_temperature_K"]["B"] and "T_B_K" not in archived_initial
          and not hasattr(initial_power_state, "T_B_K"))
    calls_at: dict[float, list[dict[str, Any]]] = {}
    for entry in calls:
        calls_at.setdefault(entry["time_s"], []).append(entry)
    missing = 0
    for moment, state in zip(archive.accepted["time_s"], states, strict=True):
        if not any(e["T_B_K"] == state[b] and e["x_n"] == state[6] and e["x_p"] == state[7]
                   for e in calls_at.get(float(moment), [])):
            missing += 1
    n_accepted = len(archive.accepted["time_s"])
    check("第5步：每个已接受状态的电池温度返回 Power",
          "for every accepted state a Power evaluation at the same instant reads exactly its T_B, x_n and x_p",
          f"{n_accepted} accepted states, {missing} without such a call", n_accepted > 0 and missing == 0)
    check("第5步：热导数只接收有效 Power 结果的原值端口",
          "every thermal_derivative call follows a valid Power result without event at the same instant; ports and "
          "battery temperature are identical",
          f"{counts['thermal_calls']} thermal calls, without usable Power {counts['thermal_without_usable_power']}, "
          f"port mismatches {counts['thermal_port_mismatch']}, T_B mismatches {counts['thermal_T_B_mismatch']}",
          counts["thermal_calls"] > 0 and counts["thermal_without_usable_power"] == 0
          and counts["thermal_port_mismatch"] == 0 and counts["thermal_T_B_mismatch"] == 0)
    check("第5步：ThermalEvaluation 的 T_B_K 是输入温度的副本",
          "T_B_K = temperature_K[3] and T_J_K = temperature_K[1] of the evaluated state in every thermal call",
          f"{counts['evaluation_copy_mismatch']} mismatches in {counts['thermal_calls']} calls",
          counts["evaluation_copy_mismatch"] == 0)
    check("第5步：电池响应不更新温度",
          "the battery response of every usable Power result echoes the input T_B_K unchanged",
          f"{counts['battery_echo_mismatch']} mismatches", counts["battery_echo_mismatch"] == 0)

    valid = np.flatnonzero(archive.sample_valid)
    worst = {node: 0.0 for node in NODES}
    limited_samples = 0
    limited_worst = 0.0
    unexported_parts = []
    reasons = archive.power_diagnostics["reason"]
    for k in valid:
        moment = float(archive.time_s[k])
        temperature = dict(zip(NODES, (float(v) for v in archive.temperature_K[k]), strict=True))
        ports = {name: float(archive.ports_W[name][k]) for name in PORTS}
        sample = run.provider.sample(moment)
        orbit_input, earth_flux = sample.orbit_input, sample.earth_flux
        point = SimpleNamespace(
            quaternion=np.array(orbit_input["quaternion_xyzw"], dtype=float),
            position=np.array(orbit_input["position_m"], dtype=float),
            sun=np.array(orbit_input["sun_position_m"], dtype=float), G=float(orbit_input["G_W_m2"]),
            albedo=[float(v) for v in earth_flux["albedo_W_m2"]],
            infrared=[float(v) for v in earth_flux["infrared_W_m2"]], temperature=temperature)
        surface_point = reference_surface(hand, point)
        terms = reference_terms(hand, temperature, surface_point["Q_env"], surface_point["Q_emit"], ports)
        errors = {}
        for index, node in enumerate(NODES):
            gross = math.fsum(abs(v) for v in terms[node])
            errors[node] = abs(hand.C[node] * float(archive.dT_dt_K_s[k, index]) - math.fsum(terms[node])) / gross
            worst[node] = worst_of(worst[node], errors[node])
        if str(reasons[k]).startswith("charge_limited"):
            cosine = surface_point["cos"][0]  # SolarArray01 front, the normal of the Power solar array
            p_max = hand.efficiency * hand.cell_area_m2 * point.G * max(0.0, cosine)
            limited_samples += 1
            limited_worst = worst_of(limited_worst, errors["S"])
            unexported_parts.append(p_max - ports["P_pv_W"])
    sample_worst = worst_of(*worst.values())
    smallest_unexported = least_of(*unexported_parts)
    check("第5步：输出样本的四个端口按 T3 进入对应组件",
          "at every valid output sample C_i dT_i of all six nodes equals the T3 terms rebuilt independently from the "
          "archived ports and temperatures, the orbit and Earth flux inputs of the same instant (own T4) and hand C "
          "and R; |error| / gross <= 1e-12",
          f"{len(valid)} of {archive.time_s.size} samples, largest errors {({k: f'{v:.3g}' for k, v in worst.items()})}",
          len(valid) == archive.time_s.size and sample_worst <= REL_TOL)
    check("第5步：限充时段太阳能板使用实际 P_pv",
          "at charge_limited samples P_pv_W < P_pv_max (hand, from the same orbit sample) and the S balance uses the "
          "actual P_pv_W",
          f"{limited_samples} charge_limited samples, smallest unexported power {smallest_unexported!r} W, largest S "
          f"error {limited_worst:.3g}",
          limited_samples > 0 and smallest_unexported > 0.0 and limited_worst <= REL_TOL)

    # Battery node audit: integrate (Q_B - q_BR) / C_B along the accepted solution with Power re-evaluated by the test
    nodes, weights = np.polynomial.legendre.leggauss(3)
    settings = archive.solver_settings
    n_state = archive.accepted["state"].shape[1]
    parts = []
    bound_parts = []
    for t_old, t_new in zip(archive.steps["t_old_s"], archive.steps["t_new_s"], strict=True):
        width = float(t_new - t_old)
        if width <= 0.0:
            continue
        for node, weight in zip(nodes, weights, strict=True):
            moment = float(t_old) + 0.5 * width * (1.0 + float(node))
            state = archive.state_at(moment)
            sample = run.provider.sample(moment)
            result = ps.solve_power_allocation(
                ps.PowerInputs(run_id=archive.run_id, instance_id="Sat01", time_s=moment,
                               environment=sample.power_environment, P_request_W=case["power"]["request_W"],
                               T_B_K=float(state[b])),
                ps.PowerState(run_id=archive.run_id, instance_id="Sat01", time_s=moment, x_n=float(state[6]),
                              x_p=float(state[7]), load_connected=True, trip_latched=False, handled_command_ids=()),
                power.parameters)
            q_br = (float(state[b]) - float(state[5])) / hand.R["BR"]
            parts.append(0.5 * width * float(weight) * (result.Q_B_W - q_br) / hand.C["B"])
        y_old = archive.state_at(float(t_old))
        bound_parts.append(math.sqrt(n_state) * (settings["atol_T_K"] + settings["rtol"] * abs(float(y_old[b]))))
    integral = math.fsum(parts)
    change = float(archive.final_thermal_state.temperature_K[b] - run.initial.temperature_K[b])
    residual = change - integral
    bound = math.fsum(bound_parts)
    check("第5步：电池温度变化等于热模块电池方程的积分",
          "T_B(end) - T_B(0) equals the integral of (Q_B - q_BR) / C_B along the accepted solution, with Q_B from "
          "Power at each point and hand C_B and R_BR; |residual| <= sum over steps of sqrt(n) (atol_T + rtol |T_B|)",
          f"change {change!r} K, integral {integral!r} K, residual {residual!r} K, bound {bound!r} K over "
          f"{len(bound_parts)} steps", abs(residual) <= bound)

    audit = archive.energy_audit or {}
    statistics = archive.statistics
    entries = [boundary.time_s for boundary in archive.eclipse_boundaries if boundary.is_eclipse_entry]
    exits = [boundary.time_s for boundary in archive.eclipse_boundaries if boundary.is_eclipse_exit]
    case_record.metric("step5_eclipse_entry_s", entries[0] if entries else None)
    case_record.metric("step5_eclipse_exit_s", exits[0] if exits else None)
    case_record.metric("step5_period_s", period)
    case_record.metric("step5_T_B_min_K", low)
    case_record.metric("step5_T_B_max_K", high)
    case_record.metric("step5_T_B_limits_K", list(limits))
    case_record.metric("step5_power_calls", counts["power_calls"])
    case_record.metric("step5_power_calls_by_context", {name: contexts.get(name, 0)
                                                        for name in TRIAL_CONTEXTS + ACCEPTED_CONTEXTS})
    case_record.metric("step5_power_calls_solver_trials", n_trial)
    case_record.metric("step5_power_calls_on_accepted_states", n_on_accepted)
    case_record.metric("step5_thermal_calls", counts["thermal_calls"])
    case_record.metric("step5_accepted_states", n_accepted)
    case_record.metric("step5_state_components", int(states.shape[1]))
    case_record.metric("step5_first_T_B_K", first.get("T_B_K"))
    case_record.metric("step5_first_context", first.get("context"))
    case_record.metric("step5_battery_initial_entries", copies)
    case_record.metric("step5_battery_initial_distinct_K", distinct)
    case_record.metric("step5_samples", int(archive.time_s.size))
    case_record.metric("step5_max_sample_relative_error", sample_worst)
    case_record.metric("step5_charge_limited_samples", limited_samples)
    case_record.metric("step5_smallest_unexported_W", smallest_unexported)
    case_record.metric("step5_battery_audit_residual_K", residual)
    case_record.metric("step5_battery_audit_bound_K", bound)
    case_record.metric("step5_battery_change_K", change)
    case_record.metric("step5_Q_B_range_W", [least_of(*archive.ports_W["Q_B_W"]), worst_of(*archive.ports_W["Q_B_W"])])
    case_record.metric("step5_energy_audit_relative_residual", audit.get("relative_residual"))
    case_record.metric("step5_accepted_steps", statistics.get("accepted_steps"))
    case_record.metric("step5_rejected_steps", statistics.get("rejected_steps"))
    case_record.metric("step5_range_warnings", len(archive.range_warnings))
    case_record.metric("step5_wall_s", run.wall_s)
    check.finish()


def _finite(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _sci_cn(value: Any) -> str:
    """Power-of-ten form of the report rules, for example 6.0×10^{−16}: U+2212 minus signs, the exponent inside
    ^{...}, which the report builder renders as a superscript; 未得到 for a missing or non-finite value."""

    if not _finite(value):
        return "未得到"
    value = float(value)
    if value == 0.0:
        return "0"
    exponent = math.floor(math.log10(abs(value)))
    if -3 <= exponent <= 3:  # no power of ten needed: three significant digits as a plain decimal
        return f"{value:.{max(0, 2 - exponent)}f}".replace("-", "−")
    mantissa = round(value / 10.0 ** exponent, 1)
    if abs(mantissa) >= 10.0:
        mantissa, exponent = round(mantissa / 10.0, 1), exponent + 1
    return f"{mantissa:.1f}".replace("-", "−") + "×10^{" + str(exponent).replace("-", "−") + "}"


def _num(value: Any, digits: int = 2) -> str:
    """Fixed-point number with U+2212 for negative values; 未得到 for a missing or non-finite value."""

    if not _finite(value):
        return "未得到"
    text = f"{float(value):.{digits}f}"
    if float(text) == 0.0:
        text = text.lstrip("-")
    return text.replace("-", "−")


def _int(value: Any) -> str:
    return str(int(value)) if isinstance(value, numbers.Integral) and not isinstance(value, bool) else "未得到"


def _fractions_cn(fractions: Any) -> str:
    """0.75 倍、0.5 倍与零 for the curtailed fractions of step 3."""

    words = ["零" if float(f) == 0.0 else f"{float(f):g} 倍" for f in fractions or [] if _finite(f)]
    if not words:
        return "未得到"
    return words[0] if len(words) == 1 else "、".join(words[:-1]) + "与" + words[-1]


def test_zz_summary(case_record: Any) -> None:
    """Chinese summary and anomaly record of the case, built from the recorded checks and metrics.

    Every statement names the checks behind it. It is written as a success only when all of them passed; otherwise the
    statement says that they failed or were not executed, and the anomaly record lists them.
    """

    m = case_record.metrics
    outcome_of: dict[str, bool] = {}
    for item in case_record.checks:
        outcome_of[item["name"]] = outcome_of.get(item["name"], True) and bool(item["passed"])
    referenced: list[str] = []

    def claim(topic: str, names: list[str], text: str) -> str:
        referenced.extend(names)
        topic = topic + (" " if topic[-1].isascii() else "")
        if any(outcome_of.get(name) is False for name in names):
            return f"{topic}的检查未通过，见异常记录。"
        if any(name not in outcome_of for name in names):
            return f"{topic}的检查未执行，见异常记录。"
        return text

    port_errors = [m.get(f"step1_{port}_max_relative_error") for port in PORTS]
    step1 = worst_of(*port_errors) if all(_finite(value) for value in port_errors) else float("nan")
    q_b = list(m.get("step2_negative_Q_B_W") or [])
    big = m.get("step2_symmetry_Q_B_W")
    limits = m.get("step5_T_B_limits_K") or [None, None]
    residual = m.get("step5_battery_audit_residual_K")
    by_context = m.get("step5_power_calls_by_context") or {}
    distinct = m.get("step5_battery_initial_distinct_K") or []
    rejected_names = ["第4步：P_pv_W 为负被拒绝", "第4步：P_load_W 为负被拒绝", "第4步：Q_D_W 为负被拒绝",
                      "第4步：P_pv 略大于 absorbed_solar_S_W 被拒绝", "第4步：P_pv 大于 absorbed_solar_S_W 被拒绝",
                      "第4步：日食时 P_pv 大于零被拒绝", "第4步：带完整端口但 valid 为假的输入被拒绝",
                      "第4步：带完整端口但 event_required 为真的输入被拒绝"]
    rejected_names += [name for code, kind in NATURAL_CODES for name in step4_natural_names(code, kind)[1:]]
    ownership = ["第5步：联合配置中电池初温只有一份", "第5步：0 s 的首次 Power 求值读取 ThermalState 的电池初温",
                 "第5步：状态向量只含一个电池温度", "第5步：Power 状态不含电池温度，Power 结果只返回输入温度",
                 "第5步：每次 Power 求值读取所用状态的电池温度", "第5步：每个已接受状态的电池温度返回 Power",
                 "第5步：电池响应不更新温度", "第5步：电池温度变化等于热模块电池方程的积分"]
    parts = [
        "本用例在 Thermal 目录用项目解释器执行。Power 结果由 sdtwin_sim.power_stand_in 给出，该程序按供电模块设计报告的接口、"
        "式 P1 至 P11 以及 valid 与 event_required 的规定编写，是替代程序，不是正式的供电模块；联合运行使用 sdtwin_sim.coupled。",
        claim("前提用例 HT-002", ["前提：HT-002 已通过"],
              "前提用例 HT-002 的结果文件记录为通过，"
              f"{_int(m.get('precondition_HT_002_checks'))} 项检查全部通过。"),
        claim("装配热容与热阻", ["前提：装配热容与 T5 手算一致", "前提：装配热阻与 T5 手算一致"],
              "热容与热阻由 assemble_thermal_parameters 按本用例数据装配，与 T5 手算的最大相对误差分别为 "
              f"{_sci_cn(m.get('premise_C_max_relative_error'))} 与 {_sci_cn(m.get('premise_R_max_relative_error'))}。"),
        claim("功率端口与实例对应", ["前提：四个功率端口的实例对应一致", "第1步：端口与实例错配的联合配置被拒绝"],
              "四个功率端口分别对应 SolarArray01、Compute01、Battery01 与 PDU01，端口与实例错配的联合配置在积分前被拒绝。"),
        claim("第1步输入范围", ["前提：absorbed_solar_S_W 与手算一致", "第1步：功率取值覆盖用例输入范围"],
              f"第1步在同一时刻逐个改变四个功率共 {_int(m.get('step1_variations'))} 组，P_pv 取零至本次 absorbed_solar_S_W "
              f"{_num(m.get('absorbed_solar_S_W'))} W，该值与手算一致，P_load 取零至额定功率 {_num(m.get('rated_load_W'), 0)} W，"
              "Q_B 取正值与负值，Q_D 取正值。"),
        claim("第1步功率作用组件",[step1_names(port)[0] for port in PORTS],
              "P_pv 只改变太阳能板，P_load 只改变计算节点，Q_B 只改变电池，Q_D 只改变电源设备，其余五个组件的导数变化最大为 "
              f"{_sci_cn(m.get('step1_max_other_node_change_K_s'))} K/s。"),
        claim("第1步导数变化量", [name for port in PORTS for name in step1_names(port)[1:]],
              f"导数变化与功率变化除以组件热容的手算值相比，最大相对误差为 {_sci_cn(step1)}，各组件储存热能的变化率之和与 T1 相比，"
              f"最大相对误差为 {_sci_cn(m.get('step1_max_T1_relative_error'))}，"
              "验收限值为 1×10^{−12}。"),
        claim("第1步独立实现核对", ["第1步：六个组件导数与独立实现一致", "第1步：替代程序 Power 结果进入 T3 与独立实现一致",
                                "第1步：ThermalInputs 保留端口数值与符号", "第1步：同一时刻的输入不产生温区警告"],
              "本用例在所用时刻另用独立实现的 T2 至 T4 核对六个组件的温度导数，替代程序给出的四个端口也一并核对，最大相对偏差为 "
              f"{_sci_cn(m.get('step1_max_full_derivative_relative_error'))}，ThermalInputs 保留各端口的数值与符号，没有温区警告。"),
        claim("第2步负 Q_B 导数变化",["第2步：Q_B 取负值时电池温度导数依次减小", "第2步：负 Q_B 引起的导数减小量与手算一致"],
              f"第2步 Q_B 取 {'、'.join(_num(value, 1) + ' W' for value in q_b) or '未得到'} 时电池温度导数依次减小，"
              "与 Q_B 取零时相比，导数的变化量等于 Q_B 除以电池热容，最大相对误差为 "
              f"{_sci_cn(m.get('step2_fixed_max_relative_error'))}。"),
        claim("第2步 Q_B 符号保留",["第2步：Q_B 保留符号不被截断"],
              f"Q_B 取 {_num(big, 1)} W 与 {_num(-big if _finite(big) else None, 1)} W 时两个电池温度导数之差等于 "
              f"{_num(2.0 * big if _finite(big) else None, 1)} W 除以电池热容，相对误差为 "
              f"{_sci_cn(m.get('step2_symmetry_relative_error'))}，ThermalInputs 保留 Q_B 的负号。"),
        claim("第2步替代程序充电工况", ["第2步：替代程序在额定负载下小电流充电给出负 Q_B",
                                    "第2步：替代程序的负 Q_B 进入电池方程与手算一致"],
              f"替代程序的请求功率等于计算节点额定功率 {_num(m.get('step2_stand_in_request_W'), 0)} W，太阳能板最大可发功率比所需"
              f"配电入口功率多 {_num(m.get('step2_stand_in_surplus_W'), 0)} W，电池以小电流充电吸收这部分余量，单体电流为 "
              f"{_num(m.get('step2_stand_in_cell_current_A'), 3)} A，Q_B 为 {_num(m.get('step2_stand_in_Q_B_W'), 4)} W，"
              "热模块保留负号，电池温度导数与手算的相对误差为 "
              f"{_sci_cn(m.get('step2_stand_in_rate_relative_error'))}，与 Q_B 取零时相比，导数变化量的相对误差为 "
              f"{_sci_cn(m.get('step2_stand_in_drop_relative_error'))}。"),
        claim("第3步降低 P_pv", ["第3步：Power 替代程序最大可发功率与手算一致", "第3步：降低 P_pv 后未输出功率留在太阳能板",
                              "第3步：降低 P_pv 时其余组件导数不变", "第3步：降低 P_pv 后整体储热速率增加量等于少输出的电功率"],
              f"第3步替代程序给出的最大可发功率为 {_num(m.get('step3_P_pv_max_W'))} W，与手算一致。把 P_pv 由该值依次降为其 "
              f"{_fractions_cn(m.get('step3_curtailed_fractions'))}，太阳能板储存热能的变化率增加量等于少输出的电功率，最大相对误差为 "
              f"{_sci_cn(m.get('step3_fixed_panel_relative_error'))}，各组件储存热能的变化率之和的增加量同样等于少输出的电功率，"
              f"最大相对误差为 {_sci_cn(m.get('step3_fixed_T1_relative_error'))}，其余五个组件的导数不变，少输出的电功率全部留在"
              "太阳能板的能量收支中。"),
        claim("第3步替代程序限充", ["第3步：替代程序限充时降低实际 P_pv", "第3步：限充少输出的电功率留在太阳能板能量收支中"],
              f"替代程序限充时实际 P_pv 为 {_num(m.get('step3_stand_in_P_pv_W'))} W，少输出 "
              f"{_num(m.get('step3_stand_in_curtailed_W'))} W，太阳能板储存热能的变化率增加同样数值，相对误差为 "
              f"{_sci_cn(m.get('step3_stand_in_relative_error'))}。"),
        claim("第4步替代程序不可用结果",[step4_natural_names(code, kind)[0] for code, kind in NATURAL_CODES],
              "第4步由替代程序给出四种不可用结果，temperature_out_of_range 与 invalid_input 的 valid 为假，supply_shortfall 与 "
              "device_boundary 的 event_required 为真，四种结果都不含功率端口。"),
        claim("第4步异常输入", rejected_names,
              "逐项注入 P_pv_W、P_load_W 或 Q_D_W 为负，P_pv 略大于 absorbed_solar_S_W 或比它大 "
              f"{_num(OVER_BOUND_W, 0)} W，日食时 P_pv 大于零，上述四种不可用结果，以及带完整端口但 valid 为假或 event_required "
              "为真的输入，热模块共 "
              f"{_int(m.get('step4_thermal_rejections'))} 次报出 ThermalInputError，报错写明出错的功率字段或 Power 结果不可用，"
              "不返回导数，也不修补功率，重复注入得到相同的错误类别与信息。"),
        claim("第4步正常输入对照", ["第4步：P_pv 等于 absorbed_solar_S_W 时正常计算", "第4步：有效且无事件的同类输入正常计算",
                                "第4步：功率与热状态不在同一时刻时被拒绝", "第4步：热模块输出不含负载启停字段"],
              "P_pv 等于 absorbed_solar_S_W 以及日食时为零的输入正常计算，有效且无事件的同类输入正常计算，功率与热状态不在同一时刻时"
              "被拒绝，ThermalEvaluation 不含负载启停字段。"),
        claim("第4步联合运行注入 valid 为假",["第4步联合运行：valid 为假时报告错误并停止",
                                            "第4步联合运行：valid 为假时不执行保护规则",
                                            "第4步联合运行：valid 为假的结果没有进入热导数"],
              f"联合运行中自 {_num(m.get('step4_invalid_from_s'), 0)} s 起注入 valid 为假的结果，运行在 "
              f"{_num(m.get('step4_invalid_stop_time_s'))} s 的试算中报出 power_invalid 并停止，已接受状态止于 "
              f"{_num(m.get('step4_invalid_last_accepted_s'))} s，没有执行保护规则，该结果没有进入热导数。"),
        claim("第4步联合运行注入供电不足",["第4步联合运行：供电不足事件在容限内定位",
                                          "第4步联合运行：供电不足事件按失电保护处理并重算",
                                          "第4步联合运行：失电后热模块不重启负载", "第4步联合运行：启动指令由 Power 接通负载",
                                          "第4步联合运行：事件前后温度不跳变",
                                          "第4步联合运行：event_required 为真的结果没有进入热导数"],
              f"自 {_num(m.get('step4_shortfall_window_start_s'), 0)} s 起注入 event_required 为真且原因为供电不足的结果，边界定位在 "
              f"{_num(m.get('step4_supply_loss_time_s'), 4)} s，与注入起点相差 {_num(m.get('step4_supply_loss_offset_s'), 5)} s，"
              f"小于容限 {_num(m.get('step4_event_tolerance_s'), 3)} s，失电保护断开负载，Power 在同一时刻重算，事件前后温度不跳变，"
              f"此后负载保持断开，直到 {_num(m.get('step4_restart_command_s'), 0)} s 的启动指令由 Power 接通负载，热模块不决定负载"
              "重启，event_required 为真的结果没有进入热导数。"),
        claim("第4步联合运行注入器件边界",["第4步联合运行：器件边界在最后一个已接受状态停止"],
              f"自 {_num(m.get('step4_device_boundary_from_s'), 0)} s 起注入原因为器件边界的结果时，运行停在 "
              f"{_num(m.get('step4_device_boundary_stop_s'), 4)} s 的已接受状态，没有施加事件，该结果没有进入热导数。"),
        claim("第4步重复运行", ["第4步联合运行：重复运行得到相同的处理结果"], "三种注入各重复运行一次，处理结果相同。"),
        claim("第5步联合运行", ["第5步：联合运行一圈完成", "第5步：电池温度保持在替代程序温度范围内"],
              f"第5步与 Power 联合运行一圈 {_num(m.get('step5_period_s'), 1)} s，日食段为 "
              f"{_num(m.get('step5_eclipse_entry_s'), 1)} s 至 {_num(m.get('step5_eclipse_exit_s'), 1)} s，没有 Power 事件，电池温度在 "
              f"{_num(m.get('step5_T_B_min_K'))} K 至 {_num(m.get('step5_T_B_max_K'))} K 之间，位于替代程序 {_num(limits[0])} K 至 "
              f"{_num(limits[1])} K 的温度范围内。"),
        claim("第5步电池初温", ["第5步：联合配置中电池初温只有一份", "第5步：0 s 的首次 Power 求值读取 ThermalState 的电池初温"],
              f"联合配置与运行归档中的电池初温只有 ThermalState 中的 {_num(distinct[0] if len(distinct) == 1 else None)} K "
              "这一个数值。替代程序的场景记录要求 initial_state.T_B_K 字段，供其初始零电流电压与温度范围检查使用。供电模块设计报告"
              "规定电池初温由 Thermal 保存，其 initial_state_fields 不含该字段，本用例因此在该字段填入 ThermalState 的同一数值。"
              "PowerState 与归档的 Power 初始状态都不含电池温度。这一配置检查对应设计报告第 9.4 节电池初温只有一份的规定，第 9.4 节"
              f"不在本用例列出的设计依据中。0 s 的首次 Power 求值在初始已接受状态上进行，读取的 T_B_K 为 "
              f"{_num(m.get('step5_first_T_B_K'))} K。"),
        claim("第5步状态向量", ["第5步：状态向量只含一个电池温度", "第5步：Power 状态不含电池温度，Power 结果只返回输入温度"],
              f"联合积分的 {_int(m.get('step5_accepted_states'))} 个已接受状态都由六个组件温度与 x_n、x_p 共 "
              f"{_int(m.get('step5_state_components'))} 个分量组成，电池温度只占一个分量，x_n 与 x_p 都在零与一之间；PowerState "
              "不含温度字段，Power 结果中的温度只有电池响应返回的输入温度 T_B_K。"),
        claim("第5步 Power 求值", ["第5步：每次 Power 求值读取所用状态的电池温度", "第5步：每个已接受状态的电池温度返回 Power"],
              f"{_int(m.get('step5_power_calls'))} 次 Power 求值中，{_int(m.get('step5_power_calls_solver_trials'))} 次为积分"
              f"与边界定位中的求解器试算，其中积分 {_int(by_context.get('integration'))} 次、边界定位 "
              f"{_int(by_context.get('event_location'))} 次；其余 {_int(m.get('step5_power_calls_on_accepted_states'))} 次在已接受"
              f"状态或已接受解上求值，不属于试算，其中已接受状态上的判断 {_int(by_context.get('boundary'))} 次、输出采样 "
              f"{_int(by_context.get('output'))} 次、能量核算 {_int(by_context.get('energy_audit'))} 次。每次求值读取的 T_B_K、x_n "
              f"与 x_p 都与所用状态逐位相同，{_int(m.get('step5_accepted_states'))} 个已接受状态的电池温度都作为 T_B_K 返回 Power。"),
        claim("第5步热导数输入", ["第5步：热导数只接收有效 Power 结果的原值端口", "第5步：ThermalEvaluation 的 T_B_K 是输入温度的副本",
                              "第5步：电池响应不更新温度"],
              f"{_int(m.get('step5_thermal_calls'))} 次热导数计算接收的四个端口与电池温度都与同一时刻有效 Power 结果及其输入相同，"
              "ThermalEvaluation 与电池响应给出的 T_B_K 都等于输入温度。"),
        claim("第5步输出样本", ["第5步：输出样本的四个端口按 T3 进入对应组件", "第5步：限充时段太阳能板使用实际 P_pv"],
              f"{_int(m.get('step5_samples'))} 个输出样本的六个组件导数与独立重建的 T3 相比，最大相对偏差为 "
              f"{_sci_cn(m.get('step5_max_sample_relative_error'))}，其中 {_int(m.get('step5_charge_limited_samples'))} 个限充样本"
              "的太阳能板使用降低后的实际 P_pv。"),
        claim("第5步电池温度积分", ["第5步：电池温度变化等于热模块电池方程的积分"],
              f"电池温度一圈变化 {_num(m.get('step5_battery_change_K'), 4)} K，沿已接受解对热模块电池方程积分的结果与之相差 "
              f"{_sci_cn(abs(residual) if _finite(residual) else None)} K，小于由求解容限给出的 "
              f"{_num(m.get('step5_battery_audit_bound_K'), 3)} K。"),
        claim("电池温度单一归属", ownership, "电池温度只在热模块中更新，并作为 T_B_K 返回 Power。"),
    ]
    summary = "".join(parts)
    case_record.summary(summary)
    failed = list(dict.fromkeys(item["name"] for item in case_record.checks if not item["passed"]))
    missing = [name for name in dict.fromkeys(referenced) if name not in outcome_of]
    notes = []
    if "前提：HT-002 已通过" in failed:
        notes.append("前提用例 HT-002 的结果文件没有记录通过，本用例的前置条件未得到证实。")
    if failed:
        notes.append("以下检查未通过：" + "；".join(failed) + "。")
    if missing:
        notes.append("以下检查未执行：" + "；".join(missing) + "。")
    case_record.anomalies("".join(notes) or "无")
    assert summary
