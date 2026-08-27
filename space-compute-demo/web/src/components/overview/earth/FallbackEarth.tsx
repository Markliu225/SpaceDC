import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import { Suspense, useEffect } from 'react'
import { Earth } from './Earth'
import { Atmosphere } from './Atmosphere'
import { Stars } from './Stars'
import { OrbitRibbons } from './OrbitRibbons'
import { DawnDuskOrbit } from './DawnDuskOrbit'
import { Satellites } from './Satellites'
import { colors } from '../../../design/tokens'

/**
 * FallbackEarth — full Three.js scene rendered when the Omniverse stream
 * isn't available. Per design brief:
 *
 *   - Procedural day/night Earth (shader; sun direction drifts)
 *   - Atmosphere Fresnel shell (additive, accent blue, intensity 1.1)
 *   - 24 colored orbit ribbons (TubeGeometry, normal-blended, steady opacity)
 *   - Satellite billboards (radial-gradient sprite, steady; selected one pulses)
 *   - 2000 star points (faint twinkle, additive)
 *   - Bloom (intensity 0.15, radius 0.3, threshold 0.95) — only the brightest cores bloom
 *   - Auto camera orbit (1 rev / 90s) until the user drags
 */
export function FallbackEarth() {
  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}
      camera={{ position: [0, 0.6, 3.4], fov: 38 }}
      style={{
        position: 'absolute',
        inset: 0,
        background: colors.bg.inset,
      }}
    >
      <ClearColor />
      <ambientLight intensity={0.18} />
      <Suspense fallback={null}>
        <Stars />
        <Earth />
        <Atmosphere />
        <OrbitRibbons />
        <DawnDuskOrbit />
        <Satellites />
      </Suspense>
      <OrbitControls
        autoRotate
        autoRotateSpeed={0.4 /* ~ 1 rev / 90s at speed 0.4 */}
        enablePan={false}
        enableZoom
        minDistance={2.2}
        maxDistance={6}
        rotateSpeed={0.6}
      />
      <EffectComposer multisampling={0}>
        <Bloom intensity={0.15} radius={0.3} luminanceThreshold={0.95} luminanceSmoothing={0.15} mipmapBlur />
      </EffectComposer>
    </Canvas>
  )
}

/** Set the GL clear color separately so it composites with the flat inset
 *  surface on the canvas's parent (we want a transparent canvas so the
 *  surface shows around the corners). */
function ClearColor() {
  const { gl } = useThree()
  useEffect(() => {
    gl.setClearColor(0x000000, 0)
  }, [gl])
  return null
}
