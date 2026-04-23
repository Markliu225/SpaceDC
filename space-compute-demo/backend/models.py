"""Pydantic models for state packets and messages. Authoritative per docs/api_spec.md."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

OrbitType = Literal["LEO", "SSO"]
GpuType = Literal["H100", "H200", "B200", "MI300X"]
Mode = Literal["on_orbit", "ground_only"]
TaskPhase = Literal[
    "idle", "created", "capturing", "inferencing",
    "packaging", "downlink", "delivered",
]


class SatelliteState(BaseModel):
    id: str = "sat-001"
    orbit_type: OrbitType = "SSO"
    lat: float = 0.0
    lon: float = 0.0
    altitude_km: float = 550.0
    sunlit: bool = True
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


class CompareMetrics(BaseModel):
    mode: Mode = "on_orbit"
    latency_s: float = 0.0
    downlink_mb: float = 0.0
    peak_temp_c: float = 0.0


class Parameters(BaseModel):
    orbit_type: Optional[OrbitType] = None
    gpu_type: Optional[GpuType] = None
    load: Optional[Literal["low", "medium", "high"]] = None
    bandwidth_mbps: Optional[float] = None
    inference_mode: Optional[Mode] = None
    sunlit: Optional[bool] = None


class Envelope(BaseModel):
    type: str
    ts: float
    payload: dict[str, Any] = Field(default_factory=dict)
    request_id: Optional[str] = None


class StatePacket(BaseModel):
    sim_time_s: float
    satellite: SatelliteState
    ground_station: GroundStationState
    task: Optional[TaskState] = None
    compare: Optional[CompareMetrics] = None
    camera_preset: str = "overview"
    running: bool = True
