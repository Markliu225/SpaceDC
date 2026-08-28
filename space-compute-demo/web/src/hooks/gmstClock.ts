/**
 * gmstClock — the BROADCAST Greenwich sidereal angle, advanced to THIS frame.
 *
 * `useSkyFrame` hands out the raw broadcast `gmst_rad`, which steps once per
 * backend tick (state_engine.TICK_HZ = 1.0). Assigning that straight to a
 * transform makes the planet sit perfectly still for ~60 frames and then jump:
 * at the demo's 60x time scale one step is 60·2π/86164.0905 = 4.375e-3 rad
 * (0.2507°), which reads as a stutter rather than a spin. This module keeps the
 * broadcast value authoritative and fills the gaps between packets at the true
 * sidereal rate, so a full revolution still takes 86164.0905/60 = 1436.1 wall
 * seconds (23.9 min) — the same 60 fps × 1436 s the backend would draw.
 *
 * It is the client-side twin of the Omniverse extension's `_gmst_now`
 * (ov_app/exts/space.demo.scene/.../extension.py), and it mirrors
 * `useSmoothSimTime`'s structure: anchor on every broadcast, extrapolate on the
 * wall clock between them, clamp the extrapolation, and freeze while paused.
 *
 * NOT A HOOK, deliberately. All four consumers are react-three-fiber objects
 * that already run a `useFrame` callback, so they sample this function inside
 * that loop and write the result to a transform — no React state, no re-render
 * per animation frame. (`useSmoothSimTime` drives state at frame rate and
 * `Satellites.tsx` already uses it in the same scene; a second per-frame state
 * hook there would double the churn for a value nothing but a matrix reads.)
 *
 * Nothing here invents GMST. Before the first packet it returns 0 and stays
 * there — there is no from-zero ramp, which is the bug `useSkyFrame`'s header
 * exists to warn about. It only ever extrapolates a value the backend sent.
 */

import { useDemoStore } from '../store/demoStore'
import { useTelemetryStore } from '../store/useTelemetryStore'
import { SIDEREAL_DAY_S } from '../components/twin/orbitMath'

const TWO_PI = Math.PI * 2

/** GMST advances 2π per sidereal day of REAL time: 7.2921159e-5 rad/s at 1x. */
const GMST_RATE_1X = TWO_PI / SIDEREAL_DAY_S

/** Used only until the store knows the backend's scale. Mirrors
 *  services/timebase.TIME_SCALE; the live value is read from
 *  `constellationDetail.time_scale` on every sample, so raising the backend's
 *  TIME_SCALE speeds the planet up without a client change. */
const FALLBACK_TIME_SCALE = 60

/** Same clamp as useSmoothSimTime: never run more than ~2.5 broadcast
 *  intervals past the anchor, so a hung backend or a dropped socket coasts for
 *  a moment and then holds instead of spinning the planet away from truth. */
const MAX_EXTRAP_S = 2.5

/** A re-anchor correction is bled off at this fraction of the current spin
 *  rate, never applied as a step: the planet may briefly run at 0.5x or 1.5x
 *  while it converges, but it never jumps and never reverses.
 *
 *  The bleed runs on wall time, so it finishes while PAUSED too. Pause is
 *  still a freeze — the extrapolation contributes nothing — but a packet that
 *  was already in flight when the user hit Pause still re-anchors, and the
 *  planet then settles the last fraction of a broadcast step onto the true
 *  angle rather than holding a stale extrapolated one. That settle is bounded
 *  by one broadcast step (0.2507° at time_scale 60), runs at half rate, and
 *  leaves the paused globe showing exactly the broadcast GMST. */
const CORRECTION_RATE_FRAC = 0.5

/** Corrections worth more than this many sim-seconds of rotation are not
 *  packet jitter — they are a reset, a preset swap or a new mission epoch, and
 *  those must snap onto truth exactly as useSmoothSimTime's anchor does. */
const MAX_DAMPED_DESYNC_S = 10

interface Anchor {
  /** Angle this anchor is pinned to, radians in [0, 2π). */
  gmst: number
  /** performance.now() at which it was taken. */
  wall: number
  /** Signed correction still to bleed off (drawn angle − anchor angle). */
  corr: number
}

let anchor: Anchor | null = null
/** Last broadcast value folded in, so Pause/Resume re-anchoring (which
 *  overwrites `anchor.gmst`) can't be mistaken for a new packet. */
