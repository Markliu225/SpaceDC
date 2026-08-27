import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { colors } from '../../../design/tokens'
import { useConstellationRings, type Vec3 } from './ringData'

/**
 * OrbitRibbons — one ribbon per orbital plane of the ACTIVE constellation,
 * built from the backend's propagated ECI samples (`rings_eci_km`, falling back
 * to the legacy single `ring_eci_km` under the documented Walker plane
 * rotation). Nothing here is synthesised: with no constellation detail loaded
 * the group renders empty rather than showing a decorative bouquet.
 *
 * Ribbons are INERTIAL — they sit outside the GMST-spun Earth mesh, because an
 * orbit plane does not turn with the planet. For an SSO design every ribbon
 * shares the dawn–dusk RAAN, so they stack as concentric rings on the
 * terminator reference circle; for a Walker design they fan out. That contrast
 * is the point of the view.
 *
 * Look is unchanged from the decorative version: TubeGeometry, the 6-hue ribbon
 * palette, normal-blended at a steady 0.6 opacity so the set reads as matte
 * lines rather than additive neon tubing.
 */

// Tube radius in scene units (Earth radius = 1). Real LEO shells sit ~0.08
// above the surface and neighbouring SSO shells can be ~0.03 apart, so the
// tube has to be thin enough for two shells to stay visibly separate.
const RIBBON_THICKNESS = 0.007
const TUBULAR_SEGMENTS = 128

export function OrbitRibbons() {
  const { rings } = useConstellationRings()

  const ribbons = useMemo(
    () => rings.map((ring, k) => ({
      k,
      color: colors.ribbons[k % colors.ribbons.length],
      geom: tubeFromRing(ring),
    })),
    [rings],
  )

  // <primitive> geometries are not auto-disposed by react-three-fiber.
  useEffect(() => () => { ribbons.forEach((r) => r.geom.dispose()) }, [ribbons])

  return (
    <group name="orbit-ribbons">
      {ribbons.map((r) => (
        // Key on the geometry too: <primitive> does not support swapping its
        // object in place, so a redesign must produce a fresh element.
        <mesh key={`${r.k}:${r.geom.uuid}`}>
          <primitive object={r.geom} attach="geometry" />
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

function tubeFromRing(ring: Vec3[]): THREE.TubeGeometry {
  const pts = ring.map(([x, y, z]) => new THREE.Vector3(x, y, z))
  const curve = new THREE.CatmullRomCurve3(pts, true, 'catmullrom', 0.5)
  return new THREE.TubeGeometry(curve, TUBULAR_SEGMENTS, RIBBON_THICKNESS, 4, true)
}
