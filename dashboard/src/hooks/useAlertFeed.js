'use client'
import { useEffect } from 'react'
import { routingApi } from '../lib/apiClient'
import useDashboardStore from '../store/dashboardStore'

export function useAlertFeed(intervalMs = 10_000) {
  const setAlerts = useDashboardStore((s) => s.setAlerts)

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const data = await routingApi.events()
        if (active) setAlerts(data)
      } catch {}
    }
    poll()
    const id = setInterval(poll, intervalMs)
    return () => { active = false; clearInterval(id) }
  }, [intervalMs, setAlerts])
}
