'use client'
import useDashboardStore from '../../store/dashboardStore'

function StatRow({ label, value, color = '#c8d8e8' }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-ops-muted text-xs">{label}</span>
      <span className="font-mono text-xs font-bold tabular-nums" style={{ color }}>
        {value ?? '—'}
      </span>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="p-3 border-b border-ops-border">
      <div className="text-ops-cyan text-xs font-mono font-bold mb-2 tracking-wider">
        {title}
      </div>
      {children}
    </div>
  )
}

export default function Sidebar() {
  const fleetStats = useDashboardStore((s) => s.fleetStats)
  const trucks     = useDashboardStore((s) => s.trucks)
  const routes     = useDashboardStore((s) => s.routes)
  const bins       = useDashboardStore((s) => s.bins)

  const s = fleetStats || {}
  const binCount = bins?.features?.length ?? '—'

  return (
    <div
      className="bg-ops-surface border-r border-ops-border flex flex-col shrink-0 overflow-hidden"
      style={{ width: 220 }}
    >
      <Section title="BIN FLEET">
        <StatRow label="Total"         value={binCount} />
        <StatRow label="Operational"   value={s.operational}    color="#00ff88" />
        <StatRow label="Flagged"       value={s.flagged}        color="#ffaa00" />
        <StatRow label="Overflow Risk" value={s.overflow_risk}  color="#ff3355" />
        <StatRow label="Faulted"       value={s.faulted}        color="#ff6600" />
        <StatRow label="Tipped"        value={s.tipped}         color="#ff3355" />
        <StatRow label="Low Battery"   value={s.low_battery}    color="#ffaa00" />
      </Section>

      <Section title="TRUCKS">
        <StatRow label="Registered"  value={trucks.length}         color="#c8d8e8" />
        <StatRow label="On Route"    value={routes.length}         color="#00ff88" />
        <StatRow label="Idle"        value={Math.max(0, trucks.length - routes.length)} color="#00d4ff" />
      </Section>

      <div className="flex-1" />

      <div className="p-3 border-t border-ops-border">
        <div className="text-ops-muted text-xs text-center tracking-wider opacity-50">
          BINFINITY v9.0
        </div>
      </div>
    </div>
  )
}
