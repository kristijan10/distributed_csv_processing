const STATUS_CLASS = {
  Pending: 'status-pending',
  Running: 'status-running',
  Completed: 'status-completed',
  Failed: 'status-failed',
}

export default function StatusBadge({ status }) {
  const className = STATUS_CLASS[status] ?? 'status-pending'
  return <span className={`status-badge ${className}`}>{status}</span>
}
