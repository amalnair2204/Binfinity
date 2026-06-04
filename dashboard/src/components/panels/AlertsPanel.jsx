'use client'
import useDashboardStore from '../../store/dashboardStore'
import AlertCard from '../cards/AlertCard'

export default function AlertsPanel() {
  const alerts = useDashboardStore((s) => s.alerts)

  return (
    <div className="flex flex-col h-full bg-ops-bg">
      <div className="px-3 py-2 border-b border-ops-border shrink-0">
        <span className="text-ops-cyan text-xs font-mono font-bold tracking-wider">
          ALERTS — {alerts.length}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {alerts.length === 0 && (
          <div className="text-ops-muted text-xs text-center py-4">No alerts</div>
        )}
        {alerts.map((alert) => (
          <AlertCard key={alert.event_id ?? `${alert.triggered_at}-${alert.event_type}`} alert={alert} />
        ))}
      </div>
    </div>
  )
}
