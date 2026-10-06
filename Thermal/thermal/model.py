"""Signed path heat flows (T2) and the six temperature derivatives (T3) of design 4.2, 4.3, 5.5 and 5.6.

``calculate_heat_flows`` evaluates each path once. ``thermal_derivative`` checks run, time, component
connections and the Power ports, calls ``calculate_surface_heat`` and ``calculate_heat_flows``, subtracts each
flow at its first node and adds it at its second, and divides the net powers by the capacitances. It updates
no state, repairs no power, decides no load restart and adds no throttling rule.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np

from .environment import calculate_surface_heat
from .types import (
    EXPOSED_NODES,
    NODE_INDEX,
    NODE_ORDER,
    PATH_NODES,
    PATH_ORDER,
    ThermalEvaluation,
    ThermalInputError,
    ThermalRangeWarning,
    _attribute,
    _check_environment,
    _finite_float,
    _identifier,
    _port_value,
    _range_messages,
    _readonly,
    _resolve_parameters,
    _same_instant,
    _state_fields,
)

# Relative tolerance of the check P_pv_W <= absorbed_solar_S_W (rounding only).
PV_RELATIVE_TOLERANCE = 1e-12
_INTERNAL_NODES = tuple(node for node in NODE_ORDER if node not in EXPOSED_NODES)


def calculate_heat_flows(state: Any, parameters: Any) -> dict[str, Any]:
    """Signed heat flow of every path from T2, ``q_ij = (T_i - T_j) / R_ij``, in PATH_ORDER (design 5.5).

    A positive value flows from the first node of the path name to the second. Returns ``run_id``,
    ``time_s`` and the read-only array ``q_W``.
    """

    run_id, time_s, temperature = _state_fields(state, "state")
    resolved = _resolve_parameters(parameters)
    flows = np.empty(len(PATH_ORDER))
    for index, path in enumerate(PATH_ORDER):
        first, second = PATH_NODES[path]
        flows[index] = (temperature[NODE_INDEX[first]] - temperature[NODE_INDEX[second]]) / resolved.R_K_W[index]
    return {"run_id": run_id, "time_s": time_s, "q_W": _readonly(flows)}


def thermal_derivative(state: Any, inputs: Any, parameters: Any) -> ThermalEvaluation:
    """Temperature derivatives of S, J, C, B, D and R from T3 (design 4.3, 5.6).

    ``inputs`` is a :class:`ThermalInputs` built from a valid Power result that needs no event.
    ``P_pv_W``, ``P_load_W`` and ``Q_D_W`` must be >= 0, ``Q_B_W`` may have either sign, and ``P_pv_W`` must not
    exceed ``absorbed_solar_S_W`` of the same evaluation. A node temperature outside its declared range is
    emitted as :class:`ThermalRangeWarning`.
    """

    run_id, time_s, temperature = _state_fields(state, "state")
    error = ThermalInputError
    # ThermalInputs has no Power flags (table 6); an object that carries them must be a usable Power result.
    if not bool(getattr(inputs, "valid", True)) or bool(getattr(inputs, "event_required", False)):
        raise error(
            "inputs come from a Power result that is invalid or requires an event; such a result must not reach "
            "the thermal derivative (design 5.6)"
        )
    inputs_run = _identifier(_attribute(inputs, "run_id", "inputs", error), "inputs.run_id", error)
    inputs_time = _finite_float(_attribute(inputs, "time_s", "inputs", error), "inputs.time_s", error)
    _same_instant("inputs", inputs_run, inputs_time, "state", run_id, time_s)
    environment = _check_environment(_attribute(inputs, "environment", "inputs", error), "inputs.environment")
    _same_instant("inputs.environment", environment["run_id"], environment["time_s"], "state", run_id, time_s)
    ports = {
        name: _port_value(_attribute(inputs, name, "inputs", error), f"inputs.{name}")
        for name in ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")
    }
    for name in ("P_pv_W", "P_load_W", "Q_D_W"):
        if ports[name] < 0.0:
            raise error(
                f"inputs.{name} must be >= 0, got {ports[name]!r}; Thermal does not repair Power results (design 5.6)"
            )
    resolved = _resolve_parameters(parameters)  # node and path orders, port instances on their nodes

    surface = calculate_surface_heat(state, environment, parameters)
    absorbed_solar = surface["absorbed_solar_S_W"]
    if ports["P_pv_W"] > absorbed_solar * (1.0 + PV_RELATIVE_TOLERANCE):
        raise error(
            f"inputs.P_pv_W {ports['P_pv_W']!r} W exceeds absorbed_solar_S_W {absorbed_solar!r} W; the actual "
            "solar electrical output cannot exceed the direct sunlight absorbed by S (design 4.4, 5.6)"
        )
    flows = calculate_heat_flows(state, parameters)

    q = dict(zip(PATH_ORDER, (float(value) for value in flows["q_W"]), strict=True))
    q_env = dict(zip(EXPOSED_NODES, (float(value) for value in surface["Q_env_W"]), strict=True))
    q_emit = dict(zip(EXPOSED_NODES, (float(value) for value in surface["Q_emit_W"]), strict=True))
    net_W = {
        "S": q_env["S"] - ports["P_pv_W"] - q["SR"] - q_emit["S"],
        "J": ports["P_load_W"] - q["JC"],
        "C": q["JC"] - q["CR"],
        "B": ports["Q_B_W"] - q["BR"],
        "D": ports["Q_D_W"] - q["DR"],
        "R": q["SR"] + q["CR"] + q["BR"] + q["DR"] + q_env["R"] - q_emit["R"],
    }
    derivative = np.array([net_W[node] for node in NODE_ORDER]) / resolved.C_J_K

    for message in _range_messages(temperature, resolved.temperature_range_K, _INTERNAL_NODES):
        warnings.warn(message, ThermalRangeWarning, stacklevel=2)
    return ThermalEvaluation(
        run_id=run_id,
        time_s=time_s,
        dT_dt_K_s=derivative,
        q_W=flows["q_W"],
        Q_env_W=surface["Q_env_W"],
        Q_emit_W=surface["Q_emit_W"],
        T_B_K=float(temperature[NODE_INDEX["B"]]),
        T_J_K=float(temperature[NODE_INDEX["J"]]),
    )


__all__ = ["PV_RELATIVE_TOLERANCE", "calculate_heat_flows", "thermal_derivative"]
