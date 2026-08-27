/**
 * assetArt — vector reference-design illustrations for the platforms whose
 * real geometry is NOT in our asset library.
 *
 * The other two cards show a software render of the actual USD hull the
 * satellite will fly (`SpaceDcBackbone`, the Redwire payload bay). Sophia
 * Space and Ada Space have no vendor model here, so rendering our stand-in
 * hull on their card would show the viewer a satellite that is simply not
 * what those companies build. These drawings follow each vendor's own
 * published description instead:
 *
 *   Sophia Space — "TILE" (Thermal Integrated LEO Edge): a 1 m², ~1 cm-thick
 *   panel carrying a solar array on the sunlit face, four processors inside,
 *   and the anti-sun face radiating straight to space — no fans, no loops.
 *   Tiles aggregate: one tile hosted on someone else's bus, ~40 as a
 *   companion-orbit cluster, ~2,500 as a full orbital data center.
 *
 *   Ada Space (国星宇航) — the Three-Body Computing Constellation bus: a
 *   compact "intelligent networked" smallsat (744 TOPS class on-board AI,
 *   100 Gbps laser inter-satellite links, twelve to a Long March 2D, in a
 *   sun-synchronous ring). Ada publishes the capability, not a CAD-level
 *   reference design, so this is drawn to that description — a compact bus
 *   with twin deployed wings and gimballed laser terminals — and is
 *   deliberately generic where the public record is silent.
 *
 * Both are drawn in the same isometric projection, on the same square canvas
 * as the rendered previews, so the card row reads as one set.
 */

import { colors } from '../../../design/tokens'

const COS30 = 0.8660254

type P3 = [number, number, number]

/** Isometric projection: +X right-down, +Y left-down, +Z up. */
function iso([x, y, z]: P3, s: number, ox: number, oy: number): [number, number] {
  return [ox + (x - y) * COS30 * s, oy + ((x + y) * 0.5 - z) * s]
}

function poly(pts: P3[], s: number, ox: number, oy: number): string {
  return pts.map((p) => {
    const [X, Y] = iso(p, s, ox, oy)
    return `${X.toFixed(1)},${Y.toFixed(1)}`
  }).join(' ')
}

/** A flat slab (a box that is much thinner than it is wide) as three faces:
 *  top, then the two side faces that face the viewer. */
function Slab({
  x0, y0, x1, y1, z, t, s, ox, oy, top, side, edge, opacity = 1,
}: {
  x0: number; y0: number; x1: number; y1: number; z: number; t: number
  s: number; ox: number; oy: number
  top: string; side: string; edge?: string; opacity?: number
}) {
  const zt = z + t
  return (
    <g opacity={opacity}>
      {/* +X side (front-right) */}
      <polygon points={poly([[x1, y0, z], [x1, y1, z], [x1, y1, zt], [x1, y0, zt]], s, ox, oy)}
               fill={side} />
      {/* +Y side (front-left) */}
      <polygon points={poly([[x0, y1, z], [x1, y1, z], [x1, y1, zt], [x0, y1, zt]], s, ox, oy)}
               fill={side} opacity={0.72} />
      <polygon points={poly([[x0, y0, zt], [x1, y0, zt], [x1, y1, zt], [x0, y1, zt]], s, ox, oy)}
               fill={top} stroke={edge} strokeWidth={edge ? 0.8 : undefined} />
    </g>
  )
}

/** Solar-cell ruling across a slab's top face. */
function CellLines({
  x0, y0, x1, y1, z, n, s, ox, oy, color = '#0B1B47',
}: {
  x0: number; y0: number; x1: number; y1: number; z: number; n: number
  s: number; ox: number; oy: number; color?: string
}) {
  const lines = []
  for (let i = 1; i < n; i++) {
    const y = y0 + ((y1 - y0) * i) / n
    const [ax, ay] = iso([x0, y, z], s, ox, oy)
    const [bx, by] = iso([x1, y, z], s, ox, oy)
    lines.push(<line key={`h${i}`} x1={ax} y1={ay} x2={bx} y2={by} stroke={color} strokeWidth={0.7} />)
  }
  return <g opacity={0.75}>{lines}</g>
}

