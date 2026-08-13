// Mirrors backend/models.py. Keep in sync with docs/api_spec.md.

export type OrbitType = 'LEO' | 'SSO' | 'MEO' | 'GEO';
export type GpuType = 'H100' | 'H200' | 'B200' | 'MI300X';
export type Mode = 'on_orbit' | 'ground_only';
export type TaskPhase =
  | 'idle' | 'created' | 'capturing' | 'inferencing'
  | 'packaging' | 'downlink' | 'delivered';

/** One homogeneous card group of a mixed payload bay (per-slot GPU selection —
 *  mirrors backend models.GpuMixItem). */
export interface GpuMixItem {
  gpu: string;
  count: number;
  power_w_per_gpu: number;
  heat_w_per_gpu: number;
  tflops_per_gpu: number;
  throughput_per_gpu: number;
  throughput_total: number;
}

/** What the payload GPUs are ACTUALLY running this tick — the typed job from
 *  the active schedule block resolved against the fitted GPU's datasheet
 *  (mirrors backend ai_workloads.py / models.GpuJobDetail). */
export interface GpuJobDetail {
  job: string;
  job_label: string;
  model: string;
  precision: string;
  mfu: number;
  gpu_count: number;
  power_w_per_gpu: number;
  heat_w_per_gpu: number;
  tflops_per_gpu: number;
  throughput_per_gpu: number;
  throughput_total: number;
  throughput_unit: string;
  /** 'analytic' — the numbers come from the llm_perf operating-point solve
   *  (power cap ∧ thermal limit → DVFS frequency → tokens/s, realized draw);
   *  'mfu' — the heuristic path (vision / idle / unknown combos). */
  engine?: 'analytic' | 'mfu';
  /** Execution phase on the analytic path: 'decode' | 'prefill' | 'train'. */
  exec_phase?: string;
  /** Concurrent decode rows per GPU (0 when not decoding). */
  batch?: number;
  /** Effective KV context per row, tokens. */
  context?: number;
  /** EPS power budget handed to each card (W). */
  power_cap_w?: number;
  /** SM frequency fraction x = f_sm/f_max the DVFS governor settles at. */
  freq_frac?: number;
  /** GPU junction temperature: T_struct + draw · R_th (°C). */
  gpu_die_temp_c?: number;
  /** Thermal limit is cutting the realized draw (die held at target). */
  thermal_throttled?: boolean;
  /** Die cannot be held at the throttle target even at the idle floor. */
  thermal_runaway?: boolean;
  /** Frequency-immune memory floor per decode step (ms). */
  t_mem_ms?: number;
  /** Frequency-scaled compute time per step (ms). */
  t_comp_ms?: number;
  /** Per-card-type breakdown — present ONLY when the fitted slots hold more
   *  than one GPU model, in which case the columns above are card-weighted
   *  means (totals are still sums). */
  mix?: GpuMixItem[];
}

/** Cumulative payload output since the active workload profile (or design)
 *  was applied — mirrors backend models.WorkloadTotals. */
export interface WorkloadTotals {
  tokens: number;
  frames: number;
  payload_kwh: number;
  duration_s: number;
}

/** One workload profile annotated with how the CURRENT design copes with it
 *  (GET /workload_profiles — mirrors state_engine.workload_adaptation). */
export interface WorkloadProfileInfo {
  id: string;
  label: string;
  cycle_s: number;
  avg_util: number;
  demand_avg_w: number;
  supply_avg_w: number;
  power_margin_pct: number;
  thermal_peak_w: number;
  thermal_emit_w: number;
  thermal_margin_pct: number;
  fit: 'ok' | 'tight' | 'exceeds';
  outputs_per_cycle: { tokens: number; frames: number; payload_kwh: number };
  jobs: string[];
}

