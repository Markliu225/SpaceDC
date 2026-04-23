"""StateEngine — single source of business truth.

Phase 1: placeholder numerics (sinusoidal/linear), no real physics.
Phase 2+: physics/ modules migrated from exts/spacedc.digital_twin will plug in here.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Callable, Optional

from models import (
    GroundStationState,
    Mode,
    Parameters,
    SatelliteState,
    StatePacket,
    TaskState,
)

TICK_HZ = 1.0


class StateEngine:
    def __init__(self, on_state: Callable[[StatePacket], Any]):
        self._on_state = on_state
        self._sim_time_s: float = 0.0
        self._running: bool = False
        self._sat = SatelliteState()
        self._gs = GroundStationState()
        self._task: Optional[TaskState] = None
        self._mode: Mode = "on_orbit"
        self._params = Parameters()
        self._camera_preset: str = "overview"
        self._task_loop: Optional[asyncio.Task] = None

    # ---- lifecycle ----
    async def start(self) -> None:
        if self._task_loop is None:
            self._running = True
            self._task_loop = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task_loop is not None:
            self._task_loop.cancel()
            try:
                await self._task_loop
            except asyncio.CancelledError:
                pass
            self._task_loop = None

    # ---- commands ----
    def play(self) -> None:
        self._running = True

    def pause(self) -> None:
        self._running = False

    def reset(self) -> None:
        self._sim_time_s = 0.0
        self._sat = SatelliteState()
        self._gs = GroundStationState()
        self._task = None

    def set_time(self, sim_time_s: float) -> None:
        self._sim_time_s = max(0.0, float(sim_time_s))

    def set_parameters(self, params: dict[str, Any]) -> None:
        self._params = self._params.model_copy(update={
            k: v for k, v in params.items() if v is not None
        })
        if self._params.gpu_type:
            self._sat.gpu_type = self._params.gpu_type
        if self._params.orbit_type:
            self._sat.orbit_type = self._params.orbit_type

    def set_mode(self, mode: Mode) -> None:
        self._mode = mode

    def set_camera_preset(self, preset: str) -> None:
        self._camera_preset = preset

    def start_task(self, case_id: str) -> TaskState:
        self._task = TaskState(
            id=f"task-{int(time.time())}",
            type="maritime_detection",
            state="created",
            input_size_mb=5120.0,
        )
        return self._task

    # ---- snapshot ----
    def snapshot(self) -> StatePacket:
        return StatePacket(
            sim_time_s=self._sim_time_s,
            satellite=self._sat.model_copy(),
            ground_station=self._gs.model_copy(),
            task=self._task.model_copy() if self._task else None,
            camera_preset=self._camera_preset,
            running=self._running,
        )

    # ---- inner loop ----
    async def _run(self) -> None:
        dt = 1.0 / TICK_HZ
        while True:
            await asyncio.sleep(dt)
            if self._running:
                self._sim_time_s += dt
                self._update_placeholder_physics(dt)
                try:
                    await _maybe_await(self._on_state(self.snapshot()))
                except Exception:
                    pass

    # ---- orbit parameters (shared with Kit scene for visualization) ----
    ORBIT_PERIOD_S = 90.0       # demo period (wall seconds per revolution)
    ORBIT_INCLINATION_DEG = 60  # circular orbit inclination
    ORBIT_ALT_KM = 550.0

    def _update_placeholder_physics(self, dt: float) -> None:
        t = self._sim_time_s
        # Circular orbit: angle theta advances linearly; position on a tilted plane.
        # Parameterization: u = (1, 0, 0), v = (0, cos(a), sin(a)) with inclination a.
        # world = R*(cos(th), sin(th)*cos(a), sin(th)*sin(a))
        omega = 2.0 * math.pi / self.ORBIT_PERIOD_S
        theta = omega * t
        cos_a = math.cos(math.radians(self.ORBIT_INCLINATION_DEG))
        sin_a = math.sin(math.radians(self.ORBIT_INCLINATION_DEG))
        # Unit sphere position; Kit multiplies by (earth_radius + alt).
        pos_x = math.cos(theta)
        pos_y = math.sin(theta) * cos_a
        pos_z = math.sin(theta) * sin_a
        self._sat.lat = math.degrees(math.asin(pos_z))
        self._sat.lon = math.degrees(math.atan2(pos_y, pos_x))
        # Sunlit: simple — lit when pos_x (facing +X where sun is) is positive-ish.
        self._sat.sunlit = pos_x > -0.3
        self._sat.solar_input_w = 4200.0 if self._sat.sunlit else 0.0
        # GPU load sinusoidal
        load = 0.15 + 0.35 * (0.5 + 0.5 * math.sin(t / 20.0))
        self._sat.gpu_utilization = load
        self._sat.payload_power_w = 400.0 + 1800.0 * load
        self._sat.platform_power_w = 600.0
        # Temperature first-order toward load-driven target
        target = 30.0 + 45.0 * load
        self._sat.temperature_c += (target - self._sat.temperature_c) * 0.1
        # Battery
        net = self._sat.solar_input_w - self._sat.payload_power_w - self._sat.platform_power_w
        self._sat.battery_soc = max(0.0, min(1.0, self._sat.battery_soc + net * dt / 3.6e7))
        # Ground visibility: toy 30%% of the time
        self._gs.visible = math.sin(t / 30.0) > 0.4
        self._sat.downlink_mbps = 120.0 if self._gs.visible else 0.0
        self._gs.rx_mbps = self._sat.downlink_mbps


async def _maybe_await(x: Any) -> None:
    if asyncio.iscoroutine(x):
        await x
