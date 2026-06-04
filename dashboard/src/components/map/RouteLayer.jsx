'use client'
import { useMemo } from 'react'
import { Polyline } from 'react-leaflet'
import useDashboardStore from '../../store/dashboardStore'

const TRUCK_COLORS = [
  '#00d4ff', '#00ff88', '#ffaa00', '#ff6600', '#ff3355',
  '#aa00ff', '#ff00aa', '#00ffcc', '#ffcc00', '#0066ff',
]

function buildRouteLines(routes, bins) {
  if (!routes?.length || !bins?.features?.length) return []

  const posMap = {}
  for (const f of bins.features) {
    const { bin_id } = f.properties
    if (bin_id) {
      const [lng, lat] = f.geometry.coordinates
      posMap[bin_id] = [lat, lng]
    }
  }

  return routes
    .map((route, i) => {
      const positions = route.stops
        .slice()
        .sort((a, b) => a.sequence - b.sequence)
        .map((s) => posMap[s.node_id])
        .filter(Boolean)
      return {
        key:       route.route_id,
        positions,
        color:     TRUCK_COLORS[i % TRUCK_COLORS.length],
      }
    })
    .filter((r) => r.positions.length >= 2)
}

export default function RouteLayer() {
  const routes  = useDashboardStore((s) => s.routes)
  const bins    = useDashboardStore((s) => s.bins)
  const visible = useDashboardStore((s) => s.layerVisibility.routes)

  const lines = useMemo(() => buildRouteLines(routes, bins), [routes, bins])

  if (!visible) return null

  return lines.map(({ key, positions, color }) => (
    <Polyline
      key={key}
      positions={positions}
      pathOptions={{ color, weight: 2, opacity: 0.65, dashArray: '6 3' }}
    />
  ))
}
