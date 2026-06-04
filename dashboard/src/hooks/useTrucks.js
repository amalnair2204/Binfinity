'use client'
import { useEffect } from 'react'
import { routingApi } from '../lib/apiClient'
import useDashboardStore from '../store/dashboardStore'

export function useTrucks(intervalMs = 10_000) {
  const setTrucks = useDashboardStore((s) => s.setTrucks)

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const data = await routingApi.trucks()
        if (active) setTrucks(data)
      } catch {}
    }
    poll()
    const id = setInterval(poll, intervalMs)
    return () => { active = false; clearInterval(id) }
  }, [intervalMs, setTrucks])
}
