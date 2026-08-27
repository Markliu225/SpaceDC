import { useEffect, useMemo, useState } from 'react'
import { Loader2, Play } from 'lucide-react'
import { Card } from '../primitives'
import { RealCoverageMap } from './RealCoverageMap'
import {
  CoverageCharts, SolarHistogram, EnergyHarvestChart,
  SolarBinControl, GroundStationControls,
} from './GroundAnalytics'
import {
  useOrbitDesign, useCoverageHistory, useEnergyHistory,
  DESIGN_DEFAULTS, GROUND_CONFIG_DEFAULTS,
  isoToLocalInput, windowSeconds, normalizeDraft, draftTimeIssue,
  ssoInclinationDeg, julianDayOf, sunUnitApprox, sunAngles,
  raanForLtan, betaDeg, terminatorDates,
  type OrbitDesignDraft, type DesignMode, type SunAngles, type TimeFieldKey,
} from '../../hooks/useOrbitDesign'
import { useSkyFrame } from '../../hooks/useSkyFrame'
import type { PropagatorOption } from '../../types/messages'

type Tab = 'designer' | 'coverage' | 'solar'

/**
 * OrbitDesignerPanel — Overview right column. Three tabs:
 *   DESIGN   — the design flow, top to bottom: active elements → mission
 *              window → propagation model → constellation pattern →
 *              the pattern's parameters → Apply.
 *   COVERAGE — the ground-station controls (mark · elevation · band) that
 *              drive the constellation status map and the live
 *              visibility/bandwidth line charts below them.
 *   SOLAR    — whole-constellation energy harvest over time, plus the marked
 *              station's illumination histogram once there IS a marked
 *              station (the histogram has nothing to bin without one).
 *
 * The Design tab is budgeted to fit the column at 1440x900 WITHOUT an inner
 * scrollbar in every pattern mode — that is why the six classical elements
 * are a compact numeric grid rather than six slider rows. Measured worst
 * case: 526 px of content in 547 px, SSO mode with the offline banner up.
 */
