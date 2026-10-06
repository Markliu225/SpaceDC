"""Test case EN-001, surface environment preparation: prepare_surface_environment (thermal design 5.3 and 6.1).

Normative definition: CASES['EN-001'] in Thermal/test_report/build_test_report_cn.py.

Steps of the case
 1. Subtract the satellite position from the Earth-to-Sun vector and normalize it to get the satellite-to-Sun
    direction; compute cos_incidence for every constructed attitude and compare it with an independent calculation.
 2. Compute one full orbit; the returned dictionary holds run_id, time_s, surface_ids, G_W_m2, cos_incidence,
    albedo_W_m2 and infrared_W_m2, the surface arrays have equal lengths and follow the asset surface order.
 3. G_W_m2 is identical to the Orbit output at every point and is not multiplied by an eclipse factor again.
 4. Inject the abnormal inputs one by one and record how each is handled. Besides the inputs listed by the case, the
    general contract of design 6.1 is injected as well: mismatched run_id or time_s, wrong dimensions of position_m,
    sun_position_m and quaternion_xyzw, NaN or infinity in the time, positions, quaternion, G_W_m2, albedo_W_m2 and
    infrared_W_m2, negative irradiances, and an epoch that is naive, missing or not a datetime.
Acceptance: cos_incidence error <= 1e-12; G over the whole orbit identical to the Orbit output point by point; every
abnormal input gives a deterministic error. Errors are aggregated NaN-aware: a missing or NaN value makes the largest
error NaN and fails the threshold (Python's builtin max would silently drop a NaN that is not the first element).

Inputs are real ntu_space_dynamics outputs: a two-body 400 km circular orbit (oe_to_rv and TwoBodyPropagator) over
one full period at 1 s, sun_position_ephemeris with the builtin ephemeris, sun_intensity with include_eclipse=True,
eclipse_fraction, a torque-free EulerDynamics attitude ephemeris and transform_ephemeris for the TEME and ITRS
positions. The reference in tests/data/en_001/en001_reference.py is written by hand (quaternion-to-matrix formula,
Hamilton product, axis permutations, Rodrigues' formula, Sun-nadir closed form, conical shadow) and imports neither
the module under test nor scipy Rotation.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from ntu_space_dynamics import (
    ClassicalElements,
    Ephemeris,
    EulerDynamics,
    OrbitState,
    TwoBodyPropagator,
    eclipse_fraction,
    oe_to_rv,
    sun_intensity,
    sun_position_ephemeris,
    transform_ephemeris,
)
from ntu_space_dynamics.constants import MU_EARTH
from ntu_space_dynamics.time import time_grid

from sdtwin_sim.earth_flux import earth_flux_record
from thermal import (
    ThermalConfigurationError,
    ThermalError,
    ThermalInputError,
    ThermalParameters,
    assemble_thermal_parameters,
    prepare_surface_environment,
)

pytestmark = pytest.mark.case("EN-001")

DATA_DIR = Path(__file__).resolve().parent / "data" / "en_001"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
SPEC = json.loads((DATA_DIR / "en001_inputs.json").read_text(encoding="utf-8"))


def _load_reference():
    spec = importlib.util.spec_from_file_location("en001_reference", DATA_DIR / "en001_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REF = _load_reference()

TOLERANCE = 1e-12  # acceptance: cos_incidence error <= 1e-12
SELF_CHECK_TOLERANCE = 1e-13  # the hand-written reference must agree with itself far below the acceptance limit
RUN_ID = SPEC["run_id"]
EPOCH = datetime.fromisoformat(SPEC["orbit"]["epoch_utc"])
EXPECTED_KEYS = frozenset(
    {"run_id", "time_s", "surface_ids", "G_W_m2", "cos_incidence", "albedo_W_m2", "infrared_W_m2"}
)
SURFACE_SPECS = [surface for component in SPEC["components"] for surface in component.get("surfaces", [])]
ASSET_ORDER = tuple(surface["surface_id"] for surface in SURFACE_SPECS)  # order in which the assets list them
NORMALS = np.array([surface["normal_body"] for surface in SURFACE_SPECS], dtype=float)
AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
CONSTRUCTED = ("identity", "rot_x_90", "rot_y_90", "rot_z_90", "composite_zyx", "random", "random_negated")
ORBIT_PROFILES = ("orbit_euler", "sun_nadir")

# Numbers handed from the step tests to the acceptance test, and Chinese labels of failed checks.
SHARED: dict = {}
FAILED_CN: list[str] = []


# --------------------------------------------------------------------------------------------- helpers


def _check(case_record, failures: list, name: str, label_cn: str, expected, actual, passed) -> bool:
    """Record one check; keep its Chinese label for the anomaly text when it fails."""

    passed = bool(passed)
    case_record.check(name, expected, actual, passed)
    if not passed:
        failures.append(name)
        FAILED_CN.append(label_cn)
    return passed


def _same_bits(a, b) -> bool:
    """Bitwise identity of two floats (also separates 0.0 from -0.0)."""

    try:
        return float(a).hex() == float(b).hex()
    except (TypeError, ValueError):
        return False


def _max_abs_error(values, reference) -> float:
    """Largest |values - reference|, NaN as soon as one value is missing or not a number.

    np.max already propagates NaN; the explicit test keeps the rule visible, so that a missing cos_incidence (the NaN
    rows that _run_profile leaves for a failed call) can never read as a small error.
    """

    difference = np.abs(np.asarray(values, dtype=float) - np.asarray(reference, dtype=float))
    if difference.size == 0 or bool(np.isnan(difference).any()):
        return math.nan
    return float(np.max(difference))


def _worst(errors) -> float:
    """Largest of several errors; NaN when there is none or when one of them is None or NaN.

    Python's builtin max keeps its first element whenever a comparison involves NaN, so it drops a NaN that is not
    first and could let a missing value pass the acceptance threshold. This helper fails on it instead; NaN <= limit
    is false.
    """

    numbers = [math.nan if error is None else float(error) for error in errors]
    if not numbers or any(math.isnan(number) for number in numbers):
        return math.nan
    return max(numbers)


def _facing_away(values, reference) -> dict:
    """Module values at the surfaces facing away from the Sun, i.e. where the reference is below -TOLERANCE.

    Returns their count, how many of them are not negative (a NaN counts as not negative) and the smallest of them
    (NaN when none is a number).
    """

    values = np.asarray(values, dtype=float)
    mask = np.asarray(reference, dtype=float) < -TOLERANCE
    picked = values[mask]
    numbers = picked[~np.isnan(picked)]
    return {"count": int(mask.sum()), "bad": int(np.sum(~(picked < 0.0))),
            "min": float(np.min(numbers)) if numbers.size else math.nan}


def _merge_facing_away(groups) -> dict:
    groups = list(groups)
    minima = [group["min"] for group in groups if not math.isnan(group["min"])]
    return {"count": sum(group["count"] for group in groups), "bad": sum(group["bad"] for group in groups),
            "min": min(minima) if minima else math.nan}


def _metric_number(value):
    """Number for the evidence file; NaN or infinity is written as text so that the JSON stays standard."""

    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else str(value)


def _range_text(values, digits: int = 3) -> str:
    return f"{min(values):.{digits}f} to {max(values):.{digits}f}" if len(values) else "none"


def _synthetic_flux(run_id: str, time_s: float, order=ASSET_ORDER) -> dict:
    albedo = SPEC["synthetic_earth_flux"]["albedo_W_m2"]
    infrared = SPEC["synthetic_earth_flux"]["infrared_W_m2"]
    return {
        "run_id": run_id,
        "time_s": float(time_s),
        "surface_ids": tuple(order),
        "albedo_W_m2": [albedo[s] for s in order],
        "infrared_W_m2": [infrared[s] for s in order],
    }


def _orbit_input(time_s, position, sun_position, quaternion, g, *, run_id=RUN_ID, frame="GCRS") -> dict:
    return {
        "run_id": run_id,
        "time_s": float(time_s),
        "epoch": EPOCH,
        "position_m": np.array(position, dtype=float),
        "sun_position_m": np.array(sun_position, dtype=float),
        "frame": frame,
        "quaternion_xyzw": np.array(quaternion, dtype=float),
        "G_W_m2": g,
    }


def _constructed_attitudes() -> dict[str, np.ndarray]:
    """Identity, 90 deg about each axis, a composite of three rotations, a random unit quaternion and its negative."""

    spec = SPEC["constructed_attitudes"]
    out = {"identity": np.array(spec["identity"]["quaternion_xyzw"], dtype=float)}
    for name in ("rot_x_90", "rot_y_90", "rot_z_90"):
        out[name] = REF.axis_angle_quat(spec[name]["axis"], math.radians(spec[name]["angle_deg"]))
    q = np.array([0.0, 0.0, 0.0, 1.0])
    for axis, degrees in spec["composite_zyx"]["sequence"]:
        q = REF.quat_multiply(q, REF.axis_angle_quat(AXES[axis], math.radians(degrees)))
    out["composite_zyx"] = REF.unit(q)
    rng = np.random.default_rng(spec["random"]["seed"])
    out["random"] = REF.unit(rng.normal(size=4))
    out["random_negated"] = -out["random"]
    return out


def _composite_matrix() -> np.ndarray:
    matrix = np.eye(3)
    for axis, degrees in SPEC["constructed_attitudes"]["composite_zyx"]["sequence"]:
        matrix = matrix @ REF.elementary_matrix(axis, math.radians(degrees))
    return matrix


def _alternative_rotated_normals(name: str, q) -> tuple[str, np.ndarray]:
    """Second independent route to the rotated normals: hand matrices, elementary products or Rodrigues."""

    spec = SPEC["constructed_attitudes"][name]
    if "hand_matrix" in spec:
        return "hand matrix", NORMALS @ np.array(spec["hand_matrix"], dtype=float).T
    if "sequence" in spec:
        return "Rz*Ry*Rx", NORMALS @ _composite_matrix().T
    return "Rodrigues", REF.rodrigues_rotate(q, NORMALS)


def _surface_records_from_spec() -> list:
    """Surface records for the earth_flux provider, taken from the case data and not from the module output."""

    return [SimpleNamespace(surface_id=s["surface_id"], normal_body=list(s["normal_body"])) for s in SURFACE_SPECS]


MINUS = "−"  # U+2212 MINUS SIGN, required for negative numbers in the Chinese text
LIMIT_CN = f"1×10^{{{MINUS}12}}"  # the acceptance limit 1e-12 as the report writes it
UNIT_IRRADIANCE_CN = "W/m^{2}"  # rendered as a superscript by the report builder, no Unicode superscript character


def _sci_cn(value: float) -> str:
    """Power of ten for the Chinese summary, e.g. 7.8×10^{−16}.

    The report builder renders ^{...} as a superscript; a negative exponent or mantissa is written with U+2212.
    Unicode superscript characters are not used.
    """

    value = float(value)
    if value == 0.0:
        return "0"
    if not math.isfinite(value):
        return "非有限值"
    exponent = math.floor(math.log10(abs(value)))
    mantissa = value / 10.0**exponent
    if abs(round(mantissa, 1)) >= 10.0:
        mantissa /= 10.0
        exponent += 1
    return f"{mantissa:.1f}×10^{{{exponent}}}".replace("-", MINUS)


def _num_cn(value: float, digits: int) -> str:
    return f"{float(value):.{digits}f}".replace("-", "−")


def _same_mapping(a, b) -> bool:
    if set(a) != set(b):
        return False
    for key in a:
        x, y = a[key], b[key]
        if isinstance(x, np.ndarray) or isinstance(y, np.ndarray):
            if not (isinstance(x, np.ndarray) and isinstance(y, np.ndarray) and np.array_equal(x, y)):
                return False
        elif isinstance(x, (list, tuple)) or isinstance(y, (list, tuple)):
            if list(x) != list(y):
                return False
        elif x != y:
            return False
    return True


# --------------------------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def params() -> ThermalParameters:
    return assemble_thermal_parameters(copy.deepcopy(SPEC["components"]), copy.deepcopy(SPEC["connections"]), None)


@pytest.fixture(scope="module")
def orbit():
    """One full revolution of Orbit outputs at 1 s: position, Sun vector, G, eclipse fraction and attitudes."""

    o = SPEC["orbit"]
    a = o["earth_radius_m"] + o["altitude_m"]
    period = 2.0 * math.pi * math.sqrt(a**3 / MU_EARTH)
    elements = ClassicalElements.from_degrees(
        a, o["eccentricity"], o["inclination_deg"], o["raan_deg"], o["argument_of_periapsis_deg"],
        o["true_anomaly_deg"], epoch=EPOCH,
    )
    r0, v0 = oe_to_rv(elements)
    times = time_grid(EPOCH, EPOCH + timedelta(seconds=period), o["step_s"])
    ephemeris = TwoBodyPropagator().propagate(OrbitState(EPOCH, r0, v0, "GCRS"), times)
    time_s = ephemeris.elapsed_seconds
    positions = ephemeris.positions_m
    sun = np.array([sun_position_ephemeris(t, ephemeris=o["sun_ephemeris"]) for t in ephemeris.times])
    g_orbit = [sun_intensity(r, s, include_eclipse=True) for r, s in zip(positions, sun)]
    g_free = [sun_intensity(r, s, include_eclipse=False) for r, s in zip(positions, sun)]
    fraction = np.array([eclipse_fraction(r, s) for r, s in zip(positions, sun)])
    shadow = np.array(
        [REF.conical_shadow(r, s, o["earth_radius_m"], o["sun_radius_m"]) for r, s in zip(positions, sun)]
    )
    euler = SPEC["euler_attitude"]
    attitude = EulerDynamics(inertia_kg_m2=euler["inertia_kg_m2"]).propagate(
        euler["initial_quaternion_xyzw"], euler["initial_rate_rad_s"], time_s
    )
    sun_nadir_q = np.array([REF.matrix_to_quat(REF.sun_nadir_axes(r, s)) for r, s in zip(positions, sun)])
    s_hat = np.array([REF.sun_direction(r, s) for r, s in zip(positions, sun)])
    return SimpleNamespace(
        a=a, period=period, ephemeris=ephemeris, times=ephemeris.times, time_s=time_s, r=positions,
        v=ephemeris.velocities_m_s, sun=sun, g=g_orbit, g_free=g_free, fraction=fraction, shadow=shadow,
        attitude=attitude, sun_nadir_q=sun_nadir_q, s_hat=s_hat,
    )


def _run_profile(orbit, params, quaternion_at, flux_at) -> SimpleNamespace:
    """Call prepare_surface_environment at every orbit point and collect the outputs and per-call checks."""

    n = len(orbit.time_s)
    cos = np.full((n, len(ASSET_ORDER)), np.nan)
    g_out: list = [None] * n
    quaternions = np.empty((n, 4))
    stats = {"calls": 0, "errors": [], "keys_bad": 0, "run_time_bad": 0, "ids_bad": 0, "length_bad": 0,
             "flux_bad": 0}
    for k in range(n):
        t = float(orbit.time_s[k])
        q = np.array(quaternion_at(k), dtype=float)
        quaternions[k] = q
        flux = flux_at(k, t, q)
        orbit_input = _orbit_input(t, orbit.r[k], orbit.sun[k], q, orbit.g[k])
        stats["calls"] += 1
        try:
            env = prepare_surface_environment(orbit_input, flux, params)
        except Exception as exc:  # noqa: BLE001 - recorded as a failed call, the orbit run continues
            stats["errors"].append(f"t={t}: {type(exc).__name__}: {exc}")
            continue
        stats["keys_bad"] += set(env) != EXPECTED_KEYS
        stats["run_time_bad"] += not (env.get("run_id") == RUN_ID and _same_bits(env.get("time_s"), t))
        stats["ids_bad"] += tuple(env.get("surface_ids", ())) != ASSET_ORDER
        arrays = [np.asarray(env.get(key), dtype=float) for key in ("cos_incidence", "albedo_W_m2", "infrared_W_m2")]
        stats["length_bad"] += not all(array.shape == (len(ASSET_ORDER),) for array in arrays)
        stats["flux_bad"] += not (
            np.array_equal(arrays[1], np.asarray(flux["albedo_W_m2"], dtype=float))
            and np.array_equal(arrays[2], np.asarray(flux["infrared_W_m2"], dtype=float))
        )
        g_out[k] = env.get("G_W_m2")
        if arrays[0].shape == (len(ASSET_ORDER),):
            cos[k] = arrays[0]
    return SimpleNamespace(cos=cos, g_out=g_out, quaternions=quaternions, **stats)


@pytest.fixture(scope="module")
def runs(orbit, params):
    """Whole-orbit calls: 7 constructed attitudes held fixed, the Orbit EulerDynamics attitude and the Sun-nadir one."""

    profiles = {}

    def synthetic(k, t, q):
        return _synthetic_flux(RUN_ID, t)

    for name, q in _constructed_attitudes().items():
        profiles[name] = _run_profile(orbit, params, lambda k, q=q: q, synthetic)

    model = SPEC["earth_flux_model"]
    records = _surface_records_from_spec()

    def model_flux(k, t, q):
        return earth_flux_record(
            RUN_ID, t, orbit.r[k], orbit.sun[k], q, records, albedo=model["albedo"], olr_W_m2=model["olr_W_m2"],
            solar_constant_W_m2=model["solar_constant_W_m2"], resolution=tuple(model["resolution"]),
        )

    profiles["orbit_euler"] = _run_profile(orbit, params, lambda k: orbit.attitude.quaternions_xyzw[k], model_flux)
    profiles["sun_nadir"] = _run_profile(orbit, params, lambda k: orbit.sun_nadir_q[k], model_flux)
    return profiles


# --------------------------------------------------------------------------------------------- step 1


def test_step1_sun_direction_and_constructed_attitudes(case_record, params, orbit, runs):
    failures: list[str] = []
    attitudes = _constructed_attitudes()
    hand = SPEC["hand_geometry"]

    # Precondition 3: the independent vector and quaternion program is available and self-consistent.
    hand_dev = _worst(
        _max_abs_error(REF.quat_to_matrix(attitudes[n]), np.array(SPEC["constructed_attitudes"][n]["hand_matrix"],
                                                                   dtype=float))
        for n in ("identity", "rot_x_90", "rot_y_90", "rot_z_90")
    )
    composite_dev = _max_abs_error(REF.quat_to_matrix(attitudes["composite_zyx"]), _composite_matrix())
    rodrigues_dev = _max_abs_error(
        REF.rodrigues_rotate(attitudes["random"], NORMALS), NORMALS @ REF.quat_to_matrix(attitudes["random"]).T
    )
    roundtrip_dev = _worst(
        _max_abs_error(REF.quat_to_matrix(q), REF.sun_nadir_axes(r, s))
        for q, r, s in zip(orbit.sun_nadir_q, orbit.r, orbit.sun)
    )
    self_check = _worst([hand_dev, composite_dev, rodrigues_dev, roundtrip_dev])
    _check(
        case_record, failures, "step1 precondition: independent quaternion and vector program self-consistent",
        "独立四元数与向量计算程序的自洽检查",
        f"matrix formula vs hand 90 deg matrices, vs Rz*Ry*Rx, vs Rodrigues, Shepperd round trip over the orbit: "
        f"all <= {SELF_CHECK_TOLERANCE:g}",
        f"hand {hand_dev:.2e}, composite {composite_dev:.2e}, Rodrigues {rodrigues_dev:.2e}, "
        f"Shepperd round trip {roundtrip_dev:.2e}",
        self_check <= SELF_CHECK_TOLERANCE,
    )

    # Hand geometry 1: the direction is normalize(sun_position_m - position_m), here exactly (0, 0.6, 0.8).
    case = hand["difference"]
    expected = np.array([REF.parse_fraction(v) for v in case["expected_cos"]])
    env = prepare_surface_environment(
        _orbit_input(0.0, case["position_m"], case["sun_position_m"], attitudes["identity"], 1361.0,
                     run_id="EN-001-hand"),
        _synthetic_flux("EN-001-hand", 0.0), params,
    )
    got = np.asarray(env["cos_incidence"], dtype=float)
    err_difference = _max_abs_error(got, expected)
    earth_centred = NORMALS @ REF.unit(case["sun_position_m"])
    not_normalized = NORMALS @ (np.array(case["sun_position_m"]) - np.array(case["position_m"]))
    hand_facing = [_facing_away(got, expected)]  # the hand values are exact, so "below -1e-12" means negative
    negatives_ok = hand_facing[0]["count"] > 0 and hand_facing[0]["bad"] == 0
    _check(
        case_record, failures, "step1 satellite-to-Sun direction from sun_position_m - position_m, normalized",
        "卫星指向太阳方向的手算检查",
        "sun - r = (0, 3, 4) m with identity attitude: cos_incidence = (0, 0, 3/7, 4/5, -3/5, -4/5, 3/5) "
        f"within {TOLERANCE:g}; negative values kept",
        f"cos_incidence {np.round(got, 15).tolist()}, max error {err_difference:.2e}; "
        f"an Earth-centred direction would differ by {np.max(np.abs(earth_centred - expected)):.3f}, "
        f"an unnormalized difference by {np.max(np.abs(not_normalized - expected)):.3f}; negatives kept {negatives_ok}",
        err_difference <= TOLERANCE and negatives_ok,
    )

    # Hand geometry 2: Sun along +X, +Y and +Z, identity and 90 deg rotations about each axis (axis permutations).
    hand_errors = {}
    for axis_label, sun_position in hand["sun_axes"]["sun_positions_m"].items():
        for name in ("identity", "rot_x_90", "rot_y_90", "rot_z_90"):
            expected = np.array([REF.parse_fraction(v) for v in hand["sun_axes"]["expected_cos"][axis_label][name]])
            env = prepare_surface_environment(
                _orbit_input(0.0, hand["sun_axes"]["position_m"], sun_position, attitudes[name], 1361.0,
                             run_id="EN-001-hand"),
                _synthetic_flux("EN-001-hand", 0.0), params,
            )
            got = np.asarray(env["cos_incidence"], dtype=float)
            hand_errors[f"Sun {axis_label} {name}"] = _max_abs_error(got, expected)
            hand_facing.append(_facing_away(got, expected))
    err_axes = _worst(hand_errors.values())
    worst_axes = max(hand_errors, key=lambda key: math.inf if math.isnan(hand_errors[key]) else hand_errors[key])
    axes_facing = _merge_facing_away(hand_facing[1:])
    _check(
        case_record, failures, "step1 constructed attitudes vs hand axis permutations, Sun along +X, +Y, +Z",
        "单位四元数与绕三个轴各转 90° 姿态的手算检查",
        f"12 cases, max |cos_incidence - hand value| <= {TOLERANCE:g}; every facing-away surface negative",
        f"max error {err_axes:.2e}, worst {worst_axes}; facing-away values {axes_facing['count']}, "
        f"not negative {axes_facing['bad']}",
        err_axes <= TOLERANCE and axes_facing["count"] > 0 and axes_facing["bad"] == 0,
    )

    # Whole orbit: every constructed attitude at every orbit point against two independent references.
    s_hat = orbit.s_hat
    orbit_errors = {}
    constructed_facing = []
    for name in CONSTRUCTED:
        profile = runs[name]
        q = attitudes[name]
        ref_matrix = s_hat @ (NORMALS @ REF.quat_to_matrix(q).T).T
        alternative_kind, rotated = _alternative_rotated_normals(name, q)
        ref_alternative = s_hat @ rotated.T
        err_matrix = _max_abs_error(profile.cos, ref_matrix)
        err_alternative = _max_abs_error(profile.cos, ref_alternative)
        orbit_errors[name] = _worst([err_matrix, err_alternative])
        constructed_facing.append(_facing_away(profile.cos, ref_matrix))
        first_error = f", first {profile.errors[0][:200]}" if profile.errors else ""
        _check(
            case_record, failures, f"step1 whole orbit cos_incidence, constructed attitude {name}",
            f"构造姿态 {name} 的整圈入射余弦检查",
            f"{len(orbit.time_s)} calls without error; max |module - reference| <= {TOLERANCE:g} against the "
            f"quaternion matrix formula and against the {alternative_kind}",
            f"calls {profile.calls}, errors {len(profile.errors)}{first_error}; max error vs matrix formula "
            f"{err_matrix:.2e}, vs {alternative_kind} {err_alternative:.2e}; q = {np.round(q, 12).tolist()}",
            not profile.errors and err_matrix <= TOLERANCE and err_alternative <= TOLERANCE,
        )
    double_cover = _max_abs_error(runs["random"].cos, runs["random_negated"].cos)
    _check(
        case_record, failures, "step1 q and -q give the same cos_incidence over the whole orbit",
        "四元数与其相反数一致性检查",
        f"max |cos(q) - cos(-q)| <= {TOLERANCE:g}",
        f"max difference {double_cover:.2e}",
        double_cover <= TOLERANCE,
    )
    constructed = _merge_facing_away(constructed_facing)
    _check(
        case_record, failures, "step1 surfaces facing away from the Sun get negative cos_incidence, no clipping",
        "背向太阳表面得到负值的检查",
        "constructed attitudes over the whole orbit: every reference value below -1e-12 is negative in the module "
        "output; at least one such value",
        f"facing-away values over the orbit {constructed['count']}, not negative {constructed['bad']}, smallest of "
        f"these module values {constructed['min']:.15f}",
        constructed["count"] > 0 and constructed["bad"] == 0 and constructed["min"] < 0.0,
    )

    # How far the satellite-to-Sun and Earth-to-Sun directions are apart on this orbit (sensitivity of the check).
    earth_dir = np.array([REF.unit(s) for s in orbit.sun])
    discrimination = _max_abs_error(s_hat @ NORMALS.T, earth_dir @ NORMALS.T)
    hand_all = _merge_facing_away(hand_facing)
    case_record.metric("step1_reference_self_check_max", _metric_number(self_check))
    case_record.metric("step1_hand_difference_max_error", _metric_number(err_difference))
    case_record.metric("step1_hand_axes_max_error", _metric_number(err_axes))
    case_record.metric("step1_orbit_constructed_max_error", {k: _metric_number(v) for k, v in orbit_errors.items()})
    case_record.metric("step1_facing_away_values_hand", hand_all["count"])
    case_record.metric("step1_facing_away_values_constructed_orbit", constructed["count"])
    case_record.metric("step1_min_cos_incidence_hand", _metric_number(hand_all["min"]))
    case_record.metric("step1_min_cos_incidence_constructed_orbit", _metric_number(constructed["min"]))
    case_record.metric("step1_earth_vs_satellite_sun_direction_max_cos_difference", _metric_number(discrimination))
    SHARED["step1_max_error"] = _worst([err_difference, err_axes, *orbit_errors.values(), double_cover])
    SHARED["hand_cases"] = 1 + len(hand_errors)
    SHARED.setdefault("facing_away", {}).update(hand=hand_all, constructed=constructed)
    SHARED["discrimination"] = discrimination
    SHARED["step1_done"] = True
    assert not failures, failures


# --------------------------------------------------------------------------------------------- step 2


def test_step2_full_orbit_fields_order_and_attitudes(case_record, params, orbit, runs):
    failures: list[str] = []
    n = len(orbit.time_s)
    o = SPEC["orbit"]

    # Input: one full revolution of a 400 km circular two-body orbit from Orbit.
    radius = np.linalg.norm(orbit.r, axis=1)
    altitude_dev = float(np.max(np.abs(radius - orbit.a)))
    closure = float(np.linalg.norm(orbit.r[-1] - orbit.r[0]))
    span = float(orbit.time_s[-1])
    max_step = float(np.max(np.diff(orbit.time_s)))
    _check(
        case_record, failures, "step2 input: one full revolution of the 400 km circular Orbit output in GCRS",
        "高度 400 km 圆轨道一整圈输入检查",
        f"Ephemeris frame GCRS; radius = R_E + 400 km within 1 mm; span = period within 1e-5 s; "
        f"steps <= {o['step_s']} s; end position back at the start within 1 m",
        f"frame {orbit.ephemeris.frame}, radius deviation {altitude_dev:.2e} m, "
        f"altitude {float(np.mean(radius)) - o['earth_radius_m']:.3f} m, span {span:.6f} s vs period "
        f"{orbit.period:.6f} s, {n} samples, max step {max_step:.6f} s, closure {closure:.3e} m",
        orbit.ephemeris.frame == "GCRS" and altitude_dev <= 1e-3 and abs(span - orbit.period) <= 1e-5
        and max_step <= o["step_s"] + 1e-9 and closure <= 1.0,
    )
    q_norm_dev = float(np.max(np.abs(np.linalg.norm(orbit.attitude.quaternions_xyzw, axis=1) - 1.0)))
    time_sync = bool(np.array_equal(orbit.attitude.times_s, orbit.time_s))
    _check(
        case_record, failures, "step2 input: Orbit attitude ephemeris on the orbit times with unit quaternions",
        "姿态星历与轨道同一时刻且四元数归一的检查",
        "AttitudeEphemeris.times_s equal to orbit time_s; | |q| - 1 | <= 1e-9",
        f"times equal {time_sync}; max | |q| - 1 | {q_norm_dev:.2e}",
        time_sync and q_norm_dev <= 1e-9,
    )

    profiles = [runs[name] for name in (*CONSTRUCTED, *ORBIT_PROFILES)]
    calls = sum(p.calls for p in profiles)
    errors = [e for p in profiles for e in p.errors]
    totals = {key: sum(getattr(p, key) for p in profiles)
              for key in ("keys_bad", "run_time_bad", "ids_bad", "length_bad", "flux_bad")}
    first_error = f", first {errors[0][:200]}" if errors else ""
    _check(
        case_record, failures, "step2 every whole-orbit call returns a result",
        "整圈逐时刻调用的返回检查",
        f"{9 * n} calls over 9 attitude profiles without error",
        f"calls {calls}, errors {len(errors)}{first_error}",
        calls == 9 * n and not errors,
    )
    field_checks = []
    field_checks.append(_check(
        case_record, failures, "step2 returned dictionary has exactly the seven design fields",
        "返回字典七个字段的检查",
        f"keys {sorted(EXPECTED_KEYS)} in every call",
        f"calls with other keys {totals['keys_bad']} of {calls}",
        calls > 0 and totals["keys_bad"] == 0 and not errors,
    ))
    field_checks.append(_check(
        case_record, failures, "step2 run_id and time_s equal the orbit_input of the same instant",
        "运行标识与时刻的检查",
        "run_id and time_s bitwise equal to the inputs in every call",
        f"calls with a different run_id or time_s {totals['run_time_bad']} of {calls}",
        calls > 0 and totals["run_time_bad"] == 0 and not errors,
    ))
    sorted_order = tuple(sorted(ASSET_ORDER))
    field_checks.append(_check(
        case_record, failures, "step2 surface_ids follow the asset surface order",
        "资产表面顺序的检查",
        f"surface_ids == {list(ASSET_ORDER)}, the asset listing order, which differs from the sorted order "
        f"{list(sorted_order)}",
        f"calls with another order {totals['ids_bad']} of {calls}; ThermalParameters order "
        f"{[s.surface_id for s in params.surfaces]}",
        calls > 0 and totals["ids_bad"] == 0 and not errors and sorted_order != ASSET_ORDER,
    ))
    field_checks.append(_check(
        case_record, failures, "step2 surface arrays have equal lengths",
        "表面数组长度一致的检查",
        f"cos_incidence, albedo_W_m2 and infrared_W_m2 each of length {len(ASSET_ORDER)} = len(surface_ids)",
        f"calls with another length {totals['length_bad']} of {calls}",
        calls > 0 and totals["length_bad"] == 0 and not errors,
    ))
    synth = SPEC["synthetic_earth_flux"]
    sample = prepare_surface_environment(
        _orbit_input(orbit.time_s[0], orbit.r[0], orbit.sun[0], [0.0, 0.0, 0.0, 1.0], orbit.g[0]),
        _synthetic_flux(RUN_ID, orbit.time_s[0]), params,
    )
    by_id = {sid: (float(a), float(i)) for sid, a, i in
             zip(sample["surface_ids"], sample["albedo_W_m2"], sample["infrared_W_m2"])}
    expected_by_id = {sid: (synth["albedo_W_m2"][sid], synth["infrared_W_m2"][sid]) for sid in ASSET_ORDER}
    field_checks.append(_check(
        case_record, failures, "step2 albedo_W_m2 and infrared_W_m2 stay attached to their surface_id",
        "反照与红外输入逐表面对应的检查",
        "a distinct value per surface lands at its own surface_id; every call equals its earth_flux record bitwise",
        f"sample {by_id}; calls not equal to their record {totals['flux_bad']} of {calls}",
        by_id == expected_by_id and totals["flux_bad"] == 0 and calls > 0 and not errors,
    ))

    # Orbit attitudes: EulerDynamics ephemeris vs matrix formula and Rodrigues; the nadir-pointing attitude of
    # en001_reference.sun_nadir_axes vs its closed form. That attitude puts body +Z on the local zenith (RAD_mZ looks
    # at nadir) and body +X, the solar array front normal, on the horizontal projection of the satellite-to-Sun
    # direction, so the front faces the Sun only as far as the nadir constraint allows.
    euler = runs["orbit_euler"]
    ref_matrix = np.array([s @ (NORMALS @ REF.quat_to_matrix(q).T).T for s, q in zip(orbit.s_hat, euler.quaternions)])
    ref_rodrigues = np.array([REF.rodrigues_rotate(q, NORMALS) @ s for s, q in zip(orbit.s_hat, euler.quaternions)])
    err_euler = _worst([_max_abs_error(euler.cos, ref_matrix), _max_abs_error(euler.cos, ref_rodrigues)])
    _check(
        case_record, failures, "step2 whole orbit cos_incidence with the Orbit EulerDynamics attitude",
        "Orbit 刚体姿态整圈入射余弦的检查",
        f"max |module - reference| <= {TOLERANCE:g} against the matrix formula and Rodrigues",
        f"max error {err_euler:.2e}; cos range {float(np.nanmin(euler.cos)):.6f} to {float(np.nanmax(euler.cos)):.6f}",
        err_euler <= TOLERANCE and not euler.errors,
    )
    nadir = runs["sun_nadir"]
    ref_closed = np.array([REF.sun_nadir_expected_cos(r, s, NORMALS) for r, s in zip(orbit.r, orbit.sun)])
    ref_nadir_matrix = np.array(
        [s @ (NORMALS @ REF.quat_to_matrix(q).T).T for s, q in zip(orbit.s_hat, nadir.quaternions)]
    )
    err_nadir = _worst([_max_abs_error(nadir.cos, ref_closed), _max_abs_error(nadir.cos, ref_nadir_matrix)])
    front = ASSET_ORDER.index("SA_front_pX")
    front_range = (float(np.nanmin(nadir.cos[:, front])), float(np.nanmax(nadir.cos[:, front])))
    _check(
        case_record, failures,
        "step2 whole orbit cos_incidence with the nadir-pointing attitude (body +Z to the zenith, +X along the "
        "horizontal projection of the Sun direction), closed form p nx + c nz",
        "对地定向姿态整圈入射余弦的检查",
        f"max |module - closed form| and |module - matrix formula| <= {TOLERANCE:g}",
        f"max error {err_nadir:.2e}; solar array front cos {front_range[0]:.6f} to {front_range[1]:.6f}, "
        f"not facing the Sun except where the Sun lies in the local horizontal plane",
        err_nadir <= TOLERANCE and not nadir.errors,
    )
    orbit_facing = _merge_facing_away([_facing_away(euler.cos, ref_matrix), _facing_away(nadir.cos, ref_closed)])
    _check(
        case_record, failures, "step2 facing-away surfaces negative with the two orbit attitudes",
        "两种轨道姿态下背向太阳表面得到负值的检查",
        "every reference value below -1e-12 is negative in the module output",
        f"facing-away values {orbit_facing['count']}, not negative {orbit_facing['bad']}, smallest of these module "
        f"values {orbit_facing['min']:.15f}",
        orbit_facing["count"] > 0 and orbit_facing["bad"] == 0,
    )

    case_record.metric("orbit_samples", n)
    case_record.metric("orbit_period_s", orbit.period)
    case_record.metric("orbit_altitude_m", float(np.mean(radius)) - o["earth_radius_m"])
    case_record.metric("orbit_radius_deviation_m", altitude_dev)
    case_record.metric("whole_orbit_calls", calls)
    case_record.metric("whole_orbit_call_errors", len(errors))
    case_record.metric("step2_orbit_euler_max_error", _metric_number(err_euler))
    case_record.metric("step2_sun_nadir_max_error", _metric_number(err_nadir))
    case_record.metric("step2_nadir_solar_array_front_cos_range", list(front_range))
    case_record.metric("step2_facing_away_values_orbit_attitudes", orbit_facing["count"])
    case_record.metric("step2_min_cos_incidence_orbit_attitudes", _metric_number(orbit_facing["min"]))
    SHARED["step2_max_error"] = _worst([err_euler, err_nadir])
    SHARED["calls"] = calls
    SHARED["call_errors"] = len(errors)
    SHARED["samples"] = n
    SHARED["period"] = orbit.period
    SHARED["fields_ok"] = all(field_checks)
    SHARED["nadir_front_range"] = front_range
    SHARED.setdefault("facing_away", {})["orbit"] = orbit_facing
    SHARED["step2_done"] = True
    assert not failures, failures


# --------------------------------------------------------------------------------------------- step 3


def test_step3_solar_irradiance_from_orbit_only(case_record, params, orbit, runs):
    failures: list[str] = []
    n = len(orbit.time_s)
    shadow = orbit.shadow
    fraction = orbit.fraction
    umbra = np.flatnonzero(shadow == "umbra")
    penumbra = np.flatnonzero(shadow == "penumbra")
    sunlit = np.flatnonzero(shadow == "sunlit")

    disagree = int(np.sum((shadow == "umbra") != (fraction == 0.0)) + np.sum((shadow == "sunlit") != (fraction == 1.0)))
    umbra_span = (f"{float(orbit.time_s[umbra[0]]):.0f} s to {float(orbit.time_s[umbra[-1]]):.0f} s"
                  if umbra.size else "none")
    _check(
        case_record, failures, "step3 input: the orbit holds an eclipse, independent conical shadow agrees with Orbit",
        "轨道含日食段且独立本影判别与 Orbit 一致的检查",
        "umbra and penumbra samples present; independent class equals the Orbit eclipse_fraction class at every sample",
        f"umbra {umbra.size}, penumbra {penumbra.size}, sunlit {sunlit.size} of {n}; disagreements {disagree}; "
        f"umbra from {umbra_span}",
        umbra.size > 0 and penumbra.size > 0 and disagree == 0,
    )

    profiles = {name: runs[name] for name in (*CONSTRUCTED, *ORBIT_PROFILES)}
    mismatches = 0
    compared = 0
    for profile in profiles.values():
        for k in range(n):
            compared += 1
            mismatches += not _same_bits(profile.g_out[k], orbit.g[k])
    _check(
        case_record, failures, "step3 G_W_m2 bitwise equal to the Orbit sun_intensity output at every point",
        "整圈 G 与 Orbit 输出逐点相同的检查",
        f"{9 * n} returned G_W_m2 values identical to sun_intensity(..., include_eclipse=True)",
        f"compared {compared}, different {mismatches}",
        compared == 9 * n and mismatches == 0,
    )
    umbra_bad = sum(not _same_bits(p.g_out[k], 0.0) for p in profiles.values() for k in umbra)
    umbra_ok = _check(
        case_record, failures, "step3 G_W_m2 is zero in the umbra",
        "日食本影段 G 为零的检查",
        "G_W_m2 = 0 W/m2 at every umbra sample of every profile",
        f"umbra samples {umbra.size}, profiles {len(profiles)}, nonzero {umbra_bad}",
        umbra.size > 0 and umbra_bad == 0,
    )
    pen_bad = 0
    second_factor_gap = []
    for k in penumbra:
        g, g_free, f = orbit.g[k], orbit.g_free[k], float(fraction[k])
        ok = 0.0 < g < g_free and 0.0 < f < 1.0
        for p in profiles.values():
            ok = ok and _same_bits(p.g_out[k], g)
        pen_bad += not ok
        second_factor_gap.append(abs(g - f * g))
    pen_g = [orbit.g[k] for k in penumbra]
    pen_f = [float(fraction[k]) for k in penumbra]
    penumbra_ok = _check(
        case_record, failures, "step3 penumbra: G_W_m2 equals the Orbit value, no second eclipse factor",
        "半影时刻 G 等于 Orbit 输出且未再乘日食系数的检查",
        "0 < G < G without eclipse, returned G equal to Orbit G; a second factor f would change G by (1 - f) G",
        f"penumbra samples {penumbra.size}, G {_range_text(pen_g)} W/m2, eclipse fraction {_range_text(pen_f, 4)}, "
        f"failing samples {pen_bad}, a second factor would shift G by up to "
        f"{max(second_factor_gap) if second_factor_gap else math.nan:.1f} W/m2",
        penumbra.size > 0 and pen_bad == 0,
    )
    sunlit_bad = sum(
        not (_same_bits(p.g_out[k], orbit.g[k]) and _same_bits(orbit.g[k], orbit.g_free[k]) and orbit.g[k] > 0.0)
        for p in profiles.values() for k in sunlit
    )
    sun_g = [orbit.g[k] for k in sunlit]
    _check(
        case_record, failures, "step3 sunlit: G_W_m2 equals the full Orbit irradiance",
        "日照段 G 等于 Orbit 输出的检查",
        "returned G equal to Orbit G, which equals the no-eclipse value and is > 0",
        f"sunlit samples {sunlit.size}, G {_range_text(sun_g)} W/m2, failing {sunlit_bad}",
        sunlit.size > 0 and sunlit_bad == 0,
    )

    # G comes only from Orbit: the function applies no shadow model of its own and computes no G from geometry.
    k_deep = int(umbra[umbra.size // 2]) if umbra.size else 0
    k_sun = int(sunlit[0]) if sunlit.size else 0
    composite = _constructed_attitudes()["composite_zyx"]
    trials = []
    for k, g_in, label in ((k_deep, orbit.g_free[k_deep], "umbra sample with the no-eclipse G"),
                           (k_deep, orbit.g[k_deep], "umbra sample with the Orbit G"),
                           (k_sun, 0.0, "sunlit sample with G = 0")):
        env = prepare_surface_environment(
            _orbit_input(orbit.time_s[k], orbit.r[k], orbit.sun[k], composite, g_in),
            _synthetic_flux(RUN_ID, orbit.time_s[k]), params,
        )
        trials.append((label, float(orbit.time_s[k]), float(g_in), env["G_W_m2"]))
    only_orbit = all(_same_bits(out, g_in) for _, _, g_in, out in trials)
    _check(
        case_record, failures, "step3 G_W_m2 is taken only from orbit_input, eclipse counted once by Orbit",
        "G 只由 Orbit 给出且日食只计入一次的检查",
        "returned G equals the supplied G whatever the geometry: no shadow or eclipse factor inside the function",
        "; ".join(f"{label} t={t:.0f} s: in {g_in:.3f}, out {float(out):.3f} W/m2" for label, t, g_in, out in trials),
        only_orbit,
    )

    case_record.metric("umbra_samples", int(umbra.size))
    case_record.metric("penumbra_samples", int(penumbra.size))
    case_record.metric("sunlit_samples", int(sunlit.size))
    case_record.metric("umbra_start_end_s", [float(orbit.time_s[umbra[0]]), float(orbit.time_s[umbra[-1]])]
                       if umbra.size else None)
    case_record.metric("g_compared", compared)
    case_record.metric("g_mismatches", mismatches)
    case_record.metric("sunlit_G_range_W_m2", [float(min(sun_g)), float(max(sun_g))] if sun_g else None)
    case_record.metric("penumbra_G_range_W_m2", [float(min(pen_g)), float(max(pen_g))] if pen_g else None)
    SHARED["g_compared"] = compared
    SHARED["g_mismatches"] = mismatches
    SHARED["g_expected"] = 9 * n
    SHARED["umbra"] = int(umbra.size)
    SHARED["penumbra"] = int(penumbra.size)
    SHARED["penumbra_g"] = (float(min(pen_g)), float(max(pen_g))) if pen_g else None
    SHARED["umbra_zero_ok"] = umbra_ok
    SHARED["penumbra_ok"] = penumbra_ok
    SHARED["g_free_deep"] = float(orbit.g_free[k_deep])
    SHARED["only_orbit"] = only_orbit
    SHARED["step3_done"] = True
    assert not failures, failures


# --------------------------------------------------------------------------------------------- step 4


def test_step4_abnormal_inputs_and_no_side_effects(case_record, params, orbit):
    failures: list[str] = []
    k0 = 0
    t0 = float(orbit.time_s[k0])
    q0 = _constructed_attitudes()["composite_zyx"]
    base_orbit = _orbit_input(t0, orbit.r[k0], orbit.sun[k0], q0, orbit.g[k0])
    base_flux = _synthetic_flux(RUN_ID, t0)
    base_orbit_copy = copy.deepcopy(base_orbit)
    base_flux_copy = copy.deepcopy(base_flux)
    params_copy = copy.deepcopy(params)

    # Control: the unmodified input is accepted, so every rejection below comes from the injected fault.
    control = prepare_surface_environment(base_orbit, base_flux, params)
    control_cos = np.asarray(control["cos_incidence"], dtype=float)
    reference_cos = NORMALS @ REF.quat_to_matrix(q0).T @ REF.sun_direction(orbit.r[k0], orbit.sun[k0])
    control_err = _max_abs_error(control_cos, reference_cos)
    _check(
        case_record, failures, "step4 control: the unmodified input is accepted",
        "未注入异常输入的对照检查",
        f"no error; cos_incidence within {TOLERANCE:g} of the reference",
        f"keys {sorted(control)}; max error {control_err:.2e}",
        set(control) == EXPECTED_KEYS and control_err <= TOLERANCE,
    )

    # Real frame transformations from Orbit for the TEME and ITRS inputs.
    single = Ephemeris((orbit.times[k0],), orbit.r[k0][None, :], orbit.v[k0][None, :], "GCRS")
    teme = transform_ephemeris(single, "TEME")
    itrs = transform_ephemeris(single, "ITRS")
    teme_back = transform_ephemeris(teme, "GCRS")
    r_teme = teme.positions_m[0]
    r_itrs = itrs.positions_m[0]
    teme_offset = float(np.linalg.norm(r_teme - orbit.r[k0]))
    roundtrip = float(np.linalg.norm(teme_back.positions_m[0] - orbit.r[k0]))

    # Duck-typed parameter objects: the function re-checks the surfaces of any object it receives.
    def surface_namespace(normal_override=None):
        out = []
        for component in SPEC["components"]:
            for spec in component.get("surfaces", []):
                normal = list(spec["normal_body"])
                if normal_override and spec["surface_id"] == normal_override[0]:
                    normal = list(normal_override[1])
                out.append(SimpleNamespace(surface_id=spec["surface_id"], node_id=component["node_id"],
                                           area_m2=spec["area_m2"], normal_body=normal,
                                           absorptivity=spec["absorptivity"], emissivity=spec["emissivity"]))
        return out

    def duck_parameters(surfaces):
        return SimpleNamespace(C_J_K=params.C_J_K, R_K_W=params.R_K_W, surfaces=surfaces,
                               instance_map=params.instance_map, provenance=params.provenance)

    duck_ok = prepare_surface_environment(base_orbit, base_flux, duck_parameters(surface_namespace()))
    duck_dev = _max_abs_error(duck_ok["cos_incidence"], control_cos)
    _check(
        case_record, failures, "step4 control: duck-typed parameters with unit normals are accepted",
        "法向归一参数对象的对照检查",
        f"same cos_incidence as with ThermalParameters within {TOLERANCE:g}",
        f"max difference {duck_dev:.2e}",
        duck_dev <= TOLERANCE,
    )
    back_env = prepare_surface_environment(dict(base_orbit, position_m=teme_back.positions_m[0]), base_flux, params)
    back_dev = _max_abs_error(back_env["cos_incidence"], reference_cos)
    _check(
        case_record, failures, "step4 control: a TEME position transformed back to GCRS by Orbit is accepted",
        "经 Orbit 真实转换回 GCRS 的位置的对照检查",
        f"accepted with frame GCRS; cos_incidence within {TOLERANCE:g} of the original GCRS input",
        f"TEME offset from GCRS {teme_offset:.1f} m, round trip error {roundtrip:.2e} m, cos difference {back_dev:.2e}",
        back_dev <= TOLERANCE,
    )

    def call(orbit_input=None, earth_flux="__base__", parameters=None):
        return prepare_surface_environment(
            base_orbit if orbit_input is None else orbit_input,
            base_flux if isinstance(earth_flux, str) and earth_flux == "__base__" else earth_flux,
            params if parameters is None else parameters,
        )

    synth = SPEC["synthetic_earth_flux"]

    def flux_with(ids, albedo=None, infrared=None, drop=()):
        record = {
            "run_id": RUN_ID, "time_s": t0, "surface_ids": tuple(ids),
            "albedo_W_m2": albedo if albedo is not None else [synth["albedo_W_m2"].get(s, 99.0) for s in ids],
            "infrared_W_m2": infrared if infrared is not None else [synth["infrared_W_m2"].get(s, 199.0) for s in ids],
        }
        for key in drop:
            record.pop(key)
        return record

    ids = list(ASSET_ORDER)
    swapped = [ids[1], ids[0], *ids[2:]]
    unknown = [("RAD_skew_old" if s == "RAD_skew" else s) for s in ids]
    duplicate = [("RAD_pY" if s == "RAD_mY" else s) for s in ids]
    dropped = [s for s in ids if s != "RAD_mZ"]
    albedo_none = [None if s == "RAD_pZ" else synth["albedo_W_m2"][s] for s in ids]
    rounded_q = np.array([0.0, 0.0, 0.7071, 0.7071])

    def with_value(vector, index, value):
        """Copy of a vector with one component replaced (NaN or infinity for design 6.1)."""

        out = np.array(vector, dtype=float)
        out[index] = value
        return out

    def flux_one(key, surface, value):
        """earth_flux record of t0 in asset order with one albedo or infrared value replaced."""

        record = flux_with(ids)
        values = list(record[key])
        values[ids.index(surface)] = value
        record[key] = values
        return record

    negative_g = -float(orbit.g_free[k0])  # the Orbit no-eclipse irradiance with its sign reversed, always < 0
    albedo_column = np.array([synth["albedo_W_m2"][s] for s in ids])[:, None]
    orbit_without_epoch = {key: value for key, value in base_orbit.items() if key != "epoch"}

    def assemble_with_unnormalized_normal():
        components = copy.deepcopy(SPEC["components"])
        for component in components:
            for surface in component.get("surfaces", []):
                if surface["surface_id"] == "RAD_skew":
                    surface["normal_body"] = [2.0, -3.0, 6.0]
        return assemble_thermal_parameters(components, copy.deepcopy(SPEC["connections"]), None)

    abnormal = [
        ("quaternion scaled to |q| = 1.000001", "模长为 1.000001 的四元数",
         lambda: call(dict(base_orbit, quaternion_xyzw=q0 * 1.000001)), ThermalInputError, ["quaternion_xyzw"]),
        (f"quaternion rounded to four decimals, |q| = {float(np.linalg.norm(rounded_q)):.8f}",
         "四位小数取整后未归一的四元数",
         lambda: call(dict(base_orbit, quaternion_xyzw=rounded_q)), ThermalInputError, ["quaternion_xyzw"]),
        ("zero quaternion", "零四元数",
         lambda: call(dict(base_orbit, quaternion_xyzw=np.zeros(4))), ThermalInputError, ["quaternion_xyzw"]),
        ("surface normal |n| = 1.001 in the parameters passed to the function", "参数中未归一的表面法向",
         lambda: call(parameters=duck_parameters(surface_namespace(("RAD_pZ", [0.0, 0.0, 1.001])))),
         ThermalConfigurationError, ["normal_body", "RAD_pZ"]),
        ("unnormalized normal (2, -3, 6) at parameter assembly", "装配时未归一的表面法向",
         assemble_with_unnormalized_normal, ThermalConfigurationError, ["normal_body", "RAD_skew"]),
        ("sun_position_m equal to position_m", "卫星位置与太阳向量之差为零的输入",
         lambda: call(dict(base_orbit, position_m=np.array(orbit.sun[k0]))), ThermalInputError,
         ["sun_position_m", "position_m"]),
        ("untransformed TEME position labelled TEME", "未经转换的 TEME 位置",
         lambda: call(dict(base_orbit, position_m=r_teme, frame="TEME")), ThermalInputError, ["frame", "TEME"]),
        ("ITRS position labelled ITRS", "ITRS 坐标系输入",
         lambda: call(dict(base_orbit, position_m=r_itrs, frame="ITRS")), ThermalInputError, ["frame", "ITRS"]),
        ("frame MOD", "MOD 坐标系输入",
         lambda: call(dict(base_orbit, frame="MOD")), ThermalInputError, ["frame", "MOD"]),
        ("frame J2000", "J2000 坐标系输入",
         lambda: call(dict(base_orbit, frame="J2000")), ThermalInputError, ["frame", "J2000"]),
        ("frame None", "未给出坐标系的输入",
         lambda: call(dict(base_orbit, frame=None)), ThermalInputError, ["frame"]),
        ("earth_flux surface_ids with the first two swapped", "前两项互换的表面编号",
         lambda: call(earth_flux=flux_with(swapped)), ThermalInputError, ["surface_ids"]),
        ("earth_flux surface_ids reversed", "倒序的表面编号",
         lambda: call(earth_flux=flux_with(list(reversed(ids)))), ThermalInputError, ["surface_ids"]),
        ("earth_flux with an unknown surface id in place of RAD_skew", "写错的表面编号",
         lambda: call(earth_flux=flux_with(unknown)), ThermalInputError, ["RAD_skew"]),
        ("earth_flux with RAD_pY twice and no RAD_mY", "重复的表面编号",
         lambda: call(earth_flux=flux_with(duplicate)), ThermalInputError, ["RAD_pY"]),
        ("earth_flux with an extra surface", "资产中不存在的表面编号",
         lambda: call(earth_flux=flux_with([*ids, "RAD_extra"])), ThermalInputError, ["RAD_extra"]),
        ("earth_flux None", "缺少的 earth_flux 记录",
         lambda: call(earth_flux=None), ThermalInputError, ["earth_flux"]),
        ("earth_flux empty mapping", "空的 earth_flux 记录",
         lambda: call(earth_flux={}), ThermalInputError, ["earth_flux"]),
        ("earth_flux without the RAD_mZ record", "缺少一个表面的 earth_flux 记录",
         lambda: call(earth_flux=flux_with(dropped)), ThermalInputError, ["RAD_mZ"]),
        ("earth_flux without albedo_W_m2", "缺少反照字段的 earth_flux 记录",
         lambda: call(earth_flux=flux_with(ids, drop=("albedo_W_m2",))), ThermalInputError, ["albedo_W_m2"]),
        ("earth_flux without infrared_W_m2", "缺少红外字段的 earth_flux 记录",
         lambda: call(earth_flux=flux_with(ids, drop=("infrared_W_m2",))), ThermalInputError, ["infrared_W_m2"]),
        ("earth_flux albedo None for RAD_pZ", "单个表面反照未配置的 earth_flux 记录",
         lambda: call(earth_flux=flux_with(ids, albedo=albedo_none)), ThermalInputError, ["albedo_W_m2", "RAD_pZ"]),
        ("earth_flux infrared with six values for seven surfaces", "红外数组少一个值的 earth_flux 记录",
         lambda: call(earth_flux=flux_with(ids, infrared=[200.0] * 6)), ThermalInputError, ["infrared_W_m2"]),
        ("earth_flux run_id differs", "运行标识不一致的 earth_flux 记录",
         lambda: call(earth_flux=dict(base_flux, run_id="EN-001-other")), ThermalInputError, ["run_id"]),
        ("earth_flux time_s one second later", "时刻不一致的 earth_flux 记录",
         lambda: call(earth_flux=dict(base_flux, time_s=t0 + 1.0)), ThermalInputError, ["time_s"]),
        # Design 6.1, dimensions: functions reject mismatched dimensions.
        ("position_m with six values, position and velocity stacked", "六个分量的卫星位置",
         lambda: call(dict(base_orbit, position_m=np.concatenate([orbit.r[k0], orbit.v[k0]]))), ThermalInputError,
         ["orbit_input.position_m", "got shape (6,)"]),
        ("sun_position_m as a (1, 3) row sliced from the Sun ephemeris", "二维数组形式的地心至太阳向量",
         lambda: call(dict(base_orbit, sun_position_m=orbit.sun[k0:k0 + 1])), ThermalInputError,
         ["orbit_input.sun_position_m", "got shape (1, 3)"]),
        ("quaternion_xyzw with the vector part only", "只有矢量部分的四元数",
         lambda: call(dict(base_orbit, quaternion_xyzw=q0[:3])), ThermalInputError,
         ["orbit_input.quaternion_xyzw", "got shape (3,)"]),
        ("quaternion_xyzw given as its 3x3 rotation matrix", "以旋转矩阵代替的四元数",
         lambda: call(dict(base_orbit, quaternion_xyzw=REF.quat_to_matrix(q0))), ThermalInputError,
         ["orbit_input.quaternion_xyzw", "got shape (3, 3)"]),
        ("earth_flux albedo_W_m2 as a (7, 1) column", "二维数组形式的反照输入",
         lambda: call(earth_flux=flux_with(ids, albedo=albedo_column)), ThermalInputError,
         ["earth_flux.albedo_W_m2", "one value per surface"]),
        # Design 6.1, non-finite inputs: NaN and infinity in the time, positions, quaternion and irradiances.
        ("orbit_input time_s NaN", "时刻为 NaN 的轨道输入",
         lambda: call(dict(base_orbit, time_s=math.nan)), ThermalInputError, ["orbit_input.time_s", "finite"]),
        ("position_m with NaN in y", "含 NaN 的卫星位置",
         lambda: call(dict(base_orbit, position_m=with_value(orbit.r[k0], 1, math.nan))), ThermalInputError,
         ["orbit_input.position_m", "finite", "nan"]),
        ("position_m with +inf in z", "含无穷大的卫星位置",
         lambda: call(dict(base_orbit, position_m=with_value(orbit.r[k0], 2, math.inf))), ThermalInputError,
         ["orbit_input.position_m", "finite", "inf"]),
        ("sun_position_m with NaN in x", "含 NaN 的地心至太阳向量",
         lambda: call(dict(base_orbit, sun_position_m=with_value(orbit.sun[k0], 0, math.nan))), ThermalInputError,
         ["orbit_input.sun_position_m", "finite", "nan"]),
        ("sun_position_m with +inf in y", "含无穷大的地心至太阳向量",
         lambda: call(dict(base_orbit, sun_position_m=with_value(orbit.sun[k0], 1, math.inf))), ThermalInputError,
         ["orbit_input.sun_position_m", "finite", "inf"]),
        ("quaternion_xyzw with NaN in w", "含 NaN 的四元数",
         lambda: call(dict(base_orbit, quaternion_xyzw=with_value(q0, 3, math.nan))), ThermalInputError,
         ["orbit_input.quaternion_xyzw", "finite", "nan"]),
        ("quaternion_xyzw with +inf in x", "含无穷大的四元数",
         lambda: call(dict(base_orbit, quaternion_xyzw=with_value(q0, 0, math.inf))), ThermalInputError,
         ["orbit_input.quaternion_xyzw", "finite", "inf"]),
        ("G_W_m2 NaN", "为 NaN 的 G",
         lambda: call(dict(base_orbit, G_W_m2=math.nan)), ThermalInputError, ["orbit_input.G_W_m2", "finite", "nan"]),
        ("G_W_m2 +inf", "为无穷大的 G",
         lambda: call(dict(base_orbit, G_W_m2=math.inf)), ThermalInputError, ["orbit_input.G_W_m2", "finite", "inf"]),
        ("earth_flux albedo_W_m2 NaN for RAD_mY", "单个表面反照为 NaN 的 earth_flux 记录",
         lambda: call(earth_flux=flux_one("albedo_W_m2", "RAD_mY", math.nan)), ThermalInputError,
         ["earth_flux.albedo_W_m2", "RAD_mY", "finite"]),
        ("earth_flux albedo_W_m2 +inf for SA_front_pX", "单个表面反照为无穷大的 earth_flux 记录",
         lambda: call(earth_flux=flux_one("albedo_W_m2", "SA_front_pX", math.inf)), ThermalInputError,
         ["earth_flux.albedo_W_m2", "SA_front_pX", "finite"]),
        ("earth_flux infrared_W_m2 NaN for RAD_skew", "单个表面红外为 NaN 的 earth_flux 记录",
         lambda: call(earth_flux=flux_one("infrared_W_m2", "RAD_skew", math.nan)), ThermalInputError,
         ["earth_flux.infrared_W_m2", "RAD_skew", "finite"]),
        ("earth_flux infrared_W_m2 +inf for SA_back_mX", "单个表面红外为无穷大的 earth_flux 记录",
         lambda: call(earth_flux=flux_one("infrared_W_m2", "SA_back_mX", math.inf)), ThermalInputError,
         ["earth_flux.infrared_W_m2", "SA_back_mX", "finite"]),
        # Negative irradiances: G_W_m2 >= 0 and earth_flux values >= 0 (design 5.4, irradiances are nonnegative).
        (f"G_W_m2 negative, {negative_g:.3f} W/m2", "为负的 G",
         lambda: call(dict(base_orbit, G_W_m2=negative_g)), ThermalInputError, ["orbit_input.G_W_m2", ">= 0"]),
        ("earth_flux albedo_W_m2 -5 W/m2 for RAD_pY", "单个表面反照为负的 earth_flux 记录",
         lambda: call(earth_flux=flux_one("albedo_W_m2", "RAD_pY", -5.0)), ThermalInputError,
         ["earth_flux.albedo_W_m2", "RAD_pY", ">= 0"]),
        ("earth_flux infrared_W_m2 -5 W/m2 for RAD_pZ", "单个表面红外为负的 earth_flux 记录",
         lambda: call(earth_flux=flux_one("infrared_W_m2", "RAD_pZ", -5.0)), ThermalInputError,
         ["earth_flux.infrared_W_m2", "RAD_pZ", ">= 0"]),
        # Design 5.3 and 6.1: epoch is a timezone-aware UTC datetime shared by all domains.
        ("epoch naive datetime without tzinfo", "缺少时区的 epoch",
         lambda: call(dict(base_orbit, epoch=EPOCH.replace(tzinfo=None))), ThermalInputError,
         ["orbit_input.epoch", "timezone-aware"]),
        ("epoch as the ISO 8601 string", "字符串形式的 epoch",
         lambda: call(dict(base_orbit, epoch=SPEC["orbit"]["epoch_utc"])), ThermalInputError,
         ["orbit_input.epoch", "datetime"]),
        ("epoch as POSIX seconds", "以秒数表示的 epoch",
         lambda: call(dict(base_orbit, epoch=EPOCH.timestamp())), ThermalInputError, ["orbit_input.epoch", "datetime"]),
        ("epoch as numpy datetime64", "numpy datetime64 类型的 epoch",
         lambda: call(dict(base_orbit, epoch=np.datetime64(EPOCH.replace(tzinfo=None)))), ThermalInputError,
         ["orbit_input.epoch", "datetime"]),
        ("orbit_input without the epoch field", "缺少 epoch 字段的轨道输入",
         lambda: call(orbit_without_epoch), ThermalInputError, ["orbit_input", "missing", "epoch"]),
    ]

    rejected = 0
    for name, label_cn, func, expected_class, keywords in abnormal:
        outcomes = []
        for _ in range(2):
            try:
                func()
                outcomes.append(None)
            except Exception as exc:  # noqa: BLE001 - every outcome is recorded
                outcomes.append(exc)
        first, second = outcomes
        deterministic = (
            first is not None and second is not None and type(first) is type(second) and str(first) == str(second)
        )
        named = first is not None and all(keyword in str(first) for keyword in keywords)
        right_class = isinstance(first, expected_class) and isinstance(first, ThermalError)
        passed = deterministic and named and right_class
        rejected += passed
        actual = "no error raised" if first is None else f"{type(first).__name__}: {str(first)[:320]}"
        _check(
            case_record, failures, f"step4 abnormal input rejected: {name}",
            f"{label_cn}被拒绝的检查",
            f"{expected_class.__name__} naming {keywords}, identical on a repeated call",
            f"{actual}; repeated call identical {deterministic}",
            passed,
        )

    # No side effects: inputs and parameters unchanged, no temperature produced, no state argument.
    unchanged = _same_mapping(base_orbit, base_orbit_copy) and _same_mapping(base_flux, base_flux_copy)
    still_writeable = all(base_orbit[key].flags.writeable for key in ("position_m", "sun_position_m", "quaternion_xyzw"))
    params_same = params == params_copy
    signature = list(inspect.signature(prepare_surface_environment).parameters)
    temperature_keys = [key for key in control if "temp" in key.lower() or key.startswith("T_")]
    _check(
        case_record, failures, "step4 the function changes no input and produces no temperature",
        "函数不改变输入与温度的检查",
        "orbit_input, earth_flux and ThermalParameters unchanged after all calls; caller arrays stay writeable; "
        "signature (orbit_input, earth_flux, parameters) without a state; no temperature field returned",
        f"inputs unchanged {unchanged}, arrays writeable {still_writeable}, parameters unchanged {params_same}, "
        f"signature {signature}, temperature fields {temperature_keys}",
        unchanged and still_writeable and params_same and signature == ["orbit_input", "earth_flux", "parameters"]
        and not temperature_keys,
    )

    case_record.metric("abnormal_inputs", len(abnormal))
    case_record.metric("abnormal_rejected_deterministically", int(rejected))
    case_record.metric("teme_position_offset_m", teme_offset)
    case_record.metric("teme_round_trip_error_m", roundtrip)
    SHARED["abnormal"] = len(abnormal)
    SHARED["rejected"] = int(rejected)
    SHARED["side_effect_free"] = bool(unchanged and still_writeable and params_same)
    SHARED["no_temperature"] = bool(
        signature == ["orbit_input", "earth_flux", "parameters"] and not temperature_keys
    )
    SHARED["step4_done"] = True
    assert not failures, failures


# --------------------------------------------------------------------------------------------- acceptance


def _write_series(orbit, runs) -> None:
    """Every 10th orbit sample plus all penumbra samples, for traceability of steps 2 and 3."""

    keep = sorted(set(range(0, len(orbit.time_s), 10)) | set(np.flatnonzero(orbit.shadow == "penumbra").tolist()))
    euler = runs["orbit_euler"]
    nadir = runs["sun_nadir"]
    rows = []
    for k in keep:
        rows.append([float(orbit.time_s[k]), str(orbit.shadow[k]), float(orbit.fraction[k]), float(orbit.g[k]),
                     None if euler.g_out[k] is None else float(euler.g_out[k]),
                     *[float(v) for v in euler.cos[k]], *[float(v) for v in nadir.cos[k]]])
    payload = {
        "case_id": "EN-001",
        "description": "Whole-orbit samples of EN-001: Orbit G with eclipse, G returned by prepare_surface_environment, "
                       "and cos_incidence with the Orbit EulerDynamics attitude and with the nadir-pointing attitude "
                       "whose body +Z is the local zenith and whose +X (solar array front normal) is the horizontal "
                       "projection of the satellite-to-Sun direction (columns cos_sun_nadir_*).",
        "epoch_utc": SPEC["orbit"]["epoch_utc"],
        "surface_ids": list(ASSET_ORDER),
        "columns": ["time_s", "shadow_class_independent", "eclipse_fraction_orbit", "G_orbit_W_m2", "G_env_W_m2",
                    *[f"cos_euler_{s}" for s in ASSET_ORDER], *[f"cos_sun_nadir_{s}" for s in ASSET_ORDER]],
        "rows": rows,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "EN-001_series.json").write_text(json.dumps(payload, indent=0), encoding="utf-8")


def test_acceptance_and_summary(case_record, request):
    failures: list[str] = []
    step_errors = {"step 1": SHARED.get("step1_max_error"), "step 2": SHARED.get("step2_max_error")}
    missing = [step for step, value in step_errors.items() if value is None]
    max_error = _worst(step_errors.values())  # NaN when a step is missing or holds a NaN error
    if missing:
        error_text = f"not available, {' and '.join(missing)} did not finish"
    elif math.isnan(max_error):
        error_text = (f"largest error NaN: at least one call returned no cos_incidence or a value that is not a number "
                      f"(step 1 {step_errors['step 1']}, step 2 {step_errors['step 2']})")
    else:
        error_text = (f"largest error {max_error:.2e} (step 1 {step_errors['step 1']:.2e}, "
                      f"step 2 {step_errors['step 2']:.2e})")
    _check(
        case_record, failures, "acceptance: cos_incidence error <= 1e-12",
        f"cos_incidence 误差不超过 {LIMIT_CN} 的验收检查",
        "largest error of steps 1 and 2 <= 1e-12; a missing or NaN error fails",
        error_text,
        not missing and math.isfinite(max_error) and max_error <= TOLERANCE,
    )
    groups = SHARED.get("facing_away", {})
    complete = all(key in groups for key in ("hand", "constructed", "orbit"))
    total = _merge_facing_away(groups.values()) if groups else None
    _check(
        case_record, failures, "expected result: every surface facing away from the Sun gets a negative cos_incidence",
        "背向太阳表面得到负值的汇总检查",
        "hand cases, constructed attitudes over the whole orbit and the two orbit attitudes together: every reference "
        "value below -1e-12 is negative in the module output",
        "not available, step 1 or 2 did not finish" if not complete else
        f"hand {groups['hand']['count']}, constructed attitudes over the orbit {groups['constructed']['count']}, "
        f"orbit attitudes {groups['orbit']['count']}, total {total['count']}, not negative {total['bad']}, smallest "
        f"of these module values {total['min']:.15f}",
        complete and total["count"] > 0 and total["bad"] == 0,
    )
    compared, mismatches, expected = SHARED.get("g_compared"), SHARED.get("g_mismatches"), SHARED.get("g_expected")
    g_ok = compared is not None and compared == expected and mismatches == 0 and SHARED.get("only_orbit") is True
    _check(
        case_record, failures, "acceptance: G over the whole orbit identical to the Orbit output point by point",
        "整圈 G 与 Orbit 输出逐点相同的验收检查",
        "every returned G_W_m2 bitwise equal to sun_intensity with include_eclipse=True; no own eclipse factor",
        "not available, step 3 did not finish" if compared is None
        else f"compared {compared} of {expected}, different {mismatches}, only from Orbit {SHARED.get('only_orbit')}",
        g_ok,
    )
    abnormal, rejected = SHARED.get("abnormal"), SHARED.get("rejected")
    _check(
        case_record, failures, "acceptance: every abnormal input gives a deterministic error",
        "全部异常输入给出确定报错的验收检查",
        "all injected abnormal inputs rejected with the same error on a repeated call",
        "not available, step 4 did not finish" if abnormal is None else f"rejected {rejected} of {abnormal}",
        abnormal is not None and rejected == abnormal,
    )

    try:
        _write_series(request.getfixturevalue("orbit"), request.getfixturevalue("runs"))
        series_written = True
    except Exception:  # noqa: BLE001 - the summary is written even when the orbit data are unavailable
        series_written = False
    case_record.metric("series_file", "tests/results/EN-001_series.json" if series_written else None)
    case_record.metric("max_cos_incidence_error", None if missing else _metric_number(max_error))
    if total is not None:
        case_record.metric("facing_away_values_total", total["count"])
        case_record.metric("facing_away_values_not_negative", total["bad"])
        case_record.metric("min_cos_incidence_facing_away", _metric_number(total["min"]))

    try:
        summary = _summary_cn(max_error, missing)
    except Exception as exc:  # noqa: BLE001 - a broken summary must appear as a failed check, not as a blank text
        summary = "结果说明生成中断。"
        _check(case_record, failures, "Chinese summary generated from the recorded numbers", "结果说明生成的检查",
               "summary text built", f"{type(exc).__name__}: {exc}", False)
    case_record.summary(summary)
    crash_cn = [f"第 {step} 步测试函数执行中断，该步其余检查未执行" for step in (1, 2, 3, 4)
                if not SHARED.get(f"step{step}_done")]
    items = list(dict.fromkeys([*(f"{label}未通过" for label in FAILED_CN), *crash_cn]))
    case_record.anomalies("无" if not items else "；".join(items) + "。")
    assert not failures, failures


def _summary_cn(max_error: float, missing: list) -> str:
    """Chinese result text; every statement depends on the check that supports it."""

    parts = []
    if SHARED.get("samples") is not None:
        text = (f"在高度 400 km 的二体圆轨道上取一整圈 {_num_cn(SHARED['period'], 1)} s，按 1 s 间隔取样并包含周期末时刻，"
                f"共 {SHARED['samples']} 个时刻，卫星位置、地心至太阳向量与 G 均取自 Orbit 输出")
        if SHARED.get("step3_done"):
            text += f"，其中日食本影 {SHARED['umbra']} 个时刻，半影 {SHARED['penumbra']} 个时刻"
        parts.append(text + "。")
        text = ("对单位四元数、绕三个轴各转 90°、任意组合旋转、随机单位四元数及其相反数共 7 个构造姿态，"
                "以及 Orbit 姿态动力学 EulerDynamics 给出的无外力矩刚体转动姿态和按轨道位置逐时刻构造的对地定向姿态，"
                f"逐时刻调用 prepare_surface_environment 共 {SHARED['calls']} 次")
        if SHARED.get("call_errors"):
            text += f"，其中 {SHARED['call_errors']} 次调用报错"
        if SHARED.get("hand_cases") is not None:
            text += f"，另做 {SHARED['hand_cases']} 组手算几何算例"
        parts.append(text + "。")
        text = ("对地定向姿态的星体 Z 轴指向当地天顶，散热板 RAD_mZ 面朝向地心；太阳能板正面法向即星体 X 轴，"
                "取卫星指向太阳方向在当地水平面上的投影")
        front = SHARED.get("nadir_front_range")
        if front is not None:
            text += f"，整圈中太阳能板正面的入射余弦为 {_num_cn(front[0], 6)} 至 {_num_cn(front[1], 6)}"
        parts.append(text + "。")
    else:
        parts.append("第 2 步测试函数未完成，整圈调用次数与返回字段检查没有结果。")

    if missing:
        parts.append(f"第 1 步或第 2 步未完成，cos_incidence 误差没有全部得到，按不满足不超过 {LIMIT_CN} 的判据处理。")
    elif math.isnan(max_error):
        parts.append(f"部分调用没有返回有效的 cos_incidence，最大误差无法确定，按不满足不超过 {LIMIT_CN} 的判据处理。")
    else:
        verdict = f"满足不超过 {LIMIT_CN} 的判据" if max_error <= TOLERANCE else f"超过 {LIMIT_CN} 的判据"
        parts.append(
            "cos_incidence 与独立编写的四元数旋转矩阵公式、按坐标轴置换的手算结果、三个基本旋转矩阵的乘积、"
            f"罗德里格旋转公式以及对地定向姿态的解析式相比，最大误差 {_sci_cn(max_error)}，{verdict}。"
        )

    groups = SHARED.get("facing_away", {})
    labels = (("hand", "手算算例"), ("constructed", "构造姿态整圈"), ("orbit", "两种轨道姿态整圈"))
    present = [(label, groups[key]) for key, label in labels if key in groups]
    if present:
        total = _merge_facing_away(group for _, group in present)
        breakdown = "、".join(f"{label} {group['count']} 个" for label, group in present)
        if total["count"] > 0 and total["bad"] == 0:
            text = f"背向太阳的表面全部得到负值，{breakdown}，共 {total['count']} 个值，最小为 {_num_cn(total['min'], 6)}"
        else:
            text = f"背向太阳的表面共 {total['count']} 个值，{breakdown}，其中 {total['bad']} 个没有得到负值"
        if len(present) < len(labels):
            text += "，其余姿态的负值检查未完成"
        parts.append(text + "。")

    discrimination = SHARED.get("discrimination")
    if discrimination is not None and math.isfinite(discrimination):
        if discrimination > 1e3 * TOLERANCE:
            parts.append(f"按地心至太阳方向计算的入射余弦与按卫星指向太阳方向计算的结果最多相差 {_sci_cn(discrimination)}，"
                         "远大于判据，说明比较能够区分两种太阳方向。")
        else:
            parts.append(f"按地心至太阳方向计算的入射余弦与按卫星指向太阳方向计算的结果最多相差 {_sci_cn(discrimination)}，"
                         "与判据相比不够大，比较不足以区分两种太阳方向。")

    if SHARED.get("step2_done"):
        if SHARED.get("fields_ok"):
            parts.append("返回字典含 run_id、time_s、surface_ids、G_W_m2、cos_incidence、albedo_W_m2 与 infrared_W_m2 七个字段，"
                         "运行标识与时刻同输入一致，七个表面的数组长度一致，顺序与资产表面顺序相同，反照与红外输入逐表面对应。")
        else:
            parts.append("返回字典的字段、运行标识与时刻、表面顺序、数组长度或反照与红外的逐表面对应没有全部通过检查。")

    if SHARED.get("g_compared") is not None:
        if SHARED["g_mismatches"] == 0 and SHARED["g_compared"] == SHARED.get("g_expected"):
            g_text = f"G_W_m2 在全部 {SHARED['g_compared']} 次调用中均与 sun_intensity 输出逐位相同"
            if SHARED.get("umbra_zero_ok"):
                g_text += f"，本影时刻为 0 {UNIT_IRRADIANCE_CN}"
            penumbra_g = SHARED.get("penumbra_g")
            if penumbra_g and SHARED.get("penumbra_ok"):
                g_text += (f"，半影时刻为 {_num_cn(penumbra_g[0], 1)} 至 {_num_cn(penumbra_g[1], 1)} {UNIT_IRRADIANCE_CN} "
                           "并与 Orbit 输出相同")
            g_text += "，函数没有再乘日食系数；"
        else:
            g_text = f"G_W_m2 在 {SHARED['g_compared']} 次调用中有 {SHARED['g_mismatches']} 次与 sun_intensity 输出不同；"
        if SHARED.get("only_orbit"):
            g_text += (f"本影时刻输入不计日食的 {_num_cn(SHARED['g_free_deep'], 1)} {UNIT_IRRADIANCE_CN} 时函数原样返回，"
                       "日食只由 Orbit 计入一次。")
        else:
            g_text += "直接给定的 G 没有被原样返回。"
        parts.append(g_text)

    if SHARED.get("abnormal") is not None:
        if SHARED["rejected"] == SHARED["abnormal"]:
            reject_text = "这些异常输入全部被拒绝并给出确定的报错，报错指出具体字段，重复调用的报错相同"
        else:
            reject_text = f"其中 {SHARED['abnormal'] - SHARED['rejected']} 项没有给出确定的报错"
        parts.append(
            f"注入 {SHARED['abnormal']} 项异常输入。用例列出的异常输入包括未归一的四元数与法向、卫星位置与太阳向量之差为零、"
            "未经转换的 TEME 位置、不支持的坐标系、表面编号错位与缺少 earth_flux 记录；"
            "按第 6.1 节通用约定另加运行标识或时刻不一致，维数错误的卫星位置、地心至太阳向量、四元数与反照数组，"
            "时刻、卫星位置、地心至太阳向量、四元数、G、反照与红外中的非有限值，"
            "以及缺少时区、缺少字段或不是 datetime 类型的 epoch；另加为负的 G、反照与红外辐照度。"
            + reject_text + "；"
            + ("调用前后输入数据与参数不变" if SHARED.get("side_effect_free") else "调用前后输入数据或参数发生了变化")
            + "，"
            + ("函数不产生温度。" if SHARED.get("no_temperature") else "函数返回了温度字段或带有状态参数。")
        )
    return "".join(parts)
