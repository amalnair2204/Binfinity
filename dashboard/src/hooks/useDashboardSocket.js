'use client'
import { useEffect, useRef } from 'react'
import useDashboardStore from '../store/dashboardStore'

const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE || 'ws://localhost:8004'

export function useDashboardSocket() {
  const setWsStatus     = useDashboardStore((s) => s.setWsStatus)
  const prependAlert    = useDashboardStore((s) => s.prependAlert)
  const updateTruckPos  = useDashboardStore((s) => s.updateTruckPosition)
  const updateRoutes    = useDashboardStore((s) => s.updateRoutes)

  const wsRef        = useRef(null)
  const retryRef     = useRef(null)
  const mountedRef   = useRef(true)

  useEffect(() => {
    mountedRef.current = true

    function connect() {
      if (!mountedRef.current) return
      setWsStatus('reconnecting')
      const ws = new WebSocket(`${WS_BASE}/ws/ops`)
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) { ws.close(); return }
        setWsStatus('connected')
        if (retryRef.current) { clearTimeout(retryRef.current); retryRef.current = null }
      }

      ws.onmessage = (evt) => {
        if (!mountedRef.current) return
        try {
          const { type, payload } = JSON.parse(evt.data)
          if (type === 'alert')           prependAlert(payload)
          else if (type === 'truck_pos')  updateTruckPos(payload.truck_id, payload.lat, payload.lng)
          else if (type === 'routes')     updateRoutes(payload.routes ?? [])
        } catch {}
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setWsStatus('disconnected')
        retryRef.current = setTimeout(connect, 5_000)
      }

      ws.onerror = () => ws.close()
    }

    connect()

    return () => {
      mountedRef.current = false
      if (retryRef.current) clearTimeout(retryRef.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, []) // stable store refs — intentionally empty deps
}
