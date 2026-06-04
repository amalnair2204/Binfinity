import { useEffect, useRef } from 'react'
import { driverSocket } from '../api/socket.js'
import useDriverStore from '../store/driverStore.js'
import { playAlertTone } from '../utils/audio.js'

const AUTO_DISMISS_MS = 8_000

function vibrate(pattern) {
  if ('vibrate' in navigator) navigator.vibrate(pattern)
}

/**
 * Subscribes to dispatch WebSocket events and surfaces them as in-app alerts
 * with haptic vibration and audio tones. Alerts auto-dismiss after 8 s.
 *
 * Handled server events:
 *   overflow_alert  → error  | 880 Hz | [200,100,200,100,200]
 *   reroute         → warning | 660 Hz | [100,50,100,50,100]
 *   shift_warning   → warning | 440 Hz | [200,100,200]
 *   stop_injected   → warning | 660 Hz | [150,80,150]
 */
export function useAlerts() {
  const addAlert   = useDriverStore((s) => s.addAlert)
  const dismissAlert = useDriverStore((s) => s.dismissAlert)
  const idRef      = useRef(0)

  function push(type, message, toneType) {
    const id = ++idRef.current
    const severity = type === 'overflow' ? 'error' : 'warning'
    addAlert({ id, type, message, severity, at: Date.now() })
    playAlertTone(toneType ?? type)
    setTimeout(() => dismissAlert(id), AUTO_DISMISS_MS)
  }

  useEffect(() => {
    const offs = [
      driverSocket.on('overflow_alert', (p) => {
        vibrate([200, 100, 200, 100, 200])
        push('overflow', `Bin ${p?.bin_id ?? ''} near overflow — route updated`, 'overflow')
      }),
      driverSocket.on('reroute', (p) => {
        vibrate([100, 50, 100, 50, 100])
        push('reroute', p?.reason ?? 'Route updated by dispatch', 'reroute')
      }),
      driverSocket.on('shift_warning', (p) => {
        vibrate([200, 100, 200])
        const mins = p?.minutes_remaining
        push('shift', mins ? `${mins} min remaining` : 'Shift ending soon', 'shift')
      }),
      driverSocket.on('stop_injected', (p) => {
        vibrate([150, 80, 150])
        push('reroute', `Dump yard${p?.yard_id ? ` ${p.yard_id}` : ''} added to route`, 'reroute')
      }),
    ]
    return () => offs.forEach((off) => off())
  }, [])

  return {
    activeAlert: null, // alerts accessed directly from store
    clearAlert: (id) => dismissAlert(id),
  }
}
