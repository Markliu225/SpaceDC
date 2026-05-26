import { Cpu, RadioTower, Snowflake, Zap, type LucideIcon } from 'lucide-react'
import { Card, Dot, Num } from '../primitives'
import { colors } from '../../design/tokens'
import { useSatConfig } from '../../hooks/useSatConfig'
import { useTwinTelemetry, type TwinTelemetrySnapshot } from '../../hooks/useTwinTelemetry'
import type { SatelliteConfig } from '../../types/messages'

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

  const cards: SubCard[] = [
    powerCard(cfg, tel),
    thermalCard(cfg, tel),
    computeCard(cfg, tel),
    commsCard(cfg, tel),
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

function powerCard(_cfg: SatelliteConfig, tel: TwinTelemetrySnapshot['current']): SubCard {
  const platform = 600
  const margin = tel.solar_w - tel.payload_w - platform
  const health: Health = margin >= 0 ? 'nominal' : margin > -300 ? 'warn' : 'fault'
  const hint =
    health === 'nominal' ? 'Surplus power — battery charging' :
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

function computeCard(cfg: SatelliteConfig, tel: TwinTelemetrySnapshot['current']): SubCard {
  const health: Health = tel.payload_w > 0 ? 'nominal' : 'warn'
  return {
    title: 'Compute',
    icon: Cpu,
    health,
    hint: health === 'nominal'
      ? `${cfg.gpu} × 8 cards running inference`
      : 'Payload offline — power or thermal cut',
    metrics: [
      { label: 'GPU',     value: cfg.gpu },
      { label: 'Payload', value: tel.payload_w, digits: 0, unit: 'W' },
    ],
  }
}

function commsCard(_cfg: SatelliteConfig, tel: TwinTelemetrySnapshot['current']): SubCard {
  // Demo placeholder — comms not yet parameterised.
  const downlink_mbps = tel.payload_w > 100 ? 120 : 0
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
