"""Data objects, constants and errors of the SDTwin thermal module.

Design report sections 1.4, 5.1 (table 6) and 6.1. Temperatures are in K, time in s, powers in W, thermal
capacitances in J/K and thermal resistances in K/W. Every object checks itself on construction, stores read-only
copies of its arrays and wraps its mappings in :class:`types.MappingProxyType`, so a record cannot change after
construction. Pickling or deep-copying a record rebuilds it through the same checks. The private helpers at the
end are shared by ``parameters``, ``environment`` and ``model``; they let every public function re-check the
objects it receives.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from numbers import Real
from types import MappingProxyType
from typing import Any, Literal, NamedTuple

import numpy as np
from numpy.typing import ArrayLike, NDArray

# Temperature nodes: solar array, computing node, cold plate, battery, power equipment, common radiator.
NODE_ORDER: tuple[str, ...] = ("S", "J", "C", "B", "D", "R")
# Heat-transfer paths in the order of R_K_W and q_W.
PATH_ORDER: tuple[str, ...] = ("SR", "JC", "CR", "BR", "DR")
# End nodes of each path; a positive q_ij flows from the first node to the second (T2).
PATH_NODES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {"SR": ("S", "R"), "JC": ("J", "C"), "CR": ("C", "R"), "BR": ("B", "R"), "DR": ("D", "R")}
)
# Nodes with exposed surfaces, in the order of Q_env_W and Q_emit_W (T4).
EXPOSED_NODES: tuple[str, ...] = ("S", "R")
# Node that each Power port enters in T3 (design 3.2, 5.1).
PORT_NODES: Mapping[str, str] = MappingProxyType({"P_pv_W": "S", "P_load_W": "J", "Q_B_W": "B", "Q_D_W": "D"})
# Instance that supplies each Power port (design 5.1: SolarArray01, Compute01, Battery01 and PDU01).
PORT_INSTANCES: Mapping[str, str] = MappingProxyType(
    {"P_pv_W": "SolarArray01", "P_load_W": "Compute01", "Q_B_W": "Battery01", "Q_D_W": "PDU01"}
)
# Instances each node must hold (design 3.2, 9.3: Controller01 and PDU01 share D); extra instances are allowed.
NODE_INSTANCES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "S": ("SolarArray01",),
        "J": ("Compute01",),
        "C": ("ColdPlate01",),
        "B": ("Battery01",),
        "D": ("Controller01", "PDU01"),
        "R": ("Radiator01",),
    }
)
# Units recorded in ThermalParameters.provenance["units"].
UNITS: Mapping[str, str] = MappingProxyType(
    {"C_J_K": "J/K", "R_K_W": "K/W", "area_m2": "m^2", "temperature": "K"}
)
# Stefan-Boltzmann constant of design table 5, W m^-2 K^-4.
STEFAN_BOLTZMANN_W_M2_K4: float = 5.670374419e-8
# Allowed | |v| - 1 | for body-frame surface normals and attitude quaternions.
UNIT_NORM_TOLERANCE: float = 1e-9
# Index of each node in NODE_ORDER.
NODE_INDEX: Mapping[str, int] = MappingProxyType({node: index for index, node in enumerate(NODE_ORDER)})

_PARAMETER_FIELDS = ("C_J_K", "R_K_W", "surfaces", "instance_map", "provenance")
_PORT_FIELDS = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")
_PROVENANCE_KEYS = (
    "node_order",
    "path_order",
    "units",
    "capacitance",
    "resistance",
    "assets",
    "overrides_applied",
    "temperature_range_K",
)
_OVERRIDE_ENTRY_KEYS = ("target", "field", "old", "new", "source")
_ENVIRONMENT_KEYS = (
    "run_id",
    "time_s",
    "surface_ids",
    "G_W_m2",
    "cos_incidence",
    "albedo_W_m2",
    "infrared_W_m2",
)
# Sanity bound on a supplied incidence cosine: unit normals (1e-9) rotated exactly, plus rounding.
_COS_TOLERANCE = 1e-8


class ThermalError(ValueError):
    """Base class of every validation error raised by the thermal module."""


class ThermalConfigurationError(ThermalError):
    """Assembly or parameter problem: missing, invalid or inconsistent configuration data."""


class ThermalInputError(ThermalError):
    """Runtime input problem: thermal state, surface environment or Power ports."""


class ThermalRangeWarning(UserWarning):
    """A temperature lies outside the declared applicability range of a node's constants (design 5.4)."""


