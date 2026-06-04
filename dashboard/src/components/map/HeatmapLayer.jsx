'use client'
import { useEffect, useRef, useMemo } from 'react'
import { useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet.heat'
import useDashboardStore from '../../store/dashboardStore'

export default function HeatmapLayer() {
  const map     = useMap()
  const bins    = useDashboardStore((s) => s.bins)
  const visible = useDashboardStore((s) => s.layerVisibility.heatmap)
  const heatRef = useRef(null)

  // Create heat layer once
  useEffect(() => {
    heatRef.current = L.heatLayer([], {
      radius:     30,
      blur:       20,
      gradient:   { 0: '#00ff88', 0.4: '#ffaa00', 1.0: '#ff3355' },
      minOpacity: 0.4,
    })
    if (visible) map.addLayer(heatRef.current)
    return () => {
      if (heatRef.current && map.hasLayer(heatRef.current)) {
        map.removeLayer(heatRef.current)
      }
    }
  }, [map]) // eslint-disable-line react-hooks/exhaustive-deps

  // Update points when bins change
  const points = useMemo(
    () => (bins?.features ?? []).map((f) => {
      const [lng, lat] = f.geometry.coordinates
      return [lat, lng, (f.properties?.fill_pct ?? 0) / 100]
    }),
    [bins],
  )

  useEffect(() => {
    if (!heatRef.current) return
    heatRef.current.setLatLngs(points)
  }, [points])

  // Show / hide
  useEffect(() => {
    if (!heatRef.current) return
    if (visible && !map.hasLayer(heatRef.current)) map.addLayer(heatRef.current)
    if (!visible && map.hasLayer(heatRef.current))  map.removeLayer(heatRef.current)
  }, [map, visible])

  return null
}
