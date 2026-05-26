import { useEffect, useRef, useState } from 'react'
import { useTelemetryStore } from '../store/useTelemetryStore'
import type { SatelliteConfig } from '../types/messages'
import {
  GPU_CARDS_PER_SAT,
  RADIATOR_PANELS_PER_SAT,
  gpuOption,
  radiatorMaterial,
  radiatorSize,
  solarMaterial,
  solarSize,
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

export interface TwinTelemetrySnapshot {
  /** Per-tick instantaneous read used by the SubsystemHealthRow + scalar tiles. */
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
}

const ZERO_SNAPSHOT: TwinTelemetrySnapshot = {
  current: { solar_w: 0, payload_w: 0, battery_soc: 0.8, temp_c: 30, gpu_util: 0, sunlit: true },
  series: {
    solar_w:    new Array(HISTORY_LEN).fill(0),
    payload_w:  new Array(HISTORY_LEN).fill(0),
    battery_soc: new Array(HISTORY_LEN).fill(0.8),
    temp_c:     new Array(HISTORY_LEN).fill(30),
    gpu_util:   new Array(HISTORY_LEN).fill(0),
  },
  scars: [],
}

/**
 * useTwinTelemetry — 1Hz synthesised time series for the currently-selected
 * sat under the currently-applied SatelliteConfig. Phase 1 computes
 * everything client-side; Phase 2 will replace the synthesis with
 * state_update broadcasts from backend (formulas match exactly so the
 * Phase 1 → Phase 2 hand-off is invisible).
 *
 * Records a scar marker whenever the SatelliteConfig changes mid-stream,
 * so the strip can paint a dashed vertical line at that point.
 */
export function useTwinTelemetry(): TwinTelemetrySnapshot {
  const cfg     = useTelemetryStore((s) => s.satConfig)
  const running = useTelemetryStore((s) => s.running)
  const simT    = useTelemetryStore((s) => s.sim_time_s)

  const [snap, setSnap] = useState<TwinTelemetrySnapshot>(() => ({
    ...ZERO_SNAPSHOT,
    series: cloneSeries(ZERO_SNAPSHOT.series),
    scars:  [],
  }))

  // Stash the previous cfg JSON to detect change events without re-running
  // setState every render — only on actual config delta.
  const lastCfgRef = useRef<string>(JSON.stringify(cfg))

  // Record a scar whenever cfg changes (the page re-renders, we compare).
  useEffect(() => {
    const next = JSON.stringify(cfg)
    if (next === lastCfgRef.current) return
    const prevCfg = JSON.parse(lastCfgRef.current)
    const changed = Object.keys(cfg).filter((k) => (cfg as never)[k] !== prevCfg[k])
    lastCfgRef.current = next
    if (changed.length === 0) return
    setSnap((s) => ({
      ...s,
      scars: [
        ...s.scars,
        {
          index: HISTORY_LEN - 1,
          sim_time_s: simT,
          label: changed.map((k) => `${k}=${(cfg as never)[k]}`).join(' · '),
        },
      ],
    }))
  }, [cfg, simT])

  // 1Hz tick — append a synthesised sample.
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => {
      setSnap((prev) => advance(prev, cfg, simT))
    }, 1000)
    return () => window.clearInterval(id)
  }, [running, cfg, simT])

  return snap
}

function cloneSeries(s: TwinSeries): TwinSeries {
  return {
    solar_w:     s.solar_w.slice(),
    payload_w:   s.payload_w.slice(),
    battery_soc: s.battery_soc.slice(),
    temp_c:      s.temp_c.slice(),
    gpu_util:    s.gpu_util.slice(),
  }
}

/** Append one new sample to each buffer + age scars (shift their index). */
function advance(
  prev: TwinTelemetrySnapshot,
  cfg: SatelliteConfig,
  simT: number,
): TwinTelemetrySnapshot {
  const sample = deriveSample(cfg, simT)

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

  return { current: sample, series, scars }
}

const SOLAR_CONSTANT_W_M2 = 1361

/** One-tick derivation — mirrors backend's _update_placeholder_physics. */
function deriveSample(cfg: SatelliteConfig, simT: number) {
  const g  = gpuOption(cfg.gpu)
  const sm = solarMaterial(cfg.solar_material)
  const ss = solarSize(cfg.solar_size)
  const rm = radiatorMaterial(cfg.radiator_material)
  const rs = radiatorSize(cfg.radiator_size)

  // Orbit phase — ISS-ish period of 5400 s scaled 60× = 90 s demo period.
  const orbitPhase = (simT * 60) / 5400
  const sunlit     = Math.sin(orbitPhase * Math.PI * 2) > -0.2
  const cosA       = Math.max(0, Math.sin(orbitPhase * Math.PI * 2 + 0.2))

  const solar_w =
    sm.efficiency * ss.area_m2_per_panel * ss.panel_count * SOLAR_CONSTANT_W_M2 * cosA * (sunlit ? 1 : 0)

  const gpu_util  = sunlit ? 0.45 + 0.35 * Math.sin(simT / 12) : 0
  const payload_w = g.tdp_w * GPU_CARDS_PER_SAT * gpu_util

  // Linear thermal proxy from the implementation doc.
  const radiator_capacity = rm.emissivity * RADIATOR_PANELS_PER_SAT * rs.area_m2_per_panel
  const temp_c = 28 + (50 * gpu_util) / Math.max(0.05, radiator_capacity)

  // Battery — slow drift. Net power positive when solar > payload + platform.
  const platform_w = 600
  const net_w = solar_w - payload_w - platform_w
  // 1Hz tick × tiny normalization keeps SOC inside [0, 1] for the demo timescale.
  const drift = Math.max(-0.005, Math.min(0.005, net_w / 80000))
  // Use a tiny pseudo-state via sim time so we don't need to thread through prev state.
  const battery_soc = Math.max(
    0,
    Math.min(1, 0.78 + 0.18 * Math.sin(simT / 90) + drift * 5),
  )

  return { solar_w, payload_w, battery_soc, temp_c, gpu_util, sunlit }
}
