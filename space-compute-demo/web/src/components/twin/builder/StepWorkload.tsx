import { Check, Loader2 } from 'lucide-react'
import type { WorkloadProfileInfo } from '../../../types/messages'

const fmt = (v: number) =>
  v >= 1e9 ? `${(v / 1e9).toFixed(2)}B`
  : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
  : v >= 1e3 ? `${(v / 1e3).toFixed(1)}k`
  : String(Math.round(v))

const fitTone = (fit: string) =>
  fit === 'ok' ? 'text-ok' : fit === 'tight' ? 'text-warn' : 'text-err'

/**
 * Step 4 — WORKLOAD: which job schedule the payload flies.
 *
 * Every option is annotated with how THIS DRAFT copes, not how the satellite
 * currently in orbit copes: the numbers come from the backend dry-run, which
 * commissions the draft on a detached engine and runs the same design check
 * the live panels use. So a schedule marked "ok" here is still "ok" after Run.
 */
export function StepWorkload({
  profiles, selected, loading, onPick,
}: {
  profiles: WorkloadProfileInfo[]
  selected: string
  loading: boolean
  onPick: (id: string) => void
}) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <p className="flex items-center gap-2 text-[13px] leading-relaxed text-text-lo">
        Pick the job schedule the GPUs will run. Fit is computed against the satellite you
        just built — average demand vs solar supply, and peak heat vs the radiator ceiling.
        {loading && <Loader2 size={14} className="animate-spin text-accent" />}
      </p>

      {profiles.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center rounded-md border border-border-weak bg-bg-inset/30 px-3 text-center text-[13px] text-text-lo">
          {loading ? 'Evaluating schedules against this design…'
                   : 'No schedules available — backend offline.'}
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 auto-rows-fr grid-cols-2 gap-3 overflow-y-auto pr-1">
          {profiles.map((p) => (
            <button
              key={p.id}
              type="button"
              data-testid={`build-workload-${p.id}`}
              onClick={() => onPick(p.id)}
              aria-pressed={p.id === selected}
              className={`flex flex-col gap-2 rounded-md border p-3.5 text-left transition-colors ${
                p.id === selected
                  ? 'border-accent bg-bg-card-hi'
                  : 'border-border-weak bg-bg-inset/40 hover:border-border-med hover:bg-bg-card-hi'
              }`}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-2 text-[15px] font-medium text-text-hi">
                  {p.id === selected && <Check size={13} strokeWidth={2.5} className="text-accent" />}
                  {p.label}
                </span>
                <span className={`font-mono text-[12px] uppercase ${fitTone(p.fit)}`}>{p.fit}</span>
              </span>

              <span className="grid grid-cols-2 gap-x-5 gap-y-1 text-[12px]">
                <Row k="Avg load" v={`${(p.avg_util * 100).toFixed(0)}%`} />
                <Row k="Demand" v={`${(p.demand_avg_w / 1000).toFixed(2)} kW`} />
                <Row
                  k="Power margin"
                  v={`${p.power_margin_pct >= 0 ? '+' : ''}${p.power_margin_pct}%`}
                  tone={p.power_margin_pct >= 10 ? 'text-ok' : p.power_margin_pct >= 0 ? 'text-warn' : 'text-err'}
                />
                <Row
                  k="Thermal margin"
                  v={`${p.thermal_margin_pct >= 0 ? '+' : ''}${p.thermal_margin_pct}%`}
                  tone={p.thermal_margin_pct >= 0 ? 'text-ok' : 'text-err'}
                />
                <Row k="Per cycle" v={`${fmt(p.outputs_per_cycle.tokens)} tok`} />
                <Row k="Energy" v={`${p.outputs_per_cycle.payload_kwh.toFixed(2)} kWh`} />
              </span>

              <span className="mt-auto truncate text-[11px] text-text-faint">{p.jobs.join(' · ')}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ k, v, tone }: { k: string; v: string; tone?: string }) {
  return (
    <span className="flex items-baseline justify-between gap-2">
      <span className="uppercase tracking-[0.08em] text-text-lo">{k}</span>
      <span className={`font-mono text-[13px] tabular-nums ${tone ?? 'text-text-hi'}`}>{v}</span>
    </span>
  )
}
