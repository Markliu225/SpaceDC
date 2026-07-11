import { Cpu, RadioTower, Snowflake, Zap, type LucideIcon } from 'lucide-react'
import { Card, Dot, Num } from '../primitives'
import { colors } from '../../design/tokens'
import { useDemoStore } from '../../store/demoStore'
import { useSatConfig } from '../../hooks/useSatConfig'
import { useTwinTelemetry, type TwinTelemetrySnapshot } from '../../hooks/useTwinTelemetry'
import type { SatelliteConfig, SatelliteState } from '../../types/messages'

type Health = 'nominal' | 'warn' | 'fault'

const HEALTH_COLOR: Record<Health, string> = {
  nominal: colors.ok,
  warn:    colors.warn,
  fault:   colors.err,
}

const HEALTH_LABEL: Record<Health, string> = {
  nominal: 'Nominal',
  warn:    'Warn',
  fault:   'Fault',
}

interface CardMetric {
  label: string
  value: number | string
  digits?: number
  unit?: string
}

interface SubCard {
  title: string
  icon: LucideIcon
  health: Health
  hint: string
  metrics: CardMetric[]
}

/**
 * SubsystemHealthRow — 4 status cards (Power · Thermal · Compute · Comms).
 * Each card shows a colored status dot + label, 2 key metrics, and a
 * 1-line root-cause hint. Status derives from current telemetry + the
 * applied SatelliteConfig — recomputes every tick.
 */
export function SubsystemHealthRow() {
  const { cfg } = useSatConfig()
  const tel = useTwinTelemetry().current
  // Authoritative physics fields not carried by the telemetry ring buffer
  // (battery net power, platform power, real downlink). Null when offline —
  // each card falls back to its local approximation then.
  const sat = useDemoStore((s) => s.lastState?.satellite)

  const cards: SubCard[] = [
    powerCard(cfg, tel, sat),
    thermalCard(cfg, tel),
    computeCard(cfg, tel, sat),
    commsCard(cfg, tel, sat),
  ]

  return (
    <div className="grid h-full grid-cols-4 gap-2.5 min-h-0">
      {cards.map((c) => <SubsystemCard key={c.title} card={c} />)}
    </div>
  )
}

function SubsystemCard({ card }: { card: SubCard }) {
  const Icon = card.icon
  return (
    <Card dense className="h-full flex flex-col min-h-0">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Icon size={14} strokeWidth={1.8} className="text-accent" />
          <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
            {card.title}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Dot color={HEALTH_COLOR[card.health]} size={7} glow={5} />
          <span className="text-[10px] uppercase tracking-[0.10em] text-text-md">
            {HEALTH_LABEL[card.health]}
          </span>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5">
        {card.metrics.map((m) => (
          <span key={m.label} className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
            <span className="text-[10px] uppercase tracking-[0.08em] text-text-lo">{m.label}</span>
            {typeof m.value === 'number' ? (
              <Num value={m.value} digits={m.digits ?? 0} className="text-[13px] text-text-hi" />
            ) : (
              <span className="text-[13px] text-text-hi">{m.value}</span>
            )}
            {m.unit && <span className="text-[10px] text-text-lo">{m.unit}</span>}
          </span>
        ))}
      </div>
      <div className="mt-auto pt-1 text-[10px] text-text-lo">
        {card.hint}
      </div>
    </Card>
  )
}

