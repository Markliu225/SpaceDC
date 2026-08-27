import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { colors } from '../../../design/tokens'

const RADIUS = 1.72      // just OUTSIDE the inclined-ribbon bouquet so it reads
const THICK  = 0.032     // bold — clearly the special terminator orbit

/**
 * Dawn-Dusk (terminator) orbit — a Sun-synchronous orbit whose orbital plane is
 * perpendicular to the Sun line, so the ring rides the day/night terminator
 * great circle and a satellite on it is always in sunlight. The Sun drifts with
 * the same omega as Earth.tsx; the ring re-orients every frame so its plane
 * normal stays locked to the Sun direction. Rendered amber (ribbon palette)
 * + steady to stand apart from the 24 inclined ribbons.
 */
export function DawnDuskOrbit() {
  const meshRef = useRef<THREE.Mesh>(null!)
  const geom = useMemo(() => {
    const pts: THREE.Vector3[] = []
    const N = 128
    for (let k = 0; k <= N; k++) {
      const th = (k / N) * Math.PI * 2
      pts.push(new THREE.Vector3(Math.cos(th) * RADIUS, Math.sin(th) * RADIUS, 0))
    }
    const curve = new THREE.CatmullRomCurve3(pts, true, 'catmullrom', 0.5)
    return new THREE.TubeGeometry(curve, 240, THICK, 8, true)
  }, [])

  const up  = useMemo(() => new THREE.Vector3(0, 0, 1), [])
  const sun = useMemo(() => new THREE.Vector3(), [])
  const q   = useMemo(() => new THREE.Quaternion(), [])

  useFrame((state) => {
    if (!meshRef.current) return
    const omega = (Math.PI * 2) / 90              // matches Earth.tsx sun drift
    const t = state.clock.elapsedTime
    sun.set(Math.cos(omega * t), 0.25, Math.sin(omega * t)).normalize()
    // Ring's default normal is +Z; rotate +Z onto the Sun direction so the ring
    // lies in the plane ⊥ Sun = the terminator great circle.
    q.setFromUnitVectors(up, sun)
    meshRef.current.quaternion.copy(q)
  })

  return (
    <mesh ref={meshRef} geometry={geom}>
      <meshBasicMaterial
        color={colors.ribbons[2]}
        transparent
        opacity={0.8}
        blending={THREE.NormalBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </mesh>
  )
}
