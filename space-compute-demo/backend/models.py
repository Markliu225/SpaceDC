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
    solar_input_w: float = 0.0
    payload_power_w: float = 0.0
    platform_power_w: float = 0.0
    gpu_type: GpuType = "H100"
    gpu_utilization: float = 0.0
    temperature_c: float = 25.0
    battery_soc: float = 0.9
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
    mission: MissionState = Field(default_factory=MissionState)
