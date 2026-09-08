const API_BASE = 'http://localhost:8000'

async function handleResponse(res) {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new Error(detail)
  }
  return res.json()
}

export async function createJob(file, workerCount) {
  const form = new FormData()
  form.append('file', file)
  form.append('worker_count', String(workerCount))
  const res = await fetch(`${API_BASE}/api/jobs`, { method: 'POST', body: form })
  return handleResponse(res)
}

export async function runJob(jobId) {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/run`, { method: 'POST' })
  return handleResponse(res)
}

export async function getJob(jobId) {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`)
  return handleResponse(res)
}

export async function listJobs() {
  const res = await fetch(`${API_BASE}/api/jobs`)
  return handleResponse(res)
}

export async function getJobWorkers(jobId) {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/workers`)
  return handleResponse(res)
}

export function resultUrl(jobId) {
  return `${API_BASE}/api/jobs/${jobId}/result`
}

export async function getSweepModes() {
  const res = await fetch(`${API_BASE}/api/metrics/sweep/modes`)
  return handleResponse(res)
}

export async function getSweepMetrics(mode) {
  const res = await fetch(`${API_BASE}/api/metrics/sweep?mode=${encodeURIComponent(mode)}`)
  return handleResponse(res)
}
