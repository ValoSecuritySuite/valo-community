import { jsonFetch } from './client.js'

export const getSettings = () => jsonFetch('/settings', { label: 'GET /settings' })

export const patchSettings = (patch) =>
  jsonFetch('/settings', {
    method: 'PATCH',
    body: patch,
    label: 'PATCH /settings',
  })
