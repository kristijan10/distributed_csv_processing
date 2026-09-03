import { useCallback, useEffect, useState } from 'react'
import UploadForm from './components/UploadForm'
import JobList from './components/JobList'
import PipelineOverview from './components/PipelineOverview'
import { createJob, runJob, listJobs } from './api'

const POLL_INTERVAL_MS = 3000

function App() {
  const [jobs, setJobs] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [listError, setListError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const data = await listJobs()
      setJobs(data)
      setListError(null)
    } catch (err) {
      setListError(err.message)
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [refresh])

  async function handleSubmit(file, workerCount) {
    setSubmitting(true)
    try {
      const job = await createJob(file, workerCount)
      await runJob(job.id)
      await refresh()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="app mx-auto max-w-4xl px-6 py-12 sm:py-16">
      <header className="mb-10">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl dark:text-white">
          Distributed Batch Processing Platform
        </h1>
        <p className="mt-2 max-w-xl text-slate-500 dark:text-slate-400">
          Upload a CSV, choose how many worker pods to split it across, and watch it run on the local
          Kubernetes cluster.
        </p>
      </header>

      <PipelineOverview />

      <div className="mt-8">
        <UploadForm onSubmit={handleSubmit} submitting={submitting} />
      </div>

      <section className="jobs-section mt-12">
        <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">Jobs</h2>
        {listError && (
          <p className="error-text mb-4 text-sm text-red-600 dark:text-red-400">
            Could not load jobs: {listError}
          </p>
        )}
        <JobList jobs={jobs} />
      </section>
    </main>
  )
}

export default App
