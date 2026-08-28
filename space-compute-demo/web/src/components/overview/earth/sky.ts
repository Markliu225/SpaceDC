/**
 * sky — the Overview globe's view of the broadcast sky frame.
 *
 * One sun vector is authoritative for the whole scene: the backend's
 * `sun_unit_teme`, in the same frame and at the same instant as the fleet ECI
 * it ships with, mapped through the SAME `eciToDisplay` transform the orbit
 * rings use (`hooks/useSkyFrame.ts` does that mapping). That is what makes
 * "the dawn–dusk ring lies on the rendered terminator" true by construction
 * rather than by coincidence.
 *
 * Nothing here animates or invents the sun. `useSkyFrame` already holds the
 * last value the session ever saw, so a dropped socket freezes the sky instead
 * of teleporting it; this wrapper adapts that to the three.js scene by handing
 * back a `Vector3` and by reporting `live`, which every consumer must honour:
 * with `live === false` there is no known terminator and none may be drawn.
 *
 * The planet's SPIN is the one thing that must not be sampled per broadcast:
 * `useSkyFrame().gmstRad` steps once per 1 Hz backend tick, so a mesh driven
 * straight from it stands still for ~60 frames and then jumps 0.25 deg. This
 * view therefore hands out `gmstNow()` — the same broadcast angle advanced to
 * the calling frame by `hooks/gmstClock` — instead of a number that is already
 * stale by the time it is drawn. Still the broadcast value; just not a stale
 * one.
 */

import { useMemo } from 'react'
import { Vector3 } from 'three'
import { gmstNow } from '../../../hooks/gmstClock'
import { useSkyFrame } from '../../../hooks/useSkyFrame'

/** Direction the `sun` vector holds before the first broadcast. It is NOT a
 *  sun position and nothing may light or align against it — `live` is false
 *  for as long as it is in force, and consumers render their "sun unknown"
 *  state instead. It exists only so the vector is always a valid unit vector. */
const UNKNOWN_SUN_DISPLAY: [number, number, number] = [1, 0, 0]

export interface SkyView {
  /** Unit sun direction in display space. A fresh vector per broadcast — read
   *  it from the `useFrame` closure (which is re-registered on every render)
   *  rather than caching its components. Meaningless while `live` is false. */
  sun: Vector3
  /** Greenwich mean sidereal time, radians in [0, 2π), from the broadcast and
   *  advanced to the instant of the call. SAMPLE IT PER FRAME from inside a
   *  `useFrame` callback — `mesh.rotation.y = gmstNow()` (display +Y is ECI +Z,
   *  so +gmst about +Y advances right ascension — the correct sense). Never
   *  cache the number across frames; that reintroduces the 1 Hz stutter this
   *  replaced. 0 until the first packet. */
  gmstNow: () => number
  /** True once a real sun vector has been received this session. False means
   *  "sky unknown": draw no terminator and claim no day/night boundary. */
  live: boolean
}

export function useSunDisplay(): SkyView {
  const { sunDisplay } = useSkyFrame()
  return useMemo(() => {
    // `useSkyFrame` already holds the last value the session saw, so a null
    // here means nothing has EVER arrived — not that a packet was missed.
    const live = sunDisplay !== null
    const sun = new Vector3(...(sunDisplay ?? UNKNOWN_SUN_DISPLAY))
    if (sun.lengthSq() > 1e-12) sun.normalize()
    else sun.set(...UNKNOWN_SUN_DISPLAY)
    // `gmstNow` is a stable module function, so it is not a memo dependency —
    // the spin is read from it per frame, not rebuilt per packet.
    return { sun, gmstNow, live }
  }, [sunDisplay])
}
