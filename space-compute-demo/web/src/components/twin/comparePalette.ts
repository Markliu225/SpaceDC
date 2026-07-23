/** Variant line hues for the live what-if comparison — shared by the
 *  ComparePanel value chips and the TimeSeriesStrip curve overlays so a
 *  variant wears ONE color everywhere. Assigned by pick order, never cycled.
 *
 *  Mid-brightness on purpose (no neon, no glow — distinction comes from
 *  hue separation + solid 2.4 px strokes): blue / amber / magenta / teal,
 *  validated via the dataviz six-checks script on surface #0A0F1E — all
 *  four inside the dark lightness band, chroma ≥ 0.1, contrast ≥ 3:1.
 *  The magenta↔teal deutan pair sits in the CVD floor band (ΔE 9.4),
 *  which is legal with secondary encoding — the strip's per-variant
 *  dot+value readouts and the legend provide it (and that pair only
 *  appears at all in 4-variant comparisons). */
export const COMPARE_PALETTE = ['#3B82F6', '#D97706', '#EC4899', '#0D9488']
