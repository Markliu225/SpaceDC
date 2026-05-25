import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { earthFrag, earthVert } from './shaders'

/**
 * Procedural day/night Earth. Sun direction is a uniform, animated slowly
 * so the terminator drifts as the camera rotates. The night side has a
 * subtle "city light" twinkle driven by uTime.
 */
export function Earth() {
  const matRef = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(
    () => ({
      uSunDir: { value: new THREE.Vector3(1, 0.2, 0.4).normalize() },
      uTime:   { value: 0 },
    }),
    [],
  )

  useFrame((_state, dt) => {
    if (!matRef.current) return
    const t = (matRef.current.uniforms.uTime.value += dt)
    // Slow sun drift — one revolution every ~90 s.
    const omega = (Math.PI * 2) / 90
    const sun = matRef.current.uniforms.uSunDir.value as THREE.Vector3
    sun.set(Math.cos(omega * t), 0.25, Math.sin(omega * t)).normalize()
  })

  return (
    <mesh>
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
