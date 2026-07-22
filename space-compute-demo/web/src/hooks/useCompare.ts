import { useCallback, useState } from 'react'
import { useDemoStore } from '../store/demoStore'
import type { CompareLiveState, CompareOptions } from '../types/messages'

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://localhost:8001'

/**
 * useCompare — data source + controls for the Twin page's live what-if
 * comparison.
 *
 * `loadOptions()` fetches the comparable dimensions (every Configurator knob
 * plus whole designs) with the live loadout's current values. `start()` POSTs
 * a dimension + 2–4 candidate values: the backend seeds one offline engine
 * per variant from the live state and steps them in LOCKSTEP with the 1 Hz
 * physics tick, so the curves evolve in real time on the telemetry strip.
 * The running comparison itself arrives on the broadcast state
 * (`lastState.compare_live`) — one current sample per variant per tick.
 */
export function useCompare() {
  const [options, setOptions] = useState<CompareOptions | null>(null)
  const [busy, setBusy] = useState(false)
  const [offline, setOffline] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const compareLive: CompareLiveState | null =
    useDemoStore((s) => s.lastState?.compare_live ?? null)

  const loadOptions = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/compare/options`)
      if (!r.ok) throw new Error(`${r.status}`)
      setOptions((await r.json()) as CompareOptions)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  const start = useCallback(async (
    dimension: string, values: (string | number)[],
  ): Promise<boolean> => {
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${BACKEND_HTTP}/compare/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dimension, values }),
      })
      if (!r.ok) {
        const detail = await r.json().catch(() => null) as { detail?: string } | null
        setError(detail?.detail ?? `Failed to start comparison (${r.status})`)
        return false
      }
      setOffline(false)
      return true
    } catch {
      setOffline(true)
      setError('Backend offline — start the FastAPI server (port 8001) to run comparisons.')
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  const stop = useCallback(async (): Promise<boolean> => {
    setBusy(true)
    try {
      const r = await fetch(`${BACKEND_HTTP}/compare/stop`, { method: 'POST' })
      return r.ok
    } catch {
      setOffline(true)
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  return { options, compareLive, busy, offline, error, loadOptions, start, stop }
}
