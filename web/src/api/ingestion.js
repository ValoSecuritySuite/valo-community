import { jsonFetch } from './client.js'

export const normalizeAndIngest = (payload) =>
  jsonFetch('/ingest/normalize', {
    method: 'POST',
    body: payload,
    label: 'POST /ingest/normalize',
  })
