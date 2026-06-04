import { useEffect, useRef } from 'react'
import { api } from '../api/client.js'
import { driverSocket } from '../api/socket.js'
import useDriverStore from '../store/driverStore.js'

const POLL_INTERVAL_MS = 60_000

/**
 * Keeps the driver's route in sync with the backend.
 *
 * - Polls GET /routing/routes/truck/{id} every 60 s.
 * - Re-fetches immediately on WebSocket route_updated / route_change events.
 * - Gracefully degrades when offline (keeps last known state).
 */
export function useRoute() {
  const truckId = useDriverStore((s) => s.truckId)
  const setRoute = useDriverStore((s) => s.setRoute)
  const setConnected = useDriverStore((s) => s.setConnected)
  const timerRef = useRef(null)

  async function fetchRoute() {
    if (!truckId) return
    try {
      const route = await api.getRoute(truckId)
      setRoute(route.stops ?? [])
    } catch {
      // network unavailable — keep last known state, no rethrow
    }
  }

  useEffect(() => {
    if (!truckId) return

    fetchRoute()
    timerRef.current = setInterval(fetchRoute, POLL_INTERVAL_MS)

    const offUpdate = driverSocket.on('route_updated', fetchRoute)
    const offChange = driverSocket.on('route_change', fetchRoute)
    const offStopInjected = driverSocket.on('stop_injected', fetchRoute)
    const offConnected = driverSocket.on('connected', () => {
      setConnected(true)
      fetchRoute()
    })
    const offDisconnected = driverSocket.on('disconnected', () => setConnected(false))

    return () => {
      clearInterval(timerRef.current)
      offUpdate()
      offChange()
      offStopInjected()
      offConnected()
      offDisconnected()
    }
  }, [truckId])
}
