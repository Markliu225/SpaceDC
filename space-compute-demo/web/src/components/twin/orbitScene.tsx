import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import {
  AdditiveBlending, BufferAttribute, BufferGeometry,
  CatmullRomCurve3, DoubleSide, Group, Mesh, MeshBasicMaterial,
  ShaderMaterial, TubeGeometry, Vector3,
} from 'three'
import type { ConstellationDetail } from '../../types/messages'
import { EARTH_RADIUS_KM, HUD_CYAN, HUD_CYAN_HOT, eciToDisplay } from './orbitMath'

/**
 * orbitScene — the shared Three.js building blocks for the REAL-orbit views:
 * the MiniOrbitHud (bottom-left of the Twin viewport) and TwinOrbitFallback
 * (the full-viewport local render when the Omniverse stream is offline).
 * Both draw the same physically-honest scene: a day/night Earth lit from the
 * backend's fixed ECI sun direction, a GMST-rotating wireframe, the active
 * constellation's orbit rings, and the tracked satellite as a pulsing
 * reticle moving along its true propagated position.
 */

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

export function DayNightEarth({ sunDir }: { sunDir: Vector3 }) {
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

export function GmstWireframe({ gmst }: { gmst: number }) {
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
export function ConstellationRings({
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

export function SatReticle({ pos, scale = 1 }: { pos: [number, number, number]; scale?: number }) {
  const haloRef = useRef<Mesh>(null!)
  useFrame(({ clock }) => {
    if (!haloRef.current) return
    const t = (clock.getElapsedTime() % 1.8) / 1.8
    const s = 1 + t * 3.5
    haloRef.current.scale.set(s, s, s)
    ;(haloRef.current.material as MeshBasicMaterial).opacity = (1 - t) * 0.75
  })
  return (
    <group position={pos} scale={scale}>
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

export function SunMarker({ dir }: { dir: Vector3 }) {
  // A small distant beacon well outside the orbit shell — sized so it reads
  // as "the sun is over there", not a nearby body.
  const pos = useMemo<[number, number, number]>(
    () => [dir.x * 3.6, dir.y * 3.6, dir.z * 3.6],
    [dir],
  )
  return (
    <group position={pos}>
      <mesh>
        <sphereGeometry args={[0.045, 12, 12]} />
        <meshBasicMaterial color="#FFE9B0" />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.1, 12, 12]} />
        <meshBasicMaterial
          color="#FFE9B0" transparent opacity={0.3}
          depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
    </group>
  )
}
