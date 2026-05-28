import { useEffect } from 'react'
import { Play, Square } from 'lucide-react'
import { useDemoStore } from '../store/demoStore'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { useBackendBridge } from '../hooks/useBackendBridge'
import { useMissionFeed } from '../hooks/useMissionFeed'
import { useMissionStore } from '../store/useMissionStore'
import { EarthViewport } from '../components/overview/EarthViewport'
import { MissionStatus } from '../components/mission/MissionStatus'
import { MissionEventLog } from '../components/mission/MissionEventLog'

/**
 * MissionPage — 天数天算 (compute-in-space) choreography. Targets 1440×900.
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │ Header: 天数天算 MISSION · Start/Stop                          56px │
 *  ├──────────────────────────────────────────────┬─────────────────────┤
 *  │ EarthViewport (geo) — Earth + fleet + AOI +   │ MissionStatus col-4 │
 *  │   data packet + ISL/GSL beams          col-8  │  phase rail + reads │
 *  ├──────────────────────────────────────────────┴─────────────────────┤
 *  │ MissionEventLog                                          col-12·150 │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 * The viewport binds the overview (geo) camera since the mission spans the
 * whole constellation. The choreography prims are authored on the overview
 * stage in Phase 3 (space.demo.scene), gated behind /World/MissionGroup.
 */
export function MissionPage() {
  const changeCamera = useDemoStore((s) => s.changeCamera)
  const connected    = useDemoStore((s) => s.connected)
  useEffect(() => {
    if (connected) changeCamera('overview')
  }, [connected, changeCamera])

  useMockTelemetryFeed()
  useBackendBridge()
  const { start, stop } = useMissionFeed()

  const active = useMissionStore((s) => s.mission.active)
  const phase  = useMissionStore((s) => s.mission.phase)
  const running = active || phase !== 'idle'

  return (
    <div
      className="grid w-full bg-bg-app font-sans text-text-md gap-2.5 overflow-hidden"
      style={{
        height: 'calc(100vh - 44px - 24px - 4px)',
        gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
        gridTemplateRows: '56px minmax(0, 1fr) 150px',
      }}
    >
      {/* Row 1 — header. */}
      <div className="col-span-12 flex items-center justify-between rounded border border-border-weak bg-card px-3 min-h-0">
        <div className="flex items-center gap-3">
          <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
            天数天算 Mission
          </span>
          <span className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
            Compute-in-Space · Maritime Detection
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={start}
            className="flex items-center gap-1.5 rounded bg-accent/20 px-3 py-1 text-[12px] uppercase tracking-[0.08em] text-text-hi ring-1 ring-accent/40 hover:bg-accent/30"
          >
            <Play size={12} strokeWidth={2} /> Start Task
          </button>
          <button
            type="button"
            onClick={stop}
            disabled={!running}
            className={[
              'flex items-center gap-1.5 rounded px-3 py-1 text-[12px] uppercase tracking-[0.08em] ring-1 transition-colors',
              running
                ? 'bg-bg-inset/60 text-text-md ring-border-weak hover:bg-bg-cardHi'
                : 'text-text-faint ring-border-weak cursor-not-allowed',
            ].join(' ')}
          >
            <Square size={11} strokeWidth={2} /> Stop
          </button>
        </div>
      </div>

      {/* Row 2 — viewport + mission status. */}
      <div className="col-span-8 min-h-0 overflow-hidden">
        <EarthViewport />
      </div>
      <div className="col-span-4 min-h-0 overflow-hidden">
        <MissionStatus />
      </div>

      {/* Row 3 — event log. */}
      <div className="col-span-12 min-h-0 overflow-hidden">
        <MissionEventLog />
      </div>
    </div>
  )
}
