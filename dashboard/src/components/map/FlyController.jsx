'use client'
import { useEffect } from 'react'
import { useMap } from 'react-leaflet'
import useDashboardStore from '../../store/dashboardStore'

export default function FlyController() {
  const map             = useMap()
  const mapFlyTarget    = useDashboardStore((s) => s.mapFlyTarget)
  const setMapFlyTarget = useDashboardStore((s) => s.setMapFlyTarget)

  useEffect(() => {
    if (!map || !mapFlyTarget) return
    const [lng, lat] = mapFlyTarget.center
    map.flyTo([lat, lng], mapFlyTarget.zoom ?? 13)
    setMapFlyTarget(null)
  }, [map, mapFlyTarget, setMapFlyTarget])

  return null
}
