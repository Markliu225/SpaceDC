import { useMemo } from 'react'
import * as THREE from 'three'
import { atmoFrag, atmoVert } from './shaders'
import { colors } from '../../../design/tokens'

/**
 * Atmosphere shell — bigger sphere rendered back-side, additive blend,
 * Fresnel emission. Sits just outside the earth surface (radius 1.05).
 */
export function Atmosphere() {
  const uniforms = useMemo(
    () => ({
      uColor:     { value: new THREE.Color(colors.accent) },
      uIntensity: { value: 1.1 },
    }),
    [],
  )

  return (
    <mesh>
      <sphereGeometry args={[1.06, 64, 64]} />
      <shaderMaterial
        uniforms={uniforms}
        vertexShader={atmoVert}
        fragmentShader={atmoFrag}
        transparent
        blending={THREE.AdditiveBlending}
        side={THREE.BackSide}
        depthWrite={false}
      />
    </mesh>
  )
}
