import React from 'react'
import useDriverStore from '../store/driverStore.js'

/**
 * Truck load bar with capacity warning.
 * Colour changes: green → yellow at 70 %, red at 85 %.
 */
export default function TruckStatus() {
  const loadLiters = useDriverStore((s) => s.loadLiters)
  const capacityLiters = useDriverStore((s) => s.capacityLiters)

  const pct = Math.min((loadLiters / (capacityLiters || 10_000)) * 100, 100)
  const isNearFull = pct >= 85
  const isWarning = pct >= 70 && !isNearFull
  const barClass = isNearFull
    ? 'bg-red-500'
    : isWarning
      ? 'bg-yellow-400'
      : 'bg-app-green'
  const labelClass = isNearFull ? 'text-red-400' : 'text-app-secondary'

  return (
    <div className="mx-4 px-4 py-3 bg-app-card rounded-xl border border-app-border">
      <div className="flex justify-between items-center mb-2">
        <span className="text-app-secondary text-xs font-bold uppercase tracking-wider">
          Truck Load
        </span>
        <span className={`text-sm font-bold ${labelClass}`}>
          {Math.round(loadLiters).toLocaleString()} / {capacityLiters.toLocaleString()} L
        </span>
      </div>

      <div className="h-3 bg-app-bg rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${barClass}`}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>

      {isNearFull && (
        <p className="text-red-400 text-xs font-bold mt-2 uppercase tracking-wide">
          ⚠ Nearly full — dump yard stop incoming
        </p>
      )}
    </div>
  )
}
