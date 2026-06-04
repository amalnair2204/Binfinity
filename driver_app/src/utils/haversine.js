const EARTH_R_M = 6_371_000

/**
 * Great-circle distance in metres between two WGS84 coordinates.
 * Mirrors routing/distance.py haversine_m for GPS throttle decisions.
 */
export function haversineM(lat1, lng1, lat2, lng2) {
  const phi1 = (lat1 * Math.PI) / 180
  const phi2 = (lat2 * Math.PI) / 180
  const dPhi = ((lat2 - lat1) * Math.PI) / 180
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const a =
    Math.sin(dPhi / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_R_M * Math.asin(Math.sqrt(a))
}
