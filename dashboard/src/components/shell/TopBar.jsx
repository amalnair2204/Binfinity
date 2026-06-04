'use client'
import { useEffect, useState } from 'react'
import useDashboardStore from '../../store/dashboardStore'
import { formatTime } from '../../lib/timeAgo'

const WS_COLOR = {
  connected:    '#00ff88',
  reconnecting: '#ffaa00',
  disconnected: '#ff3355',
}

const EVENT_ICONS = {
  overflow_alert:     '⚠',
  tip_over:           '⚡',
  truck_capacity_hit: '▲',
  truck_shift_ending: '⏰',
  new_bins_flagged:   '⚑',
  manual_override:    '↺',
}

const EVENT_COLORS = {
  overflow_alert:     '#ff3355',
  tip_over:           '#ff3355',
  truck_capacity_hit: '#ff6600',
  truck_shift_ending: '#ffaa00',
  new_bins_flagged:   '#ffaa00',
  manual_override:    '#00d4ff',
}

function TickerStrip({ alerts }) {
  const items = alerts.slice(0, 10)
  if (items.length === 0) return null

  const doubled = [...items, ...items]

  return (
    <div
      className="border-t border-ops-border overflow-hidden"
      style={{ height: 22, background: '#050810', position: 'relative' }}
    >
      <div className="ticker-track" style={{ paddingTop: 4 }}>
        {doubled.map((alert, i) => {
          const icon  = EVENT_ICONS[alert.event_type] ?? '•'
          const color = EVENT_COLORS[alert.event_type] ?? '#4a6280'
          const parts = [
            alert.affected_bin_id,
            alert.event_type?.replace(/_/g, ' '),
            alert.affected_truck_id && `(${alert.affected_truck_id})`,
          ].filter(Boolean).join(' ')

          return (
            <span key={i} style={{ color, fontSize: 10, fontFamily: 'monospace', marginRight: 28 }}>
              {icon} {parts}
            </span>
          )
        })}
      </div>
    </div>
  )
}

export default function TopBar() {
  const [now, setNow] = useState(() => new Date())
  const alerts   = useDashboardStore((s) => s.alerts)
  const wsStatus = useDashboardStore((s) => s.wsStatus)

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  const criticalCount = alerts.filter(
    (a) => a.event_type === 'overflow_alert' || a.priority >= 3,
  ).length

  return (
    <div className="shrink-0 border-b border-ops-border" style={{ background: '#0a1018' }}>
      <div className="flex items-center justify-between px-4" style={{ height: 40 }}>
        <div className="flex items-center gap-3">
          <span className="text-ops-green font-mono text-sm font-bold tracking-widest">
            BINFINITY OPS
          </span>
          <span className="text-ops-muted text-xs tracking-wider">COMMAND CENTER</span>
        </div>

        <div className="flex items-center gap-6">
          {criticalCount > 0 && (
            <div
              className="flex items-center gap-1.5 px-2 py-0.5 rounded"
              style={{ background: 'rgba(255,51,85,0.15)', border: '1px solid rgba(255,51,85,0.4)' }}
            >
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-ops-red animate-pulse" />
              <span className="text-ops-red text-xs font-mono font-bold">
                {criticalCount} CRITICAL
              </span>
            </div>
          )}

          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: WS_COLOR[wsStatus] }}
            />
            <span className="text-ops-muted text-xs font-mono uppercase tracking-wider">
              {wsStatus}
            </span>
          </div>

          <span className="text-ops-cyan text-xs font-mono tabular-nums">
            {formatTime(now)}
          </span>
        </div>
      </div>

      <TickerStrip alerts={alerts} />
    </div>
  )
}
