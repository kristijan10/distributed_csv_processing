import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getSweepMetrics, getSweepModes } from '../api'

const MODE_LABELS = {
  baseline: 'Baseline',
  noop: 'No-op transform (I/O only)',
}

const CARD =
  'rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900'

function ChartCard({ title, subtitle, children }) {
  return (
    <div className={CARD}>
      <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{title}</h3>
      {subtitle && <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
      <div className="mt-4 h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  )
}

const AXIS_TICK = { fontSize: 12 }
const GRID_STROKE = 'currentColor'
const GRID_CLASS = 'text-slate-200 dark:text-slate-800'

export default function MetricsPanel() {
  const [modes, setModes] = useState(null)
  const [mode, setMode] = useState(null)
  const [points, setPoints] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getSweepModes()
      .then((available) => {
        if (cancelled) return
        setModes(available)
        setMode((current) => current ?? available[0] ?? null)
      })
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!mode) return undefined
    let cancelled = false
    setPoints(null)
    setError(null)
    getSweepMetrics(mode)
      .then((data) => !cancelled && setPoints(data))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [mode])

  if (modes === null && !error) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">Loading benchmark data…</p>
  }

  if (modes && modes.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <p>No benchmark sweep results yet.</p>
        <p className="mt-2 font-mono text-xs">python backend/scripts/worker_sweep.py --mode baseline</p>
        <p className="mt-1">
          Restart the backend with <code>NOOP_TRANSFORM=1</code> and run{' '}
          <span className="font-mono">--mode noop</span> to also compare I/O-only scaling.
        </p>
      </div>
    )
  }

  return (
    <div>
      {modes && modes.length > 1 && (
        <div className="mb-4 flex gap-2">
          {modes.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                mode === m
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
              }`}
            >
              {MODE_LABELS[m] ?? m}
            </button>
          ))}
        </div>
      )}

      {error && <p className="text-sm text-red-600 dark:text-red-400">Could not load metrics: {error}</p>}

      {!error && !points && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}

      {points && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ChartCard title="Speedup" subtitle="Actual vs. ideal linear speedup, relative to 1 worker">
            <LineChart data={points}>
              <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
              <XAxis dataKey="worker_count" tick={AXIS_TICK} label={{ value: 'Workers', position: 'insideBottom', offset: -5, fontSize: 12 }} />
              <YAxis tick={AXIS_TICK} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="ideal_speedup" name="Ideal" stroke="#94a3b8" strokeDasharray="4 4" dot={false} />
              <Line type="monotone" dataKey="speedup" name="Actual" stroke="#4f46e5" strokeWidth={2} />
            </LineChart>
          </ChartCard>

          <ChartCard title="Parallel efficiency" subtitle="Speedup divided by worker count (1.0 = perfect scaling)">
            <LineChart data={points}>
              <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
              <XAxis dataKey="worker_count" tick={AXIS_TICK} />
              <YAxis tick={AXIS_TICK} domain={[0, 1.1]} />
              <Tooltip />
              <ReferenceLine y={1} stroke="#94a3b8" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="efficiency" name="Efficiency" stroke="#059669" strokeWidth={2} />
            </LineChart>
          </ChartCard>

          <ChartCard title="Wall-clock time" subtitle="Total job time by worker count">
            <BarChart data={points}>
              <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
              <XAxis dataKey="worker_count" tick={AXIS_TICK} />
              <YAxis tick={AXIS_TICK} unit="s" />
              <Tooltip />
              <Bar dataKey="wall_s" name="Wall time (s)" fill="#4f46e5" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ChartCard>

          <ChartCard title="Throughput" subtitle="Rows processed per second">
            <BarChart data={points}>
              <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
              <XAxis dataKey="worker_count" tick={AXIS_TICK} />
              <YAxis tick={AXIS_TICK} />
              <Tooltip />
              <Bar dataKey="throughput_rows_per_s" name="Rows/s" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ChartCard>
        </div>
      )}
    </div>
  )
}
