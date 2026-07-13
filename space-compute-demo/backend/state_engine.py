"""StateEngine — single source of business truth.

Orbit kinematics now go through services.orbit_catalog (SGP4 propagation of
real published TLEs). Power / thermal / battery / downlink remain the toy
sinusoidal model from Phase 1 — those will be replaced piecewise in later
phases without disturbing the orbit layer.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Callable, Optional

log = logging.getLogger("space_compute_demo.engine")

from models import (
    FleetSnapshot,
    GroundStationState,
    MissionState,
    Mode,
    Parameters,
    SatelliteConfig,
    TwinGeometry,
    SatelliteState,
    StatePacket,
    TaskState,
    WorkloadTotals,
)
import ai_workloads as _ai
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

# pflops = peak dense FP8 tensor PFLOPS per card — the same datasheet column
# ai_workloads.GPU_SPECS uses, so "Compute N PF" on the cards back-solves
# consistently against the workload panel's effective-TFLOPS numbers.
# (H200 shares the GH100 compute die with H100 — it differs in HBM, not PF.)
_GPU_TABLE: dict[str, dict[str, float]] = {
    "H100":   {"pflops": 1.98, "tdp_w": 700.0,  "cost_k": 30.0},
    "H200":   {"pflops": 1.98, "tdp_w": 700.0,  "cost_k": 40.0},
    "B200":   {"pflops": 4.50, "tdp_w": 1000.0, "cost_k": 45.0},
    "MI300X": {"pflops": 2.62, "tdp_w": 750.0,  "cost_k": 28.0},
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
# Sun-tracking array model: pointing/temperature losses while tracking, and
# the sunlit fraction of a LEO orbit under the scene's fixed sun direction
# (measured 0.52 for single_iss with the engine's own propagator; 0.5 is the
# slightly conservative design number). solar_supply_avg_w and the per-tick
# solar_input_w now use the SAME model, so the design-check margins match
# what the simulation actually delivers.
_POINTING_EFF    = 0.95
_SUNLIT_FRACTION = 0.5

# --- Deployable-geometry areas (Feature 4) --------------------------------
# Mirror tools/gen_twin_satellite.py: a solar "cluster" is a 2×2 grid filling
# one big-panel footprint = SOLAR_NATIVE × PANEL_SCALE × BACKBONE_SCALE per
# side; each radiator panel face = radiator_long × (radiator_long / ratio),
# both faces radiate, two panels (±Z). All in stage metres.
_BACKBONE_SCALE = 1.8
_SOLAR_CLUSTER_M2 = (0.981 * 1.45 * _BACKBONE_SCALE) * (0.777 * 1.05 * _BACKBONE_SCALE)

# Hull architectures (lumid / dish) fly INTEGRATED panels — their active cell
# area is fixed by the hull model, not by the wing-segment knob. Effective
# areas sized from the scaled hulls (LUMID ≈5.6 m cross panels; the 6.1 m
# windmill's four swept wings).
_ARCH_FIXED_SOLAR_M2 = {"lumid": 9.5, "dish": 18.0}


def _solar_area_m2(geom) -> float:
    """Total active solar area. Wing-segment archs: segments/side × 2 sides ×
    one-cluster area (blanket lays the same 4 tiles in a row, so the formula
    holds). Hull archs: fixed integrated-panel area."""
    fixed = _ARCH_FIXED_SOLAR_M2.get(getattr(geom, "architecture", "truss"))
    if fixed is not None:
        return fixed
    return geom.solar_clusters_per_side * 2 * _SOLAR_CLUSTER_M2


def _radiator_area_m2(geom) -> float:
    """Total radiating area: 2 panels × 2 faces × face area."""
    long_m = geom.radiator_long * _BACKBONE_SCALE
    short_m = (geom.radiator_long / max(0.1, geom.radiator_ratio)) * _BACKBONE_SCALE
    return 4.0 * long_m * short_m


# Deterministic compute-job schedules — (start_s, duration_s, util, job_key).
# Each profile is the GPU's queue: a fixed sequence of TYPED jobs repeating
# every cycle. `util` is the block's power-duty fraction (drives the
# electrical/thermal physics exactly as before); `job_key` names what the
# GPUs are actually running (ai_workloads.JOB_TYPES — LLM pretraining /
# fine-tune / batched or interactive inference / EO vision, each against a
# concrete model) so the state can report MFU, effective TFLOPS, tokens/s or
# frames/s and per-card heat. Design presets pick a profile by id.
_WORKLOAD_PROFILES: dict[str, dict] = {
    # LLM serving is the PRIMARY business of the orbital DC: most profiles
    # fly inference schedules over a variety of models (the analytic
    # llm_perf engine resolves each block's true power/throughput/thermal
    # operating point); vision/EO and training remain as secondary stories.
    #
    # The mixed EO + LLM utility schedule (vision + inference side-jobs).
    "balanced": {
        "label": "Mixed inference",
        "cycle_s": 400.0,
        "schedule": [
            (  0.0,  18.0, 0.10, "housekeeping"),     # cold boot
            ( 18.0,  42.0, 0.65, "vision_batch"),     # imagery batch inference
            ( 60.0,  18.0, 0.92, "vision_burst"),     # target acquired
            ( 78.0,  36.0, 0.70, "llm_chat_70b"),     # chat serving window
            (114.0,  24.0, 0.20, "llm_interactive"),  # ops queries while downlinking
            (138.0,  60.0, 0.60, "llm_code_32b"),     # code-assist window
            (198.0,  48.0, 0.85, "llm_batch"),        # report/summary backlog
            (246.0,  30.0, 0.30, "llm_interactive"),  # cooldown gap
            (276.0,  72.0, 0.70, "vision_batch"),     # sustained survey
            (348.0,  18.0, 0.95, "vision_burst"),     # emergency re-classify
            (366.0,  34.0, 0.55, "llm_chat_8b"),      # edge chat, decaying duty
        ],
    },
    # Multi-tier chat serving: big-model quality tier + small-model edge
    # tier, with interactive lulls — every block is a DIFFERENT operating
    # point on the decode law (batch, context, model size).
    "chat_serving": {
        "label": "Chat serving (multi-tier)",
        "cycle_s": 360.0,
        "schedule": [
            (  0.0,  90.0, 0.70, "llm_chat_70b"),     # quality tier
            ( 90.0,  50.0, 0.55, "llm_chat_8b"),      # edge tier surge
            (140.0,  80.0, 0.75, "llm_chat_70b"),     # quality tier peak
            (220.0,  40.0, 0.30, "llm_interactive"),  # night-side lull
            (260.0,  70.0, 0.70, "llm_chat_70b"),     # quality tier
            (330.0,  30.0, 0.55, "llm_chat_8b"),      # edge tier
        ],
    },
    # Frontier-model serving: 405B dense, near-flat-out, with eval and
    # interactive dips — the heaviest sustained inference the DC can fly.
    "frontier": {
        "label": "Frontier serving (405B)",
        "cycle_s": 360.0,
        "schedule": [
            (  0.0, 100.0, 0.85, "llm_frontier_405b"),
            (100.0,  20.0, 0.50, "llm_eval"),          # quality regression pass
            (120.0, 110.0, 0.88, "llm_frontier_405b"),
            (230.0,  30.0, 0.30, "llm_interactive"),   # request trough
            (260.0, 100.0, 0.85, "llm_frontier_405b"),
        ],
    },
    # Developer-workload mix: code completion, long-context RAG and doc
    # summarization on three mid-size models.
    "code_rag": {
        "label": "Code & RAG serving",
        "cycle_s": 360.0,
        "schedule": [
            (  0.0,  90.0, 0.60, "llm_code_32b"),      # code completion
            ( 90.0,  70.0, 0.65, "llm_rag_72b"),       # RAG long-context
            (160.0,  60.0, 0.70, "llm_summarize_24b"), # summarization batch
            (220.0,  80.0, 0.60, "llm_code_32b"),      # code completion
            (300.0,  60.0, 0.65, "llm_rag_72b"),       # RAG long-context
        ],
    },
    # Near-flat-out 70B pretraining with checkpoint/eval dips.
    "training": {
        "label": "Sustained training",
        "cycle_s": 360.0,
        "schedule": [
            (  0.0,  80.0, 0.90, "llm_pretrain"),     # epoch
            ( 80.0,  10.0, 0.35, "checkpoint_io"),    # checkpoint write
            ( 90.0,  86.0, 0.92, "llm_pretrain"),     # epoch
            (176.0,  10.0, 0.35, "checkpoint_io"),    # checkpoint write
            (186.0,  90.0, 0.88, "llm_pretrain"),     # epoch
            (276.0,  14.0, 0.50, "llm_eval"),         # eval pass
            (290.0,  70.0, 0.94, "llm_pretrain"),     # epoch
        ],
    },
    # Round-the-clock 70B token serving — decode-dominant, the workload the
    # analytical llm_perf engine (power-cap ∧ thermal-limit → DVFS → tok/s)
    # is built around: batched backlog with interactive/eval windows.
    "inference": {
        "label": "LLM serving (70B)",
        "cycle_s": 360.0,
        "schedule": [
            (  0.0, 110.0, 0.85, "llm_batch"),        # batched decode backlog
            (110.0,  40.0, 0.30, "llm_interactive"),  # interactive window
            (150.0,  90.0, 0.85, "llm_batch"),        # batched decode
            (240.0,  20.0, 0.50, "llm_eval"),         # long-context eval pass
            (260.0,  70.0, 0.90, "llm_batch"),        # peak backlog
            (330.0,  30.0, 0.30, "llm_interactive"),  # cooldown window
        ],
    },
    # Mostly quiet with tall target-of-opportunity spikes.
    "burst": {
        "label": "Burst response",
        "cycle_s": 300.0,
        "schedule": [
            (  0.0,  50.0, 0.12, "housekeeping"),     # standby scan
            ( 50.0,  16.0, 1.00, "vision_burst"),     # alert! full-rate classify
            ( 66.0,  40.0, 0.15, "housekeeping"),     # standby
            (106.0,  22.0, 0.95, "vision_burst"),     # second contact burst
            (128.0,  60.0, 0.10, "housekeeping"),     # long quiet stretch
            (188.0,  12.0, 1.00, "vision_burst"),     # flash tasking
            (200.0,  46.0, 0.30, "llm_interactive"),  # post-burst downlink prep
            (246.0,  54.0, 0.12, "housekeeping"),     # standby scan
        ],
    },
    # Housekeeping idle with one modest daily-batch window.
    "low_duty": {
        "label": "Low duty cycle",
        "cycle_s": 400.0,
        "schedule": [
            (  0.0, 150.0, 0.08, "housekeeping"),     # housekeeping
            (150.0,  60.0, 0.50, "vision_batch"),     # scheduled batch window
            (210.0,  30.0, 0.20, "llm_interactive"),  # results packaging
            (240.0, 160.0, 0.08, "housekeeping"),     # housekeeping
        ],
    },
}
_DEFAULT_WORKLOAD_PROFILE = "inference"
_IDLE_JOB = "housekeeping"

# Full-travel time (wall s) of the roll-out solar array deploy/retract —
# slow enough to read as a flexible blanket unrolling, fast enough to demo.
_SOLAR_DEPLOY_S = 12.0


def _profile(profile_id: str) -> dict:
    return _WORKLOAD_PROFILES.get(profile_id, _WORKLOAD_PROFILES[_DEFAULT_WORKLOAD_PROFILE])


def workload_profile_stats(profile_id: str) -> dict:
    """Headline numbers for a profile — duration-weighted mean utilization
    plus display labels. Used by the /designs gallery cards."""
    prof = _profile(profile_id)
    sched = prof["schedule"]
    total = sum(d for _, d, _, _ in sched)
    avg = sum(d * u for _, d, u, _ in sched) / total if total > 0 else 0.30
    return {"label": prof["label"], "avg_util": round(avg, 2)}


def _gpu_workload_util(t: float, profile_id: str) -> tuple[float, str]:
    """Walk a profile's fixed schedule. At sim time t we wrap into the
    schedule's cycle and return the active block's (power-duty utilization,
    typed job key), falling back to an idle floor if t lands in a gap."""
    prof = _profile(profile_id)
    ct = t % prof["cycle_s"]
    for start, dur, u, job in prof["schedule"]:
        if start <= ct < start + dur:
            return u, job
    return 0.05, _IDLE_JOB


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
        self._twin_geometry: TwinGeometry = TwinGeometry()
        # Active design preset (design_presets.py). Applying a preset swaps
        # config + geometry + workload profile + platform constants together;
        # any manual edit afterwards degrades the id to "custom". Boots as
        # "custom" — the engine's defaults (and whatever twin model is on
        # disk from a previous session) don't necessarily match any preset,
        # so claiming one would lie to the gallery.
        self._design_id: str = "custom"
        self._workload_profile: str = _DEFAULT_WORKLOAD_PROFILE
        self._platform_power_w: float = 600.0
        self._gpu_count: int = _GPU_CARDS_PER_SAT
        # Wall time of the last completed physics tick — anchors the on-read
        # fractional-time display-kinematics refresh (smooth 5 Hz polls).
        self._last_tick_wall: Optional[float] = None
        # 天数天算 mission — phase machine on a wall-clock timeline. The clock
        # (_mission_start_wall) only starts once the scene is loaded; until
        # then the mission holds on 'acquire'. _mission_request_wall marks when
        # Start was pressed so the load gate can time out.
        self._mission: MissionState = MissionState()
        self._mission_start_wall: Optional[float] = None
        self._mission_request_wall: Optional[float] = None
        # Cached fleet lat/lon (computed each tick) for mission cast picking.
        self._fleet_latlon: list[tuple[float, float]] = []
        # Memoized schedule-average demand for the live design check —
        # (inputs key, W). See _schedule_demand_avg_w.
        self._demand_cache: Optional[tuple[tuple, float]] = None
        # Roll-out solar-array command target (the live fraction sits on
        # SatelliteState.solar_deploy_frac and slews toward this each tick).
        self._solar_deploy_target: float = 1.0

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
        # Rebuild the telemetry state but keep design-owned hardware constants:
        # battery capacity is stamped by apply_design and must survive a sim
        # reset or the active design's power story runs on the wrong pack.
        battery_capacity_wh = self._sat.battery_capacity_wh
        self._sat = SatelliteState()
        self._sat.battery_capacity_wh = battery_capacity_wh
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

    def set_config(self, patch: dict[str, Any], *, mark_custom: bool = True) -> SatelliteConfig:
        """Merge a partial hardware loadout into the active config. Returns
        the new full config so the handler can echo it back. Unknown keys
        are ignored; bad values raise the underlying Pydantic ValidationError."""
        cleaned = {k: v for k, v in patch.items() if v is not None}
        self._config = self._config.model_copy(update=cleaned)
        # Pydantic re-validates via model_validate to ensure literals are
        # actually one of the allowed enum strings (model_copy alone does not).
        self._config = SatelliteConfig.model_validate(self._config.model_dump())
        if mark_custom and cleaned:
            self._design_id = "custom"
        return self._config

    @property
    def satellite_config(self) -> SatelliteConfig:
        return self._config

    @property
    def twin_geometry(self) -> TwinGeometry:
        return self._twin_geometry

    def set_twin_geometry(self, patch: dict[str, Any], *, mark_custom: bool = True) -> TwinGeometry:
        """Merge deployable-geometry knobs. Clamped to the same ranges
        gen_twin_satellite.py enforces. Returns the new geometry. Does NOT
        bump `version` — the handler bumps it via bump_twin_version() only
        after the regenerated USD is fully on disk, otherwise Kit's 5 Hz
        /state poll sees the new version first and force-reloads the STALE
        (or half-written) twin_satellite.usda."""
        cleaned = {k: v for k, v in patch.items() if v is not None and k != "version"}
        merged = self._twin_geometry.model_copy(update=cleaned)
        merged.solar_clusters_per_side = max(1, min(8, int(merged.solar_clusters_per_side)))
        merged.radiator_long = max(0.3, min(3.0, float(merged.radiator_long)))
        merged.radiator_ratio = max(1.2, min(6.0, float(merged.radiator_ratio)))
        self._twin_geometry = TwinGeometry.model_validate(merged.model_dump())
        if mark_custom and cleaned:
            self._design_id = "custom"
        return self._twin_geometry

    def bump_twin_version(self) -> TwinGeometry:
        """Signal Kit to reload the twin layer. Call ONLY once the regenerated
        usd/twin_satellite.usda is fully written."""
        self._twin_geometry = self._twin_geometry.model_copy(
            update={"version": self._twin_geometry.version + 1})
        return self._twin_geometry

    # ---- design presets (design_presets.py) ----
    @property
    def design_id(self) -> str:
        return self._design_id

    @property
    def workload_profile(self) -> str:
        return self._workload_profile

    def set_workload_profile(self, profile_id: str, *, mark_custom: bool = True) -> str:
        """Switch the GPU job schedule the satellite is flying. Raises
        ValueError on unknown ids. Resets the output accumulators so the
        'produced since switch' story starts clean; a manual switch degrades
        the active design to 'custom' (the profile is part of a design)."""
        if profile_id not in _WORKLOAD_PROFILES:
            raise ValueError(f"unknown workload profile {profile_id!r}")
        if profile_id != self._workload_profile:
            self._workload_profile = profile_id
            if mark_custom:
                self._design_id = "custom"
        self._reset_workload_totals()
        return self._workload_profile

    def _reset_workload_totals(self) -> None:
        self._sat.workload_totals = WorkloadTotals()

    _SPIN_AXES = {"x": 0, "y": 1, "z": 2}

    def set_attitude_spin(self, action: str, axis: str = "z") -> dict:
        """Reaction-wheel demo: start/stop/toggle a slow 360° body rotation
        about any of the centre-of-mass X/Y/Z axes (axes combine into a
        tumble). Rate is a legible 1 rpm (6°/s) per axis; Kit integrates
        the angles per frame. Display-only — the sun-tracking power model
        is unaffected."""
        idx = self._SPIN_AXES.get(str(axis).lower())
        if idx is None:
            raise ValueError(f"unknown attitude_spin axis {axis!r}")
        rates = list(self._sat.attitude_spin_dps)
        if action == "toggle":
            action = "stop" if rates[idx] > 0.0 else "start"
        if action not in ("start", "stop"):
            raise ValueError(f"unknown attitude_spin action {action!r}")
        rates[idx] = 6.0 if action == "start" else 0.0
        self._sat.attitude_spin_dps = tuple(rates)
        return {"action": action, "axis": axis, "spin_dps": rates}

    def set_solar_deploy(self, action: str) -> dict:
        """Command the roll-out solar array. 'deploy' → extend to 1.0,
        'retract' → reel in to 0.0, 'toggle' → whichever end is farther.
        The tick slews the live fraction there over _SOLAR_DEPLOY_S; solar
        production and the Kit wing-stretch driver both follow it."""
        if action == "toggle":
            action = "retract" if self._solar_deploy_target >= 0.5 else "deploy"
        if action not in ("deploy", "retract"):
            raise ValueError(f"unknown solar_deploy action {action!r}")
        self._solar_deploy_target = 1.0 if action == "deploy" else 0.0
        return {"action": action,
                "target": self._solar_deploy_target,
                "frac": round(self._sat.solar_deploy_frac, 3)}

    def _schedule_demand_avg_w(self, profile_id: str) -> float:
        """Duration-weighted average electrical demand of `profile_id`'s
        schedule on the CURRENT loadout, using the same per-block operating
        points the simulation actually flies (LLM blocks: analytic realized
        draw at the 25 °C no-throttle baseline; others: the TDP-curve cap).
        Shared by the live design check and workload_adaptation so the
        standing alarm, the popup and the power trace tell ONE story.
        Memoized on the inputs that move it — the schedule walk costs a few
        closed-form solves, but this runs every tick."""
        key = (profile_id, self._config.gpu, self._gpu_count,
               self._platform_power_w)
        if self._demand_cache is not None and self._demand_cache[0] == key:
            return self._demand_cache[1]
        sched = _profile(profile_id)["schedule"]
        gpu = _GPU_TABLE.get(self._config.gpu, _GPU_TABLE["H100"])
        total_dt = sum(d for _, d, _, _ in sched) or 1.0
        IDLE_FRAC = 0.15
        demand = 0.0
        for _, dur, util, job_key in sched:
            card_w = gpu["tdp_w"] * (IDLE_FRAC + (1.0 - IDLE_FRAC) * util)
            det = _ai.job_detail(self._config.gpu, job_key, util, card_w,
                                 self._gpu_count, t_struct_c=25.0)
            if det is not None and det.engine == "analytic":
                card_w = det.power_w_per_gpu
            demand += ((card_w * self._gpu_count + self._platform_power_w)
                       * dur / total_dt)
        self._demand_cache = (key, demand)
        return demand

    def workload_adaptation(self, profile_id: str) -> dict:
        """How the CURRENT design would cope with `profile_id`: average power
        demand vs solar supply, thermal peak vs radiator emission ceiling,
        and the expected outputs of one schedule cycle (tokens / frames /
        payload energy) on the fitted GPUs. Same formulas as the live design
        check, so the numbers agree with what the panels show after a switch."""
        prof = _profile(profile_id)
        sched = prof["schedule"]
        cfg = self._config
        gpu = _GPU_TABLE.get(cfg.gpu, _GPU_TABLE["H100"])
        s_mat = _SOLAR_MAT_TABLE.get(cfg.solar_material, _SOLAR_MAT_TABLE["Si"])
        r_mat = _RAD_MAT_TABLE.get(cfg.radiator_material, _RAD_MAT_TABLE["Aluminum"])
        geom = self._twin_geometry
        n = self._gpu_count
        platform_w = self._platform_power_w
        IDLE_FRAC = 0.15

        total_dt = sum(d for _, d, _, _ in sched) or 1.0
        avg_util = sum(d * u for _, d, u, _ in sched) / total_dt
        peak_solar_w = s_mat["efficiency"] * _solar_area_m2(geom) * _SOLAR_CONSTANT_W_M2
        supply_avg_w = peak_solar_w * _POINTING_EFF * _SUNLIT_FRACTION

        thermal_peak_w = (gpu["tdp_w"] * n + platform_w) * 0.95
        SIGMA, T_BG_K = 5.67e-8, 250.0
        thermal_emit_w = (r_mat["emissivity"] * SIGMA * _radiator_area_m2(geom)
                          * ((333.15) ** 4 - T_BG_K ** 4))

        # Demand side: the shared schedule-average (per-block analytic
        # realized draw for LLM blocks at the 25 °C no-throttle baseline) —
        # the exact number the live design check uses, so verdicts here can
        # never contradict the standing alarm.
        demand_avg_w = self._schedule_demand_avg_w(profile_id)

        tokens = frames = 0.0
        kwh = 0.0
        for _, dur, util, job_key in sched:
            card_w = gpu["tdp_w"] * (IDLE_FRAC + (1 - IDLE_FRAC) * util)
            det = _ai.job_detail(cfg.gpu, job_key, util, card_w, n,
                                 t_struct_c=25.0)
            if det is not None:
                if det.throughput_unit == "tok/s":
                    tokens += det.throughput_total * dur
                elif det.throughput_unit == "frames/s":
                    frames += det.throughput_total * dur
                if det.engine == "analytic":
                    card_w = det.power_w_per_gpu
            kwh += (card_w * n + platform_w) * dur / 3.6e6

        power_margin = supply_avg_w / max(1.0, demand_avg_w) - 1.0
        thermal_margin = thermal_emit_w / max(1.0, thermal_peak_w) - 1.0
        fit = ("ok" if power_margin >= 0.10 and thermal_margin >= 0.0
               else "tight" if power_margin >= 0.0 and thermal_margin >= -0.10
               else "exceeds")
        return {
            "id": profile_id,
            "label": prof["label"],
            "cycle_s": prof["cycle_s"],
            "avg_util": round(avg_util, 2),
            "demand_avg_w": round(demand_avg_w),
            "supply_avg_w": round(supply_avg_w),
            "power_margin_pct": round(power_margin * 100),
            "thermal_peak_w": round(thermal_peak_w),
            "thermal_emit_w": round(thermal_emit_w),
            "thermal_margin_pct": round(thermal_margin * 100),
            "fit": fit,
            "outputs_per_cycle": {
                "tokens": round(tokens),
                "frames": round(frames),
                "payload_kwh": round(kwh, 2),
            },
            "jobs": sorted({_ai.JOB_TYPES[j]["label"] for _, _, _, j in sched
                            if j in _ai.JOB_TYPES}),
        }

    def apply_design(self, preset: Any) -> TwinGeometry:
        """Switch the whole satellite design in one shot: hardware loadout,
        deployable geometry (the handler then regenerates the USD and bumps
        the version so Kit reloads), workload profile, and platform
        constants. `preset` is a design_presets.DesignPreset."""
        self.set_config(preset.config.model_dump(), mark_custom=False)
        geom = self.set_twin_geometry(preset.geometry_patch(), mark_custom=False)
        self._workload_profile = (preset.workload_profile
                                  if preset.workload_profile in _WORKLOAD_PROFILES
                                  else _DEFAULT_WORKLOAD_PROFILE)
        self._platform_power_w = float(preset.platform_power_w)
        self._gpu_count = max(1, int(preset.gpu_count))
        self._reset_workload_totals()
        # Battery: swap capacity, keep the current charge fraction so the
        # switch doesn't teleport the SOC story.
        self._sat.battery_capacity_wh = float(preset.battery_capacity_wh)
        # Deployment state never carries over across designs. The redwire
        # roll-out array arrives STOWED (the just-separated look — press
        # Deploy and watch the blanket reel out); rigid-wing designs arrive
        # fully deployed as before.
        stowed = getattr(preset, "architecture", "truss") == "redwire"
        self._solar_deploy_target = 0.0 if stowed else 1.0
        self._sat.solar_deploy_frac = 0.0 if stowed else 1.0
        self._design_id = preset.id
        return geom

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

    def _set_tracked_kinematics(self, pos_km: tuple[float, float, float],
                                t: float) -> float:
        """Write the tracked satellite's POSITION-derived display fields
        (sat_xyz/lat/lon/alt, sunlit, sun_factor, sun_cos, dawn-dusk flags)
        from an ECI position. Shared by the 1 Hz physics tick and the
        on-read display refresh. Returns the raw zenith→sun cosine."""
        x_km, y_km, z_km = pos_km
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
        # Raw zenith→sun cosine for the Kit sun-direction driver (see
        # models.SatelliteState.sun_cos). Dawn-dusk rides the terminator, so
        # its sun sits broadside on the horizon (cos ≈ 0).
        self._sat.sun_cos = cos_a
        # Dawn-dusk SSO rides the terminator → never eclipsed, and the panels
        # track the Sun, so it stays at full direct incidence at all times.
        is_dawn_dusk = (self._constellation_id == "dawn_dusk_sso")
        self._sat.is_dawn_dusk = is_dawn_dusk
        if is_dawn_dusk:
            self._sat.sunlit = True
            self._sat.sun_factor = 1.0
            self._sat.sun_cos = 0.0
        return cos_a

    def _refresh_display_kinematics(self) -> None:
        """Refresh the tracked satellite's position-derived fields at the
        CURRENT fractional sim time (single cached-Satrec sgp4 call). The
        1 Hz physics tick only produces 1 Hz kinematics, so Kit's 5 Hz
        /state polls would see the same lat/lon for ~1 s and the eased
        Earth-rotation driver would surge-and-stall once per second.
        Integration state (SOC, temperature, totals) stays strictly
        tick-owned; this touches geometry plus the instantaneous power
        readouts that are pure functions of it."""
        if not self._running or self._last_tick_wall is None:
            return
        frac = min(1.0, max(0.0, time.monotonic() - self._last_tick_wall))
        t = self._sim_time_s + frac
        preset = _consts.get_preset(self._constellation_id) or _consts.get_preset("single_iss")
        try:
            pos = _consts.propagate_tracked(preset, t)
        except Exception:  # noqa: BLE001 — display-only; keep last values
            return
        if pos == (0.0, 0.0, 0.0):
            return
        self._set_tracked_kinematics(pos, t)
        # Keep the power triplet (sunlit, solar_input_w, battery_charge_w)
        # self-consistent on eclipse-boundary reads: the fresh sunlit flag
        # would otherwise contradict last tick's solar input for up to 1 s
        # (sunlit=False with panels still "producing"). Same formulas as the
        # tick — including the deployment fraction — reusing the tick-owned
        # load.
        s_mat = _SOLAR_MAT_TABLE.get(self._config.solar_material, _SOLAR_MAT_TABLE["Si"])
        incidence = (1.0 if self._sat.is_dawn_dusk
                     else (_POINTING_EFF if self._sat.sunlit else 0.0))
        solar_w = (s_mat["efficiency"] * _solar_area_m2(self._twin_geometry)
                   * _SOLAR_CONSTANT_W_M2 * incidence
                   * self._sat.solar_deploy_frac)
        self._sat.solar_input_w = solar_w
        self._sat.battery_charge_w = solar_w - (self._sat.payload_power_w
                                                + self._sat.platform_power_w)

    # ---- snapshot ----
    def snapshot(self) -> StatePacket:
        # Evaluate the mission + the tracked satellite's display kinematics
        # on read, so /state polls (5 Hz from Kit) and WS broadcasts see
        # continuously fresh wall-clock progress, not 1 Hz-quantized steps.
        self._update_mission()
        self._refresh_display_kinematics()
        return StatePacket(
            sim_time_s=self._sim_time_s,
            satellite=self._sat.model_copy(),
            ground_station=self._gs.model_copy(),
            constellation=self._fleet_snapshot.model_copy(),
            task=self._task.model_copy() if self._task else None,
            camera_preset=self._camera_preset,
            running=self._running,
            satellite_config=self._config.model_copy(),
            twin_geometry=self._twin_geometry.model_copy(),
            mission=self._mission.model_copy(),
            design_id=self._design_id,
            workload_profile=self._workload_profile,
        )

    # ---- inner loop ----
    async def _run(self) -> None:
        dt = 1.0 / TICK_HZ
        while True:
            await asyncio.sleep(dt)
            if not self._running:
                continue
            self._sim_time_s += dt
            # Physics MUST be inside its own try: an uncaught exception here
            # would end the asyncio task silently — /state would keep serving
            # frozen values with running=true and there is no restart path.
            # A transient failure (e.g. an sgp4 hiccup) now just skips a tick.
            try:
                self._update_placeholder_physics(dt)
            except Exception:
                log.exception("physics tick failed (sim_t=%.0f) — skipping tick",
                              self._sim_time_s)
            # Anchor for on-read fractional-time kinematics refreshes.
            self._last_tick_wall = time.monotonic()
            try:
                await _maybe_await(self._on_state(self.snapshot()))
            except Exception:
                log.exception("state broadcast failed")

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
        cos_a = self._set_tracked_kinematics((x_km, y_km, z_km), t)
        is_dawn_dusk = self._sat.is_dawn_dusk

        # --- Reconfigurable hardware lookups ----------------------------------
        cfg     = self._config
        gpu     = _GPU_TABLE.get(cfg.gpu,                _GPU_TABLE["H100"])
        s_mat   = _SOLAR_MAT_TABLE.get(cfg.solar_material,     _SOLAR_MAT_TABLE["Si"])
        s_size  = _SOLAR_SIZE_TABLE.get(cfg.solar_size,        _SOLAR_SIZE_TABLE["M"])
        r_mat   = _RAD_MAT_TABLE.get(cfg.radiator_material,    _RAD_MAT_TABLE["Aluminum"])

        # Areas now come from the deployable geometry (Feature 4): solar scales
        # with clusters/side, radiators are the dedicated ±Z panels (independent
        # of solar). solar_material still sets η, radiator_material sets ε.
        geom = self._twin_geometry
        panel_area_m2 = _solar_area_m2(geom)
        radiator_area_m2 = _radiator_area_m2(geom)

        # --- Solar input (front of panel) -------------------------------------
        # The wings ride a sun-tracking drive (SADA), like every real orbital
        # power system: while sunlit the cells hold near-normal incidence and
        # deliver _POINTING_EFF × peak; in eclipse they deliver nothing. (The
        # old model reused the position-vector/sun cosine as "incidence",
        # which averaged only ~0.22 over an orbit — no physically plausible
        # array could ever close the power budget, so the battery pinned at 0
        # and the physics looked dead.) Dawn-dusk SSO: permanent full sun.
        incidence = 1.0 if is_dawn_dusk else (_POINTING_EFF if self._sat.sunlit else 0.0)
        # Roll-out array deployment: slew the live fraction toward the
        # commanded target (POST /solar_deploy) over _SOLAR_DEPLOY_S, and
        # scale production with it — a retracted blanket genuinely starves
        # the satellite (the battery/eclipse story reacts for real).
        frac = self._sat.solar_deploy_frac
        step = dt / _SOLAR_DEPLOY_S
        if frac < self._solar_deploy_target:
            frac = min(self._solar_deploy_target, frac + step)
        elif frac > self._solar_deploy_target:
            frac = max(self._solar_deploy_target, frac - step)
        self._sat.solar_deploy_frac = frac
        self._sat.solar_input_w = (
            s_mat["efficiency"] * panel_area_m2 * _SOLAR_CONSTANT_W_M2
            * incidence * frac
        )

        # --- Workload-driven GPU utilization ----------------------------------
        # The active schedule block names a TYPED job (LLM train/infer, EO
        # vision — ai_workloads.py) plus its power-duty fraction. Eclipse
        # with a low battery drops to power-save and the job degrades to
        # housekeeping (the GPUs really are throttled to survival duty).
        workload, job_key = _gpu_workload_util(t, self._workload_profile)
        if not self._sat.sunlit and self._sat.battery_soc < 0.4:
            if workload > 0.20:
                workload, job_key = 0.20, _IDLE_JOB  # power save: survival duty
        self._sat.workload = workload
        # EPS power budget per card: idle floor at ~15% TDP, scales linearly
        # with util up to TDP. Datacenter GPUs (H100/H200/B200/MI300X) bench
        # within ~10% of this curve.
        IDLE_FRAC = 0.15
        gpu_count = self._gpu_count
        gpu_cap_w_per_card = gpu["tdp_w"] * (IDLE_FRAC + (1.0 - IDLE_FRAC) * workload)
        # Per-GPU operating point for the active block. LLM jobs run the
        # ANALYTICAL engine (llm_perf via ai_workloads): the satellite
        # structure temperature is the GPU cold plate, the thermal limit
        # (T_throttle − T_struct)/R_th caps the DVFS budget, and the card's
        # REALIZED draw comes back out — so a hot structure visibly
        # throttles clocks, tokens/s AND electrical demand. Vision/idle
        # jobs keep the budget as the draw (MFU path).
        detail = _ai.job_detail(cfg.gpu, job_key, workload, gpu_cap_w_per_card,
                                gpu_count, t_struct_c=self._sat.temperature_c)
        self._sat.workload_detail = detail
        gpu_w_per_card = (detail.power_w_per_gpu
                          if detail is not None and detail.engine == "analytic"
                          else gpu_cap_w_per_card)
        payload_w = gpu_w_per_card * gpu_count
        platform_w = self._platform_power_w
        self._sat.gpu_utilization = workload
        self._sat.payload_power_w = payload_w
        self._sat.platform_power_w = platform_w
        self._sat.gpu_count = gpu_count
        # Cumulative output — sim-time (1:1) integration of the typed-job
        # throughput plus payload energy, reset on profile/design switches.
        totals = self._sat.workload_totals
        if detail is not None:
            if detail.throughput_unit == "tok/s":
                totals.tokens += detail.throughput_total * dt
            elif detail.throughput_unit == "frames/s":
                totals.frames += detail.throughput_total * dt
        totals.payload_kwh += (payload_w + platform_w) * dt / 3.6e6
        totals.duration_s += dt

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
        # Average demand across the ACTIVE profile's schedule, per-block from
        # the SAME operating points the simulation flies (analytic realized
        # draw for LLM blocks) — this is the demand the power trace actually
        # tends to over a cycle, and it matches workload_adaptation exactly,
        # so the standing alarm can never contradict the popup.
        solar_demand_avg_w = self._schedule_demand_avg_w(self._workload_profile)
        peak_solar_w = s_mat["efficiency"] * panel_area_m2 * _SOLAR_CONSTANT_W_M2
        # Orbit-average supply under the SAME sun-tracking model the per-tick
        # solar_input_w uses: tracking losses × the sunlit fraction (the
        # battery round-trips the night). Dawn-dusk never sees eclipse.
        if is_dawn_dusk:
            solar_supply_avg_w = peak_solar_w
        else:
            solar_supply_avg_w = peak_solar_w * _POINTING_EFF * _SUNLIT_FRACTION

        # Thermal peak demand: worst case is sustained 100 % workload.
        peak_card_w = gpu["tdp_w"] * (IDLE_FRAC + (1.0 - IDLE_FRAC) * 1.0)
        thermal_peak_demand_w = (peak_card_w * gpu_count + platform_w) * 0.95
        # Thermal supply: emit at the +60 °C safe-operating ceiling.
        T_max_K = 60.0 + 273.15
        thermal_max_emit_w = epsilon * SIGMA * radiator_area_m2 * (T_max_K**4 - T_BG_K**4)

        self._sat.solar_demand_avg_w    = solar_demand_avg_w
        self._sat.solar_supply_avg_w    = solar_supply_avg_w
        self._sat.thermal_peak_demand_w = thermal_peak_demand_w
        self._sat.thermal_max_emit_w    = thermal_max_emit_w
        self._sat.solar_area_m2         = panel_area_m2
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
        # Analytical-engine thermal flags: the GPU die is being held at its
        # throttle target (performance loss) / cannot be held at all.
        if detail is not None and detail.engine == "analytic":
            if detail.thermal_runaway:
                alarms.append("gpu_thermal_runaway")
            elif detail.thermal_throttled:
                alarms.append("gpu_thermal_throttle")
        self._sat.alarms = alarms
        self._sat.gpu_type = cfg.gpu  # echo for the legacy 14-param card


async def _maybe_await(x: Any) -> None:
    if asyncio.iscoroutine(x):
        await x
