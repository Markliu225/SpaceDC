"""Pydantic models for state packets and messages. Authoritative per docs/api_spec.md."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

OrbitType = Literal["LEO", "SSO", "MEO", "GEO"]
GpuType = Literal["H100", "H200", "B200", "MI300X"]
Mode = Literal["on_orbit", "ground_only"]
TaskPhase = Literal[
    "idle", "created", "capturing", "inferencing",
    "packaging", "downlink", "delivered",
]


class SatelliteState(BaseModel):
    id: str = "sat-001"
    orbit_type: OrbitType = "LEO"
    lat: float = 0.0
    lon: float = 0.0
    altitude_km: float = 550.0
    # ECI world position in km — kept as a 3-tuple so the Omniverse scene
    # can drop the satellite icon at exactly the propagated point without
    # re-doing the math. None when no propagator has run yet.
    sat_xyz_km: Optional[tuple[float, float, float]] = None
    sunlit: bool = True
    # Normalised solar incidence, 0..1 = max(0, cos(angle between sat→sun
    # and the sub-solar direction)). 0 in eclipse, 1 at solar noon. Drives
    # the satellite-stage Sun light in Kit so the lighting tracks the orbit.
    sun_factor: float = 1.0
    # True on the dawn-dusk Sun-synchronous (terminator) orbit: never eclipsed,
    # panels track the Sun, so the twin keeps the Sun normal to the panels.
    is_dawn_dusk: bool = False
    solar_input_w: float = 0.0
    payload_power_w: float = 0.0
    platform_power_w: float = 0.0
    gpu_type: GpuType = "H100"
    gpu_utilization: float = 0.0
    temperature_c: float = 25.0
    # Battery: SOC (0..1), total capacity (Wh), and instantaneous net power
    # into the battery (positive = charging, negative = discharging).
    battery_soc: float = 0.9
    battery_capacity_wh: float = 1500.0
    battery_charge_w: float = 0.0
    # Heat balance: total radiator emission (W). Stefan-Boltzmann driven —
    # see services / state_engine.
    radiator_power_w: float = 0.0
    # Workload (0..1) drives gpu_utilization; exposed so the UI can show
    # the upstream job pattern, not just the resulting load.
    workload: float = 0.0
    # Standing alarms — short string codes the web maps to localized labels.
    # Empty list while nominal.
    alarms: list[str] = []
    # Design-check numbers — let the user see the physics math behind the
    # alarms, not just the alarm flag. All in real units (W, m²); the popup
    # also derives margin = supply − demand so green/red is unambiguous.
    solar_demand_avg_w: float = 0.0
    solar_supply_avg_w: float = 0.0
    thermal_peak_demand_w: float = 0.0
    thermal_max_emit_w: float = 0.0
    # Deployable-geometry-driven areas (Feature 4) — solar = clusters × 2 sides,
    # radiator = dedicated ±Z panels (2 panels × 2 faces). Drive the power /
    # thermal balance so add/remove + resize change the live numbers.
    solar_area_m2: float = 0.0
    radiator_area_m2: float = 0.0
    downlink_mbps: float = 0.0
    task_state: TaskPhase = "idle"


class GroundStationState(BaseModel):
    id: str = "gs-001"
    visible: bool = False
    rx_mbps: float = 0.0
    queue_depth: int = 0


class TaskState(BaseModel):
    id: str
    type: str = "maritime_detection"
    state: TaskPhase = "idle"
    input_size_mb: float = 0.0
    result_size_mb: float = 0.0
    progress: float = 0.0
    targets: int = 0
    alerts: int = 0


class FleetSnapshot(BaseModel):
    """Aggregate state of the currently-active constellation. Published in
    every state_update so Web's Overview / Kit's renderer can react to the
    preset swap without round-tripping a separate endpoint."""
    constellation_id: str = "single_iss"
    name: str = "ISS (single satellite)"
    total: int = 1
    online: int = 1
    eclipse: int = 0
    standby: int = 0
    offline: int = 0
    planes: int = 1
    sats_per_plane: int = 1
    inclination_deg: float = 51.6
    altitude_km: float = 420.0
    coverage_pct: float = 9.0
    links_total: int = 0
    isl_links: int = 0
    gsl_links: int = 0
    agg_throughput_mbps: float = 60.0


class CompareMetrics(BaseModel):
    mode: Mode = "on_orbit"
    latency_s: float = 0.0
    downlink_mb: float = 0.0
    peak_temp_c: float = 0.0


MissionPhase = Literal[
    "idle", "acquire", "capture", "route", "compute", "downlink", "deliver",
]


class MissionState(BaseModel):
    """Live state of the 天数天算 (compute-in-space) choreography. The phase
    machine advances on a wall-clock timeline in MissionEngine; Kit reads
    the phase + progress + cast indices to drive the 3D data-packet flight."""
    active: bool = False
    phase: MissionPhase = "idle"
    phase_progress: float = 0.0      # 0..1 within current phase
    elapsed_s: float = 0.0           # since capture start; freezes at deliver
    data_volume_mb: float = 0.0      # 5120 at capture, ~2 after inference
    targets_found: int = 0
    sensor_idx: int = -1             # fleet index of the sensing sat
    hub_idx: int = -1                # fleet index of the compute hub
    aoi_lat: float = 38.0
    aoi_lon: float = -145.0
    ground_lat: float = 78.2
    ground_lon: float = 15.4
    ground_id: str = ""


class Parameters(BaseModel):
    orbit_type: Optional[OrbitType] = None
    gpu_type: Optional[GpuType] = None
    load: Optional[Literal["low", "medium", "high"]] = None
    bandwidth_mbps: Optional[float] = None
    inference_mode: Optional[Mode] = None
    sunlit: Optional[bool] = None


SolarMaterial = Literal["Si", "GaAs", "Perovskite"]
SolarSize     = Literal["S", "M", "L", "XL"]
RadiatorMaterial = Literal["Aluminum", "WhitePaint", "OSR", "Graphite"]
RadiatorSize  = Literal["Compact", "Standard", "Wide"]


class SatelliteConfig(BaseModel):
    """Reconfigurable hardware loadout for the tracked satellite. Drives
    both backend physics (solar / payload / thermal recompute) and
    Omniverse VariantSet selection on the Kit side."""
    gpu: GpuType = "H100"
    solar_material: SolarMaterial = "Si"
    solar_size: SolarSize = "M"
    radiator_material: RadiatorMaterial = "Aluminum"
    radiator_size: RadiatorSize = "Standard"


Architecture = Literal["truss", "twin_truss", "blanket", "lumid", "dish"]


class TwinGeometry(BaseModel):
    """Deployable-geometry knobs that drive the regenerated USD model
    (tools/gen_twin_satellite.py via usd/twin_params.json) AND the physics
    areas. `architecture` selects the hull CONFIGURATION (single truss /
    stacked twin truss / ribbon-wing truss / LUMID smallsat / dish comms
    hull); `solar_clusters_per_side` is the number of wing segments (ignored
    by the hull architectures, whose panels are integrated); `radiator_long`
    / `radiator_ratio` size and shape the two radiator panels. `version`
    bumps on every change so Kit can reload the regenerated layer."""
    architecture: Architecture = "truss"
    solar_clusters_per_side: int = 2
    radiator_long: float = 1.55
    radiator_ratio: float = 2.5
    version: int = 0


class Envelope(BaseModel):
    type: str
    ts: float
    payload: dict[str, Any] = Field(default_factory=dict)
    request_id: Optional[str] = None


class StatePacket(BaseModel):
    sim_time_s: float
    satellite: SatelliteState
    ground_station: GroundStationState
    constellation: FleetSnapshot = Field(default_factory=FleetSnapshot)
    task: Optional[TaskState] = None
    compare: Optional[CompareMetrics] = None
    camera_preset: str = "overview"
    running: bool = True
    satellite_config: SatelliteConfig = Field(default_factory=SatelliteConfig)
    twin_geometry: TwinGeometry = Field(default_factory=TwinGeometry)
    mission: MissionState = Field(default_factory=MissionState)
    # Active design preset id (design_presets.py) — "custom" at boot and
    # after any manual config/geometry edit — plus the workload profile the
    # GPUs are running.
    design_id: str = "custom"
    workload_profile: str = "balanced"
