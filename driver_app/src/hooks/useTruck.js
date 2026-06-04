import { useEffect, useRef } from 'react'
import { api } from '../api/client.js'
import useDriverStore from '../store/driverStore.js'

const POLL_INTERVAL_MS = 30_000
const GEO_PUSH_INTERVAL_MS = 15_000

/**
 * Syncs truck telemetry (load, status, capacity) from the backend and
 * pushes GPS position updates every 15 s via the Geolocation API.
 */
export function useTruck() {
  const truckId = useDriverStore((s) => s.truckId)
  const setTruckState = useDriverStore((s) => s.setTruckState)
  const setOnline = useDriverStore((s) => s.setOnline)
  const geoWatchRef = useRef(null)
  const geoPushTimerRef = useRef(null)
  const lastPosRef = useRef(null)

  async function fetchTruckState() {
    if (!truckId) return
    try {
      const state = await api.getTruckState(truckId)
      setTruckState({
        loadLiters: state.load_liters ?? 0,
        capacityLiters: state.capacity_liters || 10_000,
        status: state.status ?? 'unknown',
        position: state.position ?? null,
      })
    } catch {
      // keep last known state
    }
  }

  async function pushPosition(lat, lng) {
    if (!truckId) return
    try {
      await api.updatePosition(truckId, lat, lng)
    } catch {
      // fire-and-forget; position push is best-effort
    }
  }

  // Online / offline banner
  useEffect(() => {
    const onOnline = () => setOnline(true)
    const onOffline = () => setOnline(false)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  useEffect(() => {
    if (!truckId) return

    fetchTruckState()
    const pollTimer = setInterval(fetchTruckState, POLL_INTERVAL_MS)

    if ('geolocation' in navigator) {
      geoWatchRef.current = navigator.geolocation.watchPosition(
        ({ coords }) => {
          lastPosRef.current = { lat: coords.latitude, lng: coords.longitude }
        },
        null,
        { enableHighAccuracy: true, maximumAge: 10_000, timeout: 20_000 },
      )

      geoPushTimerRef.current = setInterval(() => {
        if (lastPosRef.current) {
          pushPosition(lastPosRef.current.lat, lastPosRef.current.lng)
        }
      }, GEO_PUSH_INTERVAL_MS)
    }

    return () => {
      clearInterval(pollTimer)
      clearInterval(geoPushTimerRef.current)
      if (geoWatchRef.current !== null) {
        navigator.geolocation.clearWatch(geoWatchRef.current)
      }
    }
  }, [truckId])
}
