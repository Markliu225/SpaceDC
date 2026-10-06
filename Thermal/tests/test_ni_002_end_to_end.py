"""NI-002 end-to-end run and result archive (thermal design 3.3, 6.3, chapter 7 and 9.4; requirements TH-01, TH-02).

One 24 h run of the example Sat01 scene couples Thermal with Orbit and Power: a two-body 400 km orbit from Orbit's
``TwoBodyPropagator``, the Earth-to-Sun vector from ``sun_position_ephemeris`` (builtin), ``G`` from ``sun_intensity``
with eclipse, Earth albedo and infrared from ``sdtwin_sim.earth_flux`` and the Power results of
``sdtwin_sim.power_stand_in``. The Power program is a stand-in written from the Power design report; it is not the
production Power module. The scenario has 15 complete eclipses and the entry of a 16th, a load stop and start pair,
one injected Power result with ``event_required`` True (a confirmed supply shortfall in a known window), one physical
battery constraint event (a supply shortfall of the stand-in battery under a request ramp in eclipse) and refused and
accepted restart commands. A second run with the same inputs checks reproducibility; a third run injects one Power
result with ``valid`` False.

Every trial is logged by spies that wrap ``prepare_surface_environment``, the Power ``solve`` and ``apply_event``,
``thermal_derivative`` and the SciPy RK45 class of the coupled runner (they record and pass values through unchanged).
References are independent of the code under test: an analytic circular orbit with a cylindrical Earth shadow for the
eclipse times, Orbit's ``sun_intensity`` for ``G``, the published Dormand-Prince weights to rebuild every accepted state
from the derivatives the thermal module returned, direct Power stand-in evaluations at the located boundaries, the asset
files for the parameter versions and the design equations T2 and T3 for the archived heat flows. Case data:
``tests/data/ni_002/ni002_scenario.json``; references: ``tests/data/ni_002/ni002_reference.py``.
"""

from __future__ import annotations

import ast
import bisect
import dataclasses
import hashlib
import importlib.util
import json
import math
import sys
import time
import warnings
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from scipy.integrate import RK45
from scipy.spatial.transform import Rotation

import ntu_space_dynamics
import ntu_space_dynamics.power
from ntu_space_dynamics import (
    AttitudeEphemeris,
    ClassicalElements,
    OrbitState,
    TwoBodyPropagator,
    oe_to_rv,
    sun_intensity,
    sun_position_ephemeris,
)
from ntu_space_dynamics.time import time_grid
from sdtwin_sim import coupled as cp
from sdtwin_sim import power_stand_in as ps
from sdtwin_sim import scene as sc
from thermal import (
    ThermalInputs,
    ThermalRangeWarning,
    ThermalState,
    assemble_thermal_parameters,
    prepare_surface_environment,
    thermal_derivative,
)

pytestmark = pytest.mark.case("NI-002")

TESTS_DIR = Path(__file__).resolve().parent
THERMAL_DIR = TESTS_DIR.parent
DATA_DIR = TESTS_DIR / "data" / "ni_002"
RESULTS_DIR = TESTS_DIR / "results"
SPEC_PATH = DATA_DIR / "ni002_scenario.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
SCENE_PATH = (DATA_DIR / SPEC["scene_file"]).resolve()
ARCHIVE_PATH = RESULTS_DIR / "NI-002_archive.json"
PRERUN_PATH = RESULTS_DIR / "NI-002_prerun.json"

MU_EARTH_M3_S2 = 3.986004418e14  # WGS 84 value, written here for the independent circular orbit
NODES = ("S", "J", "C", "B", "D", "R")  # design 1.4
PATHS = ("SR", "JC", "CR", "BR", "DR")  # design 4.2
PORTS = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")  # design 5.1 and 6.1
LITHIUM = ("x_n", "x_p")
PORT_INSTANCE = {"P_pv_W": "SolarArray01", "P_load_W": "Compute01", "Q_B_W": "Battery01", "Q_D_W": "PDU01"}
NODE_INSTANCES = {"S": ["SolarArray01"], "J": ["Compute01"], "C": ["ColdPlate01"], "B": ["Battery01"],
                  "D": ["Controller01", "PDU01"], "R": ["Radiator01"]}  # design 3.2 and 9.3
B_INDEX, J_INDEX = NODES.index("B"), NODES.index("J")
DURATION_S = float(SPEC["duration_s"])
REPEAT_TOL = float(SPEC["acceptance"]["repeat_max_abs_difference"])
ECLIPSE_TOL_S = float(SPEC["acceptance"]["eclipse_reference_tolerance_s"])
RAMP = SPEC["power"]["ramp"]
WINDOW = tuple(SPEC["injection"]["event_required"]["window_s"])
INVALID_FROM_S = float(SPEC["injection"]["invalid"]["from_s"])
LOAD_CONTROL_WORDS = ("load_connected", "trip_latched", "apply_power_event", "powerevent", "supply_loss", "throttl",
                      "derat", "shutdown", "power_off", "poweroff", "can_supply", "solve_power_allocation")


