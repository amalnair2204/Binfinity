import React, { useEffect, useState } from 'react'
import useDriverStore from '../store/driverStore.js'
import { api } from '../api/client.js'
import { offlineQueue } from '../utils/offlineQueue.js'

/**
 * Primary driver CTA. One tap confirms the current stop action:
 * - Bin stop  → COLLECTED (POST collect)
 * - Dump yard → DUMP COMPLETE (POST dump)
 *
 * Optimistically advances the store then syncs with the backend.
 * When offline, action is queued locally and flushed on reconnect.
 * On network error, shows an inline retry message without blocking navigation.
 */
export default function ActionButton() {
  const truckId    = useDriverStore((s) => s.truckId)
  const currentStop = useDriverStore((s) => s.currentStop)
  const advanceStop = useDriverStore((s) => s.advanceStop)
  const isOnline   = useDriverStore((s) => s.isOnline)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  // Flush queued offline actions when connectivity returns
  useEffect(() => {
    if (!isOnline || offlineQueue.size() === 0) return
    offlineQueue.flush(async (action) => {
      if (action.type === 'collect') {
        await api.confirmCollection(action.truckId, action.nodeId, action.liters ?? 0)
      } else if (action.type === 'dump') {
        await api.confirmDump(action.truckId, action.nodeId)
      }
    })
  }, [isOnline])

  if (!currentStop) return null

  const isBin  = currentStop.node_type === 'bin'
  const isDump = currentStop.node_type === 'dump_yard'
  const label  = isBin ? 'COLLECTED' : isDump ? 'DUMP COMPLETE' : 'DONE'
  const fillL  = currentStop.fill_collected_liters ?? 0

  async function handleAction() {
    if (loading) return
    if ('vibrate' in navigator) navigator.vibrate(50)
    setLoading(true)
    setError(null)

    // Optimistic advance — driver should never be blocked by a slow API
    advanceStop(fillL)

    if (!isOnline) {
      offlineQueue.enqueue({
        type: isBin ? 'collect' : 'dump',
        truckId,
        nodeId: currentStop.node_id,
        liters: fillL,
      })
      setLoading(false)
      return
    }

    try {
      if (isBin) {
        await api.confirmCollection(truckId, currentStop.node_id, fillL)
      } else if (isDump) {
        await api.confirmDump(truckId, currentStop.node_id)
      }
    } catch {
      // Don't roll back the optimistic advance — driver has physically done the work.
      setError('Sync failed — will retry on reconnect')
    } finally {
      setLoading(false)
    }
  }

  const bg = isBin ? 'bg-app-green active:bg-green-300' : 'bg-yellow-400 active:bg-yellow-200'
  const fg = 'text-black'

  return (
    <div className="mx-4">
      {error && (
        <p className="text-red-400 text-sm text-center mb-2 font-semibold">{error}</p>
      )}
      <button
        className={`w-full ${bg} ${fg} font-black text-3xl tracking-tight rounded-2xl py-8
          shadow-xl active:scale-[0.97] transition-transform select-none
          disabled:opacity-50 disabled:pointer-events-none`}
        onPointerDown={handleAction}
        disabled={loading}
        aria-label={label}
      >
        {loading ? '…' : label}
      </button>
    </div>
  )
}
