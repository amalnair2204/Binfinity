import React from 'react'
import useDriverStore from '../store/driverStore.js'

/**
 * Progress strip: "Stop N of M" with a green progress bar.
 *
 * Total = completed + remaining (allStops reflects server-synced remaining list).
 */
export default function RouteProgress() {
  const allStops = useDriverStore((s) => s.allStops)
  const stopsCompleted = useDriverStore((s) => s.stopsCompleted)

  const remaining = allStops.length
  const total = stopsCompleted + remaining

  if (total === 0) return null

  const current = Math.min(stopsCompleted + 1, total)
  const pct = total > 0 ? (stopsCompleted / total) * 100 : 0

  return (
    <div className="px-4 pb-1">
      <div className="flex justify-between items-center mb-1">
        <span className="text-app-secondary text-sm font-semibold">
          Stop {current} of {total}
        </span>
        <span className="text-app-secondary text-sm font-semibold">
          {stopsCompleted} done · {remaining} left
        </span>
      </div>
      <div className="h-2 bg-app-card rounded-full overflow-hidden">
        <div
          className="h-full bg-app-green rounded-full transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
