'use client'
import useDashboardStore from '../../store/dashboardStore'
import TruckCard from '../cards/TruckCard'

export default function FleetPanel() {
  const trucks = useDashboardStore((s) => s.trucks)
  const routes = useDashboardStore((s) => s.routes)

  const routeByTruck = Object.fromEntries(routes.map((r) => [r.truck_id, r]))

  return (
    <div
      className="bg-ops-surface border-l border-ops-border flex flex-col shrink-0 overflow-hidden"
      style={{ width: 300 }}
    >
      <div className="px-3 py-2 border-b border-ops-border shrink-0">
        <span className="text-ops-cyan text-xs font-mono font-bold tracking-wider">
          FLEET — {trucks.length} TRUCKS
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {trucks.length === 0 && (
          <div className="text-ops-muted text-xs text-center py-6">
            No trucks registered
          </div>
        )}
        {trucks.map((truck) => (
          <TruckCard
            key={truck.truck_id}
            truck={truck}
            route={routeByTruck[truck.truck_id]}
          />
        ))}
      </div>
    </div>
  )
}
