'use client'
import { useMemo } from 'react'
import { CircleMarker } from 'react-leaflet'
import useDashboardStore from '../../store/dashboardStore'

function binColor(pct) {
  if (pct >= 90) return '#ff3355'
  if (pct >= 75) return '#ff6600'
  if (pct >= 50) return '#ffaa00'
  return '#00ff88'
}

function binRadius(pct) {
  if (pct >= 80) return 7
  if (pct >= 50) return 5
  return 4
}

export default function BinLayer() {
  const bins        = useDashboardStore((s) => s.bins)
  const setSelected = useDashboardStore((s) => s.setSelectedBinId)
  const visible     = useDashboardStore((s) => s.layerVisibility.bins)

  const features = useMemo(() => bins?.features ?? [], [bins])

  if (!visible) return null

  return features.map((f) => {
    const { bin_id, fill_pct = 0, flagged } = f.properties
    const [lng, lat] = f.geometry.coordinates
    const color  = binColor(fill_pct)
    const radius = binRadius(fill_pct)

    return (
      <CircleMarker
        key={bin_id}
        center={[lat, lng]}
        radius={radius}
        pathOptions={{
          fillColor:   color,
          fillOpacity: 0.9,
          color:       flagged ? '#ffaa00' : color,
          weight:      flagged ? 2 : 1,
          opacity:     0.9,
        }}
        eventHandlers={{ click: () => setSelected(bin_id) }}
      />
    )
  })
}
