'use client'
import { useEffect } from 'react'
import { geoApi, ingestionApi } from '../lib/apiClient'
import useDashboardStore from '../store/dashboardStore'

export function useBinGeoJSON(intervalMs = 30_000) {
  const setBins = useDashboardStore((s) => s.setBins)

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const [geojson, states] = await Promise.all([
          geoApi.exportBins(),
          ingestionApi.bins(),
        ])
        // Enrich GeoJSON features with live fill_pct and status
        const stateMap = Object.fromEntries(states.map((s) => [s.bin_id, s]))
        const enriched = {
          ...geojson,
          features: geojson.features.map((f) => {
            const st = stateMap[f.properties.bin_id]
            return {
              ...f,
              properties: {
                ...f.properties,
                fill_pct: st?.fill_pct ?? 0,
                status: st?.status ?? 'unknown',
                flagged: st?.flagged_for_collection ?? false,
              },
            }
          }),
        }
        if (active) setBins(enriched)
      } catch {}
    }
    poll()
    const id = setInterval(poll, intervalMs)
    return () => { active = false; clearInterval(id) }
  }, [intervalMs, setBins])
}
