const GEO_BASE      = process.env.NEXT_PUBLIC_GEO_API       || 'http://localhost:8002'
const ING_BASE      = process.env.NEXT_PUBLIC_INGESTION_API || 'http://localhost:8001'
const ROUTING_BASE  = process.env.NEXT_PUBLIC_ROUTING_API   || 'http://localhost:8004'
const ML_BASE       = process.env.NEXT_PUBLIC_ML_API        || 'http://localhost:8003'

async function get(base, path) {
  const res = await fetch(`${base}${path}`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.url}`)
  return res.json()
}

export const geoApi = {
  exportBins:  () => get(GEO_BASE, '/export/bins.geojson'),
  exportZones: () => get(GEO_BASE, '/export/zones.geojson'),
  listZones:   () => get(GEO_BASE, '/zones'),
}

export const ingestionApi = {
  bins:        () => get(ING_BASE, '/bins'),
  fleetStats:  () => get(ING_BASE, '/fleet/stats'),
  fleetFlagged:() => get(ING_BASE, '/fleet/flagged'),
  fleetCritical:()=> get(ING_BASE, '/fleet/critical'),
  binHistory:  (binId, limit = 48) => get(ING_BASE, `/bins/${binId}/history?limit=${limit}`),
}

export const routingApi = {
  routes:      () => get(ROUTING_BASE, '/routing/routes'),
  stats:       () => get(ROUTING_BASE, '/routing/stats'),
  unassigned:  () => get(ROUTING_BASE, '/routing/unassigned'),
  trucks:      () => get(ROUTING_BASE, '/routing/dispatch/trucks'),
  events:      () => get(ROUTING_BASE, '/routing/events'),
  triggerReopt:(scope = 'full_fleet', reason = 'manual') =>
    fetch(`${ROUTING_BASE}/routing/dispatch/reopt/trigger`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope, reason }),
    }).then((r) => r.json()),
}

export const mlApi = {
  atRisk: (hours = 4) => get(ML_BASE, `/fleet/at_risk?hours=${hours}`),
}

const CAL_BASE = process.env.NEXT_PUBLIC_CALIBRATION_API || 'http://localhost:8005'

export const calibrationApi = {
  health:        () => get(CAL_BASE, '/calibration/health'),
  fleetAccuracy: () => get(CAL_BASE, '/calibration/accuracy/fleet'),
  worstBins:     (limit = 10) => get(CAL_BASE, `/calibration/accuracy/worst?limit=${limit}`),
  retrainJobs:   (limit = 20) => get(CAL_BASE, `/calibration/retrain/jobs?limit=${limit}`),
  triggerRetrain: (binId, body = {}) =>
    fetch(`${CAL_BASE}/calibration/retrain/trigger/${encodeURIComponent(binId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  triggerRetrainFleet: () =>
    fetch(`${CAL_BASE}/calibration/retrain/trigger/fleet`, { method: 'POST' }).then((r) => r.json()),
}
