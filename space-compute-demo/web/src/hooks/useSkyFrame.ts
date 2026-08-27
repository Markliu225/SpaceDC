import { useEffect, useMemo } from 'react'
import { useDemoStore } from '../store/demoStore'
import { eciToDisplay } from '../components/twin/orbitMath'

/**
 * useSkyFrame — the ONE client-side source of the sky frame for every 3D view.
 *
 * Both Earth renderers (the Overview globe and the Twin orbit views) must light
 * the planet from the SAME sun vector the backend designed the orbits against,
 * otherwise a dawn–dusk SSO ring lands somewhere off the visible day/night
 * boundary and the feature looks broken even though the physics is right.
 *
 * The backend broadcasts, on every fleet tick and in exactly the frame and at
 * exactly the instant of the ECI km positions in the same packet:
 *
 *   constellation.sun_unit_teme : [x, y, z] unit, TEME, Earth → Sun
 *   constellation.gmst_rad      : Greenwich mean sidereal time, radians
 *
 * Nothing here invents either value. There is no hard-coded sun direction and
 * no from-zero GMST ramp anywhere in the client any more — the previous
 * `SUN_DIR_ECI = [0.648, -0.648, 0.398]` was 141.3° away from the true sun at
 * the demo epoch, and a GMST starting at 0 was a constant 151.29° of longitude
 * error against the true 151.287° at mission start.
 *
 * Degradation, in order of preference:
 *   1. live broadcast value;
 *   2. the last value this session ever saw (module cache below) — the sky does
 *      not teleport when the socket blips, and a remounted view picks the frame
 *      back up immediately;
 *   3. `null` sun / `0` GMST when nothing has ever arrived. Callers must render
 *      an explicitly "sun unknown" state for a null sun — never substitute a
 *      constant, which is the bug this hook exists to kill.
 *
 * NOTE ON SMOOTHNESS: `gmstRad` steps at the 1 Hz broadcast rate rather than
 * gliding on the frame clock. At the demo's 60× time scale that is 0.25° per
 * step — below the perceptual floor on an untextured globe — and it is worth
 * far more to have the value be *true* than to have it be smooth. Do not
 * re-introduce a locally integrated clock here.
 */

export interface SkyFrame {
  /** Sun unit vector in Three.js display coords (Y-up), or null if unknown. */
  sunDisplay: [number, number, number] | null
  /** Sun unit vector in ECI/TEME (Z = north pole), or null if unknown. */
  sunEci: [number, number, number] | null
  /** Broadcast GMST in radians, wrapped to [0, 2π). 0 until the first packet. */
  gmstRad: number
}

const TWO_PI = Math.PI * 2

// Session-wide last-known sky. Shared by every hook instance so a view that
// mounts mid-session (or between packets) starts from the real frame instead
// of a null one. Read during render, written only from an effect (so the hook
// itself stays pure); it only ever holds values that passed validation.
const lastKnown: { sunEci: [number, number, number] | null; gmstRad: number } = {
  sunEci: null,
  gmstRad: 0,
}

function pick(obj: unknown, key: string): unknown {
  if (!obj || typeof obj !== 'object') return undefined
  return (obj as Record<string, unknown>)[key]
}

/** Validate + normalise a broadcast 3-vector. The backend's field default is
 *  (0, 0, 0), so a zero-length vector means "not filled yet", not "sun here". */
function readUnitVec3(v: unknown): [number, number, number] | null {
  if (!Array.isArray(v) || v.length < 3) return null
  const [x, y, z] = v as unknown[]
  if (typeof x !== 'number' || typeof y !== 'number' || typeof z !== 'number') return null
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null
  const n = Math.hypot(x, y, z)
  if (n < 1e-9) return null
  return [x / n, y / n, z / n]
}

function readAngle(v: unknown): number | null {
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  return ((v % TWO_PI) + TWO_PI) % TWO_PI
}

export function useSkyFrame(): SkyFrame {
  const snap = useDemoStore((s) => s.lastState?.constellation)

  const frame = useMemo<SkyFrame>(() => {
    // `sun_unit_teme` is the contract key (TERMINATOR_SPEC §1.3); `sun_eci_unit`
    // is the alias the earlier SSO_SPEC §6.1 draft used — accept both so a
    // naming slip degrades to nothing worse than the old behaviour.
    const sunEci = readUnitVec3(pick(snap, 'sun_unit_teme'))
      ?? readUnitVec3(pick(snap, 'sun_eci_unit'))
      ?? lastKnown.sunEci
    const gmstRad = readAngle(pick(snap, 'gmst_rad')) ?? lastKnown.gmstRad

    return {
      sunEci,
      // eciToDisplay is a signed axis permutation, so it preserves unit length.
      sunDisplay: sunEci ? eciToDisplay(sunEci) : null,
      gmstRad,
    }
  }, [snap])

  useEffect(() => {
    lastKnown.sunEci = frame.sunEci
    lastKnown.gmstRad = frame.gmstRad
  }, [frame])

  return frame
}
