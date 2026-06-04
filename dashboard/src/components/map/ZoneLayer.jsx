'use client'
import { useEffect, useState } from 'react'
import { Polygon } from 'react-leaflet'
import { geoApi } from '../../lib/apiClient'

function toLeafletPositions(geometry) {
  if (geometry.type === 'Polygon') {
    return geometry.coordinates[0].map(([lng, lat]) => [lat, lng])
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates[0][0].map(([lng, lat]) => [lat, lng])
  }
  return null
}

export default function ZoneLayer() {
  const [zones, setZones] = useState([])

  useEffect(() => {
    let cancelled = false
    geoApi.exportZones()
      .then((geojson) => {
        if (cancelled) return
        const polygons = (geojson?.features ?? [])
          .map((f, i) => {
            const positions = f.geometry ? toLeafletPositions(f.geometry) : null
            if (!positions) {
              // fallback: build rect from bbox properties
              const { min_lat, max_lat, min_lng, max_lng } = f.properties || {}
              if (min_lat == null) return null
              return {
                key:       f.properties?.zone_id ?? i,
                positions: [
                  [min_lat, min_lng], [max_lat, min_lng],
                  [max_lat, max_lng], [min_lat, max_lng],
                ],
              }
            }
            return { key: f.properties?.zone_id ?? i, positions }
          })
          .filter(Boolean)
        setZones(polygons)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  return zones.map(({ key, positions }) => (
    <Polygon
      key={key}
      positions={positions}
      pathOptions={{
        color:       '#1a2535',
        fillColor:   '#00d4ff',
        fillOpacity: 0.04,
        weight:      1,
        opacity:     0.8,
      }}
    />
  ))
}
