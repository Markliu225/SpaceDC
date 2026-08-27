import type { ReactNode, HTMLAttributes } from 'react'

/**
 * Card primitive — the single styled surface. Every panel composes itself
 * out of this; do NOT re-derive the card recipe in panel CSS. The recipe is:
 *   - flat surface fill (bg.card)
 *   - 1px subtle border (weak by default, med on hover)
 *   - soft drop shadow tinted to the background hue
 *   - 8px radius, 16/18px padding
 *
 * Use `selected` to apply the accent focus ring (1px, no halo).
 */
export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children?: ReactNode
  /** Apply the selected ring (accent, 1px, no halo). */
  selected?: boolean
  /** Tighten padding for dense KPI tiles. */
  dense?: boolean
}

export function Card({
  children,
  selected,
  dense,
  className = '',
  ...rest
}: CardProps) {
  const padding = dense ? 'px-4 py-3.5' : 'px-[18px] py-4'
  const ring = selected
    ? 'border-border-focus shadow-card-focus'
    : 'border-border-weak shadow-card hover:border-border-med hover:shadow-card-hover'
  return (
    <div
      {...rest}
      className={`relative rounded-lg border bg-card ${padding} transition-[border-color,box-shadow] duration-150 ${ring} ${className}`}
    >
      {children}
    </div>
  )
}
