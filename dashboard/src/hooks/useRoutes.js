'use client'
import { useEffect } from 'react'
import { routingApi } from '../lib/apiClient'
import useDashboardStore from '../store/dashboardStore'

export function useRoutes(intervalMs = 20_000) {
  const setRoutes = useDashboardStore((s) => s.setRoutes)

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const data = await routingApi.routes()
        if (active) setRoutes(data)
      } catch {}
    }
    poll()
    const id = setInterval(poll, intervalMs)
    return () => { active = false; clearInterval(id) }
  }, [intervalMs, setRoutes])
}
