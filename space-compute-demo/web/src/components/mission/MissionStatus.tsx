import { useMissionStore } from '../../store/useMissionStore'
import { Card, Num } from '../primitives'
import { phaseLabel } from '../../data/missionPlan'
import { PhaseRail } from './PhaseRail'
import { DataVolumeBar } from './DataVolumeBar'
import { LatencyClock } from './LatencyClock'
import { MissionCast } from './MissionCast'

/**
 * MissionStatus — the /mission right rail. Stacks the phase rail, the
 * current-phase headline, the data-volume + latency read-outs, and the
 * cast. All fed from useMissionStore.mission.
 */
export function MissionStatus() {
  const mission = useMissionStore((s) => s.mission)

  return (
    <Card dense className="h-full flex flex-col min-h-0 overflow-y-auto">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Mission Status
        </span>
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
          {mission.active ? 'Running' : mission.phase === 'deliver' ? 'Complete' : 'Standby'}
        </span>
      </div>

      <div className="mt-2">
        <PhaseRail />
      </div>

      <div className="mt-3 flex items-baseline justify-between">
        <span className="text-[13px] font-semibold text-text-hi">
          {phaseLabel(mission.phase)}
        </span>
        <span className="flex items-baseline text-[11px] text-text-lo">
          targets&nbsp;
          <Num value={mission.targets_found} animate={false} className="text-text-hi" />
        </span>
      </div>

      <div className="mt-3 border-t border-border-weak pt-2">
        <DataVolumeBar />
      </div>

      <div className="mt-3 border-t border-border-weak pt-2">
        <LatencyClock />
      </div>

      <div className="mt-3 border-t border-border-weak pt-2">
        <MissionCast />
      </div>
    </Card>
  )
}
