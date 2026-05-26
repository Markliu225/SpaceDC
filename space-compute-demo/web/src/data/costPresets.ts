/**
 * costPresets — per-constellation TCO / capacity profiles.
 *
 * Numbers are illustrative demo figures — sourced from publicly-cited
 * estimates (Starlink unit cost / Falcon launch cost / GPU TDP datasheets)
 * and rounded to round-number sticker values so the panel shows clean
 * "press kit"-style numbers rather than spurious precision.
 *
 * Per-preset fields:
 *  - capexUsdM     : total CAPEX = sats × unit_cost + launch_count × launch_cost
 *  - opexUsdMPerYr : ground ops + station-keeping + bandwidth fees
 *  - computePflops : aggregate effective PFLOPS at design power
 *  - powerKw       : total constellation electrical draw (sun-side)
 *  - launchMassT   : total launched payload mass in tonnes
 *  - paybackYr     : break-even horizon vs comparable ground capacity
 *
 * Falls back to a synthesised entry when a preset id isn't tabled — keeps
 * the panel useful while the catalogue grows.
 */
export interface CostPreset {
  id: string
  capexUsdM: number
  opexUsdMPerYr: number
  computePflops: number
  powerKw: number
  launchMassT: number
  paybackYr: number
}

const TABLE: Record<string, CostPreset> = {
  starlink_shell1: {
    id: 'starlink_shell1',
    capexUsdM: 9800,
    opexUsdMPerYr: 410,
    computePflops: 12_400,
    powerKw: 1_584,
    launchMassT: 462,
    paybackYr: 4.2,
  },
  oneweb: {
    id: 'oneweb',
    capexUsdM: 3300,
    opexUsdMPerYr: 180,
    computePflops: 2_700,
    powerKw: 540,
    launchMassT: 95,
    paybackYr: 5.8,
  },
  gps_iir: {
    id: 'gps_iir',
    capexUsdM: 1200,
    opexUsdMPerYr: 95,
    computePflops: 80,
    powerKw: 36,
    launchMassT: 48,
    paybackYr: 9.5,
  },
  iridium_next: {
    id: 'iridium_next',
    capexUsdM: 2200,
    opexUsdMPerYr: 140,
    computePflops: 540,
    powerKw: 230,
    launchMassT: 56,
    paybackYr: 6.8,
  },
  single_iss: {
    id: 'single_iss',
    capexUsdM: 60,
    opexUsdMPerYr: 14,
    computePflops: 0.9,
    powerKw: 4,
    launchMassT: 0.8,
    paybackYr: 12.0,
  },
}

/** Per-sat fallback — used when a preset id isn't in TABLE. Scales by total. */
function synthesise(id: string, total: number): CostPreset {
  return {
    id,
    capexUsdM: Math.round(total * 12.5),         // ~$12.5M per sat all-in
    opexUsdMPerYr: Math.round(total * 0.45),
    computePflops: Math.round(total * 6.2),
    powerKw: Math.round(total * 1.0),
    launchMassT: Math.round(total * 0.28),
    paybackYr: 6.5,
  }
}

export function getCostPreset(id: string, totalSats: number): CostPreset {
  return TABLE[id] ?? synthesise(id, totalSats)
}
