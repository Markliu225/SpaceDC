import { Canvas, useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import {
  AdditiveBlending, BackSide, BufferAttribute, BufferGeometry,
  CatmullRomCurve3, DoubleSide, Mesh, MeshBasicMaterial,
  ShaderMaterial, TubeGeometry, Vector3,
} from 'three'
import { atmoVert, atmoFrag } from '../overview/earth/shaders'
import { useFleetPositions } from '../../hooks/useFleetPositions'
import { useTelemetryStore } from '../../store/useTelemetryStore'

/**
 * MiniOrbitHud — 176×176 holographic-style HUD at the bottom-left of the
 * Satellite Twin viewport. Sci-fi wireframe Earth + glowing tube orbit +
 * pulsing satellite reticle + a sun marker placed in the same `SUN_DIR_ECI`
 * the backend uses for `sun_factor`, so the SUNLIT/ECLIPSE badge and the
 * satellite-stage lighting are driven by the same direction.
 *
 * Display frame: Y-up, geometry static — the wireframe globe slowly auto-
 * rotates for liveliness; the sun marker and sat dot live in fixed ECI.
 */

const EARTH_RADIUS_KM = 6378.137
const SUN_DIR_ECI: [number, number, number] = [0.648, -0.648, 0.398]
const HUD_CYAN = '#3B9EFF'
const HUD_CYAN_HOT = '#22D3EE'
const HUD_WARN = '#F59E0B'

/** ECI (z = north pole) → Three.js display coords (Y-up). */
function eciToDisplay([x, y, z]: [number, number, number]): [number, number, number] {
  return [x, z, -y]
}

/** Build a clean lat/lon wireframe globe — N parallels + M meridians. */
function makeLatLonGrid(radius: number, parallels: number, meridians: number): BufferGeometry {
  const pts: number[] = []
  const SEGS = 64
  // Parallels (horizontal circles at evenly spaced latitudes).
  for (let i = 1; i < parallels; i++) {
    const lat = -Math.PI / 2 + (i / parallels) * Math.PI
    const r = radius * Math.cos(lat)
    const y = radius * Math.sin(lat)
    for (let j = 0; j < SEGS; j++) {
      const a0 = (j / SEGS) * 2 * Math.PI
      const a1 = ((j + 1) / SEGS) * 2 * Math.PI
      pts.push(r * Math.cos(a0), y, r * Math.sin(a0))
      pts.push(r * Math.cos(a1), y, r * Math.sin(a1))
    }
  }
  // Meridians (vertical half-circles at evenly spaced longitudes).
  for (let i = 0; i < meridians; i++) {
    const lon = (i / meridians) * 2 * Math.PI
    for (let j = 0; j < SEGS; j++) {
      const t0 = -Math.PI / 2 + (j / SEGS) * Math.PI
      const t1 = -Math.PI / 2 + ((j + 1) / SEGS) * Math.PI
      const r0 = radius * Math.cos(t0), y0 = radius * Math.sin(t0)
      const r1 = radius * Math.cos(t1), y1 = radius * Math.sin(t1)
      pts.push(r0 * Math.cos(lon), y0, r0 * Math.sin(lon))
      pts.push(r1 * Math.cos(lon), y1, r1 * Math.sin(lon))
    }
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new BufferAttribute(new Float32Array(pts), 3))
  return g
}

function WireframeGlobe() {
  const ref = useRef<Mesh>(null!)
  const geom = useMemo(() => makeLatLonGrid(1.0, 9, 12), [])
  // Brighter equator highlight so the globe reads as oriented.
  const equator = useMemo(() => {
    const pts: number[] = []
    const SEGS = 96
    for (let j = 0; j < SEGS; j++) {
      const a0 = (j / SEGS) * 2 * Math.PI
      const a1 = ((j + 1) / SEGS) * 2 * Math.PI
      pts.push(Math.cos(a0), 0, Math.sin(a0))
      pts.push(Math.cos(a1), 0, Math.sin(a1))
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(new Float32Array(pts), 3))
    return g
  }, [])
  useFrame((_, dt) => { if (ref.current) ref.current.rotation.y += dt * 0.08 })
  return (
    <group ref={ref}>
      <lineSegments>
        <primitive object={geom} attach="geometry" />
        <lineBasicMaterial color={HUD_CYAN} transparent opacity={0.55} />
      </lineSegments>
      <lineSegments>
        <primitive object={equator} attach="geometry" />
        <lineBasicMaterial color={HUD_CYAN_HOT} transparent opacity={0.85} />
      </lineSegments>
    </group>
  )
}

function MiniAtmosphere() {
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: atmoVert,
    fragmentShader: atmoFrag,
    uniforms: {
      uColor:     { value: new Vector3(0.23, 0.62, 1.0) },
      uIntensity: { value: 0.9 },
    },
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    side: BackSide,
  }), [])
  return (
    <mesh>
      <sphereGeometry args={[1.07, 32, 32]} />
      <primitive object={material} attach="material" />
    </mesh>
  )
}

