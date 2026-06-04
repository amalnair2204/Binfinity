'use client'
import { useEffect, useState } from 'react'
import useDashboardStore     from '../../store/dashboardStore'
import { calibrationApi }   from '../../lib/apiClient'

function StatBox({ label, value, color = '#00d4ff' }) {
  return (
    <div className="border border-ops-border rounded bg-ops-surface px-4 py-3">
      <div className="text-ops-muted text-xs tracking-wider uppercase">{label}</div>
      <div className="font-bold text-xl tabular-nums mt-1" style={{ color }}>
        {value ?? '—'}
      </div>
    </div>
  )
}

function StatusBadge({ status }) {
  const map = {
    done:    { color: '#00ff88' },
    running: { color: '#00d4ff' },
    queued:  { color: '#ffaa00' },
    failed:  { color: '#ff3355' },
  }
  const { color } = map[status] ?? { color: '#4a6280' }
  return (
    <span className="text-xs font-mono uppercase" style={{ color }}>{status}</span>
  )
}

export default function MLPage() {
  const predictions    = useDashboardStore((s) => s.mlPredictions)
  const fleetAccuracy  = useDashboardStore((s) => s.fleetAccuracy)
  const worstBins      = useDashboardStore((s) => s.worstBins)
  const retrainJobs    = useDashboardStore((s) => s.retrainJobs)
  const setCalibrationData = useDashboardStore((s) => s.setCalibrationData)

  const [queueDepth, setQueueDepth]                   = useState(0)
  const [retriggered, setRetriggered]                 = useState({})
  const [retrainAllPending, setRetrainAllPending]     = useState(false)
  const [filter, setFilter]                           = useState('all')

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const [fleet, worst, jobs, health] = await Promise.all([
          calibrationApi.fleetAccuracy(),
          calibrationApi.worstBins(20),
          calibrationApi.retrainJobs(50),
          calibrationApi.health(),
        ])
        if (active) {
          setCalibrationData({ fleetAccuracy: fleet, worstBins: worst, retrainJobs: jobs })
          setQueueDepth(health?.queue_size ?? 0)
        }
      } catch {}
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { active = false; clearInterval(id) }
  }, [setCalibrationData])

  async function handleRetrain(binId) {
    try {
      await calibrationApi.triggerRetrain(binId, { reason: 'manual dashboard' })
      setRetriggered((r) => ({ ...r, [binId]: true }))
      setTimeout(
        () => setRetriggered((r) => { const n = { ...r }; delete n[binId]; return n }),
        5_000,
      )
    } catch {}
  }

  async function handleRetrainAll() {
    setRetrainAllPending(true)
    try { await calibrationApi.triggerRetrainFleet() } finally { setRetrainAllPending(false) }
  }

  const mae      = fleetAccuracy?.mae != null ? `${fleetAccuracy.mae.toFixed(2)}h` : null
  const within1h = fleetAccuracy?.within1h_pct != null
    ? `${(fleetAccuracy.within1h_pct * 100).toFixed(0)}%`
    : null

  const sorted = [...predictions].sort((a, b) => a.hours_until_critical - b.hours_until_critical)
  const filtered = filter === 'all' ? sorted
    : filter === '1h'  ? sorted.filter((p) => p.hours_until_critical < 1)
    : filter === '2h'  ? sorted.filter((p) => p.hours_until_critical < 2)
    : sorted.filter((p) => p.hours_until_critical < 4)

  return (
    <div className="flex flex-col h-full overflow-hidden bg-ops-bg font-mono">

      {/* Page header */}
      <div
        className="flex items-center justify-between px-4 border-b border-ops-border shrink-0"
        style={{ height: 40, background: '#0a1018' }}
      >
        <span className="text-ops-cyan text-xs font-bold tracking-widest">ML INSIGHTS</span>
        <button
          onClick={handleRetrainAll}
          disabled={retrainAllPending}
          className="text-xs border border-ops-border text-ops-muted px-2 py-1 rounded
            hover:text-ops-cyan hover:border-ops-cyan transition-colors disabled:opacity-40"
        >
          {retrainAllPending ? 'QUEUING…' : 'RETRAIN ALL'}
        </button>
      </div>

      {/* Two-column layout */}
      <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0 }}>

        {/* Left: predictions */}
        <div className="flex flex-col border-r border-ops-border overflow-hidden" style={{ width: '50%' }}>

          {/* Stats row */}
          <div className="grid grid-cols-3 gap-2 p-3 border-b border-ops-border shrink-0">
            <StatBox label="Fleet MAE"   value={mae} />
            <StatBox label="Within 1h"   value={within1h} color="#00ff88" />
            <StatBox
              label="Queue"
              value={queueDepth > 0 ? `${queueDepth} bins` : 'empty'}
              color={queueDepth > 0 ? '#ffaa00' : '#4a6280'}
            />
          </div>

          {/* Filter tabs */}
          <div className="flex border-b border-ops-border shrink-0" style={{ background: '#0d1520' }}>
            {[
              { key: 'all', label: 'ALL' },
              { key: '4h',  label: '< 4h' },
              { key: '2h',  label: '< 2h' },
              { key: '1h',  label: '< 1h CRITICAL' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                style={{
                  background:   'none',
                  border:       'none',
                  borderBottom: filter === key ? '2px solid #00d4ff' : '2px solid transparent',
                  color:        filter === key ? '#00d4ff' : '#4a6280',
                  cursor:       'pointer',
                  fontFamily:   'inherit',
                  fontSize:     10,
                  letterSpacing: '0.06em',
                  padding:      '6px 12px',
                }}
              >
                {label}
              </button>
            ))}
            <span className="ml-auto text-ops-muted text-xs self-center pr-3">
              {filtered.length} bins
            </span>
          </div>

          {/* Prediction rows */}
          <div className="flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="text-ops-muted text-xs text-center py-8 tracking-wider">
                NO PREDICTIONS IN THIS RANGE
              </div>
            ) : filtered.map((pred) => {
              const h = pred.hours_until_critical
              const color = h < 1 ? '#ff3355' : h < 2 ? '#ff6600' : '#ffaa00'
              const timeStr = h < 0.1 ? '<6m' : h < 1 ? `${Math.round(h * 60)}m` : `${h.toFixed(1)}h`
              return (
                <div
                  key={pred.bin_id}
                  className="flex items-center gap-2 px-3 py-1.5 border-b border-ops-border hover:bg-ops-border/10"
                >
                  <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color }} />
                  <span className="text-ops-cyan text-xs truncate flex-1">{pred.bin_id}</span>
                  <span className="text-xs tabular-nums" style={{ color }}>{timeStr}</span>
                  <span className="text-ops-muted text-xs tabular-nums w-10 text-right">
                    {(pred.predicted_fill_pct ?? 0).toFixed(0)}%
                  </span>
                  {pred.model_name && (
                    <span className="text-ops-muted text-xs w-16 truncate">{pred.model_name}</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Right: calibration + jobs */}
        <div className="flex flex-col overflow-hidden" style={{ width: '50%' }}>

          {/* Worst bins */}
          <div className="border-b border-ops-border shrink-0" style={{ maxHeight: '50%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div className="px-3 py-2 border-b border-ops-border shrink-0">
              <span className="text-ops-cyan text-xs font-bold tracking-wider">
                WORST BINS — 7D MAE
              </span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {worstBins.length === 0 ? (
                <div className="text-ops-muted text-xs text-center py-4">No data</div>
              ) : worstBins.map((bin) => (
                <div
                  key={bin.bin_id}
                  className="flex items-center gap-2 px-3 py-1.5 border-b border-ops-border/50 hover:bg-ops-border/10"
                >
                  <span className="text-ops-cyan text-xs truncate flex-1">{bin.bin_id}</span>
                  <span className="text-ops-red text-xs tabular-nums w-12 text-right">
                    {typeof bin.mae === 'number' ? `${bin.mae.toFixed(2)}h` : '—'}
                  </span>
                  <span className="text-ops-muted text-xs w-16 truncate">{bin.model_used ?? '—'}</span>
                  <button
                    onClick={() => handleRetrain(bin.bin_id)}
                    disabled={!!retriggered[bin.bin_id]}
                    className="text-xs px-1.5 py-0.5 border border-ops-border text-ops-muted
                      hover:text-ops-cyan hover:border-ops-cyan transition-colors
                      disabled:text-ops-green disabled:border-ops-green shrink-0"
                  >
                    {retriggered[bin.bin_id] ? '✓' : 'retrain'}
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Retrain jobs */}
          <div className="flex flex-col flex-1 overflow-hidden">
            <div className="px-3 py-2 border-b border-ops-border shrink-0">
              <span className="text-ops-cyan text-xs font-bold tracking-wider">
                RETRAIN JOBS
              </span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {retrainJobs.length === 0 ? (
                <div className="text-ops-muted text-xs text-center py-4">No jobs yet</div>
              ) : retrainJobs.map((job, i) => (
                <div
                  key={job.job_id ?? i}
                  className="flex items-center gap-2 px-3 py-1.5 border-b border-ops-border/50 hover:bg-ops-border/10"
                >
                  <span className="text-ops-cyan text-xs truncate flex-1">{job.target_id}</span>
                  <span className="text-ops-muted text-xs w-14 truncate">{job.target_type}</span>
                  <StatusBadge status={job.status} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
