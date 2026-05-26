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
  /** Total CAPEX (constellation-wide) in USD millions. */
  capexUsdM: number
  /** Per-sat all-in cost in USD millions. Headline cost-per-asset. */
  capexPerSatUsdM: number
  /** Cost of getting the fleet to orbit, USD millions (rockets only). */
  launchUsdM: number
  /** Annual ground ops + bandwidth + station-keeping, USD M/yr. */
  opexUsdMPerYr: number
  /** Aggregate effective compute, PFLOPS. */
  computePflops: number
  /** Total constellation electrical draw at design (sunlit), kW. */
  powerKw: number
  /** Total launched payload mass, tonnes. */
  launchMassT: number
  /** Per-sat design lifetime, years. */
  satLifetimeYr: number
  /** Break-even horizon vs comparable ground capacity, years. */
  paybackYr: number
}

const TABLE: Record<string, CostPreset> = {
  starlink_shell1: {
    id: 'starlink_shell1',
    capexUsdM: 9800,
    capexPerSatUsdM: 6.2,
    launchUsdM: 1200,
    opexUsdMPerYr: 410,
    computePflops: 12_400,
    powerKw: 1_584,
    launchMassT: 462,
    satLifetimeYr: 5,
    paybackYr: 4.2,
  },
  oneweb: {
    id: 'oneweb',
    capexUsdM: 3300,
    capexPerSatUsdM: 5.1,
    launchUsdM: 720,
    opexUsdMPerYr: 180,
    computePflops: 2_700,
    powerKw: 540,
    launchMassT: 95,
    satLifetimeYr: 7,
    paybackYr: 5.8,
  },
  gps_iir: {
    id: 'gps_iir',
    capexUsdM: 1200,
    capexPerSatUsdM: 50,
    launchUsdM: 290,
    opexUsdMPerYr: 95,
    computePflops: 80,
    powerKw: 36,
    launchMassT: 48,
    satLifetimeYr: 12,
    paybackYr: 9.5,
  },
  iridium_next: {
    id: 'iridium_next',
    capexUsdM: 2200,
    capexPerSatUsdM: 33,
    launchUsdM: 480,
    opexUsdMPerYr: 140,
    computePflops: 540,
    powerKw: 230,
    launchMassT: 56,
    satLifetimeYr: 10,
    paybackYr: 6.8,
  },
  single_iss: {
    id: 'single_iss',
    capexUsdM: 60,
    capexPerSatUsdM: 60,
    launchUsdM: 22,
    opexUsdMPerYr: 14,
    computePflops: 0.9,
    powerKw: 4,
    launchMassT: 0.8,
    satLifetimeYr: 8,
    paybackYr: 12.0,
  },
}

/** Per-sat fallback — used when a preset id isn't in TABLE. Scales by total. */
function synthesise(id: string, total: number): CostPreset {
  const perSat = 12.5
  const launchPerT = 5.5
  const massPerSatT = 0.28
  const totalMassT = total * massPerSatT
  return {
    id,
    capexUsdM:        Math.round(total * perSat),
    capexPerSatUsdM:  perSat,
    launchUsdM:       Math.round(totalMassT * launchPerT),
    opexUsdMPerYr:    Math.round(total * 0.45),
    computePflops:    Math.round(total * 6.2),
    powerKw:          Math.round(total * 1.0),
    launchMassT:      Math.round(totalMassT),
    satLifetimeYr:    7,
    paybackYr:        6.5,
  }
}

export function getCostPreset(id: string, totalSats: number): CostPreset {
  return TABLE[id] ?? synthesise(id, totalSats)
}
