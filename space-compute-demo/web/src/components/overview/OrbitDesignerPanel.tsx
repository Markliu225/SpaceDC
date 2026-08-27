import { useEffect, useRef, useState } from 'react'
import { Loader2, MapPin, Orbit, Play, Radio, Satellite, Sun } from 'lucide-react'
import { Card } from '../primitives'
import { RealCoverageMap } from './RealCoverageMap'
import { CoverageCharts, SolarHistogram, BandCurves } from './GroundAnalytics'
import {
  useOrbitDesign, useCoverageHistory, DESIGN_DEFAULTS, GROUND_CONFIG_DEFAULTS,
  type OrbitDesignDraft, type GroundConfig,
} from '../../hooks/useOrbitDesign'
import type { CommsBand, GroundTargetState } from '../../types/messages'

type Tab = 'designer' | 'coverage' | 'solar' | 'bands'

/**
 * OrbitDesignerPanel — Overview right column. Four tabs:
 *   DESIGNER — orbit elements + Walker + Apply, then the ground-station
 *              config (elevation mask · comms band · solar bin) and the
 *              Singapore mark toggle.
 *   COVERAGE — the constellation status map + live visibility/bandwidth
 *              line charts.
 *   SOLAR    — solar-collection histogram binned by illumination intensity.
 *   BANDS    — throughput-vs-elevation comparison across comms bands.
 *
 * All four analytics follow the marked ground station's live StatePacket.
 */
