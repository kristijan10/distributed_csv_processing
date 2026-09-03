import StatusBadge from './StatusBadge'
import { resultUrl } from '../api'

function formatTime(isoString) {
  return new Date(isoString).toLocaleTimeString()
}

export default function JobList({ jobs }) {
  if (jobs.length === 0) {
    return (
      <p className="empty-state rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
        No jobs yet — upload a CSV to get started.
      </p>
    )
  }

  return (
    <div className="overflow-hidden overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
      <table className="job-table w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-500 dark:bg-slate-900 dark:text-slate-400">
          <tr>
            <th className="px-4 py-3 font-medium">File</th>
            <th className="px-4 py-3 font-medium">Workers</th>
            <th className="px-4 py-3 font-medium">Rows</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Created</th>
            <th className="px-4 py-3 font-medium">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {jobs.map((job) => (
            <tr key={job.id} className="hover:bg-slate-50 dark:hover:bg-slate-900/60">
              <td className="px-4 py-3 text-slate-900 dark:text-white">{job.original_filename}</td>
              <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{job.worker_count}</td>
              <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{job.row_count}</td>
              <td className="px-4 py-3">
                <StatusBadge status={job.status} />
                {job.status === 'Failed' && job.error_message && (
                  <p className="error-text mt-1.5 max-w-xs text-xs text-red-600 dark:text-red-400">
                    {job.error_message}
                  </p>
                )}
              </td>
              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{formatTime(job.created_at)}</td>
              <td className="px-4 py-3">
                {job.status === 'Completed' ? (
                  <a
                    href={resultUrl(job.id)}
                    download
                    className="font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400"
                  >
                    Download
                  </a>
                ) : (
                  <span className="text-slate-300 dark:text-slate-600">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
