import { useEffect } from 'react'
import { useTelemetryStore } from '../store/useTelemetryStore'
import type { EventEntry } from '../store/useTelemetryStore'

/** Realistic drift parameters per tick. */
const DOWNLINK_BASE_MBPS = 84
const UPLINK_BASE_MBPS   = 22
const RNG = mulberry32(0xC0FFEE) // deterministic; brief calls for reproducible donut, but live drift can be deterministic too.

/** Cheap deterministic PRNG. */
function mulberry32(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return (((t ^ (t >>> 14)) >>> 0) % 1_000_000) / 1_000_000
  }
}

function hhmmss(d = new Date()) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const RANDOM_EVENTS: Omit<EventEntry, 'id' | 'ts'>[] = [
  { kind: 'ok',   label: 'Link established',     entities: 'SAT-07 → SAT-13' },
  { kind: 'info', label: 'Telemetry packet',     entities: 'SAT-15 · 2.4 KB' },
  { kind: 'warn', label: 'Battery warning',      entities: 'SAT-22 · SOC 18%' },
  { kind: 'ok',   label: 'AOS Svalbard',         entities: 'GS-ARC-01 · SAT-04' },
  { kind: 'info', label: 'Maritime image batch', entities: 'SAT-07 · 5.1 GB' },
  { kind: 'ok',   label: 'Eclipse exit',         entities: 'SAT-12' },
  { kind: 'err',  label: 'GPU thermal alarm',    entities: 'SAT-09 · 78°C' },
  { kind: 'info', label: 'Downlink scheduled',   entities: 'SAT-09 → GS-EU-02' },
]

/**
 * useMockTelemetryFeed — single global 1Hz driver. Pauses when store.running
 * is false (toggled by the page header Pause / Play buttons). Updates:
 *   - sim_time_s
 *   - downlink / uplink history rings (push + shift, keep 60)
 *   - aggregate throughput (sum of online sat downlinks)
 *   - select sat's gpu / temp / soc / downlink drift
 *   - 1 random event every ~12 ticks
 *   - upcoming countdown decrement
 */
export function useMockTelemetryFeed() {
  const running = useTelemetryStore((s) => s.running)

  useEffect(() => {
    if (!running) return
    let tick = 0
    const id = window.setInterval(() => {
      const s = useTelemetryStore.getState()
      tick++

      // ---- Sparkline drift.
      const dlNext = Math.max(
        20,
        DOWNLINK_BASE_MBPS + 40 * Math.sin(s.sim_time_s / 7) + (RNG() - 0.5) * 18,
      )
      const ulNext = Math.max(
        4,
        UPLINK_BASE_MBPS + 8 * Math.sin(s.sim_time_s / 5 + 1) + (RNG() - 0.5) * 6,
      )

      // ---- Per-sat drift — keep `online` busy with sinusoidal GPU/temp.
      const sats = s.sats.map((sat) => {
        if (sat.status !== 'online') return sat
        const util = 0.45 + 0.35 * Math.sin(s.sim_time_s / 12 + sat.ribbon)
        const temp = 56 + 18 * util + (RNG() - 0.5) * 1.2
        const dl   = (sat.id === 'SAT-07' || sat.id === 'SAT-09')
          ? 120 + 12 * Math.sin(s.sim_time_s / 4)
          : sat.downlink_mbps
        return {
          ...sat,
          gpu_utilization: util,
          payload_power_w: 420 + 1700 * util,
          temperature_c: temp,
          downlink_mbps: dl,
          // Battery slow drift; eclipse drains, online charges very slowly.
          battery_soc: Math.max(0, Math.min(1, sat.battery_soc + 0.0006 * (util > 0.55 ? -1 : 1))),
          lon: (sat.lon + 0.6) % 360 - (sat.lon + 0.6 > 180 ? 360 : 0),
        }
      })

      // ---- Network KPIs derived from satellite states.
      const onlineCount = sats.filter((x) => x.status === 'online').length
      const agg = sats.reduce((sum, x) => sum + x.downlink_mbps, 0)
      const network = {
        ...s.network,
        online: onlineCount,
        coverage_pct: 84 + 4 * Math.sin(s.sim_time_s / 11),
        agg_throughput_mbps: Math.round(agg + dlNext),
      }

      // ---- Upcoming countdowns.
      const upcoming = s.upcoming.map((e) => ({
        ...e,
        countdown_s: Math.max(0, e.countdown_s - 1),
      }))

      s.applyTick({
        sim_time_s: s.sim_time_s + 1,
        sats,
        network,
        downlink_history: [...s.downlink_history.slice(1), dlNext],
        uplink_history:   [...s.uplink_history.slice(1),   ulNext],
        upcoming,
      })

      // ---- Random event every ~12s.
      if (tick % 12 === 0) {
        const e = RANDOM_EVENTS[Math.floor(RNG() * RANDOM_EVENTS.length)]
        s.pushEvent({
          id: `ev-${Date.now()}`,
          ts: hhmmss(),
          ...e,
        })
      }
    }, 1000)

    return () => window.clearInterval(id)
  }, [running])
}
