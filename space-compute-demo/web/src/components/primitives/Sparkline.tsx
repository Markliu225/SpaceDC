import { useId, useMemo } from 'react'
import { AreaChart, Area, ResponsiveContainer } from 'recharts'
import { Num } from './Num'
import { colors } from '../../design/tokens'

/**
 * <Sparkline /> — used by Link / Traffic panels. Recharts <AreaChart>
 * with a quiet vertical under-tint (series color @ 0.18 → 0) under a
 * plain 1.5px stroke; no glow.
 */
export interface SparklineProps {
  title: string
  /** Latest 60 numeric samples. Component renders bottom-aligned area. */
  data: number[]
  /** Current value displayed in the header. */
  current: number
  /** Unit string e.g. "Mbps". */
  unit?: string
  /** Decimal places for the current header value. */
  digits?: number
  /** Hex color for stroke + gradient. Default: accent token. */
  color?: string
  /** Bottom-row evenly spaced timestamps. */
  timestamps?: string[]
}

export function Sparkline({
  title,
  data,
  current,
  unit,
  digits = 0,
  color = colors.accent,
  timestamps = [],
}: SparklineProps) {
  const gid = useId().replace(/:/g, '') // useId returns ":r0:"-style; sanitize for SVG id.
  const gradId = `spark-grad-${gid}`

  const chartData = useMemo(
    () => data.map((v, i) => ({ i, v })),
    [data],
  )

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          {title}
        </span>
        <span className="flex items-baseline">
          <Num
            value={current}
            digits={digits}
            // High tick-rate; don't lerp every second.
            animate={false}
            className="text-[18px] font-semibold text-text-hi"
          />
          {unit && <span className="ml-1 text-[12px] text-text-lo">{unit}</span>}
        </span>
      </div>

      <div className="h-[56px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.18} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="v"
              stroke={color}
              strokeWidth={1.5}
              fill={`url(#${gradId})`}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {timestamps.length === 3 && (
        <div className="flex justify-between text-[10px] tabular text-text-lo">
          {timestamps.map((t, i) => (
            <span key={`${t}-${i}`}>{t}</span>
          ))}
        </div>
      )}
    </div>
  )
}
