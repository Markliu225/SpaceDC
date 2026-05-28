import { useMissionStore } from '../../store/useMissionStore'
import { Num } from '../primitives'
import { RAW_DATA_MB, RESULT_MB } from '../../data/missionPlan'

/** Format an MB value as GB / MB for display. */
function fmtBytes(mb: number): { value: number; unit: string; digits: number } {
  if (mb >= 1024) return { value: mb / 1024, unit: 'GB', digits: 2 }
  if (mb >= 1)    return { value: mb,         unit: 'MB', digits: 0 }
  return { value: mb * 1024, unit: 'KB', digits: 0 }
}

/**
 * DataVolumeBar — shows the in-flight packet size shrinking from 5 GB raw
 * capture to a 2 MB result. Bar is LOG-scaled (RESULT_MB .. RAW_DATA_MB)
 * because a linear bar can't show a 2500× collapse — the log bar visibly
 * empties as inference compresses the data.
 */
export function DataVolumeBar() {
  const mission = useMissionStore((s) => s.mission)
  const mb = mission.data_volume_mb

  const lo = Math.log(RESULT_MB)
  const hi = Math.log(RAW_DATA_MB)
  const frac = mb > 0
    ? Math.max(0, Math.min(1, (Math.log(Math.max(RESULT_MB, mb)) - lo) / (hi - lo)))
    : 0

  const f = fmtBytes(mb > 0 ? mb : 0)
  const compressed = mb > 0 && mb < RAW_DATA_MB
  const ratio = mb > 0 ? RAW_DATA_MB / Math.max(RESULT_MB, mb) : 1

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
          Data Packet
        </span>
        <span className="flex items-baseline">
          <Num value={f.value} digits={f.digits} animate={false}
               className="text-[14px] font-semibold text-text-hi" />
          <span className="ml-1 text-[10px] text-text-lo">{f.unit}</span>
        </span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-bg-inset">
        <div
          className="h-full rounded-full transition-[width] duration-150 ease-out"
          style={{
            width: `${frac * 100}%`,
            background: compressed
              ? 'linear-gradient(90deg, #22C55E 0%, #3B9EFF 100%)'
              : 'linear-gradient(90deg, #3B9EFF 0%, #E0EEFF 100%)',
            boxShadow: '0 0 8px rgba(59,158,255,0.4)',
          }}
        />
      </div>
      <div className="mt-0.5 flex items-center justify-between text-[9px] tabular text-text-faint">
        <span>{RESULT_MB} MB result</span>
        <span>
          {compressed && mb < RAW_DATA_MB
            ? <>compressed <span className="text-ok">{ratio.toFixed(0)}×</span></>
            : '5 GB raw'}
        </span>
      </div>
    </div>
  )
}