export interface SatelliteState {
  id: string;
  orbit_type: OrbitType;
  lat: number;
  lon: number;
  altitude_km: number;
  sunlit: boolean;
  /** Normalised solar incidence 0..1 (0 = eclipse, 1 = solar noon). */
  sun_factor?: number;
  solar_input_w: number;
  /** Attitude-dependent panel-normal·Sun incidence 0..1 (sun-pointing ≈ 1;
   *  a body-fixed nadir/ram/inertial array projects geometrically). */
  solar_incidence?: number;
  payload_power_w: number;
  platform_power_w: number;
  gpu_type: GpuType;
  gpu_utilization: number;
  temperature_c: number;
  battery_soc: number;
  battery_capacity_wh?: number;
  /** Instantaneous net power into the battery (positive = charging,
   *  negative = discharging). */
  battery_charge_w?: number;
  /** Heat radiated out via the panel back (W). */
  radiator_power_w?: number;
  /** Workload (0..1) — the upstream job pattern driving gpu_utilization. */
  workload?: number;
  /** Accelerator cards fitted (per design preset). */
  gpu_count?: number;
  /** Roll-out solar-array deployment fraction 0..1 (POST /solar_deploy
   *  animates it; production and the Kit wing stretch follow). */
  solar_deploy_frac?: number;
  /** Reaction-wheel body spin rates [x, y, z] in deg/s about the
   *  centre-of-mass axes — any mix runs as a tumble (POST /attitude_spin
   *  toggles per axis; Kit integrates the angles per frame). */
  attitude_spin_dps?: number[];
  /** Fixed attitude pointing mode: free | sun | nadir | velocity | inertial.
   *  Non-free zeroes the wheels; the Kit close-up orients the body. */
  attitude_mode?: string;
  /** Typed-job detail for the active schedule block (ai_workloads.py). */
  workload_detail?: GpuJobDetail;
  /** Cumulative output since the workload profile / design was applied. */
  workload_totals?: WorkloadTotals;
  /** Standing alarm codes (e.g. 'low_battery', 'overtemp', 'undertemp',
   *  'eclipse_deficit', 'radiator_undersized', 'solar_undersized',
   *  'gpu_thermal_throttle', 'gpu_thermal_runaway'). */
  alarms?: string[];
  /** Design-check numbers — supply vs demand for solar avg power and
   *  thermal peak emission. Margin = supply − demand; negative = the
   *  current loadout cannot meet the workload. */
  solar_demand_avg_w?: number;
  solar_supply_avg_w?: number;
  thermal_peak_demand_w?: number;
  thermal_max_emit_w?: number;
  solar_area_m2?: number;
  radiator_area_m2?: number;
  downlink_mbps: number;
  task_state: TaskPhase;
}

export interface GroundStationState {
  id: string;
  visible: boolean;
  rx_mbps: number;
  queue_depth: number;
}

export interface TaskState {
  id: string;
  type: string;
  state: TaskPhase;
  input_size_mb: number;
  result_size_mb: number;
  progress: number;
  targets: number;
  alerts: number;
}

export interface CompareMetrics {
  mode: Mode;
  latency_s: number;
  downlink_mb: number;
  peak_temp_c: number;
}

export interface FleetSnapshot {
  constellation_id: string;
  name: string;
  total: number;
  online: number;
  eclipse: number;
  standby: number;
  offline: number;
  planes: number;
  sats_per_plane: number;
  inclination_deg: number;
  altitude_km: number;
  coverage_pct: number;
  links_total: number;
  isl_links: number;
  gsl_links: number;
  agg_throughput_mbps: number;
  /** Monotonic revision of the custom orbit design (bumps on each redesign
   *  even though the constellation id stays "custom_design"). 0 for built-ins. */
  design_rev?: number;
}

export interface ConstellationPresetSummary {
  id: string;
  name: string;
  description: string;
  total_sats: number;
  planes: number;
  sats_per_plane: number;
  phasing: number;
  inclination_deg: number;
  altitude_km: number;
  period_s: number;
}

/** Full constellation payload from GET /constellations/{id}.
 *  Carries the Walker parameters plus the precomputed base orbit ring
 *  (128 ECI km samples) so the Web client can derive every sat's
 *  ECI position without round-tripping a position per sat per tick. */
export interface ConstellationDetail {
  id: string;
  name: string;
  description: string;
  planes: number;
  sats_per_plane: number;
  phasing: number;
  total_sats: number;
  inclination_deg: number;
  altitude_km: number;
  period_s: number;
  time_scale: number;
  /** Sampled positions of the base orbit (plane 0, sat 0) in ECI km.
   *  Other planes = rotation about +Z; other sats = phase offset along ring. */
  ring_eci_km: [number, number, number][];
}

/** Reconfigurable hardware loadout for one satellite. Drives both backend
 *  physics recompute and Omniverse VariantSet swaps. */