function OrbitTube({ points }: { points: [number, number, number][] }) {
  const geom = useMemo(() => {
    const pts = points.map(([x, y, z]) => new Vector3(x, y, z))
    const curve = new CatmullRomCurve3(pts, true, 'catmullrom', 0.5)
    return new TubeGeometry(curve, 160, 0.014, 6, true)
  }, [points])
  return (
    <mesh>
      <primitive object={geom} attach="geometry" />
      <meshBasicMaterial
        color={HUD_CYAN_HOT}
        transparent
        opacity={0.9}
        depthWrite={false}
        blending={AdditiveBlending}
      />
    </mesh>
  )
}

function SatReticle({ pos }: { pos: [number, number, number] }) {
  const haloRef = useRef<Mesh>(null!)
  useFrame(({ clock }) => {
    if (!haloRef.current) return
    const t = (clock.getElapsedTime() % 1.6) / 1.6   // 0..1 over 1.6 s
    const s = 1 + t * 3.5
    haloRef.current.scale.set(s, s, s)
    ;(haloRef.current.material as MeshBasicMaterial).opacity = (1 - t) * 0.75
  })
  return (
    <group position={pos}>
      {/* core dot */}
      <mesh>
        <sphereGeometry args={[0.038, 12, 12]} />
        <meshBasicMaterial color={HUD_CYAN_HOT} />
      </mesh>
      {/* steady halo */}
      <mesh>
        <sphereGeometry args={[0.08, 12, 12]} />
        <meshBasicMaterial
          color={HUD_CYAN_HOT}
          transparent opacity={0.35}
          depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
      {/* pulsing target ring (sonar-style) */}
      <mesh ref={haloRef}>
        <ringGeometry args={[0.05, 0.07, 32]} />
        <meshBasicMaterial
          color={HUD_CYAN_HOT}
          transparent opacity={0.7}
          side={DoubleSide}
          depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
    </group>
  )
}

function SunMarker({ dir }: { dir: Vector3 }) {
  // Place a small bright marker far along the sun direction so the schematic
  // shows "where the sun is" — visually ties the sat's sunlit/eclipse state
  // to its position on the orbit.
  const pos = useMemo<[number, number, number]>(
    () => [dir.x * 2.35, dir.y * 2.35, dir.z * 2.35],
    [dir],
  )
  return (
    <group position={pos}>
      <mesh>
        <sphereGeometry args={[0.06, 12, 12]} />
        <meshBasicMaterial color="#FFE9B0" />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.15, 12, 12]} />
        <meshBasicMaterial
          color="#FFE9B0"
          transparent opacity={0.35}
          depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
    </group>
  )
}

function Brackets() {
  // L-shaped corner marks (sci-fi targeting-frame chrome). Pure CSS for crispness.
  const base = 'absolute w-3 h-3 border-[#3B9EFF]'
  return (
    <>
      <div className={`${base} left-0 top-0 border-l border-t`} />
      <div className={`${base} right-0 top-0 border-r border-t`} />
      <div className={`${base} left-0 bottom-0 border-l border-b`} />
      <div className={`${base} right-0 bottom-0 border-r border-b`} />
    </>
  )
}

