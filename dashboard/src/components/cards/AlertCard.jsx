'use client'
import { timeAgo } from '../../lib/timeAgo'

const EVENT_COLOR = {
  overflow_alert:    '#ff3355',
  new_bins_flagged:  '#ffaa00',
  manual_override:   '#00d4ff',
  truck_capacity_hit:'#ff6600',
  default:           '#4a6280',
}

const EVENT_LABEL = {
  overflow_alert:    'OVERFLOW',
  new_bins_flagged:  'BINS FLAGGED',
  manual_override:   'MANUAL',
  truck_capacity_hit:'CAPACITY',
}

export default function AlertCard({ alert }) {
  const color = EVENT_COLOR[alert.event_type] ?? EVENT_COLOR.default
  const label = EVENT_LABEL[alert.event_type] ?? alert.event_type?.toUpperCase()

  return (
    <div className="flex items-start gap-2 px-3 py-2 border-b border-ops-border last:border-0 hover:bg-ops-border/20">
      <div
        className="mt-0.5 shrink-0 w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono font-bold" style={{ color }}>{label}</span>
          {alert.affected_truck_id && (
            <span className="text-ops-cyan text-xs font-mono">{alert.affected_truck_id}</span>
          )}
          {alert.affected_bin_id && (
            <span className="text-ops-text text-xs font-mono truncate">{alert.affected_bin_id}</span>
          )}
        </div>
        <div className="text-ops-muted text-xs mt-0.5">
          {timeAgo(alert.triggered_at)}
          {alert.priority != null && (
            <span className="ml-2 font-mono">P{alert.priority}</span>
          )}
        </div>
      </div>
    </div>
  )
}
