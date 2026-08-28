import { useCallback, useEffect, useRef, useState } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useTelemetryStore } from '../store/useTelemetryStore'
import type {
  CommsBand, CommsBandsResponse, GroundTargetState,
  GroundVisibilityResponse, OrbitDesignInfo,
} from '../types/messages'

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://127.0.0.1:8001'

/** Constellation pattern. `custom` (TLE import) is UI-only — it is never
 *  POSTed, because the backend answers it with a 422. */
export type DesignMode = 'walker' | 'sso' | 'custom'

/** The designer's editable fields — mirrors POST /orbit_design.
 *  Datetime fields are `datetime-local` strings (`YYYY-MM-DDTHH:mm`, UTC
 *  wall-clock); `localInputToIso` converts them for the wire. */
export interface OrbitDesignDraft {
  mode: DesignMode
  propagator: string
  epoch_utc: string
  start_utc: string
  end_utc: string
  // walker
  altitude_km: number
  eccentricity: number
  inclination_deg: number
  raan_deg: number
  arg_perigee_deg: number
  mean_anomaly_deg: number
  planes: number
  // shared by walker + sso
  sats_per_plane: number
  phasing: number
  // sso
  alt_min_km: number
  alt_max_km: number
  layers: number
  /** Local time of the ascending node, hours. Dawn–dusk only: 6 or 18. */
  ltan_hours: number
}

/** Demo mission epoch (backend `timebase.DEMO_EPOCH_UTC`) as datetime-local. */
const DEMO_EPOCH_LOCAL = '2024-08-22T12:00'
const DEMO_END_LOCAL = '2024-08-23T12:00'

export const DESIGN_DEFAULTS: OrbitDesignDraft = {
  mode: 'walker', propagator: 'sgp4',
  epoch_utc: DEMO_EPOCH_LOCAL, start_utc: DEMO_EPOCH_LOCAL, end_utc: DEMO_END_LOCAL,
  altitude_km: 550, eccentricity: 0.001, inclination_deg: 53,
  raan_deg: 0, arg_perigee_deg: 0, mean_anomaly_deg: 0,
  planes: 3, sats_per_plane: 8, phasing: 1,
  alt_min_km: 500, alt_max_km: 700, layers: 3, ltan_hours: 18,
}

/** How many planes the draft's ACTIVE pattern has — Walker spreads RAAN over
 *  `planes`, SSO stacks `layers` shells on one plane. The phasing factor is
 *  indexed against this count in both, which is why it has to be re-clamped
 *  whenever the pattern (not just the count) changes. */
export function planeCount(draft: OrbitDesignDraft): number {
  return draft.mode === 'sso' ? draft.layers : draft.planes
}

/** Re-clamp the cross-mode fields after any edit. `phasing` is shared by both
 *  patterns but bounded by the ACTIVE one's plane count (0 ≤ f < planes), so
 *  "SSO · layers 6 · f 5 → Walker · planes 1" must drop f to 0 rather than
 *  POST an f the backend answers with a 422. */
export function normalizeDraft(draft: OrbitDesignDraft): OrbitDesignDraft {
  const maxPhasing = Math.max(0, planeCount(draft) - 1)
  const phasing = Math.min(Math.max(0, Math.round(draft.phasing)), maxPhasing)
  const ltan = draft.ltan_hours === 6 ? 6 : 18
  return phasing === draft.phasing && ltan === draft.ltan_hours
    ? draft
    : { ...draft, phasing, ltan_hours: ltan }
}

/** True when a `datetime-local` value is a complete, parseable UTC instant.
 *  An empty control (the user cleared it) yields `''`, which would otherwise
 *  be POSTed as `epoch_utc: ""` and come back as a raw 422. */
export function isValidLocalDateTime(local: string): boolean {
  const iso = localInputToIso(local)
  return iso !== '' && Number.isFinite(Date.parse(iso))
}

const TIME_FIELD_LABELS: Record<'epoch_utc' | 'start_utc' | 'end_utc', string> = {
  epoch_utc: 'Epoch', start_utc: 'Start', end_utc: 'End',
}
export type TimeFieldKey = keyof typeof TIME_FIELD_LABELS

/** Which of the three mission instants are unusable, and a message for them.
 *  Returns `null` when the draft's times are safe to POST. */
