/** Variant line hues for the live what-if comparison — shared by the
 *  ComparePanel value chips and the TimeSeriesStrip curve overlays so a
 *  variant wears ONE color everywhere. Validated (dataviz six-checks)
 *  against the app's dark surface #0A0F1E: OKLCH L inside the dark band,
 *  chroma ≥ 0.1, worst adjacent CVD ΔE 38.7, ≥ 3:1 contrast. Assigned by
 *  pick order, never cycled. */
export const COMPARE_PALETTE = ['#3B82F6', '#D97706', '#8B5CF6', '#0D9488']
