import { useEffect, useRef, useState } from 'react'
import { useTelemetryStore } from '../store/useTelemetryStore'
import { useDemoStore } from '../store/demoStore'
import type {
  CompareLiveState, SatelliteConfig, SatelliteState,
} from '../types/messages'
import {
  GPU_CARDS_PER_SAT,
  GEOMETRY_DEFAULT,
  gpuOption,
  radiatorMaterial,
  radiatorEmitAreaM2,
  solarAreaM2,
  solarMaterial,
} from '../data/satConfigOptions'

const HISTORY_LEN = 120

export interface TwinSeries {
  solar_w: number[]
  payload_w: number[]
  battery_soc: number[]
  temp_c: number[]
  gpu_util: number[]
}

export interface TwinScar {
  /** Sample index where the change happened (in the HISTORY_LEN-length ring). */
  index: number
  /** sim_time_s tag at the time of change. */
  sim_time_s: number
  /** Short human-readable description of what changed. */
  label: string
}

/** One what-if variant's growing curve set — same metric keys as the main
 *  ring so the strip can overlay them 1:1. Arrays start empty when the
 *  comparison starts and grow one sample per broadcast, right-aligned with
 *  the main window (capped at HISTORY_LEN). */
export interface CompareOverlayVariant {
  value: string | number
  label: string
  series: TwinSeries
}

export interface CompareOverlay {
  /** Identity of the running comparison — a new key restarts the rings. */
  key: string
  dimension_label: string
  variants: CompareOverlayVariant[]
}

export interface TwinTelemetrySnapshot {
  /** Per-tick instantaneous read used by the strip headers + scalar tiles. */
  current: {
    solar_w: number
    payload_w: number
    battery_soc: number
    temp_c: number
    gpu_util: number
    sunlit: boolean
  }
  /** Rolling buffers, 0..HISTORY_LEN-1, newest at end. */
  series: TwinSeries
  /** Scar markers for config changes that happened within the visible window. */
  scars: TwinScar[]
  /** Live what-if comparison overlays — null when no comparison is running. */
  compare: CompareOverlay | null
}

/**
 * useTwinTelemetry — rolling time-series for the currently-selected sat.
 *
 *  The buffer ADVANCES driven by two independent triggers, whichever fires
 *  first per tick:
 *
 *    1. **WS state_update arrival** — when the backend pushes a new
 *       SatelliteState (this is the 1 Hz nominal cadence), we subscribe
 *       to `demoStore.lastState` and append the new authoritative values.
 *       This carries the FULL backend physics: orbit-phase-driven solar /
 *       sunlit, sinusoidal GPU utilisation, payload power scaled by the
 *       active SatelliteConfig's GPU TDP, thermal target dependent on the
 *       radiator material × area, integrated battery SOC.
 *
 *    2. **1 Hz local timer** — backup when backend is offline (no
 *       lastState yet). Pushes a deriveSample() driven by the local mock
 *       sim_time_s — same formulas as backend so the visual matches once
 *       backend reconnects.
 *
 *  Scar markers (vertical dashed lines on chart) get stamped at the tail
 *  position whenever `satConfig` changes.
 *
 *  Critical bug fixed (2026-05-28): the previous version keyed the 1 Hz
 *  effect on `[running, cfg, simT]`. `simT` increments every second, so
 *  the effect cleanup ran (clearInterval) and re-created the interval
 *  every second — meaning the 1 s callback was ALWAYS cleared before it
 *  fired. The buffer therefore stayed locked at the seed prefill and
 *  charts read as flat lines. Now we key on `[running]` only and read
 *  `cfg` / `lastState` via `getState()` inside the callback.
 */
