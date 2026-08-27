import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import { Suspense, useEffect } from 'react'
import { Earth } from './Earth'
import { Atmosphere } from './Atmosphere'
import { Stars } from './Stars'
import { OrbitRibbons } from './OrbitRibbons'
import { TerminatorRing } from './DawnDuskOrbit'
import { Satellites } from './Satellites'
import { colors } from '../../../design/tokens'

/**
 * FallbackEarth — the Overview page's local Three.js scene, rendered when the
 * Omniverse stream isn't available. Every position in it is real:
 *
 *   - Day/night Earth. The MESH spins by the broadcast GMST about display +Y;
 *     the sun is the broadcast `sun_unit_teme` and stays inertial.
 *   - Terminator reference ring — a great circle whose normal is that same sun
 *     vector, i.e. the day/night boundary of the globe you are looking at. The
 *     ruler that shows whether the orbit planes really are dawn–dusk.
 *   - Orbit ribbons from the active constellation's propagated ECI rings, one
 *     per plane / SSO shell. No constellation loaded ⇒ no ribbons.
 *   - Satellite billboards sampled from those same rings at their true phase.
 *   - 2000 star points, atmosphere Fresnel shell, and a restrained bloom
 *     (intensity 0.15, threshold 0.95) so only the sprite cores flare.
 *   - Auto camera orbit (1 rev / 90 s) until the user drags.
 *
 * With no backend the scene degrades quietly: no ribbons, no sprites, and the
 * sky frame holds its last known sun instead of snapping anywhere.
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
        <TerminatorRing />
        <OrbitRibbons />
        <Satellites />
      </Suspense>
      <OrbitControls
        autoRotate
        autoRotateSpeed={0.4 /* ~ 1 rev / 90s at speed 0.4 */}
        enablePan={false}
        enableZoom
        minDistance={1.6}
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
