import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { colors } from '../../../design/tokens'
import { useSunDisplay } from './sky'

/**
 * TerminatorRing — the day/night boundary of the rendered Earth, drawn as a
 * great circle on the limb.
 *
 * This is a RULER, not a spacecraft. Its plane normal is the broadcast sun
 * direction — the same vector `Earth.tsx` lights the globe with — so the circle
 * traces exactly where the shader's terminator falls. A dawn–dusk SSO design
 * should land its shells ON this circle; a Walker i=53° design visibly should
 * not. It renders for EVERY constellation so the comparison is always
 * available — but only once a real sun vector has arrived; with the sky frame
 * unknown the ring is not drawn at all.
 *
 * Deliberately subtle: a 1 px line (WebGL ignores `linewidth`, which is what we
 * want here), `text.lo` at 0.35 alpha, no glow. Its peak luminance is roughly
 * 0.15 after the alpha, far below the composer's 0.95 bloom threshold, so it
 * contributes nothing to bloom. Depth testing is left ON, so the far half is
 * occluded by the globe and the line reads as drawn on the sphere.
 *
 * (File keeps its historical name — it used to hold a decorative dawn–dusk
 * orbit ribbon that spun on the render clock.)
 */

// r = 1.0 is the Earth's limb; the extra 2 mm of scene units clears the
// 96-segment sphere's facets so the line does not z-fight the surface.
const TERMINATOR_RADIUS = 1.002
const SEGMENTS = 256

/** Name on the three.js object so a review can assert the ring exists —
 *  `data-testid` is not a thing inside a WebGL canvas. */
export const TERMINATOR_OBJECT_NAME = 'terminator-reference'

export function TerminatorRing() {
  const ref = useRef<THREE.LineLoop>(null!)
  const { sun, live } = useSunDisplay()

  // Unit circle in the XY plane — its normal is +Z, which we then rotate onto
  // the sun direction every frame. Building it once keeps the per-frame cost at
  // a single quaternion.
  const geom = useMemo(() => {
    const pos = new Float32Array(SEGMENTS * 3)
    for (let i = 0; i < SEGMENTS; i++) {
      const th = (i / SEGMENTS) * Math.PI * 2
      pos[i * 3 + 0] = Math.cos(th) * TERMINATOR_RADIUS
      pos[i * 3 + 1] = Math.sin(th) * TERMINATOR_RADIUS
      pos[i * 3 + 2] = 0
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    return g
  }, [])
  useEffect(() => () => geom.dispose(), [geom])

  const planeNormal = useMemo(() => new THREE.Vector3(0, 0, 1), [])

  useFrame(() => {
    if (ref.current) ref.current.quaternion.setFromUnitVectors(planeNormal, sun)
  })

  // No sky frame yet ⇒ no known terminator. Draw nothing rather than a ring
  // around an invented sun; the globe is flat-lit to match (see shaders.ts).
  if (!live) return null

  return (
    <lineLoop ref={ref} name={TERMINATOR_OBJECT_NAME} geometry={geom}>
      <lineBasicMaterial
        color={colors.text.lo}
        transparent
        opacity={0.35}
        depthWrite={false}
        toneMapped={false}
      />
    </lineLoop>
  )
}
