import { useCallback, useMemo } from 'react'
import { useTelemetryStore, SAT_CONFIG_BASELINE } from '../store/useTelemetryStore'
import { useDemoStore } from '../store/demoStore'
import { deriveStats, GEOMETRY_DEFAULT, type DerivedStats } from '../data/satConfigOptions'
import type { SatelliteConfig } from '../types/messages'

export interface UseSatConfigReturn {
  /** Currently-applied config (the source of truth in Phase 1 = local store;
   *  Phase 2 = mirrored from state_update.satellite_config). */
  cfg: SatelliteConfig
  /** Reference baseline used for delta chips. */
  baseline: SatelliteConfig
  /** Stats derived from `cfg` (memoised). */
  stats: DerivedStats
  /** Stats derived from `baseline` — for the Δ row. */
  baselineStats: DerivedStats
  /** Patch updater — partial config, merged into the store. */
  update: (patch: Partial<SatelliteConfig>) => void
}

/**
 * useSatConfig — single-call accessor + updater for the satellite hardware
 * loadout. Wraps the telemetry store so the Configurator components don't
 * have to wire to it directly and so the derived stats stay memoised across
 * renders.
 */
export function useSatConfig(): UseSatConfigReturn {
  const cfg           = useTelemetryStore((s) => s.satConfig)
  const setSatConfig  = useTelemetryStore((s) => s.setSatConfig)
  const sendSetConfig = useDemoStore((s) => s.sendSetConfig)
  // Live deployable geometry — mass/CAPEX/peak-solar must move when the
  // Deployables steppers (or a design switch) change the actual wings.
  const geom          = useDemoStore((s) => s.lastState?.twin_geometry) ?? GEOMETRY_DEFAULT

  const stats         = useMemo(() => deriveStats(cfg, geom),           [cfg, geom])
  const baselineStats = useMemo(() => deriveStats(SAT_CONFIG_BASELINE), [])

  const update = useCallback((patch: Partial<SatelliteConfig>) => {
    // Optimistic local write — the UI deltas + scar markers update at
    // dropdown-click latency, not WS round-trip latency.
    setSatConfig(patch)
    // Authoritative — backend recomputes physics, broadcasts state_update,
    // bridge writes the echoed value back over our optimistic one.
    sendSetConfig(patch)
  }, [setSatConfig, sendSetConfig])

  return { cfg, baseline: SAT_CONFIG_BASELINE, stats, baselineStats, update }
}
