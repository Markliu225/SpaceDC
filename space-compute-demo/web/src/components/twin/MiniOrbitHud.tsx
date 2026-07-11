import { Canvas, useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import {
  AdditiveBlending, BufferAttribute, BufferGeometry,
  CatmullRomCurve3, DoubleSide, Group, Mesh, MeshBasicMaterial,
  ShaderMaterial, TubeGeometry, Vector3,
} from 'three'
import { useFleetPositions } from '../../hooks/useFleetPositions'
import { useDemoStore } from '../../store/demoStore'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import type { ConstellationDetail } from '../../types/messages'

/**
 * MiniOrbitHud — sci-fi holographic HUD at the bottom-left of the Satellite
 * Twin viewport. Shows the active constellation (every plane's orbit ring),
 * highlights the selected sat's plane, places the sat as a pulsing reticle,
 * a sun marker at SUN_DIR_ECI, and a solid day/night Earth sphere whose
 * terminator is computed from the SAME sun direction the backend uses for
 * `sun_factor` — so the lit hemisphere on the HUD matches the side of the
 * Omniverse satellite that's currently bright. The wireframe globe rotates
 * at the true GMST rate so Earth time, sat orbital motion, and the
 * SUNLIT/ECLIPSE badge all share one clock.
 */

const EARTH_RADIUS_KM = 6378.137
const SIDEREAL_DAY_S = 86164.0905
// Must match services/constellations.py and hooks/useFleetPositions.ts.
const SUN_DIR_ECI: [number, number, number] = [0.648, -0.648, 0.398]
const HUD_CYAN     = '#3B9EFF'
const HUD_CYAN_HOT = '#22D3EE'
const HUD_WARN     = '#F59E0B'

/** ECI (z = north pole) → Three.js display coords (Y-up). */
function eciToDisplay([x, y, z]: [number, number, number]): [number, number, number] {
  return [x, z, -y]
}

// ---------------------------------------------------------------------------
// Day/night Earth — solid sphere with a sun-direction shader. The lit
// hemisphere glows cyan; the dark side is near-black. Terminator is a soft
// smoothstep so the boundary reads but isn't a hard line.
// ---------------------------------------------------------------------------
const dayNightVert = /* glsl */`
  varying vec3 vNormalW;
  varying vec3 vPositionW;
  void main() {
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vPositionW = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`
const dayNightFrag = /* glsl */`
  precision highp float;
  uniform vec3 uSunDir;
  varying vec3 vNormalW;
  varying vec3 vPositionW;
  void main() {
    vec3 N = normalize(vNormalW);
    float ndl = dot(N, normalize(uSunDir));
    float day = smoothstep(-0.15, 0.45, ndl);
    vec3 nightCol = vec3(0.015, 0.025, 0.05);
    vec3 dayCol   = vec3(0.08, 0.28, 0.55);
    vec3 col = mix(nightCol, dayCol, day);
    // Subtle Fresnel limb so the sphere has a planetary halo, not a flat disc.
    float limb = pow(1.0 - clamp(dot(N, normalize(cameraPosition - vPositionW)), 0.0, 1.0), 3.0);
    col += vec3(0.10, 0.30, 0.55) * limb * 0.45;
    gl_FragColor = vec4(col, 1.0);
  }
`

function DayNightEarth({ sunDir }: { sunDir: Vector3 }) {
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: dayNightVert,
    fragmentShader: dayNightFrag,
    uniforms: { uSunDir: { value: sunDir.clone() } },
  }), [sunDir])
  useFrame(() => { material.uniforms.uSunDir.value.copy(sunDir) })
  return (
    <mesh>
      <sphereGeometry args={[0.985, 48, 48]} />
      <primitive object={material} attach="material" />
    </mesh>
  )
}

