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
 */

import { useMemo } from 'react'
import { Vector3 } from 'three'
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
  /** Greenwich mean sidereal time, radians, from the broadcast. Apply as
   *  `mesh.rotation.y = gmstRad` (display +Y is ECI +Z, so +gmst about +Y
   *  advances right ascension — the correct sense). 0 until the first packet. */
  gmstRad: number
  /** True once a real sun vector has been received this session. False means
   *  "sky unknown": draw no terminator and claim no day/night boundary. */
  live: boolean
}

export function useSunDisplay(): SkyView {
  const { sunDisplay, gmstRad } = useSkyFrame()
  return useMemo(() => {
    // `useSkyFrame` already holds the last value the session saw, so a null
    // here means nothing has EVER arrived — not that a packet was missed.
    const live = sunDisplay !== null
    const sun = new Vector3(...(sunDisplay ?? UNKNOWN_SUN_DISPLAY))
    if (sun.lengthSq() > 1e-12) sun.normalize()
    else sun.set(...UNKNOWN_SUN_DISPLAY)
    return { sun, gmstRad, live }
  }, [sunDisplay, gmstRad])
}
