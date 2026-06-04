'use client'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer } from 'recharts'
import useDashboardStore from '../../store/dashboardStore'

const THRESHOLD = 75 // % — count bins at or above this as "high density"

export default function ZoneDensityChart({ height = 130 }) {
  const bins = useDashboardStore((s) => s.bins)

  if (!bins?.features?.length) {
    return (
      <div className="flex items-center justify-center h-full text-ops-muted text-xs">
        No bin data
      </div>
    )
  }

  // Group by zone_id and count bins above threshold
  const zoneMap = {}
  for (const f of bins.features) {
    const z = f.properties.zone_id ?? 'unknown'
    if (!zoneMap[z]) zoneMap[z] = { total: 0, high: 0 }
    zoneMap[z].total++
    if ((f.properties.fill_pct ?? 0) >= THRESHOLD) zoneMap[z].high++
  }

  const data = Object.entries(zoneMap)
    .map(([zone, counts]) => ({ zone, high: counts.high, total: counts.total }))
    .sort((a, b) => b.high - a.high)
    .slice(0, 10)

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }} barSize={14}>
        <XAxis
          dataKey="zone"
          tick={{ fontSize: 8, fill: '#4a6280', fontFamily: 'monospace' }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          allowDecimals={false}
          tick={{ fontSize: 9, fill: '#4a6280' }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{ background: '#0d1520', border: '1px solid #1a2535', fontSize: 11 }}
          formatter={(v, _n, { payload }) => [`${v} / ${payload.total}`, `≥${THRESHOLD}%`]}
          labelStyle={{ color: '#00d4ff', fontFamily: 'monospace', fontSize: 11 }}
        />
        <Bar dataKey="high" radius={[2, 2, 0, 0]} isAnimationActive={false}>
          {data.map((entry) => (
            <Cell
              key={entry.zone}
              fill={entry.high > 0 ? '#ff6600' : '#1a2535'}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
