import { ArrowDown, ArrowRight, ArrowUp, type LucideIcon } from 'lucide-react'
import { Num } from '../primitives'

interface ConfigDeltaProps {
  label: string
  baseline: number
  current: number
  digits?: number
  unit: string
  /** "higher_is_better" or "lower_is_better" — decides whether an increase
   *  paints green (ok) or red (warn). For "neutral" the arrow is gray. */
  bias?: 'higher_is_better' | 'lower_is_better' | 'neutral'
  icon?: LucideIcon
}

/**
 * ConfigDelta — single row of the live-deltas block. Shows the metric's
 * current value, a 12px arrow chip indicating direction vs baseline, and
 * the absolute delta. Used 4× under the Configurator dropdowns.
 */
export function ConfigDelta({
  label, baseline, current, digits = 0, unit, bias = 'neutral', icon: Icon,
}: ConfigDeltaProps) {
  const diff = current - baseline
  const eps = Math.max(0.001, Math.abs(baseline) * 0.005)

  let direction: 'up' | 'down' | 'flat' = 'flat'
  if (diff > eps)  direction = 'up'
  if (diff < -eps) direction = 'down'

  const goodDir =
    bias === 'higher_is_better' ? 'up'   :
    bias === 'lower_is_better'  ? 'down' :
                                  null

  const toneCls =
    direction === 'flat' ? 'text-text-lo' :
    goodDir === direction ? 'text-ok' :
    goodDir === null ? 'text-text-md' :
    'text-warn'

  const Arrow =
    direction === 'up'   ? ArrowUp :
    direction === 'down' ? ArrowDown :
                           ArrowRight

  return (
    <div className="grid grid-cols-[1fr_auto_auto] items-baseline gap-2 text-[12px]">
      <span className="flex items-center gap-1.5 text-text-md min-w-0">
        {Icon && <Icon size={12} strokeWidth={1.6} className="text-text-lo" />}
        <span className="truncate">{label}</span>
      </span>
      <span className="flex items-baseline tabular">
        <Num value={current} digits={digits} className="text-text-hi" />
        <span className="ml-1 text-[10px] text-text-lo">{unit}</span>
      </span>
      <span className={`flex items-center gap-0.5 text-[10px] tabular ${toneCls}`}>
        <Arrow size={10} strokeWidth={2} />
        <Num value={Math.abs(diff)} digits={digits} />
      </span>
    </div>
  )
}
