import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { SERIES_COLORS, mergeByWorkerCount } from '../utils/chartSeries'

const CARD = 'rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900'
const AXIS_TICK = { fontSize: 12 }
const GRID_STROKE = 'currentColor'
const GRID_CLASS = 'text-slate-200 dark:text-slate-800'

// Groups completed jobs by row_count (their input file's line count), and
// within each group averages jobs that share a worker_count (repeated manual
// runs) down to one point - a line only has one Y per X.
function buildSeriesByRowCount(jobs) {
  const byRowCount = new Map()
  for (const job of jobs) {
    if (job.status !== 'Completed' || job.execution_time_s == null) continue
    if (!byRowCount.has(job.row_count)) byRowCount.set(job.row_count, new Map())
    const byWorkerCount = byRowCount.get(job.row_count)
    if (!byWorkerCount.has(job.worker_count)) byWorkerCount.set(job.worker_count, [])
    byWorkerCount.get(job.worker_count).push(job.execution_time_s)
  }

  return [...byRowCount.entries()]
    .sort(([a], [b]) => a - b)
    .map(([row_count, byWorkerCount], i) => ({
      key: `rows_${row_count}`,
      label: `${row_count.toLocaleString()} rows`,
      color: SERIES_COLORS[i % SERIES_COLORS.length],
      points: [...byWorkerCount.entries()].map(([worker_count, times]) => ({
        worker_count,
        execution_time_s: times.reduce((sum, t) => sum + t, 0) / times.length,
      })),
    }))
}

export default function JobDurationChart({ jobs }) {
  const series = buildSeriesByRowCount(jobs)

  if (series.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
        No completed jobs yet.
      </div>
    )
  }

  const chartData = mergeByWorkerCount(series, 'execution_time_s')

  return (
    <div className={CARD}>
      <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Execution time by worker count</h3>
      <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
        One line per input size (rows), connecting completed jobs across worker counts
      </p>
      <div className="mt-4 h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData}>
            <CartesianGrid stroke={GRID_STROKE} className={GRID_CLASS} strokeDasharray="3 3" />
            <XAxis
              dataKey="worker_count"
              type="number"
              tick={AXIS_TICK}
              allowDecimals={false}
              label={{ value: 'Workers', position: 'insideBottom', offset: -5, fontSize: 12 }}
            />
            <YAxis tick={AXIS_TICK} unit="s" />
            <Tooltip />
            <Legend />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color}
                strokeWidth={2}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
