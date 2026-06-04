import React from 'react'
import useDriverStore from '../store/driverStore.js'

/**
 * Slim banner shown when the browser reports no network connectivity.
 * Route data is served from the in-app cache; collections are queued.
 */
export default function OfflineIndicator() {
  const isOnline = useDriverStore((s) => s.isOnline)

  if (isOnline) return null

  return (
    <div className="bg-yellow-600 text-black text-center py-1.5 px-4 text-xs font-black uppercase tracking-wider z-40">
      OFFLINE — Route cached · Collections will sync on reconnect
    </div>
  )
}
