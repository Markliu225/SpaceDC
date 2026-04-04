"""
============================================================
  business_network.py - Business-to-compute orchestration helpers
============================================================

  Defines:
    - extensible business workload profiles
    - per-business-satellite workload assignment state
    - line-of-sight visibility checks
    - lightweight demand routing from business satellites to compute nodes
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .constellation import EARTH_RADIUS_KM, propagate_tle_km


@dataclass(frozen=True)
class BusinessWorkloadProfile:
    key: str
    name: str
    description: str
    demand_units: float
    color: tuple[float, float, float]


BUSINESS_WORKLOADS: dict[str, BusinessWorkloadProfile] = {
    "imagery_batch": BusinessWorkloadProfile(
        key="imagery_batch",
        name="Imagery Batch AI",
        description="Optical imagery enhancement and cloud filtering.",
        demand_units=1.8,
        color=(0.15, 0.72, 1.00),
    ),
    "sar_change": BusinessWorkloadProfile(
        key="sar_change",
        name="SAR Change Detection",
        description="On-orbit SAR change-detection and anomaly extraction.",
        demand_units=2.6,
        color=(1.00, 0.58, 0.10),
    ),
    "maritime_fusion": BusinessWorkloadProfile(
        key="maritime_fusion",
        name="Maritime Fusion",
        description="AIS fusion, vessel intent modeling, and alerting.",
        demand_units=1.2,
        color=(0.15, 0.98, 0.62),
    ),
    "emergency_mapping": BusinessWorkloadProfile(
        key="emergency_mapping",
        name="Emergency Mapping",
        description="Rapid disaster mapping and prioritised tasking.",
        demand_units=3.2,
        color=(1.00, 0.20, 0.28),
    ),
}

DEFAULT_BUSINESS_WORKLOAD_KEY = "imagery_batch"
COMPUTE_NODE_CAPACITY_UNITS = 4.0
EARTH_OCCLUSION_MARGIN_KM = 0.0


@dataclass
class BusinessSatelliteConfig:
    catalog_number: str
    workload_key: str
    enabled: bool = True

    @property
    def workload(self) -> BusinessWorkloadProfile:
        return BUSINESS_WORKLOADS[self.workload_key]


@dataclass(frozen=True)
class DemandAssignment:
    business_catalog_number: str
    compute_catalog_number: str
    workload_key: str
    distance_km: float
    demand_units: float


@dataclass
class ComputeNodeState:
    catalog_number: str
    assigned_business: list[str] = field(default_factory=list)
    load_units: float = 0.0
    utilization: float = 0.0
    state: str = "idle"


def default_business_configs(constellation, workload_key: str = DEFAULT_BUSINESS_WORKLOAD_KEY) -> dict[str, BusinessSatelliteConfig]:
    if workload_key not in BUSINESS_WORKLOADS:
        workload_key = DEFAULT_BUSINESS_WORKLOAD_KEY
    if not constellation:
        return {}
    return {
        sat.catalog_number: BusinessSatelliteConfig(
            catalog_number=sat.catalog_number,
            workload_key=workload_key,
        )
        for sat in constellation.satellites
        if sat.catalog_number
    }


def set_business_workload(
    configs: dict[str, BusinessSatelliteConfig],
    catalog_number: str,
    workload_key: str,
) -> dict[str, BusinessSatelliteConfig]:
    sat_id = str(catalog_number or "").strip()
    if not sat_id or workload_key not in BUSINESS_WORKLOADS:
        return dict(configs)
    updated = dict(configs)
    updated[sat_id] = BusinessSatelliteConfig(
        catalog_number=sat_id,
        workload_key=workload_key,
        enabled=True,
    )
    return updated


def clear_business_workload(
    configs: dict[str, BusinessSatelliteConfig],
    catalog_number: str,
) -> dict[str, BusinessSatelliteConfig]:
    sat_id = str(catalog_number or "").strip()
    if not sat_id:
        return dict(configs)
    updated = dict(configs)
    updated.pop(sat_id, None)
    return updated


def _distance_km(position_a: tuple[float, float, float], position_b: tuple[float, float, float]) -> float:
    dx = position_b[0] - position_a[0]
    dy = position_b[1] - position_a[1]
    dz = position_b[2] - position_a[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def has_line_of_sight_km(
    position_a: tuple[float, float, float],
    position_b: tuple[float, float, float],
    earth_radius_km: float = EARTH_RADIUS_KM,
    margin_km: float = EARTH_OCCLUSION_MARGIN_KM,
) -> bool:
    ax, ay, az = position_a
    bx, by, bz = position_b
    dx, dy, dz = (bx - ax, by - ay, bz - az)
    denom = dx * dx + dy * dy + dz * dz
    if denom <= 1e-9:
        return False

    t = -(ax * dx + ay * dy + az * dz) / denom
    t = max(0.0, min(1.0, t))
    closest_x = ax + t * dx
    closest_y = ay + t * dy
    closest_z = az + t * dz
    closest_radius = math.sqrt(
        closest_x * closest_x +
        closest_y * closest_y +
        closest_z * closest_z
    )
    return closest_radius > earth_radius_km + margin_km


def analyze_business_demands(
    business_constellation,
    business_configs: dict[str, BusinessSatelliteConfig],
    compute_constellation,
    when_utc,
    capacity_units: float = COMPUTE_NODE_CAPACITY_UNITS,
) -> tuple[list[DemandAssignment], dict[str, ComputeNodeState]]:
    assignments: list[DemandAssignment] = []
    compute_states: dict[str, ComputeNodeState] = {}

    if compute_constellation:
        compute_states = {
            sat.catalog_number: ComputeNodeState(catalog_number=sat.catalog_number)
            for sat in compute_constellation.satellites
            if sat.catalog_number
        }

    if not business_constellation or not compute_constellation:
        return assignments, compute_states

    compute_positions = {
        sat.catalog_number: propagate_tle_km(sat, when_utc)
        for sat in compute_constellation.satellites
        if sat.catalog_number
    }

    for business_sat in business_constellation.satellites:
        sat_id = business_sat.catalog_number
        if not sat_id:
            continue
        config = business_configs.get(sat_id)
        if not config or not config.enabled or config.workload_key not in BUSINESS_WORKLOADS:
            continue

        workload = BUSINESS_WORKLOADS[config.workload_key]
        business_position = propagate_tle_km(business_sat, when_utc)
        visible_candidates: list[tuple[float, float, str]] = []

        for compute_sat in compute_constellation.satellites:
            compute_id = compute_sat.catalog_number
            if not compute_id:
                continue
            compute_position = compute_positions.get(compute_id)
            if not compute_position:
                continue
            if not has_line_of_sight_km(business_position, compute_position):
                continue
            distance_km = _distance_km(business_position, compute_position)
            current_load = compute_states[compute_id].load_units
            visible_candidates.append((current_load, distance_km, compute_id))

        if not visible_candidates:
            continue

        visible_candidates.sort(key=lambda item: (item[0], item[1]))
        _load, distance_km, chosen_compute_id = visible_candidates[0]
        chosen_state = compute_states[chosen_compute_id]
        chosen_state.assigned_business.append(sat_id)
        chosen_state.load_units += workload.demand_units
        assignments.append(
            DemandAssignment(
                business_catalog_number=sat_id,
                compute_catalog_number=chosen_compute_id,
                workload_key=workload.key,
                distance_km=distance_km,
                demand_units=workload.demand_units,
            )
        )

    for state in compute_states.values():
        state.utilization = 0.0 if capacity_units <= 0.0 else state.load_units / capacity_units
        if state.utilization >= 1.0:
            state.state = "overloaded"
        elif state.load_units > 0.0:
            state.state = "busy"
        else:
            state.state = "idle"

    return assignments, compute_states


def business_available_text(constellation, configs: dict[str, BusinessSatelliteConfig], limit: int = 6) -> str:
    if not constellation or not constellation.satellites:
        return "Load a business-satellite TLE to configure services."
    labels: list[str] = []
    for sat in constellation.satellites[:limit]:
        config = configs.get(sat.catalog_number)
        workload_name = BUSINESS_WORKLOADS[config.workload_key].name if config and config.workload_key in BUSINESS_WORKLOADS else "Unassigned"
        labels.append(f"{sat.catalog_number}:{workload_name}")
    suffix = " ..." if len(constellation.satellites) > limit else ""
    return "Business: " + ", ".join(labels) + suffix


def business_assignment_text(
    assignments: list[DemandAssignment],
    business_constellation,
    compute_constellation,
    limit: int = 5,
) -> str:
    if not assignments:
        return "No active business demand links."

    business_lookup = business_constellation.by_catalog_number if business_constellation else {}
    compute_lookup = compute_constellation.by_catalog_number if compute_constellation else {}
    rows: list[str] = []
    for assignment in assignments[:limit]:
        biz = business_lookup.get(assignment.business_catalog_number)
        comp = compute_lookup.get(assignment.compute_catalog_number)
        workload = BUSINESS_WORKLOADS.get(assignment.workload_key)
        biz_name = biz.name if biz else assignment.business_catalog_number
        comp_name = comp.name if comp else assignment.compute_catalog_number
        workload_name = workload.name if workload else assignment.workload_key
        rows.append(f"{biz_name} -> {comp_name} ({workload_name})")
    if len(assignments) > limit:
        rows.append(f"... +{len(assignments) - limit} more")
    return " | ".join(rows)


def compute_status_text(compute_states: dict[str, ComputeNodeState], compute_constellation, limit: int = 5) -> str:
    if not compute_states:
        return "Compute constellation unavailable."
    compute_lookup = compute_constellation.by_catalog_number if compute_constellation else {}
    busy_rows: list[str] = []
    for state in compute_states.values():
        if state.load_units <= 0.0:
            continue
        sat = compute_lookup.get(state.catalog_number)
        name = sat.name if sat else state.catalog_number
        busy_rows.append(f"{name}:{state.state} {state.utilization * 100:.0f}%")
    if not busy_rows:
        return "All compute satellites idle."
    if len(busy_rows) > limit:
        busy_rows = busy_rows[:limit] + [f"... +{len(compute_states) - limit} nodes"]
    return " | ".join(busy_rows)