class _Record:
    """Base of the frozen records: equality by value (arrays included), unhashable, rebuilt when pickled."""

    def __eq__(self, other: object) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return all(_same(getattr(self, item.name), getattr(other, item.name)) for item in fields(self))

    __hash__ = None  # type: ignore[assignment]

    def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
        # Pickle and deepcopy go through __post_init__ again; MappingProxyType itself cannot be pickled.
        return (self.__class__, tuple(_unfreeze(getattr(self, item.name)) for item in fields(self)))


@dataclass(frozen=True, eq=False)
class SurfaceRecord(_Record):
    """One exposed surface of node S or R (design 4.4, 5.1); front and back are separate records.

    ``normal_body`` is the outward unit normal in the body frame. ``absorptivity`` applies to direct and
    Earth-reflected sunlight, ``emissivity`` to emission and to Earth infrared (gray-body assumption of T4).
    """

    surface_id: str
    node_id: Literal["S", "R"]
    area_m2: float
    normal_body: ArrayLike
    absorptivity: float
    emissivity: float

    def __post_init__(self) -> None:
        error = ThermalConfigurationError
        surface_id = _identifier(self.surface_id, "SurfaceRecord.surface_id", error)
        record = f"SurfaceRecord {surface_id!r}"
        if not isinstance(self.node_id, str) or self.node_id not in EXPOSED_NODES:
            raise error(
                f"{record}: node_id must be one of {EXPOSED_NODES} (exposed surfaces belong only to S or R), "
                f"got {self.node_id!r}"
            )
        area = _positive_float(self.area_m2, f"{record}: area_m2", error)
        normal = _float_array(self.normal_body, (3,), f"{record}: normal_body", error)
        norm = float(np.linalg.norm(normal))
        if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
            raise error(
                f"{record}: normal_body must be a unit vector (| |n| - 1 | <= {UNIT_NORM_TOLERANCE:g}), "
                f"got |n| = {norm!r}"
            )
        absorptivity = _unit_interval(self.absorptivity, f"{record}: absorptivity", error)
        emissivity = _unit_interval(self.emissivity, f"{record}: emissivity", error)
        object.__setattr__(self, "surface_id", surface_id)
        object.__setattr__(self, "node_id", str(self.node_id))
        object.__setattr__(self, "area_m2", area)
        object.__setattr__(self, "normal_body", normal)
        object.__setattr__(self, "absorptivity", absorptivity)
        object.__setattr__(self, "emissivity", emissivity)


@dataclass(frozen=True, eq=False)
class ThermalParameters(_Record):
    """Fixed capacitances, resistances, surfaces and component assignments of one run (design 5.1, 5.2).

    ``C_J_K`` follows NODE_ORDER in J/K and ``R_K_W`` follows PATH_ORDER in K/W. ``surfaces`` keeps the asset
    surface order. ``instance_map`` is ``{"nodes": {node: (instance_id, ...)}, "ports": {port: instance_id}}``.
    ``provenance`` records the resolved values, units, asset revisions, sources, applied overrides and the
    declared temperature range of every node. The object is read-only after construction.
    """

    C_J_K: ArrayLike
    R_K_W: ArrayLike
    surfaces: tuple[SurfaceRecord, ...]
    instance_map: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        error = ThermalConfigurationError
        capacitance = _ordered_positive(self.C_J_K, NODE_ORDER, "node", "ThermalParameters.C_J_K", error)
        resistance = _ordered_positive(self.R_K_W, PATH_ORDER, "path", "ThermalParameters.R_K_W", error)
        surfaces = _check_surfaces(self.surfaces, "ThermalParameters.surfaces")
        instance_map = _check_instance_map(self.instance_map, "ThermalParameters.instance_map")
        provenance = _check_provenance(self.provenance, instance_map, "ThermalParameters.provenance")
        object.__setattr__(self, "C_J_K", capacitance)
        object.__setattr__(self, "R_K_W", resistance)
        object.__setattr__(self, "surfaces", surfaces)
        object.__setattr__(self, "instance_map", instance_map)
        object.__setattr__(self, "provenance", provenance)
        # Arrays for the calculation functions, used only while the fields are still these exact objects.
        resolved = _resolved(capacitance, resistance, surfaces, provenance["temperature_range_K"])
        snapshot = (tuple(getattr(self, name) for name in _PARAMETER_FIELDS), resolved)
        object.__setattr__(self, "_resolved_snapshot", snapshot)

    def provenance_as_dict(self) -> dict[str, Any]:
        """Return a plain deep copy of ``provenance`` (dicts, lists, numbers, strings) for archiving."""

        return _plain(self.provenance)