// ---------------------------------------------------------------------------
// Wireframe overlay — sparse lat/lon grid on top of the day/night sphere.
// Rotates with GMST so the surface and the fixed-ECI sun direction give a
// visibly drifting terminator.
// ---------------------------------------------------------------------------
function makeLatLonGrid(radius: number, parallels: number, meridians: number): BufferGeometry {
  const pts: number[] = []
  const SEGS = 64
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

function GmstWireframe({ gmst }: { gmst: number }) {
  const ref = useRef<Group>(null!)
  const grid = useMemo(() => makeLatLonGrid(1.0, 6, 8), [])
  useFrame(() => { if (ref.current) ref.current.rotation.y = gmst })
  return (
    <group ref={ref}>
      <lineSegments>
        <primitive object={grid} attach="geometry" />
        <lineBasicMaterial color="#4DB0FF" transparent opacity={0.45} />
      </lineSegments>
    </group>
  )
}

// ---------------------------------------------------------------------------
// Constellation — every plane's orbit ring + selected plane highlighted.
// Geometry math MUST match useFleetPositions so the highlighted ring and the
// sat reticle visibly coincide.
// ---------------------------------------------------------------------------
function ConstellationRings({
  detail, selectedPlane,
}: { detail: ConstellationDetail; selectedPlane: number }) {
  const rings = useMemo(() => {
    const inv = 1 / EARTH_RADIUS_KM
    return Array.from({ length: detail.planes }, (_, k) => {
      const ang = (k * 2 * Math.PI) / detail.planes
      const ca = Math.cos(ang), sa = Math.sin(ang)
      const pts = detail.ring_eci_km.map(([x, y, z]) => {
        const rx = x * ca - y * sa
        const ry = x * sa + y * ca
        const d = eciToDisplay([rx * inv, ry * inv, z * inv])
        return new Vector3(d[0], d[1], d[2])
      })
      const curve = new CatmullRomCurve3(pts, true, 'catmullrom', 0.5)
      const isSel = k === selectedPlane
      const geom = new TubeGeometry(curve, 120, isSel ? 0.020 : 0.010, isSel ? 6 : 4, true)
      return { k, geom, isSel }
    })
  }, [detail, selectedPlane])
  return (
    <>
      {rings.map(({ k, geom, isSel }) => (
        <mesh key={k}>
          <primitive object={geom} attach="geometry" />
          <meshBasicMaterial
            color={isSel ? HUD_CYAN_HOT : HUD_CYAN}
            transparent
            opacity={isSel ? 1.0 : 0.7}
            depthWrite={false}
            blending={AdditiveBlending}
          />
        </mesh>
      ))}
    </>
  )
}

function SatReticle({ pos }: { pos: [number, number, number] }) {
  const haloRef = useRef<Mesh>(null!)
  useFrame(({ clock }) => {
    if (!haloRef.current) return
    const t = (clock.getElapsedTime() % 1.8) / 1.8
    const s = 1 + t * 3.5
    haloRef.current.scale.set(s, s, s)
    ;(haloRef.current.material as MeshBasicMaterial).opacity = (1 - t) * 0.75
  })
  return (
    <group position={pos}>
      <mesh>
        <sphereGeometry args={[0.04, 12, 12]} />
        <meshBasicMaterial color={HUD_CYAN_HOT} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.085, 12, 12]} />
        <meshBasicMaterial
          color={HUD_CYAN_HOT} transparent opacity={0.4}
          depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
      <mesh ref={haloRef}>
        <ringGeometry args={[0.05, 0.07, 32]} />
        <meshBasicMaterial
          color={HUD_CYAN_HOT} transparent opacity={0.7}
          side={DoubleSide} depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
    </group>
  )
}

function SunMarker({ dir }: { dir: Vector3 }) {
  const pos = useMemo<[number, number, number]>(
    () => [dir.x * 2.6, dir.y * 2.6, dir.z * 2.6],
    [dir],
  )
  return (
    <group position={pos}>
      <mesh>
        <sphereGeometry args={[0.07, 12, 12]} />
        <meshBasicMaterial color="#FFE9B0" />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.18, 12, 12]} />
        <meshBasicMaterial
          color="#FFE9B0" transparent opacity={0.35}
          depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
    </group>
  )
}

