import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import { Suspense, useEffect } from 'react'
import { Earth } from './Earth'
import { Atmosphere } from './Atmosphere'
import { Stars } from './Stars'
import { OrbitRibbons } from './OrbitRibbons'
import { Satellites } from './Satellites'

/**
 * FallbackEarth — full Three.js scene rendered when the Omniverse stream
 * isn't available. Per design brief:
 *
 *   - Procedural day/night Earth (shader; sun direction drifts)
 *   - Atmosphere Fresnel shell (additive, cyan, intensity 1.5)
 *   - 24 colored orbit ribbons (TubeGeometry, additive, breathing opacity)
 *   - Satellite billboards (radial-gradient sprite, 1.5–2.5x pulse)
 *   - 2000 star points (twinkle, additive)
 *   - UnrealBloom (strength 0.6, radius 0.4, threshold 0.85)
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
        background:
          'radial-gradient(ellipse at center, #0A1224 0%, #03060E 70%)',
      }}
    >
      <ClearColor />
      <ambientLight intensity={0.18} />
      <Suspense fallback={null}>
        <Stars />
        <Earth />
        <Atmosphere />
        <OrbitRibbons />
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
        <Bloom intensity={0.6} radius={0.4} luminanceThreshold={0.85} luminanceSmoothing={0.2} mipmapBlur />
      </EffectComposer>
    </Canvas>
  )
}

/** Set the GL clear color separately so it composites with the CSS gradient
 *  on the canvas's parent (we want a transparent canvas so the gradient
 *  shows around the corners). */
function ClearColor() {
  const { gl } = useThree()
  useEffect(() => {
    gl.setClearColor(0x000000, 0)
  }, [gl])
  return null
}
