import { create } from 'zustand'
import type { MissionState } from '../types/messages'
import { DEFAULT_AOI, GROUND_STATIONS } from '../data/missionPlan'

export const IDLE_MISSION: MissionState = {
  active: false,
  phase: 'idle',
  phase_progress: 0,
  elapsed_s: 0,
  data_volume_mb: 0,
  targets_found: 0,
  sensor_idx: -1,
  hub_idx: -1,
  aoi_lat: DEFAULT_AOI.lat,
  aoi_lon: DEFAULT_AOI.lon,
  ground_lat: GROUND_STATIONS[0].lat,
  ground_lon: GROUND_STATIONS[0].lon,
  ground_id: GROUND_STATIONS[0].id,
}

interface MissionStore {
  /** Current mission state — single source of truth for the /mission page.
   *  Fed by the local mock driver (Phase 1) or backend state_update.mission
   *  (Phase 2). */
  mission: MissionState
  /** Where the current value came from, so the mock can yield to backend. */
  source: 'idle' | 'mock' | 'backend'
  setMissionMock: (m: MissionState) => void
  setMissionBackend: (m: MissionState) => void
  resetMission: () => void
}

export const useMissionStore = create<MissionStore>((set) => ({
  mission: { ...IDLE_MISSION },
  source: 'idle',
  setMissionMock: (m) => set({ mission: m, source: 'mock' }),
  setMissionBackend: (m) => set({ mission: m, source: 'backend' }),
  resetMission: () => set({ mission: { ...IDLE_MISSION }, source: 'idle' }),
}))
