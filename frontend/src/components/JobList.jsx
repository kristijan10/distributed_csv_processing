import { useState } from 'react'
import StatusBadge from './StatusBadge'
import JobDetailModal from './JobDetailModal'
import { resultUrl } from '../api'
import { formatSeconds } from '../utils/format'

export default function JobList({ jobs }) {
  const [selectedJobId, setSelectedJobId] = useState(null)
  const selectedJob = jobs.find((job) => job.id === selectedJobId) ?? null

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
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Workers</th>
            <th className="px-4 py-3 font-medium">Execution time</th>
            <th className="px-4 py-3 font-medium">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {jobs.map((job) => (
            <tr
              key={job.id}
              onClick={() => setSelectedJobId(job.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setSelectedJobId(job.id)
                }
              }}
              tabIndex={0}
              role="button"
              aria-label={`View details for ${job.original_filename}`}
              className="cursor-pointer hover:bg-slate-50 focus:bg-slate-50 focus:outline-none dark:hover:bg-slate-900/60 dark:focus:bg-slate-900/60"
            >
              <td className="px-4 py-3 text-slate-900 dark:text-white">{job.original_filename}</td>
              <td className="px-4 py-3">
                <StatusBadge status={job.status} />
                {job.status === 'Failed' && job.error_message && (
                  <p className="error-text mt-1.5 max-w-xs text-xs text-red-600 dark:text-red-400">
                    {job.error_message}
                  </p>
                )}
              </td>
              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{job.worker_count}</td>
              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                {formatSeconds(job.execution_time_s) ?? (
                  <span className="text-slate-300 dark:text-slate-600">—</span>
                )}
              </td>
              <td className="px-4 py-3">
                {job.status === 'Completed' ? (
                  <a
                    href={resultUrl(job.id)}
                    download
                    onClick={(e) => e.stopPropagation()}
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
      {selectedJob && <JobDetailModal job={selectedJob} onClose={() => setSelectedJobId(null)} />}
    </div>
  )
}
