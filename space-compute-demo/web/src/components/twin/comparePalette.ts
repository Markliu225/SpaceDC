/** Variant line hues for the live what-if comparison — shared by the
 *  ComparePanel value chips and the TimeSeriesStrip curve overlays so a
 *  variant wears ONE color everywhere. Assigned by pick order, never cycled.
 *
 *  Mid-brightness, desaturated on purpose (no neon, no glow — distinction
 *  comes from hue separation + solid strokes): blue / amber / magenta /
 *  teal. Blue is the `info` token, amber + magenta are ribbon hues, teal is
 *  derived in the same hue at ≤ 65 % HSL saturation; all four keep ≥ 3:1
 *  contrast on surface #10141A. The magenta↔teal deutan pair is the
 *  weakest, which is legal with secondary encoding — the strip's
 *  per-variant dot+value readouts and the legend provide it (and that pair
 *  only appears at all in 4-variant comparisons). */
export const COMPARE_PALETTE = ['#7A8CD8', '#E0B65A', '#D57BC9', '#3FA89C']
