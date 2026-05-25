import type { ReactNode, HTMLAttributes } from 'react'

/**
 * Card primitive — the single styled surface. Every panel composes itself
 * out of this; do NOT re-derive the card recipe in panel CSS. The recipe is:
 *   - vertical gradient fill (lighter top → darker bottom)
 *   - 1px subtle border (weak by default, med on hover)
 *   - inset top highlight + soft drop shadow
 *   - 10px radius, 16/18px padding
 *
 * Use `selected` to apply the cyan focused-card ring + glow.
 */
export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children?: ReactNode
  /** Apply selected glow (cyan ring + soft outer halo). */
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
    ? 'border-border-glow shadow-card-glow'
    : 'border-border-weak shadow-card hover:border-border-med hover:shadow-card-hover'
  return (
    <div
      {...rest}
      className={`relative rounded-[10px] border bg-card ${padding} transition-[border-color,box-shadow] duration-150 ${ring} ${className}`}
    >
      {children}
    </div>
  )
}
