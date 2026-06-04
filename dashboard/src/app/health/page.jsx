'use client'
import { useCallback, useEffect, useState } from 'react'
import useDashboardStore from '../../store/dashboardStore'

const SERVICES = [
  { name: 'Emulator',   key: 'emulator',   url: process.env.NEXT_PUBLIC_EMULATOR_API    || 'http://localhost:8000', port: 8000 },
  { name: 'Ingestion',  key: 'ingestion',  url: process.env.NEXT_PUBLIC_INGESTION_API   || 'http://localhost:8001', port: 8001 },
  { name: 'Geospatial', key: 'geospatial', url: process.env.NEXT_PUBLIC_GEO_API         || 'http://localhost:8002', port: 8002 },
  { name: 'ML',         key: 'ml',         url: process.env.NEXT_PUBLIC_ML_API          || 'http://localhost:8003', port: 8003 },
  { name: 'Exogenous',  key: 'exogenous',  url: process.env.NEXT_PUBLIC_EXOGENOUS_API   || 'http://localhost:8004', port: 8004 },
  { name: 'Routing',    key: 'routing',    url: process.env.NEXT_PUBLIC_ROUTING_API      || 'http://localhost:8005', port: 8005 },
  { name: 'Feedback',   key: 'feedback',   url: process.env.NEXT_PUBLIC_FEEDBACK_API    || 'http://localhost:8006', port: 8006 },
]

async function pingService(base) {
  const start = performance.now()
  try {
    const res = await fetch(`${base}/health`, {
      cache:  'no-store',
      signal: AbortSignal.timeout(4_000),
    })
    const ms   = Math.round(performance.now() - start)
    const data = await res.json().catch(() => null)
    return { up: res.ok, ms, detail: data }
  } catch {
    return { up: false, ms: null, detail: null }
  }
}

