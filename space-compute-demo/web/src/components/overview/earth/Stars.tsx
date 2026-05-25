import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { starsFrag, starsVert } from './shaders'

const STAR_COUNT = 2000
const SHELL_RADIUS = 90

/**
 * 2000 random points on a large sphere. Each gets a random `aSeed` used by
 * the shader for size variation + twinkle phase. Additive blending.
 */
export function Stars() {
  const matRef = useRef<THREE.ShaderMaterial>(null!)
  const geometry = useMemo(() => {
    const positions = new Float32Array(STAR_COUNT * 3)
    const seeds     = new Float32Array(STAR_COUNT)
    for (let i = 0; i < STAR_COUNT; i++) {
      // Uniform on a sphere via Marsaglia.
      let x = 0, y = 0, z = 0, s2 = 2
      while (s2 >= 1) {
        x = Math.random() * 2 - 1
        y = Math.random() * 2 - 1
        s2 = x * x + y * y
      }
      const t = 2 * Math.sqrt(1 - s2)
      const px = x * t, py = y * t, pz = 1 - 2 * s2
      positions[i * 3 + 0] = px * SHELL_RADIUS
      positions[i * 3 + 1] = py * SHELL_RADIUS
      positions[i * 3 + 2] = pz * SHELL_RADIUS
      seeds[i] = Math.random()
      // suppress unused-z complaint from older lints
      z++
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    g.setAttribute('aSeed',    new THREE.BufferAttribute(seeds, 1))
    return g
  }, [])

  const uniforms = useMemo(() => ({ uTime: { value: 0 } }), [])

  useFrame((_state, dt) => {
    if (matRef.current) matRef.current.uniforms.uTime.value += dt
  })

  return (
    <points geometry={geometry}>
      <shaderMaterial
        ref={matRef}
        uniforms={uniforms}
        vertexShader={starsVert}
        fragmentShader={starsFrag}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}
