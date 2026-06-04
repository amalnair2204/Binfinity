'use client'

export default function StatCard({ label, value, sub, color = '#c8d8e8', trend }) {
  const trendColor = trend > 0 ? '#ff3355' : trend < 0 ? '#00ff88' : '#4a6280'
  const trendArrow = trend > 0 ? '▲' : trend < 0 ? '▼' : '—'

  return (
    <div
      className="flex flex-col justify-between p-3 rounded border border-ops-border"
      style={{ background: '#0d1520', minWidth: 100 }}
    >
      <div className="text-ops-muted text-xs font-mono tracking-wider mb-1">{label}</div>
      <div className="font-mono font-bold tabular-nums" style={{ fontSize: 22, color }}>
        {value ?? '—'}
      </div>
      <div className="flex items-center gap-2 mt-1">
        {sub && <span className="text-ops-muted text-xs">{sub}</span>}
        {trend !== undefined && (
          <span className="text-xs font-mono" style={{ color: trendColor }}>
            {trendArrow}
          </span>
        )}
      </div>
    </div>
  )
}
