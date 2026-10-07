"""SimReady asset and Sat01 scene assembly for the SDTwin thermal module (thermal design 9.3, 9.4, table 9).

An asset definition is a JSON record with ``asset_id``, ``asset_version`` and ``geometry_uri`` (a USD file), its physical
capabilities (``domain``, ``model_id``, ``parameter_set``) and its parameter evidence (``ports``, ``provenance``). A scene
record lists ``instances`` (``instance_id``, ``asset_ref``, ``mounting``, optional ``display_transform``) and the scene
configuration (``parameter_overrides``, ``initial_state``, ``connections``). The fields shared with the Power design
(Power design table 8 and table 9) live in the same records, so Power and Thermal use the same instance identifiers.

Physical sizes come only from USD prim extents times the asset stage ``metersPerUnit``. Instance transforms authored
under ``/World/Sat01/<instance_id>`` are display and placement data: a display scale never changes an area, a volume or
a mass (design 9.4). ``model_id`` is a key into a fixed registry of data records; nothing read from USD or JSON is
executed. Every instance produces its own component record. Design 9.3 asks two instances of one asset for independent
temperatures; the six-node network has one temperature per node and only D is a shared extent (design table 1), so a
scene that would put a second instance on S, J, C, B or R, or two instances of one asset on any node, is rejected.
Each power port must come from an asset whose Power role matches it (design 5.1): P_pv_W solar_array, P_load_W load,
Q_B_W battery, Q_D_W pdu.

Public entry points: :func:`load_asset`, :func:`load_scene`, :func:`assemble_scene`, :func:`compose_stage` and
:func:`display_bbox_size`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.spatial.transform import Rotation

# Orders of thermal design 1.4 and 5.1 (identical to thermal.types; repeated here so that scene loading does not depend
# on the thermal package being importable).
NODE_ORDER: tuple[str, ...] = ("S", "J", "C", "B", "D", "R")
PATH_ORDER: tuple[str, ...] = ("SR", "JC", "CR", "BR", "DR")
PATH_NODES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {"SR": ("S", "R"), "JC": ("J", "C"), "CR": ("C", "R"), "BR": ("B", "R"), "DR": ("D", "R")}
)
EXPOSED_NODES: tuple[str, ...] = ("S", "R")
THERMAL_POWER_PORTS: tuple[str, ...] = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")
# Design 5.1, 1.4 and 4.1: each external power comes from the device with this Power role (Q_D is the distribution
# unit's distribution and wiring loss; the controller's own losses are neglected).
PORT_POWER_ROLES: Mapping[str, str] = MappingProxyType(
    {"P_pv_W": "solar_array", "P_load_W": "load", "Q_B_W": "battery", "Q_D_W": "pdu"}
)
# Design table 1 and 3.2: D (controller, distribution unit and assigned wiring) is the only temperature extent shared by
# several instances in this version; every other node is exactly one instance with its own temperature (design 9.3).
SHARED_TEMPERATURE_NODES: tuple[str, ...] = ("D",)

SAT_ROOT = "/World/Sat01"
FACES: Mapping[str, tuple[int, float]] = MappingProxyType(
    {"+X": (0, 1.0), "-X": (0, -1.0), "+Y": (1, 1.0), "-Y": (1, -1.0), "+Z": (2, 1.0), "-Z": (2, -1.0)}
)
PROVENANCE_STATUSES: tuple[str, ...] = ("illustrative_test_value", "datasheet", "measured", "fitted")
PORT_KINDS: Mapping[str, str] = MappingProxyType(
    {"power_port": "W", "temperature": "K", "electrical": "W", "thermal_interface": "W"}
)
QUATERNION_TOL = 1e-9
RIGID_TOL = 1e-6


class SceneError(ValueError):
    """Invalid SimReady asset, geometry or scene record; the message names the record and the field."""


class UnregisteredModelError(SceneError):
    """A capability names a ``model_id`` that is not in the fixed registry of its domain."""


# --------------------------------------------------------------------------------------------------------------------
# Fixed model registries (design table 9: the model name is a controlled lookup key). Entries are plain data.
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThermalModelSpec:
    """Registry entry of a thermal capability: the node it represents and the Power ports it may supply."""

    model_id: str
    node_id: str
    exposed: bool
    allowed_ports: tuple[str, ...]
    required_ports: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        if self.node_id not in NODE_ORDER:
            raise ValueError(f"thermal model {self.model_id!r}: node_id {self.node_id!r} not in {NODE_ORDER}")
        if self.exposed != (self.node_id in EXPOSED_NODES):
            raise ValueError(f"thermal model {self.model_id!r}: exposed must be true only for nodes {EXPOSED_NODES}")
        unknown = set(self.allowed_ports) - set(THERMAL_POWER_PORTS)
        if unknown or not set(self.required_ports) <= set(self.allowed_ports):
            raise ValueError(f"thermal model {self.model_id!r}: inconsistent port lists")


@dataclass(frozen=True)
class PowerModelSpec:
    """Registry entry of a Power capability: the parameter names and kinds its ``parameter_set`` must carry."""

    model_id: str
    role: str
    parameters: Mapping[str, str]
    description: str

    def __post_init__(self) -> None:
        bad = {k: v for k, v in self.parameters.items() if v not in _POWER_PARAMETER_KINDS}
        if bad:
            raise ValueError(f"power model {self.model_id!r}: unknown parameter kinds {bad}")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


_POWER_PARAMETER_KINDS = ("positive", "efficiency", "positive_int", "text", "surface_ref")

THERMAL_MODEL_REGISTRY: Mapping[str, ThermalModelSpec] = MappingProxyType(
    {
        spec.model_id: spec
        for spec in (
            ThermalModelSpec("sdtwin.thermal.solar_array/1", "S", True, ("P_pv_W",), ("P_pv_W",),
                             "lumped solar array node S with exposed front and back surfaces"),
            ThermalModelSpec("sdtwin.thermal.compute_board/1", "J", False, ("P_load_W",), ("P_load_W",),
                             "whole-board equivalent computing node J"),
            ThermalModelSpec("sdtwin.thermal.cold_plate/1", "C", False, (), (), "lumped cold plate node C"),
            ThermalModelSpec("sdtwin.thermal.battery_pack/1", "B", False, ("Q_B_W",), ("Q_B_W",),
                             "lumped battery pack node B with signed heat from Power"),
            ThermalModelSpec("sdtwin.thermal.power_equipment/1", "D", False, ("Q_D_W",), (),
                             "controller, distribution unit and assigned wiring sharing node D"),
            ThermalModelSpec("sdtwin.thermal.radiator/1", "R", True, (), (),
                             "lumped common radiator node R with exposed surfaces"),
        )
    }
)

POWER_MODEL_REGISTRY: Mapping[str, PowerModelSpec] = MappingProxyType(
    {
        spec.model_id: spec
        for spec in (
            PowerModelSpec("sdtwin.power.solar_array.fixed_efficiency/1", "solar_array",
                           {"cell_area_m2": "positive", "efficiency": "efficiency", "surface_id": "surface_ref"},
                           "P2 fixed maximum power point efficiency on the effective cell area"),
            PowerModelSpec("sdtwin.power.battery.spm2/1", "battery",
                           {"N_s": "positive_int", "N_p": "positive_int", "cell_parameter_pack": "text"},
                           "reduced order two state single particle model with separate heat P4 to P10"),
            PowerModelSpec("sdtwin.power.controller.ideal_mppt/1", "controller", {"control_rule": "text"},
                           "ideal quasi static MPPT, charge limiting and supply loss rules, own losses neglected"),
            PowerModelSpec("sdtwin.power.pdu.fixed_efficiency/1", "pdu",
                           {"eta_D": "efficiency", "wiring_scope": "text"}, "P3 fixed distribution efficiency"),
            PowerModelSpec("sdtwin.power.load.compute_request/1", "load", {"rated_power_W": "positive"},
                           "computing node load request and start or stop interface"),
        )
    }
)

DOMAIN_REGISTRIES: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {"thermal": THERMAL_MODEL_REGISTRY, "power": POWER_MODEL_REGISTRY}
)


# --------------------------------------------------------------------------------------------------------------------
# Small validation helpers
# --------------------------------------------------------------------------------------------------------------------


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_thaw(v) for v in value.tolist()]
    return value


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SceneError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _list(value: Any, where: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise SceneError(f"{where}: expected a list, got {type(value).__name__}")
    return value


def _keys(mapping: Mapping[str, Any], where: str, required: Sequence[str], optional: Sequence[str] = ()) -> None:
    missing = [k for k in required if k not in mapping]
    if missing:
        raise SceneError(f"{where}: missing field {missing[0]!r}")
    unknown = sorted(set(mapping) - set(required) - set(optional))
    if unknown:
        raise SceneError(f"{where}: unknown field {unknown[0]!r}")


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SceneError(f"{where}: must be a non-empty string")
    return value


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SceneError(f"{where}: must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise SceneError(f"{where}: must be finite, got {value!r}")
    return number


def _positive(value: Any, where: str) -> float:
    number = _number(value, where)
    if number <= 0.0:
        raise SceneError(f"{where}: must be > 0, got {value!r}")
    return number


def _unit_interval(value: Any, where: str, *, open_low: bool = False) -> float:
    number = _number(value, where)
    if number > 1.0 or number < 0.0 or (open_low and number == 0.0):
        bound = "(0, 1]" if open_low else "[0, 1]"
        raise SceneError(f"{where}: must lie in {bound}, got {value!r}")
    return number


def _vector(value: Any, size: int, where: str) -> NDArray[np.float64]:
    items = _list(value, where)
    if len(items) != size:
        raise SceneError(f"{where}: must have {size} entries, got {len(items)}")
    array = np.array([_number(v, f"{where}[{i}]") for i, v in enumerate(items)], dtype=float)
    array.setflags(write=False)
    return array


def _temperature_range(value: Any, where: str) -> tuple[float, float]:
    low, high = _vector(value, 2, where)
    if not 0.0 < low < high:
        raise SceneError(f"{where}: must satisfy 0 < min < max, got {list(value)}")
    return float(low), float(high)


def _identifier(value: Any, where: str) -> str:
    text = _text(value, where)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        raise SceneError(f"{where}: {text!r} is not a valid USD prim name")
    return text


def _local_path(base: Path, value: Any, where: str, suffixes: Sequence[str]) -> Path:
    text = _text(value, where)
    if "://" in text or text.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", text):
        raise SceneError(f"{where}: {text!r} must be a path relative to its record file")
    path = (base / text).resolve()
    if path.suffix.lower() not in suffixes:
        raise SceneError(f"{where}: {text!r} must end with one of {tuple(suffixes)}")
    if not path.is_file():
        raise SceneError(f"{where}: file {text!r} does not exist (resolved to {path})")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite JSON constant {name}")


def _read_json(path: str | Path, what: str) -> tuple[Path, Mapping[str, Any]]:
    file = Path(path).resolve()
    if not file.is_file():
        raise SceneError(f"{what} file {file} does not exist")
    try:
        data = json.loads(file.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except ValueError as exc:
        raise SceneError(f"{what} file {file.name}: invalid JSON ({exc})") from exc
    return file, _mapping(data, f"{what} file {file.name}")


# --------------------------------------------------------------------------------------------------------------------
# Geometry (USD) records
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GeometryPrim:
    """One boundable prim of an asset stage with its physical box size in metres.

    ``size_m`` is the local extent size times ``metersPerUnit``. ``rotation_to_asset`` (3, 3) maps a vector in the
    prim's local axes to the asset root axes (column convention); prim-to-root transforms must be rigid.
    """

    prim_path: str
    extent_stage_units: NDArray[np.float64]
    size_m: NDArray[np.float64]
    rotation_to_asset: NDArray[np.float64]

    def __post_init__(self) -> None:
        for name, shape in (("extent_stage_units", (2, 3)), ("size_m", (3,)), ("rotation_to_asset", (3, 3))):
            array = np.array(getattr(self, name), dtype=float)
            if array.shape != shape or not np.all(np.isfinite(array)):
                raise ValueError(f"GeometryPrim {self.prim_path}: {name} must be finite with shape {shape}")
            array.setflags(write=False)
            object.__setattr__(self, name, array)
        if np.any(self.size_m <= 0.0):
            raise ValueError(f"GeometryPrim {self.prim_path}: size_m must be > 0 on every axis")

    def face_area_m2(self, face: str) -> float:
        axis, _ = FACES[face]
        return float(self.size_m[(axis + 1) % 3] * self.size_m[(axis + 2) % 3])

    def face_normal_asset(self, face: str) -> NDArray[np.float64]:
        axis, sign = FACES[face]
        local = np.zeros(3)
        local[axis] = sign
        normal = self.rotation_to_asset @ local
        return normal / np.linalg.norm(normal)

    @property
    def box_volume_m3(self) -> float:
        return float(np.prod(self.size_m))


@dataclass(frozen=True)
class GeometryRecord:
    """Physical geometry read from one asset USD file (design 9.4: length units and extents, no display scale)."""

    path: Path
    sha256: str
    meters_per_unit: float
    default_prim: str
    prims: Mapping[str, GeometryPrim]

    def __post_init__(self) -> None:
        if not (math.isfinite(self.meters_per_unit) and self.meters_per_unit > 0.0):
            raise ValueError(f"geometry {self.path.name}: meters_per_unit must be finite and > 0")
        object.__setattr__(self, "prims", MappingProxyType(dict(self.prims)))

    def prim(self, name: str, where: str) -> GeometryPrim:
        if name not in self.prims:
            raise SceneError(f"{where}: geometry prim {name!r} not found under the default prim of {self.path.name}")
        return self.prims[name]


def _decode_float32(value: float) -> float:
    """Shortest decimal that round-trips the float32 extent value (USD stores extents as float3)."""
    return float(np.format_float_positional(np.float32(value), unique=True, trim="-"))


def read_geometry(path: str | Path, prim_names: Sequence[str], where: str) -> GeometryRecord:
    """Read ``metersPerUnit`` and the extents of every geometry prim under the default prim of a USD file.

    ``prim_names`` (paths relative to the default prim) must all be present. Only stage metadata, extents and
    transforms are read; USD content is never executed. ``metersPerUnit`` must be authored, because the USD fallback of
    0.01 would silently define centimetres. Every geometry prim must have a rigid transform to the stage root.
    """
    from pxr import Sdf, Usd, UsdGeom

    file = Path(path).resolve()
    layer = Sdf.Layer.FindOrOpen(str(file))
    if layer is None:
        raise SceneError(f"{where}: geometry file {file.name} cannot be opened as a USD layer")
    stage = Usd.Stage.Open(layer)
    if not UsdGeom.StageHasAuthoredMetersPerUnit(stage):
        raise SceneError(f"{where}: geometry {file.name} has no authored metersPerUnit")
    mpu = float(UsdGeom.GetStageMetersPerUnit(stage))
    if not (math.isfinite(mpu) and mpu > 0.0):
        raise SceneError(f"{where}: geometry {file.name} metersPerUnit must be finite and > 0, got {mpu}")
    root = stage.GetDefaultPrim()
    if not root or not root.IsValid():
        raise SceneError(f"{where}: geometry {file.name} has no defaultPrim")
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    root_matrix = cache.GetLocalToWorldTransform(root)
    names: dict[str, Any] = {}
    for prim in Usd.PrimRange(root):
        if prim.IsA(UsdGeom.Gprim):
            names[str(prim.GetPath().MakeRelativePath(root.GetPath()))] = prim
    for name in prim_names:
        if name in names:
            continue
        try:
            prim = stage.GetPrimAtPath(root.GetPath().AppendPath(Sdf.Path(name)))
        except Exception as exc:  # noqa: BLE001  (Sdf raises Tf errors)
            raise SceneError(f"{where}: geometry {file.name} prim {name!r}: invalid relative prim path") from exc
        if not prim or not prim.IsValid():
            raise SceneError(f"{where}: geometry {file.name} prim {name!r}: not found under the default prim "
                             f"{root.GetPath()}")
        names[name] = prim
    prims: dict[str, GeometryPrim] = {}
    for name, prim in names.items():
        prim_where = f"{where}: geometry {file.name} prim {name!r}"
        boundable = UsdGeom.Boundable(prim)
        if not boundable:
            raise SceneError(f"{prim_where}: is not a boundable geometry prim")
        extent_attr = boundable.GetExtentAttr()
        if not extent_attr.HasAuthoredValue():
            raise SceneError(f"{prim_where}: has no authored extent")
        extent = np.array([[_decode_float32(c) for c in v] for v in extent_attr.Get()], dtype=float)
        if extent.shape != (2, 3) or not np.all(np.isfinite(extent)):
            raise SceneError(f"{prim_where}: extent must be two finite 3-vectors")
        world = cache.GetLocalToWorldTransform(prim)
        for label, matrix in (("prim", world), ("default prim", root_matrix)):
            linear = np.array([[matrix[i][j] for j in range(3)] for i in range(3)], dtype=float)
            if np.max(np.abs(linear @ linear.T - np.eye(3))) > RIGID_TOL or np.linalg.det(linear) < 0.0:
                raise SceneError(
                    f"{prim_where}: {label} transform contains scale, shear or reflection; physical sizes must come "
                    "from extents and metersPerUnit only"
                )
        relative = world * root_matrix.GetInverse()
        row_rotation = np.array([[relative[i][j] for j in range(3)] for i in range(3)], dtype=float)
        size = (extent[1] - extent[0]) * mpu
        if np.any(size <= 0.0):
            raise SceneError(f"{prim_where}: extent max must exceed min on every axis, got {extent.tolist()}")
        prims[name] = GeometryPrim(str(prim.GetPath()), extent, size, row_rotation.T)
    return GeometryRecord(file, _sha256(file), mpu, str(root.GetPath()), prims)


# --------------------------------------------------------------------------------------------------------------------
# Asset records
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PortRecord:
    """Parameter evidence port (design table 9): temperature, heat-source, electrical or transfer definition."""

    name: str
    kind: str
    unit: str
    description: str

    def __post_init__(self) -> None:
        if self.kind not in PORT_KINDS:
            raise ValueError(f"port {self.name!r}: kind {self.kind!r} not in {tuple(PORT_KINDS)}")
        if self.unit != PORT_KINDS[self.kind]:
            raise ValueError(f"port {self.name!r}: unit must be {PORT_KINDS[self.kind]!r} for kind {self.kind!r}")
        if self.kind == "power_port" and self.name not in THERMAL_POWER_PORTS:
            raise ValueError(f"port {self.name!r}: power_port names must be one of {THERMAL_POWER_PORTS}")


@dataclass(frozen=True)
class CapabilityRecord:
    """Physical capability (design table 9): domain, registered model_id and its read-only parameter_set."""

    domain: str
    model_id: str
    parameter_set: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_set", _freeze(self.parameter_set))

    @property
    def spec(self) -> Any:
        return DOMAIN_REGISTRIES[self.domain][self.model_id]


@dataclass(frozen=True)
class AssetRecord:
    """Validated SimReady asset definition with its parsed physical geometry."""

    asset_id: str
    asset_version: str
    geometry_uri: str
    geometry: GeometryRecord
    capabilities: tuple[CapabilityRecord, ...]
    ports: tuple[PortRecord, ...]
    provenance: Mapping[str, Any]
    source_path: Path
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "ports", tuple(self.ports))
        object.__setattr__(self, "provenance", _freeze(self.provenance))

    @property
    def label(self) -> str:
        return f"asset {self.asset_id}@{self.asset_version}"

    def capability(self, domain: str) -> CapabilityRecord | None:
        for capability in self.capabilities:
            if capability.domain == domain:
                return capability
        return None

    @property
    def thermal(self) -> CapabilityRecord:
        capability = self.capability("thermal")
        assert capability is not None  # guaranteed by load_asset
        return capability

    @property
    def thermal_spec(self) -> ThermalModelSpec:
        return self.thermal.spec

    def power_ports(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.ports if p.kind == "power_port")


def _validate_thermal_parameter_set(params: Mapping[str, Any], spec: ThermalModelSpec, where: str) -> list[str]:
    """Check the thermal parameter_set and return the geometry prim names it uses."""
    _keys(params, where, ("materials", "surfaces", "temperature_range_K"))
    _temperature_range(params["temperature_range_K"], f"{where}.temperature_range_K")
    prims: list[str] = []
    materials = _list(params["materials"], f"{where}.materials")
    if not materials:
        raise SceneError(f"{where}.materials: at least one material portion is required")
    seen: set[str] = set()
    for i, material in enumerate(materials):
        mwhere = f"{where}.materials[{i}]"
        material = _mapping(material, mwhere)
        mid = _identifier(material.get("material_id"), f"{mwhere}.material_id")
        mwhere = f"{where}.materials[{mid}]"
        if mid in seen:
            raise SceneError(f"{mwhere}: duplicate material_id")
        seen.add(mid)
        if "mass_kg" in material:
            _keys(material, mwhere, ("material_id", "mass_kg", "cp_J_kgK", "source"))
            _positive(material["mass_kg"], f"{mwhere}.mass_kg")
        else:
            _keys(material, mwhere,
                  ("material_id", "density_kg_m3", "geometry_prim", "volume_basis", "solid_fraction", "cp_J_kgK",
                   "source"))
            _positive(material["density_kg_m3"], f"{mwhere}.density_kg_m3")
            _unit_interval(material["solid_fraction"], f"{mwhere}.solid_fraction", open_low=True)
            if material["volume_basis"] != "extent_box":
                raise SceneError(f"{mwhere}.volume_basis: only 'extent_box' is supported")
            prims.append(_text(material["geometry_prim"], f"{mwhere}.geometry_prim"))
        _positive(material["cp_J_kgK"], f"{mwhere}.cp_J_kgK")
        _text(material["source"], f"{mwhere}.source")
    surfaces = _list(params["surfaces"], f"{where}.surfaces")
    if spec.exposed and not surfaces:
        raise SceneError(f"{where}.surfaces: node {spec.node_id} is exposed and needs at least one surface")
    if not spec.exposed and surfaces:
        raise SceneError(f"{where}.surfaces: node {spec.node_id} is internal; only nodes {EXPOSED_NODES} have surfaces")
    seen = set()
    for i, surface in enumerate(surfaces):
        swhere = f"{where}.surfaces[{i}]"
        surface = _mapping(surface, swhere)
        sid = _identifier(surface.get("surface_id"), f"{swhere}.surface_id")
        swhere = f"{where}.surfaces[{sid}]"
        if sid in seen:
            raise SceneError(f"{swhere}: duplicate surface_id")
        seen.add(sid)
        _keys(surface, swhere, ("surface_id", "geometry_prim", "face", "absorptivity", "emissivity", "source"))
        if surface["face"] not in FACES:
            raise SceneError(f"{swhere}.face: {surface['face']!r} not in {tuple(FACES)}")
        _unit_interval(surface["absorptivity"], f"{swhere}.absorptivity")
        _unit_interval(surface["emissivity"], f"{swhere}.emissivity")
        _text(surface["source"], f"{swhere}.source")
        prims.append(_text(surface["geometry_prim"], f"{swhere}.geometry_prim"))
    return prims


def _check_power_value(kind: str, value: Any, where: str) -> Any:
    if kind == "positive":
        return _positive(value, where)
    if kind == "efficiency":
        return _unit_interval(value, where, open_low=True)
    if kind == "positive_int":
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SceneError(f"{where}: must be an integer >= 1, got {value!r}")
        return value
    return _text(value, where)


def _validate_power_parameter_set(params: Mapping[str, Any], spec: PowerModelSpec, thermal: Mapping[str, Any],
                                  where: str) -> None:
    _keys(params, where, tuple(spec.parameters))
    for name, kind in spec.parameters.items():
        _check_power_value(kind, params[name], f"{where}.{name}")
        if kind == "surface_ref":
            ids = {s["surface_id"] for s in thermal["surfaces"]}
            if params[name] not in ids:
                raise SceneError(f"{where}.{name}: {params[name]!r} is not a thermal surface of this asset")


def load_asset(path: str | Path) -> AssetRecord:
    """Read and validate one SimReady asset definition (JSON) and its USD geometry."""
    file, data = _read_json(path, "asset")
    where = f"asset file {file.name}"
    _keys(data, where, ("asset_id", "asset_version", "geometry_uri", "capabilities", "ports", "provenance"),
          ("description",))
    asset_id = _text(data["asset_id"], f"{where}.asset_id")
    version = _text(data["asset_version"], f"{where}.asset_version")
    where = f"asset {asset_id}@{version}"
    geometry_path = _local_path(file.parent, data["geometry_uri"], f"{where}.geometry_uri", (".usd", ".usda", ".usdc"))

    provenance = _mapping(data["provenance"], f"{where}.provenance")
    _keys(provenance, f"{where}.provenance", ("status", "note"), ("references",))
    if provenance["status"] not in PROVENANCE_STATUSES:
        raise SceneError(f"{where}.provenance.status: {provenance['status']!r} not in {PROVENANCE_STATUSES}")
    _text(provenance["note"], f"{where}.provenance.note")

    capabilities: list[CapabilityRecord] = []
    for i, item in enumerate(_list(data["capabilities"], f"{where}.capabilities")):
        cwhere = f"{where}.capabilities[{i}]"
        item = _mapping(item, cwhere)
        _keys(item, cwhere, ("domain", "model_id", "parameter_set"))
        domain = _text(item["domain"], f"{cwhere}.domain")
        if domain not in DOMAIN_REGISTRIES:
            raise SceneError(f"{cwhere}.domain: {domain!r} not in {tuple(DOMAIN_REGISTRIES)}")
        if any(c.domain == domain for c in capabilities):
            raise SceneError(f"{cwhere}.domain: duplicate capability for domain {domain!r}")
        model_id = _text(item["model_id"], f"{cwhere}.model_id")
        if model_id not in DOMAIN_REGISTRIES[domain]:
            raise UnregisteredModelError(
                f"{cwhere}.model_id: {model_id!r} is not a registered {domain} model; allowed ids are "
                f"{sorted(DOMAIN_REGISTRIES[domain])}"
            )
        capabilities.append(CapabilityRecord(domain, model_id, _mapping(item["parameter_set"],
                                                                        f"{cwhere}.parameter_set")))
    thermal = next((c for c in capabilities if c.domain == "thermal"), None)
    if thermal is None:
        raise SceneError(f"{where}.capabilities: a thermal capability is required")
    spec: ThermalModelSpec = thermal.spec
    twhere = f"{where}.capabilities[thermal].parameter_set"
    prim_names = _validate_thermal_parameter_set(thermal.parameter_set, spec, twhere)
    power = next((c for c in capabilities if c.domain == "power"), None)
    if power is not None:
        _validate_power_parameter_set(power.parameter_set, power.spec, thermal.parameter_set,
                                      f"{where}.capabilities[power].parameter_set")

    ports: list[PortRecord] = []
    for i, item in enumerate(_list(data["ports"], f"{where}.ports")):
        pwhere = f"{where}.ports[{i}]"
        item = _mapping(item, pwhere)
        _keys(item, pwhere, ("name", "kind", "unit", "description"))
        name = _text(item["name"], f"{pwhere}.name")
        if any(p.name == name for p in ports):
            raise SceneError(f"{pwhere}.name: duplicate port {name!r}")
        try:
            ports.append(PortRecord(name, _text(item["kind"], f"{pwhere}.kind"), _text(item["unit"], f"{pwhere}.unit"),
                                    _text(item["description"], f"{pwhere}.description")))
        except ValueError as exc:
            if isinstance(exc, SceneError):
                raise
            raise SceneError(f"{pwhere}: {exc}") from exc
    supplied = {p.name for p in ports if p.kind == "power_port"}
    if not supplied <= set(spec.allowed_ports):
        bad = sorted(supplied - set(spec.allowed_ports))
        raise SceneError(f"{where}.ports: {bad} not allowed for thermal model {spec.model_id} "
                         f"(allowed {spec.allowed_ports})")
    if not set(spec.required_ports) <= supplied:
        bad = sorted(set(spec.required_ports) - supplied)
        raise SceneError(f"{where}.ports: thermal model {spec.model_id} requires power_port {bad}")
    for name in sorted(supplied):
        role = PORT_POWER_ROLES[name]
        if power is None:
            raise SceneError(f"{where}.ports[{name}]: power_port {name} must come from an asset with a Power "
                             f"capability of role {role!r}, but this asset has no power capability")
        if power.spec.role != role:
            raise SceneError(f"{where}.ports[{name}]: power_port {name} must come from a Power {role!r} device, but "
                             f"this asset's power model {power.model_id} has role {power.spec.role!r}")

    geometry = read_geometry(geometry_path, prim_names, where)
    return AssetRecord(asset_id, version, data["geometry_uri"], geometry, tuple(capabilities), tuple(ports),
                       provenance, file, _sha256(file))


# --------------------------------------------------------------------------------------------------------------------
# Scene records
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SceneInstance:
    """Scene instance (design table 9): instance_id, asset_ref, physical mounting and optional display transform.

    ``body_from_asset_xyzw`` is the active rotation from asset axes to the spacecraft body frame (SciPy xyzw). The
    display transform (``translate_m``, ``scale``) only places and scales the USD prim for display.
    """

    instance_id: str
    asset_ref: str
    asset_path: Path
    body_from_asset_xyzw: NDArray[np.float64]
    display_translate_m: NDArray[np.float64]
    display_scale: NDArray[np.float64]

    def __post_init__(self) -> None:
        for name, size in (("body_from_asset_xyzw", 4), ("display_translate_m", 3), ("display_scale", 3)):
            array = np.array(getattr(self, name), dtype=float)
            if array.shape != (size,) or not np.all(np.isfinite(array)):
                raise ValueError(f"instance {self.instance_id}: {name} must be finite with shape ({size},)")
            array.setflags(write=False)
            object.__setattr__(self, name, array)
        if abs(np.linalg.norm(self.body_from_asset_xyzw) - 1.0) > QUATERNION_TOL:
            raise ValueError(f"instance {self.instance_id}: body_from_asset_xyzw must be a unit quaternion")
        if np.any(self.display_scale <= 0.0):
            raise ValueError(f"instance {self.instance_id}: display_scale must be > 0")

    @property
    def prim_path(self) -> str:
        return f"{SAT_ROOT}/{self.instance_id}"


@dataclass(frozen=True)
class SceneRecord:
    """Validated scene record with its instances, loaded assets and scene configuration."""

    scene_id: str
    scene_version: str
    instances: tuple[SceneInstance, ...]
    assets: Mapping[str, AssetRecord]
    parameter_overrides: Mapping[str, Any]
    initial_state: Mapping[str, Any]
    connections: Mapping[str, Any]
    provenance: Mapping[str, Any]
    source_path: Path
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "instances", tuple(self.instances))
        object.__setattr__(self, "assets", MappingProxyType(dict(self.assets)))
        for name in ("parameter_overrides", "initial_state", "connections", "provenance"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    @property
    def label(self) -> str:
        return f"scene {self.scene_id}@{self.scene_version}"

    def instance(self, instance_id: str) -> SceneInstance:
        for item in self.instances:
            if item.instance_id == instance_id:
                return item
        raise SceneError(f"{self.label}: unknown instance_id {instance_id!r}")

    def asset_of(self, instance_id: str) -> AssetRecord:
        return self.assets[str(self.instance(instance_id).asset_path)]

    def node_of(self, instance_id: str) -> str:
        return self.asset_of(instance_id).thermal_spec.node_id


_MATERIAL_OVERRIDE_FIELDS = ("mass_kg", "cp_J_kgK", "density_kg_m3", "solid_fraction")
_SURFACE_OVERRIDE_FIELDS = ("absorptivity", "emissivity")
_CONDUCTION_FIELDS = ("length_m", "conductivity_W_mK", "area_m2", "contact_resistance_K_W")
_EQUIVALENT_FIELDS = ("equivalent_total_resistance_K_W", "includes_contact")
_CONNECTION_FIELDS = _CONDUCTION_FIELDS + _EQUIVALENT_FIELDS


def _load_instances(scene_file: Path, items: Sequence[Any], where: str) -> tuple[list[SceneInstance], dict]:
    instances: list[SceneInstance] = []
    assets: dict[str, AssetRecord] = {}
    for i, item in enumerate(items):
        iwhere = f"{where}.instances[{i}]"
        item = _mapping(item, iwhere)
        iid = _identifier(item.get("instance_id"), f"{iwhere}.instance_id")
        iwhere = f"{where}.instances[{iid}]"
        if any(x.instance_id == iid for x in instances):
            raise SceneError(f"{iwhere}.instance_id: duplicate instance_id")
        _keys(item, iwhere, ("instance_id", "asset_ref", "mounting"), ("display_transform",))
        asset_path = _local_path(scene_file.parent, item["asset_ref"], f"{iwhere}.asset_ref", (".json",))
        if str(asset_path) not in assets:
            assets[str(asset_path)] = load_asset(asset_path)
        mounting = _mapping(item["mounting"], f"{iwhere}.mounting")
        _keys(mounting, f"{iwhere}.mounting", ("body_from_asset_xyzw",))
        quaternion = _vector(mounting["body_from_asset_xyzw"], 4, f"{iwhere}.mounting.body_from_asset_xyzw")
        if abs(np.linalg.norm(quaternion) - 1.0) > QUATERNION_TOL:
            raise SceneError(f"{iwhere}.mounting.body_from_asset_xyzw: must be a unit quaternion within "
                             f"{QUATERNION_TOL}, norm is {float(np.linalg.norm(quaternion))!r}")
        display = _mapping(item.get("display_transform", {}), f"{iwhere}.display_transform")
        _keys(display, f"{iwhere}.display_transform", (), ("translate_m", "scale"))
        translate = (_vector(display["translate_m"], 3, f"{iwhere}.display_transform.translate_m")
                     if "translate_m" in display else np.zeros(3))
        scale = (_vector(display["scale"], 3, f"{iwhere}.display_transform.scale")
                 if "scale" in display else np.ones(3))
        if np.any(scale <= 0.0):
            raise SceneError(f"{iwhere}.display_transform.scale: must be > 0 on every axis")
        instances.append(SceneInstance(iid, item["asset_ref"], asset_path, quaternion, translate, scale))
    return instances, assets


def load_scene(path: str | Path) -> SceneRecord:
    """Read and validate a Sat01 scene record (JSON), its referenced assets and their USD geometry."""
    file, data = _read_json(path, "scene")
    where = f"scene file {file.name}"
    _keys(data, where, ("scene_id", "scene_version", "root_prim_path", "instances", "parameter_overrides",
                        "initial_state", "connections", "provenance"), ("description",))
    scene_id = _text(data["scene_id"], f"{where}.scene_id")
    version = _text(data["scene_version"], f"{where}.scene_version")
    where = f"scene {scene_id}@{version}"
    if data["root_prim_path"] != SAT_ROOT:
        raise SceneError(f"{where}.root_prim_path: must be {SAT_ROOT!r}, got {data['root_prim_path']!r}")
    provenance = _mapping(data["provenance"], f"{where}.provenance")
    _keys(provenance, f"{where}.provenance", ("status", "note"), ("references",))
    if provenance["status"] not in PROVENANCE_STATUSES:
        raise SceneError(f"{where}.provenance.status: {provenance['status']!r} not in {PROVENANCE_STATUSES}")

    items = _list(data["instances"], f"{where}.instances")
    if not items:
        raise SceneError(f"{where}.instances: at least one instance is required")
    instances, assets = _load_instances(file, items, where)
    by_id = {x.instance_id: x for x in instances}

    def node(iid: str) -> str:
        return assets[str(by_id[iid].asset_path)].thermal_spec.node_id

    def node_asset(iid: str) -> str:
        return assets[str(by_id[iid].asset_path)].asset_id

    nodes = {n: [x.instance_id for x in instances if node(x.instance_id) == n] for n in NODE_ORDER}
    for n, members in nodes.items():
        if not members:
            raise SceneError(f"{where}.instances: thermal node {n} has no instance")
        for k, iid in enumerate(members[1:], start=1):
            same = [m for m in members[:k] if node_asset(m) == node_asset(iid)]
            if same:
                raise SceneError(f"{where}.instances[{iid}]: node {n} already holds {same[0]}; two instances of one "
                                 "asset need independent temperatures, which the six-node model cannot represent")
            if n not in SHARED_TEMPERATURE_NODES:
                raise SceneError(f"{where}.instances[{iid}]: node {n} already holds {members[0]}; only nodes "
                                 f"{SHARED_TEMPERATURE_NODES} are shared temperature extents in this version, so "
                                 f"{iid} would need its own temperature, which the six-node model cannot represent")

    def asset(iid: str) -> AssetRecord:
        return assets[str(by_id[iid].asset_path)]

    # connections ---------------------------------------------------------------------------------------------------
    connections = _mapping(data["connections"], f"{where}.connections")
    _keys(connections, f"{where}.connections", ("thermal", "electrical"))
    thermal_paths: set[str] = set()
    for i, item in enumerate(_list(connections["thermal"], f"{where}.connections.thermal")):
        cwhere = f"{where}.connections.thermal[{i}]"
        item = _mapping(item, cwhere)
        path_id = item.get("path")
        if path_id not in PATH_ORDER:
            raise SceneError(f"{cwhere}.path: {path_id!r} not in {PATH_ORDER}")
        cwhere = f"{where}.connections.thermal[{path_id}]"
        if path_id in thermal_paths:
            raise SceneError(f"{cwhere}: path defined more than once")
        thermal_paths.add(path_id)
        _keys(item, cwhere, ("path", "from_instance", "to_instance", "source"), _CONNECTION_FIELDS)
        _text(item["source"], f"{cwhere}.source")
        for end, field, expected in (("from", "from_instance", PATH_NODES[path_id][0]),
                                     ("to", "to_instance", PATH_NODES[path_id][1])):
            iid = item[field]
            if iid not in by_id:
                raise SceneError(f"{cwhere}.{field}: unknown instance {iid!r}")
            if node(iid) != expected:
                raise SceneError(f"{cwhere}.{field}: instance {iid} is node {node(iid)}, path {path_id} needs "
                                 f"{expected} at its {end} end")
    missing = [p for p in PATH_ORDER if p not in thermal_paths]
    if missing:
        raise SceneError(f"{where}.connections.thermal: path {missing[0]} is not defined")
    for i, item in enumerate(_list(connections["electrical"], f"{where}.connections.electrical")):
        ewhere = f"{where}.connections.electrical[{i}]"
        item = _mapping(item, ewhere)
        _keys(item, ewhere, ("from", "to", "source"))
        _text(item["source"], f"{ewhere}.source")
        for end in ("from", "to"):
            endpoint = _mapping(item[end], f"{ewhere}.{end}")
            _keys(endpoint, f"{ewhere}.{end}", ("instance_id", "port"))
            iid = endpoint["instance_id"]
            if iid not in by_id:
                raise SceneError(f"{ewhere}.{end}.instance_id: unknown instance {iid!r}")
            ports = {p.name: p for p in asset(iid).ports}
            port = ports.get(endpoint["port"])
            if port is None or port.kind != "electrical":
                raise SceneError(f"{ewhere}.{end}.port: {endpoint['port']!r} is not an electrical port of {iid}")

    # parameter overrides -------------------------------------------------------------------------------------------
    overrides = _mapping(data["parameter_overrides"], f"{where}.parameter_overrides")
    owhere = f"{where}.parameter_overrides"
    _keys(overrides, owhere, ("instances", "connections"), ("source",))
    inst_over = _mapping(overrides["instances"], f"{owhere}.instances")
    conn_over = _mapping(overrides["connections"], f"{owhere}.connections")
    if (inst_over or conn_over) and "source" not in overrides:
        raise SceneError(f"{owhere}: missing field 'source' for the overrides it declares")
    if "source" in overrides:
        _text(overrides["source"], f"{owhere}.source")
    for iid, block in inst_over.items():
        bwhere = f"{owhere}.instances[{iid}]"
        if iid not in by_id:
            raise SceneError(f"{bwhere}: unknown instance_id")
        block = _mapping(block, bwhere)
        _keys(block, bwhere, (), ("thermal", "power"))
        record = asset(iid)
        if "thermal" in block:
            _validate_thermal_override(_mapping(block["thermal"], f"{bwhere}.thermal"), record, f"{bwhere}.thermal")
        if "power" in block:
            power = record.capability("power")
            pblock = _mapping(block["power"], f"{bwhere}.power")
            if power is None:
                raise SceneError(f"{bwhere}.power: asset {record.asset_id} has no power capability")
            for field, value in pblock.items():
                if field not in power.spec.parameters:
                    raise SceneError(f"{bwhere}.power.{field}: not a parameter of {power.model_id}")
                if power.spec.parameters[field] == "surface_ref":
                    raise SceneError(f"{bwhere}.power.{field}: the surface binding is fixed by the asset")
                _check_power_value(power.spec.parameters[field], value, f"{bwhere}.power.{field}")
    for path_id, block in conn_over.items():
        bwhere = f"{owhere}.connections[{path_id}]"
        if path_id not in PATH_ORDER:
            raise SceneError(f"{bwhere}: unknown path")
        for field in _mapping(block, bwhere):
            if field not in _CONNECTION_FIELDS:
                raise SceneError(f"{bwhere}.{field}: not an overridable connection field {_CONNECTION_FIELDS}")

    # initial state -------------------------------------------------------------------------------------------------
    initial = _mapping(data["initial_state"], f"{where}.initial_state")
    iwhere = f"{where}.initial_state"
    _keys(initial, iwhere, ("thermal",), ("power",))
    thermal_init = _mapping(initial["thermal"], f"{iwhere}.thermal")
    _keys(thermal_init, f"{iwhere}.thermal", ("temperature_K",))
    temps = _mapping(thermal_init["temperature_K"], f"{iwhere}.thermal.temperature_K")
    for iid in temps:
        if iid not in by_id:
            raise SceneError(f"{iwhere}.thermal.temperature_K[{iid}]: unknown instance_id")
    for x in instances:
        if x.instance_id not in temps:
            raise SceneError(f"{iwhere}.thermal.temperature_K: missing initial temperature of {x.instance_id}")
        _positive(temps[x.instance_id], f"{iwhere}.thermal.temperature_K[{x.instance_id}]")
    for n, members in nodes.items():
        values = {float(temps[m]) for m in members}
        if len(values) > 1:
            raise SceneError(f"{iwhere}.thermal.temperature_K: instances {members} share node {n} but have different "
                             f"initial temperatures {sorted(values)}")
    for iid, block in _mapping(initial.get("power", {}), f"{iwhere}.power").items():
        pwhere = f"{iwhere}.power[{iid}]"
        if iid not in by_id:
            raise SceneError(f"{pwhere}: unknown instance_id")
        if asset(iid).capability("power") is None:
            raise SceneError(f"{pwhere}: instance has no power capability")
        for field in _mapping(block, pwhere):
            if "T_" in field or "temperature" in field.lower():
                raise SceneError(f"{pwhere}.{field}: temperatures are owned by Thermal and belong in "
                                 "initial_state.thermal")

    return SceneRecord(scene_id, version, tuple(instances), assets, overrides, initial, connections, provenance, file,
                       _sha256(file))


def _validate_thermal_override(block: Mapping[str, Any], record: AssetRecord, where: str) -> None:
    _keys(block, where, (), ("materials", "surfaces", "temperature_range_K"))
    params = record.thermal.parameter_set
    materials = {m["material_id"]: m for m in params["materials"]}
    for mid, fields in _mapping(block.get("materials", {}), f"{where}.materials").items():
        mwhere = f"{where}.materials[{mid}]"
        if mid not in materials:
            raise SceneError(f"{mwhere}: not a material of asset {record.asset_id}")
        geometric = "density_kg_m3" in materials[mid]
        for field, value in _mapping(fields, mwhere).items():
            if field not in _MATERIAL_OVERRIDE_FIELDS:
                raise SceneError(f"{mwhere}.{field}: not an overridable material field {_MATERIAL_OVERRIDE_FIELDS}")
            if geometric and field == "mass_kg":
                raise SceneError(f"{mwhere}.mass_kg: mass of this portion follows its geometry; override "
                                 "density_kg_m3 or solid_fraction instead")
            if not geometric and field in ("density_kg_m3", "solid_fraction"):
                raise SceneError(f"{mwhere}.{field}: this portion has a recorded mass_kg, not a geometric mass")
            if field == "solid_fraction":
                _unit_interval(value, f"{mwhere}.{field}", open_low=True)
            else:
                _positive(value, f"{mwhere}.{field}")
    surfaces = {s["surface_id"] for s in params["surfaces"]}
    for sid, fields in _mapping(block.get("surfaces", {}), f"{where}.surfaces").items():
        swhere = f"{where}.surfaces[{sid}]"
        if sid not in surfaces:
            raise SceneError(f"{swhere}: not a surface of asset {record.asset_id}")
        for field, value in _mapping(fields, swhere).items():
            if field not in _SURFACE_OVERRIDE_FIELDS:
                raise SceneError(f"{swhere}.{field}: not an overridable surface field {_SURFACE_OVERRIDE_FIELDS}; "
                                 "areas and normals follow geometry and mounting")
            _unit_interval(value, f"{swhere}.{field}")
    if "temperature_range_K" in block:
        _temperature_range(block["temperature_range_K"], f"{where}.temperature_range_K")


# --------------------------------------------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SceneAssembly:
    """Inputs of ``thermal.assemble_thermal_parameters`` and the initial thermal state resolved from one scene.

    ``components``, ``connections`` and ``overrides`` use exactly the input formats of the contract.
    ``initial_temperature_K`` follows NODE_ORDER. ``power`` carries the Power capabilities of the same instances
    (parameter sets after scene overrides, ports, initial Power state and the electrical connections).
    """

    scene_id: str
    scene_version: str
    components: tuple[dict, ...]
    connections: tuple[dict, ...]
    overrides: dict
    initial_temperature_K: NDArray[np.float64]
    instance_paths: Mapping[str, str]
    node_map: Mapping[str, tuple[str, ...]]
    power: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        temperature = np.array(self.initial_temperature_K, dtype=float)
        if temperature.shape != (len(NODE_ORDER),) or not np.all(np.isfinite(temperature)) or np.any(temperature <= 0):
            raise ValueError("SceneAssembly.initial_temperature_K must be finite, > 0, shape (6,) in NODE_ORDER")
        temperature.setflags(write=False)
        object.__setattr__(self, "initial_temperature_K", temperature)
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(self, "connections", tuple(self.connections))
        object.__setattr__(self, "instance_paths", MappingProxyType(dict(self.instance_paths)))
        object.__setattr__(self, "node_map", MappingProxyType({k: tuple(v) for k, v in self.node_map.items()}))
        object.__setattr__(self, "power", _freeze(self.power))
        object.__setattr__(self, "provenance", _freeze(self.provenance))

    def thermal_inputs(self) -> tuple[list[dict], list[dict], dict]:
        """Fresh deep copies of ``(components, connections, overrides)`` for ``assemble_thermal_parameters``."""
        return copy.deepcopy(list(self.components)), copy.deepcopy(list(self.connections)), copy.deepcopy(
            self.overrides)

    def as_dict(self) -> dict:
        """Plain JSON-ready copy of the whole assembly for the pre-run archive of design 9.4."""
        return {
            "scene_id": self.scene_id, "scene_version": self.scene_version,
            "components": _thaw(self.components), "connections": _thaw(self.connections),
            "overrides": _thaw(self.overrides), "initial_temperature_K": self.initial_temperature_K.tolist(),
            "instance_paths": dict(self.instance_paths), "node_map": _thaw(self.node_map),
            "power": _thaw(self.power), "provenance": _thaw(self.provenance),
        }


def _qualified(instance_id: str, local_id: str) -> str:
    return f"{instance_id}/{local_id}"


def _geometric_mass(material: Mapping[str, Any], geometry: GeometryRecord, where: str,
                    density: float | None = None, solid_fraction: float | None = None) -> tuple[float, dict]:
    prim = geometry.prim(material["geometry_prim"], where)
    rho = float(material["density_kg_m3"]) if density is None else density
    fraction = float(material["solid_fraction"]) if solid_fraction is None else solid_fraction
    mass = rho * prim.box_volume_m3 * fraction
    return mass, {"density_kg_m3": rho, "solid_fraction": fraction, "box_size_m": prim.size_m.tolist(),
                  "box_volume_m3": prim.box_volume_m3, "geometry_prim": prim.prim_path, "mass_kg": mass}


def _component(instance: SceneInstance, record: AssetRecord) -> tuple[dict, dict]:
    """Build the contract component mapping of one instance and the geometry derivations behind it."""
    params = record.thermal.parameter_set
    spec = record.thermal_spec
    where = f"instance {instance.instance_id} ({record.label})"
    rotation = Rotation.from_quat(np.asarray(instance.body_from_asset_xyzw))
    base = f"{record.asset_id}@{record.asset_version}"
    materials, surfaces, derivations = [], [], {"materials": {}, "surfaces": {}}
    for material in params["materials"]:
        mid = material["material_id"]
        if "mass_kg" in material:
            mass = float(material["mass_kg"])
            source = f"{base} materials[{mid}].mass_kg recorded: {material['source']}"
        else:
            mass, info = _geometric_mass(material, record.geometry, f"{where}.materials[{mid}]")
            derivations["materials"][mid] = info
            size = " x ".join(f"{v:.6g} m" for v in info["box_size_m"])
            source = (f"{base} materials[{mid}].mass_kg = density {info['density_kg_m3']:.6g} kg/m^3 x extent box "
                      f"{size} x solid fraction {info['solid_fraction']:.6g} of {info['geometry_prim']} in "
                      f"{record.geometry.path.name}: {material['source']}")
        materials.append({"material_id": _qualified(instance.instance_id, mid), "mass_kg": mass,
                          "cp_J_kgK": float(material["cp_J_kgK"]), "source": source})
    for surface in params["surfaces"]:
        sid = surface["surface_id"]
        prim = record.geometry.prim(surface["geometry_prim"], f"{where}.surfaces[{sid}]")
        area = prim.face_area_m2(surface["face"])
        normal_asset = prim.face_normal_asset(surface["face"])
        normal_body = rotation.apply(normal_asset)
        normal_body = normal_body / np.linalg.norm(normal_body)
        normal_body[np.abs(normal_body) < 1e-15] = 0.0
        derivations["surfaces"][sid] = {"geometry_prim": prim.prim_path, "face": surface["face"],
                                        "box_size_m": prim.size_m.tolist(), "area_m2": area,
                                        "normal_asset": normal_asset.tolist(), "normal_body": normal_body.tolist()}
        surfaces.append({
            "surface_id": _qualified(instance.instance_id, sid), "area_m2": area, "normal_body": normal_body.tolist(),
            "absorptivity": float(surface["absorptivity"]), "emissivity": float(surface["emissivity"]),
            "source": (f"{base} surfaces[{sid}]: area of face {surface['face']} of {prim.prim_path} in "
                       f"{record.geometry.path.name}, normal rotated by the scene mounting; optical properties: "
                       f"{surface['source']}"),
        })
    component = {
        "instance_id": instance.instance_id,
        "node_id": spec.node_id,
        "asset_id": record.asset_id,
        "asset_version": record.asset_version,
        "materials": materials,
        "surfaces": surfaces,
        "temperature_range_K": [float(v) for v in params["temperature_range_K"]],
        "ports": list(record.power_ports()),
    }
    return component, derivations


def _thermal_overrides(scene: SceneRecord) -> tuple[dict, dict]:
    """Translate scene overrides into the contract ``overrides`` format with qualified ids.

    A density or solid-fraction override of a geometric material portion becomes a recomputed ``mass_kg`` override.
    The second return value keeps, per qualified material id, the overriding scene fields and the derivation of the
    recomputed mass, so the pre-run archive records the value that was actually set (design 9.4).
    """
    block = scene.parameter_overrides
    result: dict = {"components": {}, "connections": {},
                    "source": block.get("source", f"{scene.label}: no parameter overrides")}
    derived: dict = {}
    for iid, inst_block in block["instances"].items():
        thermal = inst_block.get("thermal")
        if not thermal:
            continue
        record = scene.asset_of(iid)
        materials = {m["material_id"]: m for m in record.thermal.parameter_set["materials"]}
        entry: dict = {}
        mat_entry: dict = {}
        for mid, fields in thermal.get("materials", {}).items():
            fields = dict(fields)
            out: dict = {}
            if "cp_J_kgK" in fields:
                out["cp_J_kgK"] = float(fields["cp_J_kgK"])
            if "mass_kg" in fields:
                out["mass_kg"] = float(fields["mass_kg"])
            if "density_kg_m3" in fields or "solid_fraction" in fields:
                mass, info = _geometric_mass(materials[mid], record.geometry, f"{scene.label} override {iid}/{mid}",
                                             density=fields.get("density_kg_m3"),
                                             solid_fraction=fields.get("solid_fraction"))
                out["mass_kg"] = mass
                derived[_qualified(iid, mid)] = {
                    "scene_fields": {k: float(fields[k]) for k in ("density_kg_m3", "solid_fraction") if k in fields},
                    **info,
                }
            if out:
                mat_entry[_qualified(iid, mid)] = out
        if mat_entry:
            entry["materials"] = mat_entry
        surf_entry = {_qualified(iid, sid): {k: float(v) for k, v in fields.items()}
                      for sid, fields in thermal.get("surfaces", {}).items() if fields}
        if surf_entry:
            entry["surfaces"] = surf_entry
        if "temperature_range_K" in thermal:
            entry["temperature_range_K"] = [float(v) for v in thermal["temperature_range_K"]]
        if entry:
            result["components"][iid] = entry
    for path_id, fields in block["connections"].items():
        if fields:
            result["connections"][path_id] = _thaw(fields)
    return result, derived


def _resolved_surface(component: dict, overrides: dict, qualified_sid: str) -> dict:
    surface = next(s for s in component["surfaces"] if s["surface_id"] == qualified_sid)
    resolved = dict(surface)
    resolved.update(overrides["components"].get(component["instance_id"], {}).get("surfaces", {})
                    .get(qualified_sid, {}))
    return resolved


def assemble_scene(scene_path: str | Path) -> SceneAssembly:
    """Load a scene and resolve the inputs of ``assemble_thermal_parameters`` and the initial ``ThermalState``."""
    scene = load_scene(scene_path)
    components: list[dict] = []
    instance_prov: dict = {}
    for instance in scene.instances:
        record = scene.asset_of(instance.instance_id)
        component, derivations = _component(instance, record)
        components.append(component)
        instance_prov[instance.instance_id] = {
            "prim_path": instance.prim_path,
            "asset_ref": instance.asset_ref,
            "asset_id": record.asset_id,
            "asset_version": record.asset_version,
            "thermal_model_id": record.thermal.model_id,
            "node_id": record.thermal_spec.node_id,
            "body_from_asset_xyzw": instance.body_from_asset_xyzw.tolist(),
            "display_transform": {"translate_m": instance.display_translate_m.tolist(),
                                  "scale": instance.display_scale.tolist(),
                                  "use": "display only; not used for areas, volumes or masses"},
            "geometry": {"uri": record.geometry_uri, "meters_per_unit": record.geometry.meters_per_unit,
                         "physical_size_m": {k: p.size_m.tolist() for k, p in record.geometry.prims.items()}},
            "derivations": derivations,
        }

    overrides, override_derivations = _thermal_overrides(scene)
    # Preserve the resolved geometry inputs alongside the effective material mass.
    # The original asset remains unchanged and overrides_applied retains old/new mass.
    for component in components:
        for material in component['materials']:
            info = override_derivations.get(material['material_id'])
            if info is not None:
                material['source'] += (
                    f"; scene override effective density {info['density_kg_m3']:.6g} kg/m^3"
                    f", solid_fraction {info['solid_fraction']:.6g}"
                    f", box_size_m {info['box_size_m']}; {overrides['source']}"
                )

    connections: list[dict] = []
    connection_prov: dict = {}
    for item in sorted(scene.connections["thermal"], key=lambda c: PATH_ORDER.index(c["path"])):
        entry = {k: _thaw(v) for k, v in item.items() if k not in ("from_instance", "to_instance")}
        connections.append(entry)
        connection_prov[item["path"]] = {"from_instance": item["from_instance"], "to_instance": item["to_instance"],
                                         "nodes": list(PATH_NODES[item["path"]])}

    node_map = {n: tuple(x.instance_id for x in scene.instances if scene.node_of(x.instance_id) == n)
                for n in NODE_ORDER}
    temps = scene.initial_state["thermal"]["temperature_K"]
    initial = np.array([float(temps[node_map[n][0]]) for n in NODE_ORDER], dtype=float)

    # Power capabilities of the same instances, with the PV efficiency check of design 9.4.
    by_instance = {c["instance_id"]: c for c in components}
    power_instances: dict = {}
    power_overrides = scene.parameter_overrides["instances"]
    power_initial = scene.initial_state.get("power", {})
    for instance in scene.instances:
        iid = instance.instance_id
        record = scene.asset_of(iid)
        capability = record.capability("power")
        if capability is None:
            continue
        params = _thaw(capability.parameter_set)
        params.update(_thaw(power_overrides.get(iid, {}).get("power", {})))
        entry = {"instance_id": iid, "asset_id": record.asset_id, "asset_version": record.asset_version,
                 "model_id": capability.model_id, "role": capability.spec.role, "parameter_set": params,
                 "ports": [{"name": p.name, "kind": p.kind, "unit": p.unit} for p in record.ports],
                 "initial_state": _thaw(power_initial.get(iid, {}))}
        for name, kind in capability.spec.parameters.items():
            if kind != "surface_ref":
                continue
            qualified = _qualified(iid, params[name])
            surface = _resolved_surface(by_instance[iid], overrides, qualified)
            where = f"{scene.label} instance {iid} power.{name} -> surface {qualified}"
            if "efficiency" in params and params["efficiency"] > surface["absorptivity"]:
                raise SceneError(f"{where}: photovoltaic efficiency {params['efficiency']} exceeds the absorptivity "
                                 f"{surface['absorptivity']} of the same surface (design 9.4)")
            if "cell_area_m2" in params and params["cell_area_m2"] > surface["area_m2"] * (1.0 + 1e-12):
                raise SceneError(f"{where}: cell_area_m2 {params['cell_area_m2']} exceeds the physical surface area "
                                 f"{surface['area_m2']}")
            entry["surface"] = {"surface_id": qualified, "area_m2": surface["area_m2"],
                                "normal_body": list(surface["normal_body"]),
                                "absorptivity": surface["absorptivity"]}
        power_instances[iid] = entry
    power = {"instances": power_instances, "electrical_connections": _thaw(scene.connections["electrical"])}

    stage = compose_stage(scene)
    for instance in scene.instances:
        instance_prov[instance.instance_id]["display_bbox_size_world"] = display_bbox_size(
            stage, instance.instance_id).tolist()

    statuses = sorted({str(r.provenance["status"]) for r in scene.assets.values()} | {str(scene.provenance["status"])})
    provenance = {
        "scene": {"scene_id": scene.scene_id, "scene_version": scene.scene_version, "path": str(scene.source_path),
                  "sha256": scene.sha256, "status": scene.provenance["status"], "note": scene.provenance["note"]},
        "value_status": statuses,
        "assets": {
            r.asset_id: {"asset_version": r.asset_version, "path": str(r.source_path), "sha256": r.sha256,
                         "geometry_uri": r.geometry_uri, "geometry_sha256": r.geometry.sha256,
                         "meters_per_unit": r.geometry.meters_per_unit, "status": r.provenance["status"],
                         "note": r.provenance["note"],
                         "models": {c.domain: c.model_id for c in r.capabilities}}
            for r in scene.assets.values()
        },
        "instances": instance_prov,
        "connections": connection_prov,
        "node_order": list(NODE_ORDER),
        "path_order": list(PATH_ORDER),
        "initial_temperature_K": {iid: float(temps[iid]) for iid in temps},
        "parameter_overrides": {"scene_block": _thaw(scene.parameter_overrides),
                                "derived_masses": override_derivations},
        "model_registry": {"thermal": sorted(THERMAL_MODEL_REGISTRY), "power": sorted(POWER_MODEL_REGISTRY)},
        "physical_size_rule": "areas and volumes come from USD extents times metersPerUnit; instance transforms are "
                              "display data",
    }
    return SceneAssembly(scene.scene_id, scene.scene_version, tuple(components), tuple(connections), overrides,
                         initial, {x.instance_id: x.prim_path for x in scene.instances}, node_map, power, provenance)


# --------------------------------------------------------------------------------------------------------------------
# Display stage
# --------------------------------------------------------------------------------------------------------------------


def compose_stage(scene: SceneRecord | str | Path):
    """Compose an in-memory USD stage with every instance referenced under ``/World/Sat01/<instance_id>``.

    Stage units are metres (``metersPerUnit = 1``). Each instance prim carries, in order, a display translate, the
    mounting orient, a ``unitsResolve`` scale (asset metersPerUnit) and the display scale. The stage is for display;
    physical parameters never read it.
    """
    from pxr import Gf, Sdf, Usd, UsdGeom

    record = scene if isinstance(scene, SceneRecord) else load_scene(scene)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Xform.Define(stage, SAT_ROOT)
    for instance in record.instances:
        asset = record.assets[str(instance.asset_path)]
        xform = UsdGeom.Xform.Define(stage, instance.prim_path)
        prim = xform.GetPrim()
        prim.GetReferences().AddReference(instance.asset_path.parent.joinpath(asset.geometry_uri).resolve().as_posix())
        prim.SetCustomDataByKey("sdtwin:asset_id", asset.asset_id)
        prim.SetCustomDataByKey("sdtwin:asset_version", asset.asset_version)
        prim.SetCustomDataByKey("sdtwin:thermal_node", asset.thermal_spec.node_id)
        xform.ClearXformOpOrder()
        xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble, "display").Set(
            Gf.Vec3d(*instance.display_translate_m.tolist()))
        x, y, z, w = instance.body_from_asset_xyzw.tolist()
        xform.AddOrientOp(UsdGeom.XformOp.PrecisionDouble, "mounting").Set(Gf.Quatd(w, x, y, z))
        mpu = asset.geometry.meters_per_unit
        xform.AddScaleOp(UsdGeom.XformOp.PrecisionDouble, "unitsResolve").Set(Gf.Vec3d(mpu, mpu, mpu))
        xform.AddScaleOp(UsdGeom.XformOp.PrecisionDouble, "display").Set(Gf.Vec3d(*instance.display_scale.tolist()))
    return stage


def display_bbox_size(stage, instance_id: str) -> NDArray[np.float64]:
    """World-aligned display bounding-box size of an instance prim in stage units (metres)."""
    from pxr import Usd, UsdGeom

    prim = stage.GetPrimAtPath(f"{SAT_ROOT}/{instance_id}")
    if not prim or not prim.IsValid():
        raise SceneError(f"display stage: no prim at {SAT_ROOT}/{instance_id}")
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    size = cache.ComputeWorldBound(prim).ComputeAlignedRange().GetSize()
    return np.array([size[0], size[1], size[2]], dtype=float)


__all__ = [
    "AssetRecord",
    "CapabilityRecord",
    "DOMAIN_REGISTRIES",
    "EXPOSED_NODES",
    "FACES",
    "GeometryPrim",
    "GeometryRecord",
    "NODE_ORDER",
    "PATH_NODES",
    "PATH_ORDER",
    "POWER_MODEL_REGISTRY",
    "PORT_POWER_ROLES",
    "PortRecord",
    "PowerModelSpec",
    "SAT_ROOT",
    "SHARED_TEMPERATURE_NODES",
    "SceneAssembly",
    "SceneError",
    "SceneInstance",
    "SceneRecord",
    "THERMAL_MODEL_REGISTRY",
    "THERMAL_POWER_PORTS",
    "ThermalModelSpec",
    "UnregisteredModelError",
    "assemble_scene",
    "compose_stage",
    "display_bbox_size",
    "load_asset",
    "load_scene",
    "read_geometry",
]
