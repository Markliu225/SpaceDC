import { Check } from 'lucide-react'
import { useMissionStore } from '../../store/useMissionStore'
import { PHASE_PLAN, phaseIndex } from '../../data/missionPlan'
import { colors } from '../../design/tokens'

/**
 * PhaseRail — the 6-beat mission timeline (acquire → deliver). The active
 * phase glows accent; completed phases show a check; the active phase also
 * draws a thin progress underline driven by mission.phase_progress.
 */
export function PhaseRail() {
  const mission = useMissionStore((s) => s.mission)
  const curIdx = phaseIndex(mission.phase)

  return (
    <div className="grid grid-cols-6 gap-1.5">
      {PHASE_PLAN.map((p, i) => {
        const done = curIdx > i || (curIdx === i && mission.phase_progress >= 1 && i === PHASE_PLAN.length - 1)
        const active = curIdx === i && mission.active
        const fill = active ? `${mission.phase_progress * 100}%` : done ? '100%' : '0%'
        return (
          <div
            key={p.phase}
            className={[
              'relative flex flex-col gap-1 rounded border px-1.5 py-1.5 transition-colors',
              active ? 'border-accent/50 bg-accent/10' :
              done   ? 'border-ok/30 bg-ok/5' :
                       'border-border-weak bg-bg-inset/40',
            ].join(' ')}
          >
            <div className="flex items-center justify-between">
              <span className={[
                'flex h-4 w-4 items-center justify-center rounded-full text-[9px] tabular',
                active ? 'bg-accent text-bg-app' :
                done   ? 'bg-ok text-bg-app' :
                         'bg-bg-cardHi text-text-lo',
              ].join(' ')}>
                {done ? <Check size={10} strokeWidth={3} /> : i + 1}
              </span>
            </div>
            <span className={[
              'text-[9px] uppercase tracking-[0.06em] leading-tight',
              active ? 'text-text-hi' : done ? 'text-text-md' : 'text-text-lo',
            ].join(' ')}>
              {p.label}
            </span>
            {/* progress underline */}
            <div className="mt-0.5 h-0.5 w-full overflow-hidden rounded-full bg-bg-inset">
              <div
                className="h-full rounded-full transition-[width] duration-150 ease-linear"
                style={{
                  width: fill,
                  background: done ? colors.ok : colors.accent,
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
