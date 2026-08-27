import { useMemo } from 'react'
import * as THREE from 'three'
import { colors } from '../../../design/tokens'

const RING_COUNT = 24
const RING_RADIUS = 1.55   // earth radius is 1 in scene units; ~ +0.55 above surface
const RING_RADIAL_THICKNESS = 0.012

/**
 * 24 colored orbit ribbons. Each ribbon is a TubeGeometry around a
 * Catmull-Rom spline that traces a great-circle in a tilted plane.
 * Ribbon hue cycles through the 6-hue palette (4 ribbons per hue).
 * Material is transparent, normal-blended at a steady 0.6 opacity so the
 * bouquet reads as matte lines rather than additive neon tubing.
 */
export function OrbitRibbons() {
  const ribbons = useMemo(() => {
    return Array.from({ length: RING_COUNT }, (_, i) => {
      const hueIdx = i % 6
      const color = new THREE.Color(colors.ribbons[hueIdx])
      // Spread inclinations + RAAN so the constellation reads as a bouquet.
      const inclination = (50 + (i % 4) * 8) * (Math.PI / 180) // 50..74 deg
      const raan = ((i / RING_COUNT) * 360) * (Math.PI / 180)  // 0..360 deg

      // Generate the orbit polyline in its own frame, then transform.
      const pts: THREE.Vector3[] = []
      const N = 128
      for (let k = 0; k <= N; k++) {
        const theta = (k / N) * Math.PI * 2
        const x = Math.cos(theta) * RING_RADIUS
        const y = Math.sin(theta) * RING_RADIUS
        pts.push(new THREE.Vector3(x, y, 0))
      }
      // Tilt by inclination around X, rotate by RAAN around Z.
      const incQ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), inclination)
      const raaQ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), raan)
      const orient = new THREE.Quaternion().multiplyQuaternions(raaQ, incQ)
      for (const p of pts) p.applyQuaternion(orient)

      const curve = new THREE.CatmullRomCurve3(pts, true, 'catmullrom', 0.5)
      const geom = new THREE.TubeGeometry(curve, 200, RING_RADIAL_THICKNESS, 6, true)
      return {
        index: i,
        hueIdx,
        color,
        geom,
        orient,
      }
    })
  }, [])

  return (
    <group>
      {ribbons.map((r) => (
        <mesh key={r.index} geometry={r.geom}>
          <meshBasicMaterial
            color={r.color}
            transparent
            opacity={0.6}
            blending={THREE.NormalBlending}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  )
}

/** Return the world-space position of `sat`'s sub-point on its orbit ring. */
export function ribbonPosition(satIndex: number, satTotal: number, sims: number): THREE.Vector3 {
  const ringIdx = satIndex % RING_COUNT
  const inclination = (50 + (ringIdx % 4) * 8) * (Math.PI / 180)
  const raan        = ((ringIdx / RING_COUNT) * 360) * (Math.PI / 180)
  // Spread the satellite phases around the ring; same-ring sats are 360/(satTotal/RING_COUNT) apart.
  const phase = (satIndex / satTotal) * Math.PI * 2 + sims * 0.04
  const r = RING_RADIUS
  const local = new THREE.Vector3(Math.cos(phase) * r, Math.sin(phase) * r, 0)
  const incQ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), inclination)
  const raaQ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), raan)
  return local.applyQuaternion(incQ).applyQuaternion(raaQ)
}