@dataclass(frozen=True, eq=False)
class ThermalState(_Record):
    """Temperatures in K of the six nodes in NODE_ORDER at one instant (design 5.1).

    Each state is its own read-only record, so a trial state never overwrites an accepted one.
    """

    run_id: str
    time_s: float
    temperature_K: ArrayLike

    def __post_init__(self) -> None:
        error = ThermalInputError
        run_id = _identifier(self.run_id, "ThermalState.run_id", error)
        time_s = _finite_float(self.time_s, "ThermalState.time_s", error)
        temperature = _ordered_positive(self.temperature_K, NODE_ORDER, "node", "ThermalState.temperature_K", error)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "time_s", time_s)
        object.__setattr__(self, "temperature_K", temperature)


@dataclass(frozen=True, eq=False)
class ThermalInputs(_Record):
    """Surface environment and the four Power ports of one trial at one instant (design 5.1, 5.6).

    ``environment`` is the mapping returned by ``prepare_surface_environment`` and must carry the same
    ``run_id`` and ``time_s``. ``Q_B_W`` keeps its sign; the sign limits of the other three ports are checked
    by ``thermal_derivative``. An invalid Power result, or one that requires an event, carries no ports and
    therefore cannot be turned into ThermalInputs.
    """

    run_id: str
    time_s: float
    environment: Mapping[str, Any]
    P_pv_W: float
    P_load_W: float
    Q_B_W: float
    Q_D_W: float

    def __post_init__(self) -> None:
        error = ThermalInputError
        run_id = _identifier(self.run_id, "ThermalInputs.run_id", error)
        time_s = _finite_float(self.time_s, "ThermalInputs.time_s", error)
        environment = _check_environment(self.environment, "ThermalInputs.environment")
        _same_instant(
            "ThermalInputs.environment", environment["run_id"], environment["time_s"], "ThermalInputs", run_id, time_s
        )
        ports = {name: _port_value(getattr(self, name), f"ThermalInputs.{name}") for name in _PORT_FIELDS}
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "time_s", time_s)
        object.__setattr__(self, "environment", environment)
        for name, value in ports.items():
            object.__setattr__(self, name, value)


@dataclass(frozen=True, eq=False)
class ThermalEvaluation(_Record):
    """Result of ``thermal_derivative`` (design 5.1, 5.6).

    ``dT_dt_K_s`` follows NODE_ORDER, ``q_W`` follows PATH_ORDER, and ``Q_env_W`` and ``Q_emit_W`` follow
    EXPOSED_NODES. ``T_B_K`` and ``T_J_K`` copy temperature_K[3] and temperature_K[1] of the evaluated state
    for recording by component identifier; they are not additional integrated states.
    """

    run_id: str
    time_s: float
    dT_dt_K_s: ArrayLike
    q_W: ArrayLike
    Q_env_W: ArrayLike
    Q_emit_W: ArrayLike
    T_B_K: float
    T_J_K: float

    def __post_init__(self) -> None:
        error = ThermalInputError
        run_id = _identifier(self.run_id, "ThermalEvaluation.run_id", error)
        time_s = _finite_float(self.time_s, "ThermalEvaluation.time_s", error)
        arrays = {}
        for name, labels, kind in (
            ("dT_dt_K_s", NODE_ORDER, "node"),
            ("q_W", PATH_ORDER, "path"),
            ("Q_env_W", EXPOSED_NODES, "exposed node"),
            ("Q_emit_W", EXPOSED_NODES, "exposed node"),
        ):
            where = f"ThermalEvaluation.{name}"
            _require_shape(getattr(self, name), labels, kind, where, error)
            arrays[name] = _float_array(getattr(self, name), (len(labels),), where, error)
        battery = _positive_float(self.T_B_K, "ThermalEvaluation.T_B_K", error)
        compute = _positive_float(self.T_J_K, "ThermalEvaluation.T_J_K", error)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "time_s", time_s)
        for name, value in arrays.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "T_B_K", battery)
        object.__setattr__(self, "T_J_K", compute)


# --------------------------------------------------------------------------- shared private helpers


class _ResolvedParameters(NamedTuple):
    """Checked parameter arrays used by the calculation functions (all read-only)."""

    C_J_K: NDArray[np.float64]
    R_K_W: NDArray[np.float64]
    surface_ids: tuple[str, ...]
    surface_node_index: NDArray[np.intp]
    surface_exposed_index: NDArray[np.intp]
    area_m2: NDArray[np.float64]
    absorptivity: NDArray[np.float64]
    emissivity: NDArray[np.float64]
    normal_body: NDArray[np.float64]
    temperature_range_K: Mapping[str, tuple[float, float]]


def _readonly(array: np.ndarray) -> np.ndarray:
    """Read-only copy of ``array`` on an immutable bytes buffer.

    ``setflags(write=False)`` alone can be undone through a base array that owns its memory; an array whose memory is
    a bytes object cannot be made writeable again, neither directly nor through its base.
    """

    if array.dtype.hasobject:
        array.setflags(write=False)
        return array.view()
    data = np.ascontiguousarray(array)
    return np.frombuffer(data.tobytes(), dtype=data.dtype).reshape(array.shape)


