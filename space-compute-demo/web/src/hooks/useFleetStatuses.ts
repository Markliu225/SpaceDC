import { useMemo } from 'react'
import { useFleetPositions, type FleetSatPosition } from './useFleetPositions'
import { useTelemetryStore } from '../store/useTelemetryStore'
import type { FleetSnapshot } from '../types/messages'

export type SatStatus = 'online' | 'eclipse' | 'standby' | 'offline'

export interface FleetSat extends FleetSatPosition {
  status: SatStatus
  /** Human-friendly id — SAT-NNNN, padded based on fleet size. */
  id: string
}

/** Pick the pad width for the id slug from the fleet size:
 *  ≤99 ⇒ 2 digits, ≤999 ⇒ 3, otherwise 4. Keeps ids legible without
 *  excessive leading zeros for small constellations like single_iss. */
function idPad(total: number): number {
  if (total <= 99) return 2
  if (total <= 999) return 3
  return 4
}

/**
 * Distribute the FleetSnapshot's aggregate counts (online / eclipse / standby
 * / offline) across the propagated sats deterministically:
 *   - first `online_capable = online + eclipse` indices are "operational"
 *     and further split by their live `sunlit` flag (sunlit ⇒ online,
 *     dark side ⇒ eclipse)
 *   - next `standby` indices are standby
 *   - tail `offline` indices are offline
 *
 *  This produces stable status labels so the SatelliteList doesn't flicker
 *  rows in/out of "online" each tick, while still letting the eclipse band
 *  visibly chase Earth's terminator.
 *
 *  When the backend snapshot is missing (offline / loading), every sat is
 *  marked `online` (cheap fallback; the donut + KPIs will show zeros until
 *  the snapshot lands).
 */
export function useFleetStatuses(): FleetSat[] {
  const positions = useFleetPositions()
  const snap = useTelemetryStore((s) => s.fleet)

  return useMemo(() => {
    const T = positions.length
    if (T === 0) return []
    const pad = idPad(T)

    const counts = bucketCounts(snap, T)
    // Boundary indices for each band. Online band is [0, op), standby is
    // [op, op+sb), offline is [op+sb, T).
    const op = counts.operational
    const sb = counts.standby

    return positions.map((p) => {
      let status: SatStatus
      if (p.idx < op) {
        status = p.sunlit ? 'online' : 'eclipse'
      } else if (p.idx < op + sb) {
        status = 'standby'
      } else {
        status = 'offline'
      }
      const id = `SAT-${String(p.idx + 1).padStart(pad, '0')}`
      return { ...p, status, id }
    })
  }, [positions, snap])
}

function bucketCounts(snap: FleetSnapshot | null, total: number) {
  if (!snap) {
    return { operational: total, standby: 0, offline: 0 }
  }
  const operational = Math.max(0, Math.min(total, snap.online + snap.eclipse))
  const standby     = Math.max(0, Math.min(total - operational, snap.standby))
  const offline     = Math.max(0, total - operational - standby)
  return { operational, standby, offline }
}
