const BADGE_STYLES = {
  Pending: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  Running: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  Completed: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  Failed: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300',
}

const DOT_STYLES = {
  Pending: 'bg-slate-400',
  Running: 'bg-blue-500 animate-pulse',
  Completed: 'bg-emerald-500',
  Failed: 'bg-red-500',
}

export default function StatusBadge({ status }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        BADGE_STYLES[status] ?? BADGE_STYLES.Pending
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${DOT_STYLES[status] ?? DOT_STYLES.Pending}`} />
      {status}
    </span>
  )
}
