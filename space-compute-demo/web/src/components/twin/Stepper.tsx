/**
 * Stepper — the ±/value row the Configurator's Deployables block and the
 * satellite builder's structure step both use for a bounded numeric knob.
 */
export function Stepper({
  label, value, onDec, onInc, decDisabled, incDisabled,
}: {
  label: string; value: string
  onDec: () => void; onInc: () => void
  decDisabled?: boolean; incDisabled?: boolean
}) {
  const btn = 'flex h-5 w-5 items-center justify-center rounded border border-border-weak text-text-md ' +
    'hover:bg-bg-card-hi hover:text-text-hi disabled:opacity-30 disabled:cursor-not-allowed'
  return (
    <div className="flex items-center justify-between rounded border border-border-weak bg-bg-inset/40 px-2 py-1">
      <span className="text-[11px] text-text-md">{label}</span>
      <div className="flex items-center gap-1.5">
        <button type="button" onClick={onDec} disabled={decDisabled} className={btn} aria-label={`decrease ${label}`}>−</button>
        <span className="w-12 text-right font-mono tabular-nums text-[11px] text-text-hi">{value}</span>
        <button type="button" onClick={onInc} disabled={incDisabled} className={btn} aria-label={`increase ${label}`}>+</button>
      </div>
    </div>
  )
}