export function useTwinTelemetry(): TwinTelemetrySnapshot {
  const cfg     = useTelemetryStore((s) => s.satConfig)
  const running = useTelemetryStore((s) => s.running)
  const simT    = useTelemetryStore((s) => s.sim_time_s)

  const [snap, setSnap] = useState<TwinTelemetrySnapshot>(() => {
    const sat = useDemoStore.getState().lastState?.satellite
    const seedCfg  = useTelemetryStore.getState().satConfig
    const seedSimT = useTelemetryStore.getState().sim_time_s
    // Backend connected → seed the whole window flat at the CURRENT backend
    // values: honest "no history yet", and real samples scroll in from the
    // right within seconds. Only the offline fallback pre-fills a synthetic
    // orbit pattern (there is nothing real to show in that mode anyway).
    if (sat) {
      const seedNow = backendSample(sat)
      return { current: seedNow, series: flatSeries(seedNow), scars: [], compare: null }
    }
    const seedNow = deriveSample(seedCfg, seedSimT)
    const series = backfillSeries(seedCfg, seedSimT, seedNow)
    return { current: seedNow, series, scars: [], compare: null }
  })

  // --- Cfg-change scar tracking ---------------------------------------
  const lastCfgRef = useRef<string>(JSON.stringify(cfg))
  useEffect(() => {
    const next = JSON.stringify(cfg)
    if (next === lastCfgRef.current) return
    const prevCfg = JSON.parse(lastCfgRef.current) as SatelliteConfig
    const changed = (Object.keys(cfg) as (keyof SatelliteConfig)[])
      .filter((k) => cfg[k] !== prevCfg[k])
    lastCfgRef.current = next
    if (changed.length === 0) return
    setSnap((s) => ({
      ...s,
      scars: [
        ...s.scars,
        {
          index: HISTORY_LEN - 1,
          sim_time_s: simT,
          label: changed.map((k) => `${k}=${cfg[k]}`).join(' · '),
        },
      ],
    }))
  }, [cfg, simT])

  // --- WS-driven append: react to lastState changes ------------------
  // demoStore writes a new `lastState` object on EVERY state_update; each
  // arrival appends a backend-authoritative sample AND timestamps the WS
  // path as live so the synth fallback knows to stay quiet.
  const lastWsAtRef = useRef<number>(0)
  useEffect(() => {
    return useDemoStore.subscribe((s, prev) => {
      if (s.lastState === prev.lastState) return
      const sat = s.lastState?.satellite
      if (!sat) return
      lastWsAtRef.current = Date.now()
      const compareLive = s.lastState?.compare_live ?? null
      setSnap((cur) => advance(cur, backendSample(sat), compareLive))
    })
  }, [])

  // --- Fallback synth tick: only fires when backend isn't pushing ----
  // Stable 1 Hz interval — independent of cfg/simT churn (those are read
  // freshly inside the callback so the interval handle never recreates).
  // Skips emitting if a WS state_update arrived within the last 1.8 s,
  // which avoids double-pushes when backend is healthy.
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => {
      if (Date.now() - lastWsAtRef.current < 1800) return
      const localCfg  = useTelemetryStore.getState().satConfig
      const localSimT = useTelemetryStore.getState().sim_time_s
      setSnap((cur) => advance(cur, deriveSample(localCfg, localSimT)))
    }, 1000)
    return () => window.clearInterval(id)
  }, [running])

  return snap
}

/** Pull a sample directly from the backend's authoritative SatelliteState. */
function backendSample(sat: SatelliteState): TwinTelemetrySnapshot['current'] {
  return {
    solar_w:     sat.solar_input_w,
    payload_w:   sat.payload_power_w,
    battery_soc: sat.battery_soc,
    temp_c:      sat.temperature_c,
    gpu_util:    sat.gpu_utilization,
    sunlit:      sat.sunlit,
  }
}

/** Whole-window flat prefill at one sample — the honest "connected but no
 *  history yet" seed. */
function flatSeries(s: TwinTelemetrySnapshot['current']): TwinSeries {
  return {
    solar_w:     new Array<number>(HISTORY_LEN).fill(s.solar_w),
    payload_w:   new Array<number>(HISTORY_LEN).fill(s.payload_w),
    battery_soc: new Array<number>(HISTORY_LEN).fill(s.battery_soc),
    temp_c:      new Array<number>(HISTORY_LEN).fill(s.temp_c),
    gpu_util:    new Array<number>(HISTORY_LEN).fill(s.gpu_util),
  }
}

