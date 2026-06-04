'use client'
import { useMemo } from 'react'
import { CircleMarker, Tooltip } from 'react-leaflet'
import useDashboardStore from '../../store/dashboardStore'

export default function TruckLayer() {
  const trucks      = useDashboardStore((s) => s.trucks)
  const setSelected = useDashboardStore((s) => s.setSelectedTruckId)
  const visible     = useDashboardStore((s) => s.layerVisibility.trucks)

  const positioned = useMemo(
    () => trucks.filter((t) => t.position?.lat != null && t.position?.lng != null),
    [trucks],
  )

  if (!visible) return null

  return positioned.map((t) => (
    <CircleMarker
      key={t.truck_id}
      center={[t.position.lat, t.position.lng]}
      radius={10}
      pathOptions={{
        fillColor:   '#00d4ff',
        fillOpacity: 0.9,
        color:       '#080c10',
        weight:      2,
        opacity:     1,
      }}
      eventHandlers={{ click: () => setSelected(t.truck_id) }}
    >
      <Tooltip permanent direction="bottom" offset={[0, 8]}>
        <span style={{ color: '#00d4ff', fontSize: 9, fontFamily: 'monospace' }}>
          {t.truck_id}
        </span>
      </Tooltip>
    </CircleMarker>
  ))
}
