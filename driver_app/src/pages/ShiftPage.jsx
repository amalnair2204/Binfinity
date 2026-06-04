import React, { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import useDriverStore from '../store/driverStore.js'
import { useRoute } from '../hooks/useRoute.js'
import { useTruck } from '../hooks/useTruck.js'
import { useAlerts } from '../hooks/useAlerts.js'
import AlertBanner from '../components/AlertBanner.jsx'
import OfflineIndicator from '../components/OfflineIndicator.jsx'
import RouteProgress from '../components/RouteProgress.jsx'
import CurrentStop from '../components/CurrentStop.jsx'
import NextStop from '../components/NextStop.jsx'
import TruckStatus from '../components/TruckStatus.jsx'
import ActionButton from '../components/ActionButton.jsx'

/**
 * Main driving screen.
 *
 * Layout (fixed viewport height, no scrolling):
 *   ┌─────────────────────────────┐
 *   │  AlertBanner (overlay)      │
 *   │  OfflineIndicator           │
 *   │  Truck ID · End Shift btn   │
 *   │  RouteProgress              │
 *   │─────────────────────────────│
 *   │         CurrentStop         │  ← flex-1 centred
 *   │─────────────────────────────│
 *   │  NextStop                   │
 *   │  TruckStatus                │
 *   │  [ COLLECTED ]              │  ← 88px CTA
 *   └─────────────────────────────┘
 */
export default function ShiftPage() {
  const truckId = useDriverStore((s) => s.truckId)
  const shiftEnded = useDriverStore((s) => s.shiftEnded)
  const allStops = useDriverStore((s) => s.allStops)
  const stopsCompleted = useDriverStore((s) => s.stopsCompleted)
  const currentStop = useDriverStore((s) => s.currentStop)
  const endShift = useDriverStore((s) => s.endShift)
  const navigate = useNavigate()

  // Activate data subscriptions
  useRoute()
  useTruck()
  useAlerts()

  // Guard: no truck ID → back to login
  useEffect(() => {
    if (!truckId) navigate('/', { replace: true })
  }, [truckId])

  // Navigate to summary when shift explicitly ended
  useEffect(() => {
    if (shiftEnded) navigate('/summary', { replace: true })
  }, [shiftEnded])

  // Auto-end shift when all stops are gone
  useEffect(() => {
    if (stopsCompleted > 0 && allStops.length === 0 && !currentStop) {
      endShift()
    }
  }, [stopsCompleted, allStops.length, currentStop])

  return (
    <div className="h-screen w-screen bg-app-bg flex flex-col overflow-hidden relative">
      {/* Alert banner — absolutely positioned overlay */}
      <AlertBanner />

      {/* Header bar */}
      <div className="flex-shrink-0 pt-4">
        <OfflineIndicator />
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-app-secondary text-sm font-medium">
            Truck{' '}
            <span className="text-white font-bold text-base">{truckId}</span>
          </span>
          <button
            className="text-app-secondary text-sm border border-app-border rounded-lg px-3 py-1.5
              active:bg-app-card transition-colors"
            onClick={endShift}
          >
            End Shift
          </button>
        </div>
        <RouteProgress />
      </div>

      {/* Current stop — centred in remaining space */}
      <div className="flex-1 flex flex-col justify-center py-2 min-h-0">
        <CurrentStop />
      </div>

      {/* Bottom action cluster */}
      <div className="flex-shrink-0 flex flex-col gap-3 pb-8 pt-2">
        <NextStop />
        <TruckStatus />
        <ActionButton />
      </div>
    </div>
  )
}