/** Synthesise a backward-time history (oldest first, newest at tail) so the
 *  chart shows orbit-driven solar + sinusoidal load motion right away
 *  instead of a flat line that takes 120 s of real time to populate.
 *  When backend is live, real samples will replace each slot one tick at
 *  a time from the right edge, so within ~10 s the chart is showing only
 *  real values. */
function backfillSeries(
  cfg: SatelliteConfig,
  simT: number,
  liveSeed: TwinTelemetrySnapshot['current'],
): TwinSeries {
  const sample = (t: number) => deriveSample(cfg, t)
  // Newest = liveSeed (from backend if available) — anchored at index N-1.
  // Older entries = deriveSample at older sim times.
  const solar_w     = new Array<number>(HISTORY_LEN)
  const payload_w   = new Array<number>(HISTORY_LEN)
  const battery_soc = new Array<number>(HISTORY_LEN)
  const temp_c      = new Array<number>(HISTORY_LEN)
  const gpu_util    = new Array<number>(HISTORY_LEN)
  for (let i = 0; i < HISTORY_LEN; i++) {
    const ageS = HISTORY_LEN - 1 - i
    if (ageS === 0) {
      solar_w[i]     = liveSeed.solar_w
      payload_w[i]   = liveSeed.payload_w
      battery_soc[i] = liveSeed.battery_soc
      temp_c[i]      = liveSeed.temp_c
      gpu_util[i]    = liveSeed.gpu_util
    } else {
      const s = sample(Math.max(0, simT - ageS))
      solar_w[i]     = s.solar_w
      payload_w[i]   = s.payload_w
      battery_soc[i] = s.battery_soc
      temp_c[i]      = s.temp_c
      gpu_util[i]    = s.gpu_util
    }
  }
  return { solar_w, payload_w, battery_soc, temp_c, gpu_util }
}

/** Append one new sample to each buffer + age scars (shift their index).
 *
 *  `compareLive` semantics: `undefined` = no fresh backend info (offline
 *  synth tick) → keep the overlay as-is; `null`/inactive = comparison over
 *  → clear; active = append each variant's current sample to its growing
 *  ring (a NEW comparison identity restarts the rings from empty). */
function advance(
  prev: TwinTelemetrySnapshot,
  sample: TwinTelemetrySnapshot['current'],
  compareLive?: CompareLiveState | null,
): TwinTelemetrySnapshot {
  const push = (arr: number[], v: number): number[] => {
    const out = arr.slice(1)
    out.push(v)
    return out
  }

  const series: TwinSeries = {
    solar_w:     push(prev.series.solar_w,     sample.solar_w),
    payload_w:   push(prev.series.payload_w,   sample.payload_w),
    battery_soc: push(prev.series.battery_soc, sample.battery_soc),
    temp_c:      push(prev.series.temp_c,      sample.temp_c),
    gpu_util:    push(prev.series.gpu_util,    sample.gpu_util),
  }

  // Each scar's index shifts left by 1 (the buffer scrolled). Drop scars
  // that fell out of the visible window.
  const scars = prev.scars
    .map((s) => ({ ...s, index: s.index - 1 }))
    .filter((s) => s.index >= 0)

  let compare: CompareOverlay | null
  if (compareLive === undefined) {
    compare = prev.compare
  } else if (!compareLive?.active || compareLive.variants.length === 0) {
    compare = null
  } else {
    const key = `${compareLive.dimension}|${compareLive.start_sim_time_s}|`
      + compareLive.variants.map((v) => String(v.value)).join(',')
    // The elapsed-0 broadcast (fired by /compare/start before the first
    // lockstep tick) carries pre-computation defaults (0 W payload/solar) —
    // appending it would draw a false zero edge at every curve's start.
    // Register the comparison identity but only append REAL stepped samples.
    const stepped = compareLive.elapsed_s >= 1
    const growInto = (ring: number[], v: number): number[] => {
      if (!stepped) return ring
      const out = ring.length >= HISTORY_LEN ? ring.slice(1) : ring.slice()
      out.push(v)
      return out
    }
    const prevSame = prev.compare?.key === key ? prev.compare : null
    compare = {
      key,
      dimension_label: compareLive.dimension_label,
      variants: compareLive.variants.map((v, i) => {
        const base = prevSame?.variants[i]?.series
        return {
          value: v.value,
          label: v.label,
          series: {
            solar_w:     growInto(base?.solar_w ?? [],     v.solar_input_w),
            payload_w:   growInto(base?.payload_w ?? [],   v.payload_power_w),
            battery_soc: growInto(base?.battery_soc ?? [], v.battery_soc),
            temp_c:      growInto(base?.temp_c ?? [],      v.temperature_c),
            gpu_util:    growInto(base?.gpu_util ?? [],    v.gpu_utilization),
          },
        }
      }),
    }
  }

  return { current: sample, series, scars, compare }
}

