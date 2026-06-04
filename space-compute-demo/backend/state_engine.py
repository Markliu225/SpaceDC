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
    MissionState,
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

# ---------------------------------------------------------------------------
# 天数天算 mission choreography — phase plan mirrors web/src/data/missionPlan.ts
# so the Phase-1 mock and this backend produce identical beats. Durations are
# wall-clock animation seconds (not sim-scaled) so the story is legible.
# ---------------------------------------------------------------------------
_MISSION_PHASES: list[tuple[str, float]] = [
    ("acquire", 3.0),    # brief establishing beat on the freshly-loaded city
    ("capture", 30.0),   # slow camera sweep (~24s) then collapse to a cube (~6s)
    ("route", 5.0),
    ("compute", 6.0),
    ("downlink", 4.0),
    ("deliver", 3.0),
]
_MISSION_TOTAL_S = sum(d for _, d in _MISSION_PHASES)
# Load gate — after Start the timeline HOLDS on 'acquire' (scene loading,
# black is fine) until Kit signals the target scene geometry is resident via
# mission_scene_ready(). This fallback caps the wait if that signal never
# arrives (e.g. Kit not running) so the demo can never hang on a black frame.
_MISSION_LOAD_TIMEOUT_S = 45.0
_MISSION_RAW_MB = 5120.0
_MISSION_RESULT_MB = 2.0
_MISSION_TARGETS = 7
_AOI_LAT, _AOI_LON = 38.0, -145.0
_GROUND_STATIONS = [
    ("GS-SVALBARD", 78.2, 15.4),
    ("GS-REYKJAVIK", 64.1, -21.9),
    ("GS-GUAM", 13.4, 144.8),
]


