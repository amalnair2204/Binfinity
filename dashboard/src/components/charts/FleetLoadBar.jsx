'use client'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer } from 'recharts'
import useDashboardStore from '../../store/dashboardStore'

function loadColor(pct) {
  if (pct >= 90) return '#ff3355'
  if (pct >= 70) return '#ffaa00'
  return '#00ff88'
}

export default function FleetLoadBar({ height = 140 }) {
  const trucks = useDashboardStore((s) => s.trucks)

  if (!trucks?.length) {
    return (
      <div className="flex items-center justify-center h-full text-ops-muted text-xs">
        No trucks
      </div>
    )
  }

  const data = trucks.map((t) => ({
    id: t.truck_id,
    pct: t.capacity_liters > 0
      ? Math.round((t.load_liters / t.capacity_liters) * 100)
      : 0,
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }} barSize={16}>
        <XAxis
          dataKey="id"
          tick={{ fontSize: 9, fill: '#4a6280', fontFamily: 'monospace' }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fontSize: 9, fill: '#4a6280' }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{ background: '#0d1520', border: '1px solid #1a2535', fontSize: 11 }}
          formatter={(v) => [`${v}%`, 'Load']}
          labelStyle={{ color: '#00d4ff', fontFamily: 'monospace' }}
        />
        <Bar dataKey="pct" radius={[2, 2, 0, 0]} isAnimationActive={false}>
          {data.map((entry) => (
            <Cell key={entry.id} fill={loadColor(entry.pct)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
