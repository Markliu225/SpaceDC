// Mirrors backend/models.py. Keep in sync with docs/api_spec.md.

export type OrbitType = 'LEO' | 'SSO' | 'MEO' | 'GEO';
export type GpuType = 'H100' | 'H200' | 'B200' | 'MI300X';
export type Mode = 'on_orbit' | 'ground_only';
export type TaskPhase =
  | 'idle' | 'created' | 'capturing' | 'inferencing'
  | 'packaging' | 'downlink' | 'delivered';

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
  payload_power_w: number;
  platform_power_w: number;
  gpu_type: GpuType;
  gpu_utilization: number;
  temperature_c: number;
  battery_soc: number;
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

export interface SatelliteConfig {
  gpu: GpuType;
  solar_material: SolarMaterial;
  solar_size: SolarSize;
  radiator_material: RadiatorMaterial;
  radiator_size: RadiatorSize;
}

export interface StatePacket {
  sim_time_s: number;
  satellite: SatelliteState;
  ground_station: GroundStationState;
  constellation: FleetSnapshot;
  task: TaskState | null;
  compare: CompareMetrics | null;
  /** Optional in Phase 1 — backend hasn't started broadcasting it yet. */
  satellite_config?: SatelliteConfig;
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
  | 'set_config';

export type ServerMessageType =
  | 'scene_ready' | 'state_update' | 'task_update'
  | 'selection_changed' | 'camera_changed' | 'error' | 'ack';

export interface Envelope<P = Record<string, unknown>> {
  type: ClientMessageType | ServerMessageType;
  ts: number;
  payload: P;
  request_id?: string;
}