const SOLAR_TOP = '#1E3A8A'
const SOLAR_SIDE = '#0E1F4E'
const RAD_TOP = '#C9CFDA'
const RAD_SIDE = '#7C8496'
const BUS_TOP = '#98A2B5'
const BUS_SIDE = '#5C6579'
const COMPUTE = '#111827'

/**
 * Sophia Space — a 3×3 patch of TILEs in the array plane, with one tile
 * exploded above it into the three layers the vendor describes: solar face,
 * compute core (four processors), radiating back face.
 */
export function SophiaArt() {
  // Square canvas, matching the rendered platform previews. `oy` centres the
  // composition: the array spans ±1.5 in (x+y)/2 and the exploded tile sits
  // ~2 units of z above it, so the drawn extent runs oy−94 … oy+69.
  const s = 46, ox = 196, oy = 214
  const t = 0.10                    // thickness, exaggerated from ~1 cm
  const gap = 0.06
  const tiles = []
  // Painter's order: far (small x+y) first.
  for (let k = 0; k <= 4; k++) {
    for (let i = 0; i < 3; i++) {
      const j = k - i
      if (j < 0 || j > 2) continue
      const x0 = i - 1.5 + gap, x1 = i - 0.5 - gap
      const y0 = j - 1.5 + gap, y1 = j - 0.5 - gap
      tiles.push(
        <g key={`${i}-${j}`}>
          <Slab x0={x0} y0={y0} x1={x1} y1={y1} z={0} t={t} s={s} ox={ox} oy={oy}
                top={SOLAR_TOP} side={SOLAR_SIDE} edge="#2B4EA8" />
          <CellLines x0={x0} y0={y0} x1={x1} y1={y1} z={t} n={4} s={s} ox={ox} oy={oy} />
        </g>,
      )
    }
  }

  // Exploded tile — the stack that makes a TILE a data center.
  const ex0 = 0.8, ey0 = -2.4, ex1 = 1.8, ey1 = -1.4
  const chips = []
  for (let a = 0; a < 2; a++) {
    for (let b = 0; b < 2; b++) {
      const cx0 = ex0 + 0.14 + a * 0.42, cy0 = ey0 + 0.14 + b * 0.42
      chips.push(
        <polygon key={`c${a}${b}`}
                 points={poly([[cx0, cy0, 1.13], [cx0 + 0.3, cy0, 1.13],
                               [cx0 + 0.3, cy0 + 0.3, 1.13], [cx0, cy0 + 0.3, 1.13]], s, ox, oy)}
                 fill={colors.ribbons[1]} opacity={0.85} />,
      )
    }
  }

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" preserveAspectRatio="xMidYMid meet"
         role="img" aria-label="Sophia Space TILE array reference design">
      <rect width="400" height="400" fill={colors.bg.inset} />
      {/* Heat leaving the anti-sun face. */}
      <g opacity={0.30}>
        {[-1.0, -0.2, 0.6].map((d, i) => {
          const [x, y] = iso([d, d + 0.4, -0.05], s, ox, oy)
          return <line key={i} x1={x} y1={y} x2={x} y2={y + 26} stroke={colors.warn} strokeWidth={1.4}
                       strokeDasharray="3 4" />
        })}
      </g>
      {tiles}

      {/* Exploded stack: radiator back / compute core / solar face. */}
      <Slab x0={ex0} y0={ey0} x1={ex1} y1={ey1} z={0.95} t={0.07} s={s} ox={ox} oy={oy}
            top={RAD_TOP} side={RAD_SIDE} opacity={0.95} />
      <Slab x0={ex0} y0={ey0} x1={ex1} y1={ey1} z={1.06} t={0.07} s={s} ox={ox} oy={oy}
            top={COMPUTE} side="#10141A" />
      {chips}
      <Slab x0={ex0} y0={ey0} x1={ex1} y1={ey1} z={1.17} t={0.07} s={s} ox={ox} oy={oy}
            top={SOLAR_TOP} side={SOLAR_SIDE} edge="#2B4EA8" />
      <CellLines x0={ex0} y0={ey0} x1={ex1} y1={ey1} z={1.24} n={4} s={s} ox={ox} oy={oy} />

      {/* Leader from the exploded tile down into the array. */}
      <line {...leader(iso([ex0, ey1, 0.95], s, ox, oy), iso([0.6, -0.6, 0.1], s, ox, oy))}
            stroke={colors.accent} strokeWidth={0.9} strokeDasharray="2 3" opacity={0.6} />
    </svg>
  )
}

