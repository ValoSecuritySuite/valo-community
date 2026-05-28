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

export const listProposals = (params = {}) =>
  jsonFetch(`/learning/proposals${buildQuery(params)}`, {
    label: 'GET /learning/proposals',
  })

export const getProposal = (proposalId) =>
  jsonFetch(`/learning/proposals/${encodeURIComponent(proposalId)}`, {
    label: `GET /learning/proposals/${proposalId}`,
  })

export const acceptProposal = (proposalId, body = {}) =>
  jsonFetch(`/learning/proposals/${encodeURIComponent(proposalId)}/accept`, {
    method: 'POST',
    body,
    label: `POST /learning/proposals/${proposalId}/accept`,
  })

export const rejectProposal = (proposalId, body = {}) =>
  jsonFetch(`/learning/proposals/${encodeURIComponent(proposalId)}/reject`, {
    method: 'POST',
    body,
    label: `POST /learning/proposals/${proposalId}/reject`,
  })

export const refreshLearning = () =>
  jsonFetch('/learning/refresh', {
    method: 'POST',
    label: 'POST /learning/refresh',
  })
