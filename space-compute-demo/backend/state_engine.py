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
from typing import Any, Callable, Optional, get_args

log = logging.getLogger("space_compute_demo.engine")

from models import (
    AttitudeMode,
    ElevationCount,
    FleetSnapshot,
    GpuMixItem,
    GroundStationState,
    GroundTargetState,
    MissionState,
    OrbitalElements,
    SolarHistBin,
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
import satellite_assets as _assets
from services import orbit_catalog
from services import constellations as _consts
from services import geodyn as _geodyn
from services import elements as _elements
from services import timebase as _timebase

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
# Payload-bay ceiling — the biggest hull in the catalog (twin_truss) carries
# 24 rack slots; anything beyond that is a malformed request, not a design.
_MAX_GPU_SLOTS = 24
# EPS power budget per card: an idle floor at ~15 % TDP, scaling linearly with
# utilization up to TDP. Datacenter GPUs (H100/H200/B200/MI300X) bench within
# ~10 % of this curve.
_IDLE_FRAC = 0.15

# Cell efficiency is quoted at the 25 °C reference; the per-material power
# temperature coefficient (fraction/K, all negative) derates it as the
# structure warms — standard datasheet behavior (Si ≈ −0.45 %/K,
# triple-junction GaAs ≈ −0.20 %/K, perovskite lab cells ≈ −0.30 %/K).
_SOLAR_MAT_TABLE = {
    "Si":         {"efficiency": 0.22, "temp_coeff_per_k": -0.0045, "density_kg_m2": 2.5},
    "GaAs":       {"efficiency": 0.32, "temp_coeff_per_k": -0.0020, "density_kg_m2": 3.0},
    "Perovskite": {"efficiency": 0.38, "temp_coeff_per_k": -0.0030, "density_kg_m2": 1.8},
}
_SOLAR_TEMP_REF_C = 25.0


def _solar_temp_factor(s_mat: dict, temp_c: float) -> float:
    """η(T)/η_ref — linear datasheet derating around the 25 °C reference
    (NTU power.py convention), clamped to a physical band so an extreme
    cold excursion can't produce runaway efficiency."""
    k = s_mat.get("temp_coeff_per_k", -0.0045)
    return max(0.0, min(1.25, 1.0 + k * (temp_c - _SOLAR_TEMP_REF_C)))
_SOLAR_SIZE_TABLE = {
    "S":  {"area_m2_per_panel": 4.0,  "panel_count": 2},
    "M":  {"area_m2_per_panel": 8.0,  "panel_count": 2},
    "L":  {"area_m2_per_panel": 12.0, "panel_count": 2},
    "XL": {"area_m2_per_panel": 16.0, "panel_count": 4},
}

# Radiator coatings: ε (IR emission) + α (solar absorption) — the α/ε ratio
# is the core thermal-control design number. Values are standard coating data
# (bare aluminum, S13G-class white paint, quartz OSR, graphite/black).
_RAD_MAT_TABLE = {
    "Aluminum":   {"emissivity": 0.10, "absorptivity": 0.25, "density_kg_m2": 4.0},
    "WhitePaint": {"emissivity": 0.85, "absorptivity": 0.25, "density_kg_m2": 4.4},
    "OSR":        {"emissivity": 0.92, "absorptivity": 0.08, "density_kg_m2": 4.6},
    "Graphite":   {"emissivity": 0.96, "absorptivity": 0.90, "density_kg_m2": 3.6},
}
_RAD_SIZE_TABLE = {
    "Compact":  {"area_m2_per_panel": 1.0},
    "Standard": {"area_m2_per_panel": 2.0},
    "Wide":     {"area_m2_per_panel": 4.0},
}
_RAD_PANELS_PER_SAT = 2

# Battery chemistry: gravimetric energy density (Wh/kg) + round-trip
# efficiency. Effective pack capacity = mass (size tier) × density, so a
# denser chemistry or a bigger pack both raise Wh; efficiency taxes charging.
_BATT_MAT_TABLE = {
    "LiIon":      {"density_wh_kg": 250.0, "efficiency": 0.95},
    "LiFePO4":    {"density_wh_kg": 160.0, "efficiency": 0.96},
    "LiS":        {"density_wh_kg": 400.0, "efficiency": 0.90},
    "SolidState": {"density_wh_kg": 350.0, "efficiency": 0.97},
}
_BATT_SIZE_TABLE = {
    "S":  {"mass_kg": 10.0},
    "M":  {"mass_kg": 20.0},
    "L":  {"mass_kg": 32.0},
    "XL": {"mass_kg": 60.0},
}


def _batt_capacity_wh(cfg) -> float:
    m = _BATT_MAT_TABLE.get(cfg.battery_material, _BATT_MAT_TABLE["LiIon"])
    s = _BATT_SIZE_TABLE.get(cfg.battery_size, _BATT_SIZE_TABLE["L"])
    return s["mass_kg"] * m["density_wh_kg"]


def _batt_efficiency(cfg) -> float:
    return _BATT_MAT_TABLE.get(cfg.battery_material, _BATT_MAT_TABLE["LiIon"])["efficiency"]


# ---------------------------------------------------------------------------
# Payload bay — per-slot GPU loadout (satellite builder step 3).
#
# `SatelliteConfig.gpu_slots` fits an individual card model into each rack slot
# of the chosen platform, so a bay can hold H100s and B200s at once. Everything
# downstream works off (card type, count) GROUPS: an empty slot list yields one
# group and collapses to exactly the pre-per-slot single-GPU arithmetic.
# ---------------------------------------------------------------------------
def _slot_groups(cfg: SatelliteConfig, fallback_gpu: str,
                 fallback_count: int) -> list[tuple[str, int]]:
    """The fitted cards as homogeneous (type, count) groups, largest first."""
    fitted = [s for s in (cfg.gpu_slots or []) if s]
    if not fitted:
        return [(fallback_gpu, max(1, int(fallback_count)))]
    counts: dict[str, int] = {}
    for s in fitted:
        counts[s] = counts.get(s, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _group_operating_point(gpu_id: str, job_key: str, util: float, n: int,
                           t_struct_c: Optional[float]):
    """(typed-job detail, realized watts per card) for ONE homogeneous group.

    The single place the EPS budget curve lives, so the live tick, the design
    check and workload_adaptation can never drift apart."""
    gpu = _GPU_TABLE.get(gpu_id, _GPU_TABLE["H100"])
    cap_w = gpu["tdp_w"] * (_IDLE_FRAC + (1.0 - _IDLE_FRAC) * util)
    det = _ai.job_detail(gpu_id, job_key, util, cap_w, n, t_struct_c=t_struct_c)
    # LLM blocks come back with the REALIZED draw (decode sits below the cap on
    # the bandwidth plateau); everything else spends its budget.
    card_w = (det.power_w_per_gpu
              if det is not None and det.engine == "analytic" else cap_w)
    return det, card_w


def _bay_job_detail(groups: list[tuple[str, int]], job_key: str, util: float,
                    t_struct_c: Optional[float]):
    """Resolve the active job across a possibly-MIXED payload bay.

    Each distinct card type is its OWN tensor-parallel group — llm_perf's
    ideal-TP algebra holds across identical silicon sharing a model, not across
    H100s and B200s — so the satellite aggregate is the sum over groups while
    the per-GPU columns become card-count-weighted means. A homogeneous bay has
    one group and returns its detail untouched.

    Returns (merged detail or None, total payload watts)."""
    per_group: list[tuple[str, int, Any]] = []
    payload_w = 0.0
    for gpu_id, n in groups:
        det, card_w = _group_operating_point(gpu_id, job_key, util, n, t_struct_c)
        payload_w += card_w * n
        per_group.append((gpu_id, n, det))
    # An unknown job key resolves to None for every group alike (the job table
    # is GPU-independent) — report no detail, exactly as the single-GPU path.
    if not per_group or any(d is None for _, _, d in per_group):
        return None, payload_w
    if len(per_group) == 1:
        return per_group[0][2], payload_w

    total = sum(n for _, n, _ in per_group)

    def wavg(pick) -> float:
        return sum(pick(d) * n for _, n, d in per_group) / total

    base = per_group[0][2]                  # the largest group (sorted above)
    return base.model_copy(update={
        "gpu_count": total,
        "mfu": round(wavg(lambda d: d.mfu), 3),
        "power_w_per_gpu": round(wavg(lambda d: d.power_w_per_gpu), 1),
        "heat_w_per_gpu": round(wavg(lambda d: d.heat_w_per_gpu), 1),
        "tflops_per_gpu": round(wavg(lambda d: d.tflops_per_gpu), 1),
        "throughput_per_gpu": round(wavg(lambda d: d.throughput_per_gpu), 1),
        "throughput_total": round(sum(d.throughput_total for _, _, d in per_group), 1),
        # The analytic columns only mean something when EVERY group solved
        # analytically — one MFU-path group degrades the whole readout.
        "engine": ("analytic" if all(d.engine == "analytic" for _, _, d in per_group)
                   else "mfu"),
        "power_cap_w": round(wavg(lambda d: d.power_cap_w), 1),
        "freq_frac": round(wavg(lambda d: d.freq_frac), 3),
        # Alarms care about the HOTTEST die, not the average one.
        "gpu_die_temp_c": round(max(d.gpu_die_temp_c for _, _, d in per_group), 1),
        "thermal_throttled": any(d.thermal_throttled for _, _, d in per_group),
        "thermal_runaway": any(d.thermal_runaway for _, _, d in per_group),
        "mix": [GpuMixItem(gpu=g, count=n,
                           power_w_per_gpu=d.power_w_per_gpu,
                           heat_w_per_gpu=d.heat_w_per_gpu,
                           tflops_per_gpu=d.tflops_per_gpu,
                           throughput_per_gpu=d.throughput_per_gpu,
                           throughput_total=d.throughput_total)
                for g, n, d in per_group],
    }), payload_w


def _peak_card_watts(groups: list[tuple[str, int]]) -> float:
    """Worst-case payload draw: every fitted card at 100 % duty."""
    return sum(_GPU_TABLE.get(g, _GPU_TABLE["H100"])["tdp_w"] * n for g, n in groups)


def _unit(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


# Sun direction used ONLY before the first physics tick (the class-level
# default of StateEngine._sun_unit_eci; every tick overwrites it with
# geodyn's analytic Sun for that instant). It used to be the hard-coded
# legacy triple (0.648, -0.648, 0.398) — a made-up sun 141° from the real
# one at the demo epoch — which meant a snapshot read before the engine
# started reported nonsense lighting. Read the real Sun at mission start
# instead; there is no reason for a constant here.
_SUN_UNIT = _consts.sun_unit_at(0.0)


_SOLAR_CONSTANT_W_M2 = 1361.0
# Sun-tracking array model: pointing/temperature losses while tracking, and
# the sunlit fraction of a LEO orbit under the scene's fixed sun direction
# (measured 0.52 for single_iss with the engine's own propagator; 0.5 is the
# slightly conservative design number). solar_supply_avg_w and the per-tick
# solar_input_w now use the SAME model, so the design-check margins match
# what the simulation actually delivers.
_POINTING_EFF    = 0.95
#: How many per-sat ECI positions ride the 1 Hz broadcast (see
#: FleetSnapshot.fleet_eci_km). 256 matches the web globe's sprite cap, so
#: everything actually drawn is ground truth and only the undrawn tail is
_FLEET_ECI_CAP   = 256
_SUNLIT_FRACTION = 0.5


def _panel_incidence(mode: str,
                     r_km: tuple[float, float, float],
                     v_km_s: tuple[float, float, float],
                     sun_unit: tuple[float, float, float],
                     dawn_dusk: bool = False) -> float:
    """Panel-normal · Sun incidence 0..1 for ONE spacecraft flown in `mode` —
    the physical coupling between where the body points and how much sunlight
    the arrays actually collect:

      sun-pointing   → 1                  (whole body slews at the Sun)
      free (default) → |sin β| — array fixed on the orbit normal n̂ = r̂×v̂,
                       so incidence is |n̂·ŝ|, the sine of the Sun's elevation
                       above the orbit plane
      nadir          → panels ride the local vertical r̂: max(0, r̂·ŝ)
      velocity (ram) → panels along-track v̂:            max(0, v̂·ŝ)
      inertial       → panels on the orbit normal r̂×v̂:  max(0, n̂·ŝ)

    WHY 'free' is |sin β| and not a constant: a constant said every sunlit
    satellite in a constellation collects identically, which collapsed the
    solar histogram to two spikes (in shadow / full) and hid the geometry the
    chart exists to show. Mounting the array on the orbit normal is also what
    makes a dawn-dusk orbit power-optimal for real — there the Sun sits ~70°
    above the orbit plane, so the array faces it for the whole revolution
    (|sin 71°| = 0.95), while an i=53° Walker plane with the Sun near its
    orbit plane sees the same array edge-on. That contrast IS the physics;
    a constant erased it.

    Note |·|: the array collects on whichever face the Sun is on, so a
    negative β (Sun below the orbit plane) is as good as a positive one.

    Every mode except 'sun' now reads geometry, so a fleet needs BOTH
    position and velocity to be evaluated.

    Eclipse is NOT applied here. Multiply by the visible solar-disc fraction
    (geodyn.sun_visible_fraction) to get the collected fraction of peak.

    This is THE array model: the tracked satellite (_solar_incidence), the
    whole-fleet harvest (_tick_fleet) and the solar histogram all call it, so
    the fleet can no longer fly a different array than the sat it reports."""
    if mode == "sun":
        return 1.0
    if mode == "free":
        # Array fixed normal to the orbit plane; |sin β|. `dawn_dusk` no longer
        # forces 1.0 — a genuine dawn-dusk orbit earns ~0.95 from this geometry
        # on its own, and forcing it made the one built-in preset (whose RAAN is
        # hard-coded 6°, β = -34.8°, nowhere near the terminator) report a power
        # it does not physically have.
        return abs(_dot(_unit(_cross(r_km, v_km_s)), sun_unit))
    if mode == "velocity":
        n = _unit(v_km_s)
    elif mode == "inertial":
        n = _unit(_cross(r_km, v_km_s))
    else:                       # 'nadir' — and any unknown mode falls back
        n = _unit(r_km)         # to the local vertical, as before
    return max(0.0, _dot(n, sun_unit))


def _thermal_env_in_w(alpha: float, epsilon: float, area_m2: float,
                      r_km: float, s_w_m2: float, illum: float,
                      cos_zen: float) -> float:
    """Environmental heat absorbed by the radiating surfaces (W): direct
    solar on the convex-body mean projected area (A/4), Earth albedo and
    Earth IR through the Earth-disc view factor. Mirrors the STK SEET
    isothermal model (benchmarked to <0.2 K in eclipse segments)."""
    f = _geodyn.earth_view_factor(max(r_km, _geodyn.R_EARTH_THERMAL_KM))
    q_sun = alpha * s_w_m2 * illum * (area_m2 / 4.0)
    q_alb = alpha * _geodyn.EARTH_ALBEDO * s_w_m2 * area_m2 * f * max(0.0, cos_zen)
    q_ir = epsilon * _geodyn.EARTH_IR_W_M2 * area_m2 * f
    return q_sun + q_alb + q_ir

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
    """Total radiating area. Most architectures fly 2 panels × 2 faces;
    the redwire bay carries a SINGLE +Z panel (2 faces)."""
    long_m = geom.radiator_long * _BACKBONE_SCALE
    short_m = (geom.radiator_long / max(0.1, geom.radiator_ratio)) * _BACKBONE_SCALE
    panels = 1.0 if getattr(geom, "architecture", "truss") == "redwire" else 2.0
    return panels * 2.0 * long_m * short_m


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
    # Sun/eclipse state refreshed by _set_tracked_kinematics each tick; the
    # class-level defaults only cover reads before the first tick.
    _sun_unit_eci: tuple[float, float, float] = _SUN_UNIT
    _solar_illum: float = 1.0
    _solar_s_w_m2: float = _SOLAR_CONSTANT_W_M2

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
        # Tick-owned whole-fleet solar GEOMETRY: Σ over sats of
        # (visible solar-disc fraction × panel incidence), dimensionless
        # "sats' worth of peak array". Watts = this × _array_scale_w(), so
        # the fleet harvest can be re-scaled on every read without
        # re-propagating the constellation.
        self._fleet_solar_geom: float = 0.0
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
        # Live what-if comparison (compare_sim.LiveCompareSession, duck-typed
        # to avoid a circular import). The tick steps it in lockstep; the
        # snapshot carries its per-variant samples on StatePacket.compare_live.
        self._compare_session: Optional[Any] = None
        # Ground-station marker (Overview) — None until first set; the fleet
        # tick fills its live visibility fields while enabled.
        self._ground_target: Optional[GroundTargetState] = None
        # Tracked satellite's ECI velocity (km/s) — refreshed with position;
        # feeds the attitude/solar geometry (ram + orbit-normal pointing).
        self._tracked_vel_km_s: tuple[float, float, float] = (0.0, 0.0, 0.0)

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
        # Rebuild the telemetry state. Battery capacity is DERIVED from the
        # (reset-surviving) config, so re-seed it here for the immediate
        # snapshot; the tick re-derives it each step anyway.
        self._sat = SatelliteState()
        self._sat.battery_capacity_wh = _batt_capacity_wh(self._config)
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
        if "gpu_slots" in cleaned:
            # [] clears the per-slot loadout back to "uniform `gpu` × count" —
            # that is what every design preset's config carries.
            slots = [s or None for s in cleaned["gpu_slots"]]
            if len(slots) > _MAX_GPU_SLOTS:
                raise ValueError(f"at most {_MAX_GPU_SLOTS} payload slots")
            if slots and not any(slots):
                raise ValueError("at least one payload slot must be fitted")
            cleaned["gpu_slots"] = slots
        elif "gpu" in cleaned and self._config.gpu_slots:
            # The plain GPU dropdown (and the compare `gpu` dimension) re-fit
            # the WHOLE bay: every populated slot takes the new card. Without
            # this the authoritative slot list would silently swallow the edit.
            cleaned["gpu_slots"] = [cleaned["gpu"] if s else None
                                    for s in self._config.gpu_slots]
        self._config = self._config.model_copy(update=cleaned)
        # Pydantic re-validates via model_validate to ensure literals are
        # actually one of the allowed enum strings (model_copy alone does not).
        self._config = SatelliteConfig.model_validate(self._config.model_dump())
        # A per-slot loadout is authoritative: it fixes the card count and the
        # reported primary GPU (its largest group), so every legacy consumer of
        # `gpu` / `gpu_count` keeps telling the truth about a mixed bay.
        if self._config.gpu_slots:
            groups = _slot_groups(self._config, self._config.gpu, self._gpu_count)
            self._gpu_count = sum(n for _, n in groups)
            if groups[0][0] != self._config.gpu:
                self._config = self._config.model_copy(update={"gpu": groups[0][0]})
        # Echo the fitted count NOW, not on the next tick: the handler
        # broadcasts immediately after this call, and a packet claiming eight
        # cards for a bay that just went down to five is simply wrong.
        self._sat.gpu_count = self._gpu_count
        # Battery capacity is derived from the (material, size) config — keep
        # the reported value fresh for the immediate broadcast.
        self._sat.battery_capacity_wh = _batt_capacity_wh(self._config)
        self._demand_cache = None
        if mark_custom and cleaned:
            self._design_id = "custom"
        return self._config

    def _gpu_groups(self) -> list[tuple[str, int]]:
        """The fitted payload as (card type, count) groups — one group for the
        classic uniform loadout, one per distinct model for a built bay."""
        return _slot_groups(self._config, self._config.gpu, self._gpu_count)

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
    def asset_id(self) -> str:
        """Which vendor platform (satellite_assets.py) the satellite flies on.
        DERIVED from the hull — the architecture is what actually distinguishes
        the platforms, so this can never drift out of sync with the model in
        the viewport (a design preset on a truss really is the SpaceX bus).
        "" for twin_truss / blanket, which no catalogued platform sells."""
        return _assets.asset_for_architecture(self._twin_geometry.architecture)

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
    _ATTITUDE_MODES = get_args(AttitudeMode)   # single source of truth

    def set_attitude_spin(self, action: str, axis: str = "z") -> dict:
        """Reaction-wheel demo: start/stop/toggle a slow 360° body rotation
        about any of the centre-of-mass X/Y/Z axes (axes combine into a
        tumble). Rate is a legible 1 rpm (6°/s) per axis; Kit integrates
        the angles per frame. Display-only — the sun-tracking power model
        is unaffected. Touching a wheel drops out of any fixed pointing
        mode back to 'free'."""
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
        # Manual wheel control is mutually exclusive with a pointing mode.
        self._sat.attitude_mode = "free"
        return {"action": action, "axis": axis, "spin_dps": rates,
                "attitude_mode": "free"}

    def set_attitude_mode(self, mode: str) -> dict:
        """Set a fixed attitude pointing mode (or 'free'). A non-free mode
        zeroes the reaction wheels — the Kit close-up then orients the body
        to the target instead of tumbling. Raises ValueError on unknown
        modes."""
        mode = str(mode).lower()
        if mode not in self._ATTITUDE_MODES:
            raise ValueError(f"unknown attitude mode {mode!r}")
        self._sat.attitude_mode = mode
        if mode != "free":
            self._sat.attitude_spin_dps = (0.0, 0.0, 0.0)
        return {"attitude_mode": mode,
                "spin_dps": list(self._sat.attitude_spin_dps)}

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
        groups = self._gpu_groups()
        key = (profile_id, tuple(groups), self._platform_power_w)
        if self._demand_cache is not None and self._demand_cache[0] == key:
            return self._demand_cache[1]
        sched = _profile(profile_id)["schedule"]
        total_dt = sum(d for _, d, _, _ in sched) or 1.0
        demand = 0.0
        for _, dur, util, job_key in sched:
            _, payload_w = _bay_job_detail(groups, job_key, util, 25.0)
            demand += (payload_w + self._platform_power_w) * dur / total_dt
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
        s_mat = _SOLAR_MAT_TABLE.get(cfg.solar_material, _SOLAR_MAT_TABLE["Si"])
        r_mat = _RAD_MAT_TABLE.get(cfg.radiator_material, _RAD_MAT_TABLE["Aluminum"])
        geom = self._twin_geometry
        groups = self._gpu_groups()
        platform_w = self._platform_power_w

        total_dt = sum(d for _, d, _, _ in sched) or 1.0
        avg_util = sum(d * u for _, d, u, _ in sched) / total_dt
        peak_solar_w = s_mat["efficiency"] * _solar_area_m2(geom) * _SOLAR_CONSTANT_W_M2
        supply_avg_w = peak_solar_w * self._orbit_avg_incidence() * _SUNLIT_FRACTION

        thermal_peak_w = (_peak_card_watts(groups) + platform_w) * 0.95
        # Same emission-ceiling model as the live design check: capacity at
        # +60 °C minus the worst-case environmental load (full sun, subsolar).
        SIGMA = 5.67e-8
        rad_area = _radiator_area_m2(geom)
        # `or ()` so the fallback below actually fires: on the /satellite_build
        # /preview DRY-RUN probe the engine is never ticked, so sat_xyz_km is
        # None (not a zero vector) and `sum(c * c for c in None)` raised
        # TypeError before the `or` could be reached — 500ing the endpoint that
        # fills the builder's workload list, which the UI then reported as
        # "backend offline".
        r_km = (math.sqrt(sum(c * c for c in (self._sat.sat_xyz_km or ())))
                or (_geodyn.WGS84_A_KM + 550.0))
        q_env_worst = _thermal_env_in_w(
            r_mat.get("absorptivity", 0.25), r_mat["emissivity"], rad_area,
            r_km, self._solar_s_w_m2, 1.0, 1.0)
        thermal_emit_w = max(
            0.0,
            r_mat["emissivity"] * SIGMA * rad_area * (333.15) ** 4 - q_env_worst)

        # Demand side: the shared schedule-average (per-block analytic
        # realized draw for LLM blocks at the 25 °C no-throttle baseline) —
        # the exact number the live design check uses, so verdicts here can
        # never contradict the standing alarm.
        demand_avg_w = self._schedule_demand_avg_w(profile_id)

        tokens = frames = 0.0
        kwh = 0.0
        for _, dur, util, job_key in sched:
            det, payload_w = _bay_job_detail(groups, job_key, util, 25.0)
            if det is not None:
                if det.throughput_unit == "tok/s":
                    tokens += det.throughput_total * dur
                elif det.throughput_unit == "frames/s":
                    frames += det.throughput_total * dur
            kwh += (payload_w + platform_w) * dur / 3.6e6

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
        self._sat.gpu_count = self._gpu_count
        self._reset_workload_totals()
        # Battery capacity is derived from the preset's (material, size)
        # config (set via set_config above); keep the current charge fraction
        # so the switch doesn't teleport the SOC story.
        self._sat.battery_capacity_wh = _batt_capacity_wh(self._config)
        # Deployment state never carries over across designs. The redwire
        # roll-out array arrives STOWED (the just-separated look — press
        # Deploy and watch the blanket reel out); rigid-wing designs arrive
        # fully deployed as before.
        stowed = getattr(preset, "architecture", "truss") == "redwire"
        self._solar_deploy_target = 0.0 if stowed else 1.0
        self._sat.solar_deploy_frac = 0.0 if stowed else 1.0
        self._design_id = preset.id
        return geom

    def apply_build(self, asset: Any, *, config_patch: dict[str, Any],
                    geometry_patch: dict[str, Any],
                    gpu_slots: list[Optional[str]],
                    workload_profile: str,
                    attitude_mode: Optional[str] = None) -> TwinGeometry:
        """Commission a satellite the user BUILT: vendor platform + structure
        design + per-slot payload + job schedule, applied in one shot (the
        handler then regenerates the USD and bumps the version so Kit
        reloads). `asset` is a satellite_assets.SatelliteAsset.

        The hull comes from the asset — a build can reshape the wings and the
        radiators, not turn a dish into a truss. Unlike a design preset the
        result is by definition hand-made, so `design_id` degrades to custom
        while `asset_id` records which platform it was built on."""
        if len(gpu_slots) > asset.slot_count:
            raise ValueError(f"{asset.name} has {asset.slot_count} payload slots")
        # Short lists are legal (the UI always sends a full bay) — pad so the
        # stored loadout always describes the whole platform.
        slots: list[Optional[str]] = list(gpu_slots) + \
            [None] * (asset.slot_count - len(gpu_slots))
        if not any(slots):
            raise ValueError("at least one payload slot must be fitted")

        self.set_config({**config_patch, "gpu_slots": slots}, mark_custom=False)
        geom = self.set_twin_geometry({**geometry_patch,
                                       "architecture": asset.architecture},
                                      mark_custom=False)
        self.set_workload_profile(workload_profile, mark_custom=False)
        self._platform_power_w = float(asset.platform_power_w)
        self._sat.battery_capacity_wh = _batt_capacity_wh(self._config)
        if attitude_mode is not None:
            self.set_attitude_mode(attitude_mode)
        # A commissioned satellite flies with its array out — the roll-out
        # blanket's stowed-on-arrival beat belongs to the design gallery, not
        # to a build the user just pressed Run on.
        self._solar_deploy_target = 1.0
        self._sat.solar_deploy_frac = 1.0
        self._design_id = "custom"
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

    # ---- ground-station target + comms config (Overview) ----
    def set_ground_target(self, enabled: bool, name: str = "Singapore",
                          lat: float = 1.3521, lon: float = 103.8198,
                          elevation_mask_deg: float = 10.0,
                          band: str = "X", solar_bin: int = 10,
                          ) -> Optional[GroundTargetState]:
        """Mark (or clear) the ground station and its comms config. The
        effective elevation mask is max(user mask, the band's minimum); the
        band sets per-sat throughput; solar_bin (5 or 10) sizes the solar
        histogram. While enabled the fleet tick computes visibility,
        bandwidth, the elevation CDF and the solar histogram each second."""
        if not enabled:
            self._ground_target = None
            return None
        band_info = _consts.get_band(band)
        band_id = band if band in _consts.COMMS_BANDS else _consts.DEFAULT_BAND
        user_mask = max(0.0, min(60.0, float(elevation_mask_deg)))
        eff_mask = max(user_mask, float(band_info["min_elevation_deg"]))
        self._ground_target = GroundTargetState(
            enabled=True, name=str(name),
            lat=max(-90.0, min(90.0, float(lat))),
            # Longitude is periodic — wrap (a clamp would silently move a
            # 0..360-convention input thousands of km).
            lon=((float(lon) + 180.0) % 360.0) - 180.0,
            elevation_mask_deg=user_mask,
            band=band_id,
            band_label=band_info["label"],
            band_mbps_per_sat=float(band_info["per_sat_mbps"]),
            solar_bin=5 if int(solar_bin) == 5 else 10,
            min_elevation_deg=eff_mask,
        )
        # Fill the live analytics right away (works while paused).
        self._refresh_fleet_now()
        return self._ground_target

    @property
    def ground_target(self) -> Optional[GroundTargetState]:
        return self._ground_target

    # ---- live what-if comparison ----
    def set_compare_session(self, session: Optional[Any]) -> None:
        """Attach (or clear, with None) the live comparison. The session must
        expose step(dt) and payload(); it is stepped on the tick right after
        the live physics update, so variants stay in lockstep with the
        satellite — pausing the sim pauses the comparison too."""
        self._compare_session = session

    @property
    def compare_session(self) -> Optional[Any]:
        return self._compare_session

    def set_constellation(self, preset_id: str) -> bool:
        """Switch the active constellation. Refreshes the fleet snapshot
        immediately (not just on the next tick) so the caller's broadcast —
        and GET /state while PAUSED — already carry the new constellation.
        Returns False if the preset id is unknown."""
        if _consts.get_preset(preset_id) is None:
            return False
        self._constellation_id = preset_id
        self._refresh_fleet_now()
        return True

    def _refresh_fleet_now(self) -> None:
        """Run the fleet part of the tick once at the current sim time —
        used by mutators (constellation switch, ground target) so their
        derived snapshot fields are fresh in the very next broadcast even
        when the sim is paused. Integration state is untouched."""
        try:
            self._set_tracked_kinematics(self._tick_fleet(self._sim_time_s),
                                         self._sim_time_s)
        except Exception:
            log.exception("fleet refresh on mutation failed")

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

        # Live osculating classical elements from the same SGP4 state the
        # display flies (NTU OE/RV layer — services/elements.py). Cheap
        # closed-form; None on degenerate states (sgp4 error sentinel).
        try:
            oe = _elements.rv_to_oe(pos_km, self._tracked_vel_km_s)
            a = oe["a_km"]
            self._sat.orbital_elements = OrbitalElements(
                semi_major_axis_km=a,
                eccentricity=oe["e"],
                inclination_deg=math.degrees(oe["inc_rad"]),
                raan_deg=math.degrees(oe["raan_rad"]),
                arg_periapsis_deg=math.degrees(oe["argp_rad"]),
                true_anomaly_deg=math.degrees(oe["nu_rad"]),
                period_s=_elements.period_s(a),
                apogee_alt_km=a * (1.0 + oe["e"]) - _geodyn.WGS84_A_KM,
                perigee_alt_km=a * (1.0 - oe["e"]) - _geodyn.WGS84_A_KM,
            )
        except (ValueError, ZeroDivisionError):
            self._sat.orbital_elements = None

        # Real Sun + conical Earth-shadow geometry (STK-benchmarked): analytic
        # Sun at the absolute epoch (mission start + t × TIME_SCALE), visible
        # solar-disc fraction through umbra/penumbra, and true solar
        # irradiance at the current Earth-Sun distance.
        sun_km, r_au = _geodyn.sun_teme(_timebase.jd_utc_at(t))
        sn = math.sqrt(sun_km[0] ** 2 + sun_km[1] ** 2 + sun_km[2] ** 2) or 1.0
        self._sun_unit_eci = (sun_km[0] / sn, sun_km[1] / sn, sun_km[2] / sn)
        self._solar_s_w_m2 = _SOLAR_CONSTANT_W_M2 / (r_au * r_au)
        illum = _geodyn.sun_visible_fraction((x_km, y_km, z_km), sun_km)
        self._solar_illum = illum
        self._sat.solar_illum = illum
        r_norm = max(1e-6, math.sqrt(x_km * x_km + y_km * y_km + z_km * z_km))
        cos_a = (x_km * self._sun_unit_eci[0] + y_km * self._sun_unit_eci[1]
                 + z_km * self._sun_unit_eci[2]) / r_norm
        self._sat.sunlit = illum >= 0.5  # majority of the solar disc visible
        # Normalised incidence for the Kit Sun driver — 0 in eclipse, 1 at
        # solar noon. Same cos_a the solar-input model uses.
        self._sat.sun_factor = max(0.0, cos_a) if self._sat.sunlit else 0.0
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
            self._solar_illum = 1.0
            self._sat.solar_illum = 1.0
        return cos_a

    def _solar_incidence(self) -> float:
        """Panel-normal · Sun incidence 0..1 for the tracked satellite's
        CURRENT attitude: the shared _panel_incidence model on this sat's live
        geometry, hard-zeroed in eclipse (sunlit = majority of the solar disc
        visible). Every fleet member is scored by the same function."""
        sat = self._sat
        if not sat.sunlit:
            return 0.0
        return _panel_incidence(sat.attitude_mode, sat.sat_xyz_km,
                                self._tracked_vel_km_s, self._sun_unit_eci,
                                sat.is_dawn_dusk)

    def _orbit_avg_incidence(self) -> float:
        """Orbit-averaged panel incidence for the CURRENT attitude, used by the
        design check and the workload fit verdicts.

        For 'free' (array on the orbit normal) and 'sun' the incidence does not
        vary around the revolution, so the live value IS the orbit average. The
        body-fixed modes sweep a cosine and average to 1/pi of their peak over
        the sunlit arc; falling back to the live sample there would make the
        verdict swing with where the satellite happens to be right now."""
        mode = self._sat.attitude_mode
        if mode in ("sun", "free"):
            live = self._sat.solar_incidence
            if live > 0.0:
                return live
            # Pre-first-tick (or eclipsed): recompute from geometry if we can.
            pos, vel = self._sat.sat_xyz_km, self._tracked_vel_km_s
            if mode == "sun":
                return 1.0
            if pos and vel:
                return _panel_incidence("free", pos, vel, self._sun_unit_eci)
            return _POINTING_EFF
        return 1.0 / math.pi

    def _array_scale_w(self) -> float:
        """The NON-geometric half of the array chain, in watts of peak: cell
        η × deployed area × true irradiance at the current Earth–Sun distance
        × the η(T) datasheet derate at the structure temperature × the
        roll-out deployment fraction.

        Multiplied by (visible solar-disc fraction × _panel_incidence) it
        gives collected watts. The tracked satellite and every fleet member
        share it, because the constellation flies the ACTIVE design — so a
        one-satellite fleet's solar_total_w is identically its solar_input_w."""
        s_mat = _SOLAR_MAT_TABLE.get(self._config.solar_material,
                                     _SOLAR_MAT_TABLE["Si"])
        return (s_mat["efficiency"] * _solar_area_m2(self._twin_geometry)
                * self._solar_s_w_m2
                * _solar_temp_factor(s_mat, self._sat.temperature_c)
                * self._sat.solar_deploy_frac)

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
            pos, self._tracked_vel_km_s = _consts.propagate_tracked_rv(preset, t)
        except Exception:  # noqa: BLE001 — display-only; keep last values
            return
        if pos == (0.0, 0.0, 0.0):
            return
        self._set_tracked_kinematics(pos, t)
        # Keep the power triplet (sunlit, solar_input_w, battery_charge_w)
        # self-consistent on eclipse-boundary reads: the fresh sunlit flag
        # would otherwise contradict last tick's solar input for up to 1 s
        # (sunlit=False with panels still "producing"). Same formulas as the
        # tick — including the attitude incidence + deployment fraction —
        # reusing the tick-owned load.
        incidence = self._solar_incidence()
        self._sat.solar_incidence = incidence
        scale_w = self._array_scale_w()
        solar_w = scale_w * incidence * self._solar_illum
        self._sat.solar_input_w = solar_w
        self._sat.battery_charge_w = solar_w - (self._sat.payload_power_w
                                                + self._sat.platform_power_w)
        # Re-scale the fleet harvest onto the SAME array chain this read just
        # used for the tracked sat. Fleet GEOMETRY stays tick-owned (1 Hz,
        # Σ illum×incidence over the constellation); only the shared
        # non-geometric scale is refreshed here, so the Overview energy chart
        # and the satellite card can never disagree about irradiance,
        # temperature or deployment.
        self._fleet_snapshot.solar_total_w = round(
            self._fleet_solar_geom * scale_w, 1)

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
            asset_id=self.asset_id,
            workload_profile=self._workload_profile,
            compare_live=(self._compare_session.payload()
                          if self._compare_session is not None else None),
            ground_target=(self._ground_target.model_copy()
                           if self._ground_target is not None else None),
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
            # Live comparison: step every variant in lockstep with the tick.
            # A failing session is dropped rather than allowed to kill the
            # loop — the live satellite always outranks a what-if.
            if self._compare_session is not None:
                try:
                    self._compare_session.step(dt)
                except Exception:
                    log.exception("compare session step failed — comparison stopped")
                    self._compare_session = None
            # Anchor for on-read fractional-time kinematics refreshes.
            self._last_tick_wall = time.monotonic()
            try:
                await _maybe_await(self._on_state(self.snapshot()))
            except Exception:
                log.exception("state broadcast failed")

    def _tick_fleet(self, t: float) -> tuple[float, float, float]:
        """Per-tick fleet bookkeeping: SGP4-propagate every sat of the active
        constellation, refresh the aggregate FleetSnapshot + the per-sat
        lat/lon cache (mission cast picking), and return the TRACKED
        satellite's ECI position (plane 0, sat 0 — the reference sat the
        legacy 14-param card follows). Overridden by the offline compare
        simulator (compare_sim._OfflineTwin) to propagate only the tracked
        sat on a private Satrec — the downstream physics is untouched."""
        preset = _consts.get_preset(self._constellation_id) or _consts.get_preset("single_iss")
        # Position AND velocity per sat: the ram/orbit-normal panel modes
        # project onto v̂ and r̂×v̂, so the fleet power model needs the
        # velocities sgp4 already computes (propagate_fleet_rv). Fleet member 0
        # IS the tracked satellite (zero Walker offsets), so its velocity comes
        # from the same call instead of a second propagate_tracked_rv.
        fleet_rv = _consts.propagate_fleet_rv(preset, t)
        fleet_pos_km = [pos for (pos, _v) in fleet_rv]
        self._tracked_vel_km_s = fleet_rv[0][1] if fleet_rv else (0.0, 0.0, 0.0)
        kpis = _consts.synthesize_kpis(preset, fleet_pos_km, t)

        # Whole-fleet instantaneous solar collection (the Overview energy
        # chart). Independent of any ground target, and it INCLUDES eclipse:
        # the visible fraction of the solar disc scales the panel incidence.
        # One extra pass over the state we already propagated — the same
        # per-sat factors feed the ground-target histogram below.
        #
        # The constellation flies the ACTIVE design, so every member is scored
        # by the SAME array model as the tracked satellite: _panel_incidence
        # for the commanded attitude (sun/free are orientation-independent
        # constants; nadir/velocity/inertial project r̂ / v̂ / r̂×v̂ onto ŝ)
        # times _array_scale_w for the non-geometric chain. This loop used to
        # hard-code max(0, r̂·ŝ) — a body-fixed NADIR array — no matter what
        # the satellite was actually flying. In a dawn-dusk SSO the Sun is
        # perpendicular to the orbit plane and r̂ lies in it, so r̂·ŝ ≈ 0 for
        # the whole orbit: the fleet aggregate read ~2% of peak on the orbit
        # that is in PERMANENT sunlight, while the sat card next to it
        # correctly read full power.
        jd_utc = _timebase.jd_utc_at(t)
        sun_km, _r_au = _geodyn.sun_teme(jd_utc)
        sx, sy, sz = sun_km
        s_norm = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
        sun_unit = (sx / s_norm, sy / s_norm, sz / s_norm)
        mode = self._sat.attitude_mode
        dawn_dusk = self._sat.is_dawn_dusk
        fleet_geom = 0.0
        solar_lit_sats = 0
        harvest_factors: list[float] = []
        for (pos, vel) in fleet_rv:
            if pos == (0.0, 0.0, 0.0):
                harvest_factors.append(0.0)   # sgp4-error sentinel
                continue
            inc = _panel_incidence(mode, pos, vel, sun_unit, dawn_dusk)
            illum = _geodyn.sun_visible_fraction(pos, sun_km)
            # Eclipse-AWARE collection factor. The histogram bins and sums this
            # same number, so an eclipsed sat lands in bin 0 collecting nothing
            # and the histogram's total is identically solar_total_w. Binning
            # the bare incidence instead would credit a satellite in full
            # shadow with the power its panel would have made in daylight.
            factor = illum * inc
            harvest_factors.append(factor)
            if illum <= 0.0:
                continue                      # full umbra — collects nothing
            solar_lit_sats += 1
            fleet_geom += factor
        self._fleet_solar_geom = fleet_geom
        # Watts now; /state reads re-scale this same geometry against the
        # live array chain (_refresh_display_kinematics).
        solar_total_w = fleet_geom * self._array_scale_w()

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
            design_rev=getattr(preset, "revision", 0),
            solar_total_w=round(solar_total_w, 1),
            solar_lit_sats=solar_lit_sats,
            # The sky frame for THIS tick: same instant (jd_utc), same frame
            # (TEME) as fleet_pos_km above. Broadcast so no renderer has to
            # invent a sun direction or start GMST at zero.
            sun_unit_teme=sun_unit,
            gmst_rad=_geodyn.gmst_rad(jd_utc),
            # Truth for the map / selector / globe. 0.1 km is far finer than
            # any display needs and keeps the packet small.
            fleet_eci_km=[(round(x, 1), round(y, 1), round(z, 1))
                          for (x, y, z) in fleet_pos_km[:_FLEET_ECI_CAP]],
        )

        # Cache per-sat lat/lon for mission cast picking (sensor = nearest AOI).
        fleet_lla = [
            orbit_catalog.eci_to_lat_lon_alt(px, py, pz, t)
            for (px, py, pz) in fleet_pos_km
        ]
        self._fleet_latlon = [(la, lo) for (la, lo, _al) in fleet_lla]

        # Ground-target visibility (Overview marker): reuse the sub-points
        # this loop just computed — elevation-angle test per sat, results
        # ride StatePacket.ground_target on the next snapshot.
        gt = self._ground_target
        if gt is not None and gt.enabled:
            # Same per-sat collection factors and array chain the harvest
            # above used, so the histogram's bins and its collection axis are
            # the physics — not a parallel visualisation model.
            a = _consts.ground_analytics(
                fleet_pos_km, fleet_lla, gt.lat, gt.lon,
                gt.min_elevation_deg, gt.band_mbps_per_sat,
                self._array_scale_w(), gt.solar_bin, harvest_factors,
            )
            gt.visible_sats = a["visible_sats"]
            gt.best_elevation_deg = a["best_elevation_deg"]
            gt.visible_indices = a["visible_indices"]
            gt.aggregate_mbps = a["aggregate_mbps"]
            gt.elevation_cdf = [ElevationCount(**c) for c in a["elevation_cdf"]]
            gt.solar_hist = [SolarHistBin(**b) for b in a["solar_hist"]]
        return fleet_pos_km[0] if fleet_pos_km else (0.0, 0.0, 0.0)

    def _update_placeholder_physics(self, dt: float) -> None:
        t = self._sim_time_s

        # --- Fleet: propagate + KPIs; returns the tracked sat's ECI position.
        cos_a = self._set_tracked_kinematics(self._tick_fleet(t), t)
        is_dawn_dusk = self._sat.is_dawn_dusk

        # --- Reconfigurable hardware lookups ----------------------------------
        cfg     = self._config
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
        # Incidence is now ATTITUDE-DEPENDENT (see _solar_incidence): a
        # sun-pointing body holds ~1 while sunlit; the default 'free' rides the
        # sun-tracking drive (SADA, _POINTING_EFF); a nadir/ram/inertial
        # body-fixed array projects panel_normal·ŝ and can fall to 0 even in
        # daylight, so the chosen attitude visibly changes generated power.
        # Dawn-dusk SSO: permanent full sun for sun/free.
        incidence = self._solar_incidence()
        self._sat.solar_incidence = incidence
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
        # True irradiance at the current Earth-Sun distance × the visible
        # solar-disc fraction (0 in umbra, partial through the penumbra)
        # × the cell's η(T) datasheet derating at the structure temperature
        # (single-node model: the panels share the bus temperature) — a hot
        # satellite now genuinely generates less, closing the thermal→power
        # loop alongside the thermal→compute one.
        # (_array_scale_w is exactly η · area · S(r) · η(T) · deployed fraction;
        # `frac` was written back to the sat just above, so this is the same
        # product as before — now shared verbatim with the fleet aggregate.)
        self._sat.solar_input_w = (self._array_scale_w() * incidence
                                   * self._solar_illum)

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
        # Operating point for the active block, resolved per card-type group of
        # the fitted bay (one group unless the builder mixed models). LLM jobs
        # run the ANALYTICAL engine (llm_perf via ai_workloads): the satellite
        # structure temperature is the GPU cold plate, the thermal limit
        # (T_throttle − T_struct)/R_th caps the DVFS budget, and the card's
        # REALIZED draw comes back out — so a hot structure visibly throttles
        # clocks, tokens/s AND electrical demand. Vision/idle jobs keep the
        # budget as the draw (MFU path).
        groups = self._gpu_groups()
        gpu_count = sum(n for _, n in groups)
        detail, payload_w = _bay_job_detail(groups, job_key, workload,
                                            self._sat.temperature_c)
        self._sat.workload_detail = detail
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
        # Capacity = pack mass (size tier) × chemistry energy density, and the
        # chemistry's round-trip efficiency taxes charging — so both the
        # battery material and size the user picks move the SOC story.
        cap_wh = _batt_capacity_wh(cfg)
        self._sat.battery_capacity_wh = cap_wh
        batt_eff = _batt_efficiency(cfg)
        # Net power into the battery. The round-trip loss is booked once, on
        # the charging leg: only `eff` of a surplus watt reaches stored energy;
        # discharge draws stored energy 1:1. So over a charge→discharge cycle
        # energy_out/energy_in = eff (a true round-trip efficiency, not eff²).
        # Reported charge_w is the raw electrical net.
        load_total_w = payload_w + platform_w
        net_w = self._sat.solar_input_w - load_total_w
        self._sat.battery_charge_w = net_w
        eff_net_w = net_w * batt_eff if net_w >= 0.0 else net_w
        PHYS_TIME_SCALE = 60.0   # 1 wall sec runs 60 sim sec of battery dynamics
        capacity_J = cap_wh * 3600.0
        d_soc = (eff_net_w * dt * PHYS_TIME_SCALE) / capacity_J
        self._sat.battery_soc = max(0.0, min(1.0, self._sat.battery_soc + d_soc))

        # --- Thermal (Stefan-Boltzmann, accelerated 60x) ----------------------
        # Heat in = electrical dissipation (payload + platform minus ~5% RF)
        # PLUS the orbital environment: direct solar absorption (coating α),
        # Earth albedo and Earth IR — so the temperature now swings with the
        # eclipse cycle like the STK SEET reference instead of sitting on a
        # fixed 250 K background.
        SIGMA = 5.67e-8             # W/m²K⁴ Stefan-Boltzmann
        epsilon = r_mat["emissivity"]
        alpha = r_mat.get("absorptivity", 0.25)
        T_K = self._sat.temperature_c + 273.15
        r_km = math.sqrt(sum(c * c for c in self._sat.sat_xyz_km)) or _geodyn.WGS84_A_KM
        q_env = _thermal_env_in_w(alpha, epsilon, radiator_area_m2, r_km,
                                  self._solar_s_w_m2, self._solar_illum,
                                  self._sat.sun_cos)
        Q_in = (payload_w + platform_w) * 0.95 + q_env
        Q_out = epsilon * SIGMA * radiator_area_m2 * T_K**4
        self._sat.radiator_power_w = max(0.0, Q_out)
        # Thermal mass — typical 200 kg sat with aluminum/structures: c_p ~ 800
        # J/kg·K, mass ~ 200 kg → 160 kJ/K. Picked here for legible dynamics.
        THERMAL_MASS_J_PER_K = 160_000.0
        dT_dt = (Q_in - Q_out) / THERMAL_MASS_J_PER_K
        T_K_new = T_K + dT_dt * dt * PHYS_TIME_SCALE
        # Soft clamp to plausible space-sat range.
        self._sat.temperature_c = max(-80.0, min(95.0, T_K_new - 273.15))

        # --- Downlink ---------------------------------------------------------
        # Real elevation-mask geometry against the configured ground target
        # (default Singapore / X-band) — replaces the sin(t/30) placeholder.
        gt = self._ground_target
        gs_lat = gt.lat if gt is not None else 1.3521
        gs_lon = gt.lon if gt is not None else 103.8198
        gs_mask = gt.min_elevation_deg if gt is not None else 10.0
        gs_mbps = gt.band_mbps_per_sat if gt is not None else 150.0
        elev = _consts.elevation_deg(self._sat.lat, self._sat.lon,
                                     self._sat.altitude_km, gs_lat, gs_lon)
        self._gs.visible = elev >= gs_mask
        self._sat.downlink_mbps = gs_mbps if self._gs.visible else 0.0
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
            solar_supply_avg_w = (peak_solar_w * self._orbit_avg_incidence()
                                  * _SUNLIT_FRACTION)

        # Thermal peak demand: worst case is sustained 100 % workload.
        thermal_peak_demand_w = (_peak_card_watts(groups) + platform_w) * 0.95
        # Thermal supply: emission capacity at the +60 °C safe-operating
        # ceiling minus the worst-case environmental load (full sun, subsolar
        # albedo) — same flux model the per-tick integration uses.
        T_max_K = 60.0 + 273.15
        q_env_worst = _thermal_env_in_w(alpha, epsilon, radiator_area_m2, r_km,
                                        self._solar_s_w_m2, 1.0, 1.0)
        thermal_max_emit_w = max(
            0.0,
            epsilon * SIGMA * radiator_area_m2 * T_max_K**4 - q_env_worst)

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