export function OrbitDesignerPanel() {
  const [tab, setTab] = useState<Tab>('designer')
  const design = useOrbitDesign()
  const coverage = useCoverageHistory()
  const gt = design.groundTarget

  const TABS: [Tab, string][] = [
    ['designer', 'Design'], ['coverage', 'Coverage'],
    ['solar', 'Solar'], ['bands', 'Bands'],
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
      {tab === 'coverage' && (
        <div className="flex flex-1 min-h-0 flex-col gap-2">
          <div className="min-h-0" style={{ flex: '1 1 52%' }}>
            <RealCoverageMap embedded />
          </div>
          <div className="flex min-h-0 flex-col" style={{ flex: '1 1 48%' }}>
            <CoverageCharts history={coverage} gt={gt} />
          </div>
        </div>
      )}
      {tab === 'solar' && (
        <div className="flex flex-1 min-h-0 flex-col">
          <SolarHistogram gt={gt} />
        </div>
      )}
      {tab === 'bands' && (
        <div className="flex flex-1 min-h-0 flex-col">
          <BandCurves gt={gt} bands={design.bands} />
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
function DesignerBody({ design }: { design: ReturnType<typeof useOrbitDesign> }) {
  const {
    info, bands, groundTarget, visibility,
    busy, analyzing, offline, error,
    apply, setGroundTarget, analyze,
  } = design

  const [draft, setDraft] = useState<OrbitDesignDraft>(DESIGN_DEFAULTS)
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    if (touched || !info) return
    const clamp = (lo: number, hi: number, v: number) => Math.min(hi, Math.max(lo, v))
    const wrap360 = (v: number) => ((v % 360) + 360) % 360
    const planes = clamp(1, 36, Math.round(info.walker.planes))
    setDraft({
      altitude_km: clamp(200, 36000, Math.round(info.elements.altitude_km)),
      eccentricity: clamp(0, 0.3, info.elements.eccentricity),
      inclination_deg: clamp(0, 180, info.elements.inclination_deg),
      raan_deg: Math.min(359.9, wrap360(info.elements.raan_deg)),
      arg_perigee_deg: Math.min(359.9, wrap360(info.elements.arg_perigee_deg)),
      mean_anomaly_deg: Math.min(359.9, wrap360(info.elements.mean_anomaly_deg)),
      planes,
      sats_per_plane: clamp(1, 40, Math.round(info.walker.sats_per_plane)),
      phasing: clamp(0, planes - 1, Math.round(info.walker.phasing)),
    })
  }, [info, touched])

  const upd = (patch: Partial<OrbitDesignDraft>) => {
    setTouched(true)
    setDraft((d) => ({ ...d, ...patch }))
  }

  const el = info?.elements
  const gtOn = groundTarget?.enabled === true

  return (
    <div className="flex flex-1 min-h-0 flex-col gap-2 overflow-y-auto pr-0.5">
      {offline && (
        <div className="rounded border border-warn/40 bg-warn/10 px-2 py-1.5 text-[10px] text-warn">
          Backend offline — designs cannot be applied.
        </div>
      )}
      {error && !offline && (
        <div className="rounded border border-err/40 bg-err/10 px-2 py-1.5 text-[10px] text-err">{error}</div>
      )}

      <Section icon={<Orbit size={11} />} title={`Active elements · ${info?.name ?? '—'}`}>
        <div className="grid grid-cols-3 gap-x-2 gap-y-1" data-testid="orbit-elements">
          <Elem k="a" label="semi-major" v={el ? `${el.semi_major_axis_km.toFixed(0)} km` : '—'} />
          <Elem k="e" label="eccentricity" v={el ? el.eccentricity.toFixed(4) : '—'} />
          <Elem k="i" label="inclination" v={el ? `${el.inclination_deg.toFixed(2)}°` : '—'} />
          <Elem k="Ω" label="RAAN" v={el ? `${el.raan_deg.toFixed(2)}°` : '—'} />
          <Elem k="ω" label="arg perigee" v={el ? `${el.arg_perigee_deg.toFixed(2)}°` : '—'} />
          <Elem k="M" label="mean anomaly" v={el ? `${el.mean_anomaly_deg.toFixed(2)}°` : '—'} />
        </div>
        <div className="mt-1 text-[9px] text-text-lo tabular">
          period {el ? el.period_min.toFixed(1) : '—'} min · altitude {el ? el.altitude_km.toFixed(0) : '—'} km
        </div>
      </Section>

      <Section icon={<Satellite size={11} />} title="Design · orbital elements">
        <Field label="Altitude" unit="km" value={draft.altitude_km} min={200} max={36000} step={10}
               onChange={(v) => upd({ altitude_km: v })} />
        <Field label="Eccentricity" unit="" value={draft.eccentricity} min={0} max={0.3} step={0.001} digits={3}
               onChange={(v) => upd({ eccentricity: v })} />
        <Field label="Inclination" unit="°" value={draft.inclination_deg} min={0} max={180} step={0.5} digits={1}
               onChange={(v) => upd({ inclination_deg: v })} />
        <Field label="RAAN Ω" unit="°" value={draft.raan_deg} min={0} max={359.9} step={1} digits={1}
               onChange={(v) => upd({ raan_deg: v })} />
        <Field label="Arg perigee ω" unit="°" value={draft.arg_perigee_deg} min={0} max={359.9} step={1} digits={1}
               onChange={(v) => upd({ arg_perigee_deg: v })} />
        <Field label="Mean anomaly M" unit="°" value={draft.mean_anomaly_deg} min={0} max={359.9} step={1} digits={1}
               onChange={(v) => upd({ mean_anomaly_deg: v })} />
      </Section>

      <Section icon={<Satellite size={11} />} title="Design · Walker pattern">
        <Field label="Planes" unit="" value={draft.planes} min={1} max={36} step={1}
               onChange={(v) => upd({ planes: Math.round(v), phasing: Math.min(draft.phasing, Math.max(0, Math.round(v) - 1)) })} />
        <Field label="Sats / plane" unit="" value={draft.sats_per_plane} min={1} max={40} step={1}
               onChange={(v) => upd({ sats_per_plane: Math.round(v) })} />
        <Field label="Phasing f" unit="" value={draft.phasing} min={0} max={Math.max(0, draft.planes - 1)} step={1}
               onChange={(v) => upd({ phasing: Math.round(v) })} />
        <div className="text-[9px] text-text-lo tabular">total {draft.planes * draft.sats_per_plane} satellites</div>
      </Section>

      <button
        type="button"
        data-testid="orbit-apply"
        onClick={() => void apply(draft)}
        disabled={busy || offline}
        className="flex items-center justify-center gap-2 rounded border border-accent/60 bg-accent/15
                   px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.10em] text-accent
                   hover:bg-accent/25 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} strokeWidth={2} />}
        Apply design
      </button>

      {/* Ground-station config step. */}
      <GroundConfigSection
        gtOn={gtOn} groundTarget={groundTarget} bands={bands}
        setGroundTarget={setGroundTarget}
        visibility={visibility} analyzing={analyzing} analyze={analyze}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
function GroundConfigSection({
  gtOn, groundTarget, bands, setGroundTarget, visibility, analyzing, analyze,
}: {
  gtOn: boolean
  groundTarget: GroundTargetState | null
  bands: CommsBand[]
  setGroundTarget: (enabled: boolean, config?: GroundConfig) => Promise<boolean>
  visibility: ReturnType<typeof useOrbitDesign>['visibility']
  analyzing: boolean
  analyze: () => Promise<boolean>
}) {
  // Local config draft, authoritative for the controls while the user edits.
  const [cfg, setCfg] = useState<GroundConfig>(GROUND_CONFIG_DEFAULTS)
  // Debounce the live re-config POST: the elevation slider fires onChange on
  // every pixel of a drag, which would otherwise flood the backend with
  // /ground_target posts (and race — last-write-wins is not guaranteed).
  const postTimer = useRef<number | undefined>(undefined)
  const pendingRef = useRef(false)
  useEffect(() => () => window.clearTimeout(postTimer.current), [])

  // Adopt the server config whenever it changes AND we have no local edit in
  // flight — keeps the selector in sync with the live analytics (e.g. after
  // an external POST /ground_target) without stomping an in-progress drag.
  useEffect(() => {
    if (!groundTarget?.enabled || pendingRef.current) return
    setCfg({
      elevation_mask_deg: groundTarget.elevation_mask_deg,
      band: groundTarget.band,
      solar_bin: groundTarget.solar_bin,
    })
  }, [groundTarget?.enabled, groundTarget?.band,
      groundTarget?.elevation_mask_deg, groundTarget?.solar_bin])

  const bandList = bands.length ? bands : FALLBACK_BANDS
  const push = (next: GroundConfig) => {
    setCfg(next)
    if (!gtOn) return
    pendingRef.current = true
    window.clearTimeout(postTimer.current)
    postTimer.current = window.setTimeout(() => {
      void setGroundTarget(true, next).finally(() => { pendingRef.current = false })
    }, 200)
  }

  return (
    <Section icon={<MapPin size={11} className="text-err" />} title="Ground station · Singapore">
      <button
        type="button"
        data-testid="ground-target-toggle"
        onClick={() => void setGroundTarget(!gtOn, cfg)}
        aria-pressed={gtOn}
        className={
          'mb-2 flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left text-[11px] ' +
          (gtOn ? 'border-err/60 bg-err/15 text-text-hi'
                : 'border-border-weak bg-bg-inset/40 text-text-md hover:border-border-med')
        }
      >
        <span className={'h-2 w-2 rounded-full ' + (gtOn ? 'bg-err' : 'border border-border-med')} />
        {gtOn ? 'Marked on Earth — 1.35°N 103.82°E' : 'Mark Singapore on the Earth'}
      </button>

      {/* Config: elevation mask · band · solar bin. */}
      <Field label="Elevation mask" unit="°" value={cfg.elevation_mask_deg} min={0} max={40} step={1} digits={0}
             onChange={(v) => push({ ...cfg, elevation_mask_deg: v })} />

      <div className="mt-1 flex items-center gap-2">
        <span className="flex w-[92px] shrink-0 items-center gap-1 text-[10px] text-text-md">
          <Radio size={10} /> Comms band
        </span>
        <div className="flex flex-1 gap-1">
          {bandList.map((b) => (
            <button
              key={b.id}
              type="button"
              data-testid={`band-${b.id}`}
              onClick={() => push({ ...cfg, band: b.id })}
              aria-pressed={cfg.band === b.id}
              title={`${b.label} · ${b.per_sat_mbps} Mbps/sat · min ${b.min_elevation_deg}°`}
              className={
                'flex-1 rounded border px-1 py-0.5 text-[9px] ' +
                (cfg.band === b.id
                  ? 'border-accent bg-bg-card-hi text-text-hi'
                  : 'border-border-weak bg-bg-inset/40 text-text-lo hover:border-border-med')
              }
            >
              {b.id}
            </button>
          ))}
        </div>
      </div>
      {gtOn && groundTarget && (
        <div className="mt-0.5 text-[9px] text-text-lo tabular">
          {groundTarget.band_label} · {groundTarget.band_mbps_per_sat} Mbps/sat ·
          effective mask {groundTarget.min_elevation_deg.toFixed(0)}°
        </div>
      )}

      <div className="mt-1 flex items-center gap-2">
        <span className="flex w-[92px] shrink-0 items-center gap-1 text-[10px] text-text-md">
          <Sun size={10} /> Solar bin
        </span>
        <div className="flex flex-1 gap-1">
          {[5, 10].map((n) => (
            <button
              key={n}
              type="button"
              data-testid={`solar-bin-${n}`}
              onClick={() => push({ ...cfg, solar_bin: n })}
              aria-pressed={cfg.solar_bin === n}
              className={
                'flex-1 rounded border px-1 py-0.5 text-[9px] ' +
                (cfg.solar_bin === n
                  ? 'border-accent bg-bg-card-hi text-text-hi'
                  : 'border-border-weak bg-bg-inset/40 text-text-lo hover:border-border-med')
              }
            >
              per {n}
            </button>
          ))}
        </div>
      </div>

      {gtOn && groundTarget && (
        <div className="mt-2 flex flex-col gap-1.5" data-testid="ground-visibility-live">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-text-md">Comm visibility now</span>
            <span className={'tabular font-semibold ' + (groundTarget.visible_sats > 0 ? 'text-ok' : 'text-text-lo')}>
              {groundTarget.visible_sats > 0
                ? `${groundTarget.visible_sats} sat${groundTarget.visible_sats > 1 ? 's' : ''} · ${Math.round(groundTarget.aggregate_mbps)} Mbps`
                : 'no contact'}
            </span>
          </div>
          <button
            type="button"
            data-testid="ground-analyze"
            onClick={() => void analyze()}
            disabled={analyzing}
            className="flex items-center justify-center gap-1.5 rounded border border-border-med bg-bg-inset/40
                       px-2 py-1 text-[10px] uppercase tracking-[0.08em] text-text-md hover:text-text-hi disabled:opacity-40"
          >
            {analyzing && <Loader2 size={10} className="animate-spin" />}
            Analyze passes · 1 orbit
          </button>
          {visibility && <PassAnalysis v={visibility} />}
        </div>
      )}
    </Section>
  )
}

const FALLBACK_BANDS: CommsBand[] = [
  { id: 'UHF', label: 'UHF', per_sat_mbps: 2, min_elevation_deg: 5 },
  { id: 'S', label: 'S-band', per_sat_mbps: 20, min_elevation_deg: 5 },
  { id: 'X', label: 'X-band', per_sat_mbps: 150, min_elevation_deg: 10 },
  { id: 'Ka', label: 'Ka-band', per_sat_mbps: 800, min_elevation_deg: 20 },
]

// ---------------------------------------------------------------------------
function PassAnalysis({ v }: { v: ReturnType<typeof useOrbitDesign>['visibility'] & object }) {
  if (!v) return null
  const toRealMin = (simS: number) => (simS * v.time_scale) / 60
  return (
    <div data-testid="ground-passes" className="rounded border border-border-weak bg-bg-inset/40 p-1.5">
      <div className="relative h-2 w-full overflow-hidden rounded-sm bg-bg-app">
        {v.windows.map((w, i) => (
          <span key={i} className="absolute inset-y-0 bg-ok/80"
                style={{ left: `${(w.start_s / v.duration_s) * 100}%`,
                         width: `${Math.max(1, ((w.end_s - w.start_s) / v.duration_s) * 100)}%` }} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[9px] tabular text-text-lo">
        <span>now</span><span>+{(v.period_s_real / 60).toFixed(0)} min (1 orbit)</span>
      </div>
      <div className="mt-1 text-[10px] tabular text-text-md">
        contact {Math.round(v.coverage_fraction * 100)}% of orbit · {v.windows.length} pass{v.windows.length === 1 ? '' : 'es'}
        {v.next_pass_in_s !== null && v.next_pass_in_s > 0.5 && (
          <> · next in {toRealMin(v.next_pass_in_s).toFixed(0)} min</>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
function Section({ icon, title, children }: {
  icon: React.ReactNode; title: string; children: React.ReactNode
}) {
  return (
    <div className="rounded border border-border-weak bg-bg-inset/30 px-2 py-1.5">
      <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.10em] text-text-lo">
        <span className="text-accent">{icon}</span>{title}
      </div>
      {children}
    </div>
  )
}

function Elem({ k, label, v }: { k: string; label: string; v: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] text-text-lo">{k} · {label}</span>
      <span className="text-[11px] font-semibold tabular text-text-hi">{v}</span>
    </div>
  )
}

function Field({ label, unit, value, min, max, step, digits = 0, onChange }: {
  label: string; unit: string; value: number
  min: number; max: number; step: number; digits?: number
  onChange: (v: number) => void
}) {
  return (
    <div className="mb-1 flex items-center gap-2">
      <span className="w-[92px] shrink-0 text-[10px] text-text-md">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="h-1 flex-1 accent-accent" />
      <span className="w-[64px] shrink-0 text-right text-[10px] tabular text-text-hi">
        {value.toFixed(digits)}{unit && <span className="text-text-lo"> {unit}</span>}
      </span>
    </div>
  )
}