def _ang_dist(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle angular distance (radians) between two lat/lon (deg)."""
    a1, a2 = math.radians(lat_a), math.radians(lat_b)
    dlon = math.radians(lon_b - lon_a)
    cosd = math.sin(a1) * math.sin(a2) + math.cos(a1) * math.cos(a2) * math.cos(dlon)
    return math.acos(max(-1.0, min(1.0, cosd)))

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


# Deterministic compute-job schedule. (start_s, duration_s, util_target).
# This is the GPU's queue — a fixed sequence of inference / training /
# downlink-preprocessing jobs that repeats every JOB_CYCLE_S. No sinusoid,
# no mod-based step folding: each tuple is one concrete job arriving at
# its scheduled sim time and holding the GPUs at a target utilization for
# its duration. The schedule is hand-picked to cover idle gaps, sustained
# medium load, and short peak bursts the way a real maritime-detection
# pipeline would (target-of-interest spikes vs steady inference batches).
_JOB_SCHEDULE: list[tuple[float, float, float]] = [
    (  0.0,  18.0, 0.10),   # cold boot — housekeeping idle
    ( 18.0,  42.0, 0.65),   # batch inference on imagery
    ( 60.0,  18.0, 0.92),   # target acquired — burst classification
    ( 78.0,  36.0, 0.75),   # continued tracking
    (114.0,  24.0, 0.20),   # downlinking results, GPU mostly idle
    (138.0,  60.0, 0.55),   # medium training batch
    (198.0,  48.0, 0.85),   # heavy compute run
    (246.0,  30.0, 0.30),   # cooldown gap
    (276.0,  72.0, 0.70),   # sustained mid-high
    (348.0,  18.0, 0.95),   # peak burst — emergency re-classify
    (366.0,  34.0, 0.40),   # decaying back to idle
]
_JOB_CYCLE_S = 400.0


def _gpu_workload_util(t: float) -> float:
    """Walk the fixed _JOB_SCHEDULE — NOT a sinusoid, NOT a mod-folded step
    wave. At sim time t we wrap into the schedule's cycle and pick the
    single active job's target utilization, falling back to a 0.05 idle
    floor if t lands in a gap. The schedule is hand-authored so config
    changes (GPU model, panel size, etc.) interact with a *consistent*
    workload trace and the user sees their design choice as the only
    moving variable."""
    ct = t % _JOB_CYCLE_S
    for start, dur, u in _JOB_SCHEDULE:
        if start <= ct < start + dur:
            return u
    return 0.05


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
        # 天数天算 mission — phase machine on a wall-clock timeline. The clock
        # (_mission_start_wall) only starts once the scene is loaded; until
        # then the mission holds on 'acquire'. _mission_request_wall marks when
        # Start was pressed so the load gate can time out.
        self._mission: MissionState = MissionState()
        self._mission_start_wall: Optional[float] = None
        self._mission_request_wall: Optional[float] = None
        # Cached fleet lat/lon (computed each tick) for mission cast picking.
        self._fleet_latlon: list[tuple[float, float]] = []

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

    # ---- 天数天算 mission ----
    def start_mission(self) -> MissionState:
        """Kick the compute-in-space choreography: assign cast (sensor =
        fleet sat nearest AOI, hub = idx 0, ground = nearest GS to hub) and
        start the wall-clock phase machine."""
        sensor_idx, hub_idx, gs = self._assign_cast()
        self._mission = MissionState(
            active=True,
            phase="acquire",
            phase_progress=0.0,
            elapsed_s=0.0,
            data_volume_mb=0.0,
            targets_found=0,
            sensor_idx=sensor_idx,
            hub_idx=hub_idx,
            aoi_lat=_AOI_LAT,
            aoi_lon=_AOI_LON,
            ground_lat=gs[1],
            ground_lon=gs[2],
            ground_id=gs[0],
        )
        # Don't start the clock yet — hold on 'acquire' until the scene loads.
        self._mission_start_wall = None
        self._mission_request_wall = time.monotonic()
        return self._mission

    def mission_scene_ready(self) -> None:
        """Begin the cinematic timeline. Called once Kit confirms the target
        scene geometry is resident (POST /mission/scene_ready). Idempotent and
        ignored unless a mission is pending its load gate."""
        if not self._mission.active or self._mission_start_wall is not None:
            return
        self._mission_start_wall = time.monotonic()

    def stop_mission(self) -> None:
        self._mission = MissionState()
        self._mission_start_wall = None
        self._mission_request_wall = None

    @property
    def mission(self) -> MissionState:
        return self._mission

    def _assign_cast(self) -> tuple[int, int, tuple[str, float, float]]:
        """Pick (sensor_idx, hub_idx, ground_station) from the live fleet."""
        sensor_idx = 0
        if self._fleet_latlon:
            best = float("inf")
            for i, (lat, lon) in enumerate(self._fleet_latlon):
                d = _ang_dist(lat, lon, _AOI_LAT, _AOI_LON)
                if d < best:
                    best, sensor_idx = d, i
        hub_idx = 0
        # Ground station nearest the hub's sub-point (fallback: first GS).
        gs = _GROUND_STATIONS[0]
        if self._fleet_latlon and hub_idx < len(self._fleet_latlon):
            hlat, hlon = self._fleet_latlon[hub_idx]
            best = float("inf")
            for cand in _GROUND_STATIONS:
                d = _ang_dist(hlat, hlon, cand[1], cand[2])
                if d < best:
                    best, gs = d, cand
        return sensor_idx, hub_idx, gs

    def _update_mission(self) -> None:
        """Advance the mission phase machine on the wall clock."""
        if not self._mission.active:
            return
        # Load gate — hold on 'acquire' (scene loading) until the clock starts
        # (Kit signalled scene_ready) or the fallback timeout elapses.
        if self._mission_start_wall is None:
            waited = (
                time.monotonic() - self._mission_request_wall
                if self._mission_request_wall is not None else 0.0
            )
            if waited >= _MISSION_LOAD_TIMEOUT_S:
                self._mission_start_wall = time.monotonic()
            else:
                self._mission = self._mission.model_copy(update={
                    "active": True, "phase": "acquire", "phase_progress": 0.0,
                    "elapsed_s": 0.0, "data_volume_mb": 0.0, "targets_found": 0,
                })
                return
        t = time.monotonic() - self._mission_start_wall

        # Find active phase + progress.
        acc = 0.0
        phase, phase_start, dur = _MISSION_PHASES[0][0], 0.0, _MISSION_PHASES[0][1]
        for name, d in _MISSION_PHASES:
            if t < acc + d:
                phase, phase_start, dur = name, acc, d
                break
            acc += d
        else:
            # Walked past the end — mission complete, pin to delivered.
            self._mission = self._mission.model_copy(update={
                "active": False,
                "phase": "deliver",
                "phase_progress": 1.0,
                "elapsed_s": _MISSION_TOTAL_S - _MISSION_PHASES[0][1],
                "data_volume_mb": _MISSION_RESULT_MB,
                "targets_found": _MISSION_TARGETS,
            })
            return

        progress = max(0.0, min(1.0, (t - phase_start) / dur))

        # Data volume: full raw through capture/route; eases 5120→2 during
        # compute; result-sized afterwards.
        if phase in ("capture", "route"):
            data_mb = _MISSION_RAW_MB
        elif phase == "compute":
            data_mb = _MISSION_RAW_MB * (_MISSION_RESULT_MB / _MISSION_RAW_MB) ** progress
        elif phase in ("downlink", "deliver"):
            data_mb = _MISSION_RESULT_MB
        else:
            data_mb = 0.0

        if phase == "compute":
            targets = round(_MISSION_TARGETS * progress)
        elif phase in ("downlink", "deliver"):
            targets = _MISSION_TARGETS
        else:
            targets = 0

        capture_start = _MISSION_PHASES[0][1]  # acquire duration
        elapsed = max(0.0, min(t, _MISSION_TOTAL_S) - capture_start)

        self._mission = self._mission.model_copy(update={
            "active": True,
            "phase": phase,
            "phase_progress": progress,
            "elapsed_s": elapsed,
            "data_volume_mb": data_mb,
            "targets_found": targets,
        })

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
        # Evaluate the mission on read so /state polls (5 Hz from Kit) and WS
        # broadcasts always see fresh wall-clock progress, not 1 Hz-quantized.
        self._update_mission()
        return StatePacket(
            sim_time_s=self._sim_time_s,
            satellite=self._sat.model_copy(),
            ground_station=self._gs.model_copy(),
            constellation=self._fleet_snapshot.model_copy(),
            task=self._task.model_copy() if self._task else None,
            camera_preset=self._camera_preset,
            running=self._running,
            satellite_config=self._config.model_copy(),
            mission=self._mission.model_copy(),
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

        # Cache per-sat lat/lon for mission cast picking (sensor = nearest AOI).
        self._fleet_latlon = [
            orbit_catalog.eci_to_lat_lon_alt(px, py, pz, t)[:2]
            for (px, py, pz) in fleet_pos_km
        ]

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
        # Normalised incidence for the Kit Sun driver — 0 in eclipse, 1 at
        # solar noon. Same cos_a the solar-input model uses.
        self._sat.sun_factor = max(0.0, cos_a)

        # --- Reconfigurable hardware lookups ----------------------------------
        cfg     = self._config
        gpu     = _GPU_TABLE.get(cfg.gpu,                _GPU_TABLE["H100"])
        s_mat   = _SOLAR_MAT_TABLE.get(cfg.solar_material,     _SOLAR_MAT_TABLE["Si"])
        s_size  = _SOLAR_SIZE_TABLE.get(cfg.solar_size,        _SOLAR_SIZE_TABLE["M"])
        r_mat   = _RAD_MAT_TABLE.get(cfg.radiator_material,    _RAD_MAT_TABLE["Aluminum"])

        # Per user spec: the back of each solar panel is also the radiator —
        # area shared. Ignore the radiator_size selector for area; keep
        # radiator MATERIAL as the only knob (its emissivity).
        panel_area_m2 = s_size["area_m2_per_panel"] * s_size["panel_count"]
        radiator_area_m2 = panel_area_m2

        # --- Solar input (front of panel) -------------------------------------
        incidence = max(0.0, cos_a) if self._sat.sunlit else 0.0
        self._sat.solar_input_w = (
            s_mat["efficiency"] * panel_area_m2 * _SOLAR_CONSTANT_W_M2 * incidence
        )

        # --- Workload-driven GPU utilization ----------------------------------
        # Superposition of square jobs with mismatched periods so the curve
        # has burstiness (high/mid/low steps) rather than a clean sinusoid.
        # Eclipse triggers low-power mode (clamped down further below).
        workload = _gpu_workload_util(t)
        if not self._sat.sunlit and self._sat.battery_soc < 0.4:
            workload = min(workload, 0.20)  # power save: drop to baseline
        self._sat.workload = workload
        # Real-design GPU power: idle floor at ~15% TDP, scales linearly with
        # util up to TDP. Datacenter GPUs (H100/H200/B200/MI300X) bench
        # within ~10% of this curve.
        IDLE_FRAC = 0.15
        gpu_w_per_card = gpu["tdp_w"] * (IDLE_FRAC + (1.0 - IDLE_FRAC) * workload)
        payload_w = gpu_w_per_card * _GPU_CARDS_PER_SAT
        platform_w = 600.0
        self._sat.gpu_utilization = workload
        self._sat.payload_power_w = payload_w
        self._sat.platform_power_w = platform_w

        # --- Battery (real Wh integration, accelerated 60x for visibility) ----
        # Net power into the battery. Surplus charges it; deficit discharges.
        load_total_w = payload_w + platform_w
        net_w = self._sat.solar_input_w - load_total_w
        self._sat.battery_charge_w = net_w
        PHYS_TIME_SCALE = 60.0   # 1 wall sec runs 60 sim sec of battery dynamics
        capacity_J = self._sat.battery_capacity_wh * 3600.0
        d_soc = (net_w * dt * PHYS_TIME_SCALE) / capacity_J
        self._sat.battery_soc = max(0.0, min(1.0, self._sat.battery_soc + d_soc))

        # --- Thermal (Stefan-Boltzmann, accelerated 60x) ----------------------
        # Heat in = electrical power dissipated as heat (≈ payload + platform
        # minus a small fraction that leaves as RF — call it 5%).
        SIGMA = 5.67e-8             # W/m²K⁴ Stefan-Boltzmann
        T_BG_K = 250.0              # effective deep-space + Earth IR background
        epsilon = r_mat["emissivity"]
        T_K = self._sat.temperature_c + 273.15
        Q_in = (payload_w + platform_w) * 0.95
        Q_out = epsilon * SIGMA * radiator_area_m2 * (T_K**4 - T_BG_K**4)
        self._sat.radiator_power_w = max(0.0, Q_out)
        # Thermal mass — typical 200 kg sat with aluminum/structures: c_p ~ 800
        # J/kg·K, mass ~ 200 kg → 160 kJ/K. Picked here for legible dynamics.
        THERMAL_MASS_J_PER_K = 160_000.0
        dT_dt = (Q_in - Q_out) / THERMAL_MASS_J_PER_K
        T_K_new = T_K + dT_dt * dt * PHYS_TIME_SCALE
        # Soft clamp to plausible space-sat range.
        self._sat.temperature_c = max(-80.0, min(95.0, T_K_new - 273.15))

        # --- Downlink ---------------------------------------------------------
        self._gs.visible = math.sin(t / 30.0) > 0.4
        self._sat.downlink_mbps = 120.0 if self._gs.visible else 0.0
        self._gs.rx_mbps = self._sat.downlink_mbps

        # --- Design check (solar supply vs avg demand; thermal headroom) ------
        # Average workload across the _JOB_SCHEDULE — duration-weighted mean
        # of each block's target util. This is the same number the visible
        # workload trace will tend to (over a cycle), so the user sees the
        # demand the SCHEDULE actually produces, not a hand-typed 0.40.
        sched_total_dt = sum(d for _, d, _ in _JOB_SCHEDULE)
        avg_workload = (sum(d * u for _, d, u in _JOB_SCHEDULE) / sched_total_dt
                        if sched_total_dt > 0 else 0.30)
        avg_card_w = gpu["tdp_w"] * (IDLE_FRAC + (1.0 - IDLE_FRAC) * avg_workload)
        avg_payload_w = avg_card_w * _GPU_CARDS_PER_SAT
        solar_demand_avg_w = avg_payload_w + platform_w
        peak_solar_w = s_mat["efficiency"] * panel_area_m2 * _SOLAR_CONSTANT_W_M2
        # Sat is sunlit ~50 % of an orbit; the BATTERY needs to round-trip
        # the night, so average solar supply is 0.5 × peak.
        solar_supply_avg_w = peak_solar_w * 0.5

        # Thermal peak demand: worst case is sustained 100 % workload.
        peak_card_w = gpu["tdp_w"] * (IDLE_FRAC + (1.0 - IDLE_FRAC) * 1.0)
        thermal_peak_demand_w = (peak_card_w * _GPU_CARDS_PER_SAT + platform_w) * 0.95
        # Thermal supply: emit at the +60 °C safe-operating ceiling.
        T_max_K = 60.0 + 273.15
        thermal_max_emit_w = epsilon * SIGMA * radiator_area_m2 * (T_max_K**4 - T_BG_K**4)

        self._sat.solar_demand_avg_w    = solar_demand_avg_w
        self._sat.solar_supply_avg_w    = solar_supply_avg_w
        self._sat.thermal_peak_demand_w = thermal_peak_demand_w
        self._sat.thermal_max_emit_w    = thermal_max_emit_w
        self._sat.radiator_area_m2      = radiator_area_m2

        # --- Standing alarms --------------------------------------------------
        alarms: list[str] = []
        if self._sat.battery_soc < 0.20:
            alarms.append("low_battery")
        if self._sat.temperature_c > 70.0:
            alarms.append("overtemp")
        if self._sat.temperature_c < -40.0:
            alarms.append("undertemp")
        if (not self._sat.sunlit
                and self._sat.battery_soc < 0.35
                and net_w < 0):
            alarms.append("eclipse_deficit")
        # Design alarms — use the same numbers the popup will display.
        if thermal_max_emit_w < thermal_peak_demand_w * 0.9:
            alarms.append("radiator_undersized")
        if solar_supply_avg_w < solar_demand_avg_w:
            alarms.append("solar_undersized")
        self._sat.alarms = alarms
        self._sat.gpu_type = cfg.gpu  # echo for the legacy 14-param card


async def _maybe_await(x: Any) -> None:
    if asyncio.iscoroutine(x):
        await x
