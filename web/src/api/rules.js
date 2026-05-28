import { jsonFetch } from './client.js'

export const getRules = () => jsonFetch('/rules', { label: 'GET /rules' })

export const evaluateRules = (context) =>
  jsonFetch('/rules/evaluate', {
    method: 'POST',
    body: { context },
    label: 'POST /rules/evaluate',
  })

export const reloadRules = () =>
  jsonFetch('/rules/reload', { method: 'POST', label: 'POST /rules/reload' })
