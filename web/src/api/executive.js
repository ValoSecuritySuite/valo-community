import { apiEndpoint, jsonFetch } from './client.js'

function buildQuery(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      if (value.length === 0) return
      search.append(key, value.join(','))
      return
    }
    search.append(key, String(value))
  })
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export const getSummary = (params = {}) =>
  jsonFetch(`/executive/summary${buildQuery(params)}`, {
    label: 'GET /executive/summary',
  })

export const getTrends = (params = {}) =>
  jsonFetch(`/executive/trends${buildQuery(params)}`, {
    label: 'GET /executive/trends',
  })

export function exportUrl(params = {}) {
  const finalParams = { window: '30d', format: 'pdf', ...params }
  return apiEndpoint(`/executive/export${buildQuery(finalParams)}`)
}

export async function downloadExport(params = {}) {
  const url = exportUrl(params)
  const resp = await fetch(url)
  if (!resp.ok) {
    let message = `GET /executive/export failed (${resp.status})`
    try {
      const body = await resp.text()
      if (body) message = `${message}: ${body}`
    } catch {
      // keep default
    }
    const err = new Error(message)
    err.status = resp.status
    throw err
  }
  const disposition = resp.headers.get('content-disposition') || ''
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i)
  const filename =
    (filenameMatch && filenameMatch[1]) ||
    `valo-executive-${params.window || '30d'}.${params.format || 'pdf'}`
  const blob = await resp.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(objectUrl), 5_000)
  return { filename, size: blob.size }
}