export type SolarMaterial   = 'Si' | 'GaAs' | 'Perovskite';
export type SolarSize       = 'S' | 'M' | 'L' | 'XL';
export type RadiatorMaterial = 'Aluminum' | 'WhitePaint' | 'OSR' | 'Graphite';
export type RadiatorSize    = 'Compact' | 'Standard' | 'Wide';
export type BatteryMaterial = 'LiIon' | 'LiFePO4' | 'LiS' | 'SolidState';
export type BatterySize     = 'S' | 'M' | 'L' | 'XL';

export interface SatelliteConfig {
  gpu: GpuType;
  solar_material: SolarMaterial;
  solar_size: SolarSize;
  radiator_material: RadiatorMaterial;
  radiator_size: RadiatorSize;
  battery_material: BatteryMaterial;
  battery_size: BatterySize;
  /** Per-slot payload loadout (satellite builder step 3): one entry per rack
   *  slot of the platform — a GPU model for a fitted card, null for an empty
   *  slot. Absent/empty = the uniform `gpu` loadout every design preset flies,
   *  in which case the card count comes from the design. */
  gpu_slots?: (GpuType | null)[];
}

/** Hull configuration — each is a genuinely different satellite shape. */
export type Architecture =
  | 'truss' | 'twin_truss' | 'blanket' | 'lumid' | 'dish' | 'redwire';

/** Deployable geometry knobs (Feature 3) — hull architecture + solar segment
 * count + radiator size/ratio. Drives the regenerated USD model and the
 * physics areas. `solar_clusters_per_side` is ignored by the hull
 * architectures (lumid/dish), whose panels are integrated. */
export interface TwinGeometry {
  architecture?: Architecture;
  solar_clusters_per_side: number;
  radiator_long: number;
  radiator_ratio: number;
  version: number;
}

/** Derived headline stats for one design preset — computed backend-side with
 *  the same formulas the physics engine uses (GET /designs). */
export interface DesignStats {
  solar_area_m2: number;
  radiator_area_m2: number;
  peak_solar_w: number;
  compute_pflops: number;
  mass_kg: number;
  gpu_tdp_w: number;
  radiator_emissivity: number;
  workload_avg_util: number;
  workload_label: string;
}

/** One complete satellite design (backend design_presets.py): hardware
 *  loadout + deployable geometry + workload profile + platform constants.
 *  Applying it via POST /designs/{id}/apply swaps the 3D model (USD regen +
 *  Kit layer reload) and the physics inputs together. */
export interface DesignPresetInfo {
  id: string;
  name: string;
  tagline: string;
  description: string;
  config: SatelliteConfig;
  architecture: string;
  gpu_count: number;
  solar_clusters_per_side: number;
  radiator_long: number;
  radiator_ratio: number;
  workload_profile: string;
  battery_capacity_wh: number;
  platform_power_w: number;
  stats: DesignStats;
  /** Backend-relative path of the software-rendered thumbnail. */
  preview_url: string;
}

/** GET /designs response. `active` is "custom" after any manual edit. */
export interface DesignsResponse {
  active: string;
  designs: DesignPresetInfo[];
}

// ---------------------------------------------------------------------------
// Satellite assets + builder (backend satellite_assets.py — Twin page build
// flow: platform → structure design → per-slot payload → workload → Run).
// ---------------------------------------------------------------------------

/** Headline stats of an asset's FACTORY loadout (GET /satellite_assets). */
export interface SatelliteAssetStats {
  solar_area_m2: number;
  radiator_area_m2: number;
  peak_solar_w: number;
  compute_pflops: number;
  mass_kg: number;
  gpu_tdp_w: number;
  radiator_emissivity: number;
}

/** One buildable vendor platform: which hull flies, how many payload slots it
 *  has, and the loadout it ships with. */
export interface SatelliteAssetInfo {
  id: string;
  name: string;
  vendor: string;
  tagline: string;
  description: string;
  architecture: Architecture;
  slot_count: number;
  /** Slots per visual group in the builder's bay grid. */
  slot_group_size: number;
  slot_group_label: string;
  /** Per-slot names, in the same order as the 3D model's slots. */
  slot_labels: string[];
  config: SatelliteConfig;
  solar_clusters_per_side: number;
  radiator_long: number;
  radiator_ratio: number;
  workload_profile: string;
  default_gpu: GpuType;
  default_gpu_count: number;
  platform_power_w: number;
  battery_capacity_wh: number;
  stats: SatelliteAssetStats;
  preview_url: string;
}

