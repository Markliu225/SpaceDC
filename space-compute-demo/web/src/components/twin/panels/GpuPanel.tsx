import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { gpuOption, GPU_CARDS_PER_SAT } from '../../../data/satConfigOptions'

/** Sub-panel for one of the GPU modules. Shows the active GPU type's
 * static spec (per-card + per-sat aggregate) plus the LIVE typed workload
 * from the physics engine: which job/model the cards are running, achieved
 * MFU and effective TFLOPS, model-level throughput (tokens/s or frames/s),
 * and the per-card electrical/heat load. */
export function GpuPanel({ cardIdx }: { cardIdx: number }) {
  const sat = useDemoStore((s) => s.lastState?.satellite)
  const cfg = useTelemetryStore((s) => s.satConfig)
  const gpu = gpuOption(cfg.gpu)

  const cards = sat?.gpu_count ?? GPU_CARDS_PER_SAT
  const perSatPflops = gpu.pflops_per_card * cards
  const perSatTdpKw  = (gpu.tdp_w * cards) / 1000

  const util = sat?.gpu_utilization
  const die  = sat?.temperature_c
  const wd   = sat?.workload_detail

  const fmtThroughput = (v: number) =>
    v >= 10_000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)

  return (
    <>
      <Section title={`Module · ${String(cardIdx).padStart(2, '0')}`}>
        <Row label="Model"    value={gpu.label} />
        <Row label="Cards"    value={cards.toString()} unit="×" />
      </Section>
      <Section title={`Aggregate (${cards}×)`}>
        <Row label="Compute"  value={perSatPflops.toFixed(2)} unit="PF" />
        <Row label="TDP"      value={perSatTdpKw.toFixed(1)}  unit="kW" />
      </Section>
      <Section title="Running now">
        <Row label="Job"   value={wd?.job_label ?? '— —'} />
        <Row label="Model" value={wd?.model ?? '— —'} />
        <Row
          label="Precision"
          value={wd?.precision && wd.precision !== '-' ? wd.precision : '— —'}
        />
        <Row
          label="MFU"
          value={wd != null ? (wd.mfu * 100).toFixed(0) : '— —'}
          unit="%"
        />
        <Row
          label="Effective"
          value={wd != null ? wd.tflops_per_gpu.toFixed(0) : '— —'}
          unit="TF/GPU"
        />
        <Row
          label="Throughput"
          value={wd != null && wd.throughput_unit !== '-'
            ? fmtThroughput(wd.throughput_total) : '— —'}
          unit={wd?.throughput_unit !== '-' ? wd?.throughput_unit : undefined}
        />
      </Section>
      <Section title="Live card">
        <Row
          label="Util"
          value={util != null ? Math.round(Math.max(0, Math.min(1, util)) * 100).toString() : '— —'}
          unit="%"
          tone={util != null && util > 0.8 ? 'hot' : undefined}
        />
        <Row
          label="Power"
          value={wd != null ? Math.round(wd.power_w_per_gpu).toString() : '— —'}
          unit="W"
        />
        <Row
          label="Heat out"
          value={wd != null ? Math.round(wd.heat_w_per_gpu).toString() : '— —'}
          unit="W"
        />
        <Row label="Die" value={die != null ? die.toFixed(1) : '— —'} unit="°C" />
      </Section>
    </>
  )
}
