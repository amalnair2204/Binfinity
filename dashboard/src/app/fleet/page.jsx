'use client'
import useDashboardStore from '../../store/dashboardStore'
import { fillColor }     from '../../lib/colorScale'

const STATUS_COLOR = {
  active:  '#00ff88',
  idle:    '#00d4ff',
  full:    '#ffaa00',
  offline: '#4a6280',
  unknown: '#4a6280',
}

function LoadBar({ pct }) {
  const color = pct >= 90 ? '#ff3355' : pct >= 70 ? '#ffaa00' : '#00ff88'
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-ops-muted">Load</span>
        <span className="text-ops-text tabular-nums font-mono">{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full" style={{ background: '#1a2535' }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

function StopList({ stops }) {
  const bins = (stops ?? []).filter((s) => s.node_type !== 'depot')
  if (bins.length === 0) return <div className="text-ops-muted text-xs">No stops</div>
  return (
    <div className="space-y-0.5 max-h-28 overflow-y-auto">
      {bins.map((stop, i) => {
        const isDump = stop.node_type === 'dump_yard'
        return (
          <div key={stop.node_id ?? i} className="flex items-center gap-2 text-xs font-mono">
            <span style={{ color: isDump ? '#ffaa00' : '#4a6280', fontSize: 9 }}>
              {isDump ? '⛽' : '●'}
            </span>
            <span className="text-ops-text truncate flex-1">{stop.node_id}</span>
            {stop.fill_pct != null && (
              <span style={{ color: fillColor(stop.fill_pct), fontSize: 9 }} className="tabular-nums">
                {stop.fill_pct.toFixed(0)}%
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

function TruckDetailCard({ truck, route }) {
  const selectedId         = useDashboardStore((s) => s.selectedTruckId)
  const setSelectedTruckId = useDashboardStore((s) => s.setSelectedTruckId)
  const isSelected = selectedId === truck.truck_id

  const loadPct   = truck.capacity_liters > 0
    ? Math.round((truck.load_liters / truck.capacity_liters) * 100)
    : 0
  const statusColor = STATUS_COLOR[truck.status] ?? '#4a6280'
  const binStops    = (route?.stops ?? []).filter((s) => s.node_type === 'bin')

  return (
    <div
      className="border rounded p-3 cursor-pointer transition-colors"
      style={{
        background:   isSelected ? '#1a2535' : '#0d1520',
        borderColor:  isSelected ? '#00d4ff' : '#1a2535',
        fontFamily:   'JetBrains Mono, Courier New, monospace',
      }}
      onClick={() => setSelectedTruckId(isSelected ? null : truck.truck_id)}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-ops-cyan text-sm font-bold">{truck.truck_id}</span>
        <span className="text-xs font-bold" style={{ color: statusColor }}>
          ● {(truck.status ?? 'UNKNOWN').toUpperCase()}
        </span>
      </div>

      {/* Load bar */}
      <div className="mb-2">
        <LoadBar pct={loadPct} />
      </div>

      {/* Capacity figures */}
      <div className="flex justify-between text-xs text-ops-muted mb-2">
        <span>Capacity</span>
        <span className="text-ops-text tabular-nums font-mono">
          {Math.round(truck.load_liters ?? 0)}L / {truck.capacity_liters ?? 10_000}L
        </span>
      </div>

      {/* Route summary */}
      <div className="flex justify-between text-xs text-ops-muted mb-2">
        <span>Bin stops left</span>
        <span className="text-ops-text tabular-nums font-mono">{binStops.length}</span>
      </div>

      {/* Position */}
      {truck.position && (
        <div className="text-xs text-ops-muted font-mono tabular-nums mb-2">
          {truck.position.lat.toFixed(4)}, {truck.position.lng.toFixed(4)}
        </div>
      )}

      {/* Stop list — shown when selected */}
      {isSelected && route && (
        <div className="mt-2 pt-2 border-t border-ops-border">
          <div className="text-ops-muted text-xs tracking-wider mb-1.5">ROUTE STOPS</div>
          <StopList stops={route.stops} />
        </div>
      )}
    </div>
  )
}

export default function FleetPage() {
  const trucks     = useDashboardStore((s) => s.trucks)
  const routes     = useDashboardStore((s) => s.routes)
  const fleetStats = useDashboardStore((s) => s.fleetStats)

  const routeByTruck = Object.fromEntries(routes.map((r) => [r.truck_id, r]))

  const active  = trucks.filter((t) => t.status === 'active').length
  const idle    = trucks.filter((t) => t.status === 'idle').length
  const full    = trucks.filter((t) => t.status === 'full').length
  const offline = trucks.filter((t) => t.status === 'offline' || t.status === 'unknown').length

  return (
    <div className="flex flex-col h-full overflow-hidden bg-ops-bg font-mono">

      {/* Page header */}
      <div
        className="flex items-center justify-between px-4 border-b border-ops-border shrink-0"
        style={{ height: 40, background: '#0a1018' }}
      >
        <span className="text-ops-cyan text-xs font-bold tracking-widest">
          FLEET MANAGEMENT — {trucks.length} TRUCKS
        </span>
        <div className="flex items-center gap-4 text-xs">
          <span style={{ color: '#00ff88' }}>● {active} ACTIVE</span>
          <span style={{ color: '#00d4ff' }}>● {idle} IDLE</span>
          <span style={{ color: '#ffaa00' }}>● {full} FULL</span>
          {offline > 0 && <span style={{ color: '#4a6280' }}>● {offline} OFFLINE</span>}
        </div>
      </div>

      {/* Stats strip */}
      {fleetStats && (
        <div className="flex border-b border-ops-border shrink-0" style={{ background: '#0d1520' }}>
          {[
            { label: 'Operational', value: fleetStats.operational, color: '#00ff88' },
            { label: 'Flagged',     value: fleetStats.flagged,     color: '#ffaa00' },
            { label: 'Overflow ⚠', value: fleetStats.overflow_risk, color: '#ff3355' },
            { label: 'Faulted',    value: fleetStats.faulted,     color: '#ff6600' },
            { label: 'Total Bins', value: fleetStats.total,       color: '#c8d8e8' },
          ].map(({ label, value, color }) => (
            <div key={label} className="flex-1 px-3 py-2 border-r border-ops-border last:border-0">
              <div className="text-ops-muted text-xs tracking-wider">{label}</div>
              <div className="font-bold text-sm tabular-nums" style={{ color }}>
                {value ?? '—'}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Truck grid */}
      <div className="flex-1 overflow-y-auto p-3">
        {trucks.length === 0 ? (
          <div className="flex items-center justify-center h-full text-ops-muted text-xs tracking-wider">
            NO TRUCKS REGISTERED
          </div>
        ) : (
          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}
          >
            {trucks.map((truck) => (
              <TruckDetailCard
                key={truck.truck_id}
                truck={truck}
                route={routeByTruck[truck.truck_id]}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
