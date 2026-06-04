import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { gpuOption, GPU_CARDS_PER_SAT } from '../../../data/satConfigOptions'

/** Sub-panel for one of the GPU modules. Shows the active GPU type's
 * static spec (per-card + per-sat aggregate) plus live utilization, die
 * temperature, and the current task phase from the backend state — the
 * three rows that make this richer than the Mission-page GpuInfoPopup. */
export function GpuPanel({ cardIdx }: { cardIdx: number }) {
  const sat = useDemoStore((s) => s.lastState?.satellite)
  const task = useDemoStore((s) => s.lastState?.task)
  const cfg = useTelemetryStore((s) => s.satConfig)
  const gpu = gpuOption(cfg.gpu)

  const perSatPflops = gpu.pflops_per_card * GPU_CARDS_PER_SAT
  const perSatTdpKw  = (gpu.tdp_w * GPU_CARDS_PER_SAT) / 1000

  const util = sat?.gpu_utilization
  const workload = sat?.workload
  const payloadW = sat?.payload_power_w
  const liveTotalKw = payloadW != null ? payloadW / 1000 : undefined
  const liveCardW   = payloadW != null ? payloadW / GPU_CARDS_PER_SAT : undefined
  const die  = sat?.temperature_c
  const jobPhase = (() => {
    const phase = sat?.task_state ?? 'idle'
    const type = task?.type
    return type ? `${type} · ${phase}` : phase
  })()

  return (
    <>
      <Section title={`Module · ${String(cardIdx).padStart(2, '0')}`}>
        <Row label="Model"    value={gpu.label} />
        <Row label="Cards"    value={GPU_CARDS_PER_SAT.toString()} unit="×" />
      </Section>
      <Section title="Aggregate (8×)">
        <Row label="Compute"  value={perSatPflops.toFixed(2)} unit="PF" />
        <Row label="TDP"      value={perSatTdpKw.toFixed(1)}  unit="kW" />
      </Section>
      <Section title="Live">
        <Row
          label="Workload"
          value={workload != null ? Math.round(Math.max(0, Math.min(1, workload)) * 100).toString() : '— —'}
          unit="%"
          tone={workload != null && workload > 0.8 ? 'hot' : undefined}
        />
        <Row
          label="Util"
          value={util != null ? Math.round(Math.max(0, Math.min(1, util)) * 100).toString() : '— —'}
          unit="%"
        />
        <Row
          label="Per card"
          value={liveCardW != null ? Math.round(liveCardW).toString() : '— —'}
          unit="W"
        />
        <Row
          label="Total"
          value={liveTotalKw != null ? liveTotalKw.toFixed(2) : '— —'}
          unit="kW"
        />
        <Row label="Die"   value={die != null ? die.toFixed(1) : '— —'} unit="°C" />
        <Row label="Job"   value={jobPhase} />
      </Section>
    </>
  )
}
