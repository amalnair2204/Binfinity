import React from 'react'
import useDriverStore from '../store/driverStore.js'

/**
 * Compact next-stop preview strip shown below CurrentStop.
 * Renders nothing when there is no following stop.
 */
export default function NextStop() {
  const stop = useDriverStore((s) => s.nextStop)

  if (!stop) return null

  const isDump = stop.node_type === 'dump_yard'
  const icon = isDump ? '⛽' : '🗑'
  const label = isDump ? 'NEXT: DUMP' : 'NEXT BIN'

  return (
    <div className="mx-4 px-4 py-3 bg-app-card/50 rounded-xl border border-app-border flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-xl select-none">{icon}</span>
        <div>
          <p className="text-app-secondary text-xs font-bold uppercase tracking-wider">{label}</p>
          <p className="text-white text-lg font-bold mt-0.5 leading-none">{stop.node_id}</p>
        </div>
      </div>
      <svg className="w-5 h-5 text-app-secondary flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
      </svg>
    </div>
  )
}
