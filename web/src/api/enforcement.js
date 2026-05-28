import { jsonFetch } from './client.js'

function buildQuery(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.append(key, String(value))
  })
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export const getEvents = (filters = {}) =>
  jsonFetch(`/enforcement/events${buildQuery(filters)}`, {
    label: 'GET /enforcement/events',
  })

export const getStats = (params = {}) =>
  jsonFetch(`/enforcement/stats${buildQuery(params)}`, {
    label: 'GET /enforcement/stats',
  })

export const getConfig = () =>
  jsonFetch('/enforcement/config', { label: 'GET /enforcement/config' })

export const patchConfig = (patch) =>
  jsonFetch('/enforcement/config', {
    method: 'PATCH',
    body: patch,
    label: 'PATCH /enforcement/config',
  })

export const simulate = (payload) =>
  jsonFetch('/enforcement/simulate', {
    method: 'POST',
    body: payload,
    label: 'POST /enforcement/simulate',
  })
