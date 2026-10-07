"""Assembly of capacitances, resistances and surface records from assets and the scene (design 4.5 T5, 5.2).

``assemble_thermal_parameters`` resolves explicit scene overrides over the asset values, checks every record,
sums capacitances with the first line of T5, computes solid-path resistances with its second line, takes the
supplied total of a heat-pipe or liquid-cooling equivalent without adding an included contact part again, and
returns a read-only :class:`ThermalParameters` whose provenance records the resolved values, units, asset
revisions, sources and applied overrides. It supplies no default device value and creates no temperature.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np

from .types import (
    EXPOSED_NODES,
    NODE_ORDER,
    PATH_ORDER,
    PORT_NODES,
    UNITS,
    SurfaceRecord,
    ThermalConfigurationError,
    ThermalParameters,
    _identifier,
    _items,
    _nonnegative_float,
    _positive_float,
    _temperature_range,
    _unit_interval,
)

METHOD_CONDUCTION = "conduction_plus_contact"
METHOD_EQUIVALENT = "equivalent_total"

_COMPONENT_REQUIRED = ("instance_id", "node_id", "asset_id", "asset_version", "materials", "temperature_range_K")
_MATERIAL_REQUIRED = ("material_id", "mass_kg", "cp_J_kgK", "source")
_SURFACE_REQUIRED = ("surface_id", "area_m2", "normal_body", "absorptivity", "emissivity", "source")
_CONDUCTION_FIELDS = ("length_m", "conductivity_W_mK", "area_m2")
_CONNECTION_KEYS = frozenset(
    {
        "path",
        "source",
        "length_m",
        "conductivity_W_mK",
        "area_m2",
        "contact_resistance_K_W",
        "equivalent_total_resistance_K_W",
        "includes_contact",
    }
)
_OVERRIDE_KEYS = frozenset({"components", "connections", "source"})
_COMPONENT_OVERRIDE_KEYS = frozenset({"materials", "surfaces", "temperature_range_K"})
_MATERIAL_OVERRIDES = frozenset({"mass_kg", "cp_J_kgK"})
_SURFACE_OVERRIDES = frozenset({"area_m2", "normal_body", "absorptivity", "emissivity"})
_CONNECTION_OVERRIDES = _CONNECTION_KEYS - {"path", "source"}


def assemble_thermal_parameters(
    components: Any, connections: Any, overrides: Mapping[str, Any] | None
) -> ThermalParameters:
    """Assemble ThermalParameters from component assets, the five path connections and scene overrides.

    ``components`` is a sequence of mappings with ``instance_id``, ``node_id``, ``asset_id``,
    ``asset_version``, ``materials`` (``material_id``, ``mass_kg``, ``cp_J_kgK``, ``source``),
    ``temperature_range_K`` ``[min, max]`` and, where present, ``surfaces`` (``surface_id``, ``area_m2``,
    ``normal_body``, ``absorptivity``, ``emissivity``, ``source``) and ``ports`` (the Power ports the instance
    supplies). ``connections`` has one mapping per path, either the solid form ``length_m``,
    ``conductivity_W_mK``, ``area_m2``, ``contact_resistance_K_W`` giving R = l/(k A) + R_contact, or the
    equivalent form ``equivalent_total_resistance_K_W`` with ``includes_contact``. ``overrides`` is
    ``{"components": {instance_id: {"materials": {material_id: {field: value}}, "surfaces": {surface_id:
    {field: value}}, "temperature_range_K": [min, max]}}, "connections": {path: {field: value}}, "source": str}``
    or None; explicit overrides take precedence over asset values. Every error names the offending record.
    """

    component_records = _read_components(components)
    connection_records = _read_connections(connections)
    applied, overridden = _apply_overrides(overrides, component_records, connection_records)

    def where(target: str, label: str, field: str) -> str:
        suffix = " (set by override)" if (target, field) in overridden else ""
        return f"{label}: {field}{suffix}"

    instances: dict[str, list[str]] = {node: [] for node in NODE_ORDER}
    portions: dict[str, list[dict[str, Any]]] = {node: [] for node in NODE_ORDER}
    instance_ranges: dict[str, list[tuple[str, tuple[float, float]]]] = {node: [] for node in NODE_ORDER}
    material_owner: dict[str, str] = {}
    surfaces: list[SurfaceRecord] = []
    surface_provenance: dict[str, dict[str, Any]] = {}
    port_owner: dict[str, str] = {}
    assets: dict[str, dict[str, Any]] = {}

    for component in component_records:
        instance_id = component["instance_id"]
        node = component["node_id"]
        label = f"component {instance_id!r}"
        target = f"components/{instance_id}"
        instances[node].append(instance_id)
        temperature_range = _temperature_range(
            component["temperature_range_K"], where(target, label, "temperature_range_K"), ThermalConfigurationError
        )
        instance_ranges[node].append((instance_id, temperature_range))
        assets[instance_id] = {
            "asset_id": component["asset_id"],
            "asset_version": component["asset_version"],
            "node_id": node,
            "temperature_range_K": temperature_range,
        }

        for material in component["materials"]:
            material_id = material["material_id"]
            if material_id in material_owner:
                owner = material_owner[material_id]
                place = f"twice to {owner!r}" if owner == instance_id else f"to both {owner!r} and {instance_id!r}"
                raise _error(
                    f"material {material_id!r} is assigned {place}; a material portion belongs to one component "
                    "and its mass is counted once (design 4.5)"
                )
            material_owner[material_id] = instance_id
            material_label = f"{label} material {material_id!r}"
            material_target = f"{target}/materials/{material_id}"
            _require_fields(material, _MATERIAL_REQUIRED, material_label)
            mass = _positive_float(
                material["mass_kg"], where(material_target, material_label, "mass_kg"), ThermalConfigurationError
            )
            specific_heat = _positive_float(
                material["cp_J_kgK"], where(material_target, material_label, "cp_J_kgK"), ThermalConfigurationError
            )
            portions[node].append(
                {
                    "instance_id": instance_id,
                    "material_id": material_id,
                    "mass_kg": mass,
                    "cp_J_kgK": specific_heat,
                    "C_J_K": mass * specific_heat,
                    "source": _identifier(material["source"], f"{material_label}: source", ThermalConfigurationError),
                }
            )

        for surface in component["surfaces"]:
            surface_id = surface["surface_id"]
            surface_label = f"{label} surface {surface_id!r}"
            surface_target = f"{target}/surfaces/{surface_id}"
            if node not in EXPOSED_NODES:
                raise _error(
                    f"{surface_label}: the component sits on node {node!r}, but exposed surfaces belong only to "
                    f"{EXPOSED_NODES} (design 4.4)"
                )
            if surface_id in surface_provenance:
                raise _error(
                    f"{surface_label}: surface_id {surface_id!r} is already used by component "
                    f"{surface_provenance[surface_id]['instance_id']!r}; duplicate surfaces are rejected"
                )
            _require_fields(surface, _SURFACE_REQUIRED, surface_label)
            area = _positive_float(
                surface["area_m2"], where(surface_target, surface_label, "area_m2"), ThermalConfigurationError
            )
            absorptivity = _unit_interval(
                surface["absorptivity"], where(surface_target, surface_label, "absorptivity"), ThermalConfigurationError
            )
            emissivity = _unit_interval(
                surface["emissivity"], where(surface_target, surface_label, "emissivity"), ThermalConfigurationError
            )
            try:
                record = SurfaceRecord(surface_id, node, area, surface["normal_body"], absorptivity, emissivity)
            except ThermalConfigurationError as exc:
                suffix = " (normal_body set by override)" if (surface_target, "normal_body") in overridden else ""
                raise _error(f"{label}: {exc}{suffix}") from None
            surfaces.append(record)
            surface_provenance[surface_id] = {
                "instance_id": instance_id,
                "node_id": node,
                "area_m2": area,
                "normal_body": tuple(float(value) for value in record.normal_body),
                "absorptivity": absorptivity,
                "emissivity": emissivity,
                "source": _identifier(surface["source"], f"{surface_label}: source", ThermalConfigurationError),
            }

        for port in component["ports"]:
            if port not in PORT_NODES:
                raise _error(f"{label}: unknown Power port {port!r}; the ports are {tuple(PORT_NODES)}")
            if PORT_NODES[port] != node:
                raise _error(
                    f"{label} supplies {port} but sits on node {node!r}; {port} enters node "
                    f"{PORT_NODES[port]!r} (design 4.3 T3)"
                )
            if port in port_owner:
                raise _error(f"{port} is supplied by both {port_owner[port]!r} and {instance_id!r}")
            port_owner[port] = instance_id

    for node in NODE_ORDER:
        if not instances[node]:
            raise _error(f"node {node!r} has no component instance; every node of {NODE_ORDER} needs one")
        if not portions[node]:
            raise _error(
                f"node {node!r} (instances {instances[node]}) has no material portion; C_{node} needs the masses "
                "and specific heats of T5"
            )
    for node in EXPOSED_NODES:
        if not any(record.node_id == node for record in surfaces):
            raise _error(
                f"node {node!r} (instances {instances[node]}) has no exposed surface; T4 needs its surfaces with "
                "area, normal, absorptivity and emissivity"
            )
    missing_ports = [port for port in PORT_NODES if port not in port_owner]
    if missing_ports:
        raise _error(
            f"Power port(s) {missing_ports} are not supplied by any component; each port must come from one "
            "instance of its node (design 5.1)"
        )

    capacitance_provenance: dict[str, dict[str, Any]] = {}
    capacitance = np.empty(len(NODE_ORDER))
    node_ranges: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(NODE_ORDER):
        value = math.fsum(portion["C_J_K"] for portion in portions[node])
        if not (math.isfinite(value) and value > 0.0):
            raise _error(f"node {node!r}: capacitance {value!r} J/K from T5 is not finite and positive")
        capacitance[index] = value
        capacitance_provenance[node] = {"value_J_K": value, "portions": portions[node]}
        low = max(bounds[0] for _, bounds in instance_ranges[node])
        high = min(bounds[1] for _, bounds in instance_ranges[node])
        if not low < high:
            raise _error(
                f"node {node!r}: the temperature ranges {dict(instance_ranges[node])} of its instances have no "
                "common interval in which the node's constants apply"
            )
        node_ranges[node] = (low, high)

    resistance = np.empty(len(PATH_ORDER))
    resistance_provenance: dict[str, dict[str, Any]] = {}
    for index, path in enumerate(PATH_ORDER):
        value, method, inputs, source = _path_resistance(path, connection_records[path], overridden)
        resistance[index] = value
        resistance_provenance[path] = {"value_K_W": value, "method": method, "inputs": inputs, "source": source}

    instance_map = {
        "nodes": {node: tuple(instances[node]) for node in NODE_ORDER},
        "ports": {port: port_owner[port] for port in PORT_NODES},
    }
    provenance = {
        "node_order": NODE_ORDER,
        "path_order": PATH_ORDER,
        "units": dict(UNITS),
        "capacitance": capacitance_provenance,
        "resistance": resistance_provenance,
        "surfaces": surface_provenance,
        "assets": assets,
        "overrides_applied": applied,
        "temperature_range_K": node_ranges,
    }
    return ThermalParameters(
        C_J_K=capacitance,
        R_K_W=resistance,
        surfaces=tuple(surfaces),
        instance_map=instance_map,
        provenance=provenance,
    )


def _error(message: str) -> ThermalConfigurationError:
    return ThermalConfigurationError(message)


def _require_fields(record: Mapping[str, Any], required: tuple[str, ...], label: str) -> None:
    missing = [key for key in required if key not in record]
    if missing:
        raise _error(f"{label} is missing field(s) {missing}; no default device value is supplied")


def _mapping_list(value: Any, where: str) -> list[Mapping[str, Any]]:
    items = _items(value, where, ThermalConfigurationError)
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise _error(f"{where}[{index}] must be a mapping, got {type(item).__name__}")
    return items


def _read_components(components: Any) -> list[dict[str, Any]]:
    """Copy the component records after checking identity fields, node, materials, surfaces and ports."""

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, item in enumerate(_mapping_list(components, "components")):
        instance_id = _identifier(
            item.get("instance_id"), f"components[{position}].instance_id", ThermalConfigurationError
        )
        label = f"component {instance_id!r}"
        _require_fields(item, _COMPONENT_REQUIRED, label)
        if instance_id in seen:
            raise _error(f"{label} is defined more than once; two instances need distinct instance_id values")
        seen.add(instance_id)
        node = item["node_id"]
        if not isinstance(node, str) or node not in NODE_ORDER:
            raise _error(f"{label}: node_id must be one of {NODE_ORDER}, got {node!r}")
        materials = []
        for index, material in enumerate(_mapping_list(item["materials"], f"{label}: materials")):
            material = dict(material)
            material["material_id"] = _identifier(
                material.get("material_id"), f"{label}: materials[{index}].material_id", ThermalConfigurationError
            )
            materials.append(material)
        surfaces = []
        for index, surface in enumerate(_mapping_list(item.get("surfaces", []), f"{label}: surfaces")):
            surface = dict(surface)
            surface["surface_id"] = _identifier(
                surface.get("surface_id"), f"{label}: surfaces[{index}].surface_id", ThermalConfigurationError
            )
            surfaces.append(surface)
        ports = [
            _identifier(port, f"{label}: ports[{index}]", ThermalConfigurationError)
            for index, port in enumerate(_items(item.get("ports", []), f"{label}: ports", ThermalConfigurationError))
        ]
        records.append(
            {
                "instance_id": instance_id,
                "node_id": str(node),
                "asset_id": _identifier(item["asset_id"], f"{label}: asset_id", ThermalConfigurationError),
                "asset_version": _identifier(
                    item["asset_version"], f"{label}: asset_version", ThermalConfigurationError
                ),
                "materials": materials,
                "surfaces": surfaces,
                "temperature_range_K": item["temperature_range_K"],
                "ports": ports,
            }
        )
    return records


def _read_connections(connections: Any) -> dict[str, dict[str, Any]]:
    """Copy the connection records, requiring each of the five paths exactly once."""

    by_path: dict[str, dict[str, Any]] = {}
    for position, item in enumerate(_mapping_list(connections, "connections")):
        if "path" not in item:
            raise _error(f"connections[{position}] is missing field 'path'")
        path = item["path"]
        if not isinstance(path, str) or path not in PATH_ORDER:
            raise _error(f"connections[{position}]: unknown path {path!r}; the paths are {PATH_ORDER}")
        if path in by_path:
            raise _error(f"connection {path!r} is defined more than once; each path is defined exactly once")
        unknown = sorted(str(key) for key in item if key not in _CONNECTION_KEYS)
        if unknown:
            raise _error(f"connection {path!r} has unknown field(s) {unknown}; allowed are {sorted(_CONNECTION_KEYS)}")
        by_path[path] = dict(item)
    missing = [path for path in PATH_ORDER if path not in by_path]
    if missing:
        raise _error(
            f"connection(s) {missing} are not defined; every path of {PATH_ORDER} needs its conducting structure "
            "or a supported equivalent resistance (design 5.2, 5.5)"
        )
    return by_path


def _plain_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return tuple(value.tolist())
    if isinstance(value, (list, tuple)):
        return tuple(_plain_value(item) for item in value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _override_fields(value: Any, allowed: frozenset[str], target: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"overrides for {target} must map field names to values, got {type(value).__name__}")
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise _error(f"overrides for {target}: field(s) {unknown} cannot be overridden; allowed are {sorted(allowed)}")
    return value


def _apply_overrides(
    overrides: Mapping[str, Any] | None,
    components: list[dict[str, Any]],
    connections: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    """Apply explicit scene overrides in place on the copied records; return the applied list and targets."""

    if overrides is None:
        return [], set()
    if not isinstance(overrides, Mapping):
        raise _error(f"overrides must be a mapping or None, got {type(overrides).__name__}")
    unknown = sorted(str(key) for key in overrides if key not in _OVERRIDE_KEYS)
    if unknown:
        raise _error(f"overrides has unknown key(s) {unknown}; allowed are {sorted(_OVERRIDE_KEYS)}")
    component_overrides = overrides.get("components") or {}
    connection_overrides = overrides.get("connections") or {}
    if not isinstance(component_overrides, Mapping):
        raise _error(f"overrides['components'] must be a mapping, got {type(component_overrides).__name__}")
    if not isinstance(connection_overrides, Mapping):
        raise _error(f"overrides['connections'] must be a mapping, got {type(connection_overrides).__name__}")

    changes: list[tuple[dict[str, Any], str, str, Any]] = []
    by_instance = {component["instance_id"]: component for component in components}
    for instance_id, change in component_overrides.items():
        component = by_instance.get(instance_id)
        if component is None:
            raise _error(f"overrides['components'] names unknown instance {instance_id!r}")
        target = f"components/{instance_id}"
        if not isinstance(change, Mapping):
            raise _error(f"overrides for {target} must be a mapping, got {type(change).__name__}")
        unknown = sorted(str(key) for key in change if key not in _COMPONENT_OVERRIDE_KEYS)
        if unknown:
            raise _error(
                f"overrides for {target}: key(s) {unknown} cannot be overridden; allowed are "
                f"{sorted(_COMPONENT_OVERRIDE_KEYS)}"
            )
        for kind, key, allowed in (
            ("materials", "material_id", _MATERIAL_OVERRIDES),
            ("surfaces", "surface_id", _SURFACE_OVERRIDES),
        ):
            requested = change.get(kind) or {}
            if not isinstance(requested, Mapping):
                raise _error(f"overrides for {target}/{kind} must be a mapping, got {type(requested).__name__}")
            records = {record[key]: record for record in component[kind]}
            for record_id, values in requested.items():
                record = records.get(record_id)
                if record is None:
                    raise _error(f"overrides for {target}/{kind} name unknown {key} {record_id!r}")
                record_target = f"{target}/{kind}/{record_id}"
                for field, value in _override_fields(values, allowed, record_target).items():
                    changes.append((record, record_target, field, value))
        if "temperature_range_K" in change:
            changes.append((component, target, "temperature_range_K", change["temperature_range_K"]))
    for path, values in connection_overrides.items():
        record = connections.get(path)
        if record is None:
            raise _error(f"overrides['connections'] names unknown path {path!r}; the paths are {PATH_ORDER}")
        record_target = f"connections/{path}"
        for field, value in _override_fields(values, _CONNECTION_OVERRIDES, record_target).items():
            changes.append((record, record_target, field, value))

    if not changes:
        return [], set()
    source = _identifier(overrides.get("source"), "overrides['source']", ThermalConfigurationError)
    applied: list[dict[str, Any]] = []
    overridden: set[tuple[str, str]] = set()
    for record, target, field, value in changes:
        applied.append(
            {
                "target": target,
                "field": field,
                "old": _plain_value(record.get(field)),
                "new": _plain_value(value),
                "source": source,
            }
        )
        record[field] = value
        overridden.add((target, field))
    return applied, overridden


def _path_resistance(
    path: str, record: Mapping[str, Any], overridden: set[tuple[str, str]]
) -> tuple[float, str, dict[str, Any], str]:
    """Resistance of one path: T5 second line, or a supplied equivalent total without double contact."""

    label = f"connection {path!r}"
    target = f"connections/{path}"

    def where(field: str) -> str:
        suffix = " (set by override)" if (target, field) in overridden else ""
        return f"{label}: {field}{suffix}"

    _require_fields(record, ("source",), label)
    source = _identifier(record["source"], f"{label}: source", ThermalConfigurationError)
    if "equivalent_total_resistance_K_W" in record:
        mixed = [field for field in _CONDUCTION_FIELDS if field in record]
        if mixed:
            raise _error(
                f"{label} gives equivalent_total_resistance_K_W together with solid-path field(s) {mixed}; "
                "a connection uses one form"
            )
        total = _positive_float(
            record["equivalent_total_resistance_K_W"],
            where("equivalent_total_resistance_K_W"),
            ThermalConfigurationError,
        )
        if "includes_contact" not in record:
            raise _error(
                f"{label} is missing field 'includes_contact'; it states whether the total holds the contact part"
            )
        includes_contact = record["includes_contact"]
        if not isinstance(includes_contact, (bool, np.bool_)):
            raise _error(f"{where('includes_contact')} must be true or false, got {includes_contact!r}")
        if includes_contact:
            if "contact_resistance_K_W" in record:
                raise _error(
                    f"{label}: equivalent_total_resistance_K_W already includes the contact resistance "
                    "(includes_contact is true), so contact_resistance_K_W must not be given; adding it again "
                    "would count the contact part twice (design 4.5)"
                )
            inputs = {"equivalent_total_resistance_K_W": total, "includes_contact": True}
            value = total
        else:
            if "contact_resistance_K_W" not in record:
                raise _error(
                    f"{label}: includes_contact is false, so contact_resistance_K_W of the installation must be "
                    "given; it is not assumed to be zero"
                )
            contact = _nonnegative_float(
                record["contact_resistance_K_W"], where("contact_resistance_K_W"), ThermalConfigurationError
            )
            inputs = {
                "equivalent_total_resistance_K_W": total,
                "includes_contact": False,
                "contact_resistance_K_W": contact,
            }
            value = total + contact
        method = METHOD_EQUIVALENT
    else:
        if "includes_contact" in record:
            raise _error(
                f"{label} gives includes_contact without equivalent_total_resistance_K_W; includes_contact "
                "belongs to the equivalent form"
            )
        _require_fields(record, _CONDUCTION_FIELDS + ("contact_resistance_K_W",), label)
        length = _positive_float(record["length_m"], where("length_m"), ThermalConfigurationError)
        conductivity = _positive_float(
            record["conductivity_W_mK"], where("conductivity_W_mK"), ThermalConfigurationError
        )
        area = _positive_float(record["area_m2"], where("area_m2"), ThermalConfigurationError)
        contact = _nonnegative_float(
            record["contact_resistance_K_W"], where("contact_resistance_K_W"), ThermalConfigurationError
        )
        conduction = length / (conductivity * area)
        value = conduction + contact
        inputs = {
            "length_m": length,
            "conductivity_W_mK": conductivity,
            "area_m2": area,
            "contact_resistance_K_W": contact,
            "conduction_K_W": conduction,
        }
        method = METHOD_CONDUCTION
    if not (math.isfinite(value) and value > 0.0):
        raise _error(f"{label}: resistance {value!r} K/W is not finite and positive")
    return value, method, inputs, source


__all__ = ["METHOD_CONDUCTION", "METHOD_EQUIVALENT", "assemble_thermal_parameters"]
