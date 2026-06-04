import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { haversineM } from '../utils/haversine.js'

const MIN_INTERVAL_MS = 30_000   // don't push more often than 30s
const MIN_DISTANCE_M  = 50       // push if moved ≥ 50m regardless of time

/**
 * Tracks GPS position via the Geolocation API.
 * Pushes updates to the backend when either 30s have elapsed or the truck
 * has moved ≥ 50 m since the last push (whichever comes first).
 *
 * Returns: { lat, lng, gpsError, lastUpdated }
 */
export function useGPS(truckId) {
  const [position, setPosition] = useState({ lat: null, lng: null })
  const [gpsError, setGpsError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const lastPushPosRef  = useRef(null)
  const lastPushTimeRef = useRef(0)
  const watchIdRef      = useRef(null)

  async function maybePush(lat, lng) {
    if (!truckId) return
    const now = Date.now()
    const timeSince = now - lastPushTimeRef.current
    const last = lastPushPosRef.current
    const dist = last ? haversineM(last.lat, last.lng, lat, lng) : Infinity

    if (timeSince < MIN_INTERVAL_MS && dist < MIN_DISTANCE_M) return

    lastPushTimeRef.current = now
    lastPushPosRef.current  = { lat, lng }
    setLastUpdated(new Date(now))
    try {
      await api.updatePosition(truckId, lat, lng)
    } catch {
      // fire-and-forget; position push is best-effort
    }
  }

  useEffect(() => {
    if (!truckId || !('geolocation' in navigator)) {
      if (!('geolocation' in navigator)) {
        setGpsError('Geolocation not available')
      }
      return
    }

    watchIdRef.current = navigator.geolocation.watchPosition(
      ({ coords }) => {
        const { latitude: lat, longitude: lng } = coords
        setPosition({ lat, lng })
        setGpsError(null)
        maybePush(lat, lng)
      },
      (err) => {
        setGpsError(err.message)
      },
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 20_000 },
    )

    return () => {
      if (watchIdRef.current !== null) {
        navigator.geolocation.clearWatch(watchIdRef.current)
      }
    }
  }, [truckId])

  return { lat: position.lat, lng: position.lng, gpsError, lastUpdated }
}
