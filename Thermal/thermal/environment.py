"""Surface environment preparation and surface heat exchange of nodes S and R (design 4.4 T4, 5.3, 5.4).

``prepare_surface_environment`` turns one synchronized Orbit record and the Earth albedo and infrared record
into per-surface inputs: the satellite-to-Sun direction comes from the Earth-to-Sun vector minus the satellite
position, each body-frame normal is rotated into GCRS by the active body-to-GCRS quaternion, and their dot
product is the incidence cosine. The solar irradiance G already includes eclipse and is passed through
unchanged. ``calculate_surface_heat`` evaluates T4 for every surface and sums the results for S and R.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation

from .types import (
    EXPOSED_NODES,
    STEFAN_BOLTZMANN_W_M2_K4,
    UNIT_NORM_TOLERANCE,
    ThermalInputError,
    ThermalRangeWarning,
    _check_environment,
    _finite_float,
    _float_array,
    _id_tuple,
    _identifier,
    _nonnegative_float,
    _per_surface,
    _range_messages,
    _readonly,
    _resolve_parameters,
    _same_instant,
    _state_fields,
)

SUPPORTED_FRAME = "GCRS"

_ORBIT_KEYS = ("run_id", "time_s", "epoch", "position_m", "sun_position_m", "frame", "quaternion_xyzw", "G_W_m2")
_EARTH_FLUX_KEYS = ("run_id", "time_s", "surface_ids", "albedo_W_m2", "infrared_W_m2")


def prepare_surface_environment(
    orbit_input: Mapping[str, Any], earth_flux: Mapping[str, Any], parameters: Any
) -> dict[str, Any]:
    """Prepare the synchronized surface inputs of design 5.3 in asset surface order.

    ``orbit_input`` holds ``run_id``, ``time_s``, ``epoch`` (aware UTC datetime), ``position_m`` and
    ``sun_position_m`` (Earth to Sun) in GCRS, ``frame`` (only ``"GCRS"``), ``quaternion_xyzw`` (active
    body-to-GCRS rotation, SciPy scalar-last order, unit within 1e-9) and ``G_W_m2`` (including eclipse).
    ``earth_flux`` holds ``run_id``, ``time_s``, ``surface_ids``, ``albedo_W_m2`` and ``infrared_W_m2`` for
    exactly the surfaces of ``parameters`` in the same order. ``cos_incidence`` is not clipped here; T4
    clips it. Returns ``run_id``, ``time_s``, ``surface_ids``, ``G_W_m2``, ``cos_incidence``,
    ``albedo_W_m2`` and ``infrared_W_m2`` with read-only arrays.
    """

    resolved = _resolve_parameters(parameters)
    orbit = _read_orbit_input(orbit_input)
    albedo, infrared = _read_earth_flux(earth_flux, orbit["run_id"], orbit["time_s"], resolved.surface_ids)

    satellite_to_sun = orbit["sun_position_m"] - orbit["position_m"]
    distance = float(np.linalg.norm(satellite_to_sun))
    if not distance > 0.0:
        raise ThermalInputError(
            "orbit_input: sun_position_m - position_m is zero, so the satellite-to-Sun direction is undefined"
        )
    sun_direction = satellite_to_sun / distance
    # Scalar-last xyzw; apply() is the active rotation. SciPy's compiled routines need writable copies.
    rotation = Rotation.from_quat(np.array(orbit["quaternion_xyzw"]))
    normals_gcrs = np.atleast_2d(rotation.apply(np.array(resolved.normal_body)))
    cos_incidence = _readonly(normals_gcrs @ sun_direction)
    return {
        "run_id": orbit["run_id"],
        "time_s": orbit["time_s"],
        "surface_ids": resolved.surface_ids,
        "G_W_m2": orbit["G_W_m2"],
        "cos_incidence": cos_incidence,
        "albedo_W_m2": albedo,
        "infrared_W_m2": infrared,
    }


def calculate_surface_heat(state: Any, environment: Mapping[str, Any], parameters: Any) -> dict[str, Any]:
    """Absorbed and emitted powers of S and R from T4 (design 4.4, 5.4).

    Per surface ``g_sun = G max(0, cos)``, absorbed ``A [alpha (g_sun + g_alb) + eps g_IR]`` and emitted
    ``eps sigma A T^4`` with T the temperature of the owning node. Returns ``run_id``, ``time_s``,
    ``Q_env_W`` and ``Q_emit_W`` in EXPOSED_NODES order, ``absorbed_solar_S_W`` (direct sunlight absorbed by
    the S surfaces only) and ``range_warnings``; each S or R temperature outside its declared range is listed
    there and emitted as :class:`ThermalRangeWarning`.
    """

    run_id, time_s, temperature = _state_fields(state, "state")
    resolved = _resolve_parameters(parameters)
    env = _check_environment(environment, "environment")
    _same_instant("environment", env["run_id"], env["time_s"], "state", run_id, time_s)
    if env["surface_ids"] != resolved.surface_ids:
        raise ThermalInputError(
            f"environment.surface_ids {env['surface_ids']} differ from the parameter surfaces "
            f"{resolved.surface_ids} in asset surface order"
        )

    g_sun = env["G_W_m2"] * np.maximum(0.0, env["cos_incidence"])
    absorbed = resolved.area_m2 * (
        resolved.absorptivity * (g_sun + env["albedo_W_m2"]) + resolved.emissivity * env["infrared_W_m2"]
    )
    surface_temperature = temperature[resolved.surface_node_index]
    emitted = resolved.emissivity * STEFAN_BOLTZMANN_W_M2_K4 * resolved.area_m2 * surface_temperature**4
    direct_solar = resolved.area_m2 * resolved.absorptivity * g_sun

    q_env = np.empty(len(EXPOSED_NODES))
    q_emit = np.empty(len(EXPOSED_NODES))
    for index in range(len(EXPOSED_NODES)):
        on_node = resolved.surface_exposed_index == index
        q_env[index] = math.fsum(absorbed[on_node])
        q_emit[index] = math.fsum(emitted[on_node])
    absorbed_solar_s = math.fsum(direct_solar[resolved.surface_exposed_index == EXPOSED_NODES.index("S")])

    messages = _range_messages(temperature, resolved.temperature_range_K, EXPOSED_NODES)
    for message in messages:
        warnings.warn(message, ThermalRangeWarning, stacklevel=2)
    return {
        "run_id": run_id,
        "time_s": time_s,
        "Q_env_W": _readonly(q_env),
        "Q_emit_W": _readonly(q_emit),
        "absorbed_solar_S_W": absorbed_solar_s,
        "range_warnings": tuple(messages),
    }


def _read_orbit_input(orbit_input: Any) -> dict[str, Any]:
    """Check one synchronized Orbit record of design 5.3."""

    error = ThermalInputError
    if not isinstance(orbit_input, Mapping):
        raise error(f"orbit_input must be a mapping, got {type(orbit_input).__name__}")
    missing = [key for key in _ORBIT_KEYS if key not in orbit_input]
    if missing:
        raise error(f"orbit_input is missing field(s) {missing}")
    frame = orbit_input["frame"]
    if not (isinstance(frame, str) and frame == SUPPORTED_FRAME):
        if isinstance(frame, str) and frame.upper() == "TEME":
            raise error(
                "orbit_input.frame is 'TEME'; transform position_m and sun_position_m to GCRS before this call, "
                "because relabelling a TEME vector as GCRS is not a frame transformation"
            )
        raise error(f"orbit_input.frame must be {SUPPORTED_FRAME!r}, got {frame!r}")
    epoch = orbit_input["epoch"]
    if not isinstance(epoch, datetime) or epoch.tzinfo is None or epoch.utcoffset() is None:
        raise error(f"orbit_input.epoch must be a timezone-aware UTC datetime, got {epoch!r}")
    quaternion = _float_array(orbit_input["quaternion_xyzw"], (4,), "orbit_input.quaternion_xyzw", error)
    norm = float(np.linalg.norm(quaternion))
    if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        raise error(
            f"orbit_input.quaternion_xyzw must be a unit quaternion (| |q| - 1 | <= {UNIT_NORM_TOLERANCE:g}), "
            f"got |q| = {norm!r}"
        )
    return {
        "run_id": _identifier(orbit_input["run_id"], "orbit_input.run_id", error),
        "time_s": _finite_float(orbit_input["time_s"], "orbit_input.time_s", error),
        "position_m": _float_array(orbit_input["position_m"], (3,), "orbit_input.position_m", error),
        "sun_position_m": _float_array(orbit_input["sun_position_m"], (3,), "orbit_input.sun_position_m", error),
        "quaternion_xyzw": quaternion,
        "G_W_m2": _nonnegative_float(orbit_input["G_W_m2"], "orbit_input.G_W_m2", error),
    }


def _read_earth_flux(
    earth_flux: Any, run_id: str, time_s: float, surface_ids: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray]:
    """Check the albedo and infrared record against the run, the time and the asset surface order."""

    error = ThermalInputError
    if not isinstance(earth_flux, Mapping):
        raise error(f"earth_flux must be a mapping, got {type(earth_flux).__name__}")
    missing = [key for key in _EARTH_FLUX_KEYS if key not in earth_flux]
    if missing:
        raise error(
            f"earth_flux is missing field(s) {missing}; albedo and infrared are environment data that cannot be "
            "inferred from the solar irradiance (design 5.3)"
        )
    flux_run = _identifier(earth_flux["run_id"], "earth_flux.run_id", error)
    flux_time = _finite_float(earth_flux["time_s"], "earth_flux.time_s", error)
    _same_instant("earth_flux", flux_run, flux_time, "orbit_input", run_id, time_s)
    flux_ids = _id_tuple(earth_flux["surface_ids"], "earth_flux.surface_ids", error)
    if flux_ids != surface_ids:
        absent = [surface for surface in surface_ids if surface not in flux_ids]
        if absent:
            raise error(f"earth_flux has no record for surface(s) {absent} of the asset surfaces {surface_ids}")
        unknown = [surface for surface in flux_ids if surface not in surface_ids]
        if unknown:
            raise error(f"earth_flux lists unknown surface(s) {unknown}; the asset surfaces are {surface_ids}")
        raise error(f"earth_flux.surface_ids {flux_ids} are not in the asset surface order {surface_ids}")
    albedo = _per_surface(earth_flux["albedo_W_m2"], surface_ids, "earth_flux.albedo_W_m2", error, nonnegative=True)
    infrared = _per_surface(
        earth_flux["infrared_W_m2"], surface_ids, "earth_flux.infrared_W_m2", error, nonnegative=True
    )
    return albedo, infrared


__all__ = ["SUPPORTED_FRAME", "calculate_surface_heat", "prepare_surface_environment"]
