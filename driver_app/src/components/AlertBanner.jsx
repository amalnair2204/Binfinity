import React from 'react'
import useDriverStore from '../store/driverStore.js'

const SEVERITY = {
  error: 'bg-red-600 border-red-500 text-white',
  warning: 'bg-yellow-500 border-yellow-400 text-black',
  info: 'bg-blue-600 border-blue-500 text-white',
}

/**
 * Full-width banner overlay that shows the most recent active alert.
 * Rendered inside the ShiftPage's relative container so it sits above all content.
 */
export default function AlertBanner() {
  const alerts = useDriverStore((s) => s.alerts)
  const dismissAlert = useDriverStore((s) => s.dismissAlert)

  if (alerts.length === 0) return null

  const top = alerts[0]
  const cls = SEVERITY[top.severity] ?? SEVERITY.info

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`absolute top-0 left-0 right-0 z-50 border-b-2 ${cls} flex items-center justify-between px-4 py-3`}
    >
      <p className="text-base font-black leading-tight flex-1 pr-4">{top.message}</p>
      <button
        aria-label="Dismiss"
        className="text-2xl font-black leading-none opacity-80 active:opacity-100 flex-shrink-0"
        onClick={() => dismissAlert(top.id)}
      >
        ×
      </button>
    </div>
  )
}
