"""Pydantic models for state packets and messages. Authoritative per docs/api_spec.md."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

OrbitType = Literal["LEO", "SSO", "MEO", "GEO"]
GpuType = Literal["H100", "H200", "B200", "MI300X"]
AttitudeMode = Literal["free", "sun", "nadir", "velocity", "inertial"]
Mode = Literal["on_orbit", "ground_only"]
TaskPhase = Literal[
    "idle", "created", "capturing", "inferencing",
    "packaging", "downlink", "delivered",
]


class GpuMixItem(BaseModel):
    """One homogeneous card group of a MIXED payload bay (per-slot GPU
    selection — see SatelliteConfig.gpu_slots). Each distinct card type is
    its own tensor-parallel group; the satellite-level detail below is the
    card-weighted merge of these."""
    gpu: str
    count: int
    power_w_per_gpu: float = 0.0
    heat_w_per_gpu: float = 0.0
    tflops_per_gpu: float = 0.0
    throughput_per_gpu: float = 0.0
    throughput_total: float = 0.0


class GpuJobDetail(BaseModel):
    """What the payload GPUs are ACTUALLY running this tick — the typed job
    from the active schedule block (ai_workloads.py) resolved against the
    fitted GPU's datasheet: achieved MFU, effective TFLOPS, model-level
    throughput, and per-card electrical/heat load."""
    job: str = "housekeeping"
    job_label: str = "Housekeeping / standby"
    model: str = "-"
    precision: str = "-"
    mfu: float = 0.0
    gpu_count: int = 8
    power_w_per_gpu: float = 0.0
    heat_w_per_gpu: float = 0.0
    tflops_per_gpu: float = 0.0
    throughput_per_gpu: float = 0.0
    throughput_total: float = 0.0
    throughput_unit: str = "-"
    # --- Analytical LLM engine (llm_perf.py) ---------------------------------
    # engine == "analytic": the numbers above come from the coupled
    # power-cap ∧ thermal-limit → DVFS frequency → tok/s solve, not the MFU
    # heuristic. "mfu" for vision/idle jobs and unknown GPU/model combos.
    engine: str = "mfu"
    exec_phase: str = "-"            # decode | prefill | train
    batch: int = 0                   # decode batch rows (0 when N/A)
    context: int = 0                 # effective KV context per row (tokens)
    power_cap_w: float = 0.0         # EPS budget handed to each card
    freq_frac: float = 0.0           # x = f_sm/f_max the governor settles at
    gpu_die_temp_c: float = 0.0      # junction temp via T_struct + P·R_th
    thermal_throttled: bool = False  # thermal limit is the binding constraint
    thermal_runaway: bool = False    # can't hold throttle target even parked
    t_mem_ms: float = 0.0            # frequency-immune memory floor per step
    t_comp_ms: float = 0.0           # frequency-scaled compute tail per step
    # --- Mixed payload bay ---------------------------------------------------
    # Populated ONLY when the fitted slots hold more than one card type: the
    # per-group breakdown behind the merged columns above. Empty for the
    # (normal) homogeneous loadout, where the columns are exact.
    mix: list[GpuMixItem] = Field(default_factory=list)


class WorkloadTotals(BaseModel):
    """Cumulative payload output since the active workload profile (or
    design) was applied — sim-time integration of the typed-job throughput.
    The 'what did I get for my watts' story: tokens generated, frames
    classified, and payload energy consumed."""
    tokens: float = 0.0
    frames: float = 0.0
    payload_kwh: float = 0.0
    duration_s: float = 0.0


class OrbitalElements(BaseModel):
    """Live osculating classical elements of the tracked satellite, derived
    each tick from the SGP4 position/velocity (services/elements.py — the
    NTU OE/RV layer). Degrees on the wire; singular cases resolved by the
    documented conventions (circular → argp=0, anomaly=argument of latitude;
    equatorial → raan=0), never NaN."""
    semi_major_axis_km: float = 0.0
    eccentricity: float = 0.0
    inclination_deg: float = 0.0
    raan_deg: float = 0.0
    arg_periapsis_deg: float = 0.0
    true_anomaly_deg: float = 0.0
    period_s: float = 0.0
    apogee_alt_km: float = 0.0
    perigee_alt_km: float = 0.0


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
    # Osculating classical elements at the current tick (None until the
    # first propagation). The orbit designer edits MEAN elements to build
    # TLEs; these are the instantaneous truth the propagator actually flies.
    orbital_elements: Optional[OrbitalElements] = None
    sunlit: bool = True
    # Normalised solar incidence, 0..1 = max(0, cos(angle between sat→sun
    # and the sub-solar direction)). 0 in eclipse, 1 at solar noon. Drives
    # the satellite-stage Sun light INTENSITY in Kit.
    sun_factor: float = 1.0
    # Visible fraction of the solar disc (conical umbra/penumbra model):
    # 1 full sun · 0 umbra · smooth 0..1 through the penumbra. This is the
    # exact factor the solar-power and thermal models consume (sunlit is
    # just solar_illum >= 0.5), broadcast so validators/UI can re-derive
    # the physics without re-running the shadow geometry.
    solar_illum: float = 1.0
    # Raw cosine of the zenith→sun angle (−1..1, unclamped — negative in
    # eclipse). Under the yaw-steering attitude the sun always sits in the
    # satellite's X-Z plane, so this single number fixes the full sun
    # DIRECTION in the twin stage: d = (sqrt(1−c²), 0, c). Kit sweeps the
    # Key light + the visible sun disk with it; in eclipse the sun dips
    # below the −Z (nadir) horizon and the Earth visually blocks it.
    sun_cos: float = 1.0
    # True on the dawn-dusk Sun-synchronous (terminator) orbit: never eclipsed,
    # panels track the Sun, so the twin keeps the Sun normal to the panels.
    is_dawn_dusk: bool = False
    solar_input_w: float = 0.0
    # Effective panel-normal incidence 0..1 = max(0, panel_normal · sun) for
    # the current attitude (1.0 = dead-on / sun-tracking, 0 = edge-on/eclipse).
    # Sun-pointing holds ~1 while sunlit; a nadir/ram/inertial body-fixed array
    # projects geometrically and can fall to 0 even in daylight.
    solar_incidence: float = 0.0
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
    # Number of accelerator cards fitted (per design preset).
    gpu_count: int = 8
    # Typed-job detail for the active schedule block.
    workload_detail: Optional[GpuJobDetail] = None
    # Cumulative output since the workload profile / design was applied.
    workload_totals: WorkloadTotals = Field(default_factory=WorkloadTotals)
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
    # Roll-out solar-array deployment fraction 0..1 (mock of a flexible
    # blanket array unrolling off the redwire bay edges): POST /solar_deploy
    # animates it, solar production scales with it, and the Kit driver
    # stretches the wing geometry from the root so the blanket visibly
    # extends. 1.0 = fully deployed (every non-redwire design just stays 1).
    solar_deploy_frac: float = 1.0
    # Reaction-wheel attitude spin rates (deg/s about the body X/Y/Z axes
    # through the centre of mass — any combination may run, giving a slow
    # tumble). POST /attitude_spin toggles per axis; the Kit close-up
    # integrates the angles per frame so the whole model visibly rotates.
    # Display-only — the power/thermal physics keeps its sun-tracking model.
    attitude_spin_dps: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Attitude pointing mode (Twin page attitude control): "free" = the
    # reaction wheels above are in charge (manual tumble); otherwise the Kit
    # close-up orients the body to a target — "sun" (panels to the Sun),
    # "nadir" (payload to Earth), "velocity" (ram along-track), "inertial"
    # (fixed). Selecting a mode zeroes the wheels; touching a wheel drops
    # back to "free". Display-only, like the wheels.
    attitude_mode: AttitudeMode = "free"
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
    # Monotonic revision of the custom orbit design. Re-designing keeps the
    # constellation id ("custom_design") but bumps this, so id-keyed caches
    # (Kit ring rebuild, web ring detail) know to refetch. 0 for built-ins.
    design_rev: int = 0


class CompareMetrics(BaseModel):
    mode: Mode = "on_orbit"
    latency_s: float = 0.0
    downlink_mb: float = 0.0
    peak_temp_c: float = 0.0


class CompareLiveVariant(BaseModel):
    """One what-if variant's CURRENT sample (compare_sim.LiveCompareSession).
    The web accumulates these 1 Hz samples into the telemetry strip's rolling
    window, so variant curves grow in real time alongside the live trace."""
    value: str | float | int
    label: str
    solar_input_w: float = 0.0
    payload_power_w: float = 0.0
    battery_soc: float = 0.0
    temperature_c: float = 0.0
    gpu_utilization: float = 0.0
    tokens_per_s: float = 0.0


class SolarHistBin(BaseModel):
    """One bar of the solar-intensity histogram (Overview Solar tab)."""
    lo: int            # intensity lower bound (inclusive), 0..100
    hi: int            # upper bound (exclusive)
    sat_count: int
    collection_w: float


class ElevationCount(BaseModel):
    """Sats visible above a given elevation mask (band-comparison curves)."""
    mask_deg: int
    count: int


class GroundTargetState(BaseModel):
    """Optional ground station marked on the Earth (Overview page) — when
    enabled, every fleet tick also computes line-of-sight visibility, the
    active band's aggregate bandwidth, an elevation CDF (for the band curves)
    and a solar-intensity histogram from this point to the whole fleet."""
    enabled: bool = False
    name: str = "Singapore"
    lat: float = 1.3521
    lon: float = 103.8198
    # --- configuration (Overview config step) ---
    # User-selected antenna elevation mask; the effective mask is the max of
    # this and the active band's minimum.
    elevation_mask_deg: float = 10.0
    band: str = "X"
    band_label: str = "X-band"
    band_mbps_per_sat: float = 150.0
    solar_bin: int = 10                 # histogram bin width, 5 or 10
    min_elevation_deg: float = 10.0     # EFFECTIVE mask = max(user, band min)
    # --- live per-tick analytics ---
    visible_sats: int = 0
    best_elevation_deg: float = -90.0
    aggregate_mbps: float = 0.0
    # Indices (into the fleet) of currently-visible sats, capped at 64 so
    # a mega-constellation can't bloat the packet.
    visible_indices: list[int] = Field(default_factory=list)
    elevation_cdf: list[ElevationCount] = Field(default_factory=list)
    solar_hist: list[SolarHistBin] = Field(default_factory=list)


class CompareLiveState(BaseModel):
    """Live what-if comparison riding StatePacket.compare_live: 2–4 variant
    engines seeded from one event-loop-consistent snapshot, stepped in
    lockstep with the live 1 Hz physics tick."""
    active: bool = True
    dimension: str = ""
    dimension_label: str = ""
    start_sim_time_s: float = 0.0
    elapsed_s: float = 0.0
    variants: list[CompareLiveVariant] = Field(default_factory=list)


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
BatteryMaterial = Literal["LiIon", "LiFePO4", "LiS", "SolidState"]
BatterySize   = Literal["S", "M", "L", "XL"]


class SatelliteConfig(BaseModel):
    """Reconfigurable hardware loadout for the tracked satellite. Drives
    both backend physics (solar / payload / thermal recompute) and
    Omniverse VariantSet selection on the Kit side."""
    gpu: GpuType = "H100"
    solar_material: SolarMaterial = "Si"
    solar_size: SolarSize = "M"
    radiator_material: RadiatorMaterial = "Aluminum"
    radiator_size: RadiatorSize = "Standard"
    # Battery chemistry (round-trip efficiency + energy density) and pack size
    # (mass tier). Effective capacity = mass × density, so both matter.
    battery_material: BatteryMaterial = "LiIon"
    battery_size: BatterySize = "L"
    # Per-slot payload loadout (satellite builder, step 3): one entry per rack
    # slot of the chosen platform — a GpuType for a fitted card, None for an
    # empty slot. EMPTY LIST = "uniform `gpu` × the engine's card count", which
    # is what every design preset and the plain GPU dropdown produce, so the
    # homogeneous path is unchanged. When present this list is AUTHORITATIVE:
    # it fixes the card count and `gpu` echoes its largest group.
    gpu_slots: list[Optional[GpuType]] = Field(default_factory=list)


Architecture = Literal["truss", "twin_truss", "blanket", "lumid", "dish",
                       "redwire"]


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
    # Live what-if comparison (compare_sim) — present while a comparison runs.
    compare_live: Optional[CompareLiveState] = None
    # Ground-station marker + live visibility — present once a target is set.
    ground_target: Optional[GroundTargetState] = None
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
    # Vendor platform the satellite is built on (satellite_assets.py) — set by
    # the satellite builder and inferred from the hull when a design preset is
    # applied. "" when the current hull belongs to no catalogued platform.
    asset_id: str = ""
