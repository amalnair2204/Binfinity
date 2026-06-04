'use client'
import BinfinityMap    from '../map/BinfinityMap'
import FleetPanel      from '../panels/FleetPanel'
import BinStatsPanel   from '../panels/BinStatsPanel'
import AlertsPanel     from '../panels/AlertsPanel'
import MLPanel         from '../panels/MLPanel'
import CalibrationPanel from '../panels/CalibrationPanel'
import useDashboardStore from '../../store/dashboardStore'

export default function DashboardShell() {
  const calibrationVisible = useDashboardStore((s) => s.calibrationVisible)

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* Middle row: map + fleet panel */}
      <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0 }}>
        <div className="flex-1 relative overflow-hidden">
          <BinfinityMap />
        </div>
        <FleetPanel />
      </div>

      {/* Bottom strip — 240px fixed */}
      <div className="flex border-t border-ops-border shrink-0" style={{ height: 240 }}>
        <BinStatsPanel />
        <div className="flex flex-1 overflow-hidden" style={{ minWidth: 0 }}>
          <div className="flex-1 border-r border-ops-border overflow-hidden">
            <AlertsPanel />
          </div>
          <div className="flex-1 overflow-hidden">
            <MLPanel />
          </div>
        </div>
      </div>

      {/* Calibration panel — toggled by C key */}
      {calibrationVisible && (
        <div
          className="border-t border-ops-border shrink-0 overflow-hidden"
          style={{ height: 300 }}
        >
          <CalibrationPanel />
        </div>
      )}
    </div>
  )
}
