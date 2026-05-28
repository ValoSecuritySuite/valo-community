import { jsonFetch } from './client.js'

export const listPolicies = () => jsonFetch('/policies', { label: 'GET /policies' })

export const getPolicy = (policyId) =>
  jsonFetch(`/policies/${encodeURIComponent(policyId)}`, {
    label: `GET /policies/${policyId}`,
  })

export const createPolicy = (policy) =>
  jsonFetch('/policies', { method: 'POST', body: policy, label: 'POST /policies' })

export const updatePolicy = (policyId, policy) =>
  jsonFetch(`/policies/${encodeURIComponent(policyId)}`, {
    method: 'PUT',
    body: policy,
    label: `PUT /policies/${policyId}`,
  })

export const deletePolicy = (policyId) =>
  jsonFetch(`/policies/${encodeURIComponent(policyId)}`, {
    method: 'DELETE',
    label: `DELETE /policies/${policyId}`,
  })

export const validatePolicy = (rawPolicy) =>
  jsonFetch('/policies/validate', {
    method: 'POST',
    body: rawPolicy,
    label: 'POST /policies/validate',
  })

export const evaluatePolicies = (context) =>
  jsonFetch('/policies/evaluate', {
    method: 'POST',
    body: { context },
    label: 'POST /policies/evaluate',
  })

export const reloadPolicies = () =>
  jsonFetch('/policies/reload', { method: 'POST', label: 'POST /policies/reload' })
