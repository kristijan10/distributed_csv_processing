import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import StatusBadge from './StatusBadge'
import { getJobWorkers } from '../api'
import { formatTime, formatDuration, formatSeconds } from '../utils/format'

const POLL_INTERVAL_MS = 3000

const PHASE_STYLES = {
  Pending: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  Running: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  Succeeded: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  Failed: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300',
  Unknown: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
}

function PhaseBadge({ phase }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        PHASE_STYLES[phase] ?? PHASE_STYLES.Unknown
      }`}
    >
      {phase}
    </span>
  )
}

export default function JobDetailModal({ job, onClose }) {
  const [workers, setWorkers] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const isTerminal = job.status === 'Completed' || job.status === 'Failed'

  useEffect(() => {
    let cancelled = false

    async function fetchWorkers() {
      try {
        const data = await getJobWorkers(job.id)
        if (!cancelled) {
          setWorkers(data)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchWorkers()
    if (isTerminal) return undefined

    const interval = setInterval(fetchWorkers, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [job.id, isTerminal])

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Details for ${job.original_filename}`}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="truncate text-lg font-semibold text-slate-900 dark:text-white">
              {job.original_filename}
            </h3>
            <p className="mt-1 truncate font-mono text-xs text-slate-500 dark:text-slate-400">{job.id}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
          >
            ✕
          </button>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Status</dt>
            <dd className="mt-1">
              <StatusBadge status={job.status} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Workers</dt>
            <dd className="mt-1 text-slate-700 dark:text-slate-300">{job.worker_count}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Rows</dt>
            <dd className="mt-1 text-slate-700 dark:text-slate-300">{job.row_count}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Created</dt>
            <dd className="mt-1 text-slate-700 dark:text-slate-300">{formatTime(job.created_at) ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Finished</dt>
            <dd className="mt-1 text-slate-700 dark:text-slate-300">{formatTime(job.finished_at) ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Queue time</dt>
            <dd className="mt-1 text-slate-700 dark:text-slate-300">
              {formatSeconds(job.queue_time_s) ?? '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Execution time</dt>
            <dd className="mt-1 text-slate-700 dark:text-slate-300">
              {formatSeconds(job.execution_time_s) ?? '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Throughput</dt>
            <dd className="mt-1 text-slate-700 dark:text-slate-300">
              {job.throughput_rows_per_s != null ? `${job.throughput_rows_per_s.toFixed(1)} rows/s` : '—'}
            </dd>
          </div>
        </dl>

        {job.status === 'Failed' && job.error_message && (
          <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
            {job.error_message}
          </p>
        )}

        <h4 className="mt-6 mb-2 text-sm font-semibold text-slate-900 dark:text-white">Workers</h4>

        {error && (
          <p className="mb-2 text-xs text-red-600 dark:text-red-400">Could not load worker status: {error}</p>
        )}

        {!error && loading && workers.length === 0 && (
          <p className="text-sm text-slate-500 dark:text-slate-400">Loading worker status…</p>
        )}

        {!error && !loading && workers.length === 0 && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {job.status === 'Pending'
              ? 'Workers have not been scheduled yet.'
              : 'No worker information available.'}
          </p>
        )}

        {workers.length > 0 && (
          <div className="overflow-hidden overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                <tr>
                  <th className="px-3 py-2 font-medium">#</th>
                  <th className="px-3 py-2 font-medium">Pod</th>
                  <th className="px-3 py-2 font-medium">Phase</th>
                  <th className="px-3 py-2 font-medium">Detail</th>
                  <th className="px-3 py-2 font-medium">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {workers.map((w) => (
                  <tr key={w.index ?? w.pod_name}>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{w.index ?? '—'}</td>
                    <td className="px-3 py-2 font-mono text-[11px] text-slate-500 dark:text-slate-400">
                      {w.pod_name ?? '—'}
                    </td>
                    <td className="px-3 py-2">
                      <PhaseBadge phase={w.phase} />
                    </td>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                      {w.phase === 'Failed' ? (
                        <span className="text-red-600 dark:text-red-400">
                          {[w.reason, w.exit_code != null ? `exit ${w.exit_code}` : null]
                            .filter(Boolean)
                            .join(' · ') || 'Failed'}
                          {w.message && (
                            <span className="mt-0.5 block text-[11px] text-red-500/80 dark:text-red-400/80">
                              {w.message}
                            </span>
                          )}
                        </span>
                      ) : (
                        (w.reason ?? '—')
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                      {formatDuration(w.started_at, w.finished_at) ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