export function OrbitDesignerPanel() {
  const [tab, setTab] = useState<Tab>('designer')
  const design = useOrbitDesign()
  const coverage = useCoverageHistory()
  const energy = useEnergyHistory()
  const gt = design.groundTarget

  // The solar bin belongs to the ground-station config but its control lives
  // in the Solar tab, so it is read straight off the live target and a click
  // re-posts the whole config. No local mirror: the control and the histogram
  // it drives then always move on the SAME broadcast, never one tick apart.
  const solarBin = gt?.enabled ? gt.solar_bin : GROUND_CONFIG_DEFAULTS.solar_bin
  const onSolarBin = (n: number) => {
    if (!gt?.enabled) return   // nothing to configure until the site is marked
    void design.setGroundTarget(true, {
      elevation_mask_deg: gt.elevation_mask_deg, band: gt.band, solar_bin: n,
    })
  }

  const TABS: [Tab, string][] = [
    ['designer', 'Design'], ['coverage', 'Coverage'], ['solar', 'Solar'],
  ]

  return (
    <Card className="h-full flex flex-col min-h-0">
      <div className="mb-2 flex items-center gap-1">
        {TABS.map(([k, label]) => (
          <button
            key={k}
            type="button"
            data-testid={`overview-tab-${k}`}
            onClick={() => setTab(k)}
            aria-current={tab === k ? 'true' : undefined}
            className={
              'rounded border px-2 py-1 text-[10px] uppercase tracking-[0.08em] ' +
              (tab === k
                ? 'border-accent bg-bg-card-hi text-text-hi'
                : 'border-border-weak bg-bg-inset/40 text-text-lo hover:border-border-med hover:text-text-md')
            }
          >
            {label}
          </button>
        ))}
      </div>

      {/* Designer stays MOUNTED (CSS-hidden) so in-progress draft edits
          survive a tab switch; the analytics tabs are cheap to remount. */}
      <div className={tab === 'designer' ? 'flex flex-1 min-h-0 flex-col' : 'hidden'}>
        <DesignerBody design={design} />
      </div>
      {/* COVERAGE — the controls take their natural height (they carry the
          analyze/pass block), and everything left over is split by GROWTH,
          not by a percentage basis: percentages of the FULL column meant the
          controls' height was charged twice and the map collapsed to ~90px.
          The charts take the larger share because two stacked line charts
          spend ~40px of chrome each before a pixel of data is drawn. */}
      {tab === 'coverage' && (
        <div className="flex flex-1 min-h-0 flex-col gap-2">
          <div className="shrink-0">
            <GroundStationControls design={design} />
          </div>
          <div className="min-h-0" style={{ flex: '1 1 0', minHeight: 96 }}>
            <RealCoverageMap embedded />
          </div>
          <div className="flex min-h-0 flex-col" style={{ flex: '1.35 1 0', minHeight: 132 }}>
            <CoverageCharts history={coverage} gt={gt} />
          </div>
        </div>
      )}
      {/* SOLAR — the histogram bins the MARKED station's illumination, so with
          no station there is nothing to bin: the energy harvest (whole fleet,
          no ground target needed) takes the whole tab instead of sitting under
          an empty 281px box. */}
      {tab === 'solar' && (
        <div className="flex flex-1 min-h-0 flex-col gap-2">
          {gt?.enabled ? (
            <>
              <div className="shrink-0">
                <SolarBinControl value={solarBin} onChange={onSolarBin} />
              </div>
              <div className="flex min-h-0 flex-col" style={{ flex: '1 1 0' }}>
                <SolarHistogram gt={gt} />
              </div>
              <div className="flex min-h-0 flex-col" style={{ flex: '0.85 1 0' }}>
                <EnergyHarvestChart history={energy} />
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-1 min-h-0 flex-col">
                <EnergyHarvestChart history={energy} />
              </div>
              <div className="shrink-0 text-[9px] leading-[12px] text-text-faint">
                Mark the ground station on the Coverage tab to add its
                illumination histogram.
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Design tab
// ---------------------------------------------------------------------------

/** Shown while the backend is unreachable (GET /orbit_design never landed) so
 *  the model row still renders. Mirrors the catalog in app.py. */
const PROPAGATOR_FALLBACK: PropagatorOption[] = [
  { id: 'sgp4', label: 'SGP4', implemented: true, note: 'NORAD mean elements, SGP4/SDP4 perturbations' },
  { id: 'twobody', label: 'Two-body', implemented: false, note: 'Keplerian point mass, no perturbations' },
  { id: 'j2', label: 'J2', implemented: false, note: 'Secular J2 nodal + apsidal drift' },
  { id: 'hpop', label: 'HPOP', implemented: false, note: 'Numerical integration, full force model' },
]

const PATTERNS: [DesignMode, string][] = [
  ['walker', 'Walker'], ['sso', 'SSO'], ['custom', 'Custom (TLE)'],
]

function DesignerBody({ design }: { design: ReturnType<typeof useOrbitDesign> }) {
  const { info, busy, offline, error, apply } = design
  // The broadcast sun, through the SAME hook both 3D views light the Earth
  // from — so "β says 19° off the terminator" and what the globe draws cannot
  // disagree. Live, because the packet arrives every tick.
  const { sunEci } = useSkyFrame()

  const [draft, setDraft] = useState<OrbitDesignDraft>(DESIGN_DEFAULTS)
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    if (touched || !info) return
    const clamp = (lo: number, hi: number, v: number) => Math.min(hi, Math.max(lo, v))
    const wrap360 = (v: number) => ((v % 360) + 360) % 360
    const planes = clamp(1, 36, Math.round(info.walker.planes))
    const sso = info.sso
    const layers = sso ? clamp(1, 12, Math.round(sso.layers)) : DESIGN_DEFAULTS.layers
    // `sats_per_plane` and `phasing` are one draft field but two server blocks:
    // seed them from the pattern actually in force, or an SSO apply would
    // hand the Walker draft an f that its plane count cannot carry.
    const isSso = (info.mode ?? 'walker') === 'sso' && !!sso
    const seed = isSso && sso ? sso : info.walker
    setDraft((d) => normalizeDraft({
      ...d,
      mode: info.mode ?? d.mode,
      propagator: info.propagator ?? d.propagator,
      epoch_utc: isoToLocalInput(info.epoch_utc) || d.epoch_utc,
      start_utc: isoToLocalInput(info.start_utc) || d.start_utc,
      end_utc: isoToLocalInput(info.end_utc) || d.end_utc,
      altitude_km: clamp(200, 40000, Math.round(info.elements.altitude_km)),
      eccentricity: clamp(0, 0.5, info.elements.eccentricity),
      inclination_deg: clamp(0, 180, info.elements.inclination_deg),
      raan_deg: Math.min(359.9, wrap360(info.elements.raan_deg)),
      arg_perigee_deg: Math.min(359.9, wrap360(info.elements.arg_perigee_deg)),
      mean_anomaly_deg: Math.min(359.9, wrap360(info.elements.mean_anomaly_deg)),
      planes,
      sats_per_plane: clamp(1, 60, Math.round(seed.sats_per_plane)),
      phasing: Math.max(0, Math.round(seed.phasing)),
      ...(sso ? {
        alt_min_km: clamp(250, 1600, sso.alt_min_km),
        alt_max_km: clamp(250, 1600, sso.alt_max_km),
        layers,
        ltan_hours: sso.ltan_hours === 6 ? 6 : 18,
      } : {}),
    }))
  }, [info, touched])

  // Every edit goes through normalizeDraft, so cross-field bounds hold no
  // matter WHICH field moved — switching pattern re-clamps `phasing` against
  // the new pattern's plane count exactly like changing the count itself does.
  const upd = (patch: Partial<OrbitDesignDraft>) => {
    setTouched(true)
    setDraft((d) => normalizeDraft({ ...d, ...patch }))
  }

  const el = info?.elements
  // The live fleet size comes from whichever pattern is actually in force.
  const activeSats = info
    ? (info.mode === 'sso' ? info.sso?.total_sats : info.walker.total_sats)
    : undefined
  const timeScale = info?.time_scale ?? 60
  const propagators = info?.propagators?.length ? info.propagators : PROPAGATOR_FALLBACK
  const selectedProp = propagators.find((p) => p.id === draft.propagator) ?? propagators[0]

  const span = useMemo(() => {
    const s = windowSeconds(draft.start_utc, draft.end_utc)
    if (s <= 0) return null
    return { hours: s / 3600, simMin: s / timeScale / 60 }
  }, [draft.start_utc, draft.end_utc, timeScale])

  // A cleared datetime-local is '' — POSTing that is a raw 422, so Apply is
  // gated on all three instants and the offending field is marked.
  const timeIssue = useMemo(() => draftTimeIssue(draft), [draft])
  const badTime = (k: TimeFieldKey) => timeIssue?.fields.includes(k) === true

  // Sun for the dawn–dusk preview, in this order:
  //   1. the broadcast TEME sun — but it is the sun at the CURRENT sim
  //      instant, so it only describes the design while the drafted epoch is
  //      the epoch the mission is actually propagating;
  //   2. otherwise the analytic sun at the DRAFTED epoch, which is what Apply
  //      will design against (this is how dialling the epoch to early October
  //      walks β up to 90°).
  const sun: SunAngles | null = useMemo(() => {
    const live = sunEci ? sunAngles(sunEci) : null
    if (live && isoToLocalInput(info?.epoch_utc) === draft.epoch_utc) return live
    const jd = julianDayOf(draft.epoch_utc)
    return Number.isFinite(jd) ? sunAngles(sunUnitApprox(jd)) : live
  }, [sunEci, draft.epoch_utc, info?.epoch_utc])

  const isCustom = draft.mode === 'custom'
  // The other two states the backend answers with a 422 and the SSO derived
  // line already explains. Gate Apply on them too, so no arrangement of the
  // form can produce a raw rejection.
  const paramIssue = draft.mode !== 'sso' ? null
    : draft.alt_min_km > draft.alt_max_km ? 'Alt min must be ≤ alt max'
    : ssoInclinationDeg(draft.alt_min_km) === null
      || ssoInclinationDeg(draft.alt_max_km) === null
      ? 'No sun-synchronous solution at this altitude'
      : null

  return (
    // No overflow-y-auto: the flow is budgeted to FIT this column. If a block
    // ever grows past the budget it must be traded against another block, not
    // hidden behind a scrollbar.
    <div data-testid="designer-body" className="flex flex-1 min-h-0 flex-col overflow-hidden">
      {offline && (
        <div className="mb-2 rounded border border-warn/40 bg-warn/10 px-2 py-1 text-[10px] text-warn">
          Backend offline — designs cannot be applied.
        </div>
      )}
      {error && !offline && (
        <div className="mb-2 rounded border border-err/40 bg-err/10 px-2 py-1 text-[10px] text-err">{error}</div>
      )}

      {/* ACTIVE — the live constellation, two compact lines. */}
      <div className="rounded-md border border-border-weak bg-bg-inset/30 px-2 py-1">
        <div className="flex items-baseline justify-between gap-2 text-[9px] leading-[12px]">
          <span className="truncate text-text-lo">
            <span className="uppercase tracking-[0.10em]">Active</span>
            {' · '}<span className="text-text-md">{info?.name ?? '—'}</span>
          </span>
          <span className="shrink-0 tabular text-text-lo">
            {activeSats === undefined ? '—' : `${activeSats} sats`} · {el ? el.period_min.toFixed(1) : '—'} min
            {' · '}{el ? el.altitude_km.toFixed(0) : '—'} km
          </span>
        </div>
        <div className="mt-0.5 grid grid-cols-3 gap-x-2 text-[10px] leading-[13px] tabular"
             data-testid="orbit-elements">
          <Elem k="a" v={el ? `${el.semi_major_axis_km.toFixed(0)} km` : '—'} />
          <Elem k="e" v={el ? el.eccentricity.toFixed(4) : '—'} />
          <Elem k="i" v={el ? `${el.inclination_deg.toFixed(2)}°` : '—'} />
          <Elem k="Ω" v={el ? `${el.raan_deg.toFixed(2)}°` : '—'} />
          <Elem k="ω" v={el ? `${el.arg_perigee_deg.toFixed(2)}°` : '—'} />
          <Elem k="M" v={el ? `${el.mean_anomaly_deg.toFixed(2)}°` : '—'} />
        </div>
      </div>

      {/* MISSION WINDOW */}
      <Rule label="Mission window" />
      <div className="grid grid-cols-2 gap-2">
        <TimeField label="START" value={draft.start_utc} invalid={badTime('start_utc')}
                   onChange={(v) => upd({ start_utc: v })} />
        <TimeField label="END" value={draft.end_utc} invalid={badTime('end_utc')}
                   onChange={(v) => upd({ end_utc: v })} />
      </div>
      {/* One status line for all three mission instants (Epoch lives in the
          parameter block below) — it never changes height, so an invalid
          entry cannot push the flow past its budget. */}
      <div
        className="mt-0.5 text-[9px] tabular text-text-lo"
        title={timeIssue ? undefined
          : 'The window sizes and labels the interval of interest. It is advisory: '
            + 'the sim clock is not stopped when the end is reached.'}
      >
        {timeIssue
          ? <span className="text-err">{timeIssue.message}</span>
          : span
            ? <>
                {span.hours.toFixed(1)} h · {span.simMin.toFixed(0)} min at {timeScale}×
                {' · '}<span className="text-text-faint">advisory</span>
              </>
            : null}
      </div>

      {/* PROPAGATOR */}
      <Rule label="Propagation model" />
      <div className="flex gap-1">
        {propagators.map((p) => (
          <Seg
            key={p.id}
            testId={`prop-${p.id}`}
            label={p.label}
            active={draft.propagator === p.id}
            disabled={!p.implemented}
            title={p.note}
            onClick={() => upd({ propagator: p.id })}
          />
        ))}
      </div>
      <div className="mt-0.5 truncate text-[9px] leading-[12px] text-text-lo" title={selectedProp?.note}>
        {selectedProp ? `${selectedProp.label} · ${selectedProp.note}` : '—'}
      </div>

      {/* PATTERN */}
      <Rule label="Constellation pattern" />
      <div className="flex gap-1">
        {PATTERNS.map(([m, label]) => (
          <Seg
            key={m}
            testId={`pattern-${m}`}
            label={label}
            active={draft.mode === m}
            onClick={() => upd({ mode: m })}
          />
        ))}
      </div>

      {/* PARAMETERS */}
      <Rule
        label={isCustom ? 'TLE import' : 'Parameters'}
        right={draft.mode === 'walker' ? (
          <span className="shrink-0 tabular normal-case tracking-normal text-text-md">
            total {draft.planes * draft.sats_per_plane} satellites
          </span>
        ) : undefined}
      />
      {draft.mode === 'walker' && (
        <WalkerParams draft={draft} upd={upd} badEpoch={badTime('epoch_utc')} />
      )}
      {draft.mode === 'sso' && (
        <SsoParams draft={draft} upd={upd} badEpoch={badTime('epoch_utc')} sun={sun} />
      )}
      {isCustom && (
        <div className="rounded-md border border-dashed border-border-weak bg-bg-inset/30 px-2 py-3 text-center">
          <div className="text-[11px] text-text-md">Paste or drop a TLE set</div>
          <div className="mt-1 text-[9px] text-text-faint">
            TLE import is not wired up yet — pick Walker or SSO to apply a design.
          </div>
        </div>
      )}

      <button
        type="button"
        data-testid="orbit-apply"
        onClick={() => void apply(draft)}
        disabled={busy || offline || isCustom || timeIssue !== null || paramIssue !== null}
        title={isCustom
          ? 'TLE import is not wired up yet'
          : timeIssue?.message ?? paramIssue ?? undefined}
        className="mt-2 flex items-center justify-center gap-2 rounded-md border border-accent/60 bg-accent/15
                   px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.10em] text-accent
                   hover:bg-accent/25 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} strokeWidth={2} />}
        Apply design
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
function WalkerParams({ draft, upd, badEpoch }: {
  draft: OrbitDesignDraft
  upd: (patch: Partial<OrbitDesignDraft>) => void
  badEpoch: boolean
}) {
  return (
    <>
      <TimeField label="EPOCH" value={draft.epoch_utc} invalid={badEpoch}
                 onChange={(v) => upd({ epoch_utc: v })} inline />
      <div className="mt-1 grid grid-cols-3 gap-x-2 gap-y-1">
        <Num label="ALT" unit="km" value={draft.altitude_km} min={200} max={40000} step={10}
             onChange={(v) => upd({ altitude_km: v })} />
        <Num label="ECC e" value={draft.eccentricity} min={0} max={0.5} step={0.001} digits={4}
             onChange={(v) => upd({ eccentricity: v })} />
        <Num label="INC i" unit="°" value={draft.inclination_deg} min={0} max={180} step={0.1} digits={2}
             onChange={(v) => upd({ inclination_deg: v })} />
        <Num label="RAAN Ω" unit="°" value={draft.raan_deg} min={0} max={359.9} step={1} digits={2}
             onChange={(v) => upd({ raan_deg: v })} />
        <Num label="PERIGEE ω" unit="°" value={draft.arg_perigee_deg} min={0} max={359.9} step={1} digits={2}
             onChange={(v) => upd({ arg_perigee_deg: v })} />
        <Num label="ANOMALY M" unit="°" value={draft.mean_anomaly_deg} min={0} max={359.9} step={1} digits={2}
             onChange={(v) => upd({ mean_anomaly_deg: v })} />
      </div>
      <div className="mt-1 grid grid-cols-3 gap-x-2 gap-y-1">
        {/* `phasing` is re-clamped by normalizeDraft on every edit — no
            per-handler bookkeeping, so a pattern switch is covered too. */}
        <Num label="PLANES" value={draft.planes} min={1} max={36} step={1}
             onChange={(v) => upd({ planes: Math.round(v) })} />
        <Num label="SATS / PLANE" value={draft.sats_per_plane} min={1} max={60} step={1}
             onChange={(v) => upd({ sats_per_plane: Math.round(v) })} />
        <Num label="PHASING f" value={draft.phasing} min={0} max={Math.max(0, draft.planes - 1)} step={1}
             onChange={(v) => upd({ phasing: Math.round(v) })} />
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
/** Dawn–dusk only: the ascending node crosses at dusk (18:00) or dawn (06:00).
 *  Anything between is a different sun-synchronous orbit, not this feature. */
const LTAN_CHOICES: [number, string][] = [[6, '06:00'], [18, '18:00']]

/** Degrees with an explicit sign and a real minus glyph (β is signed: a dawn
 *  plane carries the sun on the other side of its normal). */
function fmtSignedDeg(v: number): string {
  return `${v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}°`
}

function SsoParams({ draft, upd, badEpoch, sun }: {
  draft: OrbitDesignDraft
  upd: (patch: Partial<OrbitDesignDraft>) => void
  badEpoch: boolean
  sun: SunAngles | null
}) {
  const iLo = ssoInclinationDeg(draft.alt_min_km)
  const iHi = ssoInclinationDeg(draft.alt_max_km)
  // One layer = ONE shell at alt_min, so there is one altitude and one
  // inclination — printing a range there would be a lie.
  const single = draft.layers <= 1
  const total = draft.layers * draft.sats_per_plane

  // Every shell shares this Ω — that is what puts them all on one plane.
  // β is quoted for shell 0 (the lowest), which is also what the backend
  // reports at the top level of `sso`; across a 500–700 km stack the shells'
  // own sun-synchronous inclinations spread β by well under 1°.
  const raan = sun ? raanForLtan(sun.raDeg, draft.ltan_hours) : null
  const beta = sun && raan !== null && iLo !== null
    ? betaDeg(iLo, raan, sun.raDeg, sun.decDeg)
    : null
  const tilt = beta === null ? null : 90 - Math.abs(beta)
  const offTerminator = tilt !== null && tilt > 5      // i.e. |β| < 85°
  // A day-resolution scan of one year — a few hundred flops, only while the
  // note is actually shown, so it needs no memo of its own.
  const dates = offTerminator && iLo !== null
    ? terminatorDates(iLo, julianDayOf(draft.epoch_utc))
    : []

  const ltanLabel = LTAN_CHOICES.find(([h]) => h === draft.ltan_hours)?.[1] ?? '18:00'
  const derived = iLo === null || iHi === null ? [] : [
    `${draft.layers} shell${single ? '' : 's'} on the dawn–dusk line`,
    single ? `${draft.alt_min_km.toFixed(0)} km`
           : `${draft.alt_min_km.toFixed(0)}–${draft.alt_max_km.toFixed(0)} km`,
    single ? `i ${iLo.toFixed(2)}°` : `i ${iLo.toFixed(2)}°–${iHi.toFixed(2)}°`,
    `LTAN ${ltanLabel}`,
    ...(raan !== null ? [`Ω ${raan.toFixed(1)}°`] : []),
    ...(beta !== null ? [`β ${fmtSignedDeg(beta)}`] : []),
    `${total} satellite${total === 1 ? '' : 's'}`,
  ]

  return (
    <>
      <TimeField label="EPOCH" value={draft.epoch_utc} invalid={badEpoch}
                 onChange={(v) => upd({ epoch_utc: v })} inline />
      {/* LTAN rides the altitude row rather than a row of its own: the flow
          has no spare vertical budget, and a 4th cell on the Layers row would
          truncate "SATS / PLANE". */}
      <div className="mt-1 grid grid-cols-3 gap-x-2 gap-y-1">
        <Num label="ALT MIN" unit="km" value={draft.alt_min_km} min={250} max={1600} step={10}
             onChange={(v) => upd({ alt_min_km: v })} />
        <Num label="ALT MAX" unit="km" value={draft.alt_max_km} min={250} max={1600} step={10}
             onChange={(v) => upd({ alt_max_km: v })} />
        <div className="flex min-w-0 flex-col gap-0.5">
          <FieldLabel>LTAN <span className="text-text-faint">utc</span></FieldLabel>
          <div className="flex gap-1" role="group" aria-label="Local time of ascending node">
            {LTAN_CHOICES.map(([h, label]) => (
              <button
                key={h}
                type="button"
                data-testid={`ltan-${h}`}
                onClick={() => upd({ ltan_hours: h })}
                aria-pressed={draft.ltan_hours === h}
                title={h === 18
                  ? 'Dusk ascending node — Ω = α_sun + 90°'
                  : 'Dawn ascending node — Ω = α_sun − 90°'}
                className={
                  'flex-1 truncate rounded-md border px-1 py-1 text-[9px] leading-[14px] tabular ' +
                  (draft.ltan_hours === h
                    ? 'border-accent bg-bg-card-hi text-text-hi'
                    : 'border-border-weak bg-bg-inset/40 text-text-lo hover:border-border-med hover:text-text-md')
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-1 grid grid-cols-3 gap-x-2 gap-y-1">
        <Num label="LAYERS" value={draft.layers} min={1} max={12} step={1}
             onChange={(v) => upd({ layers: Math.round(v) })} />
        <Num label="SATS / PLANE" value={draft.sats_per_plane} min={1} max={60} step={1}
             onChange={(v) => upd({ sats_per_plane: Math.round(v) })} />
        <Num label="PHASING f" value={draft.phasing} min={0} max={Math.max(0, draft.layers - 1)} step={1}
             onChange={(v) => upd({ phasing: Math.round(v) })} />
      </div>
      <div className="mt-1 text-[9px] leading-[12px] tabular text-text-lo" data-testid="sso-derived">
        {draft.alt_min_km > draft.alt_max_km ? (
          <span className="text-err">Alt min must be ≤ alt max</span>
        ) : derived.length === 0 ? (
          <span className="text-err">No sun-synchronous solution at this altitude</span>
        ) : (
          <>
            {derived.join(' · ')}
            {/* β is what the geometry actually gives, never a claim that the
                plane IS the terminator. Ω already maximises it; the residual
                is the sun's declination and only the epoch can move it. */}
            {offTerminator && beta !== null && tilt !== null && (
              <div className="mt-0.5 text-text-faint">
                β {fmtSignedDeg(beta)} — plane is {tilt.toFixed(1)}° off the terminator at this epoch
                {dates.length ? ` (β = 90° near ${dates.join(' / ')})` : ''}
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

/** Section rule: a 1px separator + a small-caps label, with an optional
 *  right-hand readout. Groups the flow with negative space instead of
 *  stacking one bordered card per step — and costs ~19px, which is what
 *  keeps the whole flow inside the column's height budget. */
function Rule({ label, right }: { label: string; right?: React.ReactNode }) {
  return (
    <div className="mt-2 flex items-baseline justify-between gap-2 border-t border-border-weak
                    pt-1 pb-0.5 text-[9px] uppercase tracking-[0.12em] text-text-lo">
      <span className="truncate">{label}</span>
      {right}
    </div>
  )
}

function Elem({ k, v }: { k: string; v: string }) {
  return (
    <span className="flex items-baseline gap-1 truncate">
      <span className="text-text-lo">{k}</span>
      <span className="truncate font-semibold text-text-hi">{v}</span>
    </span>
  )
}

/** Segmented-control button. Unimplemented entries render but never fire. */
function Seg({ testId, label, active, disabled, title, onClick }: {
  testId: string; label: string; active: boolean
  disabled?: boolean; title?: string; onClick: () => void
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      aria-disabled={disabled ? 'true' : undefined}
      aria-pressed={active}
      title={title}
      className={
        'flex-1 truncate rounded-md border px-1 py-1 text-[10px] ' +
        (disabled
          ? 'cursor-not-allowed border-border-weak bg-bg-inset/20 text-text-faint'
          : active
            ? 'border-accent bg-bg-card-hi text-text-hi'
            : 'border-border-weak bg-bg-inset/40 text-text-lo hover:border-border-med hover:text-text-md')
      }
    >
      {label}
    </button>
  )
}

const timeInputClass =
  'w-full rounded-md border border-border-weak bg-bg-inset px-1.5 py-1 text-[10px] tabular ' +
  'text-text-hi outline-none focus:border-accent'

/** Same recipe, but every property that App.css's legacy global
 *  `select, input[type="number"], input[type="text"] { font: inherit; … }`
 *  rule also sets has to be marked important: an attribute selector
 *  out-specifies a Tailwind utility class, so without `!` these cells render
 *  at 16px on the legacy panel fill and the accent focus border never shows. */
const numInputClass =
  'w-full rounded-md border !border-border-weak !bg-bg-inset !px-1.5 !py-1 ' +
  '!text-[10px] !leading-[14px] !tabular-nums !text-text-hi text-right ' +
  'outline-none focus:!border-accent'

/** Labels are written already-capitalised rather than `uppercase`: the CSS
 *  transform would fold the ω of "PERIGEE ω" into an Ω. */
function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="truncate text-[9px] tracking-[0.08em] text-text-lo">{children}</span>
  )
}

/** `inline` puts the label beside the control instead of above it — one row
 *  instead of two, which is how the Epoch fits the parameter budget.
 *  `invalid` marks a cleared/unparseable instant: Apply is gated on the same
 *  condition, so the block and the button always agree. */
function TimeField({ label, value, onChange, inline = false, invalid = false }: {
  label: string; value: string; onChange: (v: string) => void
  inline?: boolean; invalid?: boolean
}) {
  const input = (
    <input
      type="datetime-local"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid ? 'true' : undefined}
      className={
        (inline ? `${timeInputClass} w-[172px]` : timeInputClass)
        + (invalid ? ' !border-err' : '')
      }
    />
  )
  if (inline) {
    return (
      <label className="flex min-w-0 items-center gap-2">
        <span className="w-[60px] shrink-0">
          <FieldLabel>{label} <span className="text-text-faint">utc</span></FieldLabel>
        </span>
        {input}
      </label>
    )
  }
  return (
    <label className="flex min-w-0 flex-col gap-0.5">
      <FieldLabel>{label} <span className="text-text-faint">utc</span></FieldLabel>
      {input}
    </label>
  )
}

/** Trim a value to `digits` decimals without padding zeros — the input shows
 *  `0.001`, not `0.0010`, so typing stays predictable. */
function fmtNum(v: number, digits: number): string {
  return digits > 0 ? String(Number(v.toFixed(digits))) : String(Math.round(v))
}

/** Compact numeric cell: label above a right-aligned number input. While the
 *  cell has focus the raw keystrokes win, so a partial "5" on the way to "550"
 *  isn't fought; on blur the value is clamped to [min, max] and the cell goes
 *  back to rendering `value` directly (no mirrored copy to keep in sync). */
function Num({ label, unit, value, min, max, step, digits = 0, onChange }: {
  label: string; unit?: string; value: number
  min: number; max: number; step: number; digits?: number
  onChange: (v: number) => void
}) {
  const [raw, setRaw] = useState<string | null>(null)   // non-null only while editing

  return (
    <label className="flex min-w-0 flex-col gap-0.5">
      <FieldLabel>{label}{unit ? <span className="text-text-faint"> {unit}</span> : null}</FieldLabel>
      <input
        type="number"
        min={min} max={max} step={step}
        value={raw ?? fmtNum(value, digits)}
        onFocus={() => setRaw(fmtNum(value, digits))}
        onChange={(e) => {
          setRaw(e.target.value)
          const n = Number(e.target.value)
          if (e.target.value !== '' && Number.isFinite(n)) onChange(n)
        }}
        onBlur={(e) => {
          const n = Number(e.target.value)
          const clamped = e.target.value !== '' && Number.isFinite(n)
            ? Math.min(max, Math.max(min, n))
            : value
          setRaw(null)
          if (clamped !== value) onChange(clamped)
        }}
        className={numInputClass}
      />
    </label>
  )
}
