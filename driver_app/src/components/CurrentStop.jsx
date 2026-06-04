import React from 'react'
import useDriverStore from '../store/driverStore.js'

function formatEta(seconds) {
  if (!seconds || seconds <= 0) return null
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `~${h}h ${m}m`
  return `~${m} min`
}

/**
 * Primary stop card — glanceable in < 2 s.
 * Shows stop ID, type label, fill to collect, and ETA.
 */
export default function CurrentStop() {
  const stop = useDriverStore((s) => s.currentStop)

  if (!stop) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 text-center px-6 py-8">
        <div className="text-6xl mb-4 select-none">🎉</div>
        <p className="text-3xl font-black text-app-green">All stops done!</p>
        <p className="text-lg text-app-secondary mt-2">Return to depot</p>
      </div>
    )
  }

  const isBin = stop.node_type === 'bin'
  const isDump = stop.node_type === 'dump_yard'
  const typeLabel = isBin ? 'COLLECT BIN' : isDump ? 'DUMP YARD' : 'STOP'
  const eta = formatEta(stop.arrival_time_seconds)
  const fillL = stop.fill_collected_liters ?? 0

  return (
    <div className="bg-app-card rounded-2xl p-6 mx-4 border border-app-border shadow-2xl">
      {/* Type label */}
      <p className="text-app-secondary text-sm font-bold uppercase tracking-widest mb-2">
        {typeLabel}
      </p>

      {/* Stop ID — largest text on screen */}
      <p className="text-5xl font-black text-white tracking-tight leading-none break-all">
        {stop.node_id}
      </p>

      {/* Fill to collect */}
      {isBin && fillL > 0 && (
        <div className="mt-4 flex items-baseline gap-2">
          <span className="text-3xl font-black text-app-green">{Math.round(fillL)}L</span>
          <span className="text-app-secondary text-base">to collect</span>
        </div>
      )}

      {/* ETA */}
      {eta && (
        <div className="mt-4 flex items-center gap-3 border-t border-app-border pt-4">
          <svg className="w-5 h-5 text-app-secondary flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-app-secondary text-base">ETA</span>
          <span className="text-white text-xl font-bold">{eta}</span>
        </div>
      )}
    </div>
  )
}
