'use client'
import { useEffect } from 'react'
import { mlApi } from '../lib/apiClient'
import useDashboardStore from '../store/dashboardStore'

export function useMLPredictions(intervalMs = 60_000) {
  const setMLPredictions = useDashboardStore((s) => s.setMLPredictions)

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const data = await mlApi.atRisk(4)
        if (active) setMLPredictions(data)
      } catch {}
    }
    poll()
    const id = setInterval(poll, intervalMs)
    return () => { active = false; clearInterval(id) }
  }, [intervalMs, setMLPredictions])
}