/** GET /satellite_assets — `active` is "" when the live hull belongs to no
 *  catalogued platform (the twin_truss / blanket design presets). */
export interface SatelliteAssetsResponse {
  active: string;
  assets: SatelliteAssetInfo[];
}

/** POST /satellite_build(/preview) request body. */
export interface SatelliteBuildRequest {
  asset: string;
  config: SatelliteConfig;
  geometry: {
    solar_clusters_per_side: number;
    radiator_long: number;
    radiator_ratio: number;
  };
  gpu_slots: (GpuType | null)[];
  workload_profile: string;
  attitude_mode?: string;
}

/** POST /satellite_build/preview — the draft dry-run: derived stats plus how
 *  every job schedule would cope, computed by a detached engine so the verdict
 *  shown before Run is the one the panels show after it. */
export interface SatelliteBuildPreview {
  asset_id: string;
  stats: {
    gpu_count: number;
    mix: { gpu: string; count: number }[];
    compute_pflops: number;
    payload_peak_w: number;
    solar_area_m2: number;
    radiator_area_m2: number;
    peak_solar_w: number;
    battery_capacity_wh: number;
    platform_power_w: number;
  };
  profiles: WorkloadProfileInfo[];
}

// ---------------------------------------------------------------------------
// What-if comparison (backend compare_sim.py — Twin page Compare panel).
// ---------------------------------------------------------------------------

/** One choice inside a comparable dimension (e.g. "OSR" for radiator_material). */
export interface CompareChoice {
  id: string | number;
  label: string;
}

/** A comparable knob — every Configurator control plus whole designs. */
export interface CompareDimension {
  id: string;
  label: string;
  group: string;
  values: CompareChoice[];
  /** The live loadout's current value for this dimension. */
  current: string | number;
  default_metric: string;
}

/** A plottable metric of the compare series. */
export interface CompareMetric {
  key: string;
  label: string;
  unit: string;
  digits: number;
  /** Display multiplier (e.g. 100 for SOC ⇒ %). */
  factor?: number;
}

/** GET /compare/options response. */
export interface CompareOptions {
  dimensions: CompareDimension[];
  metrics: CompareMetric[];
  default_duration_s: number;
}

/** One live variant's CURRENT sample (backend LiveCompareSession). The web
 *  accumulates these 1 Hz samples into the telemetry strip's rolling window,
 *  so the variant curves grow and diverge in real time. */
export interface CompareLiveVariant {
  value: string | number;
  label: string;
  solar_input_w: number;
  payload_power_w: number;
  battery_soc: number;
  temperature_c: number;
  gpu_utilization: number;
  tokens_per_s: number;
}

/** Live what-if comparison riding StatePacket.compare_live — 2–4 variant
 *  engines seeded from the live state, stepped in lockstep with the 1 Hz
 *  physics tick (POST /compare/start · /compare/stop). */
export interface CompareLiveState {
  active: boolean;
  dimension: string;
  dimension_label: string;
  start_sim_time_s: number;
  elapsed_s: number;
  variants: CompareLiveVariant[];
}

/** 天数天算 mission phase. idle = not running; the rest advance in order. */
export type MissionPhase =
  | 'idle' | 'acquire' | 'capture' | 'route' | 'compute' | 'downlink' | 'deliver';

export const MISSION_PHASES: MissionPhase[] = [
  'acquire', 'capture', 'route', 'compute', 'downlink', 'deliver',
];

/** Live state of the single compute-in-space mission. Mirrors backend
 *  MissionState (Phase 2); driven by a local mock until backend lands. */
export interface MissionState {
  active: boolean;
  phase: MissionPhase;
  /** 0..1 progress within the current phase. */
  phase_progress: number;
  /** Seconds since capture start; freezes at deliver. */
  elapsed_s: number;
  /** Current data-packet size (MB): 5120 at capture, ~2 after inference. */
  data_volume_mb: number;
  targets_found: number;
  /** Fleet indices of the assigned cast. -1 when unassigned. */
  sensor_idx: number;
  hub_idx: number;
  aoi_lat: number;
  aoi_lon: number;
  ground_lat: number;
  ground_lon: number;
  ground_id: string;
}

// ---------------------------------------------------------------------------
// Orbit designer + ground-station visibility (Overview page).
// ---------------------------------------------------------------------------

