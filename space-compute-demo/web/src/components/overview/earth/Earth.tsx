import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { earthFrag, earthVert } from './shaders'
import { useSunDisplay } from './sky'

/**
 * Procedural day/night Earth.
 *
 * THE PLANET SPINS, THE LIGHT DOES NOT. The mesh is rotated by the broadcast
 * GMST about display +Y (= ECI +Z, the north pole), so the surface carries a
 * defined longitude; `uSunDir` is the broadcast sun in display space and stays
 * inertial. The shader lights in world space (`vNormalW` goes through
 * `modelMatrix`), so the terminator falls where the sky frame says it does —
 * the same vector the terminator reference ring and the orbit rings are drawn
 * against.
 *
 * The spin is sampled with `gmstNow()` INSIDE this useFrame, not read off a
 * render-time prop: the backend broadcasts at 1 Hz, so the raw value holds
 * still for ~60 frames and then steps 0.2507° — visible as a stutter, not a
 * rotation. `hooks/gmstClock` anchors on each broadcast and fills the gap at
 * the true sidereal rate, and because it is sampled in the render loop rather
 * than through React state, the smoothing costs this tree zero re-renders.
 *
 * Before the first broadcast the sky frame is UNKNOWN, and `uSunKnown = 0`
 * shows the globe evenly lit rather than drawing a made-up terminator.
 *
 * The only animated uniform is `uTime`, which drives the faint night-side city
 * twinkle; it carries no physics.
 */
export function Earth() {
  const matRef  = useRef<THREE.ShaderMaterial>(null!)
  const meshRef = useRef<THREE.Mesh>(null!)
  const { sun, gmstNow, live } = useSunDisplay()

  const uniforms = useMemo(
    () => ({
      uSunDir:   { value: sun.clone() },
      uTime:     { value: 0 },
      uSunKnown: { value: 0 },
    }),
    // Built once and then written per frame in useFrame — a new `sun` from the
    // broadcast must not rebuild the material (that would recompile the shader
    // every packet). Intentionally empty deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  useFrame((_state, dt) => {
    const mat = matRef.current
    if (mat) {
      mat.uniforms.uTime.value += dt
      mat.uniforms.uSunKnown.value = live ? 1 : 0
      ;(mat.uniforms.uSunDir.value as THREE.Vector3).copy(sun)
    }
    if (meshRef.current) meshRef.current.rotation.y = gmstNow()
  })

  return (
    <mesh ref={meshRef} name="earth-globe">
      <sphereGeometry args={[1, 96, 96]} />
      <shaderMaterial
        ref={matRef}
        uniforms={uniforms}
        vertexShader={earthVert}
        fragmentShader={earthFrag}
      />
    </mesh>
  )
}