let lastBroadcast: number | null = null
/** Previous `running`, to catch the Play/Pause edges. null = never sampled. */
let lastRunning: boolean | null = null

/** Wrap into [0, 2π). */
function wrap(a: number): number {
  return ((a % TWO_PI) + TWO_PI) % TWO_PI
}

/** Wrap into [-π, π) — the SHORT way round, so a difference measured across
 *  the 2π seam reads as the small angle it is. */
function wrapSigned(a: number): number {
  return wrap(a + Math.PI) - Math.PI
}

/** Radians of GMST per wall second, at the backend's current time scale. */
function rateRadPerS(): number {
  const ts = useTelemetryStore.getState().constellationDetail?.time_scale
  const scale = typeof ts === 'number' && Number.isFinite(ts) && ts > 0
    ? ts
    : FALLBACK_TIME_SCALE
  return scale * GMST_RATE_1X
}

/** The latest broadcast angle, validated and wrapped, or null if no packet has
 *  ever carried one. `lastState` is never cleared on socket close, so a drop
 *  keeps returning the last real value rather than null. */
function broadcastGmst(): number | null {
  const c = useDemoStore.getState().lastState?.constellation as
    { gmst_rad?: unknown } | undefined
  const g = c?.gmst_rad
  if (typeof g !== 'number' || !Number.isFinite(g)) return null
  return wrap(g)
}

/** The angle an anchor puts on screen at `now` (unwrapped by at most one
 *  clamp's worth). Pure — two calls in the same rAF differ only by the
 *  microseconds between them (measured: ~1e-6 rad), so the day/night sphere
 *  and the lat/lon grid drawn over it agree to far below one pixel. */
function sample(a: Anchor, now: number, rate: number, running: boolean): number {
  const dt = (now - a.wall) / 1000
  const elapsed = running ? Math.min(MAX_EXTRAP_S, dt) : 0
  const step = rate * CORRECTION_RATE_FRAC * Math.max(0, dt)
  const corr = a.corr > 0
    ? Math.max(0, a.corr - step)
    : Math.min(0, a.corr + step)
  return a.gmst + elapsed * rate + corr
}

/**
 * The broadcast GMST, in radians wrapped to [0, 2π), advanced to this instant.
 * Call it from a `useFrame` callback and assign it to `rotation.y` (display +Y
 * is ECI +Z, so +GMST advances right ascension — the correct sense).
 *
 * Returns 0 until the first packet carrying `gmst_rad` arrives.
 */
export function gmstNow(): number {
  const now = performance.now()
  const running = useTelemetryStore.getState().running
  const g = broadcastGmst()

  // No packet has ever arrived: the sky frame is unknown, so hold at 0 rather
  // than ramping a made-up angle. (A LATER null — a packet with the field
  // missing — keeps the existing anchor coasting instead.)
  if (g === null && anchor === null) return 0

  const rate = rateRadPerS()

  if (anchor === null) {
    anchor = { gmst: g as number, wall: now, corr: 0 }
    lastBroadcast = g
    lastRunning = running
    return anchor.gmst
  }

  // Play/Pause edge: re-anchor onto the angle currently drawn. Pausing folds
  // the extrapolation done so far into the anchor instead of dropping it (a
  // drop would step the planet back by up to one broadcast interval), and
  // resuming restarts the clamp from there. Neither edge moves the planet.
  if (lastRunning !== null && running !== lastRunning) {
    anchor = { gmst: wrap(sample(anchor, now, rate, lastRunning)), wall: now, corr: 0 }
  }
  lastRunning = running

  // Re-anchor on every broadcast. The new packet is truth; the difference
  // against what is on screen is packet jitter (we extrapolated over a 1.04 s
  // gap, or coasted through a late one) and is bled off over the following
  // frames rather than applied as a step. A difference too large to be jitter
  // is a genuine discontinuity — reset, preset swap, new epoch — and snaps.
  if (g !== null && g !== lastBroadcast) {
    const shown = sample(anchor, now, rate, running)
    const delta = wrapSigned(shown - g)
    const limit = rate * MAX_DAMPED_DESYNC_S
    anchor = { gmst: g, wall: now, corr: Math.abs(delta) <= limit ? delta : 0 }
    lastBroadcast = g
  }

  return wrap(sample(anchor, now, rate, running))
}
