import { useDemoStore } from '../../store/demoStore'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import {
  gpuOption, GPU_CARDS_PER_SAT, deriveStats,
} from '../../data/satConfigOptions'

/**
 * DesignSummary — replaces the prior cryptic "Δ vs baseline / Thermal Load
 * Ratio W/ε·m²" block. Three traffic-light rows answer the questions the
 * user actually has when sliding the Configurator dropdowns:
 *
 *   "Does my panel choice produce more power than my GPUs draw?"   → Power
 *   "Can my radiator surface shed the GPU heat at full throttle?"  → Thermal
 *   "If I lost the sun right now, how long would I last?"          → Battery
 *
 * Status colour is decided from the real backend numbers (solar_supply_avg_w
 * vs solar_demand_avg_w, thermal_max_emit_w vs thermal_peak_demand_w, and
 * battery_capacity_wh / peak payload draw) so the dots can't drift from the
 * alarm logic. Below the lights, three plain-text specs (Compute / CAPEX /
 * Dry mass) replace the directional arrows.
 */

type Tone = 'ok' | 'warn' | 'alert'

const TONE_DOT: Record<Tone, string> = {
  ok:    'bg-ok',
  warn:  'bg-warn',
  alert: 'bg-warn',
}

const TONE_TEXT: Record<Tone, string> = {
  ok:    'text-ok',
  warn:  'text-warn',
  alert: 'text-warn',
}

const TONE_LABEL: Record<Tone, string> = {
  ok:    'OK',
  warn:  'TIGHT',
  alert: 'ALERT',
}

function powerTone(margin_w: number): Tone {
  if (margin_w >= 500)   return 'ok'
  if (margin_w >= -200)  return 'warn'
  return 'alert'
}

function thermalTone(margin_w: number): Tone {
  if (margin_w >= 500)  return 'ok'
  if (margin_w >= 0)    return 'warn'
  return 'alert'
}

function batteryTone(minutes: number): Tone {
  if (minutes >= 30) return 'ok'
  if (minutes >= 10) return 'warn'
  return 'alert'
}

export function DesignSummary() {
  const sat = useDemoStore((s) => s.lastState?.satellite)
  const cfg = useTelemetryStore((s) => s.satConfig)
  const gpu = gpuOption(cfg.gpu)
  const stats = deriveStats(cfg)

  // Power balance (W) — supply minus demand on average.
  const solarSupply = sat?.solar_supply_avg_w ?? 0
  const solarDemand = sat?.solar_demand_avg_w ?? 0
  const powerMargin = solarSupply - solarDemand

  // Thermal headroom (W) — emit cap minus peak demand at the +60 °C ceiling.
  const thermMax    = sat?.thermal_max_emit_w ?? 0
  const thermDemand = sat?.thermal_peak_demand_w ?? 0
  const thermMargin = thermMax - thermDemand

  // Eclipse autonomy (min) — battery Wh ÷ peak payload draw.
  const cap_wh   = sat?.battery_capacity_wh ?? 1500
  // Peak payload: TDP × 8 + 600 W platform (real-world peak under workload=1).
  const peakLoad = gpu.tdp_w * GPU_CARDS_PER_SAT + 600
  const autonomy_min = (cap_wh / Math.max(1, peakLoad)) * 60
  // Scale by the actual SOC so we're showing the remaining runtime, not the
  // theoretical maximum from a full pack.
  const soc = sat?.battery_soc ?? 0.9
  const eff_min = autonomy_min * soc

  const rows: Array<{ label: string; tone: Tone; value: string }> = [
    { label: 'Power',   tone: powerTone(powerMargin),
      value: `${powerMargin >= 0 ? '+' : ''}${Math.round(powerMargin)} W` },
    { label: 'Thermal', tone: thermalTone(thermMargin),
      value: `${thermMargin >= 0 ? '+' : ''}${Math.round(thermMargin)} W` },
    { label: 'Battery', tone: batteryTone(eff_min),
      value: `${eff_min.toFixed(0)} min` },
  ]

  return (
    <div className="mt-3 border-t border-border-weak pt-2">
      <div className="mb-1.5 text-[10px] uppercase tracking-[0.10em] text-text-lo">
        Design summary
      </div>

      {/* Traffic lights — three single-line rows. */}
      <div className="flex flex-col gap-1">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between text-[12px]">
            <div className="flex items-center gap-2 text-text-md">
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${TONE_DOT[r.tone]}`} />
              <span>{r.label}</span>
              <span className={`text-[9.5px] uppercase tracking-[0.12em] ${TONE_TEXT[r.tone]}`}>
                {TONE_LABEL[r.tone]}
              </span>
            </div>
            <span className="font-mono tabular-nums text-text-hi">{r.value}</span>
          </div>
        ))}
      </div>

      {/* Specs — plain text, no Δ arrows. */}
      <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-text-md">
        <Spec label="Compute" value={`${stats.compute_pflops.toFixed(1)} PF`} />
        <Spec label="CAPEX"   value={`$${stats.capex_usd_m.toFixed(2)} M`} />
        <Spec label="Mass"    value={`${Math.round(stats.launch_mass_kg)} kg`} />
      </div>
    </div>
  )
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col leading-tight">
      <span className="text-[9.5px] uppercase tracking-[0.12em] text-text-lo">{label}</span>
      <span className="font-mono tabular-nums text-text-hi">{value}</span>
    </div>
  )
}
