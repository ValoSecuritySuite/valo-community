// Shared HTTP plumbing reused by all backend-facing modules in this app.

export function apiEndpoint(path) {
  const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  return base ? `${base}${path}` : path
}

export async function readJsonResponse(resp, endpointLabel) {
  const contentType = (resp.headers.get('content-type') || '').toLowerCase()
  const raw = await resp.text()

  if (!raw) {
    return {}
  }

  const trimmed = raw.trim()
  const looksLikeHtml = trimmed.startsWith('<!doctype') || trimmed.startsWith('<html')

  if (looksLikeHtml) {
    throw new Error(
      `Backend returned HTML instead of JSON for ${endpointLabel}. Check VITE_API_BASE_URL or the dev proxy configuration.`,
    )
  }

  try {
    return JSON.parse(raw)
  } catch {
    throw new Error(
      `Failed to parse JSON from ${endpointLabel} (content-type: ${contentType || 'unknown'}).`,
    )
  }
}

function buildErrorFromBody(body, defaultLabel) {
  if (!body) return defaultLabel
  if (typeof body === 'string') return body
  if (typeof body.detail === 'string') return body.detail
  if (body.error && typeof body.error === 'object' && body.error.message) {
    return body.error.message
  }
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  }
  return defaultLabel
}

export async function jsonFetch(path, { method = 'GET', body, label } = {}) {
  const opts = { method }
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' }
    opts.body = JSON.stringify(body)
  }

  const resp = await fetch(apiEndpoint(path), opts)
  const requestLabel = label || `${method} ${path}`

  if (resp.status === 204) {
    return null
  }

  if (!resp.ok) {
    let message = `${requestLabel} failed (${resp.status})`
    let body = null
    try {
      body = await readJsonResponse(resp, requestLabel)
      message = buildErrorFromBody(body, message) || message
    } catch {
      // fall back to the default message
    }
    const err = new Error(message)
    err.status = resp.status
    err.body = body
    err.code = body?.error?.code || null
    err.detail = body?.error?.detail || (body?.detail ?? null)
    throw err
  }

  return readJsonResponse(resp, requestLabel)
}
