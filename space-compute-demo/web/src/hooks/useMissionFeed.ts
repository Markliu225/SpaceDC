import { useCallback, useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useMissionStore } from '../store/useMissionStore'
import type { MissionState } from '../types/messages'

const POLL_MS = 100
const HTTP_BASE =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://localhost:8001'

/**
 * useMissionFeed — owns the /mission page's mission lifecycle.
 *
 * The backend MissionEngine is the single source of truth: it runs the
 * wall-clock phase machine AND the scene-load gate (it holds on 'acquire'
 * until Kit reports the target scene geometry is resident). We poll /state at
 * 10 Hz and mirror `mission` straight into the store, so the side panel and
 * the Omniverse 3D scene are driven by the *same* clock and can never desync —
 * and the loading hold is honoured by the UI as well.
 *
 * (Earlier there was a local mock driver here with its own clock; it raced the
 * backend and is the reason the panel and 3D could drift. Retired.)
 */
export function useMissionFeed() {
  const setMissionBackend = useMissionStore((s) => s.setMissionBackend)
  const resetMission      = useMissionStore((s) => s.resetMission)
  const startMissionCmd   = useDemoStore((s) => s.startMission)
  const stopMissionCmd    = useDemoStore((s) => s.stopMission)

  useEffect(() => {
    let alive = true
    let inFlight = false
    const tick = async () => {
      if (inFlight) return
      inFlight = true
      try {
        const r = await fetch(`${HTTP_BASE}/state`)
        const s = (await r.json()) as { mission?: MissionState }
        if (alive && s.mission) setMissionBackend(s.mission)
      } catch {
        /* backend momentarily unreachable — keep the last state */
      } finally {
        inFlight = false
      }
    }
    const id = window.setInterval(tick, POLL_MS)
    tick()
    return () => { alive = false; window.clearInterval(id) }
  }, [setMissionBackend])

  const start = useCallback(() => {
    startMissionCmd()
  }, [startMissionCmd])

  const stop = useCallback(() => {
    stopMissionCmd()
    resetMission()
  }, [stopMissionCmd, resetMission])

  return { start, stop }
}
