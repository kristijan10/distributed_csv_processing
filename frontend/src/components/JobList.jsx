import StatusBadge from './StatusBadge'
import { resultUrl } from '../api'

function formatTime(isoString) {
  return new Date(isoString).toLocaleTimeString()
}

export default function JobList({ jobs }) {
  if (jobs.length === 0) {
    return <p className="empty-state">No jobs yet — upload a CSV to get started.</p>
  }

  return (
    <table className="job-table">
      <thead>
        <tr>
          <th>File</th>
          <th>Workers</th>
          <th>Rows</th>
          <th>Status</th>
          <th>Created</th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.id}>
            <td>{job.original_filename}</td>
            <td>{job.worker_count}</td>
            <td>{job.row_count}</td>
            <td>
              <StatusBadge status={job.status} />
              {job.status === 'Failed' && job.error_message && (
                <p className="error-text">{job.error_message}</p>
              )}
            </td>
            <td>{formatTime(job.created_at)}</td>
            <td>
              {job.status === 'Completed' ? (
                <a href={resultUrl(job.id)} download>
                  Download
                </a>
              ) : (
                '—'
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
