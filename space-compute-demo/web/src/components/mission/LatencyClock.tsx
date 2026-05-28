import { useMissionStore } from '../../store/useMissionStore'
import { Num } from '../primitives'
import { GROUND_COMPUTE_REF_S } from '../../data/missionPlan'

/** "41 min" style compact duration. */
function fmtDuration(s: number): string {
  if (s < 60) return `${s.toFixed(0)} s`
  const m = Math.floor(s / 60)
  return `${m} min`
}

/**
 * LatencyClock — time-to-result since capture. Counts up live while the
 * mission runs (driven by mission.elapsed_s) and freezes at delivery.
 * The grey caption states what the same task would cost via 天数地算
 * (ground compute) — a static reference, not a second animated path.
 */
export function LatencyClock() {
  const mission = useMissionStore((s) => s.mission)
  const delivered = mission.phase === 'deliver'

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
          Time to Result
        </span>
        {delivered && (
          <span className="text-[9px] uppercase tracking-[0.10em] text-ok">Delivered</span>
        )}
      </div>
      <div className="mt-0.5 flex items-baseline">
        <Num value={mission.elapsed_s} digits={1} animate={false}
             className="text-[24px] leading-none font-semibold text-text-hi" />
        <span className="ml-1 text-[12px] text-text-lo">s</span>
        <span className="ml-2 rounded bg-ok/15 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.08em] text-ok">
          天数天算
        </span>
      </div>
      <div className="mt-1 text-[10px] text-text-faint">
        天数地算 (ground compute) ≈{' '}
        <span className="text-text-lo">{fmtDuration(GROUND_COMPUTE_REF_S)}</span>
        {' '}— downlink raw, wait for pass, process on ground
      </div>
    </div>
  )
}
