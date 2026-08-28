import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { gpuOption, slotGroups, GPU_CARDS_PER_SAT } from '../../../data/satConfigOptions'

/** Sub-panel for one of the GPU modules. Shows the active GPU type's
 * static spec (per-card + per-sat aggregate) plus the LIVE typed workload
 * from the physics engine: which job/model the cards are running, achieved
 * MFU and effective TFLOPS, model-level throughput (tokens/s or frames/s),
 * and the per-card electrical/heat load. LLM jobs run the analytical
 * llm_perf engine — the card then also reports its true operating point:
 * execution phase, DVFS frequency, junction temperature and throttle
 * state (structure temp is the cold plate; die = struct + P·R_th). */
export function GpuPanel({ cardIdx }: { cardIdx: number }) {
  const sat = useDemoStore((s) => s.lastState?.satellite)
  const cfg = useTelemetryStore((s) => s.satConfig)
  // With a per-slot loadout (satellite builder) THIS slot's card is what the
  // viewer clicked — reporting the satellite's primary model would describe a
  // different blade. Falls back to the uniform loadout when no bay was built.
  const slots = cfg.gpu_slots ?? []
  const slotGpu = slots.length ? slots[cardIdx - 1] ?? null : null
  const gpu = gpuOption(slotGpu ?? cfg.gpu)

  const cards = sat?.gpu_count ?? GPU_CARDS_PER_SAT
  const groups = slots.length ? slotGroups(slots) : []
  const mixed = groups.length > 1
  const perSatPflops = mixed
    ? groups.reduce((p, g) => p + gpuOption(g.gpu).pflops_per_card * g.count, 0)
    : gpu.pflops_per_card * cards
  const perSatTdpKw = (mixed
    ? groups.reduce((w, g) => w + gpuOption(g.gpu).tdp_w * g.count, 0)
    : gpu.tdp_w * cards) / 1000

  const util = sat?.gpu_utilization
  const wdSat = sat?.workload_detail
  // A mixed bay's satellite-level detail is a card-weighted merge; this card
  // belongs to exactly one group, so show that group's operating point.
  const wdGroup = slotGpu
    ? wdSat?.mix?.find((m) => m.gpu === slotGpu)
    : undefined
  // Thermal state comes from THIS group too. The satellite-level detail is a
  // merge — its die temp is the HOTTEST group's and its throttle flag is
  // `any(...)` — so reading it here made every slot light up the moment the
  // first card type hit its ceiling, hiding exactly the staggered onset the
  // mixed bay is supposed to show.
  const wd = wdSat && wdGroup
    ? { ...wdSat,
        power_w_per_gpu: wdGroup.power_w_per_gpu,
        heat_w_per_gpu: wdGroup.heat_w_per_gpu,
        tflops_per_gpu: wdGroup.tflops_per_gpu,
        throughput_total: wdGroup.throughput_total,
        gpu_die_temp_c: wdGroup.gpu_die_temp_c,
        freq_frac: wdGroup.freq_frac,
        thermal_throttled: wdGroup.thermal_throttled,
        thermal_runaway: wdGroup.thermal_runaway }
    : wdSat
  const analytic = wd?.engine === 'analytic'
  // Junction temp exists only on the analytic path (die = struct + P·R_th);
  // the MFU path knows just the structure temp (the card's cold plate) —
  // label it as such rather than passing it off as a die reading.
  const temp = analytic ? wd?.gpu_die_temp_c : sat?.temperature_c
  const tempLabel = analytic ? 'Die' : 'Cold plate'
  const tempHot = analytic
    ? (wd!.thermal_throttled || wd!.thermal_runaway)
    : (sat?.temperature_c ?? 0) > 70 // backend overtemp line

  const fmtThroughput = (v: number) =>
    v >= 10_000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)

  return (
    <>
      <Section title={`Module · ${String(cardIdx).padStart(2, '0')}`}>
        <Row label="Model"    value={slots.length && !slotGpu ? 'Empty slot' : gpu.label} />
        <Row label="Cards"    value={cards.toString()} unit="×" />
      </Section>
      <Section title={`Aggregate (${cards}×)`}>
        {mixed && (
          <Row label="Loadout"
               value={groups.map((g) => `${g.count}×${g.gpu}`).join(' + ')} />
        )}
        <Row label="Compute"  value={perSatPflops.toFixed(2)} unit="PF" />
        <Row label="TDP"      value={perSatTdpKw.toFixed(1)}  unit="kW" />
      </Section>
      <Section title="Running now">
        {/* The number that makes the ordering explicit: this card type's own
            throttle threshold on the current job. In a mixed bay the values
            differ, so the reader can see WHICH card gives out first and by
            how much margin — not just that "something" is throttling. */}
        {wdGroup && wdGroup.throttle_onset_c > 0 && (
          <Row label="Throttles at"
               value={wdGroup.throttle_onset_c.toFixed(1)}
               unit="°C plate"
               tone={(sat?.temperature_c ?? 0) >= wdGroup.throttle_onset_c
                 ? 'hot' : undefined} />
        )}
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
        {analytic && (
          <Row
            label="Phase"
            value={`${wd!.exec_phase}${wd!.exec_phase === 'decode' && wd!.batch
              ? ` · B=${wd!.batch} · ctx ${wd!.context}` : ''}`}
          />
        )}
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
        {analytic && (
          <Row
            label="SM clock"
            value={Math.round((wd!.freq_frac ?? 0) * 100).toString()}
            unit="% fmax"
          />
        )}
        <Row
          label={tempLabel}
          value={temp != null ? temp.toFixed(1) : '— —'}
          unit="°C"
          tone={tempHot ? 'hot' : undefined}
        />
        {analytic && (
          <Row
            label="Thermal"
            value={wd!.thermal_runaway ? 'RUNAWAY'
              : wd!.thermal_throttled ? 'THROTTLED' : 'Nominal'}
            tone={wd!.thermal_runaway || wd!.thermal_throttled ? 'hot' : undefined}
          />
        )}
      </Section>
    </>
  )
}