def _load_reference() -> Any:
    spec = importlib.util.spec_from_file_location("ni002_reference", DATA_DIR / "ni002_reference.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REF = _load_reference()


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


def plain(value: Any) -> Any:
    """JSON-ready copy written for this test (mappings, sequences, arrays, numbers, datetimes)."""

    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_W(time_s: float) -> float:
    """Computing load request of the scenario: base request with a linear ramp in eclipse 9."""

    if RAMP["start_s"] <= time_s < RAMP["end_s"]:
        return RAMP["start_W"] + (RAMP["end_W"] - RAMP["start_W"]) * (time_s - RAMP["start_s"]) / (
            RAMP["end_s"] - RAMP["start_s"])
    return float(SPEC["power"]["base_request_W"])


def injected_result(inputs: Any, *, valid: bool, reason: str) -> Any:
    """Power result without ports: valid False (input or numerical error) or valid True with event_required True."""

    return ps.PowerResult(
        run_id=inputs.run_id, instance_id=inputs.instance_id, time_s=inputs.time_s, P_pv_W=None, P_load_W=None,
        Q_B_W=None, Q_D_W=None, dx_n_dt=None, dx_p_dt=None, battery=None, valid=valid, event_required=valid,
        can_supply_request=False, reason=reason, solar=None, P_bus_W=None,
        diagnostics={"injected_by": "NI-002 test through PowerCoupling.solve"},
    )


def scenario_solve(inputs: Any, state: Any, parameters: Any) -> Any:
    """Power stand-in with the injected confirmed supply shortfall of the scenario window."""

    if WINDOW[0] <= inputs.time_s < WINDOW[1]:
        if state.load_connected:
            return injected_result(inputs, valid=True, reason=SPEC["injection"]["event_required"]["reason"])
        result = ps.solve_power_allocation(inputs, state, parameters)
        if result.valid and not result.event_required:
            return dataclasses.replace(result, can_supply_request=False)
        return result
    return ps.solve_power_allocation(inputs, state, parameters)


def invalid_solve(inputs: Any, state: Any, parameters: Any) -> Any:
    """The scenario Power with valid False from the injection time on (the run must stop at the first one)."""

    if inputs.time_s >= INVALID_FROM_S:
        return injected_result(inputs, valid=False, reason=SPEC["injection"]["invalid"]["reason"])
    return scenario_solve(inputs, state, parameters)


# ------------------------------------------------------------------------------------------------- scenario inputs


def orbit_inputs(epoch: datetime) -> tuple[Any, Any, np.ndarray, np.ndarray]:
    """Orbit ephemeris (TwoBodyPropagator), Sun-tracking attitude and Earth-to-Sun vectors of the scenario."""

    o = SPEC["orbit"]
    elements = ClassicalElements.from_degrees(o["earth_radius_m"] + o["altitude_m"], o["eccentricity"],
                                              o["inclination_deg"], o["raan_deg"], o["argument_of_perigee_deg"],
                                              o["true_anomaly_deg"], epoch=epoch)
    r0, v0 = oe_to_rv(elements)
    times = time_grid(epoch, epoch + timedelta(seconds=DURATION_S + o["ephemeris_margin_s"]), o["ephemeris_step_s"])
    ephemeris = TwoBodyPropagator().propagate(OrbitState(epoch, r0, v0, "GCRS"), times)
    sun_times = np.arange(0.0, DURATION_S + o["sun_margin_s"], o["sun_step_s"])
    sun = np.array([sun_position_ephemeris(epoch + timedelta(seconds=float(t)), ephemeris=o["sun_ephemeris"])
                    for t in sun_times])
    sun_at_orbit = np.array([np.interp(ephemeris.elapsed_seconds, sun_times, sun[:, k]) for k in range(3)]).T
    tilt = math.radians(o["sun_tilt_deg"])
    quaternions = []
    for r, v, s in zip(ephemeris.positions_m, ephemeris.velocities_m_s, sun_at_orbit, strict=True):
        u = (s - r) / np.linalg.norm(s - r)
        h = np.cross(r, v)
        z = h - np.dot(h, u) * u
        z /= np.linalg.norm(z)
        w = np.cross(z, u)
        x = math.cos(tilt) * u - math.sin(tilt) * w
        quaternions.append(Rotation.from_matrix(np.column_stack([x, np.cross(z, x), z])).as_quat())
    attitude = AttitudeEphemeris(ephemeris.elapsed_seconds, np.array(quaternions), np.zeros((len(times), 3)))
    return ephemeris, attitude, sun, sun_times


def build_provider(world: SimpleNamespace, run_id: str) -> cp.EnvironmentProvider:
    ephemeris, attitude, sun, sun_times = orbit_inputs(world.epoch)
    m = SPEC["orbit"]["earth_flux_model"]
    earth = cp.EarthFluxModel(albedo=m["albedo"], olr_W_m2=m["olr_W_m2"], solar_constant_W_m2=m["solar_constant_W_m2"],
                              resolution=tuple(m["resolution"]))
    return cp.EnvironmentProvider.from_orbit(run_id=run_id, epoch=world.epoch, parameters=world.params,
                                             ephemeris=ephemeris, attitude=attitude, sun_positions_m=sun,
                                             sun_times_s=sun_times, earth_flux=earth)


def power_setup(world: SimpleNamespace, run_id: str) -> tuple[Any, Any]:
    """Power stand-in parameters with the Sat01 power capabilities and the inventory-consistent initial state."""

    asset_record, scene_record = ps.example_power_records()
    capabilities = world.assembly.power["instances"]
    scene_record["overrides"] = {
        "solar": {"area_m2": capabilities["SolarArray01"]["parameter_set"]["cell_area_m2"],
                  "efficiency": capabilities["SolarArray01"]["parameter_set"]["efficiency"],
                  "normal_body": [float(v) for v in capabilities["SolarArray01"]["surface"]["normal_body"]]},
        "battery": {"N_s": capabilities["Battery01"]["parameter_set"]["N_s"],
                    "N_p": capabilities["Battery01"]["parameter_set"]["N_p"]},
        "pdu": {"eta_D": capabilities["PDU01"]["parameter_set"]["eta_D"]},
        "source": "Sat01 scene power capabilities of SolarArray01, Battery01 and PDU01",
    }
    battery = ps.load_power_parameters(asset_record, scene_record).battery
    x_n0 = float(SPEC["power"]["initial_x_n"])
    x_p0 = battery.x_p_100 + (battery.x_n_100 - x_n0) * battery.Q_n_C / battery.Q_p_C
    initial_b = float(getattr(world, 'power_initial_T_B_K', world.assembly.initial_temperature_K[B_INDEX]))
    scene_record["initial_state"].update(x_n=x_n0, x_p=x_p0, T_B_K=initial_b)
    return ps.load_power_parameters(asset_record, scene_record), ps.power_state_from_scene(scene_record, run_id)


# ----------------------------------------------------------------------------------------------- instrumentation


class Recorder:
    """Ordered log of one coupled run: environment preparation, Power, thermal_derivative, trials and solver data."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []
        self.solvers = 0
        self.step_aborted = 0
        self.construct_aborted = 0
        self.orbit_thermal_calls = 0

    def prepare_spy(self, inner: Any) -> Any:
        def prepare(orbit_input: Any, earth_flux: Any, parameters: Any) -> Any:
            environment = inner(orbit_input, earth_flux, parameters)
            self.entries.append({"k": "prepare", "t": float(orbit_input["time_s"]), "orbit": orbit_input,
                                 "env": environment})
            return environment

        return prepare

    def power_spy(self, inner: Any) -> Any:
        def solve(inputs: Any, state: Any, parameters: Any) -> Any:
            result = inner(inputs, state, parameters)
            battery = result.battery
            self.entries.append({
                "k": "power", "t": float(inputs.time_s), "T_B": float(inputs.T_B_K), "x_n": float(state.x_n),
                "x_p": float(state.x_p), "connected": bool(state.load_connected), "latched": bool(state.trip_latched),
                "request": float(inputs.P_request_W), "env": inputs.environment, "valid": bool(result.valid),
                "event": bool(result.event_required), "can_supply": bool(result.can_supply_request),
                "reason": str(result.reason), "ports": tuple(getattr(result, name) for name in PORTS),
                "dx": (result.dx_n_dt, result.dx_p_dt),
                "battery_T_B": None if battery is None else float(battery.T_B_K),
            })
            return result

        return solve

    def apply_spy(self, inner: Any) -> Any:
        def apply(state: Any, event: Any, decision: Any) -> Any:
            updated = inner(state, event, decision)
            events = (event,) if isinstance(event, ps.PowerEvent) else tuple(event)
            self.entries.append({"k": "apply", "t": float(state.time_s), "state": state, "events": events,
                                 "decision": decision, "updated": updated})
            return updated

        return apply

    def thermal_spy(self, inner: Any) -> Any:
        def derivative(state: Any, inputs: Any, parameters: Any) -> Any:
            evaluation = inner(state, inputs, parameters)
            self.entries.append({
                "k": "thermal", "t": float(state.time_s), "T": np.array(state.temperature_K, dtype=float),
                "ports": tuple(float(getattr(inputs, name)) for name in PORTS), "env": inputs.environment,
                "dT": np.array(evaluation.dT_dt_K_s, dtype=float), "T_B_out": float(evaluation.T_B_K),
                "T_J_out": float(evaluation.T_J_K),
            })
            return evaluation

        return derivative

    def hook(self, record: Any) -> None:
        self.entries.append({"k": "hook", "t": float(record.time_s), "context": record.context,
                             "outcome": record.outcome, "sid": int(record.solver_id), "state": record.state})

    def orbit_sentinel(self, *args: Any, **kwargs: Any) -> Any:
        self.orbit_thermal_calls += 1
        raise AssertionError("Orbit power_considering_thermal was called during a run with the thermal module")

    def rk45_class(self) -> type:
        recorder = self

        class RecordingRK45(RK45):
            """SciPy RK45 that records every right-hand-side value and every successful step; numerics unchanged."""

            def __init__(self, fun: Any, t0: float, y0: Any, t_bound: float, **options: Any) -> None:
                sid = recorder.solvers
                recorder.solvers += 1
                self.ni002_sid = sid
                self.ni002_calls: list[dict[str, Any]] = []
                self.ni002_constructing = True

                def wrapped(t: float, y: Any) -> Any:
                    # role: "start" is f(t0, y0) at the accepted start state, "probe" the initial step-size trial,
                    # "stage" every evaluation inside step() (stages, rejected candidates and the FSAL value)
                    role = "start" if not self.ni002_calls else ("probe" if self.ni002_constructing else "stage")
                    f = fun(t, y)
                    entry = {"k": "f", "sid": sid, "t": float(t), "y": np.array(y, dtype=float),
                             "f": np.array(f, dtype=float), "role": role}
                    self.ni002_calls.append(entry)
                    recorder.entries.append(entry)
                    return f

                try:
                    super().__init__(wrapped, t0, y0, t_bound, **options)
                except BaseException:
                    recorder.construct_aborted += 1
                    raise
                self.ni002_constructing = False

            def step(self) -> Any:
                t_old, y_old, f_old = float(self.t), np.array(self.y, dtype=float), np.array(self.f, dtype=float)
                start = len(self.ni002_calls)
                try:
                    message = super().step()
                except BaseException:
                    recorder.step_aborted += 1
                    raise
                recorder.steps.append({"sid": self.ni002_sid, "t_old": t_old, "y_old": y_old, "f_old": f_old,
                                       "t_new": float(self.t), "y_new": np.array(self.y, dtype=float),
                                       "calls": self.ni002_calls[start:], "status": self.status})
                return message

        return RecordingRK45


@dataclasses.dataclass
class RunResult:
    run_id: str
    archive: Any
    error: Any
    recorder: Recorder | None
    wall_s: float
    call_stats: dict[str, int]
    provider: Any
    power_parameters: Any
    initial_power_state: Any
    initial_temperature_K: np.ndarray
    request: Any
    started_unix_s: float
    warnings: list[str]
    prerun_written_unix_s: float | None


def run_scenario(world: SimpleNamespace, run_id: str, solve: Any, *, t_end: float, commands: tuple, request: Any,
                 boundaries: list, initial_temperature_K: np.ndarray, prerun_path: Path | None = None) -> RunResult:
    """One coupled run with the spies of this test; returns the archive (also of a stopped run) and the log."""

    recorder = Recorder()
    setup_world = SimpleNamespace(**vars(world))
    setup_world.power_initial_T_B_K = float(initial_temperature_K[B_INDEX])
    power_parameters, power_state = power_setup(setup_world, run_id)
    coupling = cp.PowerCoupling(parameters=power_parameters, initial_state=power_state, request_W=request,
                                commands=commands, solve=recorder.power_spy(solve),
                                apply_event=recorder.apply_spy(ps.apply_power_event))
    provider = build_provider(world, run_id)
    initial = ThermalState(run_id, 0.0, initial_temperature_K)
    caller = {
        "case_id": "NI-002",
        "scenario": {"path": str(SPEC_PATH), "sha256": sha256(SPEC_PATH)},
        "scene": plain(world.assembly.provenance["scene"]),
        "assets": plain(world.assembly.provenance["assets"]),
        "value_status": plain(world.assembly.provenance["value_status"]),
    }
    if prerun_path is not None:
        # design 9.4: before startup save the resolved parameters, sources, initial values and environment configuration
        settings = cp.SolverSettings.from_power_numerics(power_parameters.numerics)
        record = {
            "case_id": "NI-002", "run_id": run_id, "epoch_utc": world.epoch.isoformat(),
            "scene": caller["scene"], "assets": caller["assets"], "value_status": caller["value_status"],
            "thermal_parameters": {
                "C_J_K": dict(zip(NODES, (float(v) for v in world.params.C_J_K), strict=True)),
                "R_K_W": dict(zip(PATHS, (float(v) for v in world.params.R_K_W), strict=True)),
                "surfaces": [plain(dataclasses.asdict(s)) for s in world.params.surfaces],
                "provenance": plain(world.params.provenance_as_dict()),
            },
            "initial_state": {
                "time_s": 0.0, "temperature_K": dict(zip(NODES, (float(v) for v in initial_temperature_K), strict=True)),
                "x_n": power_state.x_n, "x_p": power_state.x_p, "load_connected": power_state.load_connected,
                "trip_latched": power_state.trip_latched,
            },
            "power_parameters": {"provenance": plain(power_parameters.provenance),
                                 "links": plain(power_parameters.links)},
            "environment": provider.describe(),
            "solver_settings": plain(settings.as_dict()),
            "commands": plain([dataclasses.asdict(c) for c in commands]),
            "request": {"base_W": SPEC["power"]["base_request_W"], "ramp": RAMP},
        }
        prerun_path.parent.mkdir(parents=True, exist_ok=True)
        prerun_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    prerun_written = time.time() if prerun_path is not None else None
    ps.CALL_STATS.reset()
    error = None
    started_unix = time.time()
    with pytest.MonkeyPatch.context() as patch, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        patch.setattr(cp, "prepare_surface_environment", recorder.prepare_spy(prepare_surface_environment))
        patch.setattr(cp, "thermal_derivative", recorder.thermal_spy(thermal_derivative))
        patch.setitem(cp._METHOD_CLASSES, "RK45", recorder.rk45_class())
        patch.setattr(ntu_space_dynamics, "power_considering_thermal", recorder.orbit_sentinel)
        patch.setattr(ntu_space_dynamics.power, "power_considering_thermal", recorder.orbit_sentinel)
        started = time.perf_counter()
        try:
            archive = cp.run_coupled(world.params, initial, provider, t_end, power=coupling, boundaries_s=boundaries,
                                     trial_hook=recorder.hook, provenance=caller)
        except cp.CoupledRunError as exc:
            archive, error = exc.archive, exc
        wall = time.perf_counter() - started
    stats = dict(ps.CALL_STATS.snapshot())
    request_fn = request if callable(request) else (lambda _t, value=float(request): value)
    return RunResult(run_id, archive, error, recorder, wall, stats, provider, power_parameters, power_state,
                     np.array(initial_temperature_K, dtype=float), request_fn, started_unix,
                     [str(item.message) for item in caught], prerun_written)


# ------------------------------------------------------------------------------------------------------- analysis


def analyse_log(run: RunResult) -> Counter:
    """Order and value pairing of every trial (design 6.3): environment, Power, thermal_derivative, solver value."""

    entries = run.recorder.entries
    counts: Counter = Counter()
    prepared: dict[float, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        kind = entry["k"]
        if kind == "prepare":
            counts["prepare"] += 1
            prepared[entry["t"]] = entry
        elif kind == "power":
            counts["power"] += 1
            if not entry["valid"]:
                counts["power_invalid"] += 1
            elif entry["event"]:
                counts["power_event_required"] += 1
            following = index + 1
            if following < len(entries) and entries[following]["k"] == "thermal":
                if not entry["valid"] or entry["event"]:
                    counts["unusable_reached_thermal"] += 1
                following += 1
            hook = entries[following] if following < len(entries) else None
            if (hook is None or hook["k"] != "hook" or hook["t"] != entry["t"] or hook["state"][B_INDEX] != entry["T_B"]
                    or hook["state"][6] != entry["x_n"] or hook["state"][7] != entry["x_p"]):
                counts["power_trial_mismatch"] += 1
            if entry["request"] != run.request(entry["t"]):
                counts["request_mismatch"] += 1
            if entry["battery_T_B"] is not None and entry["battery_T_B"] != entry["T_B"]:
                counts["battery_echo_mismatch"] += 1
            if entry["valid"] and not entry["event"] and entry["battery_T_B"] is None:
                counts["usable_without_battery"] += 1
        elif kind == "thermal":
            counts["thermal"] += 1
            previous = entries[index - 1] if index > 0 else None
            if previous is None or previous["k"] != "power" or previous["t"] != entry["t"]:
                counts["thermal_without_power"] += 1
                continue
            if not previous["valid"] or previous["event"]:
                counts["thermal_from_unusable"] += 1
            if previous["ports"] != entry["ports"]:
                counts["port_mismatch"] += 1
            if previous["T_B"] != entry["T"][B_INDEX]:
                counts["T_B_mismatch"] += 1
            if entry["T_B_out"] != entry["T"][B_INDEX] or entry["T_J_out"] != entry["T"][J_INDEX]:
                counts["evaluation_copy_mismatch"] += 1
            prepared_entry = prepared.get(entry["t"])
            if prepared_entry is None:
                counts["environment_not_prepared"] += 1
                continue
            environment, orbit = prepared_entry["env"], prepared_entry["orbit"]
            used = entry["env"]  # ThermalInputs keeps a checked read-only copy; compare it by value
            if not (used["time_s"] == entry["t"] == environment["time_s"] and used["run_id"] == run.run_id
                    and used["G_W_m2"] == environment["G_W_m2"]
                    and tuple(used["surface_ids"]) == tuple(environment["surface_ids"])
                    and all(np.array_equal(used[key], environment[key])
                            for key in ("cos_incidence", "albedo_W_m2", "infrared_W_m2"))):
                counts["environment_mismatch"] += 1
            power_env = previous["env"]
            if not (power_env.G_W_m2 == orbit["G_W_m2"] and power_env.frame == orbit["frame"] == "GCRS"
                    and np.array_equal(power_env.position_m, orbit["position_m"])
                    and np.array_equal(power_env.sun_position_m, orbit["sun_position_m"])
                    and np.array_equal(power_env.quaternion_xyzw, orbit["quaternion_xyzw"])):
                counts["power_environment_mismatch"] += 1
        elif kind == "hook":
            counts[f"trial_{entry['context']}"] += 1
            counts[f"outcome_{entry['outcome']}"] += 1
        elif kind == "f":
            counts["solver_values"] += 1
            if index < 3:
                counts["solver_value_unpaired"] += 1
                continue
            hook, thermal, power = entries[index - 1], entries[index - 2], entries[index - 3]
            if not (hook["k"] == "hook" and thermal["k"] == "thermal" and power["k"] == "power"
                    and hook["t"] == thermal["t"] == power["t"] == entry["t"] and hook["outcome"] == "ok"):
                counts["solver_value_unpaired"] += 1
                continue
            if not (np.array_equal(entry["y"][:6], thermal["T"]) and entry["y"][6] == power["x_n"]
                    and entry["y"][7] == power["x_p"]):
                counts["solver_state_mismatch"] += 1
            if not (np.array_equal(entry["f"][:6], thermal["dT"]) and entry["f"][6] == power["dx"][0]
                    and entry["f"][7] == power["dx"][1]):
                counts["solver_derivative_mismatch"] += 1
        elif kind == "apply":
            counts["apply"] += 1
    return counts


def piece_table(run: RunResult) -> dict[str, Any]:
    """Every accepted state of the archive explained from the solver records (design 6.3, chapter 7).

    Integration and event-location steps must equal y_old + h K^T b of the recorded stage derivatives (Dormand-Prince
    weights written in the reference module), steps ended at a located charge-limit change must equal the continuous
    extension of the same stages, event bridges must equal one explicit Euler step with the derivative evaluated at the
    last accepted state, and segment starts and the final state carry the previous accepted state unchanged.
    """

    archive = run.archive
    recorder = run.recorder
    by_key = {(step["sid"], step["t_old"]): step for step in recorder.steps}
    steps = archive.steps
    pieces = list(zip((float(v) for v in steps["t_old_s"]), (float(v) for v in steps["t_new_s"]), steps["kind"],
                      (int(v) for v in steps["solver_id"]), (int(v) for v in steps["attempts"]), strict=True))
    times, states, kinds = archive.accepted["time_s"], archive.accepted["state"], archive.accepted["kind"]
    y0 = np.concatenate([run.initial_temperature_K, [run.initial_power_state.x_n, run.initial_power_state.x_p]])
    counts: Counter = Counter()
    worst = 0.0
    info: list[dict[str, Any]] = []
    used: set[int] = set()
    full_records: list[dict[str, Any]] = []
    truncated_records: list[dict[str, Any]] = []
    piece_index = 0
    previous_t, previous_y = None, None
    thermal_at: dict[tuple[float, bytes], tuple[np.ndarray, tuple]] = {}
    for index, entry in enumerate(recorder.entries):
        if entry["k"] == "thermal" and index > 0 and recorder.entries[index - 1]["k"] == "power":
            power = recorder.entries[index - 1]
            thermal_at[(entry["t"], entry["T"].tobytes())] = (entry["dT"], power["dx"], power["x_n"], power["x_p"])
    for t, y, kind in zip((float(v) for v in times), states, kinds, strict=True):
        y = np.array(y, dtype=float)
        if kind == "initial":
            ok = np.array_equal(y, y0) and t == 0.0
            counts["initial"] += 1
        elif kind in ("segment_start", "final"):
            ok = previous_y is not None and np.array_equal(y, previous_y) and t >= previous_t
            counts[kind] += 1
        elif kind in ("integration", "event_location", "event_bridge"):
            if piece_index >= len(pieces):
                counts["unexplained"] += 1
                previous_t, previous_y = t, y
                continue
            t_old, t_new, piece_kind, sid, attempts = pieces[piece_index]
            piece_index += 1
            continuity = previous_y is not None and t_old == previous_t and t_new == t and piece_kind == kind
            if kind == "event_bridge":
                found = thermal_at.get((t_old, previous_y[:6].tobytes()))
                ok = False
                if found is not None and found[2] == previous_y[6] and found[3] == previous_y[7]:
                    rate = np.concatenate([found[0], np.array(found[1], dtype=float)])
                    rebuilt = previous_y + (t_new - t_old) * rate
                    worst = max(worst, float(np.max(np.abs(rebuilt - y))))
                    ok = continuity and np.array_equal(rebuilt, y)
                counts["event_bridge"] += 1
                info.append({"t_old": t_old, "t_new": t_new, "kind": kind, "y_old": previous_y, "y_new": y,
                             "record": None})
            else:
                record = by_key.get((sid, t_old))
                ok = False
                if record is not None and np.array_equal(record["y_old"], previous_y):
                    calls = record["calls"]
                    stages = np.vstack([record["f_old"]] + [call["f"] for call in calls[-6:-1]])
                    h = record["t_new"] - record["t_old"]
                    rebuilt_full = REF.rk45_update(record["y_old"], h, stages)
                    full_ok = np.array_equal(rebuilt_full, record["y_new"])
                    stages7 = np.vstack([stages, calls[-1]["f"]])
                    if record["t_new"] == t_new:
                        rebuilt = rebuilt_full
                        counts["full_steps"] += 1
                        full_records.append(record)
                    else:
                        rebuilt = REF.rk45_dense(t_new, record["t_old"], record["t_new"], record["y_old"], stages7,
                                                 RK45.P)
                        counts["truncated_steps"] += 1
                        truncated_records.append(record)
                    worst = max(worst, float(np.max(np.abs(rebuilt - y))))
                    ok = continuity and full_ok and np.array_equal(rebuilt, y) and len(calls) == 6 * attempts
                    used.add(id(record))
                    info.append({"t_old": t_old, "t_new": t_new, "kind": kind, "y_old": previous_y, "y_new": y,
                                 "record": record, "stages7": stages7})
                else:
                    info.append({"t_old": t_old, "t_new": t_new, "kind": kind, "y_old": previous_y, "y_new": y,
                                 "record": None})
        else:
            ok = False
        counts["explained" if ok else "unexplained"] += 1
        previous_t, previous_y = t, y
    discarded = [step for step in recorder.steps if id(step) not in used]
    committed = [step for step in recorder.steps if id(step) in used]
    return {"counts": counts, "worst": worst, "pieces": info, "committed": committed, "discarded": discarded,
            "full_records": full_records, "truncated_records": truncated_records,
            "pieces_left": len(pieces) - piece_index, "y0": y0}


_CACHE: dict[tuple[int, str], Any] = {}


def cached(run: RunResult, name: str) -> Any:
    """analyse_log and piece_table computed once per run."""

    key = (id(run), name)
    if key not in _CACHE:
        _CACHE[key] = analyse_log(run) if name == "log" else piece_table(run)
    return _CACHE[key]


def rebuild_outputs(run: RunResult, table: dict[str, Any]) -> dict[str, Any]:
    """Output samples rebuilt on the accepted solution from the solver records (table 8: sample accepted results)."""

    archive = run.archive
    pieces = table["pieces"]
    starts = [piece["t_old"] for piece in pieces]
    worst_T = 0.0
    worst_x = 0.0
    identical = 0
    final = np.array(archive.accepted["state"][-1], dtype=float)
    for k, tau in enumerate(float(v) for v in archive.time_s):
        index = bisect.bisect_right(starts, tau) - 1
        if index < 0:
            value = table["y0"]
        else:
            piece = pieces[index]
            if tau <= piece["t_new"]:
                if tau == piece["t_old"]:
                    value = piece["y_old"]
                elif tau == piece["t_new"]:
                    value = piece["y_new"]
                elif piece["record"] is None:
                    weight = (tau - piece["t_old"]) / (piece["t_new"] - piece["t_old"])
                    value = piece["y_old"] + weight * (piece["y_new"] - piece["y_old"])
                else:
                    record = piece["record"]
                    value = REF.rk45_dense(tau, record["t_old"], record["t_new"], record["y_old"], piece["stages7"],
                                           RK45.P)
            elif index + 1 < len(pieces):
                value = pieces[index + 1]["y_old"]
            else:
                value = final
        archived = np.concatenate([archive.temperature_K[k], [archive.lithium["x_n"][k], archive.lithium["x_p"][k]]])
        if np.array_equal(value, archived):
            identical += 1
        worst_T = max(worst_T, float(np.max(np.abs(value[:6] - archived[:6]) / np.abs(archived[:6]))))
        worst_x = max(worst_x, float(np.max(np.abs(value[6:] - archived[6:]))))
    return {"samples": int(archive.time_s.size), "identical": identical, "worst_T_rel": worst_T, "worst_x": worst_x}


def compare_trees(first: Any, second: Any) -> dict[str, Any]:
    """Leaf by leaf comparison of two plain archives; statistics.wall_time_s (measured run time) is excluded."""

    result = {"leaves": 0, "numeric": 0, "different": 0, "max_abs": 0.0, "examples": []}
    excluded = {"statistics.wall_time_s"}

    def note(path: str, text: str) -> None:
        result["different"] += 1
        if len(result["examples"]) < 5:
            result["examples"].append(f"{path}: {text}")

    def walk(a: Any, b: Any, path: str) -> None:
        if path in excluded:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                note(path, f"keys {sorted(set(a) ^ set(b))}")
                return
            for key in a:
                walk(a[key], b[key], f"{path}.{key}" if path else key)
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                note(path, f"lengths {len(a)} and {len(b)}")
                return
            for i, (u, v) in enumerate(zip(a, b, strict=True)):
                walk(u, v, f"{path}[{i}]")
            return
        result["leaves"] += 1
        numeric = (isinstance(a, (int, float)) and not isinstance(a, bool)
                   and isinstance(b, (int, float)) and not isinstance(b, bool))
        if numeric:
            result["numeric"] += 1
            if a != b:
                result["max_abs"] = max(result["max_abs"], abs(float(a) - float(b)))
                note(path, f"{a!r} and {b!r}")
        elif type(a) is not type(b) or a != b:
            note(path, f"{a!r} and {b!r}")

    walk(first, second, "")
    return result


def identifiers(path: Path) -> set[str]:
    """Names, attributes, definitions, arguments and imports of a Python source (docstrings and comments excluded)."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.name.split(".")[-1])
            if node.asname:
                names.add(node.asname)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def stand_in_decision(run: RunResult, time_s: float, state: np.ndarray, *, connected: bool, latched: bool) -> Any:
    """Direct Power stand-in evaluation at one accepted state (test reference of the Power decision)."""

    sample = run.provider.sample(time_s)
    inputs = ps.PowerInputs(run_id=run.run_id, instance_id="Sat01", time_s=time_s,
                            environment=sample.power_environment, P_request_W=request_W(time_s),
                            T_B_K=float(state[B_INDEX]))
    power_state = ps.PowerState(run_id=run.run_id, instance_id="Sat01", time_s=time_s, x_n=float(state[6]),
                                x_p=float(state[7]), load_connected=connected, trip_latched=latched,
                                handled_command_ids=())
    return ps.solve_power_allocation(inputs, power_state, run.power_parameters)


def accepted_state_at(archive: Any, time_s: float) -> np.ndarray | None:
    matches = np.flatnonzero(archive.accepted["time_s"] == time_s)
    return None if matches.size == 0 else np.array(archive.accepted["state"][matches[-1]], dtype=float)


def event_chain(run: RunResult, event: Mapping[str, Any]) -> dict[str, Any]:
    """Log facts around one applied supply_loss: decision, protection update, recomputation and next derivative."""

    entries = run.recorder.entries
    t_e = float(event["time_s"])
    applies = [i for i, e in enumerate(entries) if e["k"] == "apply" and e["t"] == t_e]
    facts: dict[str, Any] = {"applies": len(applies)}
    if not applies:
        return facts
    i = applies[0]
    apply = entries[i]
    decision = apply["decision"]
    facts.update({
        "kinds": [e.kind for e in apply["events"]],
        "accepted_flags": [bool(e.accepted) for e in apply["events"]],
        "decision": {"time_s": float(decision.time_s), "valid": bool(decision.valid),
                     "event_required": bool(decision.event_required),
                     "can_supply_request": bool(decision.can_supply_request), "reason": str(decision.reason)},
        "state_lithium": (float(apply["state"].x_n), float(apply["state"].x_p)),
        "state_time": float(apply["state"].time_s),
        "updated": {"load_connected": bool(apply["updated"].load_connected),
                    "trip_latched": bool(apply["updated"].trip_latched),
                    "lithium": (float(apply["updated"].x_n), float(apply["updated"].x_p))},
        "decision_logged": any(e["k"] == "power" and e["t"] == t_e and e["event"] and e["reason"] == decision.reason
                               for e in entries[:i]),
    })
    recompute = next((e for e in entries[i + 1:] if e["k"] == "power"), None)
    facts["recompute"] = None if recompute is None else {
        "time_s": recompute["t"], "connected": recompute["connected"], "latched": recompute["latched"],
        "valid": recompute["valid"], "event": recompute["event"], "ports": recompute["ports"],
        "reason": recompute["reason"]}
    thermal = next((e for e in entries[i + 1:] if e["k"] == "thermal"), None)
    facts["next_thermal"] = None if thermal is None else {"time_s": thermal["t"], "ports": thermal["ports"]}
    return facts


def first_event_trial(run: RunResult, predicate: Any) -> dict[str, Any] | None:
    """The first Power trial with event_required True that satisfies ``predicate`` and what followed it."""

    entries = run.recorder.entries
    for index, entry in enumerate(entries):
        if entry["k"] == "power" and entry["event"] and predicate(entry):
            following = entries[index + 1] if index + 1 < len(entries) else None
            hook = following if following is not None and following["k"] == "hook" else None
            return {"time_s": entry["t"], "reason": entry["reason"], "connected": entry["connected"],
                    "next_kind": None if following is None else following["k"],
                    "context": None if hook is None else hook["context"],
                    "outcome": None if hook is None else hook["outcome"],
                    "state": None if hook is None else np.array(hook["state"], dtype=float)}
    return None


def disconnected_ok(run: RunResult, start: float, stop: float) -> dict[str, Any]:
    """Output samples and thermal calls strictly between two instants: load disconnected and P_load_W = 0."""

    archive = run.archive
    times = archive.time_s
    mask = (times > start) & (times < stop)
    p_load = archive.ports_W["P_load_W"][mask]
    connected = archive.power_diagnostics["load_connected"][mask]
    thermal = [e for e in run.recorder.entries if e["k"] == "thermal" and start < e["t"] < stop]
    return {"samples": int(mask.sum()), "max_P_load_W": float(np.max(p_load)) if mask.any() else None,
            "any_connected": bool(np.any(connected)) if mask.any() else None, "thermal_calls": len(thermal),
            "thermal_max_P_load_W": max((e["ports"][1] for e in thermal), default=None)}


# ---------------------------------------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def world() -> SimpleNamespace:
    """Scene, thermal parameters, schedule and the independent eclipse reference of the scenario."""

    epoch = datetime.fromisoformat(SPEC["epoch_utc"])
    assembly = sc.assemble_scene(SCENE_PATH)
    params = assemble_thermal_parameters(*assembly.thermal_inputs())
    commands = tuple(cp.LoadCommand(c["time_s"], c["kind"], c["command_id"]) for c in SPEC["commands"])
    boundaries = [(RAMP["start_s"], "request ramp start"), (RAMP["end_s"], "request ramp end")]
    o = SPEC["orbit"]
    sun_times = np.arange(0.0, DURATION_S + o["sun_margin_s"], o["sun_step_s"])
    table = REF.SunTable(sun_times, [sun_position_ephemeris(epoch + timedelta(seconds=float(t)),
                                                            ephemeris=o["sun_ephemeris"]) for t in sun_times])
    radius = o["earth_radius_m"] + o["altitude_m"]
    u0 = o["argument_of_perigee_deg"] + o["true_anomaly_deg"]

    def shadow(time_s: float) -> bool:
        position = REF.circular_position(time_s, radius_m=radius, mu_m3_s2=MU_EARTH_M3_S2,
                                         inclination_deg=o["inclination_deg"], raan_deg=o["raan_deg"],
                                         argument_of_latitude0_deg=u0)
        return REF.in_cylindrical_shadow(position, table(time_s), o["earth_radius_m"])

    entries, exits = REF.shadow_crossings(shadow, 0.0, DURATION_S, scan_step_s=10.0)
    return SimpleNamespace(epoch=epoch, assembly=assembly, params=params, commands=commands, boundaries=boundaries,
                           shadow=shadow, shadow_entries=entries, shadow_exits=exits)


@pytest.fixture(scope="module")
def baseline(world: SimpleNamespace) -> SimpleNamespace:
    """The 24 h scenario run twice with the same inputs; the first archive and the pre-run record are saved."""

    initial = np.array(world.assembly.initial_temperature_K, dtype=float)
    run1 = run_scenario(world, SPEC["run_id"], scenario_solve, t_end=DURATION_S, commands=world.commands,
                        request=request_W, boundaries=world.boundaries, initial_temperature_K=initial,
                        prerun_path=PRERUN_PATH)
    saved = run1.archive.to_json(ARCHIVE_PATH)
    prerun_written = run1.prerun_written_unix_s if PRERUN_PATH.is_file() else None
    run2 = run_scenario(world, SPEC["run_id"], scenario_solve, t_end=DURATION_S, commands=world.commands,
                        request=request_W, boundaries=world.boundaries, initial_temperature_K=initial)
    table2 = piece_table(run2)
    run2_counts = {"power_spy_calls": sum(1 for e in run2.recorder.entries if e["k"] == "power"),
                   "committed_rejected": sum(len(s["calls"]) // 6 - 1 for s in table2["committed"]),
                   "discarded_steps": len(table2["discarded"]),
                   "discarded_rejected": sum(len(s["calls"]) // 6 - 1 for s in table2["discarded"]),
                   "aborted": run2.recorder.step_aborted + run2.recorder.construct_aborted,
                   "orbit_thermal_calls": run2.recorder.orbit_thermal_calls,
                   "explained": table2["counts"]["explained"], "unexplained": table2["counts"]["unexplained"]}
    run2.recorder = None  # the log of the repeat run is not needed beyond these counts
    return SimpleNamespace(run1=run1, run2=run2, run2_counts=run2_counts, archive_path=Path(saved),
                           prerun_written=prerun_written)


@pytest.fixture(scope="module")
def invalid_run(world: SimpleNamespace) -> RunResult:
    """The same scenario with one Power result with valid False injected at or after INVALID_FROM_S."""

    return run_scenario(world, SPEC["invalid_run_id"], invalid_solve, t_end=DURATION_S, commands=world.commands,
                        request=request_W, boundaries=world.boundaries,
                        initial_temperature_K=np.array(world.assembly.initial_temperature_K, dtype=float))


@pytest.fixture(scope="module")
def hot_run(world: SimpleNamespace) -> RunResult:
    """Short run of the same scene and orbit with J and B above their declared ranges."""

    probe = SPEC["hot_probe"]
    temperature = np.array([probe["temperature_K"][node] for node in NODES], dtype=float)
    return run_scenario(world, SPEC["hot_run_id"], ps.solve_power_allocation, t_end=float(probe["duration_s"]),
                        commands=(), request=float(SPEC["power"]["base_request_W"]), boundaries=[],
                        initial_temperature_K=temperature)


# ------------------------------------------------------------------------------------------------------------- tests


def test_step1_run_in_call_order_and_save(world: SimpleNamespace, baseline: SimpleNamespace, case_record: Any) -> None:
    """Step 1: run the 24 h scenario in the call order of design 6.3 and save every output."""

    check = Checks(case_record)
    run = baseline.run1
    archive = run.archive
    statistics = archive.statistics
    final_time = archive.final_thermal_state.time_s
    check("第1步：24 h 联合运行完成",
          f"no CoupledRunError, archive status completed, last accepted state at {DURATION_S} s, every output sample "
          "valid",
          f"error {type(run.error).__name__ if run.error else None}, status {archive.status}, last accepted "
          f"{final_time!r} s, {int(archive.sample_valid.sum())} of {archive.time_s.size} samples valid, wall "
          f"{run.wall_s:.1f} s",
          run.error is None and archive.status == "completed" and final_time == DURATION_S
          and bool(np.all(archive.sample_valid)))

    # eclipses against the independent analytic orbit with a cylindrical shadow
    bounds = archive.eclipse_boundaries
    pen_in = [b.time_s for b in bounds if b.phase_before == "sunlit"]
    umb_in = [b.time_s for b in bounds if b.phase_after == "umbra"]
    umb_out = [b.time_s for b in bounds if b.phase_before == "umbra"]
    pen_out = [b.time_s for b in bounds if b.phase_after == "sunlit"]
    ref_in, ref_out = world.shadow_entries, world.shadow_exits
    counts_ok = len(pen_in) == len(umb_in) == len(ref_in) and len(pen_out) == len(umb_out) == len(ref_out)
    excess = []
    if counts_ok:
        for k, t_ref in enumerate(ref_in):
            excess.append(max(0.0, pen_in[k] - t_ref, t_ref - umb_in[k]))
        for k, t_ref in enumerate(ref_out):
            excess.append(max(0.0, umb_out[k] - t_ref, t_ref - pen_out[k]))
    worst_excess = max(excess) if excess else float("nan")
    check("第1步：场景含日食，进出时刻与独立计算一致",
          f"the archive eclipse boundaries from Orbit eclipse_fraction give as many entries and exits as the analytic "
          f"circular orbit with a cylindrical shadow; each cylindrical crossing lies between the penumbra and umbra "
          f"boundaries of the same crossing within {ECLIPSE_TOL_S} s",
          f"entries {len(pen_in)} archive, {len(ref_in)} reference; exits {len(pen_out)} archive, {len(ref_out)} "
          f"reference; largest excess outside the penumbra band {worst_excess:.3g} s",
          counts_ok and len(ref_in) >= 15 and worst_excess <= ECLIPSE_TOL_S)

    # scheduled instants against the independent shadow
    placement = {
        "injected window in eclipse 0": world.shadow(WINDOW[0]) and world.shadow(WINDOW[1]),
        "stop and start after eclipse 3 in sunlight": not world.shadow(SPEC["commands"][2]["time_s"])
        and not world.shadow(SPEC["commands"][3]["time_s"]),
        "request ramp inside eclipse 9": world.shadow(RAMP["start_s"]) and world.shadow(RAMP["end_s"]),
        "refused restarts in eclipse": world.shadow(SPEC["commands"][0]["time_s"])
        and world.shadow(SPEC["commands"][4]["time_s"]),
        "accepted restart after the ramp in sunlight": not world.shadow(SPEC["commands"][5]["time_s"]),
        "invalid injection in sunlight": not world.shadow(INVALID_FROM_S),
    }
    check("前提：负载启停、注入与请求爬升位于设定的光照段",
          "the injected window, the refused restarts and the ramp lie in the cylindrical shadow; the stop and start "
          "pair, the accepted restart after the ramp and the invalid injection lie in sunlight",
          f"{placement}", all(placement.values()))

    # segmentation at eclipse boundaries, commands, declared request boundaries and located events
    t_old = np.array(archive.steps["t_old_s"], dtype=float)
    t_new = np.array(archive.steps["t_new_s"], dtype=float)
    span_eclipse = sum(int(np.count_nonzero((t_old <= b.time_left_s) & (t_new >= b.time_right_s))) for b in bounds)
    declared = [b[0] for b in world.boundaries]
    span_declared = sum(int(np.count_nonzero((t_old < d) & (t_new > d))) for d in declared)
    command_times = [float(c["time_s"]) for c in SPEC["commands"]]
    span_commands = sum(int(np.count_nonzero((t_old < c) & (t_new > c))) for c in command_times)
    accepted_times = set(float(v) for v in archive.accepted["time_s"])
    missing_commands = [c for c in command_times if c not in accepted_times]
    event_times = [float(e["time_s"]) for e in archive.events]
    span_events = sum(int(np.count_nonzero((t_old < e) & (t_new > e))) for e in event_times)
    missing_events = [e for e in event_times if e not in accepted_times]
    check("第1步：日食、负载启停与电池约束在同一物理时刻分段处理",
          "no accepted step spans an eclipse boundary, a declared request boundary, a command instant or a located "
          "Power event; every command and event instant is an accepted state",
          f"{len(bounds)} eclipse boundaries, {len(declared)} declared, {len(command_times)} commands, "
          f"{len(event_times)} events; spanning steps {span_eclipse}, {span_declared}, {span_commands}, {span_events}; "
          f"instants without accepted state: commands {missing_commands}, events {missing_events}",
          span_eclipse == span_declared == span_commands == span_events == 0 and not missing_commands
          and not missing_events)

    # call order of design 6.3 inside every trial
    counts = cached(run, "log")
    order_keys = ("thermal_without_power", "thermal_from_unusable", "port_mismatch", "T_B_mismatch",
                  "environment_not_prepared", "environment_mismatch", "power_environment_mismatch",
                  "power_trial_mismatch", "request_mismatch", "unusable_reached_thermal")
    violations = {key: counts[key] for key in order_keys}
    check("第1步：每次试算按第 6.3 节顺序读取同一时刻的输入",
          "every thermal_derivative call follows, at the same instant, a Power trial whose PowerInputs carry T_B_K of "
          "the trial ThermalState and the request of that instant, whose PowerEnvironment equals the orbit_input of "
          "prepare_surface_environment for that instant, and whose usable ports reach ThermalInputs unchanged; the "
          "environment passed to thermal_derivative is the one prepared for that instant",
          f"{counts['power']} Power trials, {counts['thermal']} thermal calls, {counts['prepare']} prepared instants; "
          f"violations {violations}",
          counts["thermal"] > 0 and counts["power"] >= counts["thermal"] and not any(violations.values()))

    # irradiance from Orbit with the eclipse applied once
    g_mismatch = 0
    umbra_nonzero = 0
    sunlit_zero = 0
    phases = [(b.time_right_s, b.phase_after) for b in bounds]
    phase_times = [p[0] for p in phases]
    prepared = [e for e in run.recorder.entries if e["k"] == "prepare"]
    for entry in prepared:
        orbit = entry["orbit"]
        reference = sun_intensity(np.asarray(orbit["position_m"]), np.asarray(orbit["sun_position_m"]),
                                  include_eclipse=True)
        if reference != orbit["G_W_m2"]:
            g_mismatch += 1
        index = bisect.bisect_right(phase_times, entry["t"]) - 1
        phase = "sunlit" if index < 0 else phases[index][1]
        if phase == "umbra" and orbit["G_W_m2"] != 0.0:
            umbra_nonzero += 1
        if phase == "sunlit" and not orbit["G_W_m2"] > 0.0:
            sunlit_zero += 1
    check("第1步：G 取自 Orbit 的 sun_intensity 且日食只计一次",
          "G_W_m2 of every prepared instant equals Orbit sun_intensity(position, Sun, include_eclipse=True) of the same "
          "orbit_input bit for bit; G = 0 in umbra and G > 0 in sunlight",
          f"{len(prepared)} instants, {g_mismatch} mismatches, umbra with G > 0: {umbra_nonzero}, sunlight with G = 0: "
          f"{sunlit_zero}", prepared and g_mismatch == 0 and umbra_nonzero == 0 and sunlit_zero == 0)

    # every output saved
    saved = json.loads(baseline.archive_path.read_text(encoding="utf-8"))
    shapes = {
        "time_s": len(saved["time_s"]),
        "temperature_K": [len(saved["temperature_K"]), len(saved["temperature_K"][0])],
        "ports_W": {k: len(v) for k, v in saved["ports_W"].items()},
        "q_W": [len(saved["q_W"]), len(saved["q_W"][0])],
        "accepted_states": len(saved["accepted"]["state"]),
        "events": len(saved["events"]),
    }
    n = archive.time_s.size
    saved_ok = (saved["status"] == "completed" and shapes["time_s"] == n and shapes["temperature_K"] == [n, 6]
                and all(v == n for v in shapes["ports_W"].values()) and shapes["q_W"] == [n, 5]
                and shapes["accepted_states"] == len(archive.accepted["time_s"]) and shapes["events"] == len(archive.events))
    prerun_first = baseline.prerun_written is not None and baseline.prerun_written <= run.started_unix_s
    check("第1步：全部输出与启动前记录已保存",
          "CoupledArchive.to_json writes the archive with every output sample, accepted state and event; the resolved "
          "parameters, sources, initial values and environment configuration are written before the run starts "
          "(design 9.4)",
          f"archive {baseline.archive_path.name} {baseline.archive_path.stat().st_size} bytes, shapes {shapes}; "
          f"pre-run record {PRERUN_PATH.name} written at {baseline.prerun_written!r}, run started at "
          f"{run.started_unix_s!r} (Unix s)", saved_ok and prerun_first)

    case_record.metric("step1_wall_s", run.wall_s)
    case_record.metric("step1_output_samples", int(n))
    case_record.metric("step1_accepted_states", int(statistics["accepted_states"]))
    case_record.metric("step1_eclipse_entries", len(pen_in))
    case_record.metric("step1_eclipse_exits", len(pen_out))
    case_record.metric("step1_eclipse_reference_excess_s", worst_excess)
    case_record.metric("step1_power_trials", counts["power"])
    case_record.metric("step1_thermal_calls", counts["thermal"])
    case_record.metric("step1_prepared_instants", counts["prepare"])
    case_record.metric("step1_order_violations", int(sum(violations.values())))
    case_record.metric("step1_archive_bytes", baseline.archive_path.stat().st_size)
    case_record.metric("step1_events", [(float(e["time_s"]), e["kind"], e["source"]) for e in archive.events])
    check.finish()


def test_step2_invalid_power_result(baseline: SimpleNamespace, invalid_run: RunResult, case_record: Any) -> None:
    """Step 2a: a Power result with valid False is reported and stops the calculation; no protection rule."""

    check = Checks(case_record)
    run = invalid_run
    archive = run.archive
    error = dict(archive.error or {})
    entries = run.recorder.entries
    invalid = [i for i, e in enumerate(entries) if e["k"] == "power" and not e["valid"]]
    first_after = next((e for e in entries if e["k"] == "power" and e["t"] >= INVALID_FROM_S), None)
    t_invalid = entries[invalid[0]]["t"] if invalid else float("nan")
    check("第2步：注入一次 valid 为假的试算",
          f"exactly one Power trial returns valid False, the first Power trial at or after {INVALID_FROM_S} s",
          f"{len(invalid)} invalid results, first at {t_invalid!r} s; first trial at or after the injection time "
          f"{None if first_after is None else first_after['t']!r} s",
          len(invalid) == 1 and first_after is not None and first_after["t"] == t_invalid)
    message = str(run.error) if run.error else ""
    check("第2步：Power 结果无效时报告错误并停止本次计算",
          "CoupledRunError raised; archive status stopped with an error record of kind power_invalid at the invalid "
          "trial time carrying the Power reason; the message reports valid=False",
          f"error {type(run.error).__name__ if run.error else None}, status {archive.status}, kind {error.get('kind')}, "
          f"time {error.get('time_s')!r} s, context {error.get('context')}, power_reason {error.get('power_reason')!r}",
          run.error is not None and archive.status == "stopped" and error.get("kind") == "power_invalid"
          and error.get("time_s") == t_invalid and error.get("power_reason") == SPEC["injection"]["invalid"]["reason"]
          and "valid=False" in message)
    after = entries[invalid[0] + 1:] if invalid else []
    hook = after[0] if after else None
    later_integration = [e for e in after[1:] if e["k"] == "hook" and e["context"] != "output"]
    late_thermal = [e for e in entries if e["k"] == "thermal" and e["t"] >= INVALID_FROM_S]
    check("第2步：无效结果没有进入热导数且计算不再推进",
          "the trial with valid False ends without a thermal_derivative call; after it only the output samples of the "
          "accepted solution are evaluated; no thermal call at or after the injection time",
          f"entry after the invalid result: {None if hook is None else (hook['k'], hook.get('context'), hook.get('outcome'))}; "
          f"later integration, location or boundary trials {len(later_integration)}; thermal calls at or after "
          f"{INVALID_FROM_S} s {len(late_thermal)}",
          hook is not None and hook["k"] == "hook" and hook["outcome"] == "invalid" and not later_integration
          and not late_thermal)
    base = baseline.run1.archive
    base_events = [(float(e["time_s"]), e["kind"], e["source"]) for e in base.events if e["time_s"] < INVALID_FROM_S]
    run_events = [(float(e["time_s"]), e["kind"], e["source"]) for e in archive.events]
    final = archive.final_power_state
    check("第2步：无效结果不执行物理边界保护",
          "the events of the stopped run equal the events of the 24 h run before the injection time; no supply_loss "
          "after it; the final protection state is the one before the stop",
          f"events {run_events}; 24 h run before {INVALID_FROM_S} s {base_events}; final load_connected "
          f"{final.load_connected}, trip_latched {final.trip_latched}",
          run_events == base_events and final.load_connected and not final.trip_latched)
    n_b = len(archive.accepted["time_s"])
    prefix_states = np.array_equal(archive.accepted["state"], base.accepted["state"][:n_b])
    prefix_times = np.array_equal(archive.accepted["time_s"], base.accepted["time_s"][:n_b])
    last_accepted = float(archive.accepted["time_s"][-1])
    m = archive.time_s.size
    on_grid = np.isin(archive.time_s, base.time_s)
    index = np.searchsorted(base.time_s, archive.time_s[on_grid])
    same_samples = (np.array_equal(archive.temperature_K[on_grid], base.temperature_K[index])
                    and all(np.array_equal(archive.ports_W[p][on_grid], base.ports_W[p][index]) for p in PORTS)
                    and np.array_equal(archive.q_W[on_grid], base.q_W[index])
                    and all(np.array_equal(archive.lithium[x][on_grid], base.lithium[x][index]) for x in LITHIUM))
    # the stopped run samples its accepted solution up to the stop, so its last sample lies at the last accepted time
    extra_times = archive.time_s[~on_grid]
    base_state = accepted_state_at(base, last_accepted)
    extra_ok = (extra_times.size == 1 and float(extra_times[0]) == last_accepted and base_state is not None
                and np.array_equal(archive.temperature_K[~on_grid][0], base_state[:6])
                and float(archive.lithium["x_n"][~on_grid][0]) == base_state[6]
                and float(archive.lithium["x_p"][~on_grid][0]) == base_state[7])
    check("第2步：停止前的已接受状态与输出不受影响",
          "the accepted states of the stopped run equal the first accepted states of the 24 h run bit for bit and the "
          "last one lies before the injection time; its output samples on the 60 s grid equal those of the 24 h run "
          "and its final sample at the last accepted time equals the accepted state of the 24 h run at that time",
          f"{n_b} accepted states, identical times {prefix_times}, identical states {prefix_states}, last accepted "
          f"{last_accepted!r} s; {int(on_grid.sum())} grid samples identical {same_samples}; samples off the grid "
          f"{extra_times.tolist()} equal to the accepted state {extra_ok}",
          prefix_states and prefix_times and last_accepted < INVALID_FROM_S and same_samples and extra_ok)
    case_record.metric("step2_invalid_time_s", t_invalid)
    case_record.metric("step2_invalid_last_accepted_s", last_accepted)
    case_record.metric("step2_invalid_prefix_states", n_b)
    case_record.metric("step2_invalid_output_samples", int(m))
    check.finish()


def test_step2_event_required_handling(world: SimpleNamespace, baseline: SimpleNamespace, case_record: Any) -> None:
    """Step 2b: event_required returns to the boundary, applies the declared rule and recomputes Power and dT/dt."""

    check = Checks(case_record)
    run = baseline.run1
    archive = run.archive
    tolerance = float(archive.solver_settings["event_time_tol_s"])
    events = [dict(e) for e in archive.events]
    losses = [e for e in events if e["kind"] == "supply_loss"]
    injected = next((e for e in losses if WINDOW[0] <= e["time_s"] < WINDOW[1]), None)
    physical = next((e for e in losses if RAMP["start_s"] <= e["time_s"] < RAMP["end_s"]), None)
    expected_sequence = [("supply_loss", "located"), ("start", "command"), ("start", "command"), ("stop", "command"),
                         ("start", "command"), ("supply_loss", "located"), ("start", "command"), ("start", "command")]
    check("第2步：事件序列符合场景",
          f"applied Power events in order {expected_sequence}: injected supply loss, refused and accepted restart, "
          "stop and start, physical supply loss, refused and accepted restart",
          f"{[(round(e['time_s'], 4), e['kind'], e['source']) for e in events]}",
          [(e["kind"], e["source"]) for e in events] == expected_sequence and injected is not None
          and physical is not None)
    if injected is None or physical is None:
        check.finish()
        return

    # injected event_required: discarded trial, located boundary, declared rule, recomputation
    trial = first_event_trial(run, lambda e: e["reason"] == SPEC["injection"]["event_required"]["reason"])
    accepted_pairs = {(float(t), np.array(y).tobytes()) for t, y in zip(archive.accepted["time_s"],
                                                                         archive.accepted["state"], strict=True)}
    trial_saved = trial is not None and trial["state"] is not None and (
        (trial["time_s"], trial["state"].tobytes()) in accepted_pairs)
    check("第2步：event_required 为真的试算被丢弃",
          f"the first trial with the injected event_required result lies at or after the window start {WINDOW[0]} s "
          "with the load connected; no thermal_derivative call follows it and its state is not an accepted state",
          f"first trial {None if trial is None else (trial['time_s'], trial['connected'], trial['context'], trial['outcome'], trial['next_kind'])}; "
          f"its state saved {trial_saved}; aborted solver attempts {run.recorder.step_aborted + run.recorder.construct_aborted}",
          trial is not None and trial["time_s"] >= WINDOW[0] and trial["connected"] and trial["next_kind"] == "hook"
          and trial["outcome"] == "event_required" and not trial_saved)
    t_e = float(injected["time_s"])
    bracket = injected.get("bracket_s", [float("nan"), float("nan")])
    located = (injected["source"] == "located" and WINDOW[0] <= t_e <= WINDOW[0] + tolerance
               and bracket[1] - bracket[0] <= tolerance and bracket[0] < WINDOW[0] <= bracket[1]
               and accepted_state_at(archive, t_e) is not None)
    check("第2步：注入事件先回到约束边界",
          f"the boundary is located by bisection within event_time_tol_s {tolerance} s after the known window start "
          f"{WINDOW[0]} s: bracket low < start <= high, width <= tolerance, the event instant is an accepted state",
          f"event at {t_e!r} s, offset {t_e - WINDOW[0]!r} s, bracket {bracket}, width {bracket[1] - bracket[0]!r} s",
          located)
    facts = event_chain(run, injected)
    state_e = accepted_state_at(archive, t_e)
    rule_ok = (facts.get("applies") == 1 and facts.get("kinds") == ["supply_loss"] and facts.get("accepted_flags") == [True]
               and facts["decision"]["time_s"] == t_e and facts["decision"]["valid"] and facts["decision"]["event_required"]
               and not facts["decision"]["can_supply_request"]
               and facts["decision"]["reason"].startswith("supply_shortfall") and facts["decision_logged"]
               and facts["state_time"] == t_e and state_e is not None
               and facts["state_lithium"] == (float(state_e[6]), float(state_e[7]))
               and facts["updated"]["load_connected"] is False and facts["updated"]["trip_latched"] is True
               and facts["updated"]["lithium"] == facts["state_lithium"])
    check("第2步：注入事件按已声明规则更新负载离散状态",
          "apply_power_event is called once at the event instant with an accepted supply_loss, the Power decision of "
          "that instant (valid, event_required, can_supply_request False, reason supply_shortfall) and the accepted "
          "lithium fractions; it disconnects and latches the load and keeps x_n and x_p",
          f"{ {k: facts.get(k) for k in ('applies', 'kinds', 'accepted_flags', 'decision', 'state_time', 'updated')} }",
          rule_ok)
    recompute, next_thermal = facts.get("recompute"), facts.get("next_thermal")
    archived_recomputed = tuple(float(injected["recomputed"][p]) for p in PORTS)
    recompute_ok = (recompute is not None and recompute["time_s"] == t_e and not recompute["connected"]
                    and recompute["latched"] and recompute["valid"] and not recompute["event"]
                    and recompute["ports"][1] == 0.0 and recompute["ports"][3] == 0.0
                    and tuple(float(v) for v in recompute["ports"]) == archived_recomputed
                    and next_thermal is not None and next_thermal["time_s"] == t_e
                    and next_thermal["ports"] == tuple(float(v) for v in recompute["ports"]))
    check("第2步：注入事件后在同一时刻重新求功率与温度导数",
          "after the update Power is evaluated again at the event instant with the load disconnected (valid, no event, "
          "P_load_W = 0, Q_D_W = 0, equal to the archived recomputed ports) and the next thermal_derivative call is at "
          "the same instant with these ports",
          f"recompute {recompute}; archived {archived_recomputed}; next thermal call {next_thermal}", recompute_ok)

    command_events = {e["command_id"]: e for e in events if e["source"] == "command"}
    refused = command_events.get("ni002.start.in_window", {})
    accepted_start = command_events.get("ni002.start.after_window", {})
    restart_ok = (refused.get("decision", {}).get("can_supply_request") is False
                  and refused.get("after") == {"load_connected": False, "trip_latched": True}
                  and accepted_start.get("decision", {}).get("can_supply_request") is True
                  and accepted_start.get("after") == {"load_connected": True, "trip_latched": False})
    gap = disconnected_ok(run, t_e, float(accepted_start.get("time_s", t_e)))
    check("第2步：注入事件后只有 can_supply_request 为真的启动指令接通负载",
          "the start command inside the window meets can_supply_request False and leaves the load disconnected and "
          "latched; the start command after the window meets can_supply_request True and connects; between the event "
          "and the accepted start every output sample and thermal call has P_load_W = 0",
          f"refused {refused.get('time_s')} s decision {refused.get('decision')} after {refused.get('after')}; accepted "
          f"{accepted_start.get('time_s')} s decision {accepted_start.get('decision')} after {accepted_start.get('after')}; "
          f"disconnected interval {gap}",
          restart_ok and gap["samples"] > 0 and gap["max_P_load_W"] == 0.0 and gap["any_connected"] is False
          and gap["thermal_calls"] > 0 and gap["thermal_max_P_load_W"] == 0.0)

    # physical battery constraint event of the stand-in battery under the request ramp
    trial_p = first_event_trial(run, lambda e: e["reason"].startswith("supply_shortfall: the largest"))
    t_p = float(physical["time_s"])
    bracket_p = physical.get("bracket_s", [float("nan"), float("nan")])
    low_state = accepted_state_at(archive, float(bracket_p[0]))
    high_state = accepted_state_at(archive, t_p)
    decision_low = None if low_state is None else stand_in_decision(run, float(bracket_p[0]), low_state, connected=True,
                                                                     latched=False)
    decision_high = None if high_state is None else stand_in_decision(run, t_p, high_state, connected=True,
                                                                       latched=False)
    physical_ok = (trial_p is not None and trial_p["next_kind"] == "hook" and trial_p["outcome"] == "event_required"
                   and physical["source"] == "located" and bracket_p[1] - bracket_p[0] <= tolerance
                   and bracket_p[1] == t_p and decision_low is not None and decision_low.valid
                   and not decision_low.event_required and decision_high is not None and decision_high.valid
                   and decision_high.event_required and decision_high.reason_code == "supply_shortfall"
                   and str(physical["decision"]["reason"]).startswith("supply_shortfall: the largest"))
    check("第2步：电池约束事件由 Power 确认并定位",
          f"the stand-in battery reports a supply shortfall during the request ramp; the first such trial is discarded; "
          f"the boundary is bracketed within {tolerance} s and direct stand-in evaluations at the bracket ends give a "
          "supplied load at the low end and a confirmed supply_shortfall at the event state",
          f"first shortfall trial {None if trial_p is None else (trial_p['time_s'], trial_p['outcome'])}; event at "
          f"{t_p!r} s, bracket {bracket_p}, width {bracket_p[1] - bracket_p[0]!r} s, request {request_W(t_p):.3f} W; "
          f"stand-in at low {None if decision_low is None else decision_low.reason[:60]}; at high "
          f"{None if decision_high is None else decision_high.reason[:60]}",
          physical_ok)
    facts_p = event_chain(run, physical)
    state_p = accepted_state_at(archive, t_p)
    recompute_p, thermal_p = facts_p.get("recompute"), facts_p.get("next_thermal")
    chain_ok = (facts_p.get("applies") == 1 and facts_p.get("kinds") == ["supply_loss"]
                and facts_p["decision"]["time_s"] == t_p and facts_p["decision"]["event_required"]
                and not facts_p["decision"]["can_supply_request"] and state_p is not None
                and facts_p["state_lithium"] == (float(state_p[6]), float(state_p[7]))
                and facts_p["updated"]["load_connected"] is False and facts_p["updated"]["trip_latched"] is True
                and recompute_p is not None and recompute_p["time_s"] == t_p and recompute_p["valid"]
                and not recompute_p["event"] and recompute_p["ports"][1] == 0.0
                and thermal_p is not None and thermal_p["time_s"] == t_p
                and thermal_p["ports"] == tuple(float(v) for v in recompute_p["ports"]))
    check("第2步：电池约束事件按已声明规则处理并重算",
          "apply_power_event with supply_loss at the event instant and the accepted lithium fractions disconnects and "
          "latches; Power and the temperature derivatives are evaluated again at the same instant with P_load_W = 0",
          f"apply {facts_p.get('kinds')} decision {facts_p.get('decision')} updated {facts_p.get('updated')}; "
          f"recompute {recompute_p}; next thermal {thermal_p}", chain_ok)
    refused_p = command_events.get("ni002.start.in_ramp", {})
    accepted_p = command_events.get("ni002.start.after_ramp", {})
    t_refused, t_accepted = float(refused_p.get("time_s", math.nan)), float(accepted_p.get("time_s", math.nan))
    state_refused = accepted_state_at(archive, t_refused)
    state_accepted = accepted_state_at(archive, t_accepted)
    ref_refused = None if state_refused is None else stand_in_decision(run, t_refused, state_refused, connected=False,
                                                                       latched=True)
    ref_accepted = None if state_accepted is None else stand_in_decision(run, t_accepted, state_accepted,
                                                                         connected=False, latched=True)
    gap_p = disconnected_ok(run, t_p, t_accepted)
    restart_p_ok = (refused_p.get("decision", {}).get("can_supply_request") is False
                    and refused_p.get("after") == {"load_connected": False, "trip_latched": True}
                    and accepted_p.get("decision", {}).get("can_supply_request") is True
                    and accepted_p.get("after") == {"load_connected": True, "trip_latched": False}
                    and ref_refused is not None and ref_refused.can_supply_request is False
                    and ref_accepted is not None and ref_accepted.can_supply_request is True
                    and gap_p["samples"] > 0 and gap_p["max_P_load_W"] == 0.0 and gap_p["any_connected"] is False)
    check("第2步：电池约束事件后只有 can_supply_request 为真的启动指令接通负载",
          "the restart in eclipse during the ramp meets can_supply_request False (also in a direct stand-in "
          "evaluation of the accepted state with the ramp request) and stays disconnected; the restart in sunlight "
          "after the ramp meets can_supply_request True and connects; P_load_W = 0 in between",
          f"refused {t_refused} s request {request_W(t_refused):.3f} W, runner {refused_p.get('decision', {}).get('can_supply_request')}, "
          f"stand-in {None if ref_refused is None else ref_refused.can_supply_request}; accepted {t_accepted} s, "
          f"runner {accepted_p.get('decision', {}).get('can_supply_request')}, stand-in "
          f"{None if ref_accepted is None else ref_accepted.can_supply_request}; disconnected interval {gap_p}",
          restart_p_ok)
    case_record.metric("step2_event_tolerance_s", tolerance)
    case_record.metric("step2_injected_window_start_s", WINDOW[0])
    case_record.metric("step2_injected_event_s", t_e)
    case_record.metric("step2_injected_offset_s", t_e - WINDOW[0])
    case_record.metric("step2_injected_bracket_width_s", float(bracket[1] - bracket[0]))
    case_record.metric("step2_injected_refused_start_s", refused.get("time_s"))
    case_record.metric("step2_injected_accepted_start_s", accepted_start.get("time_s"))
    case_record.metric("step2_physical_event_s", t_p)
    case_record.metric("step2_physical_bracket_width_s", float(bracket_p[1] - bracket_p[0]))
    case_record.metric("step2_physical_request_W", request_W(t_p))
    case_record.metric("step2_physical_x_n", None if state_p is None else float(state_p[6]))
    case_record.metric("step2_physical_T_B_K", None if state_p is None else float(state_p[B_INDEX]))
    case_record.metric("step2_physical_refused_start_s", t_refused)
    case_record.metric("step2_physical_refused_request_W", request_W(t_refused))
    case_record.metric("step2_physical_accepted_start_s", t_accepted)
    check.finish()


def test_step3_accepted_states_and_temperature_ports(world: SimpleNamespace, baseline: SimpleNamespace,
                                                     case_record: Any) -> None:
    """Step 3: temperatures are saved only after acceptance; Compute reads J, Power reads B in the next trial."""

    check = Checks(case_record)
    run = baseline.run1
    archive = run.archive
    statistics = archive.statistics
    table = cached(run, "table")
    counts = table["counts"]
    n_accepted = len(archive.accepted["time_s"])
    check("第3步：每个已接受状态都来自被接受的积分步",
          "every accepted state of the archive is the initial ThermalState, a carried state at a segment start, the "
          "end of a solver step equal bit for bit to y_old + h K^T b of its recorded stage derivatives (Dormand-Prince "
          "weights), the continuous extension of such a step at a located charge-limit change, or one Euler bridge of "
          "event location; each step starts from the previous accepted state",
          f"{n_accepted} accepted states: explained {counts['explained']}, unexplained {counts['unexplained']}; full "
          f"steps {counts['full_steps']}, truncated {counts['truncated_steps']}, bridges {counts['event_bridge']}, "
          f"segment starts {counts['segment_start']}, final {counts['final']}; largest rebuild deviation "
          f"{table['worst']!r}; pieces left {table['pieces_left']}",
          counts["unexplained"] == 0 and counts["explained"] == n_accepted and table["pieces_left"] == 0
          and table["worst"] == 0.0)

    accepted_pairs = {(float(t), np.array(y).tobytes()) for t, y in zip(archive.accepted["time_s"],
                                                                         archive.accepted["state"], strict=True)}
    # the only solver evaluations at accepted states: f(t0, y0) of a solver started at an accepted state and the
    # FSAL value of a step that was committed whole; every other evaluated state is a trial state
    full_ends = {(r["t_new"], r["y_new"].tobytes()) for r in table["full_records"]}
    # The located boundary state of an event is accepted on purpose (chapter 7, design 5.6: return to the boundary
    # and accept it, then apply the rule). It is the Euler bridge y_low + (t_b - t_low) f(t_low, y_low), the same
    # expression as the initial step-size probe of the last sub-integration solver started at y_low, so that probe
    # trial coincides with it bit for bit. Such coincidences are counted separately and checked to be bridge ends
    # followed by an applied event at the same instant; any other match is a leak.
    bridge_ends = {(float(t), np.array(y).tobytes()) for t, y, k in zip(archive.accepted["time_s"],
                                                                         archive.accepted["state"],
                                                                         archive.accepted["kind"], strict=True)
                   if k == "event_bridge"}
    event_instants = {float(e["time_s"]) for e in archive.events}
    starts = 0
    trial_states = 0
    leaked = 0
    at_boundary: list[tuple[float, str]] = []
    roles: Counter = Counter()

    def classify(key: tuple[float, bytes], label: str) -> None:
        nonlocal leaked
        if key not in accepted_pairs:
            return
        if key in bridge_ends and key[0] in event_instants:
            at_boundary.append((key[0], label))
        else:
            leaked += 1

    for entry in run.recorder.entries:
        if entry["k"] == "f":
            key = (entry["t"], entry["y"].tobytes())
            roles[entry["role"]] += 1
            if entry["role"] == "start" or (entry["role"] == "stage" and key in full_ends):
                starts += 1
                continue
            trial_states += 1
            classify(key, f"solver {entry['role']}")
        elif (entry["k"] == "hook" and entry["outcome"] in ("event_required", "invalid") and entry["sid"] >= 0
              and entry["context"] in ("integration", "event_location")):
            trial_states += 1
            classify((entry["t"], np.array(entry["state"]).tobytes()), f"{entry['context']} {entry['outcome']}")
    for record in table["discarded"] + table["truncated_records"]:
        trial_states += 1
        classify((record["t_new"], record["y_new"].tobytes()), "unused step end")
    boundary_instants = sorted({t for t, _ in at_boundary})
    construction = roles["start"]
    rejected_committed = sum(len(r["calls"]) // 6 - 1 for r in table["committed"])
    rejected_discarded = sum(len(r["calls"]) // 6 - 1 for r in table["discarded"])
    aborted = run.recorder.step_aborted + run.recorder.construct_aborted
    located_instants = sorted(float(e["time_s"]) for e in archive.events if e["source"] == "located")
    check("第3步：被拒绝的积分步与丢弃的试算不写入组件温度",
          "no stage state, rejected candidate, step-size probe, aborted attempt, discarded event-search step, step end "
          "replaced at a charge-limit change or trial with event_required or valid False appears among the accepted "
          "states; the only coincidences allowed are located boundary states, accepted as event bridges at the instant "
          "where the event is applied (chapter 7)",
          f"{trial_states} trial states, {leaked} found among the accepted states outside located boundaries; "
          f"coincidences with accepted boundary states {at_boundary} at the located events {located_instants}; "
          f"rejected attempts behind accepted steps {rejected_committed}, discarded event-search steps "
          f"{len(table['discarded'])} with {rejected_discarded} rejected attempts, aborted attempts {aborted}, solver "
          f"starts at accepted states {construction}",
          trial_states > 0 and rejected_committed > 0 and aborted > 0 and leaked == 0
          and set(boundary_instants) <= set(located_instants))

    outputs = rebuild_outputs(run, table)
    check("第3步：输出样本取自已接受的解",
          "every output sample of the six temperatures and the two lithium fractions equals the continuous extension "
          "of the accepted step that contains it, rebuilt from the recorded stage derivatives (relative difference "
          "<= 1e-12 for temperatures, absolute <= 1e-12 for lithium fractions)",
          f"{outputs['samples']} samples, {outputs['identical']} identical bit for bit, largest relative temperature "
          f"difference {outputs['worst_T_rel']!r}, largest lithium difference {outputs['worst_x']!r}",
          outputs["worst_T_rel"] <= 1e-12 and outputs["worst_x"] <= 1e-12)

    # temperature port to Compute: T_J of Compute01
    instance_map = archive.instance_map
    nodes_map = {node: list(instance_map["nodes"][node]) for node in NODES}
    output_thermal = [e for e in run.recorder.entries if e["k"] == "thermal"]
    by_time = {}
    for entry in output_thermal:
        by_time.setdefault(entry["t"], []).append(entry)
    j_mismatch = 0
    for k, tau in enumerate(float(v) for v in archive.time_s):
        candidates = by_time.get(tau, [])
        if not any(np.array_equal(e["T"], archive.temperature_K[k]) and e["T_J_out"] == archive.temperature_K[k, J_INDEX]
                   for e in candidates):
            j_mismatch += 1
    counts_log = cached(run, "log")
    check("第3步：计算域读取 J 的温度",
          "the instance map binds node J to Compute01 and the P_load_W port to Compute01; ThermalEvaluation.T_J_K "
          "equals temperature_K[1] of the evaluated state in every call; at every output sample the archived J "
          "temperature equals the T_J_K port of the thermal evaluation of that sample",
          f"J -> {nodes_map['J']}, P_load_W -> {instance_map['ports']['P_load_W']}; evaluation copy mismatches "
          f"{counts_log['evaluation_copy_mismatch']} in {counts_log['thermal']} calls; output samples without a "
          f"matching T_J_K {j_mismatch} of {archive.time_s.size}",
          nodes_map["J"] == ["Compute01"] and instance_map["ports"]["P_load_W"] == "Compute01"
          and counts_log["evaluation_copy_mismatch"] == 0 and j_mismatch == 0)

    # temperature port to Power: T_B of Battery01 in every trial and after every acceptance
    power_calls = [e for e in run.recorder.entries if e["k"] == "power"]
    first = power_calls[0]
    initial_b = float(world.assembly.initial_temperature_K[B_INDEX])
    record_b = float(run.power_parameters.provenance["initial_state"]["T_B_K"])
    by_instant: dict[float, list[tuple[float, float, float]]] = {}
    for entry in power_calls:
        by_instant.setdefault(entry["t"], []).append((entry["T_B"], entry["x_n"], entry["x_p"]))
    unread = 0
    for t, y in zip(archive.accepted["time_s"], archive.accepted["state"], strict=True):
        triple = (float(y[B_INDEX]), float(y[6]), float(y[7]))
        if triple not in by_instant.get(float(t), []):
            unread += 1
    temperature_fields = [f.name for cls in (ps.PowerState, ps.PowerResult, ps.PowerInputs)
                          for f in dataclasses.fields(cls) if f.name.startswith("T_") or "temperature" in f.name]
    check("第3步：Power 下次试算读取 B 的温度",
          "every Power trial reads T_B_K, x_n and x_p bit for bit from the trial state of the same evaluation; the "
          "first trial reads the B temperature of the initial ThermalState, not the copy in the Power scene record; "
          "the B temperature of every accepted state is read by a Power evaluation at that instant; only PowerInputs "
          "carries T_B_K and the battery response echoes it unchanged",
          f"{counts_log['power']} Power trials, {counts_log['power_trial_mismatch']} mismatches; first trial at "
          f"{first['t']!r} s reads {first['T_B']!r} K, ThermalState {initial_b!r} K, Power record {record_b!r} K; "
          f"accepted states not read by Power {unread} of {n_accepted}; temperature fields {temperature_fields}; "
          f"battery echo mismatches {counts_log['battery_echo_mismatch']}",
          counts_log["power_trial_mismatch"] == 0 and first["t"] == 0.0 and first["T_B"] == initial_b
           and initial_b == record_b and unread == 0 and temperature_fields == ["T_B_K"]
          and counts_log["battery_echo_mismatch"] == 0)
    case_record.metric("step3_accepted_states", n_accepted)
    case_record.metric("step3_full_steps", counts["full_steps"])
    case_record.metric("step3_truncated_steps", counts["truncated_steps"])
    case_record.metric("step3_event_bridges", counts["event_bridge"])
    case_record.metric("step3_rebuild_max_deviation", table["worst"])
    case_record.metric("step3_trial_states_not_saved", trial_states - len(at_boundary))
    case_record.metric("step3_trial_states_checked", trial_states)
    case_record.metric("step3_boundary_coincidences", [list(item) for item in at_boundary])
    case_record.metric("step3_rejected_attempts", rejected_committed)
    case_record.metric("step3_discarded_search_steps", len(table["discarded"]))
    case_record.metric("step3_aborted_attempts", aborted)
    case_record.metric("step3_output_identical", outputs["identical"])
    case_record.metric("step3_output_samples", outputs["samples"])
    case_record.metric("step3_output_max_rel", outputs["worst_T_rel"])
    case_record.metric("step3_power_trials", counts_log["power"])
    case_record.metric("step3_first_T_B_K", first["T_B"])
    case_record.metric("step3_record_T_B_K", record_b)
    case_record.metric("step3_rk45_weights_equal_scipy", bool(np.array_equal(REF.DOPRI5_B, RK45.B)))
    assert statistics["accepted_states"] == n_accepted
    check.finish()


def test_step4_single_source_and_no_power_rules(world: SimpleNamespace, baseline: SimpleNamespace,
                                                invalid_run: RunResult, hot_run: RunResult, case_record: Any) -> None:
    """Step 4: Orbit's power_considering_thermal stops updating S; Thermal adds no power-off or throttling rule."""

    check = Checks(case_record)
    run = baseline.run1
    archive = run.archive
    calls = {"24 h run": run.recorder.orbit_thermal_calls, "repeat run": baseline.run2_counts["orbit_thermal_calls"],
             "invalid run": invalid_run.recorder.orbit_thermal_calls, "hot run": hot_run.recorder.orbit_thermal_calls}
    sources = sorted(list((THERMAL_DIR / "thermal").glob("*.py")) + list((THERMAL_DIR / "sdtwin_sim").glob("*.py")))
    referencing = [p.relative_to(THERMAL_DIR).as_posix() for p in sources if "power_considering_thermal" in identifiers(p)]
    procedure = archive.provenance["procedure"]
    check("第4步：Orbit 的 power_considering_thermal 不再更新太阳能板温度",
          "the Orbit function, replaced by a sentinel that fails when called, is called 0 times in every run; no "
          "source of thermal or sdtwin_sim names it; the archive records it as not called",
          f"calls {calls}; sources naming it {referencing}; archive note {procedure.get('orbit_power_considering_thermal')!r}",
          all(v == 0 for v in calls.values()) and not referencing
          and "not called" in str(procedure.get("orbit_power_considering_thermal")))

    counts = cached(run, "log")
    table = cached(run, "table")
    state_vector = list(procedure["state_vector"])
    check("第4步：每个组件温度只有一个更新来源",
          "the coupled state vector holds one temperature per node; every derivative handed to the solver equals bit "
          "for bit the dT_dt_K_s of thermal_derivative and the lithium rates of Power for the same trial; every "
          "accepted state is rebuilt from these derivatives alone, so S and every other node are updated only by "
          "integrating T3",
          f"state vector {state_vector}; {counts['solver_values']} solver values, unpaired "
          f"{counts['solver_value_unpaired']}, state mismatches {counts['solver_state_mismatch']}, derivative "
          f"mismatches {counts['solver_derivative_mismatch']}; accepted states unexplained {table['counts']['unexplained']}",
          state_vector == list(NODES) + list(LITHIUM) and counts["solver_values"] > 0
          and counts["solver_value_unpaired"] == 0 and counts["solver_state_mismatch"] == 0
          and counts["solver_derivative_mismatch"] == 0 and table["counts"]["unexplained"] == 0)

    # load changes only at Power events
    times = archive.time_s
    connected = archive.power_diagnostics["load_connected"]
    events = [dict(e) for e in archive.events]
    unexplained_changes = []
    for k in range(1, times.size):
        if connected[k] != connected[k - 1]:
            cause = [e for e in events if times[k - 1] < e["time_s"] <= times[k]
                     and e["after"]["load_connected"] == bool(connected[k])]
            if not cause:
                unexplained_changes.append(float(times[k]))
    allowed = {("start", "command"), ("stop", "command"), ("supply_loss", "located"), ("supply_loss", "boundary_decision")}
    foreign = [(e["kind"], e["source"]) for e in events if (e["kind"], e["source"]) not in allowed]
    loss_from_power = all(e["decision"]["valid"] and e["decision"]["event_required"]
                          and str(e["decision"]["reason"]).startswith("supply_shortfall")
                          for e in events if e["kind"] == "supply_loss")
    excursions = [dict(w) for w in archive.range_warnings if w.get("source") == "accepted_states"]
    excursion_nodes = sorted({w["node"] for w in excursions})
    in_excursion_connected = 0
    load_off_target = 0
    for w in excursions:
        last = w["last_time_s"] if w.get("returned_s") is None else w["returned_s"]
        mask = (times >= w["time_s"]) & (times <= last) & connected
        for k in np.flatnonzero(mask):
            in_excursion_connected += 1
            request = request_W(float(times[k]))
            if abs(archive.ports_W["P_load_W"][k] - request) > 1e-9 * request:
                load_off_target += 1
    check("第4步：热模块没有增加断电或降频规则",
          "the load state changes only at applied Power events (commands or a Power supply_shortfall decision); every "
          "thermal call receives P_load_W of its Power result unchanged; while node temperatures lie outside their "
          "declared ranges the connected load keeps P_load_W equal to the request",
          f"load changes without an event {unexplained_changes}; foreign events {foreign}; supply losses from Power "
          f"decisions {loss_from_power}; port mismatches {counts['port_mismatch']}; excursions of nodes "
          f"{excursion_nodes} ({len(excursions)} records), {in_excursion_connected} connected samples inside them, "
          f"{load_off_target} with P_load_W different from the request",
          not unexplained_changes and not foreign and loss_from_power and counts["port_mismatch"] == 0
          and in_excursion_connected > 0 and load_off_target == 0)

    # hot probe: J and B above their declared ranges
    hot = hot_run.archive
    probe = SPEC["hot_probe"]
    ranges = world.params.provenance_as_dict()["temperature_range_K"]
    hot_nodes = sorted({w["node"] for w in hot.range_warnings if w.get("source") == "accepted_states"})
    p_load = hot.ports_W["P_load_W"]
    base_request = float(SPEC["power"]["base_request_W"])
    hot_ok = (hot_run.error is None and hot.status == "completed" and len(hot.events) == 0
              and bool(np.all(hot.power_diagnostics["load_connected"]))
              and float(np.max(np.abs(p_load - base_request))) <= 1e-9 * base_request
              and {"B", "J"} <= set(hot_nodes))
    check("第4步：计算节点与电池超出声明范围时只报告不断电",
          f"a {probe['duration_s']} s run from J = {probe['temperature_K']['J']} K above {ranges['J']} K and B = "
          f"{probe['temperature_K']['B']} K above {ranges['B']} K completes without events, the load stays connected "
          "with P_load_W equal to the request, and the excursions of J and B are recorded",
          f"status {hot.status}, error {None if hot_run.error is None else type(hot_run.error).__name__}, events "
          f"{len(hot.events)}, load connected at every sample {bool(np.all(hot.power_diagnostics['load_connected']))}, "
          f"largest |P_load_W - request| {float(np.max(np.abs(p_load - base_request))):.3g} W, excursion nodes {hot_nodes}",
          hot_ok)

    # direct probe of thermal_derivative at the hot state
    state = ThermalState(hot.run_id, 0.0, [probe["temperature_K"][n] for n in NODES])
    sample = hot_run.provider.sample(0.0)
    ports = {p: float(hot.ports_W[p][0]) for p in PORTS}
    inputs = ThermalInputs(hot.run_id, 0.0, sample.surface_environment, ports["P_pv_W"], ports["P_load_W"],
                           ports["Q_B_W"], ports["Q_D_W"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        evaluation = thermal_derivative(state, inputs, world.params)
    messages = [str(w.message) for w in caught if issubclass(w.category, ThermalRangeWarning)]
    C = dict(zip(NODES, (float(v) for v in world.params.C_J_K), strict=True))
    R = dict(zip(PATHS, (float(v) for v in world.params.R_K_W), strict=True))
    T = probe["temperature_K"]
    q = REF.heat_flows([T[n] for n in NODES], R)
    error_j = abs(C["J"] * float(evaluation.dT_dt_K_s[J_INDEX]) - (ports["P_load_W"] - q["JC"])) / (
        abs(ports["P_load_W"]) + abs(q["JC"]))
    error_b = abs(C["B"] * float(evaluation.dT_dt_K_s[B_INDEX]) - (ports["Q_B_W"] - q["BR"])) / (
        abs(ports["Q_B_W"]) + abs(q["BR"]))
    check("第4步：热导数在超范围时使用 Power 给出的原值",
          "thermal_derivative at J and B above their declared ranges emits ThermalRangeWarning for J and B and keeps "
          "C_J dT_J/dt = P_load - q_JC and C_B dT_B/dt = Q_B - q_BR with the Power values (relative error <= 1e-12)",
          f"warnings {[m[:40] for m in messages]}; P_load_W {ports['P_load_W']!r} W, Q_B_W {ports['Q_B_W']!r} W; "
          f"relative errors J {error_j:.3g}, B {error_b:.3g}",
          any("node J" in m for m in messages) and any("node B" in m for m in messages)
          and error_j <= 1e-12 and error_b <= 1e-12)

    words = {}
    for path in sorted((THERMAL_DIR / "thermal").glob("*.py")):
        names = {name.lower() for name in identifiers(path)}
        hits = sorted(name for name in names if any(word in name for word in LOAD_CONTROL_WORDS))
        if hits:
            words[path.name] = hits
    check("第4步：热模块源码不含负载控制规则",
          f"no name, attribute, definition, argument or import of the thermal package contains {LOAD_CONTROL_WORDS}",
          f"hits {words}", not words)
    case_record.metric("step4_orbit_thermal_calls", calls)
    case_record.metric("step4_excursion_nodes", excursion_nodes)
    case_record.metric("step4_excursion_records", len(excursions))
    case_record.metric("step4_excursion_connected_samples", in_excursion_connected)
    case_record.metric("step4_min_T_K", {n: float(np.min(archive.temperature_K[:, i])) for i, n in enumerate(NODES)})
    case_record.metric("step4_max_T_K", {n: float(np.max(archive.temperature_K[:, i])) for i, n in enumerate(NODES)})
    case_record.metric("step4_hot_excursion_nodes", hot_nodes)
    case_record.metric("step4_hot_wall_s", hot_run.wall_s)
    check.finish()


def test_step5_repeat_archive_and_counts(world: SimpleNamespace, baseline: SimpleNamespace, case_record: Any) -> None:
    """Step 5: repeat with the same inputs, compare, check the archive fields and record Power and rejection counts."""

    check = Checks(case_record)
    run1, run2 = baseline.run1, baseline.run2
    a1, a2 = run1.archive, run2.archive
    first, second = a1.as_dict(), a2.as_dict()
    comparison = compare_trees(first, second)
    arrays_equal = all([
        np.array_equal(a1.time_s, a2.time_s), np.array_equal(a1.temperature_K, a2.temperature_K),
        np.array_equal(a1.dT_dt_K_s, a2.dT_dt_K_s), np.array_equal(a1.q_W, a2.q_W),
        np.array_equal(a1.Q_env_W, a2.Q_env_W), np.array_equal(a1.Q_emit_W, a2.Q_emit_W),
        all(np.array_equal(a1.ports_W[p], a2.ports_W[p]) for p in PORTS),
        all(np.array_equal(a1.lithium[x], a2.lithium[x]) for x in LITHIUM),
        np.array_equal(a1.accepted["state"], a2.accepted["state"]), np.array_equal(a1.accepted["time_s"], a2.accepted["time_s"]),
        np.array_equal(a1.steps["t_new_s"], a2.steps["t_new_s"]),
    ])
    bitwise = comparison["different"] == 0 and arrays_equal
    check("第5步：相同输入的两次运行结果相同",
          f"every leaf of the two archives except the measured wall time is identical, or numeric leaves differ by at "
          f"most {REPEAT_TOL:g}; the in-memory arrays are equal",
          f"{comparison['leaves']} leaves, {comparison['numeric']} numeric, {comparison['different']} different, largest "
          f"difference {comparison['max_abs']!r}, examples {comparison['examples']}; arrays equal {arrays_equal}; wall "
          f"time {run1.wall_s:.1f} s and {run2.wall_s:.1f} s",
           bitwise)

    saved = json.loads(baseline.archive_path.read_text(encoding="utf-8"))
    epoch = datetime.fromisoformat(saved["epoch_utc"])
    n = len(saved["time_s"])
    times = np.array(saved["time_s"], dtype=float)
    asset_versions = {}
    scene_doc = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
    for instance in scene_doc["instances"]:
        asset = json.loads((SCENE_PATH.parent / instance["asset_ref"]).read_text(encoding="utf-8"))
        asset_versions[instance["instance_id"]] = (asset["asset_id"], asset["asset_version"])
    archived_assets = {k: (v["asset_id"], v["asset_version"])
                       for k, v in saved["provenance"]["thermal_parameters"]["assets"].items()}
    power_assets = {k: (v["asset_id"], v["asset_version"])
                    for k, v in saved["provenance"]["power"]["parameters_provenance"]["assets"].items()}
    example_asset, example_scene = ps.example_power_records()
    expected_power_assets = {g: (example_asset[g]["asset_id"], example_asset[g]["asset_version"])
                             for g in ("solar", "battery", "pdu")}
    numerics = example_scene["numerics"]
    settings = saved["solver_settings"]
    fields = {
        "run_id": saved["run_id"] == SPEC["run_id"],
        "UTC epoch": epoch == world.epoch and epoch.utcoffset() == timedelta(0),
        "time_s": n == a1.time_s.size and times[0] == 0.0 and times[-1] == DURATION_S
        and bool(np.all(np.diff(times) == float(numerics["output_step_s"]))),
        "component ids and state order": saved["node_order"] == list(NODES)
        and {k: list(v) for k, v in saved["instance_map"]["nodes"].items()} == NODE_INSTANCES
        and saved["instance_map"]["ports"] == PORT_INSTANCE and saved["path_order"] == list(PATHS)
        and saved["exposed_node_order"] == ["S", "R"] and saved["port_order"] == list(PORTS)
        and saved["lithium_order"] == list(LITHIUM)
        and saved["provenance"]["procedure"]["state_vector"] == list(NODES) + list(LITHIUM),
        "temperatures": np.array(saved["temperature_K"], dtype=float).shape == (n, 6)
        and bool(np.all(np.isfinite(np.array(saved["temperature_K"], dtype=float)))),
        "four Power ports": list(saved["ports_W"]) == list(PORTS)
        and all(np.array(saved["ports_W"][p], dtype=float).shape == (n,) for p in PORTS),
        "heat flows": np.array(saved["q_W"], dtype=float).shape == (n, 5)
        and np.array(saved["Q_env_W"], dtype=float).shape == (n, 2)
        and np.array(saved["Q_emit_W"], dtype=float).shape == (n, 2),
        "solver settings": settings["method"] == "RK45"
        and all(settings[k] == float(numerics[k]) for k in ("rtol", "atol_T_K", "atol_x", "max_step_s",
                                                             "output_step_s", "environment_step_s",
                                                             "event_time_tol_s")),
        "parameter versions": archived_assets == asset_versions and power_assets == expected_power_assets
        and saved["provenance"]["caller"]["scene"]["scene_version"] == scene_doc["scene_version"]
        and all(k in saved["provenance"]["software"] for k in ("python", "numpy", "scipy", "ntu_space_dynamics")),
    }
    check("第5步：归档字段完整",
          "the saved archive contains run_id, the UTC epoch, time_s, component identifiers with node, path, port and "
          "state order, temperatures, the four Power ports, heat flows, the solver settings of the Power numerics and "
          "the parameter versions of every thermal asset, the Power assets and the scene (design 9.4)",
          f"{fields}; thermal assets {archived_assets}; Power assets {power_assets}; solver settings {settings}",
          all(fields.values()))

    # value status and the pre-run record of design 9.4
    prerun = json.loads(PRERUN_PATH.read_text(encoding="utf-8"))
    archived_values = saved["provenance"]["thermal_values"]
    initial = saved["accepted"]["state"][0]
    statuses = saved["provenance"]["caller"]["value_status"]
    data_status = saved["provenance"]["power"]["parameters_provenance"]["data_status"]
    prerun_ok = (prerun["thermal_parameters"]["C_J_K"] == archived_values["C_J_K"]
                 and prerun["thermal_parameters"]["R_K_W"] == archived_values["R_K_W"]
                 and prerun["thermal_parameters"]["provenance"] == saved["provenance"]["thermal_parameters"]
                 and prerun["environment"] == saved["provenance"]["environment"]
                 and [prerun["initial_state"]["temperature_K"][k] for k in NODES] == initial[:6]
                 and [prerun["initial_state"]["x_n"], prerun["initial_state"]["x_p"]] == initial[6:]
                 and prerun["solver_settings"] == settings
                 and statuses == ["illustrative_test_value"] and "illustrative" in data_status)
    check("第5步：启动前记录与归档一致并标明数值性质",
          "the pre-run record holds the same resolved capacitances, resistances, thermal provenance, environment "
          "configuration, initial temperatures and lithium fractions and solver settings as the archive; asset values "
          "are labelled illustrative test values, not measured device parameters",
          f"C equal {prerun['thermal_parameters']['C_J_K'] == archived_values['C_J_K']}, R equal "
          f"{prerun['thermal_parameters']['R_K_W'] == archived_values['R_K_W']}, environment equal "
          f"{prerun['environment'] == saved['provenance']['environment']}, initial state {initial}; value status "
          f"{statuses}; Power data status {data_status[:60]!r}", prerun_ok)

    # Power root solving and trial rejection counts
    s1, s2 = a1.statistics, a2.statistics
    entries = run1.recorder.entries
    spy_calls = sum(1 for e in entries if e["k"] == "power")
    injected = sum(1 for e in entries if e["k"] == "power" and e["reason"] == SPEC["injection"]["event_required"]["reason"])
    table = cached(run1, "table")
    rejected_committed = sum(len(r["calls"]) // 6 - 1 for r in table["committed"])
    rejected_discarded = sum(len(r["calls"]) // 6 - 1 for r in table["discarded"])
    aborted = run1.recorder.step_aborted + run1.recorder.construct_aborted
    counts_ok = (s1["power_calls"] == spy_calls and run1.call_stats["solve_calls"] == spy_calls - injected
                 and s1["rejected_steps"] == rejected_committed
                 and s1["discarded_event_search_steps"] == len(table["discarded"])
                 and s1["discarded_event_search_rejections"] == rejected_discarded
                 and s1["event_aborted_attempts"] == aborted
                 and s1["rejected_steps_total"] == rejected_committed + aborted + len(table["discarded"]) + rejected_discarded
                 and s2["power_calls"] == baseline.run2_counts["power_spy_calls"] == spy_calls
                 and s2["rejected_steps"] == baseline.run2_counts["committed_rejected"] == rejected_committed
                 and s2["event_aborted_attempts"] == baseline.run2_counts["aborted"] == aborted
                 and run2.call_stats == run1.call_stats)
    check("第5步：记录 Power 求根次数与试算拒绝次数",
          "the archive counts equal independent counts: Power calls equal the calls seen by the spy and the stand-in "
          "solve counter plus the injected results; rejected steps, discarded event-search steps and aborted attempts "
          "equal the counts of the recording RK45 solver; both runs give the same counts",
          f"Power calls {s1['power_calls']} archive, {spy_calls} spy, {run1.call_stats['solve_calls']} stand-in solves "
          f"plus {injected} injected, battery evaluations {run1.call_stats['battery_evaluations']}; rejected steps "
          f"{s1['rejected_steps']} archive, {rejected_committed} solver; discarded search steps "
          f"{s1['discarded_event_search_steps']} and {len(table['discarded'])}; aborted attempts "
          f"{s1['event_aborted_attempts']} and {aborted}; total rejected {s1['rejected_steps_total']}; repeat run "
          f"{baseline.run2_counts} and {run2.call_stats}", counts_ok)
    case_record.metric("step5_leaves_compared", comparison["leaves"])
    case_record.metric("step5_numeric_leaves", comparison["numeric"])
    case_record.metric("step5_different_leaves", comparison["different"])
    case_record.metric("step5_max_abs_difference", comparison["max_abs"])
    case_record.metric("step5_bitwise_identical", bitwise)
    case_record.metric("step5_archive_fields", fields)
    case_record.metric("step5_power_calls", s1["power_calls"])
    case_record.metric("step5_power_calls_by_context", dict(s1["power_calls_by_context"]))
    case_record.metric("step5_stand_in_solves", run1.call_stats["solve_calls"])
    case_record.metric("step5_injected_results", injected)
    case_record.metric("step5_battery_evaluations", run1.call_stats["battery_evaluations"])
    case_record.metric("step5_accepted_steps", s1["accepted_steps"])
    case_record.metric("step5_rejected_steps", s1["rejected_steps"])
    case_record.metric("step5_event_aborted_attempts", s1["event_aborted_attempts"])
    case_record.metric("step5_discarded_search_steps", s1["discarded_event_search_steps"])
    case_record.metric("step5_rejected_steps_total", s1["rejected_steps_total"])
    case_record.metric("step5_function_evaluations", s1["function_evaluations"])
    case_record.metric("step5_event_searches", s1["event_searches"])
    case_record.metric("step5_bisection_iterations", s1["bisection_iterations"])
    case_record.metric("step5_wall_s", [run1.wall_s, run2.wall_s])
    check.finish()


# ------------------------------------------------------------------------------------------------------------ summary


def _sci_cn(value: Any) -> str:
    """Plain Chinese form of a small number without brackets, carets or ASCII minus signs."""

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "未得到"
    if value == 0.0:
        return "0"
    exponent = math.floor(math.log10(abs(value)))
    mantissa = round(value / 10 ** exponent, 1)
    if abs(mantissa) >= 10.0:
        mantissa, exponent = round(mantissa / 10.0, 1), exponent + 1
    sign = "−" if exponent < 0 else ""
    return f"{mantissa:.1f}".replace("-", "−") + f"×10 的 {sign}{abs(exponent)} 次方"


def _num(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "未得到"
    return f"{value:.{digits}f}".replace("-", "−")


def test_zz_summary(case_record: Any) -> None:
    """Chinese summary and anomaly record of the case from the checks and metrics above."""

    m = case_record.metrics
    checks = case_record.checks
    minimum = m.get("step4_min_T_K") or {}
    maximum = m.get("step4_max_T_K") or {}
    wall = m.get("step5_wall_s") or [None, None]
    node_cn = {"S": "太阳能板", "J": "计算节点", "C": "冷板", "B": "电池", "D": "电源设备", "R": "散热板"}

    def step_ok(k: int) -> bool:
        names = (f"第{k}步", f"test_step{k}_")
        if k == 1:
            names = names + ("前提",)
        selected = [c for c in checks if c["name"].startswith(names)]
        return bool(selected) and all(c["passed"] for c in selected)

    def failed_step(k: int) -> str:
        return f"第{k}步有检查未通过，具体项目见异常记录。"

    excess = m.get("step1_eclipse_reference_excess_s")
    eclipse_text = ("独立的圆轨道圆柱阴影边界全部落在 Orbit 给出的半影段内" if excess == 0
                    else f"独立的圆轨道圆柱阴影边界超出 Orbit 给出的半影段最多 {_num(excess, 3)} s")
    intro = (
        "本用例在 Thermal 目录用项目解释器执行。Power 结果由 sdtwin_sim.power_stand_in 给出，该程序按供电模块设计报告的接口、"
        "式 P1 至 P11 以及 valid 与 event_required 的规定编写，是测试用供电程序。联合运行使用 sdtwin_sim.coupled，"
        "场景为示例 Sat01，轨道为 Orbit 二体传播的 400 km 圆轨道，太阳位置取 sun_position_ephemeris 内置星历，日照取含日食的 "
        "sun_intensity，太阳能板法向与太阳方向夹角为 55°，地球反照与红外由 earth_flux 计算，计算节点请求功率为 60 W，第 10 个日食内从 52898.5 s 至 53798.5 s 的 900 s 内请求线性升至 250 W，随后恢复 60 W。"
    )
    step1 = (
        f"第1步按第 6.3 节的调用顺序运行 24 h，共 {m.get('step1_eclipse_entries', '未得到')} 次进入日食、"
        f"{m.get('step1_eclipse_exits', '未得到')} 次出日食，{eclipse_text}，限值为 1 s。运行完成，保存 "
        f"{m.get('step1_output_samples', '未得到')} 个输出样本与 {m.get('step1_accepted_states', '未得到')} 个已接受状态，"
        f"归档文件 {m.get('step1_archive_bytes', '未得到')} 字节，测试驱动程序在调用联合求解之前写出参数记录。"
        f"{m.get('step1_power_trials', '未得到')} 次 Power 试算与 {m.get('step1_thermal_calls', '未得到')} 次热导数计算都读取"
        "同一时刻的轨道、姿态、表面环境与电池温度，调用顺序违例为 "
        f"{m.get('step1_order_violations', '未得到')} 次，日食、负载启停与电池约束都在相同物理时刻分段处理。"
    ) if step_ok(1) else failed_step(1)
    step2 = (
        f"第2步在独立的故障注入运行中注入一次 valid 为假的试算，运行在 {_num(m.get('step2_invalid_time_s'), 3)} s 报告 power_invalid "
        f"并停止，该结果没有进入热导数，没有执行保护规则，停止前的 {m.get('step2_invalid_prefix_states', '未得到')} 个已接受状态"
        f"与基准运行逐位相同。注入的 event_required 为真的试算被丢弃，约束边界定位在 {_num(m.get('step2_injected_event_s'), 4)} s，"
        f"比窗口起点晚 {_sci_cn(m.get('step2_injected_offset_s'))} s，容限为 0.001 s，Power 按已声明规则断开负载并锁存，"
        "随后在同一时刻重新求功率与温度导数，计算节点功率为 0 W；窗口内的启动指令因 can_supply_request 为假未接通，窗口后的启动指令"
        f"接通负载。电池约束事件发生在请求升至 {_num(m.get('step2_physical_request_W'), 1)} W 时，定位在 "
        f"{_num(m.get('step2_physical_event_s'), 4)} s，区间宽度 {_sci_cn(m.get('step2_physical_bracket_width_s'))} s，"
        "替代程序在区间两端分别给出正常供电与供电不足；日食中的启动指令未接通，出日食后的启动指令接通负载。"
    ) if step_ok(2) else failed_step(2)
    step3 = (
        f"第3步共记录 {m.get('step3_accepted_states', '未得到')} 个已接受状态，其中包含初始状态、分段起始状态与接受的积分结果。{m.get('step3_full_steps', '未得到')} "
        "个完整积分步与按 RK45 权系数由热导数和锂占比导数重建的结果逐位相同，"
        f"{m.get('step3_truncated_steps', '未得到')} 个在限充起止时刻结束的积分步与稠密输出插值结果逐位相同，"
        f"{m.get('step3_event_bridges', '未得到')} 个事件边界处的显式欧拉步与重建结果逐位相同。"
        f"{m.get('step3_rejected_attempts', '未得到')} 次被拒绝的积分步、{m.get('step3_aborted_attempts', '未得到')} 次因事件中止的"
        f"试算均有记录。共有 {m.get('step3_trial_states_not_saved', '未得到')} 个试算状态未写入组件温度，该计数包含拒绝与中止试算。"
        "另有两次事件定位试算与最终接受的边界状态数值重合，数值重合本身不代表未接受状态被写入。"
        f"{m.get('step3_output_samples', '未得到')} 个输出样本取自已接受的解，最大相对差为 "
        f"{_sci_cn(m.get('step3_output_max_rel'))}。归档的 J 温度与 ThermalEvaluation 的 T_J_K 逐位相同，供计算域读取；"
        "每次 Power 试算读取的 T_B_K 与同一试算状态的电池温度逐位相同，首次试算读取 ThermalState 的 "
        f"{_num(m.get('step3_first_T_B_K'))} K，Power 参数校验所用的温度副本与热初值一致，后续温度均从当前试算状态读取。"
    ) if step_ok(3) else failed_step(3)
    cold = "与".join(node_cn[n] for n in (m.get("step4_excursion_nodes") or []) if n in node_cn) or "组件"
    step4 = (
        "第4步 Orbit 的 power_considering_thermal 在四次运行中被调用 0 次，热模块与联合程序源码没有引用该函数；"
        "交给求解器的六个温度导数与 thermal_derivative 的结果逐位相同，太阳能板等每个组件温度只由热模块的积分更新。"
        f"24 h 内太阳能板温度在 {_num(minimum.get('S'), 1)} K 至 {_num(maximum.get('S'), 1)} K 之间，计算节点在 "
        f"{_num(minimum.get('J'), 1)} K 至 {_num(maximum.get('J'), 1)} K 之间，电池在 {_num(minimum.get('B'), 1)} K 至 "
        f"{_num(maximum.get('B'), 1)} K 之间。负载状态只在 Power 事件处改变，{cold}温度低于声明范围时只记录范围警告，"
        "接通期间负载功率等于请求；计算节点 365 K、电池 320 K 起始的 600 s 运行同样只记录范围警告，负载保持 60 W，"
        "热模块没有增加断电或降频规则。"
    ) if step_ok(4) else failed_step(4)
    step5 = (
        f"第5步两次运行比较 {m.get('step5_leaves_compared', '未得到')} 个归档叶项，其中包含数值、字符串与逻辑值，不同项为 "
        f"{m.get('step5_different_leaves', '未得到')} 个，最大差值为 {_sci_cn(m.get('step5_max_abs_difference'))}，"
        "验收限值为 1×10 的 −12 次方；归档包含 run_id、UTC 起点、time_s、组件标识与状态顺序、温度、Power 四功率端口、热流、"
        f"求解设置与参数版本。第一次运行共 {m.get('step5_power_calls', '未得到')} 次 Power 试算，其中替代程序求根 "
        f"{m.get('step5_stand_in_solves', '未得到')} 次，注入结果 {m.get('step5_injected_results', '未得到')} 次，电池响应计算 "
        f"{m.get('step5_battery_evaluations', '未得到')} 次；接受积分步 {m.get('step5_accepted_steps', '未得到')} 个，"
        f"误差控制拒绝 {m.get('step5_rejected_steps', '未得到')} 次，事件中止试算 "
        f"{m.get('step5_event_aborted_attempts', '未得到')} 次，试算拒绝合计 {m.get('step5_rejected_steps_total', '未得到')} 次，"
        f"各项计数与独立统计一致，两次运行分别用时 {_num(wall[0], 1)} s 与 {_num(wall[1], 1)} s。"
    ) if step_ok(5) else failed_step(5)
    failed = [c["name"] for c in checks if not c["passed"]]
    closing = (f"全部 {len(checks)} 项检查通过，满足验收判据。" if not failed
               else f"共 {len(checks)} 项检查，其中 {len(failed)} 项未通过，不满足验收判据。")
    summary = intro + step1 + step2 + step3 + step4 + step5 + closing
    case_record.summary(summary)
    if failed:
        case_record.anomalies("以下检查未通过：" + "；".join(failed) + "。")
    else:
        case_record.anomalies("无")
    assert summary
