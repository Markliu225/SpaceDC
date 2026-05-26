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
    SatelliteConfig,
    SatelliteState,
    StatePacket,
    TaskState,
)
from services import orbit_catalog
from services import constellations as _consts

TICK_HZ = 1.0

# Reconfigurable hardware tables — values mirror docs/satellite_twin_implementation.md §3
# and web/src/data/satConfigOptions.ts so the backend physics, Web optimistic
# UI, and USD VariantSet selections all agree on the same numbers.

_GPU_TABLE: dict[str, dict[str, float]] = {
    "H100":   {"pflops": 0.98, "tdp_w": 700.0,  "cost_k": 30.0},
    "H200":   {"pflops": 1.50, "tdp_w": 700.0,  "cost_k": 40.0},
    "B200":   {"pflops": 2.50, "tdp_w": 1000.0, "cost_k": 45.0},
    "MI300X": {"pflops": 1.30, "tdp_w": 750.0,  "cost_k": 28.0},
}
_GPU_CARDS_PER_SAT = 8

_SOLAR_MAT_TABLE = {
    "Si":         {"efficiency": 0.22, "density_kg_m2": 2.5},
    "GaAs":       {"efficiency": 0.32, "density_kg_m2": 3.0},
    "Perovskite": {"efficiency": 0.38, "density_kg_m2": 1.8},
}
_SOLAR_SIZE_TABLE = {
    "S":  {"area_m2_per_panel": 4.0,  "panel_count": 2},
    "M":  {"area_m2_per_panel": 8.0,  "panel_count": 2},
    "L":  {"area_m2_per_panel": 12.0, "panel_count": 2},
    "XL": {"area_m2_per_panel": 16.0, "panel_count": 4},
}

_RAD_MAT_TABLE = {
    "Aluminum":   {"emissivity": 0.10, "density_kg_m2": 4.0},
    "WhitePaint": {"emissivity": 0.85, "density_kg_m2": 4.4},
    "OSR":        {"emissivity": 0.92, "density_kg_m2": 4.6},
    "Graphite":   {"emissivity": 0.96, "density_kg_m2": 3.6},
}
_RAD_SIZE_TABLE = {
    "Compact":  {"area_m2_per_panel": 1.0},
    "Standard": {"area_m2_per_panel": 2.0},
    "Wide":     {"area_m2_per_panel": 4.0},
}
_RAD_PANELS_PER_SAT = 2

_SOLAR_CONSTANT_W_M2 = 1361.0


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
        # Reconfigurable hardware loadout — Twin page mutates via set_config.
        self._config: SatelliteConfig = SatelliteConfig()

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

    def set_config(self, patch: dict[str, Any]) -> SatelliteConfig:
        """Merge a partial hardware loadout into the active config. Returns
        the new full config so the handler can echo it back. Unknown keys
        are ignored; bad values raise the underlying Pydantic ValidationError."""
        cleaned = {k: v for k, v in patch.items() if v is not None}
        self._config = self._config.model_copy(update=cleaned)
        # Pydantic re-validates via model_validate to ensure literals are
        # actually one of the allowed enum strings (model_copy alone does not).
        self._config = SatelliteConfig.model_validate(self._config.model_dump())
        return self._config

    @property
    def satellite_config(self) -> SatelliteConfig:
        return self._config

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
            satellite_config=self._config.model_copy(),
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

        # --- Reconfigurable hardware lookups ----------------------------------
        cfg     = self._config
        gpu     = _GPU_TABLE.get(cfg.gpu,                _GPU_TABLE["H100"])
        s_mat   = _SOLAR_MAT_TABLE.get(cfg.solar_material,     _SOLAR_MAT_TABLE["Si"])
        s_size  = _SOLAR_SIZE_TABLE.get(cfg.solar_size,        _SOLAR_SIZE_TABLE["M"])
        r_mat   = _RAD_MAT_TABLE.get(cfg.radiator_material,    _RAD_MAT_TABLE["Aluminum"])
        r_size  = _RAD_SIZE_TABLE.get(cfg.radiator_size,       _RAD_SIZE_TABLE["Standard"])

        # Solar input depends on material × size × incidence × sunlit flag.
        # cos_a above is the dot of sat-position-unit with sun direction, which
        # ranges roughly -1..1; we clamp the negative side to 0 for incidence.
        incidence = max(0.0, cos_a) if self._sat.sunlit else 0.0
        self._sat.solar_input_w = (
            s_mat["efficiency"]
            * s_size["area_m2_per_panel"]
            * s_size["panel_count"]
            * _SOLAR_CONSTANT_W_M2
            * incidence
        )

        # --- Power / thermal / battery / downlink -----------------------------
        load = 0.15 + 0.35 * (0.5 + 0.5 * math.sin(t / 20.0))
        self._sat.gpu_utilization = load
        # Payload draw now scales with GPU TDP × card count × utilization.
        self._sat.payload_power_w = gpu["tdp_w"] * _GPU_CARDS_PER_SAT * load
        self._sat.platform_power_w = 600.0
        # Thermal target uses the linear surrogate from the doc: lower
        # emissivity × area => higher steady-state temperature.
        radiator_capacity = max(
            0.05,
            r_mat["emissivity"] * _RAD_PANELS_PER_SAT * r_size["area_m2_per_panel"],
        )
        target = 28.0 + (50.0 * load) / radiator_capacity
        self._sat.temperature_c += (target - self._sat.temperature_c) * 0.1
        net = self._sat.solar_input_w - self._sat.payload_power_w - self._sat.platform_power_w
        self._sat.battery_soc = max(0.0, min(1.0, self._sat.battery_soc + net * dt / 3.6e7))
        self._gs.visible = math.sin(t / 30.0) > 0.4
        self._sat.downlink_mbps = 120.0 if self._gs.visible else 0.0
        self._gs.rx_mbps = self._sat.downlink_mbps
        self._sat.gpu_type = cfg.gpu  # echo for the legacy 14-param card


async def _maybe_await(x: Any) -> None:
    if asyncio.iscoroutine(x):
        await x