export function draftTimeIssue(draft: OrbitDesignDraft): {
  fields: TimeFieldKey[]; message: string
} | null {
  const keys: TimeFieldKey[] = ['epoch_utc', 'start_utc', 'end_utc']
  const bad = keys.filter((k) => !isValidLocalDateTime(draft[k]))
  if (bad.length) {
    const names = bad.map((k) => TIME_FIELD_LABELS[k])
    const list = names.length > 1
      ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
      : names[0]
    return {
      fields: bad,
      message: `${list} ${names.length > 1 ? 'need' : 'needs'} a valid UTC time`,
    }
  }
  if (windowSeconds(draft.start_utc, draft.end_utc) <= 0) {
    return { fields: ['end_utc'], message: 'End must be after start' }
  }
  return null
}

/** ISO-8601 UTC (`2024-08-22T12:00:00Z`) → `datetime-local` value.
 *  Cuts the UTC wall-clock fields out of the string rather than going through
 *  `Date`, so the control shows UTC and not the viewer's timezone. */
export function isoToLocalInput(iso: string | undefined | null): string {
  if (!iso) return ''
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(iso)
  return m ? `${m[1]}T${m[2]}` : ''
}

/** `datetime-local` value → ISO-8601 UTC with seconds and a Z suffix. */
export function localInputToIso(local: string): string {
  if (!local) return ''
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(:\d{2})?/.exec(local)
  return m ? `${m[1]}T${m[2]}${m[3] ?? ':00'}Z` : ''
}

/** Real seconds spanned by two `datetime-local` values (NaN-safe, may be <= 0). */
export function windowSeconds(startLocal: string, endLocal: string): number {
  const a = Date.parse(localInputToIso(startLocal))
  const b = Date.parse(localInputToIso(endLocal))
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0
  return (b - a) / 1000
}

/** Ground-station comms config (Overview config step). */
export interface GroundConfig {
  elevation_mask_deg: number
  band: string
  solar_bin: number
}

export const GROUND_CONFIG_DEFAULTS: GroundConfig = {
  elevation_mask_deg: 10, band: 'X', solar_bin: 10,
}

/**
 * useOrbitDesign — data source + actions for the Overview orbit designer and
 * ground-station comms config.
 *
 * `info` is the ACTIVE constellation's six classical elements plus the
 * mission window, the propagation-model catalog and the Walker/SSO pattern
 * in force. `apply()` POSTs the design and refetches the ring so every
 * view re-propagates. `bands` is the comms-band catalog. `setGroundTarget`
 * marks Singapore with the current comms config; live analytics (visibility,
 * bandwidth, elevation CDF, solar histogram) ride `lastState.ground_target`.
 */
