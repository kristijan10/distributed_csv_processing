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
import { getSweepMetrics, getSweepRuns } from '../api'
import { SERIES_COLORS, mergeByWorkerCount } from '../utils/chartSeries'

const MODE_LABELS = {
  baseline: 'Baseline',
  noop: 'No-op transform (I/O only)',
}

const IDEAL_COLOR = '#94a3b8'

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

function runLabel(run) {
  return `${MODE_LABELS[run.mode] ?? run.mode} · ${run.row_count.toLocaleString()} rows`
}

export default function MetricsPanel() {
  const [series, setSeries] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const runs = await getSweepRuns()
        if (cancelled) return
        if (runs.length === 0) {
          setSeries([])
          return
        }

        const withPoints = await Promise.all(
          runs.map(async (run) => {
            const points = await getSweepMetrics(run.mode, run.row_count)
            return { ...run, points }
          }),
        )
        if (cancelled) return

        setSeries(
          withPoints.map((run, i) => ({
            key: `${run.mode}_${run.row_count}`,
            label: runLabel(run),
            color: SERIES_COLORS[i % SERIES_COLORS.length],
            points: run.points,
          })),
        )
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  if (series === null && !error) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">Loading benchmark data…</p>
  }

  if (series && series.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <p>No benchmark sweep results yet.</p>
        <p className="mt-2">
          Drop one or more CSVs into <span className="font-mono">backend/scripts/sweep_input/</span>, then:
        </p>
        <p className="mt-1 font-mono text-xs">python backend/scripts/worker_sweep.py --mode baseline</p>
        <p className="mt-1">
          Restart the backend with <code>NOOP_TRANSFORM=1</code> and run{' '}
          <span className="font-mono">--mode noop</span> to also compare I/O-only scaling.
        </p>
      </div>
    )
  }

  if (error) {
    return <p className="text-sm text-red-600 dark:text-red-400">Could not load metrics: {error}</p>
  }

  const speedupData = mergeByWorkerCount(series, 'speedup')
  const efficiencyData = mergeByWorkerCount(series, 'efficiency')
  const wallData = mergeByWorkerCount(series, 'wall_s')
  const throughputData = mergeByWorkerCount(series, 'throughput_rows_per_s')

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <ChartCard title="Speedup" subtitle="Relative to 1 worker">
        <LineChart data={speedupData}>
          <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
          <XAxis dataKey="worker_count" tick={AXIS_TICK} label={{ value: 'Workers', position: 'insideBottom', offset: -5, fontSize: 12 }} />
          <YAxis tick={AXIS_TICK} />
          <Tooltip />
          <Legend />
          {series.map((s) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} />
          ))}
        </LineChart>
      </ChartCard>

      <ChartCard title="Parallel efficiency" subtitle="Speedup divided by worker count (1.0 = perfect scaling)">
        <LineChart data={efficiencyData}>
          <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
          <XAxis dataKey="worker_count" tick={AXIS_TICK} />
          <YAxis tick={AXIS_TICK} domain={[0, 1.1]} />
          <Tooltip />
          <Legend />
          <ReferenceLine y={1} stroke={IDEAL_COLOR} strokeDasharray="4 4" />
          {series.map((s) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} />
          ))}
        </LineChart>
      </ChartCard>

      <ChartCard title="Wall-clock time" subtitle="Total job time by worker count">
        <BarChart data={wallData}>
          <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
          <XAxis dataKey="worker_count" tick={AXIS_TICK} />
          <YAxis tick={AXIS_TICK} unit="s" />
          <Tooltip />
          <Legend />
          {series.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[4, 4, 0, 0]} />
          ))}
        </BarChart>
      </ChartCard>

      <ChartCard title="Throughput" subtitle="Rows processed per second">
        <BarChart data={throughputData}>
          <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
          <XAxis dataKey="worker_count" tick={AXIS_TICK} />
          <YAxis tick={AXIS_TICK} />
          <Tooltip />
          <Legend />
          {series.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[4, 4, 0, 0]} />
          ))}
        </BarChart>
      </ChartCard>
    </div>
  )
}