export function MiniOrbitHud() {
  const fleet    = useFleetPositions()
  const selected = useTelemetryStore((s) => s.selectedSatIdx)
  const detail   = useTelemetryStore((s) => s.constellationDetail)
  const sat      = fleet[selected]

  const sunDir = useMemo(
    () => new Vector3(...eciToDisplay(SUN_DIR_ECI)).normalize(),
    [],
  )

  const orbitPoints = useMemo<[number, number, number][]>(() => {
    if (!detail || !sat) return []
    const { ring_eci_km, planes } = detail
    const ang = (sat.planeIdx * 2 * Math.PI) / planes
    const ca = Math.cos(ang), sa = Math.sin(ang)
    const inv = 1 / EARTH_RADIUS_KM
    return ring_eci_km.map(([x, y, z]) => {
      const rx = x * ca - y * sa
      const ry = x * sa + y * ca
      return eciToDisplay([rx * inv, ry * inv, z * inv])
    })
  }, [detail, sat?.planeIdx])

  const satPos = useMemo<[number, number, number] | null>(() => {
    if (!sat) return null
    const inv = 1 / EARTH_RADIUS_KM
    return eciToDisplay([sat.eci[0] * inv, sat.eci[1] * inv, sat.eci[2] * inv])
  }, [sat?.eci])

  return (
    <div className="absolute left-3 bottom-3 z-10 pointer-events-none">
      <div className="pointer-events-auto relative h-[176px] w-[176px] bg-[#040912]/85 backdrop-blur-sm">
        {/* Faint cyan grid texture — holographic feel. */}
        <div
          className="absolute inset-0 opacity-50"
          style={{
            backgroundImage:
              'linear-gradient(rgba(59,158,255,0.06) 1px, transparent 1px),'
              + 'linear-gradient(90deg, rgba(59,158,255,0.06) 1px, transparent 1px)',
            backgroundSize: '14px 14px',
          }}
        />
        <Brackets />

        {/* Header strip. */}
        <div className="absolute left-1.5 right-1.5 top-1.5 flex items-center justify-between">
          <span className="text-[8.5px] uppercase tracking-[0.20em] text-[#3B9EFF] font-mono">
            ▸ ORBIT TRK
          </span>
          <span
            className="text-[8.5px] uppercase tracking-[0.18em] font-mono"
            style={{ color: sat?.sunlit ? HUD_CYAN_HOT : HUD_WARN }}
          >
            {sat ? (sat.sunlit ? '◉ SUNLIT' : '○ ECLIPSE') : '— STDBY'}
          </span>
        </div>

        {/* 3D holographic scene. */}
        <div className="absolute inset-x-1 top-6 bottom-[40px]">
          <Canvas
            camera={{ position: [0, 0.55, 3.2], fov: 32 }}
            gl={{ antialias: true, alpha: true }}
          >
            <ambientLight intensity={0.4} />
            <WireframeGlobe />
            <MiniAtmosphere />
            {orbitPoints.length > 0 && <OrbitTube points={orbitPoints} />}
            {satPos && <SatReticle pos={satPos} />}
            <SunMarker dir={sunDir} />
          </Canvas>
        </div>

        {/* Footer telemetry — labeled mono readouts in HUD cyan. */}
        <div className="absolute left-1.5 right-1.5 bottom-1.5 flex flex-col gap-[1px] text-[8.5px] font-mono leading-[1.25]">
          <div className="flex justify-between text-[#3B9EFF]/85">
            <span>LAT</span>
            <span className="text-[#E0F0FF]">
              {sat ? `${sat.lat >= 0 ? '+' : ''}${sat.lat.toFixed(1)}°` : '— —'}
            </span>
          </div>
          <div className="flex justify-between text-[#3B9EFF]/85">
            <span>LON</span>
            <span className="text-[#E0F0FF]">
              {sat ? `${sat.lon >= 0 ? '+' : ''}${sat.lon.toFixed(1)}°` : '— —'}
            </span>
          </div>
          <div className="flex justify-between text-[#3B9EFF]/85">
            <span>ALT</span>
            <span className="text-[#E0F0FF]">
              {sat ? `${Math.round(sat.altitudeKm)} KM` : '— —'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
