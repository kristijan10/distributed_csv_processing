import { useCallback, useEffect, useState } from 'react'
import UploadForm from './components/UploadForm'
import JobList from './components/JobList'
import { createJob, runJob, listJobs } from './api'
import './App.css'

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
    <main className="app">
      <header>
        <h1>Distributed Batch Processing Platform</h1>
        <p className="subtitle">
          Upload a CSV, choose how many worker pods to split it across, and watch it run on the
          local Kubernetes cluster.
        </p>
      </header>

      <UploadForm onSubmit={handleSubmit} submitting={submitting} />

      <section className="jobs-section">
        <h2>Jobs</h2>
        {listError && <p className="error-text">Could not load jobs: {listError}</p>}
        <JobList jobs={jobs} />
      </section>
    </main>
  )
}

export default App
