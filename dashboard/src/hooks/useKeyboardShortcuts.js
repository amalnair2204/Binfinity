'use client'
import { useEffect } from 'react'
import useDashboardStore from '../store/dashboardStore'

export function useKeyboardShortcuts() {
  const toggleLayer        = useDashboardStore((s) => s.toggleLayer)
  const setSelectedBinId   = useDashboardStore((s) => s.setSelectedBinId)
  const setSelectedTruckId = useDashboardStore((s) => s.setSelectedTruckId)
  const setMapFlyTarget    = useDashboardStore((s) => s.setMapFlyTarget)
  const trucks             = useDashboardStore((s) => s.trucks)
  const toggleCalibration  = useDashboardStore((s) => s.toggleCalibration)

  useEffect(() => {
    const handler = (e) => {
      const tag = e.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.ctrlKey || e.metaKey || e.altKey) return

      switch (e.key.toUpperCase()) {
        case 'H': toggleLayer('heatmap'); break
        case 'B': toggleLayer('bins'); break
        case 'T': toggleLayer('trucks'); break
        case 'R': toggleLayer('routes'); break
        case 'C': toggleCalibration(); break
        case 'ESCAPE':
          setSelectedBinId(null)
          setSelectedTruckId(null)
          break
        case 'F': {
          const positioned = trucks.filter((t) => t.position?.lat != null)
          if (positioned.length === 0) break
          const lat = positioned.reduce((s, t) => s + t.position.lat, 0) / positioned.length
          const lng = positioned.reduce((s, t) => s + t.position.lng, 0) / positioned.length
          setMapFlyTarget({ center: [lng, lat], zoom: 13 })
          break
        }
        case '/':
          e.preventDefault()
          document.getElementById('bin-search')?.focus()
          break
        default: break
      }
    }

    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [toggleLayer, setSelectedBinId, setSelectedTruckId, setMapFlyTarget, trucks, toggleCalibration])
}
