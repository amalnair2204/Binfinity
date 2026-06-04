'use client'
import { FILL_LEGEND } from '../../lib/colorScale'

export default function MapLegend() {
  return (
    <div
      className="absolute bottom-8 right-2 flex flex-col gap-1 rounded border border-ops-border p-2"
      style={{ background: 'rgba(13,21,32,0.9)', zIndex: 10 }}
    >
      <div className="text-ops-muted text-xs font-mono tracking-wider mb-0.5">
        FILL LEVEL
      </div>
      {FILL_LEGEND.map(({ label, color, desc }) => (
        <div key={label} className="flex items-center gap-2">
          <span
            className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
            style={{ backgroundColor: color }}
          />
          <span className="text-ops-text text-xs font-mono">{label}</span>
          <span className="text-ops-muted text-xs">{desc}</span>
        </div>
      ))}
      <div className="mt-1 pt-1 border-t border-ops-border flex items-center gap-2">
        <span
          className="inline-block w-2.5 h-2.5 rounded-full border-2 shrink-0"
          style={{ borderColor: '#ffaa00', backgroundColor: 'transparent' }}
        />
        <span className="text-ops-muted text-xs font-mono">FLAGGED</span>
      </div>
      <div className="flex items-center gap-2">
        <span
          className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
          style={{ backgroundColor: '#00d4ff' }}
        />
        <span className="text-ops-muted text-xs font-mono">TRUCK</span>
      </div>
    </div>
  )
}