function powerCard(
  _cfg: SatelliteConfig,
  tel: TwinTelemetrySnapshot['current'],
  sat: SatelliteState | undefined,
): SubCard {
  // Margin = the engine's own battery net power (solar − payload − platform);
  // the local reconstruction (with its hard-coded 600 W platform) is only
  // the offline fallback.
  const margin = sat?.battery_charge_w
    ?? (tel.solar_w - tel.payload_w - 600)
  // In eclipse every design draws from the battery by construction — that is
  // nominal night operation, not a fault, as long as the pack holds charge.
  const inEclipse = !(sat?.sunlit ?? tel.sunlit)
  const soc = sat?.battery_soc ?? tel.battery_soc
  const health: Health =
    margin >= 0 ? 'nominal'
    : inEclipse ? (soc > 0.25 ? 'nominal' : soc > 0.15 ? 'warn' : 'fault')
    : margin > -300 ? 'warn' : 'fault'
  const hint =
    margin >= 0          ? 'Surplus power — battery charging' :
    inEclipse            ? (health === 'nominal'
                              ? 'Eclipse — riding the battery as designed'
                              : 'Eclipse deficit — battery running low') :
    health === 'warn'    ? 'Insufficient solar — drawing from battery' :
                           'Significant deficit — SOC will drop'
  return {
    title: 'Power',
    icon: Zap,
    health,
    hint,
    metrics: [
      { label: 'Solar',   value: tel.solar_w,   digits: 0, unit: 'W' },
      { label: 'Margin',  value: margin,        digits: 0, unit: 'W' },
    ],
  }
}

function thermalCard(_cfg: SatelliteConfig, tel: TwinTelemetrySnapshot['current']): SubCard {
  const health: Health = tel.temp_c < 70 ? 'nominal' : tel.temp_c < 85 ? 'warn' : 'fault'
  const hint =
    health === 'nominal' ? 'Within radiator dissipation envelope' :
    health === 'warn'    ? 'Approaching GPU thermal limit' :
                           'Radiator undersized for payload load'
  return {
    title: 'Thermal',
    icon: Snowflake,
    health,
    hint,
    metrics: [
      { label: 'Temp',  value: tel.temp_c,  digits: 1, unit: '°C' },
      { label: 'Util',  value: tel.gpu_util * 100, digits: 0, unit: '%' },
    ],
  }
}

function computeCard(
  cfg: SatelliteConfig,
  tel: TwinTelemetrySnapshot['current'],
  sat: SatelliteState | undefined,
): SubCard {
  const health: Health = tel.payload_w > 0 ? 'nominal' : 'warn'
  const wd = sat?.workload_detail
  const cards = sat?.gpu_count ?? 8
  // "Llama-3.3-70B FP8 · LLM pretraining" — the typed job the engine is
  // actually simulating; falls back to the generic line offline.
  const hint =
    health !== 'nominal' ? 'Payload offline — power or thermal cut'
    : wd && wd.model !== '-' ? [wd.model, wd.precision !== '-' ? wd.precision : '']
        .filter(Boolean).join(' ') + ` · ${wd.job_label}`
    : wd ? wd.job_label
    : `${cfg.gpu} × ${cards} cards running inference`
  const throughput: CardMetric =
    wd && wd.throughput_unit !== '-'
      ? {
          label: 'Rate',
          value: wd.throughput_total >= 10_000
            ? `${(wd.throughput_total / 1000).toFixed(1)}k`
            : String(Math.round(wd.throughput_total)),
          unit: wd.throughput_unit,
        }
      : { label: 'Payload', value: tel.payload_w, digits: 0, unit: 'W' }
  return {
    title: 'Compute',
    icon: Cpu,
    health,
    hint,
    metrics: [
      { label: 'GPU', value: `${cfg.gpu} ×${cards}` },
      throughput,
    ],
  }
}

function commsCard(
  _cfg: SatelliteConfig,
  tel: TwinTelemetrySnapshot['current'],
  sat: SatelliteState | undefined,
): SubCard {
  // Real backend downlink (ground-station visibility windows); the payload
  // heuristic is only the offline fallback.
  const downlink_mbps = sat?.downlink_mbps ?? (tel.payload_w > 100 ? 120 : 0)
  const health: Health = downlink_mbps > 0 ? 'nominal' : 'warn'
  return {
    title: 'Comms',
    icon: RadioTower,
    health,
    hint: downlink_mbps > 0
      ? 'Downlink window open · K-band'
      : 'No ground station in view',
    metrics: [
      { label: 'Downlink', value: downlink_mbps, digits: 0, unit: 'Mbps' },
      { label: 'GS Vis',   value: downlink_mbps > 0 ? 'YES' : 'NO' },
    ],
  }
}
