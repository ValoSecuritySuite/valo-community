import { apiEndpoint, jsonFetch } from './client.js'

function buildQuery(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === '') continue
    search.append(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export const listReports = (params = {}) =>
  jsonFetch(`/reports${buildQuery(params)}`, { label: 'GET /reports' })

export const getReport = (reportId) =>
  jsonFetch(`/reports/${encodeURIComponent(reportId)}`, {
    label: `GET /reports/${reportId}`,
  })

export const listReportKinds = () =>
  jsonFetch('/reports/kinds', { label: 'GET /reports/kinds' })

export const getSchedulerState = () =>
  jsonFetch('/reports/scheduler', { label: 'GET /reports/scheduler' })

export const generateReport = (payload) =>
  jsonFetch('/reports/generate', {
    method: 'POST',
    body: payload,
    label: 'POST /reports/generate',
  })

export const runScheduler = (payload = {}) =>
  jsonFetch('/reports/scheduler/run', {
    method: 'POST',
    body: payload,
    label: 'POST /reports/scheduler/run',
  })

export const deleteReport = (reportId) =>
  jsonFetch(`/reports/${encodeURIComponent(reportId)}`, {
    method: 'DELETE',
    label: `DELETE /reports/${reportId}`,
  })

export async function downloadReport(reportId) {
  const resp = await fetch(
    apiEndpoint(`/reports/${encodeURIComponent(reportId)}/download`),
  )
  if (!resp.ok) {
    throw new Error(
      `Failed to download report ${reportId} (${resp.status})`,
    )
  }
  return resp
}
