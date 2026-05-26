"""StateEngine — single source of business truth.

Orbit kinematics now go through services.orbit_catalog (SGP4 propagation of
real published TLEs). Power / thermal / battery / downlink remain the toy
sinusoidal model from Phase 1 — those will be replaced piecewise in later
phases without disturbing the orbit layer.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Callable, Optional

from models import (
    FleetSnapshot,
    GroundStationState,
    Mode,
    Parameters,
    SatelliteState,
    StatePacket,
    TaskState,
)
from services import orbit_catalog
from services import constellations as _consts

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
        # Active constellation preset id; default boots into the single-sat
        # ISS preset so behaviour matches the pre-constellation baseline.
        self._constellation_id: str = "single_iss"
        self._fleet_snapshot: FleetSnapshot = FleetSnapshot()

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

    def set_constellation(self, preset_id: str) -> bool:
        """Switch the active constellation. Triggers fleet rebuild on next tick.
        Returns False if the preset id is unknown."""
        if _consts.get_preset(preset_id) is None:
            return False
        self._constellation_id = preset_id
        return True

    @property
    def constellation_id(self) -> str:
        return self._constellation_id

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
            constellation=self._fleet_snapshot.model_copy(),
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

    def _update_placeholder_physics(self, dt: float) -> None:
        t = self._sim_time_s

        # --- Fleet: SGP4 propagate every sat of the active constellation.
        # The "tracked" SatelliteState (the legacy single-sat fields) tracks
        # the constellation's reference satellite (plane 0, sat 0) so the
        # 14-param card on Web stays meaningful. The aggregate FleetSnapshot
        # comes from the full fleet.
        preset = _consts.get_preset(self._constellation_id) or _consts.get_preset("single_iss")
        fleet_pos_km = _consts.propagate_fleet(preset, t)
        kpis = _consts.synthesize_kpis(preset, fleet_pos_km)
        self._fleet_snapshot = FleetSnapshot(
            constellation_id=preset.id,
            name=preset.name,
            total=kpis["total"],
            online=kpis["online"],
            eclipse=kpis["eclipse"],
            standby=kpis["standby"],
            offline=kpis["offline"],
            planes=preset.planes,
            sats_per_plane=preset.sats_per_plane,
            inclination_deg=preset.inclination_deg,
            altitude_km=preset.altitude_km,
            coverage_pct=kpis["coverage_pct"],
            links_total=kpis["links_total"],
            isl_links=kpis["isl_links"],
            gsl_links=kpis["gsl_links"],
            agg_throughput_mbps=kpis["agg_throughput_mbps"],
        )

        # Tracked satellite: plane 0, sat 0.
        x_km, y_km, z_km = fleet_pos_km[0] if fleet_pos_km else (0.0, 0.0, 0.0)
        self._sat.sat_xyz_km = (x_km, y_km, z_km)
        lat, lon, alt = orbit_catalog.eci_to_lat_lon_alt(x_km, y_km, z_km, t)
        self._sat.lat = lat
        self._sat.lon = lon
        self._sat.altitude_km = alt

        # Sunlit: in scene the sun direction is fixed in inertial frame at
        # azimuth -45° / elevation +23.5°. The satellite is in sunlight when
        # its position dotted with the sun direction is positive.
        sun_dx, sun_dy, sun_dz = 0.648, -0.648, 0.398
        r_norm = max(1e-6, math.sqrt(x_km * x_km + y_km * y_km + z_km * z_km))
        cos_a = (x_km * sun_dx + y_km * sun_dy + z_km * sun_dz) / r_norm
        self._sat.sunlit = cos_a > -0.05  # tiny dawn/dusk margin
        self._sat.solar_input_w = 4200.0 if self._sat.sunlit else 0.0

        # --- Power / thermal / battery / downlink (placeholder, unchanged) -
        load = 0.15 + 0.35 * (0.5 + 0.5 * math.sin(t / 20.0))
        self._sat.gpu_utilization = load
        self._sat.payload_power_w = 400.0 + 1800.0 * load
        self._sat.platform_power_w = 600.0
        target = 30.0 + 45.0 * load
        self._sat.temperature_c += (target - self._sat.temperature_c) * 0.1
        net = self._sat.solar_input_w - self._sat.payload_power_w - self._sat.platform_power_w
        self._sat.battery_soc = max(0.0, min(1.0, self._sat.battery_soc + net * dt / 3.6e7))
        self._gs.visible = math.sin(t / 30.0) > 0.4
        self._sat.downlink_mbps = 120.0 if self._gs.visible else 0.0
        self._gs.rx_mbps = self._sat.downlink_mbps


async def _maybe_await(x: Any) -> None:
    if asyncio.iscoroutine(x):
        await x
