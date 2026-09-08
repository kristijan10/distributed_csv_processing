// Fixed-order categorical palette (blue/orange/aqua/yellow/magenta/green) -
// CVD-safe as an ordered set for up to ~4 simultaneous series. Extend only by
// appending, and re-validate if a 5th+ ever shows up on screen at once.
export const SERIES_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300']

// Merges each series' points (keyed by worker_count) into one array, e.g.
// [{ worker_count: 1, series_a: 0.9, series_b: 0.95 }, ...], so recharts can
// render one <Line>/<Bar> per series against a shared X axis.
export function mergeByWorkerCount(series, metricKey) {
  const workerCounts = [...new Set(series.flatMap((s) => s.points.map((p) => p.worker_count)))].sort(
    (a, b) => a - b,
  )
  return workerCounts.map((worker_count) => {
    const row = { worker_count }
    for (const s of series) {
      const point = s.points.find((p) => p.worker_count === worker_count)
      if (point) row[s.key] = point[metricKey]
    }
    return row
  })
}
