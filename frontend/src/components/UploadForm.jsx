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
    <form
      className="upload-form rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      onSubmit={handleSubmit}
    >
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end">
        <div className="flex flex-1 flex-col gap-1.5">
          <label htmlFor="csv-file" className="text-sm font-medium text-slate-700 dark:text-slate-300">
            CSV file
          </label>
          <div className="flex items-center gap-3">
            <label
              htmlFor="csv-file"
              className="cursor-pointer rounded-md border border-slate-300 bg-slate-50 px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            >
              Choose file
            </label>
            <span className="truncate text-sm text-slate-500 dark:text-slate-400">
              {file ? file.name : 'No file chosen'}
            </span>
          </div>
          <input
            id="csv-file"
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={submitting}
            className="sr-only"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="worker-count" className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Worker count
          </label>
          <input
            id="worker-count"
            type="number"
            min={1}
            max={32}
            value={workerCount}
            onChange={(e) => setWorkerCount(parseInt(e.target.value, 10))}
            disabled={submitting}
            className="w-24 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-white"
          />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-indigo-600 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? 'Submitting…' : 'Upload & Run'}
        </button>
      </div>

      {formError && <p className="error-text mt-3 text-sm text-red-600 dark:text-red-400">{formError}</p>}
    </form>
  )
}
