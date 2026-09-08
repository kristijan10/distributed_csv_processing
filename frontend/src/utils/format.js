export function formatTime(isoString) {
  if (!isoString) return null
  return new Date(isoString).toLocaleTimeString()
}

export function formatDuration(startIso, endIso) {
  if (!startIso || !endIso) return null
  const ms = new Date(endIso) - new Date(startIso)
  if (!Number.isFinite(ms) || ms < 0) return null
  return formatSeconds(ms / 1000)
}

export function formatSeconds(seconds) {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null

  const totalSeconds = Math.round(seconds)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60

  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`
  if (minutes > 0) return `${minutes}m ${secs}s`
  if (totalSeconds > 0) return `${secs}s`
  return `${seconds.toFixed(2)}s`
}
