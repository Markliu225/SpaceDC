import { create } from 'zustand'
import type {
  ConstellationDetail,
  ConstellationPresetSummary,
  FleetSnapshot,
  SatelliteConfig,
} from '../types/messages'

/** Baseline hardware loadout — referenced by the twin page's "Δ vs baseline"
 *  delta chips. Kept as a module-level constant so any component can import
 *  it without round-tripping through the store. */
export const SAT_CONFIG_BASELINE: SatelliteConfig = {
  gpu: 'H100',
  solar_material: 'Si',
  solar_size: 'M',
  radiator_material: 'Aluminum',
  radiator_size: 'Standard',
  battery_material: 'LiIon',
  battery_size: 'L',
}

// Status taxonomy used by the donut + sat markers.
export type SatStatus = 'online' | 'eclipse' | 'standby' | 'offline'

export interface Satellite {
  id: string                // SAT-01..SAT-24
  status: SatStatus
  // 6-hue ribbon palette assignment (deterministic by index).
  ribbon: number            // 0..5
  // Live orbital params — drift per tick.
  lat: number
  lon: number
  altitude_km: number
  sunlit: boolean
  // Compute / power telemetry — only meaningful for `online`.
  solar_input_w: number
  payload_power_w: number
  platform_power_w: number
  gpu_type: 'H100' | 'H200' | 'B200' | 'MI300X'
  gpu_utilization: number   // 0..1
  temperature_c: number
  battery_soc: number       // 0..1
  downlink_mbps: number
  task_state: 'idle' | 'created' | 'capturing' | 'inferencing' | 'packaging' | 'downlink' | 'delivered'
  orbit_type: 'LEO' | 'SSO'
}

export interface NetworkKPIs {
  total: number
  online: number
  links_total: number
  isl_links: number
  gsl_links: number
  coverage_pct: number      // 0..100
  agg_throughput_mbps: number
}

export interface SubsystemHealth {
  power: 'nominal' | 'warn' | 'fault'
  thermal: 'nominal' | 'warn' | 'fault'
  propulsion: 'nominal' | 'warn' | 'fault'
  comms: 'nominal' | 'warn' | 'fault'
}

export interface EventEntry {
  id: string
  ts: string                // HH:MM:SS
  kind: 'info' | 'ok' | 'warn' | 'err'
  label: string
  entities: string          // right-aligned ids
}

export interface UpcomingEvent {
  id: string
  ts: string                // HH:MM:SS
  label: string
  sub: string
  /** Seconds until event. Updated each tick. */
  countdown_s: number
}

interface TelemetryStore {
  running: boolean
  sim_time_s: number
  sats: Satellite[]
  selectedId: string        // e.g. SAT-07
  network: NetworkKPIs
  health: SubsystemHealth
  // Last 60 samples for the two sparklines.
  downlink_history: number[]
  uplink_history: number[]
  events: EventEntry[]
  upcoming: UpcomingEvent[]

  // ---- backend-driven fields (filled by useBackendBridge) ----
  /** Currently active constellation snapshot from /state.constellation. */
  fleet: FleetSnapshot | null
  /** Full preset catalog from GET /constellations.presets. */
  presets: ConstellationPresetSummary[]
  /** Active preset id; mirrors fleet.constellation_id once we receive a snapshot. */
  activeConstellationId: string
  /** Full Walker params + base orbit ring for the active preset.
   *  Fetched once per preset swap via GET /constellations/{id} — drives
   *  the Web-side fleet propagator (ring + plane rotation + phase offset). */
  constellationDetail: ConstellationDetail | null
  /** Index of the currently-selected sat within the propagated fleet
   *  [0..constellationDetail.total_sats). Replaces the legacy SAT-XX string
   *  for the new fleet-driven Overview. */
  selectedSatIdx: number
  /** Currently-applied hardware loadout. Twin page mutates via setSatConfig;
   *  bridge mirrors backend's authoritative value once Phase 2 lands. */
  satConfig: SatelliteConfig

  // ---- actions ----
  setRunning: (v: boolean) => void
  reset: () => void
  select: (id: string) => void
  applyTick: (patch: Partial<TelemetryStore>) => void
  pushEvent: (e: EventEntry) => void
  applyFleet: (fleet: FleetSnapshot) => void
  setPresets: (p: ConstellationPresetSummary[]) => void
  setActiveConstellation: (id: string) => void
  setConstellationDetail: (d: ConstellationDetail | null) => void
  setSelectedSatIdx: (i: number) => void
  setSatConfig: (patch: Partial<SatelliteConfig>) => void
}

// ---- Deterministic seed satellites: 20 online / 2 eclipse / 1 standby / 1 offline.
// Brief requires this exact distribution so donut numbers are reproducible.
const STATUS_PLAN: SatStatus[] = [
  ...Array(20).fill('online'),
  'eclipse', 'eclipse',
  'standby',
  'offline',
] as SatStatus[]

