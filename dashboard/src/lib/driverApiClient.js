const BASE = process.env.NEXT_PUBLIC_ROUTING_API || 'http://localhost:8004'

async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
    signal: AbortSignal.timeout(10_000),
  }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${method} ${path} → HTTP ${res.status}: ${text}`)
  }
  return res.json()
}

export const driverApi = {
  getRoute: (truckId) =>
    request('GET', `/routing/routes/truck/${truckId}`),

  getNextStop: (truckId) =>
    request('GET', `/routing/routes/truck/${truckId}/next-stop`),

  getTruckState: (truckId) =>
    request('GET', `/routing/dispatch/trucks/${truckId}`),

  confirmCollection: (truckId, binId, actualLiters = 0) =>
    request('POST', `/routing/dispatch/trucks/${truckId}/collect/${binId}`, {
      actual_liters: actualLiters,
    }),

  confirmDump: (truckId, yardId) =>
    request('POST', `/routing/dispatch/trucks/${truckId}/dump/${yardId}`),

  updatePosition: (truckId, lat, lng) =>
    request('PATCH', `/routing/dispatch/trucks/${truckId}/position`, { lat, lng }),
}