/** Classical orbital elements of a constellation's reference orbit. */
export interface OrbitElements {
  altitude_km: number;
  semi_major_axis_km: number;
  eccentricity: number;
  inclination_deg: number;
  raan_deg: number;
  arg_perigee_deg: number;
  mean_anomaly_deg: number;
  period_s: number;
  period_min: number;
}

/** GET/POST /orbit_design payload — active constellation's elements + Walker. */
export interface OrbitDesignInfo {
  active: string;
  name: string;
  elements: OrbitElements;
  walker: { planes: number; sats_per_plane: number; phasing: number; total_sats: number };
}

/** One communication band: throughput vs elevation-mask requirement. */
export interface CommsBand {
  id: string;
  label: string;
  per_sat_mbps: number;
  min_elevation_deg: number;
}

/** GET /comms_bands response. */
export interface CommsBandsResponse {
  default: string;
  bands: CommsBand[];
}

/** One bar of the solar-intensity histogram. */
export interface SolarHistBin {
  lo: number;
  hi: number;
  sat_count: number;
  collection_w: number;
}

/** Sats visible above a given elevation mask (band-comparison curves). */
export interface ElevationCount {
  mask_deg: number;
  count: number;
}

/** Ground-station marker + comms config + live analytics (StatePacket.ground_target). */
export interface GroundTargetState {
  enabled: boolean;
  name: string;
  lat: number;
  lon: number;
  // config
  elevation_mask_deg: number;
  band: string;
  band_label: string;
  band_mbps_per_sat: number;
  solar_bin: number;
  min_elevation_deg: number;   // effective mask = max(user, band min)
  // live analytics
  visible_sats: number;
  best_elevation_deg: number;
  aggregate_mbps: number;
  visible_indices: number[];
  elevation_cdf: ElevationCount[];
  solar_hist: SolarHistBin[];
}

/** GET /ground_visibility response — pass analysis over N orbital periods. */
export interface GroundVisibilityResponse {
  target: { name: string; lat: number; lon: number; min_elevation_deg: number };
  constellation: string;
  total_sats: number;
  period_s_real: number;
  duration_s: number;
  time_scale: number;
  samples: { t_s: number; visible_sats: number; best_elevation_deg: number }[];
  windows: { start_s: number; end_s: number; max_elevation_deg: number }[];
  coverage_fraction: number;
  next_pass_in_s: number | null;
}

export interface StatePacket {
  sim_time_s: number;
  satellite: SatelliteState;
  ground_station: GroundStationState;
  constellation: FleetSnapshot;
  task: TaskState | null;
  compare: CompareMetrics | null;
  /** Live what-if comparison — present while a comparison is running. */
  compare_live?: CompareLiveState | null;
  /** Ground-station marker + live visibility — present once a target is set. */
  ground_target?: GroundTargetState | null;
  /** Optional in Phase 1 — backend hasn't started broadcasting it yet. */
  satellite_config?: SatelliteConfig;
  /** Deployable geometry (solar count, radiator size) — Feature 3. */
  twin_geometry?: TwinGeometry;
  /** Optional until backend MissionEngine lands. */
  mission?: MissionState;
  /** Active design preset id ("custom" after manual config/geometry edits). */
  design_id?: string;
  /** Vendor platform the current hull belongs to (satellite_assets.py) —
   *  derived from the architecture, "" for twin_truss / blanket. */
  asset_id?: string;
  /** Workload profile id the GPU job schedule is running. */
  workload_profile?: string;
}

export interface Parameters {
  orbit_type?: OrbitType;
  gpu_type?: GpuType;
  load?: 'low' | 'medium' | 'high';
  bandwidth_mbps?: number;
  inference_mode?: Mode;
  sunlit?: boolean;
}

export type ClientMessageType =
  | 'play' | 'pause' | 'reset' | 'set_time' | 'set_parameters'
  | 'set_mode' | 'start_task' | 'select_object' | 'change_camera'
  | 'set_config' | 'start_mission' | 'stop_mission';

export type ServerMessageType =
  | 'scene_ready' | 'state_update' | 'task_update'
  | 'selection_changed' | 'camera_changed' | 'error' | 'ack';

export interface Envelope<P = Record<string, unknown>> {
  type: ClientMessageType | ServerMessageType;
  ts: number;
  payload: P;
  request_id?: string;
}