const SOLAR_CONSTANT_W_M2 = 1361

/** One-tick derivation for the OFFLINE fallback — mirrors the backend's
 *  current physics: geometry-driven areas (twin_geometry, not the size
 *  tables), sun-tracking arrays (0.95 incidence while sunlit), the 15 % TDP
 *  idle floor, and a Stefan-Boltzmann equilibrium temperature. Approximate
 *  by design — it only ever renders when no backend is pushing. */
function deriveSample(cfg: SatelliteConfig, simT: number) {
  const g  = gpuOption(cfg.gpu)
  const sm = solarMaterial(cfg.solar_material)
  const rm = radiatorMaterial(cfg.radiator_material)
  const last = useDemoStore.getState().lastState
  const geom = last?.twin_geometry ?? GEOMETRY_DEFAULT
  const cards = last?.satellite?.gpu_count ?? GPU_CARDS_PER_SAT

  // Orbit phase — ISS-ish period of 5400 s scaled 60× = 90 s demo period.
  const orbitPhase = (simT * 60) / 5400
  const sunlit     = Math.sin(orbitPhase * Math.PI * 2) > -0.05

  // Sun-tracking wings: near-normal incidence whenever sunlit.
  const solar_w = sm.efficiency * solarAreaM2(geom) * SOLAR_CONSTANT_W_M2 * (sunlit ? 0.95 : 0)

  const gpu_util  = Math.max(0.05, sunlit ? 0.45 + 0.35 * Math.sin(simT / 12) : 0.2)
  const payload_w = g.tdp_w * cards * (0.15 + 0.85 * gpu_util)

  // Stefan-Boltzmann equilibrium at the current dissipation (the backend
  // integrates toward this with a ~30 s time constant; equilibrium is close
  // enough for a fallback trace).
  const platform_w = 600
  const SIGMA = 5.67e-8
  const T_BG4 = 250 ** 4
  const q_in = (payload_w + platform_w) * 0.95
  const emitArea = Math.max(0.1, rm.emissivity * radiatorEmitAreaM2(geom))
  const temp_c = Math.max(-80, Math.min(95,
    Math.pow(q_in / (SIGMA * emitArea) + T_BG4, 0.25) - 273.15))

  // Battery — slow drift. Net power positive when solar > payload + platform.
  const net_w = solar_w - payload_w - platform_w
  const drift = Math.max(-0.005, Math.min(0.005, net_w / 80000))
  // Use a tiny pseudo-state via sim time so we don't need to thread through prev state.
  const battery_soc = Math.max(
    0,
    Math.min(1, 0.78 + 0.18 * Math.sin(simT / 90) + drift * 5),
  )

  return { solar_w, payload_w, battery_soc, temp_c, gpu_util, sunlit }
}
