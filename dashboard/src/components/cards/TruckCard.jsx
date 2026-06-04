'use client'
import useDashboardStore from '../../store/dashboardStore'

const STATUS_COLOR = {
  active:   '#00ff88',
  idle:     '#00d4ff',
  full:     '#ffaa00',
  offline:  '#4a6280',
  unknown:  '#4a6280',
}

export default function TruckCard({ truck, route }) {
  const setSelectedTruckId = useDashboardStore((s) => s.setSelectedTruckId)
  const selectedId         = useDashboardStore((s) => s.selectedTruckId)
  const isSelected = selectedId === truck.truck_id

  const loadPct = truck.capacity_liters > 0
    ? Math.round((truck.load_liters / truck.capacity_liters) * 100)
    : 0

  const statusColor = STATUS_COLOR[truck.status] ?? '#4a6280'
  const stopsLeft = route
    ? route.stops.filter((s) => s.node_type === 'bin').length
    : 0

  return (
    <div
      className="p-2.5 rounded border cursor-pointer transition-colors"
      style={{
        background: isSelected ? '#1a2535' : '#0d1520',
        borderColor: isSelected ? '#00d4ff' : '#1a2535',
      }}
      onClick={() => setSelectedTruckId(isSelected ? null : truck.truck_id)}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-ops-cyan text-xs font-mono font-bold">{truck.truck_id}</span>
        <span className="text-xs font-mono" style={{ color: statusColor }}>
          {truck.status?.toUpperCase() ?? 'UNKNOWN'}
        </span>
      </div>

      {/* Load bar */}
      <div className="mb-1.5">
        <div className="flex justify-between mb-0.5">
          <span className="text-ops-muted text-xs">Load</span>
          <span className="text-ops-text text-xs font-mono tabular-nums">{loadPct}%</span>
        </div>
        <div className="h-1.5 rounded-full" style={{ background: '#1a2535' }}>
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${loadPct}%`,
              background: loadPct >= 90 ? '#ff3355' : loadPct >= 70 ? '#ffaa00' : '#00ff88',
            }}
          />
        </div>
      </div>

      <div className="flex items-center justify-between text-xs">
        <span className="text-ops-muted">Stops left</span>
        <span className="font-mono text-ops-text tabular-nums">{stopsLeft}</span>
      </div>

      {truck.position && (
        <div className="mt-1 text-xs text-ops-muted font-mono tabular-nums">
          {truck.position.lat.toFixed(4)}, {truck.position.lng.toFixed(4)}
        </div>
      )}
    </div>
  )
}
