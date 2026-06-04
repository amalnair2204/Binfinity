'use client'
import { useEffect, useRef, useState } from 'react'
import useDriverStore from '../../store/driverStore'
import { driverApi }    from '../../lib/driverApiClient'
import { driverSocket } from '../../lib/driverSocket'

// ── Data sync hooks ───────────────────────────────────────────────────────────

function useDriverRoute() {
  const truckId      = useDriverStore((s) => s.truckId)
  const setRoute     = useDriverStore((s) => s.setRoute)
  const setConnected = useDriverStore((s) => s.setConnected)
  const timerRef     = useRef(null)

  async function fetchRoute() {
    if (!truckId) return
    try {
      const route = await driverApi.getRoute(truckId)
      setRoute(route.stops ?? [])
    } catch {}
  }

  useEffect(() => {
    if (!truckId) return
    fetchRoute()
    timerRef.current = setInterval(fetchRoute, 60_000)
    const offU    = driverSocket.on('route_updated',   fetchRoute)
    const offC    = driverSocket.on('route_change',    fetchRoute)
    const offI    = driverSocket.on('stop_injected',   fetchRoute)
    const offConn = driverSocket.on('connected',       () => { setConnected(true); fetchRoute() })
    const offDisc = driverSocket.on('disconnected',    () => setConnected(false))
    return () => {
      clearInterval(timerRef.current)
      offU(); offC(); offI(); offConn(); offDisc()
    }
  }, [truckId]) // eslint-disable-line react-hooks/exhaustive-deps
}

function useDriverTruck() {
  const truckId       = useDriverStore((s) => s.truckId)
  const setTruckState = useDriverStore((s) => s.setTruckState)

  async function fetchTruck() {
    if (!truckId) return
    try {
      const state = await driverApi.getTruckState(truckId)
      setTruckState(state)
    } catch {}
  }

  useEffect(() => {
    if (!truckId) return
    fetchTruck()
    const id  = setInterval(fetchTruck, 30_000)
    const off = driverSocket.on('truck_updated', fetchTruck)
    return () => { clearInterval(id); off() }
  }, [truckId]) // eslint-disable-line react-hooks/exhaustive-deps
}

// ── Login view ────────────────────────────────────────────────────────────────

function LoginView({ onLogin }) {
  const [input, setInput] = useState('')
  const [error, setError] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    const id = input.trim().toUpperCase()
    if (!id) { setError('Enter truck ID'); return }
    onLogin(id)
  }

  return (
    <div className="flex flex-col items-center justify-center h-full px-8 bg-ops-bg font-mono">
      <div className="text-center mb-10">
        <div className="text-5xl mb-4 select-none">🚛</div>
        <div className="text-ops-cyan text-xl font-bold tracking-widest">DRIVER SIM</div>
        <div className="text-ops-muted text-xs mt-1 tracking-wider">ENTER TRUCK IDENTIFICATION</div>
      </div>

      <form onSubmit={handleSubmit} className="w-full max-w-xs">
        <label className="block text-ops-muted text-xs tracking-widest uppercase mb-2">
          Truck ID
        </label>
        <input
          value={input}
          onChange={(e) => { setInput(e.target.value); setError('') }}
          placeholder="TRUCK_01"
          autoFocus
          autoCapitalize="characters"
          autoCorrect="off"
          autoComplete="off"
          spellCheck="false"
          className="w-full bg-ops-surface border-2 border-ops-border text-ops-text
            text-xl font-mono rounded px-4 py-3 outline-none focus:border-ops-cyan
            transition-colors placeholder:text-ops-muted/40 uppercase tracking-widest"
          style={{ caretColor: '#00d4ff' }}
        />
        {error && (
          <p className="text-ops-red text-xs mt-2 font-mono">{error}</p>
        )}
        <button
          type="submit"
          className="mt-5 w-full bg-ops-green text-black font-mono font-black
            text-base tracking-widest py-4 rounded transition-opacity
            active:opacity-80 select-none"
        >
          START SHIFT
        </button>
      </form>
    </div>
  )
}

// ── Shift view ────────────────────────────────────────────────────────────────