export function useOrbitDesign() {
  const activeId = useTelemetryStore((s) => s.activeConstellationId)
  const groundTarget: GroundTargetState | null =
    useDemoStore((s) => s.lastState?.ground_target ?? null)

  const [info, setInfo] = useState<OrbitDesignInfo | null>(null)
  const [bands, setBands] = useState<CommsBand[]>([])
  const [visibility, setVisibility] = useState<GroundVisibilityResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [offline, setOffline] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshInfo = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/orbit_design`)
      if (!r.ok) throw new Error(`${r.status}`)
      setInfo((await r.json()) as OrbitDesignInfo)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => { void refreshInfo() }, [refreshInfo, activeId])

  // Comms-band catalog (static — fetch once).
  useEffect(() => {
    let cancelled = false
    fetch(`${BACKEND_HTTP}/comms_bands`)
      .then((r) => r.ok ? r.json() as Promise<CommsBandsResponse> : null)
      .then((d) => { if (!cancelled && d) setBands(d.bands) })
      .catch(() => { /* offline — band selector shows a minimal fallback */ })
    return () => { cancelled = true }
  }, [])

  const apply = useCallback(async (draft: OrbitDesignDraft): Promise<boolean> => {
    // `custom` is a UI-only placeholder (TLE import is not wired up) and the
    // backend answers it with a 422 — never put it on the wire.
    if (draft.mode === 'custom') {
      setError('TLE import is not wired up yet.')
      return false
    }
    // A cleared datetime-local reads as '' and would go on the wire as
    // `epoch_utc: ""` → a raw 422. Refuse here as well as in the UI so no
    // caller can produce that request.
    const timeIssue = draftTimeIssue(draft)
    if (timeIssue) {
      setError(`${timeIssue.message}.`)
      return false
    }
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${BACKEND_HTTP}/orbit_design`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(designPayload(draft)),
      })
      if (!r.ok) {
        const detail = await r.json().catch(() => null) as { detail?: string } | null
        setError(detail?.detail ?? `Design rejected (${r.status})`)
        return false
      }
      const body = (await r.json()) as OrbitDesignInfo
      setInfo(body)
      useTelemetryStore.getState().setActiveConstellation(body.active)
      // Refetch the ring detail EXPLICITLY: every design registers under the
      // same 'custom_design' id, so the id-keyed bridge effect would not
      // re-run on a REdesign and the fleet views would keep the old orbit.
      try {
        const dr = await fetch(`${BACKEND_HTTP}/constellations/${body.active}`)
        if (dr.ok) {
          useTelemetryStore.getState().setConstellationDetail(await dr.json())
        }
      } catch { /* bridge's id-keyed fetch remains the fallback */ }
      setVisibility(null)
      setOffline(false)
      return true
    } catch {
      setOffline(true)
      setError('Backend offline — start the FastAPI server (port 8001).')
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  /** Mark/clear the ground station with the comms config (or re-post config
   *  while already marked to change band / elevation / solar bin live). */
  const setGroundTarget = useCallback(async (
    enabled: boolean, config?: GroundConfig,
  ): Promise<boolean> => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/ground_target`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, ...(config ?? {}) }),  // defaults = Singapore
      })
      if (!enabled) setVisibility(null)
      return r.ok
    } catch {
      setOffline(true)
      return false
    }
  }, [])

  const analyze = useCallback(async (): Promise<boolean> => {
    setAnalyzing(true)
    setError(null)
    try {
      const r = await fetch(`${BACKEND_HTTP}/ground_visibility?orbits=1`)
      if (!r.ok) {
        const detail = await r.json().catch(() => null) as { detail?: string } | null
        setError(detail?.detail ?? `Analysis failed (${r.status})`)
        return false
      }
      setVisibility((await r.json()) as GroundVisibilityResponse)
      return true
    } catch {
      setOffline(true)
      return false
    } finally {
      setAnalyzing(false)
    }
  }, [])

  return {
    info, bands, groundTarget, visibility,
    busy, analyzing, offline, error,
    refreshInfo, apply, setGroundTarget, analyze,
  }
}

/** One coverage sample: visible-sat count + aggregate bandwidth at a tick. */
export interface CoverageSample {
  visible: number
  mbps: number
}

const COVERAGE_LEN = 120

/**
 * useCoverageHistory — a rolling window of ground-station visibility +
 * bandwidth, accumulated from the broadcast state (1 Hz). Feeds the Coverage
 * tab's line charts. Resets when the ground target is cleared or the sim
 * resets (sim_time_s goes backwards).
 */
export function useCoverageHistory(): CoverageSample[] {
  const [series, setSeries] = useState<CoverageSample[]>([])
  const lastSimRef = useRef<number>(-1)
  // Identity of the fleet these samples describe — a constellation switch OR
  // a same-id custom redesign (design_rev bumps) starts a fresh window so two
  // different fleets' visibility are never conflated in the chart.
  const fleetKeyRef = useRef<string>('')

  useEffect(() => {
    return useDemoStore.subscribe((s, prev) => {
      if (s.lastState === prev.lastState) return
      const st = s.lastState
      const gt = st?.ground_target
      const simT = st?.sim_time_s ?? 0
      if (!gt?.enabled) {
        lastSimRef.current = -1
        fleetKeyRef.current = ''
        setSeries((cur) => (cur.length ? [] : cur))
        return
      }
      const c = st?.constellation
      const fleetKey = `${c?.constellation_id ?? ''}:${c?.design_rev ?? 0}`
      const fleetChanged = fleetKey !== fleetKeyRef.current
      fleetKeyRef.current = fleetKey
      // One sample per new sim-second; reset on a backwards jump (sim reset)
      // or a fleet change (constellation switch / redesign).
      if (!fleetChanged && simT === lastSimRef.current) return
      const reset = fleetChanged || simT < lastSimRef.current
      lastSimRef.current = simT
      const sample: CoverageSample = { visible: gt.visible_sats, mbps: gt.aggregate_mbps }
      setSeries((cur) => {
        const base = reset ? [] : cur
        const next = base.length >= COVERAGE_LEN ? base.slice(1) : base.slice()
        next.push(sample)
        return next
      })
    })
  }, [])

  return series
}

/** POST body for a draft: the common keys plus only the ones its mode uses.
 *  Sending walker elements in `sso` mode (or vice versa) would be ignored by
 *  the backend, but it would also make the request lie about the design. */
function designPayload(draft: OrbitDesignDraft): Record<string, unknown> {
  const common = {
    mode: draft.mode,
    propagator: draft.propagator,
    epoch_utc: localInputToIso(draft.epoch_utc),
    start_utc: localInputToIso(draft.start_utc),
    end_utc: localInputToIso(draft.end_utc),
  }
  if (draft.mode === 'sso') {
    return {
      ...common,
      alt_min_km: draft.alt_min_km,
      alt_max_km: draft.alt_max_km,
      layers: draft.layers,
      sats_per_plane: draft.sats_per_plane,
      phasing: draft.phasing,
      ltan_hours: draft.ltan_hours,
    }
  }
  return {
    ...common,
    altitude_km: draft.altitude_km,
    eccentricity: draft.eccentricity,
    inclination_deg: draft.inclination_deg,
    raan_deg: draft.raan_deg,
    arg_perigee_deg: draft.arg_perigee_deg,
    mean_anomaly_deg: draft.mean_anomaly_deg,
    planes: draft.planes,
    sats_per_plane: draft.sats_per_plane,
    phasing: draft.phasing,
  }
}

/** One fleet energy sample: instantaneous collection (W) + lit-sat count. */
export interface EnergySample {
  w: number
  lit: number
}

const ENERGY_LEN = COVERAGE_LEN

/**
 * useEnergyHistory — a rolling window of whole-constellation solar collection,
 * accumulated from the broadcast state (1 Hz). Feeds the Solar tab's energy
 * chart. Unlike useCoverageHistory it does NOT depend on the ground target:
 * the fleet harvests power whether or not a station is marked. Resets on a
 * fleet change (constellation switch / redesign) or a sim reset.
 */
export function useEnergyHistory(): EnergySample[] {
  const [series, setSeries] = useState<EnergySample[]>([])
  const lastSimRef = useRef<number>(-1)
  const fleetKeyRef = useRef<string>('')

  useEffect(() => {
    return useDemoStore.subscribe((s, prev) => {
      if (s.lastState === prev.lastState) return
      const st = s.lastState
      const c = st?.constellation
      if (!c) {
        lastSimRef.current = -1
        fleetKeyRef.current = ''
        setSeries((cur) => (cur.length ? [] : cur))
        return
      }
      const simT = st?.sim_time_s ?? 0
      const fleetKey = `${c.constellation_id}:${c.design_rev ?? 0}`
      const fleetChanged = fleetKey !== fleetKeyRef.current
      fleetKeyRef.current = fleetKey
      if (!fleetChanged && simT === lastSimRef.current) return
      const reset = fleetChanged || simT < lastSimRef.current
      lastSimRef.current = simT
      const sample: EnergySample = { w: c.solar_total_w ?? 0, lit: c.solar_lit_sats ?? 0 }
      setSeries((cur) => {
        const base = reset ? [] : cur
        const next = base.length >= ENERGY_LEN ? base.slice(1) : base.slice()
        next.push(sample)
        return next
      })
    })
  }, [])

  return series
}

// ---------------------------------------------------------------------------
// Dawn–dusk design physics — the SSO preview's numbers, computed client-side
// from the SAME expressions the backend applies, so the derived line tells the
// truth before Apply rather than after.
// ---------------------------------------------------------------------------

const DEG = Math.PI / 180
const MU_EARTH = 398600.4418        // km^3/s^2
const J2_EARTH = 1.08262668e-3
const RE_KM = 6378.137
const OMEGA_DOT_SUN = 1.99106e-7    // rad/s (2*pi / 365.2422 d)
/** Obliquity at J2000 — the largest |declination| the sun can reach. */
const OBLIQUITY_DEG = 23.4393

/** Sun-synchronous inclination for a circular orbit at `altitudeKm`:
 *    cos i = -2 * Ω̇_sun / (3 * J2 * (Re/p)^2 * n),   p = a(1 - e^2) = a at e = 0.
 *  `null` when no solution exists (|cos i| > 1). Sanity: 500 km → 97.40°. */
export function ssoInclinationDeg(altitudeKm: number): number | null {
  const a = RE_KM + altitudeKm
  if (!(a > 0)) return null
  const n = Math.sqrt(MU_EARTH / (a * a * a))
  const cosI = (-2 * OMEGA_DOT_SUN) / (3 * J2_EARTH * (RE_KM / a) ** 2 * n)
  if (!Number.isFinite(cosI) || Math.abs(cosI) > 1) return null
  return Math.acos(cosI) / DEG
}

/** Julian Date of a `datetime-local` UTC value; NaN when unparseable. */
export function julianDayOf(local: string): number {
  const ms = Date.parse(localInputToIso(local))
  return Number.isFinite(ms) ? ms / 86_400_000 + 2440587.5 : NaN
}

/** Low-precision solar position (USNO almanac series, ±0.01°) as a unit
 *  Earth→Sun vector in the true equator of date.
 *
 *  This is the FALLBACK. It differs from the backend's TEME sun by precession
 *  since J2000 (~0.3° in 2024) — fine for a preview, but whenever the drafted
 *  epoch is the epoch the mission is actually propagating, the broadcast
 *  `sun_unit_teme` is used instead so the preview and the render agree exactly. */
export function sunUnitApprox(jd: number): [number, number, number] {
  const n = jd - 2451545.0
  const L = (280.460 + 0.9856474 * n) * DEG
  const g = (357.528 + 0.9856003 * n) * DEG
  const lam = L + (1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * DEG
  const eps = (OBLIQUITY_DEG - 4e-7 * n) * DEG
  return [Math.cos(lam), Math.cos(eps) * Math.sin(lam), Math.sin(eps) * Math.sin(lam)]
}

/** Right ascension / declination of a sun vector, degrees (α in [0,360)). */
export interface SunAngles { raDeg: number; decDeg: number }
export function sunAngles(v: readonly number[]): SunAngles | null {
  if (v.length < 3) return null
  const r = Math.hypot(v[0], v[1], v[2])
  if (!(r > 0) || !Number.isFinite(r)) return null
  return {
    raDeg: ((Math.atan2(v[1], v[0]) / DEG) % 360 + 360) % 360,
    decDeg: Math.asin(Math.max(-1, Math.min(1, v[2] / r))) / DEG,
  }
}

/** Dawn–dusk RAAN: Ω = α_sun + 15°(LTAN − 12) — the Ω that MAXIMISES β.
 *  LTAN 18:00 → α + 90° (dusk ascending node), LTAN 06:00 → α − 90°. */
export function raanForLtan(sunRaDeg: number, ltanHours: number): number {
  return ((sunRaDeg + 15 * (ltanHours - 12)) % 360 + 360) % 360
}

/** Sun elevation above the orbit plane:
 *    sin β = sin i · cos δ · sin(Ω − α_sun) + cos i · sin δ
 *  |β| = 90° ⇔ the plane contains the terminator. Signed by the right-hand
 *  orbit normal, so a dawn plane (LTAN 06) reports β negative with the same
 *  magnitude as its dusk twin; the tilt off the terminator is 90° − |β| for
 *  both. At the demo epoch (δ = +11.5°) a dusk plane at i = 97.4° gives
 *  β = 71.1°, NOT 90° — that ~19° is real seasonal geometry. */
export function betaDeg(
  incDeg: number, raanDeg: number, sunRaDeg: number, sunDecDeg: number,
): number {
  const s = Math.sin(incDeg * DEG) * Math.cos(sunDecDeg * DEG)
      * Math.sin((raanDeg - sunRaDeg) * DEG)
    + Math.cos(incDeg * DEG) * Math.sin(sunDecDeg * DEG)
  return Math.asin(Math.max(-1, Math.min(1, s))) / DEG
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/**
 * The dates in the year after `jd` when |β| would reach 90° for a dawn–dusk
 * plane at inclination `incDeg` — i.e. when the sun's declination reaches
 * δ* = −(i − 90°). Empty when the sun never gets there (|δ*| > obliquity).
 * Day-resolution scan for sign changes, then bisection; ~2 entries.
 */
export function terminatorDates(incDeg: number, jd: number): string[] {
  const target = -(incDeg - 90)
  if (!Number.isFinite(jd) || Math.abs(target) > OBLIQUITY_DEG) return []
  const f = (d: number) => {
    const a = sunAngles(sunUnitApprox(jd + d))
    return a ? a.decDeg - target : NaN
  }
  const out: string[] = []
  let prev = f(0)
  for (let d = 1; d <= 366 && out.length < 2; d += 1) {
    const cur = f(d)
    if (!Number.isFinite(prev) || !Number.isFinite(cur)) { prev = cur; continue }
    if ((prev <= 0) !== (cur <= 0)) {
      let lo = d - 1, hi = d
      for (let k = 0; k < 24; k += 1) {
        const mid = (lo + hi) / 2
        if ((f(lo) <= 0) === (f(mid) <= 0)) lo = mid; else hi = mid
      }
      const t = new Date((jd + (lo + hi) / 2 - 2440587.5) * 86_400_000)
      out.push(`${t.getUTCDate()} ${MONTHS[t.getUTCMonth()]}`)
    }
    prev = cur
  }
  return out
}