def _identifier(value: Any, where: str, error: type[ThermalError]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{where} must be a non-empty string, got {value!r}")
    return str(value)


def _finite_float(value: Any, where: str, error: type[ThermalError]) -> float:
    if isinstance(value, np.ndarray) and value.ndim == 0:
        value = value.item()
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise error(f"{where} must be a real number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise error(f"{where} must be finite, got {number!r}")
    return number


def _positive_float(value: Any, where: str, error: type[ThermalError]) -> float:
    number = _finite_float(value, where, error)
    if number <= 0.0:
        raise error(f"{where} must be > 0, got {number!r}")
    return number


def _nonnegative_float(value: Any, where: str, error: type[ThermalError]) -> float:
    number = _finite_float(value, where, error)
    if number < 0.0:
        raise error(f"{where} must be >= 0, got {number!r}")
    return number


def _unit_interval(value: Any, where: str, error: type[ThermalError]) -> float:
    number = _finite_float(value, where, error)
    if not 0.0 <= number <= 1.0:
        raise error(f"{where} must lie in [0, 1], got {number!r}")
    return number


def _port_value(value: Any, where: str) -> float:
    if value is None:
        raise ThermalInputError(
            f"{where} is missing (None); an invalid Power result or one that requires an event provides no "
            "ports and must not reach the thermal derivative (design 5.6)"
        )
    return _finite_float(value, where, ThermalInputError)


def _items(value: Any, where: str, error: type[ThermalError]) -> list[Any]:
    if isinstance(value, np.ndarray) and value.ndim == 1:
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    raise error(f"{where} must be a list or tuple, got {type(value).__name__}")


def _id_tuple(value: Any, where: str, error: type[ThermalError]) -> tuple[str, ...]:
    items = _items(value, where, error)
    if not items:
        raise error(f"{where} must list at least one identifier")
    ids = tuple(_identifier(item, f"{where}[{index}]", error) for index, item in enumerate(items))
    repeated = sorted({item for item in ids if ids.count(item) > 1})
    if repeated:
        raise error(f"{where} repeats identifier(s) {repeated}")
    return ids


def _float_array(
    value: Any, shape: tuple[int, ...], where: str, error: type[ThermalError]
) -> NDArray[np.float64]:
    """Return a read-only float copy of ``value`` after checking dtype, shape and finiteness."""

    try:
        raw = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise error(f"{where} must be a numeric array of shape {shape}: {exc}") from None
    if raw.dtype.kind not in "fiu":
        raise error(f"{where} must be a numeric array of shape {shape}, got {value!r}")
    if raw.shape != shape:
        raise error(f"{where} must have shape {shape}, got shape {raw.shape}")
    array = np.array(raw, dtype=float)
    finite = np.isfinite(array).ravel()
    if not finite.all():
        index = int(np.flatnonzero(~finite)[0])
        raise error(f"{where} must contain only finite values, got {array.ravel()[index]!r} at index {index}")
    return _readonly(array)


def _require_shape(value: Any, labels: tuple[str, ...], kind: str, where: str, error: type[ThermalError]) -> None:
    try:
        shape = np.shape(value)
    except (TypeError, ValueError):
        return  # _float_array reports the conversion problem
    if shape != (len(labels),):
        raise error(
            f"{where} must have shape ({len(labels)},) with one value per {kind} in the order {labels}, "
            f"got shape {shape}"
        )


def _ordered_positive(
    value: Any, labels: tuple[str, ...], kind: str, where: str, error: type[ThermalError]
) -> NDArray[np.float64]:
    """Read-only copy of a per-node or per-path array whose entries must be finite and > 0."""

    _require_shape(value, labels, kind, where, error)
    array = _float_array(value, (len(labels),), where, error)
    bad = np.flatnonzero(array <= 0.0)
    if bad.size:
        index = int(bad[0])
        raise error(f"{where}[{index}] ({kind} {labels[index]}) must be > 0, got {array[index]!r}")
    return array


def _temperature_range(value: Any, where: str, error: type[ThermalError]) -> tuple[float, float]:
    items = _items(value, where, error)
    if len(items) != 2:
        raise error(f"{where} must be (min, max) in K, got {value!r}")
    low = _positive_float(items[0], f"{where} min", error)
    high = _positive_float(items[1], f"{where} max", error)
    if not low < high:
        raise error(f"{where} must have min < max, got ({low!r}, {high!r})")
    return (low, high)


def _attribute(record: Any, name: str, where: str, error: type[ThermalError]) -> Any:
    try:
        return getattr(record, name)
    except AttributeError:
        raise error(f"{where} has no field {name!r} ({type(record).__name__} given)") from None


def _same_instant(where_a: str, run_a: str, time_a: float, where_b: str, run_b: str, time_b: float) -> None:
    if run_a != run_b:
        raise ThermalInputError(f"{where_a}.run_id {run_a!r} differs from {where_b}.run_id {run_b!r}")
    if time_a != time_b:
        raise ThermalInputError(f"{where_a}.time_s {time_a!r} differs from {where_b}.time_s {time_b!r}")


def _state_fields(state: Any, where: str) -> tuple[str, float, NDArray[np.float64]]:
    """Re-check a thermal state and return its run_id, time_s and read-only temperatures."""

    error = ThermalInputError
    run_id = _identifier(_attribute(state, "run_id", where, error), f"{where}.run_id", error)
    time_s = _finite_float(_attribute(state, "time_s", where, error), f"{where}.time_s", error)
    temperature = _ordered_positive(
        _attribute(state, "temperature_K", where, error), NODE_ORDER, "node", f"{where}.temperature_K", error
    )
    return run_id, time_s, temperature


def _per_surface(
    values: Any, surface_ids: tuple[str, ...], where: str, error: type[ThermalError], *, nonnegative: bool
) -> NDArray[np.float64]:
    """One finite value per surface, in surface order; None means an unconfigured record."""

    if isinstance(values, np.ndarray) and values.ndim == 1:
        items = values.tolist()
    elif isinstance(values, (list, tuple)):
        items = list(values)
    else:
        raise error(f"{where} must be a sequence with one value per surface {surface_ids}, got {values!r}")
    if len(items) != len(surface_ids):
        raise error(
            f"{where} has {len(items)} value(s) for the {len(surface_ids)} surface(s) {surface_ids}; "
            "every surface needs its own record"
        )
    result = np.empty(len(items))
    for index, (surface_id, item) in enumerate(zip(surface_ids, items, strict=True)):
        label = f"{where} for surface {surface_id!r}"
        if item is None:
            raise error(f"{label} is not configured (None); a missing environment value is not taken as zero")
        number = _finite_float(item, label, error)
        if nonnegative and number < 0.0:
            raise error(f"{label} must be >= 0, got {number!r}")
        result[index] = number
    return _readonly(result)


def _check_environment(environment: Any, where: str) -> Mapping[str, Any]:
    """Check the surface-environment mapping of design 5.3 and return a read-only copy of it."""

    error = ThermalInputError
    if not isinstance(environment, Mapping):
        raise error(
            f"{where} must be the mapping returned by prepare_surface_environment, "
            f"got {type(environment).__name__}"
        )
    missing = [key for key in _ENVIRONMENT_KEYS if key not in environment]
    if missing:
        raise error(f"{where} is missing field(s) {missing}")
    run_id = _identifier(environment["run_id"], f"{where}.run_id", error)
    time_s = _finite_float(environment["time_s"], f"{where}.time_s", error)
    surface_ids = _id_tuple(environment["surface_ids"], f"{where}.surface_ids", error)
    irradiance = _nonnegative_float(environment["G_W_m2"], f"{where}.G_W_m2", error)
    cosine = _per_surface(
        environment["cos_incidence"], surface_ids, f"{where}.cos_incidence", error, nonnegative=False
    )
    outside = np.flatnonzero(np.abs(cosine) > 1.0 + _COS_TOLERANCE)
    if outside.size:
        index = int(outside[0])
        raise error(
            f"{where}.cos_incidence for surface {surface_ids[index]!r} must lie in [-1, 1], got {cosine[index]!r}"
        )
    albedo = _per_surface(environment["albedo_W_m2"], surface_ids, f"{where}.albedo_W_m2", error, nonnegative=True)
    infrared = _per_surface(
        environment["infrared_W_m2"], surface_ids, f"{where}.infrared_W_m2", error, nonnegative=True
    )
    return MappingProxyType(
        {
            "run_id": run_id,
            "time_s": time_s,
            "surface_ids": surface_ids,
            "G_W_m2": irradiance,
            "cos_incidence": cosine,
            "albedo_W_m2": albedo,
            "infrared_W_m2": infrared,
        }
    )


def _check_surfaces(value: Any, where: str) -> tuple[SurfaceRecord, ...]:
    """Re-validate surface records: SurfaceRecord fields, unique ids, and surfaces on both S and R."""

    error = ThermalConfigurationError
    if not isinstance(value, (list, tuple)):
        raise error(f"{where} must be a tuple of SurfaceRecord in asset surface order, got {type(value).__name__}")
    records: list[SurfaceRecord] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        label = f"{where}[{index}]"
        record = SurfaceRecord(
            _attribute(item, "surface_id", label, error),
            _attribute(item, "node_id", label, error),
            _attribute(item, "area_m2", label, error),
            _attribute(item, "normal_body", label, error),
            _attribute(item, "absorptivity", label, error),
            _attribute(item, "emissivity", label, error),
        )
        if record.surface_id in seen:
            raise error(f"{where}: surface_id {record.surface_id!r} appears more than once")
        seen.add(record.surface_id)
        records.append(record)
    for node in EXPOSED_NODES:
        if not any(record.node_id == node for record in records):
            raise error(
                f"{where} has no exposed surface on node {node!r}; T4 needs the surfaces of both S and R "
                "(front and back as separate records)"
            )
    return tuple(records)


def _check_instance_map(value: Any, where: str) -> Mapping[str, Any]:
    """Check node assignments and port instances (design 3.2, 5.1) and return a read-only copy."""

    error = ThermalConfigurationError
    if not isinstance(value, Mapping):
        raise error(f"{where} must be a mapping with 'nodes' and 'ports', got {type(value).__name__}")
    if set(value.keys()) != {"nodes", "ports"}:
        raise error(
            f"{where} must have exactly the keys 'nodes' and 'ports', got {sorted(map(str, value.keys()))}"
        )
    nodes = value["nodes"]
    if not isinstance(nodes, Mapping):
        raise error(f"{where}['nodes'] must map each node to its instance ids, got {type(nodes).__name__}")
    missing = [node for node in NODE_ORDER if node not in nodes]
    if missing:
        raise error(f"{where}['nodes'] is missing node(s) {missing}; every node of {NODE_ORDER} needs its instances")
    unknown = [node for node in nodes if node not in NODE_ORDER]
    if unknown:
        raise error(f"{where}['nodes'] has unknown node(s) {unknown}; the nodes are {NODE_ORDER}")
    owner: dict[str, str] = {}
    frozen_nodes: dict[str, tuple[str, ...]] = {}
    for node in NODE_ORDER:
        instances = _id_tuple(nodes[node], f"{where}['nodes'][{node!r}]", error)
        for instance_id in instances:
            if instance_id in owner:
                raise error(
                    f"{where}: instance {instance_id!r} is assigned to nodes {owner[instance_id]!r} and {node!r}; "
                    "an instance belongs to one node"
                )
            owner[instance_id] = node
        frozen_nodes[node] = instances
    for node, required in NODE_INSTANCES.items():
        for instance_id in required:
            if instance_id not in frozen_nodes[node]:
                placed = owner.get(instance_id)
                found = "is missing" if placed is None else f"is assigned to node {placed!r}"
                raise error(
                    f"{where}['nodes'][{node!r}] must contain instance {instance_id!r}, which {found}; "
                    f"node {node!r} holds {NODE_INSTANCES[node]} (design 3.2, 9.3)"
                )
    ports = value["ports"]
    if not isinstance(ports, Mapping):
        raise error(f"{where}['ports'] must map each Power port to an instance id, got {type(ports).__name__}")
    missing = [port for port in PORT_NODES if port not in ports]
    if missing:
        raise error(f"{where}['ports'] is missing port(s) {missing}")
    unknown = [port for port in ports if port not in PORT_NODES]
    if unknown:
        raise error(f"{where}['ports'] has unknown port(s) {unknown}; the ports are {tuple(PORT_NODES)}")
    frozen_ports: dict[str, str] = {}
    for port, node in PORT_NODES.items():
        instance_id = _identifier(ports[port], f"{where}['ports'][{port!r}]", error)
        if owner.get(instance_id) != node:
            raise error(
                f"{where}['ports'][{port!r}] is instance {instance_id!r} on node {owner.get(instance_id)!r}; "
                f"{port} must come from an instance of node {node!r} (design 5.1)"
            )
        if instance_id != PORT_INSTANCES[port]:
            raise error(
                f"{where}['ports'][{port!r}] is instance {instance_id!r}; {port} must come from "
                f"{PORT_INSTANCES[port]!r} (design 5.1)"
            )
        frozen_ports[port] = instance_id
    return MappingProxyType({"nodes": MappingProxyType(frozen_nodes), "ports": MappingProxyType(frozen_ports)})


def _check_orders_and_units(provenance: Mapping[str, Any], where: str) -> None:
    error = ThermalConfigurationError
    for key, expected in (("node_order", NODE_ORDER), ("path_order", PATH_ORDER)):
        if key not in provenance:
            raise error(f"{where} is missing {key!r}")
        actual = provenance[key]
        try:
            as_tuple = None if isinstance(actual, str) else tuple(actual)
        except TypeError:
            as_tuple = None
        if as_tuple != expected:
            raise error(f"{where}[{key!r}] must be {expected}, got {actual!r}")
    units = provenance.get("units")
    if not isinstance(units, Mapping) or dict(units) != dict(UNITS):
        raise error(f"{where}['units'] must be {dict(UNITS)}, got {units!r}")


def _check_temperature_ranges(value: Any, where: str) -> dict[str, tuple[float, float]]:
    error = ThermalConfigurationError
    if not isinstance(value, Mapping):
        raise error(f"{where} must map each node to its (min, max) range in K, got {type(value).__name__}")
    missing = [node for node in NODE_ORDER if node not in value]
    if missing:
        raise error(f"{where} is missing node(s) {missing}")
    unknown = [node for node in value if node not in NODE_ORDER]
    if unknown:
        raise error(f"{where} has unknown node(s) {unknown}")
    return {node: _temperature_range(value[node], f"{where}[{node!r}]", error) for node in NODE_ORDER}


def _check_keyed(value: Any, expected: tuple[str, ...], kind: str, where: str) -> None:
    error = ThermalConfigurationError
    if not isinstance(value, Mapping):
        raise error(f"{where} must be a mapping with one entry per {kind}, got {type(value).__name__}")
    missing = [key for key in expected if key not in value]
    if missing:
        raise error(f"{where} is missing {kind}(s) {missing}")
    unknown = [key for key in value if key not in expected]
    if unknown:
        raise error(f"{where} has unknown {kind}(s) {unknown}")


def _check_provenance(value: Any, instance_map: Mapping[str, Any], where: str) -> Mapping[str, Any]:
    """Check the provenance mapping of design 5.2 and return a deeply read-only copy."""

    error = ThermalConfigurationError
    if not isinstance(value, Mapping):
        raise error(f"{where} must be a mapping, got {type(value).__name__}")
    missing = [key for key in _PROVENANCE_KEYS if key not in value]
    if missing:
        raise error(f"{where} is missing {missing}")
    _check_orders_and_units(value, where)
    ranges = _check_temperature_ranges(value["temperature_range_K"], f"{where}['temperature_range_K']")
    _check_keyed(value["capacitance"], NODE_ORDER, "node", f"{where}['capacitance']")
    _check_keyed(value["resistance"], PATH_ORDER, "path", f"{where}['resistance']")
    instances = tuple(instance for node in NODE_ORDER for instance in instance_map["nodes"][node])
    _check_keyed(value["assets"], instances, "instance", f"{where}['assets']")
    for instance_id in instances:
        entry = value["assets"][instance_id]
        label = f"{where}['assets'][{instance_id!r}]"
        if not isinstance(entry, Mapping):
            raise error(f"{label} must be a mapping with asset_id and asset_version, got {type(entry).__name__}")
        for key in ("asset_id", "asset_version"):
            if key not in entry:
                raise error(f"{label} is missing {key!r}")
            _identifier(entry[key], f"{label}[{key!r}]", error)
    applied = value["overrides_applied"]
    if not isinstance(applied, (list, tuple)):
        raise error(f"{where}['overrides_applied'] must be a list, got {type(applied).__name__}")
    for index, entry in enumerate(applied):
        label = f"{where}['overrides_applied'][{index}]"
        if not isinstance(entry, Mapping):
            raise error(f"{label} must be a mapping, got {type(entry).__name__}")
        absent = [key for key in _OVERRIDE_ENTRY_KEYS if key not in entry]
        if absent:
            raise error(f"{label} is missing {absent}")
    resolved = dict(value)
    resolved["node_order"] = NODE_ORDER
    resolved["path_order"] = PATH_ORDER
    resolved["units"] = dict(UNITS)
    resolved["temperature_range_K"] = ranges
    return _freeze(resolved)


def _resolved(
    capacitance: NDArray[np.float64],
    resistance: NDArray[np.float64],
    surfaces: tuple[SurfaceRecord, ...],
    ranges: Mapping[str, tuple[float, float]],
) -> _ResolvedParameters:
    """Arrays of checked parameters in the layout the calculation functions use."""

    def readonly(values: list[Any], dtype: Any = float) -> np.ndarray:
        return _readonly(np.array(values, dtype=dtype))

    return _ResolvedParameters(
        C_J_K=capacitance,
        R_K_W=resistance,
        surface_ids=tuple(surface.surface_id for surface in surfaces),
        surface_node_index=readonly([NODE_INDEX[surface.node_id] for surface in surfaces], np.intp),
        surface_exposed_index=readonly([EXPOSED_NODES.index(surface.node_id) for surface in surfaces], np.intp),
        area_m2=readonly([surface.area_m2 for surface in surfaces]),
        absorptivity=readonly([surface.absorptivity for surface in surfaces]),
        emissivity=readonly([surface.emissivity for surface in surfaces]),
        normal_body=readonly([surface.normal_body for surface in surfaces]),
        temperature_range_K=MappingProxyType({node: tuple(ranges[node]) for node in NODE_ORDER}),
    )


def _resolve_parameters(parameters: Any) -> _ResolvedParameters:
    """Checked arrays of the parameter object received by a calculation function.

    A ThermalParameters that still holds the field objects it was constructed with uses the arrays prepared
    by its own construction checks; any other object, or one whose fields were replaced, is checked again.
    """

    if isinstance(parameters, ThermalParameters):
        snapshot = parameters.__dict__.get("_resolved_snapshot")
        if snapshot is not None:
            objects, resolved = snapshot
            if all(getattr(parameters, name) is item for name, item in zip(_PARAMETER_FIELDS, objects, strict=True)):
                return resolved
    error = ThermalConfigurationError
    where = "parameters"
    provenance = _attribute(parameters, "provenance", where, error)
    if not isinstance(provenance, Mapping):
        raise error(f"{where}.provenance must be a mapping, got {type(provenance).__name__}")
    _check_orders_and_units(provenance, f"{where}.provenance")
    if "temperature_range_K" not in provenance:
        raise error(f"{where}.provenance is missing 'temperature_range_K'")
    ranges = _check_temperature_ranges(
        provenance["temperature_range_K"], f"{where}.provenance['temperature_range_K']"
    )
    capacitance = _ordered_positive(
        _attribute(parameters, "C_J_K", where, error), NODE_ORDER, "node", f"{where}.C_J_K", error
    )
    resistance = _ordered_positive(
        _attribute(parameters, "R_K_W", where, error), PATH_ORDER, "path", f"{where}.R_K_W", error
    )
    _check_instance_map(_attribute(parameters, "instance_map", where, error), f"{where}.instance_map")
    surfaces = _check_surfaces(_attribute(parameters, "surfaces", where, error), f"{where}.surfaces")
    return _resolved(capacitance, resistance, surfaces, ranges)


def _range_messages(
    temperature: NDArray[np.float64], ranges: Mapping[str, tuple[float, float]], nodes: tuple[str, ...]
) -> list[str]:
    """Messages for nodes whose temperature lies outside the declared range of their constants."""

    messages = []
    for node in nodes:
        value = float(temperature[NODE_INDEX[node]])
        low, high = ranges[node]
        if not low <= value <= high:
            messages.append(
                f"node {node} temperature {value!r} K is outside the declared range [{low!r}, {high!r}] K "
                "of its constant capacitance, resistance and optical properties (design 5.4)"
            )
    return messages


def _freeze(value: Any) -> Any:
    """Deep read-only copy: mappings become MappingProxyType, lists tuples, arrays read-only copies."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, np.ndarray):
        return _readonly(value.copy())
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _unfreeze(value: Any) -> Any:
    """Replace MappingProxyType by dict at every depth, keeping tuples and arrays (for pickling)."""

    if isinstance(value, Mapping):
        return {key: _unfreeze(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_unfreeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    """Plain data for archives: dicts, lists, Python numbers and strings."""

    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _same(first: Any, second: Any) -> bool:
    if isinstance(first, np.ndarray) or isinstance(second, np.ndarray):
        return (
            isinstance(first, np.ndarray)
            and isinstance(second, np.ndarray)
            and first.shape == second.shape
            and bool(np.array_equal(first, second))
        )
    if isinstance(first, Mapping) or isinstance(second, Mapping):
        return (
            isinstance(first, Mapping)
            and isinstance(second, Mapping)
            and set(first.keys()) == set(second.keys())
            and all(_same(first[key], second[key]) for key in first)
        )
    if isinstance(first, (list, tuple)) or isinstance(second, (list, tuple)):
        return (
            isinstance(first, (list, tuple))
            and isinstance(second, (list, tuple))
            and len(first) == len(second)
            and all(_same(a, b) for a, b in zip(first, second, strict=True))
        )
    return bool(first == second)


__all__ = [
    "EXPOSED_NODES",
    "NODE_INDEX",
    "NODE_INSTANCES",
    "NODE_ORDER",
    "PATH_NODES",
    "PATH_ORDER",
    "PORT_INSTANCES",
    "PORT_NODES",
    "STEFAN_BOLTZMANN_W_M2_K4",
    "UNITS",
    "UNIT_NORM_TOLERANCE",
    "SurfaceRecord",
    "ThermalConfigurationError",
    "ThermalError",
    "ThermalEvaluation",
    "ThermalInputError",
    "ThermalInputs",
    "ThermalParameters",
    "ThermalRangeWarning",
    "ThermalState",
]
