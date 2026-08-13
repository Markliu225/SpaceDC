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
    <div className="flex flex-col gap-3">
      <p className="flex items-center gap-2 text-[11px] leading-relaxed text-text-lo">
        Pick the job schedule the GPUs will run. Fit is computed against the satellite you
        just built — average demand vs solar supply, and peak heat vs the radiator ceiling.
        {loading && <Loader2 size={12} className="animate-spin text-accent" />}
      </p>

      {profiles.length === 0 ? (
        <div className="rounded border border-border-weak bg-bg-inset/40 px-3 py-6 text-center text-[11px] text-text-lo">
          {loading ? 'Evaluating schedules against this design…'
                   : 'No schedules available — backend offline.'}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {profiles.map((p) => (
            <button
              key={p.id}
              type="button"
              data-testid={`build-workload-${p.id}`}
              onClick={() => onPick(p.id)}
              aria-pressed={p.id === selected}
              className={`flex flex-col gap-1.5 rounded-md border p-2.5 text-left transition-colors ${
                p.id === selected
                  ? 'border-accent bg-bg-card-hi'
                  : 'border-border-weak bg-bg-inset/40 hover:border-border-glow hover:bg-bg-card-hi'
              }`}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-1.5 text-[12px] font-medium text-text-hi">
                  {p.id === selected && <Check size={11} strokeWidth={2.5} className="text-accent" />}
                  {p.label}
                </span>
                <span className={`font-mono text-[10px] uppercase ${fitTone(p.fit)}`}>{p.fit}</span>
              </span>

              <span className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px]">
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

              <span className="truncate text-[9px] text-text-faint">{p.jobs.join(' · ')}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ k, v, tone }: { k: string; v: string; tone?: string }) {
  return (
    <span className="flex items-baseline justify-between gap-1.5">
      <span className="uppercase tracking-[0.08em] text-text-lo">{k}</span>
      <span className={`font-mono tabular-nums ${tone ?? 'text-text-hi'}`}>{v}</span>
    </span>
  )
}
