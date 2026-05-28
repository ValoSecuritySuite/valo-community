import { jsonFetch } from './client.js'

function buildQuery(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === '') continue
    search.append(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export const listOutcomes = (params = {}) =>
  jsonFetch(`/outcomes${buildQuery(params)}`, { label: 'GET /outcomes' })

export const outcomeStats = (params = {}) =>
  jsonFetch(`/outcomes/stats${buildQuery(params)}`, {
    label: 'GET /outcomes/stats',
  })

export const labelOutcome = (traceId, payload) =>
  jsonFetch(`/outcomes/${encodeURIComponent(traceId)}/label`, {
    method: 'POST',
    body: payload,
    label: `POST /outcomes/${traceId}/label`,
  })

export const ingestOutcome = (envelope) =>
  jsonFetch('/outcomes/ingest', {
    method: 'POST',
    body: envelope,
    label: 'POST /outcomes/ingest',
  })

export const OUTCOME_LABELS = [
  'true_positive',
  'false_positive',
  'benign_block',
  'malicious_allow',
  'suppressed',
  'dismissed',
]
