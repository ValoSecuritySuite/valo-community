export const SEVERITY_ORDER = ['low', 'medium', 'high', 'critical']

export function formatNumber(value) {
  const parsed = Number(value)
  if (Number.isNaN(parsed)) return '0'
  return parsed.toLocaleString()
}

export function formatScore(value) {
  const parsed = Number(value)
  if (Number.isNaN(parsed)) return '0.00'
  return parsed.toFixed(2)
}

export function formatDate(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleString()
}

export function formatRelativeTime(value, nowMs = Date.now()) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  const diff = Math.max(0, Math.floor((nowMs - parsed.getTime()) / 1000))
  if (diff < 5) return 'just now'
  if (diff < 60) return `${diff}s ago`
  const minutes = Math.floor(diff / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function normalizeSeverity(value) {
  const normalized = String(value || '').toLowerCase()
  if (normalized === 'minimal') return 'low'
  if (SEVERITY_ORDER.includes(normalized)) return normalized
  return 'low'
}

export function clipText(value, maxLen = 130) {
  const text = String(value || '')
  if (text.length <= maxLen) return text
  return `${text.slice(0, maxLen - 1)}...`
}

export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(String(text || ''))
    return true
  } catch {
    return false
  }
}

export function decisionLabel(decision) {
  const value = String(decision || '').toLowerCase()
  if (value === 'deny') return 'Deny'
  if (value === 'warn') return 'Warn'
  if (value === 'allow') return 'Allow'
  return value || 'unknown'
}
