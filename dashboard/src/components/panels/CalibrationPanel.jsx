'use client'
import { useEffect, useState } from 'react'
import useDashboardStore from '../../store/dashboardStore'
import { calibrationApi } from '../../lib/apiClient'

function StatBox({ label, value }) {
  return (
    <div className="flex-1 border border-ops-border rounded px-3 py-2 bg-ops-bg">
      <div className="text-ops-muted text-xs font-mono uppercase tracking-wider">{label}</div>
      <div className="text-ops-cyan text-sm font-mono font-bold tabular-nums mt-0.5">
        {value ?? '—'}
      </div>
    </div>
  )
}

function StatusBadge({ status }) {
  const colors = {
    done:    'text-green-400',
    running: 'text-ops-cyan',
    queued:  'text-yellow-400',
    failed:  'text-red-400',
  }
  return (
    <span className={`text-xs font-mono uppercase ${colors[status] ?? 'text-ops-muted'}`}>
      {status}
    </span>
  )
}

export default function CalibrationPanel() {
  const fleetAccuracy     = useDashboardStore((s) => s.fleetAccuracy)
  const worstBins         = useDashboardStore((s) => s.worstBins)
  const retrainJobs       = useDashboardStore((s) => s.retrainJobs)
  const setCalibrationData = useDashboardStore((s) => s.setCalibrationData)

  const [queueDepth, setQueueDepth]     = useState(0)
  const [retriggered, setRetriggered]   = useState({})
  const [retrainAllPending, setRetrainAllPending] = useState(false)

  useEffect(() => {
    let active = true

    async function poll() {
      try {
        const [fleet, worst, jobs, health] = await Promise.all([
          calibrationApi.fleetAccuracy(),
          calibrationApi.worstBins(10),
          calibrationApi.retrainJobs(20),
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
        5000,
      )
    } catch {}
  }

  async function handleRetrainAll() {
    setRetrainAllPending(true)
    try {
      await calibrationApi.triggerRetrainFleet()
    } finally {
      setRetrainAllPending(false)
    }
  }

  const mae       = fleetAccuracy?.mae != null ? `${fleetAccuracy.mae.toFixed(2)}h` : null
  const within1h  = fleetAccuracy?.within1h_pct != null
    ? `${(fleetAccuracy.within1h_pct * 100).toFixed(0)}%`
    : null

  return (
    <div className="flex flex-col h-full bg-ops-bg text-ops-text font-mono text-xs overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-ops-border shrink-0">
        <span className="text-ops-cyan text-xs font-bold tracking-wider">
          CALIBRATION PANEL
        </span>
        <button
          onClick={handleRetrainAll}
          disabled={retrainAllPending}
          className="px-2 py-1 border border-ops-border text-ops-muted hover:text-ops-cyan hover:border-ops-cyan transition-colors disabled:opacity-40"
        >
          {retrainAllPending ? 'queuing…' : 'RETRAIN ALL'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Fleet stats */}
        <div className="flex gap-2 px-3 py-2 border-b border-ops-border">
          <StatBox label="Fleet MAE" value={mae} />
          <StatBox label="Within 1h" value={within1h} />
        </div>

        {/* Queue depth */}
        <div className="px-3 py-1.5 border-b border-ops-border">
          <span className="text-ops-muted">Retrain queue: </span>
          <span className={queueDepth > 0 ? 'text-yellow-400' : 'text-ops-muted'}>
            {queueDepth} {queueDepth === 1 ? 'bin' : 'bins'}
          </span>
        </div>

        {/* Worst bins table */}
        <div className="border-b border-ops-border">
          <div className="px-3 py-1.5 text-ops-muted uppercase tracking-wider">
            Worst performing bins (7d)
          </div>
          {worstBins.length === 0 && (
            <div className="px-3 py-2 text-ops-muted">No data</div>
          )}
          {worstBins.map((bin) => (
            <div
              key={bin.bin_id}
              className="flex items-center gap-2 px-3 py-1 border-t border-ops-border/50 hover:bg-ops-border/20"
            >
              <span className="text-ops-cyan truncate flex-1">{bin.bin_id}</span>
              <span className="text-red-400 tabular-nums w-12 text-right">
                {typeof bin.mae === 'number' ? `${bin.mae.toFixed(2)}h` : '—'}
              </span>
              <span className="text-ops-muted w-20 truncate">{bin.model_used ?? '—'}</span>
              <button
                onClick={() => handleRetrain(bin.bin_id)}
                disabled={!!retriggered[bin.bin_id]}
                className="px-1.5 py-0.5 border border-ops-border text-ops-muted hover:text-ops-cyan hover:border-ops-cyan transition-colors disabled:text-green-400 disabled:border-green-400 shrink-0"
              >
                {retriggered[bin.bin_id] ? '✓' : 'retrain'}
              </button>
            </div>
          ))}
        </div>

        {/* Recent retrain jobs */}
        <div>
          <div className="px-3 py-1.5 text-ops-muted uppercase tracking-wider">
            Recent retrain jobs
          </div>
          {retrainJobs.length === 0 && (
            <div className="px-3 py-2 text-ops-muted">No jobs yet</div>
          )}
          {retrainJobs.slice(0, 10).map((job, i) => (
            <div
              key={job.job_id ?? i}
              className="flex items-center gap-2 px-3 py-1 border-t border-ops-border/50 hover:bg-ops-border/20"
            >
              <span className="text-ops-cyan truncate flex-1">{job.target_id}</span>
              <span className="text-ops-muted w-14 truncate">{job.target_type}</span>
              <StatusBadge status={job.status} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
