import { useId, useMemo } from 'react'
import { ComposableMap, Geographies, Geography, Marker } from 'react-simple-maps'
import { Card } from '../primitives'
import { colors } from '../../design/tokens'
import { useFleetPositions } from '../../hooks/useFleetPositions'
import { useTelemetryStore } from '../../store/useTelemetryStore'

const TOPO = 'https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json'

const W = 800
const H = 320

/** Half-angle of the visibility cone from a sat at altitude h above an
 *  Earth of radius R, for a min-elevation cutoff of 10° at the ground:
 *      cos(λ) = R / (R + h) · cos(elev_min)
 *  Returned as degrees of central angle ⇒ ground-circle radius on the map. */
function visibilityRadiusDeg(altKm: number): number {
  const R = 6378.137
  const elevMin = (10 * Math.PI) / 180
  const cosLam = (R / (R + altKm)) * Math.cos(elevMin)
  const lam = Math.acos(Math.min(1, Math.max(-1, cosLam)))
  return (lam * 180) / Math.PI
}

/**
 * RealCoverageMap — flat world map with one density circle per live sat.
 *
 * Replaces the legacy `CoverageMap` (which animated a single decorative
 * orbital swath). The radii are physical: each circle is the central-angle
 * footprint of a sat's visibility cone at 10° min-elevation. Online sats
 * draw bright cyan, eclipse sats dim blue, others faint gray — gives an
 * instant read of "how much of the planet is currently usable".
 *
 * Implementation note: instead of projecting actual spherical caps (which
 * would clip messily near the poles in equal-earth), we approximate each
 * footprint as an SVG <circle> placed at the projected lat/lon point with
 * radius proportional to the central angle. This is intentionally a 2D
 * density read, not a geodesic footprint — accurate enough for a glanceable
 * coverage panel and far cheaper than full great-circle polygon tessellation.
 */
export function RealCoverageMap() {
  const fleet      = useFleetPositions()
  const coveragePct = useTelemetryStore((s) => Math.round(s.fleet?.coverage_pct ?? 0))
  const totalSats   = useTelemetryStore((s) => s.fleet?.total ?? fleet.length)
  const detail      = useTelemetryStore((s) => s.constellationDetail)
  const selectedIdx = useTelemetryStore((s) => s.selectedSatIdx)
  const setSelected = useTelemetryStore((s) => s.setSelectedSatIdx)
  const gid = useId().replace(/:/g, '')

  // Cache per-sat marker primitives — recomputed each tick because lat/lon move.
  const markers = useMemo(() => {
    return fleet.map((s) => {
      const rDeg = visibilityRadiusDeg(s.altitudeKm)
      // Equal-earth projection isn't conformal; pick a screen radius that
      // looks right for a typical LEO footprint ~25° central angle ⇒ ~28px.
      const rPx = Math.max(4, Math.min(40, (rDeg / 25) * 28))
      return {
        idx: s.idx,
        lon: s.lon,
        lat: s.lat,
        rPx,
        sunlit: s.sunlit,
      }
    })
  }, [fleet])

  return (
    <Card className="h-full flex flex-col min-h-0">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Coverage Map
        </span>
        <span className="text-[11px] text-text-lo tabular">
          {detail
            ? `${detail.inclination_deg.toFixed(1)}° · ${totalSats} sats`
            : `${totalSats} sats`}
        </span>
      </div>

      <div className="relative flex-1 min-h-0 overflow-hidden rounded-md bg-bg-inset">
        <ComposableMap
          projection="geoEqualEarth"
          projectionConfig={{ scale: 145 }}
          width={W}
          height={H}
          style={{ width: '100%', height: '100%' }}
        >
          <defs>
            <radialGradient id={`cov-online-${gid}`}>
              <stop offset="0%"   stopColor={colors.status.online} stopOpacity="0.55" />
              <stop offset="60%"  stopColor={colors.status.online} stopOpacity="0.15" />
              <stop offset="100%" stopColor={colors.status.online} stopOpacity="0" />
            </radialGradient>
            <radialGradient id={`cov-eclipse-${gid}`}>
              <stop offset="0%"   stopColor={colors.status.eclipse} stopOpacity="0.45" />
              <stop offset="60%"  stopColor={colors.status.eclipse} stopOpacity="0.10" />
              <stop offset="100%" stopColor={colors.status.eclipse} stopOpacity="0" />
            </radialGradient>
          </defs>

          <Geographies geography={TOPO}>
            {({ geographies }) =>
              geographies.map((geo) => (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  fill="#1B233A"
                  stroke="transparent"
                  style={{
                    default: { outline: 'none' },
                    hover:   { outline: 'none' },
                    pressed: { outline: 'none' },
                  }}
                />
              ))
            }
          </Geographies>

          {/* Density circles. */}
          {markers.map((m) => {
            const dotColor = m.sunlit ? colors.status.online : colors.status.eclipse
            const fillRef  = m.sunlit ? `url(#cov-online-${gid})` : `url(#cov-eclipse-${gid})`
            const selected = m.idx === selectedIdx
            return (
              <Marker
                key={m.idx}
                coordinates={[m.lon, m.lat]}
                onClick={() => setSelected(m.idx)}
                style={{ default: { cursor: 'pointer' } }}
              >
                <circle r={m.rPx} fill={fillRef} />
                <circle
                  r={selected ? 3 : 1.8}
                  fill={dotColor}
                  stroke={selected ? '#FFFFFF' : 'none'}
                  strokeWidth={selected ? 1 : 0}
                  style={{ filter: `drop-shadow(0 0 4px ${dotColor})` }}
                />
              </Marker>
            )
          })}
        </ComposableMap>
      </div>

      <div className="mt-2">
        <div className="flex items-center justify-between text-[10px] tabular text-text-lo">
          <span>0%</span>
          <span className="text-text-md">Coverage</span>
          <span>100%</span>
        </div>
        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-bg-inset">
          <div
            className="h-full rounded-full transition-[width] duration-500 ease-out"
            style={{
              width: `${coveragePct}%`,
              background: 'linear-gradient(90deg, #3B9EFF 0%, #E8EEFB 100%)',
              boxShadow: '0 0 8px rgba(59,158,255,0.4)',
            }}
          />
        </div>
      </div>
    </Card>
  )
}
