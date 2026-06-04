'use client'
import useDashboardStore from '../../store/dashboardStore'
import StatCard         from '../cards/StatCard'
import FleetLoadBar     from '../charts/FleetLoadBar'
import ZoneDensityChart from '../charts/ZoneDensityChart'

export default function BinStatsPanel() {
  const fleetStats = useDashboardStore((s) => s.fleetStats)
  const routes     = useDashboardStore((s) => s.routes)

  const s = fleetStats || {}

  const totalDist = routes.reduce((sum, r) => sum + (r.total_distance_m ?? 0), 0)
  const distKm    = (totalDist / 1000).toFixed(1)

  return (
    <div
      className="border-r border-ops-border flex flex-col shrink-0 overflow-hidden"
      style={{ width: 460, background: '#080c10' }}
    >
      <div className="px-3 py-2 border-b border-ops-border shrink-0">
        <span className="text-ops-cyan text-xs font-mono font-bold tracking-wider">
          BIN STATS
        </span>
      </div>

      {/* KPI row */}
      <div className="flex gap-1.5 px-2 pt-2 shrink-0">
        <StatCard label="TOTAL BINS"  value={s.total}          color="#c8d8e8" />
        <StatCard label="FLAGGED"     value={s.flagged}        color="#ffaa00" />
        <StatCard label="OVERFLOW"    value={s.overflow_risk}  color="#ff3355" />
        <StatCard label="ROUTES KM"   value={distKm}           color="#00d4ff" sub="km today" />
      </div>

      {/* Charts */}
      <div className="flex flex-1 gap-0 overflow-hidden min-h-0 px-2 pb-2 pt-1">
        <div className="flex-1 min-w-0">
          <div className="text-ops-muted text-xs font-mono mb-0.5">TRUCK LOAD</div>
          <FleetLoadBar height={100} />
        </div>
        <div className="flex-1 min-w-0 ml-2">
          <div className="text-ops-muted text-xs font-mono mb-0.5">ZONES ≥75%</div>
          <ZoneDensityChart height={100} />
        </div>
      </div>
    </div>
  )
}
