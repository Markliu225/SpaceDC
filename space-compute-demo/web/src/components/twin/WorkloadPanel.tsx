import { useEffect } from 'react'
import { useDemoStore } from '../../store/demoStore'
import { useWorkloadProfiles } from '../../hooks/useWorkloadProfiles'
import { ConfigDropdown } from './ConfigDropdown'

/**
 * WorkloadPanel — pick WHAT the satellite computes and watch the
 * consequences live. The dropdown lists every job schedule annotated with
 * how the CURRENT design copes (average demand vs solar supply → fit
 * verdict); below it, the live typed-job readout: model + precision,
 * achieved MFU / effective TFLOPS, throughput, electrical draw and per-card
 * heat, and the cumulative output (tokens / frames / kWh) since the switch.
 *
 * LLM jobs resolve through the analytical performance/power/thermal engine
 * (backend llm_perf.py): an extra strip shows the operating point — phase,
 * decode batch, SM frequency the DVFS governor settled at, GPU die temp —
 * and turns amber/red when the thermal limit throttles the cards.
 */
export function WorkloadPanel() {
  const { profiles, active, applying, refresh, applyProfile } = useWorkloadProfiles()
  const sat = useDemoStore((s) => s.lastState?.satellite)
  // Adaptation numbers depend on the live loadout — refetch whenever the
  // design/config/geometry generation changes (cheap, and design switches
  // are user-paced).
  const designId = useDemoStore((s) => s.lastState?.design_id)
  const geomVersion = useDemoStore((s) => s.lastState?.twin_geometry?.version)
  useEffect(() => { void refresh() }, [refresh, designId, geomVersion])

  const wd = sat?.workload_detail
  const totals = sat?.workload_totals
  const current = profiles.find((p) => p.id === active)

  const fitTone = (fit: string) =>
    fit === 'ok' ? 'text-ok' : fit === 'tight' ? 'text-warn' : 'text-err'
  const fmt = (v: number) =>
    v >= 1e9 ? `${(v / 1e9).toFixed(2)}B`
    : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
    : v >= 1e3 ? `${(v / 1e3).toFixed(1)}k`
    : String(Math.round(v))

  return (
    <div className="flex flex-col gap-1.5">
      {profiles.length > 0 ? (
        <ConfigDropdown
          label="Job schedule"
          value={active}
          options={profiles.map((p) => ({
            id: p.id,
            label: p.label,
            meta: `avg ${(p.avg_util * 100).toFixed(0)}% · ${(p.demand_avg_w / 1000).toFixed(1)} kW · `
              + (p.power_margin_pct >= 0 ? `+${p.power_margin_pct}%` : `${p.power_margin_pct}%`),
          }))}
          onChange={(v) => { if (!applying) void applyProfile(v) }}
        />
      ) : (
        <div className="rounded border border-border-weak bg-bg-inset/40 px-2 py-1 text-[10px] text-text-lo">
          Job schedule — loading profiles…
        </div>
      )}

      {/* Fit verdict for the active schedule on the current design. */}
      {current && (
        <div className="flex items-center justify-between rounded border border-border-weak bg-bg-inset/40 px-2 py-1 text-[10px]">
          <span className="uppercase tracking-[0.08em] text-text-lo">Design fit</span>
          <span className={`font-mono uppercase ${fitTone(current.fit)}`}>
            {current.fit} · pwr {current.power_margin_pct >= 0 ? '+' : ''}{current.power_margin_pct}%
            {' · '}thm {current.thermal_margin_pct >= 0 ? '+' : ''}{current.thermal_margin_pct}%
          </span>
        </div>
      )}

      {/* Live typed-job readout. */}
      <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 rounded border border-border-weak bg-bg-inset/40 px-2 py-1.5 text-[10px]">
        <Row k="Running" v={wd?.job_label ?? '— —'} wide />
        <Row k="Model" v={wd && wd.model !== '-'
          ? `${wd.model}${wd.precision !== '-' ? ` ${wd.precision}` : ''}` : '— —'} wide />
        <Row k="MFU" v={wd ? `${(wd.mfu * 100).toFixed(0)}%` : '— —'} />
        <Row k="Effective" v={wd ? `${wd.tflops_per_gpu.toFixed(0)} TF/GPU` : '— —'} />
        <Row k="Rate" v={wd && wd.throughput_unit !== '-'
          ? `${fmt(wd.throughput_total)} ${wd.throughput_unit}` : '— —'} />
        <Row k="Draw" v={sat ? `${((sat.payload_power_w + sat.platform_power_w) / 1000).toFixed(2)} kW` : '— —'} />
        <Row k="Heat/GPU" v={wd ? `${Math.round(wd.heat_w_per_gpu)} W` : '— —'} />
        <Row k="Radiated" v={sat?.radiator_power_w != null ? `${(sat.radiator_power_w / 1000).toFixed(2)} kW` : '— —'} />
      </div>

      {/* Analytical operating point — LLM jobs only (llm_perf engine). */}
      {wd?.engine === 'analytic' && (
        <div
          data-testid="llm-operating-point"
          className={`flex items-center justify-between rounded border px-2 py-1 text-[10px] ${
            wd.thermal_runaway ? 'border-err/60 bg-err/10'
            : wd.thermal_throttled ? 'border-warn/60 bg-warn/10'
            : 'border-border-weak bg-bg-inset/40'
          }`}
        >
          <span className="uppercase tracking-[0.08em] text-text-lo">
            {wd.exec_phase}{wd.exec_phase === 'decode' && wd.batch ? ` B${wd.batch}` : ''}
          </span>
          <span className="font-mono tabular-nums text-text-hi">
            SM {Math.round((wd.freq_frac ?? 0) * 100)}%
            {' · '}die {wd.gpu_die_temp_c?.toFixed(0)}°C
            {wd.thermal_runaway ? (
              <span className="ml-1.5 font-sans uppercase text-err">runaway</span>
            ) : wd.thermal_throttled ? (
              <span className="ml-1.5 font-sans uppercase text-warn">throttled</span>
            ) : null}
          </span>
        </div>
      )}

      {/* Cumulative output since the schedule was applied. */}
      {totals && (
        <div className="flex items-center justify-between rounded border border-border-weak bg-bg-inset/40 px-2 py-1 text-[10px]">
          <span className="uppercase tracking-[0.08em] text-text-lo">
            Output · {Math.round(totals.duration_s)}s
          </span>
          <span className="font-mono tabular-nums text-text-hi">
            {fmt(totals.tokens)} tok · {fmt(totals.frames)} img · {totals.payload_kwh.toFixed(2)} kWh
          </span>
        </div>
      )}
    </div>
  )
}

function Row({ k, v, wide = false }: { k: string; v: string; wide?: boolean }) {
  return (
    <span className={`flex items-baseline justify-between gap-1.5 ${wide ? 'col-span-2' : ''}`}>
      <span className="uppercase tracking-[0.08em] text-text-lo">{k}</span>
      <span className="truncate text-right font-mono tabular-nums text-text-hi">{v}</span>
    </span>
  )
}
