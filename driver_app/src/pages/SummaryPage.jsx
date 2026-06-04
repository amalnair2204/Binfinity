import React from 'react'
import { useNavigate } from 'react-router-dom'
import useDriverStore from '../store/driverStore.js'
import { driverSocket } from '../api/socket.js'

/**
 * End-of-shift summary.
 * Shows collected bins, total litres, and stops completed.
 * "New Shift" clears state and returns to login.
 */
export default function SummaryPage() {
  const truckId = useDriverStore((s) => s.truckId)
  const binsCollectedToday = useDriverStore((s) => s.binsCollectedToday)
  const litersCollectedToday = useDriverStore((s) => s.litersCollectedToday)
  const stopsCompleted = useDriverStore((s) => s.stopsCompleted)
  const setTruckId = useDriverStore((s) => s.setTruckId)
  const navigate = useNavigate()

  function handleNewShift() {
    driverSocket.disconnect()
    setTruckId(null)
    navigate('/', { replace: true })
  }

  const stats = [
    {
      value: binsCollectedToday,
      unit: '',
      label: 'Bins\nCollected',
    },
    {
      value: Math.round(litersCollectedToday).toLocaleString(),
      unit: 'L',
      label: 'Waste\nCollected',
    },
    {
      value: stopsCompleted,
      unit: '',
      label: 'Stops\nCompleted',
    },
  ]

  return (
    <div className="min-h-screen bg-app-bg flex flex-col items-center justify-center px-6 text-center">
      <div className="text-6xl mb-4 select-none">✅</div>
      <h1 className="text-4xl font-black text-white tracking-tight">Shift Complete</h1>
      <p className="text-app-secondary text-lg mt-2 mb-10">
        Well done{truckId ? `, ${truckId}` : ''}!
      </p>

      {/* Stats grid */}
      <div className="w-full max-w-sm grid grid-cols-3 gap-3 mb-10">
        {stats.map(({ value, unit, label }) => (
          <div
            key={label}
            className="bg-app-card rounded-2xl p-4 border border-app-border"
          >
            <p className="text-3xl font-black text-app-green leading-none">
              {value}
              <span className="text-xl">{unit}</span>
            </p>
            <p className="text-app-secondary text-xs font-semibold mt-2 leading-tight whitespace-pre-line">
              {label}
            </p>
          </div>
        ))}
      </div>

      <button
        className="w-full max-w-sm bg-app-green text-black font-black text-2xl tracking-tight
          py-6 rounded-2xl shadow-xl active:scale-[0.97] transition-transform select-none"
        onClick={handleNewShift}
      >
        NEW SHIFT
      </button>
    </div>
  )
}
