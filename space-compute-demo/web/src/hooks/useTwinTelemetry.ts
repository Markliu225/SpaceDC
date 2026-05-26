import { useEffect, useRef, useState } from 'react'
import { useTelemetryStore } from '../store/useTelemetryStore'
import { useDemoStore } from '../store/demoStore'
import type { SatelliteConfig, SatelliteState } from '../types/messages'
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

/**
 * useTwinTelemetry — 1Hz time series for the active satellite under the
 * applied SatelliteConfig.
 *
 *  - When the backend's `state_update` is reaching us (lastState present),
 *    we drive the rolling buffer off the AUTHORITATIVE per-tick values:
 *    solar_input_w / payload_power_w / battery_soc / temperature_c /
 *    gpu_utilization come straight from `lastState.satellite`. This is
 *    the Phase 2 path.
 *
 *  - When backend is offline (no lastState yet), we fall back to a local
 *    synthesis driven by `useTelemetryStore.sim_time_s` and the cfg
 *    tables — same formulas as backend's _update_placeholder_physics so
 *    the visual matches when backend comes back online.
 *
 *  - Whenever `cfg` changes, we record a scar marker at the current
 *    buffer tail; the strip paints a dashed vertical line that scrolls
 *    left and fades out as the buffer ages past it.
 */
export function useTwinTelemetry(): TwinTelemetrySnapshot {
  const cfg       = useTelemetryStore((s) => s.satConfig)
  const running   = useTelemetryStore((s) => s.running)
  const simT      = useTelemetryStore((s) => s.sim_time_s)
  const lastState = useDemoStore((s) => s.lastState)

  const [snap, setSnap] = useState<TwinTelemetrySnapshot>(() => {
    const seed = lastState?.satellite
      ? backendSample(lastState.satellite)
      : deriveSample(cfg, simT)
    return {
      current: seed,
      series:  prefill(seed),
      scars:   [],
    }
  })

  // Cfg-change scar — stash JSON to compare across renders cheaply.
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

  // 1Hz buffer advance — prefers backend-authoritative values when present.
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => {
      setSnap((prev) => {
        const sat = useDemoStore.getState().lastState?.satellite
        const sample = sat ? backendSample(sat) : deriveSample(cfg, simT)
        return advance(prev, sample)
      })
    }, 1000)
    return () => window.clearInterval(id)
  }, [running, cfg, simT])

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

/** Fill all 120 slots with the seed sample so the first render isn't blank. */
function prefill(seed: TwinTelemetrySnapshot['current']): TwinSeries {
  return {
    solar_w:     new Array(HISTORY_LEN).fill(seed.solar_w),
    payload_w:   new Array(HISTORY_LEN).fill(seed.payload_w),
    battery_soc: new Array(HISTORY_LEN).fill(seed.battery_soc),
    temp_c:      new Array(HISTORY_LEN).fill(seed.temp_c),
    gpu_util:    new Array(HISTORY_LEN).fill(seed.gpu_util),
  }
}

/** Append one new sample to each buffer + age scars (shift their index). */
function advance(
  prev: TwinTelemetrySnapshot,
  sample: TwinTelemetrySnapshot['current'],
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
