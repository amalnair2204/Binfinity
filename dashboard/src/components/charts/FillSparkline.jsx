'use client'
import { AreaChart, Area, YAxis, ResponsiveContainer, Tooltip } from 'recharts'
import { fillColor } from '../../lib/colorScale'

export default function FillSparkline({ data, height = 48 }) {
  if (!data?.length) return null

  const lastPct = data[data.length - 1]?.v ?? 0
  const color   = fillColor(lastPct)

  const chartData = data.map((d) => ({ v: d.v }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={chartData} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="fillGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0.0} />
          </linearGradient>
        </defs>
        <YAxis domain={[0, 100]} hide />
        <Tooltip
          contentStyle={{ background: '#0d1520', border: '1px solid #1a2535', fontSize: 11 }}
          labelStyle={{ display: 'none' }}
          formatter={(v) => [`${v.toFixed(1)}%`, 'Fill']}
        />
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          fill="url(#fillGrad)"
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