function Brackets() {
  const base = 'absolute w-2.5 h-2.5 border-[#3B9EFF]'
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
  const fleet     = useFleetPositions()
  const selected  = useTelemetryStore((s) => s.selectedSatIdx)
  const detail    = useTelemetryStore((s) => s.constellationDetail)
  const simTime   = useTelemetryStore((s) => s.sim_time_s)
  const timeScale = detail?.time_scale ?? 60
  // The physics engine tracks fleet[0]; when it is the selected sat and the
  // backend is live, the badge + LAT/LON/ALT read the engine's authoritative
  // values so the HUD can never contradict the telemetry panels (the local
  // propagation only positions the 3D dot).
  const backendSat = useDemoStore((s) => s.lastState?.satellite)
  const local = fleet[selected]
  const sat = (selected === 0 && backendSat && local)
    ? { ...local,
        sunlit: backendSat.sunlit,
        lat: backendSat.lat,
        lon: backendSat.lon,
        altitudeKm: backendSat.altitude_km }
    : local

  const sunDir = useMemo(
    () => new Vector3(...eciToDisplay(SUN_DIR_ECI)).normalize(),
    [],
  )
  const gmst = useMemo(
    () => (simTime * timeScale / SIDEREAL_DAY_S) * 2 * Math.PI,
    [simTime, timeScale],
  )

  const satPos = useMemo<[number, number, number] | null>(() => {
    if (!sat) return null
    const inv = 1 / EARTH_RADIUS_KM
    return eciToDisplay([sat.eci[0] * inv, sat.eci[1] * inv, sat.eci[2] * inv])
  }, [sat?.eci])

  const constellationId = detail?.id?.toUpperCase().replace(/_/g, '-') ?? 'STDBY'

  return (
    <div className="absolute left-3 bottom-3 z-10 pointer-events-none">
      <div className="pointer-events-auto relative h-[200px] w-[180px] bg-[#040912]/85 backdrop-blur-sm">
        <div
          className="absolute inset-0 opacity-50"
          style={{
            backgroundImage:
              'linear-gradient(rgba(59,158,255,0.06) 1px, transparent 1px),'
              + 'linear-gradient(90deg, rgba(59,158,255,0.06) 1px, transparent 1px)',
            backgroundSize: '12px 12px',
          }}
        />
        <Brackets />

        <div className="absolute left-1.5 right-1.5 top-1.5 flex items-center justify-between">
          <span className="text-[8px] uppercase tracking-[0.18em] text-[#3B9EFF] font-mono">
            ▸ {constellationId}
          </span>
          <span
            className="text-[8px] uppercase tracking-[0.16em] font-mono"
            style={{ color: sat?.sunlit ? HUD_CYAN_HOT : HUD_WARN }}
          >
            {sat ? (sat.sunlit ? '◉ SUNLIT' : '○ ECLIPSE') : '— STDBY'}
          </span>
        </div>

        <div className="absolute left-1.5 right-1.5 top-[18px] flex items-center justify-between">
          <span className="text-[7.5px] tracking-[0.16em] text-[#3B9EFF]/80 font-mono">
            SAT-{String(selected).padStart(3, '0')}
          </span>
          <span className="text-[7.5px] tracking-[0.16em] text-[#3B9EFF]/80 font-mono">
            {detail ? `${detail.planes}P × ${detail.sats_per_plane}S` : ''}
          </span>
        </div>

        <div className="absolute inset-x-1 top-[32px] bottom-[44px]">
          <Canvas
            camera={{ position: [2.7, 1.6, 3.2], fov: 32 }}
            gl={{ antialias: true, alpha: true }}
          >
            <ambientLight intensity={0.3} />
            <DayNightEarth sunDir={sunDir} />
            <GmstWireframe gmst={gmst} />
            {detail && detail.ring_eci_km.length > 0 && sat && (
              <ConstellationRings detail={detail} selectedPlane={sat.planeIdx} />
            )}
            {satPos && <SatReticle pos={satPos} />}
            <SunMarker dir={sunDir} />
          </Canvas>
        </div>

        <div className="absolute left-1.5 right-1.5 bottom-1.5 flex flex-col gap-[1px] text-[8px] font-mono leading-[1.25]">
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
