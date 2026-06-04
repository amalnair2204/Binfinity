'use client'
import { useEffect } from 'react'
import { ingestionApi } from '../lib/apiClient'
import useDashboardStore from '../store/dashboardStore'

export function useFleetStats(intervalMs = 15_000) {
  const setFleetStats = useDashboardStore((s) => s.setFleetStats)

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const data = await ingestionApi.fleetStats()
        if (active) setFleetStats(data)
      } catch {}
    }
    poll()
    const id = setInterval(poll, intervalMs)
    return () => { active = false; clearInterval(id) }
  }, [intervalMs, setFleetStats])
}
