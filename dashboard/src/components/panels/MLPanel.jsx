'use client'
import useDashboardStore from '../../store/dashboardStore'
import { fillColor } from '../../lib/colorScale'

function PredRow({ pred }) {
  const urgency = pred.hours_until_critical
  const color = urgency < 1 ? '#ff3355' : urgency < 2 ? '#ff6600' : '#ffaa00'

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 border-b border-ops-border last:border-0 hover:bg-ops-border/20">
      <div
        className="shrink-0 w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      <span className="text-ops-cyan text-xs font-mono truncate flex-1">{pred.bin_id}</span>
      <span className="text-xs font-mono tabular-nums" style={{ color }}>
        {urgency < 0.1 ? '<6m' : urgency < 1 ? `${Math.round(urgency * 60)}m` : `${urgency.toFixed(1)}h`}
      </span>
      <span className="text-ops-muted text-xs font-mono tabular-nums w-10 text-right">
        {(pred.predicted_fill_pct ?? 0).toFixed(0)}%
      </span>
    </div>
  )
}

export default function MLPanel() {
  const predictions = useDashboardStore((s) => s.mlPredictions)

  const sorted = [...predictions].sort(
    (a, b) => a.hours_until_critical - b.hours_until_critical,
  )

  return (
    <div className="flex flex-col h-full bg-ops-bg">
      <div className="px-3 py-2 border-b border-ops-border shrink-0">
        <span className="text-ops-cyan text-xs font-mono font-bold tracking-wider">
          ML PREDICTIONS — AT RISK (4h)
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {sorted.length === 0 && (
          <div className="text-ops-muted text-xs text-center py-4">No at-risk bins</div>
        )}
        {sorted.map((pred) => (
          <PredRow key={pred.bin_id} pred={pred} />
        ))}
      </div>
    </div>
  )
}