function ServiceCard({ svc, result, onPing }) {
  const up = result?.up

  return (
    <div
      className="border rounded p-3"
      style={{
        borderColor: up == null ? '#1a2535' : up ? 'rgba(0,255,136,0.3)' : 'rgba(255,51,85,0.3)',
        background:  up == null ? '#0d1520' : up ? 'rgba(0,255,136,0.04)' : 'rgba(255,51,85,0.04)',
        fontFamily:  'JetBrains Mono, Courier New, monospace',
      }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-ops-text text-sm font-bold">{svc.name}</span>
        <div className="flex items-center gap-2">
          {up == null ? (
            <span className="text-ops-muted text-xs">—</span>
          ) : up ? (
            <span className="text-xs font-bold" style={{ color: '#00ff88' }}>● UP</span>
          ) : (
            <span className="text-xs font-bold" style={{ color: '#ff3355' }}>● DOWN</span>
          )}
        </div>
      </div>

      <div className="text-ops-muted text-xs font-mono mb-1">
        :{svc.port} — {svc.url}/health
      </div>

      {result?.ms != null && (
        <div className="text-xs text-ops-muted">
          Latency: <span className="text-ops-text tabular-nums">{result.ms}ms</span>
        </div>
      )}

      {result?.detail && (
        <div className="mt-1.5 text-xs text-ops-muted space-y-0.5">
          {Object.entries(result.detail)
            .filter(([k]) => k !== 'status')
            .slice(0, 4)
            .map(([k, v]) => (
              <div key={k}>
                <span className="text-ops-muted">{k}: </span>
                <span className="text-ops-text">{String(v)}</span>
              </div>
            ))}
        </div>
      )}

      <div className="mt-2 flex gap-2">
        <button
          onClick={() => onPing(svc)}
          className="text-xs border border-ops-border text-ops-muted px-2 py-0.5 rounded
            hover:text-ops-cyan hover:border-ops-cyan transition-colors"
        >
          ping
        </button>
        <a
          href={`${svc.url}/metrics`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs border border-ops-border text-ops-muted px-2 py-0.5 rounded
            hover:text-ops-cyan hover:border-ops-cyan transition-colors"
        >
          metrics ↗
        </a>
        <a
          href={`${svc.url}/docs`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs border border-ops-border text-ops-muted px-2 py-0.5 rounded
            hover:text-ops-cyan hover:border-ops-cyan transition-colors"
        >
          docs ↗
        </a>
      </div>
    </div>
  )
}

export default function HealthPage() {
  const alerts   = useDashboardStore((s) => s.alerts)
  const wsStatus = useDashboardStore((s) => s.wsStatus)

  const [results, setResults]   = useState({})
  const [loading, setLoading]   = useState(false)
  const [lastCheck, setLastCheck] = useState(null)

  const pingAll = useCallback(async () => {
    setLoading(true)
    const checks = await Promise.all(
      SERVICES.map(async (svc) => [svc.key, await pingService(svc.url)]),
    )
    setResults(Object.fromEntries(checks))
    setLastCheck(new Date())
    setLoading(false)
  }, [])

  const pingSingle = useCallback(async (svc) => {
    const r = await pingService(svc.url)
    setResults((prev) => ({ ...prev, [svc.key]: r }))
  }, [])

  useEffect(() => { pingAll() }, [pingAll])

  const upCount   = Object.values(results).filter((r) => r.up).length
  const downCount = Object.values(results).filter((r) => r.up === false).length

  return (
    <div className="flex flex-col h-full overflow-hidden bg-ops-bg font-mono">

      {/* Page header */}
      <div
        className="flex items-center justify-between px-4 border-b border-ops-border shrink-0"
        style={{ height: 40, background: '#0a1018' }}
      >
        <span className="text-ops-cyan text-xs font-bold tracking-widest">SYSTEM HEALTH</span>
        <div className="flex items-center gap-4">
          {Object.keys(results).length > 0 && (
            <span className="text-xs">
              <span style={{ color: '#00ff88' }}>{upCount} UP</span>
              {downCount > 0 && <span style={{ color: '#ff3355' }}> · {downCount} DOWN</span>}
            </span>
          )}
          {lastCheck && (
            <span className="text-ops-muted text-xs">
              Last check: {lastCheck.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={pingAll}
            disabled={loading}
            className="text-xs border border-ops-border text-ops-muted px-2 py-1 rounded
              hover:text-ops-cyan hover:border-ops-cyan transition-colors disabled:opacity-40"
          >
            {loading ? 'PINGING…' : 'REFRESH ALL'}
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0 }}>

        {/* Service grid */}
        <div className="flex-1 overflow-y-auto p-3 border-r border-ops-border">
          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
            {SERVICES.map((svc) => (
              <ServiceCard
                key={svc.key}
                svc={svc}
                result={results[svc.key]}
                onPing={pingSingle}
              />
            ))}
          </div>

          {/* Prometheus + Grafana links */}
          <div className="mt-4 border border-ops-border rounded p-3">
            <div className="text-ops-cyan text-xs font-bold tracking-wider mb-2">
              MONITORING STACK
            </div>
            <div className="flex gap-3 flex-wrap">
              {[
                { label: 'Prometheus',  href: 'http://localhost:9090' },
                { label: 'Grafana',     href: 'http://localhost:3002' },
              ].map(({ label, href }) => (
                <a
                  key={label}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs border border-ops-border text-ops-muted px-3 py-1.5 rounded
                    hover:text-ops-cyan hover:border-ops-cyan transition-colors"
                >
                  {label} ↗
                </a>
              ))}
            </div>
          </div>
        </div>

        {/* Right panel: WebSocket + recent alerts */}
        <div className="flex flex-col overflow-hidden" style={{ width: 320 }}>

          {/* WebSocket status */}
          <div className="border-b border-ops-border p-3 shrink-0">
            <div className="text-ops-cyan text-xs font-bold tracking-wider mb-2">WEBSOCKET</div>
            <div className="flex items-center gap-2">
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{
                  background: wsStatus === 'connected' ? '#00ff88'
                    : wsStatus === 'reconnecting' ? '#ffaa00' : '#ff3355',
                }}
              />
              <span className="text-ops-text text-xs uppercase tracking-wider">{wsStatus}</span>
            </div>
          </div>

          {/* Recent alerts */}
          <div className="px-3 py-2 border-b border-ops-border shrink-0">
            <span className="text-ops-cyan text-xs font-bold tracking-wider">
              RECENT EVENTS ({alerts.length})
            </span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {alerts.length === 0 ? (
              <div className="text-ops-muted text-xs text-center py-6 tracking-wider">
                NO EVENTS
              </div>
            ) : alerts.slice(0, 50).map((alert, i) => {
              const isErr = alert.event_type === 'overflow_alert' || alert.event_type === 'tip_over'
              return (
                <div
                  key={alert.event_id ?? i}
                  className="flex items-start gap-2 px-3 py-1.5 border-b border-ops-border/50 hover:bg-ops-border/10"
                >
                  <span style={{ color: isErr ? '#ff3355' : '#ffaa00', fontSize: 10, lineHeight: '20px' }}>
                    {isErr ? '⚠' : '●'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-ops-muted uppercase tracking-wider truncate">
                      {(alert.event_type ?? '').replace(/_/g, ' ')}
                    </div>
                    {alert.affected_bin_id && (
                      <div className="text-xs text-ops-cyan truncate">{alert.affected_bin_id}</div>
                    )}
                    {alert.affected_truck_id && (
                      <div className="text-xs text-ops-muted truncate">{alert.affected_truck_id}</div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
