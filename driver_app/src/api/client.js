const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function request(method, path, body = undefined) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
    signal: AbortSignal.timeout(10_000),
  }
  if (body !== undefined) opts.body = JSON.stringify(body)

  const res = await fetch(`${BASE_URL}${path}`, opts)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    const err = new Error(`${method} ${path} → HTTP ${res.status}: ${text}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  /**
   * Full route for a truck — returns OptimizedRoute with all stops.
   * Used to initialise the driver's stop sequence.
   */
  getRoute: (truckId) =>
    request('GET', `/routing/routes/truck/${truckId}`),

  /**
   * Convenience: just the next stop (RouteStop).
   * Used for lightweight polling when only the head of queue matters.
   */
  getNextStop: (truckId) =>
    request('GET', `/routing/routes/truck/${truckId}/next-stop`),

  /**
   * Truck dispatch state: load_liters, capacity_liters, status, position.
   */
  getTruckState: (truckId) =>
    request('GET', `/routing/dispatch/trucks/${truckId}`),

  /**
   * Confirm bin collection. actual_liters defaults to 0 when unknown.
   */
  confirmCollection: (truckId, binId, actualLiters = 0) =>
    request('POST', `/routing/dispatch/trucks/${truckId}/collect/${binId}`, {
      actual_liters: actualLiters,
    }),

  /**
   * Confirm dump yard visit — resets truck load to 0.
   */
  confirmDump: (truckId, yardId) =>
    request('POST', `/routing/dispatch/trucks/${truckId}/dump/${yardId}`),

  /**
   * Push GPS position to backend for real-time fleet tracking.
   */
  updatePosition: (truckId, lat, lng) =>
    request('PATCH', `/routing/dispatch/trucks/${truckId}/position`, { lat, lng }),
}