function ShiftView({ onEndShift }) {
  const truckId            = useDriverStore((s) => s.truckId)
  const currentStop        = useDriverStore((s) => s.currentStop)
  const nextStop           = useDriverStore((s) => s.nextStop)
  const allStops           = useDriverStore((s) => s.allStops)
  const stopsCompleted     = useDriverStore((s) => s.stopsCompleted)
  const loadLiters         = useDriverStore((s) => s.loadLiters)
  const capacityLiters     = useDriverStore((s) => s.capacityLiters)
  const advanceStop        = useDriverStore((s) => s.advanceStop)
  const isConnected        = useDriverStore((s) => s.isConnected)

  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError]     = useState(null)

  useDriverRoute()
  useDriverTruck()

  const remaining = allStops.length
  const total     = stopsCompleted + remaining
  const pct       = total > 0 ? (stopsCompleted / total) * 100 : 0
  const loadPct   = capacityLiters > 0
    ? Math.round((loadLiters / capacityLiters) * 100)
    : 0

  const isBin  = currentStop?.node_type === 'bin'
  const isDump = currentStop?.node_type === 'dump_yard'
  const fillL  = currentStop?.fill_collected_liters ?? 0

  const etaSec = currentStop?.arrival_time_seconds
  const etaStr = !etaSec || etaSec <= 0 ? null
    : etaSec < 3600
      ? `~${Math.floor(etaSec / 60)}m`
      : `~${Math.floor(etaSec / 3600)}h ${Math.floor((etaSec % 3600) / 60)}m`

  async function handleAction() {
    if (!currentStop || actionLoading) return
    if ('vibrate' in navigator) navigator.vibrate(50)
    setActionLoading(true)
    setActionError(null)
    advanceStop(fillL)
    try {
      if (isBin)        await driverApi.confirmCollection(truckId, currentStop.node_id, fillL)
      else if (isDump)  await driverApi.confirmDump(truckId, currentStop.node_id)
    } catch {
      setActionError('Sync failed — will retry on reconnect')
    } finally {
      setActionLoading(false)
    }
  }

  // Auto-complete when all stops done
  useEffect(() => {
    if (stopsCompleted > 0 && allStops.length === 0 && !currentStop) onEndShift()
  }, [stopsCompleted, allStops.length, currentStop]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col h-full bg-ops-bg font-mono overflow-hidden">

      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b border-ops-border shrink-0"
        style={{ background: '#0a1018' }}
      >
        <div>
          <span className="text-ops-muted text-xs">TRUCK </span>
          <span className="text-ops-cyan text-sm font-bold">{truckId}</span>
        </div>
        <div className="flex items-center gap-3">
          <span style={{ color: isConnected ? '#00ff88' : '#4a6280', fontSize: 10 }}>
            ● {isConnected ? 'LIVE' : 'OFFLINE'}
          </span>
          <button
            onClick={onEndShift}
            className="text-ops-muted text-xs border border-ops-border rounded px-2 py-1
              hover:text-ops-red hover:border-ops-red transition-colors"
          >
            END SHIFT
          </button>
        </div>
      </div>

      {/* Route progress */}
      {total > 0 && (
        <div className="px-4 py-2 border-b border-ops-border shrink-0">
          <div className="flex justify-between text-xs text-ops-muted mb-1.5">
            <span>Stop {Math.min(stopsCompleted + 1, total)} of {total}</span>
            <span>{stopsCompleted} done · {remaining} left</span>
          </div>
          <div className="h-1.5 rounded-full" style={{ background: '#1a2535' }}>
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{ width: `${pct}%`, background: '#00ff88' }}
            />
          </div>
        </div>
      )}

      {/* Current stop */}
      <div className="flex-1 flex flex-col justify-center px-4 py-4 min-h-0">
        {!currentStop ? (
          <div className="text-center">
            <div className="text-5xl mb-3 select-none">✓</div>
            <div className="text-ops-green text-lg font-bold tracking-widest">ALL STOPS DONE</div>
            <div className="text-ops-muted text-xs mt-1 tracking-wider">RETURN TO DEPOT</div>
          </div>
        ) : (
          <div className="border border-ops-border rounded bg-ops-surface p-4">
            <div className="text-ops-muted text-xs tracking-widest mb-2">
              {isBin ? 'COLLECT BIN' : isDump ? 'DUMP YARD' : 'STOP'}
            </div>
            <div className="text-ops-text text-3xl font-bold tracking-tight break-all leading-tight">
              {currentStop.node_id}
            </div>
            {isBin && fillL > 0 && (
              <div className="mt-3 flex items-baseline gap-2">
                <span className="text-ops-green text-xl font-bold">{Math.round(fillL)}L</span>
                <span className="text-ops-muted text-sm">to collect</span>
              </div>
            )}
            {etaStr && (
              <div className="mt-3 pt-3 border-t border-ops-border flex items-center gap-2 text-sm">
                <span className="text-ops-muted">⏱ ETA</span>
                <span className="text-ops-text font-bold">{etaStr}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Next stop + load bar */}
      <div className="shrink-0 px-4 space-y-2 pb-2">
        {nextStop && (
          <div className="flex items-center gap-3 border border-ops-border rounded bg-ops-surface px-3 py-2">
            <span className="text-lg select-none">
              {nextStop.node_type === 'dump_yard' ? '⛽' : '🗑'}
            </span>
            <div>
              <div className="text-ops-muted text-xs tracking-widest">
                {nextStop.node_type === 'dump_yard' ? 'NEXT: DUMP' : 'NEXT BIN'}
              </div>
              <div className="text-ops-text font-bold text-sm">{nextStop.node_id}</div>
            </div>
          </div>
        )}

        <div className="border border-ops-border rounded bg-ops-surface px-3 py-2">
          <div className="flex justify-between text-xs mb-1.5">
            <span className="text-ops-muted">TRUCK LOAD</span>
            <span className="text-ops-text tabular-nums">
              {loadPct}%  ({Math.round(loadLiters)}L / {capacityLiters}L)
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-ops-bg">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${loadPct}%`,
                background: loadPct >= 90 ? '#ff3355' : loadPct >= 70 ? '#ffaa00' : '#00ff88',
              }}
            />
          </div>
        </div>
      </div>

      {/* Action button */}
      {currentStop && (
        <div className="shrink-0 px-4 pb-4 pt-2">
          {actionError && (
            <p className="text-ops-red text-xs text-center mb-2 font-mono">{actionError}</p>
          )}
          <button
            onPointerDown={handleAction}
            disabled={actionLoading}
            className="w-full font-black text-xl tracking-widest py-6 rounded
              disabled:opacity-50 transition-opacity select-none"
            style={{
              background: isBin ? '#00ff88' : '#ffaa00',
              color: '#000',
              fontFamily: 'JetBrains Mono, Courier New, monospace',
            }}
          >
            {actionLoading ? '…' : isBin ? 'COLLECTED' : isDump ? 'DUMP COMPLETE' : 'DONE'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Summary view ──────────────────────────────────────────────────────────────

function SummaryView({ onNewShift }) {
  const binsCollectedToday   = useDriverStore((s) => s.binsCollectedToday)
  const litersCollectedToday = useDriverStore((s) => s.litersCollectedToday)
  const truckId              = useDriverStore((s) => s.truckId)

  return (
    <div className="flex flex-col items-center justify-center h-full font-mono px-8 bg-ops-bg">
      <div className="text-center mb-8">
        <div className="text-5xl mb-4 select-none">✓</div>
        <div className="text-ops-green text-xl font-bold tracking-widest">SHIFT COMPLETE</div>
        <div className="text-ops-muted text-xs mt-1 tracking-wider">{truckId}</div>
      </div>

      <div className="w-full max-w-xs border border-ops-border rounded bg-ops-surface p-4 mb-6">
        <div className="flex justify-between py-2 border-b border-ops-border">
          <span className="text-ops-muted text-xs tracking-wider">BINS COLLECTED</span>
          <span className="text-ops-cyan font-bold tabular-nums">{binsCollectedToday}</span>
        </div>
        <div className="flex justify-between py-2">
          <span className="text-ops-muted text-xs tracking-wider">WASTE COLLECTED</span>
          <span className="text-ops-cyan font-bold tabular-nums">
            {Math.round(litersCollectedToday)}L
          </span>
        </div>
      </div>

      <button
        onClick={onNewShift}
        className="w-full max-w-xs border border-ops-border text-ops-muted
          hover:text-ops-cyan hover:border-ops-cyan transition-colors
          py-3 rounded tracking-widest text-sm"
      >
        NEW SHIFT
      </button>
    </div>
  )
}

// ── Root component ────────────────────────────────────────────────────────────

export default function DriverSim() {
  const [view, setView]   = useState('login')
  const truckId           = useDriverStore((s) => s.truckId)
  const setTruckId        = useDriverStore((s) => s.setTruckId)
  const startShift        = useDriverStore((s) => s.startShift)

  // Restore persisted session on mount
  useEffect(() => {
    if (truckId && view === 'login') setView('shift')
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function handleLogin(id) {
    setTruckId(id)
    startShift()
    driverSocket.connect(id)
    setView('shift')
  }

  function handleEndShift() {
    driverSocket.disconnect()
    setView('summary')
  }

  function handleNewShift() {
    setTruckId(null)
    setView('login')
  }

  return (
    <div className="h-full overflow-hidden">
      {view === 'login'   && <LoginView   onLogin={handleLogin} />}
      {view === 'shift'   && <ShiftView   onEndShift={handleEndShift} />}
      {view === 'summary' && <SummaryView onNewShift={handleNewShift} />}
    </div>
  )
}
