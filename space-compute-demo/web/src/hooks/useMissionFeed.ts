import { useCallback, useEffect, useRef } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useMissionStore } from '../store/useMissionStore'
import { useFleetPositions } from './useFleetPositions'
import {
  DEFAULT_AOI,
  GROUND_STATIONS,
  TOTAL_MISSION_S,
  angularDist,
  missionStateAt,
  type MissionCastInput,
} from '../data/missionPlan'
import type { MissionState } from '../types/messages'

const MOCK_TICK_MS = 100

/**
 * useMissionFeed — owns the /mission page's mission state lifecycle.
 *
 *  - Mirrors backend `state_update.mission` into the store when present
 *    (Phase 2 path) and tears down any running local mock so backend wins.
 *  - Provides `start()` / `stop()`. `start()` fires the `start_mission` WS
 *    command (backend, when it exists) AND kicks a local mock driver so
 *    the choreography animates even before the backend MissionEngine
 *    lands (Phase 1).
 *
 *  Cast assignment for the mock: Sensor = fleet sat nearest the AOI; Hub =
 *  fleet index 0; Ground = nearest ground station to the hub's sub-point.
 *  (Backend will own this once Phase 2 is live.)
 */
export function useMissionFeed() {
  const setMissionMock    = useMissionStore((s) => s.setMissionMock)
  const setMissionBackend = useMissionStore((s) => s.setMissionBackend)
  const resetMission      = useMissionStore((s) => s.resetMission)
  const startMissionCmd   = useDemoStore((s) => s.startMission)
  const stopMissionCmd    = useDemoStore((s) => s.stopMission)
  const fleet             = useFleetPositions()

  const mockTimer = useRef<number | null>(null)
  const fleetRef  = useRef(fleet)
  fleetRef.current = fleet

  const clearMock = useCallback(() => {
    if (mockTimer.current !== null) {
      window.clearInterval(mockTimer.current)
      mockTimer.current = null
    }
  }, [])

  // Backend mirror — a real mission snapshot supersedes the mock.
  useEffect(() => {
    return useDemoStore.subscribe((s, prev) => {
      if (s.lastState === prev.lastState) return
      const m = (s.lastState as { mission?: MissionState } | null)?.mission
      if (m && m.active) {
        clearMock()
        setMissionBackend(m)
      }
    })
  }, [setMissionBackend, clearMock])

  useEffect(() => clearMock, [clearMock])

  const pickCast = useCallback((): MissionCastInput => {
    const sats = fleetRef.current
    let sensorIdx = 0
    if (sats.length > 0) {
      let best = Infinity
      for (const s of sats) {
        const d = angularDist(s.lat, s.lon, DEFAULT_AOI.lat, DEFAULT_AOI.lon)
        if (d < best) { best = d; sensorIdx = s.idx }
      }
    }
    const hubIdx = 0
    // Nearest ground station to the hub sub-point (fallback: first GS).
    const hub = sats.find((s) => s.idx === hubIdx) ?? sats[0]
    let ground = GROUND_STATIONS[0]
    if (hub) {
      let best = Infinity
      for (const gs of GROUND_STATIONS) {
        const d = angularDist(hub.lat, hub.lon, gs.lat, gs.lon)
        if (d < best) { best = d; ground = gs }
      }
    }
    return { sensor_idx: sensorIdx, hub_idx: hubIdx, ground }
  }, [])

  const start = useCallback(() => {
    // Fire the backend command (no-op until Phase 2 — backend replies
    // unknown_type, harmless). Then run the local mock as the driver;
    // the backend-mirror effect will take over + clear the mock if a real
    // mission snapshot arrives.
    startMissionCmd()
    clearMock()
    const cast = pickCast()
    const t0 = performance.now()
    mockTimer.current = window.setInterval(() => {
      const t = (performance.now() - t0) / 1000
      setMissionMock(missionStateAt(Math.min(t, TOTAL_MISSION_S), cast))
      if (t >= TOTAL_MISSION_S) clearMock()  // leave the delivered state up
    }, MOCK_TICK_MS)
  }, [startMissionCmd, clearMock, pickCast, setMissionMock])

  const stop = useCallback(() => {
    stopMissionCmd()
    clearMock()
    resetMission()
  }, [stopMissionCmd, clearMock, resetMission])

  return { start, stop }
}