function makeSats(): Satellite[] {
  return Array.from({ length: 24 }, (_, i) => {
    const id = `SAT-${String(i + 1).padStart(2, '0')}`
    const status = STATUS_PLAN[i]
    // Spread satellites around the orbit. inclination ~ 60 deg.
    const phase = (i / 24) * Math.PI * 2
    return {
      id,
      status,
      ribbon: i % 6,
      lat: Math.sin(phase) * 60,
      lon: ((phase * 180) / Math.PI) - 180,
      altitude_km: 550 + (i % 4) * 10,
      sunlit: status !== 'eclipse',
      solar_input_w: status === 'online' ? 4200 : status === 'eclipse' ? 0 : 1200,
      payload_power_w: status === 'online' ? 1800 : 0,
      platform_power_w: 600,
      gpu_type: (['H100', 'H200', 'B200', 'MI300X'] as const)[i % 4],
      gpu_utilization: status === 'online' ? 0.5 : 0,
      temperature_c: status === 'online' ? 58 + (i % 5) * 2 : 22,
      battery_soc: status === 'offline' ? 0.06 : 0.78 - (i % 6) * 0.05,
      downlink_mbps: status === 'online' && i % 3 === 0 ? 120 : 0,
      task_state: status === 'online' ? 'inferencing' : 'idle',
      orbit_type: i % 2 === 0 ? 'SSO' : 'LEO',
    } satisfies Satellite
  })
}

function initialNetwork(): NetworkKPIs {
  return {
    total: 24,
    online: 20,
    links_total: 38,
    isl_links: 32,
    gsl_links: 6,
    coverage_pct: 87,
    agg_throughput_mbps: 4280,
  }
}

function initialUpcoming(): UpcomingEvent[] {
  return [
    { id: 'u1', ts: '14:32:08', label: 'AOS over Svalbard',  sub: 'SAT-07 · 8m 12s window', countdown_s: 240 },
    { id: 'u2', ts: '14:45:00', label: 'Eclipse entry',      sub: 'SAT-12 · expected 34min',  countdown_s: 1020 },
    { id: 'u3', ts: '15:02:11', label: 'Maritime task START',sub: 'SAT-07 · Pacific NW AOI',  countdown_s: 2270 },
  ]
}

function initialEvents(): EventEntry[] {
  // Pre-populate enough rows to show the panel well on first render.
  return [
    { id: 'e1', ts: '14:21:04', kind: 'ok',   label: 'Link established',        entities: 'SAT-07 → SAT-13' },
    { id: 'e2', ts: '14:20:51', kind: 'info', label: 'Task created',            entities: 'SAT-07 · maritime' },
    { id: 'e3', ts: '14:19:33', kind: 'warn', label: 'Thermal warning cleared', entities: 'SAT-04' },
    { id: 'e4', ts: '14:18:17', kind: 'ok',   label: 'AOS Reykjavik',           entities: 'GS-EU-01 · SAT-15' },
    { id: 'e5', ts: '14:16:02', kind: 'info', label: 'Downlink complete',       entities: 'SAT-09 · 412 MB' },
    { id: 'e6', ts: '14:14:48', kind: 'err',  label: 'Comms drop (recovered)',  entities: 'SAT-22' },
    { id: 'e7', ts: '14:12:31', kind: 'ok',   label: 'Battery charge resumed',  entities: 'SAT-13' },
    { id: 'e8', ts: '14:10:09', kind: 'info', label: 'Constellation sync',      entities: 'ALL · 22 nodes' },
  ]
}

export const useTelemetryStore = create<TelemetryStore>((set) => ({
  running: true,
  sim_time_s: 0,
  sats: makeSats(),
  selectedId: 'SAT-07',
  network: initialNetwork(),
  health: { power: 'nominal', thermal: 'nominal', propulsion: 'nominal', comms: 'nominal' },
  downlink_history: Array.from({ length: 60 }, (_, i) => 60 + 20 * Math.sin(i / 6)),
  uplink_history:   Array.from({ length: 60 }, (_, i) => 18 + 10 * Math.sin(i / 5 + 1)),
  events: initialEvents(),
  upcoming: initialUpcoming(),

  fleet: null,
  presets: [],
  activeConstellationId: 'single_iss',
  constellationDetail: null,
  selectedSatIdx: 0,
  satConfig: { ...SAT_CONFIG_BASELINE },

  setRunning: (v) => set({ running: v }),
  reset: () =>
    set({
      sim_time_s: 0,
      sats: makeSats(),
      network: initialNetwork(),
      events: initialEvents(),
      upcoming: initialUpcoming(),
    }),
  select: (id) => set({ selectedId: id }),
  applyTick: (patch) => set((s) => ({ ...s, ...patch })),
  pushEvent: (e) =>
    set((s) => ({ events: [e, ...s.events].slice(0, 24) })),
  applyFleet: (fleet) =>
    set({
      fleet,
      activeConstellationId: fleet.constellation_id,
      // Mirror fleet into NetworkKPIs so existing NetworkOverview reads stay
      // valid even before its component-level rewrite.
      network: {
        total: fleet.total,
        online: fleet.online,
        links_total: fleet.links_total,
        isl_links: fleet.isl_links,
        gsl_links: fleet.gsl_links,
        coverage_pct: fleet.coverage_pct,
        agg_throughput_mbps: fleet.agg_throughput_mbps,
      },
    }),
  setPresets: (presets) => set({ presets }),
  setActiveConstellation: (id) => set({ activeConstellationId: id }),
  setConstellationDetail: (d) =>
    // Clamp selectedSatIdx to the new fleet size so a smaller preset doesn't
    // leave the selection pointing past the last sat.
    set((s) => ({
      constellationDetail: d,
      selectedSatIdx: d ? Math.min(s.selectedSatIdx, d.total_sats - 1) : 0,
    })),
  setSelectedSatIdx: (i) => set({ selectedSatIdx: Math.max(0, i) }),
  setSatConfig: (patch) =>
    set((s) => ({ satConfig: { ...s.satConfig, ...patch } })),
}))