function leader(a: [number, number], b: [number, number]) {
  return { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }
}

/**
 * Ada Space — the Three-Body Computing Constellation bus: compact body,
 * twin deployed wings, gimballed laser terminals for the inter-satellite
 * mesh, nadir payload aperture.
 */
export function AdaArt() {
  // Square canvas. The wingspan runs the full width; `oy` centres the
  // drawn extent (oy−115 … oy+87) in the 400-unit box.
  const s = 40, ox = 200, oy = 214
  const bx = 0.85, bz = 0.5           // body half-width, height

  // Wing: three panel segments per side, out along ±Y, coplanar with the deck.
  const wing = (sign: 1 | -1) => {
    const segs = []
    for (let i = 0; i < 3; i++) {
      const y0 = sign > 0 ? bx + 0.45 + i * 1.05 : -(bx + 0.45 + (i + 1) * 1.05) + 0.05
      const y1 = y0 + 1.0
      segs.push(
        <g key={i}>
          <Slab x0={-0.62} y0={y0} x1={0.62} y1={y1} z={0.30} t={0.05}
                s={s} ox={ox} oy={oy} top={SOLAR_TOP} side={SOLAR_SIDE} edge="#2B4EA8" />
          <CellLines x0={-0.62} y0={y0} x1={0.62} y1={y1} z={0.35} n={3} s={s} ox={ox} oy={oy} />
        </g>,
      )
    }
    // Yoke from the body edge to the inboard panel.
    const yy = sign > 0 ? bx : -bx
    segs.push(
      <polygon key="yoke"
               points={poly([[-0.07, yy, 0.34], [0.07, yy, 0.34],
                             [0.07, yy + sign * 0.45, 0.34], [-0.07, yy + sign * 0.45, 0.34]],
                            s, ox, oy)}
               fill={BUS_SIDE} />,
    )
    return <g>{segs}</g>
  }

  const [lx, ly] = iso([0.55, -0.55, bz + 0.42], s, ox, oy)

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" preserveAspectRatio="xMidYMid meet"
         role="img" aria-label="Ada Space computing satellite reference design">
      <rect width="400" height="400" fill={colors.bg.inset} />

      {/* Far wing, body, near wing — painter's order. */}
      {wing(-1)}

      {/* Bus: a compact box with a radiator strip down the +X face. */}
      <Slab x0={-bx} y0={-bx} x1={bx} y1={bx} z={0} t={bz} s={s} ox={ox} oy={oy}
            top={BUS_TOP} side={BUS_SIDE} edge="#39414f" />
      <polygon points={poly([[bx, -0.55, 0.08], [bx, 0.55, 0.08],
                             [bx, 0.55, bz - 0.08], [bx, -0.55, bz - 0.08]], s, ox, oy)}
               fill={RAD_TOP} opacity={0.55} />

      {/* Gimballed laser terminal on top + its link, and a second terminal
          on the far side (the constellation meshes both ways). */}
      <polygon points={poly([[0.22, -0.62, bz], [0.62, -0.62, bz],
                             [0.62, -0.22, bz], [0.22, -0.22, bz]], s, ox, oy)}
               fill="#39414f" />
      <circle cx={lx} cy={ly} r={7.5} fill="#1F2937" stroke="#98A2B5" strokeWidth={1.2} />
      <circle cx={lx} cy={ly} r={3} fill={colors.accent} />
      <line x1={lx} y1={ly} x2={lx + 68} y2={ly - 38} stroke={colors.accent} strokeWidth={1.4}
            strokeDasharray="5 4" opacity={0.75} />
      <circle cx={lx + 68} cy={ly - 38} r={2.5} fill={colors.accent} opacity={0.8} />

      {/* Nadir payload aperture on the −X face. */}
      <polygon points={poly([[-bx, -0.34, 0.10], [-bx, 0.34, 0.10],
                             [-bx, 0.34, 0.40], [-bx, -0.34, 0.40]], s, ox, oy)}
               fill="#10141A" stroke="#39414f" strokeWidth={0.8} />

      {wing(1)}
    </svg>
  )
}
