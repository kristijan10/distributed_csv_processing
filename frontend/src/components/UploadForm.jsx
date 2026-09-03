import { useRef, useState } from 'react'

export default function UploadForm({ onSubmit, submitting }) {
  const fileInputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [workerCount, setWorkerCount] = useState(3)
  const [formError, setFormError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    setFormError(null)

    if (!file) {
      setFormError('Choose a CSV file first.')
      return
    }
    if (!Number.isInteger(workerCount) || workerCount < 1) {
      setFormError('Worker count must be a positive integer.')
      return
    }

    try {
      await onSubmit(file, workerCount)
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (err) {
      setFormError(err.message)
    }
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit}>
      <div className="field">
        <label htmlFor="csv-file">CSV file</label>
        <input
          id="csv-file"
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          disabled={submitting}
        />
      </div>

      <div className="field">
        <label htmlFor="worker-count">Worker count</label>
        <input
          id="worker-count"
          type="number"
          min={1}
          max={32}
          value={workerCount}
          onChange={(e) => setWorkerCount(parseInt(e.target.value, 10))}
          disabled={submitting}
        />
      </div>

      <button type="submit" disabled={submitting}>
        {submitting ? 'Submitting…' : 'Upload & Run'}
      </button>

      {formError && <p className="error-text">{formError}</p>}
    </form>
  )
}
